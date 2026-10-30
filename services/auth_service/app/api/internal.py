"""Internal /internal/auth routes (rest_api_notes.md Part 4). Never routed by the gateway."""

from fastapi import APIRouter, Request

from app import accounts
from app.dependencies import DbSession
from app.schemas import ServiceTokenRequest, ServiceTokenResponse

router = APIRouter(prefix="/internal/auth", tags=["internal"])


@router.post(
    "/service-token",
    response_model=ServiceTokenResponse,
    summary="Issue a scoped service token (client credentials)",
)
def service_token(body: ServiceTokenRequest, session: DbSession, request: Request) -> ServiceTokenResponse:
    requested = body.scope.split() if body.scope else None
    scopes = accounts.authenticate_client(session, body.client_id, body.client_secret, requested)
    token, expires_in = request.app.state.token_issuer.service_token(body.client_id, scopes)
    return ServiceTokenResponse(access_token=token, expires_in=expires_in, scope=" ".join(scopes))
