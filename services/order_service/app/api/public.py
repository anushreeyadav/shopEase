"""Public /api/orders routes (rest_api_notes.md §3.5). Reached through the gateway.

Customers see and change only their own orders; someone else's order answers 404.
Admins may list and read all orders and set fulfilment statuses.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from app import orders
from app.clients import ServiceClients
from app.dependencies import DbSession, SettingsDep
from app.models import OrderStatus
from app.schemas import OrderCreate, OrderRead, OrderSummary, Page, StatusUpdate
from shopease_shared.security import AdminUser, CurrentUser, bearer_token

router = APIRouter(prefix="/api/orders", tags=["orders"])


def get_clients(request: Request) -> ServiceClients:
    return request.app.state.clients


Clients = Annotated[ServiceClients, Depends(get_clients)]
IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=8, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$",
           description="A unique value (e.g. a UUID) per intended order; reuse it on retries"),
]


@router.post("", status_code=201, response_model=OrderRead, summary="Place an order (requires Idempotency-Key)")
def create_order(
    body: OrderCreate,
    user: CurrentUser,
    key: IdempotencyKey,
    session: DbSession,
    settings: SettingsDep,
    clients: Clients,
    request: Request,
    response: Response,
) -> OrderRead:
    order, created = orders.create_order(
        session, clients, settings, user, bearer_token(request), body, key
    )
    response.headers["Location"] = f"/api/orders/{order.id}"
    if not created:
        response.headers["Idempotent-Replayed"] = "true"
    return orders.to_read(order)


@router.get("", response_model=Page[OrderSummary], summary="Order history (own orders; admins: all)")
def list_orders(
    user: CurrentUser,
    session: DbSession,
    status: OrderStatus | None = None,
    user_id: Annotated[UUID | None, Query(description="Admins only")] = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    sort: Literal["created_at", "-created_at"] = "-created_at",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[OrderSummary]:
    items, total = orders.list_orders(
        session, user, user_id=user_id, status=status, created_from=created_from, created_to=created_to,
        sort=sort, limit=limit, offset=offset,
    )
    return Page[OrderSummary](items=items, total=total, limit=limit, offset=offset)


@router.get("/{order_id}", response_model=OrderRead, summary="Order details with status history")
def get_order(order_id: UUID, user: CurrentUser, session: DbSession) -> OrderRead:
    return orders.to_read(orders.get_visible_order(session, order_id, user))


@router.post("/{order_id}/cancel", response_model=OrderRead, summary="Cancel an unpaid order (owner or admin)")
def cancel_order(order_id: UUID, user: CurrentUser, session: DbSession, clients: Clients) -> OrderRead:
    return orders.to_read(orders.cancel_order(session, clients, order_id, user))


@router.patch("/{order_id}/status", response_model=OrderRead, summary="Set fulfilment status (admin)")
def update_status(order_id: UUID, body: StatusUpdate, admin: AdminUser, session: DbSession) -> OrderRead:
    return orders.to_read(orders.set_fulfilment_status(session, order_id, body.status, admin))
