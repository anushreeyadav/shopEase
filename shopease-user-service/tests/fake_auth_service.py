"""A stand-in for the ShopEase Authentication Service, for the security audit tests.

It follows the real service's contract (read from shopease-auth-service): HS256 access tokens
with claims sub (user ID as a decimal string), role, iat and exp, and
POST /api/auth/verify-token, which takes only the Authorization header and answers
  200 {"valid": true, "user": {"id", "full_name", "email", "role", "is_active"}}
  401 {"detail": "Could not validate credentials"}   bad signature, malformed, expired, unknown user
  403 {"detail": "Inactive user"}
Tokens are real signed JWTs, so expiry and tampering are checked here as the real service would.
The signing key exists only in this test module; the User Service never sees it.
"""

import base64
import copy
import hashlib
import hmac
import json
import time

import httpx

VERIFY_PATH = "/api/auth/verify-token"
_SIGNING_KEY = b"test-only-signing-key-held-by-the-fake-auth-service"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_token(claims: dict, *, key: bytes = _SIGNING_KEY, alg: str = "HS256") -> str:
    header = _b64(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    payload = _b64(json.dumps(claims).encode())
    signature = _b64(hmac.new(key, f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


class FakeAuthService:
    def __init__(self, users: dict[int, dict]):
        self.users = users
        self.requests: list[httpx.Request] = []

    def issue_token(self, user_id: int, *, expires_in: int = 1800) -> str:
        now = int(time.time())
        role = self.users[user_id]["role"] if user_id in self.users else "USER"
        return sign_token({"sub": str(user_id), "role": role, "iat": now, "exp": now + expires_in})

    def _decode(self, token: str) -> dict | None:
        try:
            header, payload, signature = token.split(".")
            if json.loads(_unb64(header)).get("alg") != "HS256":
                return None
            expected = _b64(hmac.new(_SIGNING_KEY, f"{header}.{payload}".encode(), hashlib.sha256).digest())
            if not hmac.compare_digest(signature, expected):
                return None
            claims = json.loads(_unb64(payload))
        except (ValueError, TypeError, json.JSONDecodeError):
            return None
        if not isinstance(claims.get("exp"), int) or claims["exp"] <= time.time():
            return None
        return claims

    def verify(self, authorization: str | None) -> tuple[int, dict]:
        """The verify-token logic: returns (status code, JSON body)."""
        unauthorized = (401, {"detail": "Could not validate credentials"})
        if not authorization or not authorization.startswith("Bearer "):
            return unauthorized
        claims = self._decode(authorization.removeprefix("Bearer "))
        sub = claims.get("sub") if claims else None
        if not isinstance(sub, str) or not sub.isdigit() or int(sub) not in self.users:
            return unauthorized
        user = self.users[int(sub)]
        if not user["is_active"]:
            return 403, {"detail": "Inactive user"}
        return 200, {"valid": True, "user": {"id": int(sub), **user}}

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method != "POST" or request.url.path != VERIFY_PATH:
            return httpx.Response(404, json={"detail": "Not Found"})
        status_code, body = self.verify(request.headers.get("Authorization"))
        return httpx.Response(status_code, json=body)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    def snapshot(self) -> dict:
        return copy.deepcopy(self.users)


def default_users() -> dict[int, dict]:
    return {
        7: {"full_name": "Asha Rao", "email": "asha.test@example.com", "role": "USER", "is_active": True},
        8: {"full_name": "Ravi Kumar", "email": "ravi.test@example.com", "role": "USER", "is_active": True},
        9: {"full_name": "Inactive Person", "email": "inactive.test@example.com", "role": "USER", "is_active": False},
    }
