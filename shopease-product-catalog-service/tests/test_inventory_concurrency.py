"""Simultaneous stock movements on one product, against real MySQL.

Each worker thread has its own session and connection and commits for real, as concurrent API
requests would. A barrier releases them together. Afterwards the stock and the history must be
consistent: the history forms one unbroken chain (each row starts where another ended), no two
rows start from the same stock, and the final stock equals the end of the chain.

Runs only with CATALOG_SERVICE_TEST_DB=mysql and MYSQL_DATABASE=shopease_product_catalog_test_db.
SQLite has no row locks, so it cannot show this. The rows created here are committed, so each
test deletes its own product, history and category at the end.
"""

import threading
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.database.connection import SessionLocal
from app.models import Category, InventoryTransaction, Product, TransactionType
from app.services import inventory_service
from app.services.errors import ConflictError
from tests.conftest import USE_MYSQL

TEST_DATABASE = "shopease_product_catalog_test_db"
WORKERS = 12  # below the engine's pool limit (5 + 10 overflow), so no worker waits for a connection

pytestmark = pytest.mark.skipif(
    not USE_MYSQL or get_settings().mysql_database != TEST_DATABASE,
    reason="needs MySQL row locks: CATALOG_SERVICE_TEST_DB=mysql MYSQL_DATABASE=shopease_product_catalog_test_db",
)


@pytest.fixture
def product_id(request):
    """A committed product with the given starting stock (recorded as an IN transaction)."""
    stock = request.param
    suffix = request.node.name.replace("[", "-").replace("]", "")[-40:]
    with SessionLocal() as db:
        category = Category(name=f"Concurrency {suffix}")
        product = Product(category=category, name="Concurrency", sku=f"CONC-{abs(hash(suffix)) % 10**8}",
                          price=Decimal("1.00"))
        db.add(product)
        db.flush()
        if stock:
            inventory_service.record_movement(db, product, TransactionType.IN, stock, "Initial stock")
        db.commit()
        ids = product.id, category.id
    yield ids[0]
    with SessionLocal() as db:
        db.execute(delete(InventoryTransaction).where(InventoryTransaction.product_id == ids[0]))
        db.execute(delete(Product).where(Product.id == ids[0]))
        db.execute(delete(Category).where(Category.id == ids[1]))
        db.commit()


def run_together(jobs) -> list[str]:
    """Run each job in its own thread and session, all released at once. Returns their outcomes."""
    barrier = threading.Barrier(len(jobs))
    outcomes: list[str] = [""] * len(jobs)

    def worker(index, job):
        with SessionLocal() as db:
            barrier.wait()
            try:
                job(db)
                outcomes[index] = "ok"
            except ConflictError as exc:
                outcomes[index] = exc.message
            except Exception as exc:  # recorded, so the test reports it instead of hanging
                outcomes[index] = f"error: {type(exc).__name__}"

    threads = [threading.Thread(target=worker, args=(i, job)) for i, job in enumerate(jobs)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads), "a worker did not finish"
    return outcomes


def stock_and_history(product_id: int) -> tuple[int, list[InventoryTransaction]]:
    with SessionLocal() as db:
        stock = db.scalar(select(Product.stock_quantity).where(Product.id == product_id))
        history = list(db.scalars(select(InventoryTransaction).where(InventoryTransaction.product_id == product_id)
                                  .order_by(InventoryTransaction.id)))
    return stock, history


def assert_one_chain(stock: int, history: list[InventoryTransaction]) -> None:
    """The history replays from 0 to the current stock without a gap or a fork.

    Rows are ordered by id, which is the commit order here: each movement holds the row lock
    from its read until its commit, so the next one can only start after it.
    """
    level = 0
    for row in history:
        assert row.previous_stock == level, [(r.transaction_type, r.previous_stock, r.updated_stock) for r in history]
        sign = 1 if row.transaction_type == TransactionType.IN else -1
        assert row.updated_stock == level + sign * row.quantity >= 0
        level = row.updated_stock
    assert level == stock


@pytest.mark.parametrize("product_id", [5], indirect=True)
def test_simultaneous_stock_outs_never_oversell(product_id):
    """12 requests for 1 unit each, only 5 in stock: exactly 5 succeed and stock ends at 0."""
    outcomes = run_together([lambda db: inventory_service.stock_out(db, product_id, 1)] * WORKERS)
    assert outcomes.count("ok") == 5, outcomes
    assert sorted(set(outcomes) - {"ok"}) == ["Insufficient stock: 0 available, 1 requested"]
    stock, history = stock_and_history(product_id)
    assert stock == 0
    assert len(history) == 1 + 5  # initial stock + one row per successful stock-out
    assert_one_chain(stock, history)


@pytest.mark.parametrize("product_id", [10], indirect=True)
def test_simultaneous_stock_ins_lose_no_update(product_id):
    """12 simultaneous stock-ins of 3: every one counts."""
    outcomes = run_together([lambda db: inventory_service.stock_in(db, product_id, 3)] * WORKERS)
    assert outcomes == ["ok"] * WORKERS
    stock, history = stock_and_history(product_id)
    assert stock == 10 + 3 * WORKERS
    assert_one_chain(stock, history)
    assert sorted(row.previous_stock for row in history[1:]) == list(range(10, 10 + 3 * WORKERS, 3))


@pytest.mark.parametrize("product_id", [6], indirect=True)
def test_simultaneous_mixed_movements(product_id):
    """6 stock-ins of 2 and 6 stock-outs of 3 at once, from 6. Outs may be refused only when the
    stock at that moment is too low; the final stock always matches the history."""
    jobs = ([lambda db: inventory_service.stock_in(db, product_id, 2)] * 6
            + [lambda db: inventory_service.stock_out(db, product_id, 3)] * 6)
    outcomes = run_together(jobs)
    assert not [o for o in outcomes if o.startswith("error")], outcomes
    assert outcomes[:6] == ["ok"] * 6
    successful_outs = outcomes[6:].count("ok")
    stock, history = stock_and_history(product_id)
    assert stock == 6 + 2 * 6 - 3 * successful_outs >= 0
    assert len(history) == 1 + 6 + successful_outs
    assert_one_chain(stock, history)


@pytest.mark.parametrize("product_id", [20], indirect=True)
def test_simultaneous_requests_through_the_api(product_id):
    """The same through HTTP: the real get_db (one session per request), only the caller is faked."""
    from fastapi.testclient import TestClient

    from app.core.security import AuthenticatedUser, get_current_authenticated_user
    from app.main import app

    admin = AuthenticatedUser(auth_user_id=1, full_name="Admin", email="admin@example.com", role="ADMIN")
    app.dependency_overrides[get_current_authenticated_user] = lambda: admin
    try:
        client = TestClient(app)
        statuses: list[int] = []
        lock = threading.Lock()

        def call(_db):
            response = client.post(f"/api/inventory/{product_id}/stock-out", json={"quantity": 2})
            with lock:
                statuses.append(response.status_code)

        run_together([call] * WORKERS)
    finally:
        app.dependency_overrides.clear()
    assert sorted(statuses) == [201] * 10 + [409] * 2
    stock, history = stock_and_history(product_id)
    assert stock == 0
    assert_one_chain(stock, history)
