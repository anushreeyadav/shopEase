"""Internal routes for order_service (rest_api_notes.md Part 4). Never routed by the gateway.

order_service never touches product_db: prices, availability and every stock change go
through these endpoints, each requiring a service token with the listed scope.
"""

from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app import stock
from app.dependencies import DbSession, SettingsDep
from app.schemas import PriceCheckRequest, PriceCheckResponse, ReservationRequest, ReservationResponse
from shopease_shared.security import Principal, require_scope

router = APIRouter(tags=["internal"])

ReadProducts = Annotated[Principal, Depends(require_scope("products:read"))]
ReserveStock = Annotated[Principal, Depends(require_scope("inventory:reserve"))]


class ReleaseResponse(BaseModel):
    order_id: UUID
    released_items: int


@router.post(
    "/internal/products/price-check",
    response_model=PriceCheckResponse,
    summary="Current prices and availability (scope products:read)",
)
def price_check(body: PriceCheckRequest, service: ReadProducts, session: DbSession) -> PriceCheckResponse:
    return stock.price_check(session, body.product_ids)


@router.post(
    "/internal/reservations",
    status_code=201,
    response_model=ReservationResponse,
    summary="Reserve stock for an order, all or nothing (scope inventory:reserve)",
    responses={200: {"model": ReservationResponse, "description": "Replay: this order already holds the same reservation"}},
)
def reserve_stock(
    body: ReservationRequest, service: ReserveStock, session: DbSession, settings: SettingsDep, response: Response
) -> ReservationResponse:
    ttl = timedelta(seconds=body.ttl_seconds) if body.ttl_seconds else timedelta(minutes=settings.reservation_ttl_minutes)
    reservation, created = stock.reserve(session, body.order_id, body.items, ttl, actor=service.subject)
    if not created:
        response.status_code = 200
    return reservation


@router.post(
    "/internal/reservations/{order_id}/confirm",
    response_model=ReservationResponse,
    summary="Deduct reserved stock after payment; idempotent (scope inventory:reserve)",
)
def confirm_reservation(order_id: UUID, service: ReserveStock, session: DbSession) -> ReservationResponse:
    return stock.confirm(session, order_id, actor=service.subject)


@router.post(
    "/internal/reservations/{order_id}/release",
    response_model=ReleaseResponse,
    summary="Return reserved stock; idempotent, 0 when nothing is held (scope inventory:reserve)",
)
def release_reservation(order_id: UUID, service: ReserveStock, session: DbSession) -> ReleaseResponse:
    return ReleaseResponse(order_id=order_id, released_items=stock.release(session, order_id, actor=service.subject))
