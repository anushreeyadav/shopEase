"""Live check of the JWT integration with the running ShopEase Authentication Service.

    python -m scripts.auth_integration_check

Runs against the real services, with no stand-ins:
  - the Authentication Service at AUTH_SERVICE_VERIFY_URL (from .env), and
  - the running Catalog Service at CATALOG_BASE_URL (default http://127.0.0.1:8006).

Nothing is created or changed in either service. Only GET requests and refused writes are sent
to the Catalog Service. No account is registered in the Authentication Service.

Tokens for real accounts. Valid-token checks need an account to log in with. They run only if
these environment variables are set, and are skipped otherwise. Passwords are never printed.
  CHECK_CUSTOMER_EMAIL / CHECK_CUSTOMER_PASSWORD   an account with role USER
  CHECK_ADMIN_EMAIL    / CHECK_ADMIN_PASSWORD      an account with role ADMIN
"""

import base64
import json
import os
import secrets
import sys
import time
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from jose import jwt

from app.core.config import get_settings
from app.core.security import verify_access_token

CATALOG = os.environ.get("CATALOG_BASE_URL", "http://127.0.0.1:8006").rstrip("/")
results: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def expect(name: str, response: httpx.Response, status: int, body: dict | None = None) -> None:
    ok = response.status_code == status and (body is None or response.json() == body)
    check(name, ok, f"HTTP {response.status_code} {response.text[:80]}")


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def forged(lifetime: int, role: str = "ADMIN", sub: str = "1") -> str:
    """Well-formed HS256 token with the real claim names, signed with a random key."""
    now = int(time.time())
    return jwt.encode({"sub": sub, "role": role, "iat": now, "exp": now + lifetime},
                      secrets.token_urlsafe(48), algorithm="HS256")


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login(auth_base: str, email_var: str, password_var: str) -> tuple[str, dict] | None:
    email, password = os.environ.get(email_var), os.environ.get(password_var)
    if not email or not password:
        print(f"[SKIP] {email_var} / {password_var} not set")
        return None
    response = httpx.post(f"{auth_base}/api/auth/login", json={"email": email, "password": password}, timeout=10)
    if response.status_code != 200:
        check(f"login with {email_var}", False, f"HTTP {response.status_code}")
        return None
    data = response.json()
    return data["access_token"], data["user"]


def main() -> int:
    settings = get_settings()
    verify_url = str(settings.auth_service_verify_url)
    parts = urlsplit(verify_url)
    auth_base = f"{parts.scheme}://{parts.netloc}"
    print(f"Authentication Service: {verify_url}")
    print(f"Catalog Service:        {CATALOG}\n")

    with httpx.Client(timeout=10) as http:
        print("== Services")
        expect("Authentication Service /health", http.get(f"{auth_base}/health"), 200)
        expect("Catalog Service /health", http.get(f"{CATALOG}/health"), 200)

        print("\n== The real Authentication Service, called directly")
        expect("verify-token without a token -> 401", http.post(verify_url), 401)
        expect("verify-token with a forged token -> 401", http.post(verify_url, headers=bearer(forged(1800))), 401)
        expect("verify-token with an expired forged token -> 401",
               http.post(verify_url, headers=bearer(forged(-60))), 401)

        print("\n== Catalog Service: missing and invalid tokens")
        unauthorized = {"detail": "Could not validate credentials"}
        body = {"name": "auth-check-must-not-be-created"}
        expect("no token, browse products -> 200", http.get(f"{CATALOG}/api/products"), 200)
        expect("no token, browse categories -> 200", http.get(f"{CATALOG}/api/categories"), 200)
        expect("no token, create category -> 401", http.post(f"{CATALOG}/api/categories", json=body), 401, unauthorized)
        expect("no token, inventory -> 401", http.get(f"{CATALOG}/api/inventory/low-stock"), 401, unauthorized)
        expect("Basic credentials -> 401",
               http.post(f"{CATALOG}/api/categories", json=body, headers={"Authorization": "Basic dTpw"}),
               401, unauthorized)
        expect("garbage token -> 401",
               http.post(f"{CATALOG}/api/categories", json=body, headers=bearer("not-a-jwt")), 401, unauthorized)
        unsigned = f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64({'sub': '1', 'role': 'ADMIN'})}."
        expect("alg none token claiming ADMIN -> 401",
               http.post(f"{CATALOG}/api/categories", json=body, headers=bearer(unsigned)), 401, unauthorized)
        expect("forged HS256 token claiming ADMIN -> 401 (rejected by the Authentication Service)",
               http.post(f"{CATALOG}/api/categories", json=body, headers=bearer(forged(1800))), 401, unauthorized)
        expect("expired forged token -> 401",
               http.get(f"{CATALOG}/api/inventory/low-stock", headers=bearer(forged(-60))), 401, unauthorized)
        expect("forged token on a public route -> 401, not ignored",
               http.get(f"{CATALOG}/api/products", headers=bearer(forged(1800))), 401, unauthorized)

        print("\n== Catalog Service: real accounts")
        customer = login(auth_base, "CHECK_CUSTOMER_EMAIL", "CHECK_CUSTOMER_PASSWORD")
        if customer:
            token, user = customer
            check("customer account has role USER", user.get("role") == "USER", f"role {user.get('role')!r}")
            expect("customer, browse products -> 200", http.get(f"{CATALOG}/api/products", headers=bearer(token)), 200)
            expect("customer, browse categories -> 200",
                   http.get(f"{CATALOG}/api/categories", headers=bearer(token)), 200)
            expect("customer, include_inactive -> 403",
                   http.get(f"{CATALOG}/api/products", params={"include_inactive": True}, headers=bearer(token)),
                   403, {"detail": "Admin role required"})
            expect("customer, create category -> 403",
                   http.post(f"{CATALOG}/api/categories", json=body, headers=bearer(token)),
                   403, {"detail": "Admin role required"})
            expect("customer, inventory -> 403",
                   http.get(f"{CATALOG}/api/inventory/low-stock", headers=bearer(token)),
                   403, {"detail": "Admin role required"})
        admin = login(auth_base, "CHECK_ADMIN_EMAIL", "CHECK_ADMIN_PASSWORD")
        if admin:
            token, user = admin
            check("admin account has role ADMIN", user.get("role") == "ADMIN", f"role {user.get('role')!r}")
            expect("admin, inventory low-stock -> 200",
                   http.get(f"{CATALOG}/api/inventory/low-stock", headers=bearer(token)), 200)
            expect("admin, include_inactive -> 200",
                   http.get(f"{CATALOG}/api/products", params={"include_inactive": True}, headers=bearer(token)), 200)

    print("\n== Authentication Service unreachable (real connection to a closed port)")
    closed = httpx.Client(timeout=2, follow_redirects=False)
    original = settings.auth_service_verify_url
    try:
        object.__setattr__(settings, "auth_service_verify_url", "http://127.0.0.1:9/api/auth/verify-token")
        try:
            verify_access_token(forged(1800), closed)
            check("verification with the Authentication Service down -> refused", False, "token was accepted")
        except HTTPException as exc:
            check("verification with the Authentication Service down -> 503, refused", exc.status_code == 503,
                  f"HTTP {exc.status_code} {exc.detail}")
    finally:
        object.__setattr__(settings, "auth_service_verify_url", original)
        closed.close()

    passed = sum(results)
    print(f"\n{passed} passed, {len(results) - passed} failed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
