"""Concurrency tests on a real MySQL (row locks don't exist in SQLite).

Skipped unless SHOPEASE_MYSQL_TESTS=1, with the same environment variables as the service
(see docs/database_setup.md). They create their own products with unique SKUs and only add
rows; they never delete data. Each thread uses its own connection and transaction, calling
the same functions the API routes call.
"""

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select

from app import stock
from app.config import Settings
from app.db import Database
from app.models import Inventory, InventoryMovement, MovementReason, Product
from app.schemas import ReservationItemIn
from shopease_shared import ShopEaseError

pytestmark = pytest.mark.skipif(
    os.getenv("SHOPEASE_MYSQL_TESTS") != "1", reason="set SHOPEASE_MYSQL_TESTS=1 to run"
)

SERVICE_DIR = Path(__file__).resolve().parents[1]
TTL = timedelta(minutes=15)


@pytest.fixture(scope="module")
def db():
    settings = Settings()
    engine = create_engine(settings.migration_database_url)
    with engine.begin() as connection:
        config = Config(str(SERVICE_DIR / "alembic.ini"), attributes={"connection": connection, "configure_logger": False})
        command.upgrade(config, "head")
    engine.dispose()
    # The service's own engine configuration, with a pool big enough for the races below.
    database = Database.from_settings(Settings(DB_POOL_SIZE=40))
    yield database
    database.dispose()


def make_product(db: Database, stock_level: int) -> uuid.UUID:
    with db.session() as session:
        product = Product(id=uuid.uuid4(), sku=f"CONC-{uuid.uuid4().hex[:12]}".upper(), name="Concurrency", price=1)
        session.add(product)
        inventory = Inventory(product_id=product.id, quantity_on_hand=stock_level)
        session.add(inventory)
        stock.record_movement(session, inventory, MovementReason.RESTOCK, stock_level, 0, "test")
        session.commit()
        return product.id


def levels(db: Database, product_id: uuid.UUID) -> tuple[int, int]:
    with db.session() as session:
        inv = session.get(Inventory, product_id)
        return inv.quantity_on_hand, inv.quantity_reserved


def assert_ledger(db: Database, product_id: uuid.UUID) -> None:
    on_hand, reserved = levels(db, product_id)
    assert 0 <= reserved <= on_hand
    with db.session() as session:
        sums = session.execute(
            select(func.sum(InventoryMovement.quantity_change), func.sum(InventoryMovement.reserved_change)).where(
                InventoryMovement.product_id == product_id
            )
        ).one()
    assert (int(sums[0]), int(sums[1] or 0)) == (on_hand, reserved)


def race(workers: int, task):
    """Start every task at the same moment and collect results or error codes."""
    barrier = threading.Barrier(workers)

    def run(i):
        barrier.wait()
        try:
            return task(i)
        except ShopEaseError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run, range(workers)))


def reserve(db, order_id, items):
    with db.session() as session:
        response, created = stock.reserve(
            session, order_id, [ReservationItemIn(product_id=p, quantity=q) for p, q in items], TTL, "svc:test"
        )
        return "CREATED" if created else "REPLAYED"


def test_thirty_buyers_ten_units_never_oversell(db):
    product = make_product(db, 10)
    results = race(30, lambda i: reserve(db, uuid.uuid4(), [(product, 1)]))
    assert results.count("CREATED") == 10, results
    assert results.count("OUT_OF_STOCK") == 20, results
    assert levels(db, product) == (10, 10)
    assert_ledger(db, product)


def test_multi_item_orders_in_opposite_order_do_not_deadlock_or_oversell(db):
    a, b = make_product(db, 8), make_product(db, 8)
    results = race(16, lambda i: reserve(db, uuid.uuid4(), [(a, 1), (b, 1)] if i % 2 else [(b, 1), (a, 1)]))
    assert results.count("CREATED") == 8 and results.count("OUT_OF_STOCK") == 8, results
    assert levels(db, a) == (8, 8) and levels(db, b) == (8, 8)
    assert_ledger(db, a)
    assert_ledger(db, b)


def test_concurrent_admin_removals_and_reservations_never_go_negative(db):
    product = make_product(db, 10)

    def task(i):
        with db.session() as session:
            if i % 2:
                stock.adjust_stock(session, product, -1, MovementReason.ADJUST, "admin", "count")
                return "ADJUSTED"
        return reserve(db, uuid.uuid4(), [(product, 1)])

    results = race(30, task)
    on_hand, reserved = levels(db, product)
    assert on_hand == 10 - results.count("ADJUSTED")
    assert reserved == results.count("CREATED")
    assert on_hand >= reserved >= 0
    assert set(results) <= {"ADJUSTED", "CREATED", "OUT_OF_STOCK", "INSUFFICIENT_STOCK"}, results
    assert_ledger(db, product)


def test_duplicate_requests_for_one_order_reserve_once(db):
    product = make_product(db, 10)
    order = uuid.uuid4()
    results = race(8, lambda i: reserve(db, order, [(product, 3)]))
    assert results.count("CREATED") == 1 and results.count("REPLAYED") == 7, results
    assert levels(db, product) == (10, 3)
    assert_ledger(db, product)


def test_confirm_racing_release_has_one_consistent_outcome(db):
    product = make_product(db, 5)
    order = uuid.uuid4()
    reserve(db, order, [(product, 2)])

    def task(i):
        with db.session() as session:
            if i % 2:
                stock.confirm(session, order, "svc:test")
                return "CONFIRMED"
            stock.release(session, order, "svc:test")
            return "RELEASED"

    results = race(10, task)
    on_hand, reserved = levels(db, product)
    assert reserved == 0
    confirm_won = on_hand == 3 and set(results) == {"CONFIRMED", "RESERVATION_ALREADY_CONFIRMED"}
    release_won = on_hand == 5 and set(results) == {"RELEASED", "RESERVATION_EXPIRED"}
    assert confirm_won or release_won, (on_hand, results)
    assert_ledger(db, product)
