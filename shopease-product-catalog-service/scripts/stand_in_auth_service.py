"""A stand-in for the Authentication Service's POST /api/auth/verify-token, served over HTTP.

    python -m uvicorn scripts.stand_in_auth_service:app --host 127.0.0.1 --port 8099

Used only for API tests that need an ADMIN token, because the live Authentication Service has no
ADMIN account. It is the StandInAuthService of tests/test_auth_integration.py, which applies the
same rules as shopease-auth-service (HS256 signature, required claims, user lookup, inactive users),
with a test-only signing key. Tokens are issued with issue_token() by the test runner.

It never runs against, replaces or changes the real Authentication Service.
"""

import httpx
from fastapi import FastAPI, Request, Response

from tests.test_auth_integration import ADMIN_ID, CUSTOMER_ID, StandInAuthService

stand_in = StandInAuthService()
app = FastAPI(title="Stand-in Authentication Service (tests only)", docs_url=None, redoc_url=None)


@app.post("/api/auth/verify-token")
async def verify_token(request: Request) -> Response:
    forwarded = httpx.Request("POST", str(request.url), headers={
        "Authorization": request.headers.get("Authorization", "")})
    answer = stand_in.handle(forwarded)
    return Response(content=answer.content, status_code=answer.status_code, media_type="application/json")


def issue_token(role: str) -> str:
    """A token the stand-in accepts: role "ADMIN" or "USER" (the Authentication Service's customer role)."""
    return stand_in.issue(ADMIN_ID if role == "ADMIN" else CUSTOMER_ID)
