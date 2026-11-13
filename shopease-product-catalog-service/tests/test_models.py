"""Models and database layer: constraints, relationships, indexes, UTC timestamps and sessions.

These tests work on the ORM directly, below the services, to prove the database itself refuses
invalid data. They run on SQLite by default and on MySQL 8 with CATALOG_SERVICE_TEST_DB=mysql.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, insert, inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError, StatementError
from sqlalchemy.orm import Session, sessionmaker

from app.database import connection
from app.database.base import Base
from app.models import Category, InventoryTransaction, Product, TransactionType


# --- helpers ---

@pytest.fixture
def category(db_session: Session) -> Category:
    category = Category(name="Electronics")
    db_session.add(category)
    db_session.flush()
    return category


def new_product(category: Category, **overrides) -> Product:
    values = {"category": category, "name": "Phone", "sku": "PHN-1", "price": Decimal("100.00")}
    return Product(**(values | overrides))


def assert_rejected(db: Session, *objects, error=IntegrityError) -> None:
    """The database refuses to store the objects; the session stays usable afterwards."""
    with pytest.raises(error):
        with db.begin_nested():
            db.add_all(objects)
            db.flush()


# A missing foreign-key parent: MySQL raises IntegrityError (1452). SQLite, inside a savepoint,
# reports the same refusal as OperationalError("FOREIGN KEY constraint failed").
FOREIGN_KEY_ERRORS = (IntegrityError, OperationalError)


def transaction(product: Product, type_: str, quantity: int, previous: int, updated: int) -> InventoryTransaction:
    return InventoryTransaction(product=product, transaction_type=TransactionType(type_),
                                quantity=quantity, previous_stock=previous, updated_stock=updated)


# --- schema shape ---

def test_three_tables_with_the_specified_columns(db_engine):
    inspector = inspect(db_engine)
    columns = {table: [c["name"] for c in inspector.get_columns(table)]
               for table in ("categories", "products", "inventory_transactions")}
    assert columns["categories"] == ["id", "name", "description", "is_active", "created_at", "updated_at"]
    assert columns["products"] == [
        "id", "category_id", "name", "description", "sku", "price", "discount_price", "stock_quantity",
        "image_url", "brand", "is_active", "created_at", "updated_at",
    ]
    assert columns["inventory_transactions"] == [
        "id", "product_id", "transaction_type", "quantity", "previous_stock", "updated_stock", "remarks", "created_at",
    ]


def test_indexes_and_unique_constraints(db_engine):
    inspector = inspect(db_engine)
    product_indexes = {tuple(ix["column_names"]) for ix in inspector.get_indexes("products")}
    assert {("name",), ("category_id",)} <= product_indexes
    history_indexes = {tuple(ix["column_names"]) for ix in inspector.get_indexes("inventory_transactions")}
    assert ("product_id", "created_at") in history_indexes

    def unique_columns(table):
        found = {tuple(uq["column_names"]) for uq in inspector.get_unique_constraints(table)}
        # MySQL also reports unique constraints as unique indexes.
        found |= {tuple(ix["column_names"]) for ix in inspector.get_indexes(table) if ix.get("unique")}
        return found

    assert ("name",) in unique_columns("categories")
    assert ("sku",) in unique_columns("products")


def test_foreign_keys_restrict_deletes(db_engine):
    inspector = inspect(db_engine)
    (product_fk,) = inspector.get_foreign_keys("products")
    assert (product_fk["referred_table"], product_fk["constrained_columns"]) == ("categories", ["category_id"])
    assert product_fk["options"].get("ondelete", "").upper() == "RESTRICT"
    (history_fk,) = inspector.get_foreign_keys("inventory_transactions")
    assert (history_fk["referred_table"], history_fk["constrained_columns"]) == ("products", ["product_id"])
    assert history_fk["options"].get("ondelete", "").upper() == "RESTRICT"


# --- defaults and types ---

def test_defaults(db_session, category):
    product = new_product(category)
    db_session.add(product)
    db_session.flush()
    assert category.is_active is True
    assert (product.is_active, product.stock_quantity, product.discount_price) == (True, 0, None)
    assert (product.description, product.image_url, product.brand) == (None, None, None)


def test_server_defaults_apply_to_rows_inserted_outside_the_orm(db_session):
    db_session.execute(text("INSERT INTO categories (name) VALUES ('Raw SQL')"))
    row = db_session.execute(
        text("SELECT is_active, created_at, updated_at FROM categories WHERE name = 'Raw SQL'")
    ).one()
    assert row.is_active in (1, True)
    assert row.created_at is not None and row.updated_at is not None


def test_money_is_decimal(db_session, category):
    db_session.add(new_product(category, price=Decimal("19.99"), discount_price=Decimal("0.10")))
    db_session.flush()
    db_session.expire_all()
    product = db_session.scalars(select(Product)).one()
    assert isinstance(product.price, Decimal) and product.price == Decimal("19.99")
    assert isinstance(product.discount_price, Decimal) and product.discount_price == Decimal("0.10")
    assert product.effective_price == Decimal("0.10")


# --- constraints ---

def test_category_name_is_unique_and_required(db_session, category):
    assert_rejected(db_session, Category(name="Electronics"))
    assert_rejected(db_session, Category(name=None))
    assert_rejected(db_session, Category(name="   "))


def test_product_sku_is_unique_and_required(db_session, category):
    db_session.add(new_product(category))
    db_session.flush()
    assert_rejected(db_session, new_product(category, name="Other"))  # same SKU
    assert_rejected(db_session, new_product(category, sku=None))
    assert_rejected(db_session, new_product(category, sku=" "))


def test_product_requires_name_price_and_category(db_session, category):
    assert_rejected(db_session, new_product(category, name=None))
    assert_rejected(db_session, new_product(category, price=None))
    assert_rejected(db_session, Product(name="Orphan", sku="ORPHAN", price=Decimal("1.00")))  # no category


def test_product_category_must_exist(db_session):
    assert_rejected(db_session, Product(category_id=987654, name="X", sku="X", price=Decimal("1.00")),
                    error=FOREIGN_KEY_ERRORS)


@pytest.mark.parametrize("stock", [-1, -100])
def test_negative_stock_is_refused(db_session, category, stock):
    # Plain SQL: the ORM's stock guard (app.models.stock_guard) would refuse this before the
    # database sees it, and this test is about the database's own CHECK constraint.
    db_session.flush()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(insert(Product).values(
                category_id=category.id, name="Phone", sku="PHN-1", price=Decimal("100.00"), stock_quantity=stock))


def test_negative_price_is_refused(db_session, category):
    assert_rejected(db_session, new_product(category, price=Decimal("-0.01")))


@pytest.mark.parametrize("discount", ["100.00", "150.00", "-1.00"])
def test_invalid_discount_is_refused(db_session, category, discount):
    assert_rejected(db_session, new_product(category, discount_price=Decimal(discount)))


def test_valid_discount_is_accepted(db_session, category):
    db_session.add(new_product(category, discount_price=Decimal("99.99")))
    db_session.flush()


# --- inventory transactions ---

def test_valid_transactions_are_accepted(db_session, category):
    product = new_product(category)
    db_session.add_all([product, transaction(product, "IN", 10, 0, 10), transaction(product, "OUT", 4, 10, 6)])
    db_session.flush()
    assert db_session.scalar(select(InventoryTransaction.remarks).limit(1)) is None


@pytest.mark.parametrize(("type_", "quantity", "previous", "updated"), [
    ("IN", 0, 5, 5),        # quantity must be positive
    ("IN", -2, 5, 3),
    ("IN", 5, 0, 4),        # arithmetic does not add up
    ("OUT", 5, 10, 6),
    ("OUT", 5, 3, -2),      # stock would go negative
    ("IN", 1, -1, 0),       # previous stock negative
])
def test_inconsistent_transactions_are_refused(db_session, category, type_, quantity, previous, updated):
    product = new_product(category)
    db_session.add(product)
    db_session.flush()
    assert_rejected(db_session, transaction(product, type_, quantity, previous, updated))


def test_transaction_type_is_only_in_or_out(db_session, category):
    product = new_product(category)
    db_session.add(product)
    db_session.flush()
    # The ORM refuses an unknown value before it reaches the database...
    with pytest.raises((StatementError, LookupError)):
        with db_session.begin_nested():
            db_session.add(InventoryTransaction(product_id=product.id, transaction_type="MOVE",
                                                quantity=1, previous_stock=0, updated_stock=1))
            db_session.flush()
    # ...and the database's CHECK constraint refuses it from raw SQL too.
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(text(
                "INSERT INTO inventory_transactions (product_id, transaction_type, quantity, previous_stock, updated_stock)"
                " VALUES (:pid, 'MOV', 1, 0, 1)"), {"pid": product.id})  # 3 chars: fits VARCHAR(3), so the CHECK decides


def test_transaction_needs_an_existing_product(db_session):
    assert_rejected(db_session, InventoryTransaction(product_id=987654, transaction_type=TransactionType.IN,
                                                     quantity=1, previous_stock=0, updated_stock=1),
                    error=FOREIGN_KEY_ERRORS)


# --- relationships ---

def test_category_product_relationship(db_session, category):
    first, second = new_product(category, sku="A"), new_product(category, sku="B")
    db_session.add_all([first, second])
    db_session.flush()
    assert first.category is category
    assert {p.sku for p in category.products} == {"A", "B"}
    assert first.category_id == category.id


def test_product_history_relationship(db_session, category):
    product = new_product(category)
    db_session.add(product)
    product.inventory_transactions.add(transaction(product, "IN", 3, 0, 3))
    db_session.flush()
    history = db_session.scalars(product.inventory_transactions.select()).all()
    assert [(t.transaction_type, t.quantity) for t in history] == [(TransactionType.IN, 3)]
    assert history[0].product is product


def test_category_with_products_cannot_be_deleted(db_session, category):
    db_session.add(new_product(category))
    db_session.flush()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.delete(category)
            db_session.flush()


def test_product_with_history_cannot_be_deleted(db_session, category):
    product = new_product(category)
    db_session.add_all([product, transaction(product, "IN", 1, 0, 1)])
    db_session.flush()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.delete(product)
            db_session.flush()


# --- UTC timestamps ---

def test_timestamps_are_timezone_aware_utc(db_session, category):
    before = datetime.now(timezone.utc) - timedelta(seconds=2)
    db_session.expire_all()
    loaded = db_session.get(Category, category.id)
    assert loaded.created_at.tzinfo == timezone.utc
    assert loaded.updated_at.tzinfo == timezone.utc
    assert before <= loaded.created_at <= datetime.now(timezone.utc) + timedelta(seconds=2)


def test_stored_value_is_utc_wall_time(db_session, category):
    ist = timezone(timedelta(hours=5, minutes=30))
    category.created_at = datetime(2026, 1, 1, 12, 0, tzinfo=ist)
    db_session.flush()
    raw = db_session.execute(text("SELECT created_at FROM categories WHERE id = :id"), {"id": category.id}).scalar()
    if isinstance(raw, str):  # SQLite returns text
        raw = datetime.fromisoformat(raw)
    assert raw.replace(tzinfo=None) == datetime(2026, 1, 1, 6, 30)


def test_naive_datetimes_are_refused(db_session, category):
    category.created_at = datetime(2026, 1, 1, 12, 0)  # no time zone: ambiguous
    with pytest.raises(StatementError):
        with db_session.begin_nested():
            db_session.flush()


def test_updated_at_changes_on_update(db_session, category):
    old = datetime(2020, 1, 1, tzinfo=timezone.utc)
    category.updated_at = old
    db_session.flush()
    category.description = "changed"
    db_session.flush()
    assert category.updated_at > old
    assert category.created_at <= category.updated_at


# --- session management ---

@pytest.fixture
def isolated_sessions(monkeypatch):
    """session_scope() bound to a private in-memory database instead of MySQL."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(connection, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    yield engine
    engine.dispose()


def test_session_scope_commits_on_success(isolated_sessions):
    with connection.session_scope() as db:
        db.add(Category(name="Committed"))
    with Session(isolated_sessions) as check:
        assert check.scalars(select(Category.name)).all() == ["Committed"]


def test_session_scope_rolls_back_on_error(isolated_sessions):
    with pytest.raises(RuntimeError):
        with connection.session_scope() as db:
            db.add(Category(name="Discarded"))
            db.flush()
            raise RuntimeError("boom")
    with Session(isolated_sessions) as check:
        assert check.scalars(select(Category)).all() == []


def test_get_db_closes_and_rolls_back(isolated_sessions):
    generator = connection.get_db()
    db = next(generator)
    db.add(Category(name="Uncommitted"))
    db.flush()
    with pytest.raises(ValueError):
        generator.throw(ValueError("request failed"))
    with Session(isolated_sessions) as check:
        assert check.scalars(select(Category)).all() == []


def test_models_import_without_a_database_connection():
    """Models, the declarative base and the engine live in separate modules."""
    import app.database.base as base_module
    import app.models.product_model as product_module
    assert "engine" not in vars(base_module)
    assert "engine" not in vars(product_module)
    assert "SessionLocal" not in vars(product_module)


# --- MySQL CHECK violations are integrity errors ---

class _FakeContext:
    def __init__(self, original):
        self.original_exception, self.statement, self.parameters = original, "INSERT ...", {"x": "secret"}


def test_mysql_check_violation_becomes_integrity_error():
    import pymysql

    original = pymysql.err.OperationalError(3819, "Check constraint 'ck_products_stock_quantity_non_negative' is violated.")
    with pytest.raises(IntegrityError) as caught:
        connection.translate_check_violation(_FakeContext(original))
    assert caught.value.orig is original
    assert "secret" not in str(caught.value)  # parameters stay hidden


def test_other_database_errors_are_left_alone():
    import pymysql

    # 2003: cannot connect. That really is an operational problem and must stay one.
    assert connection.translate_check_violation(_FakeContext(pymysql.err.OperationalError(2003, "down"))) is None


def test_integrity_error_reaching_the_api_is_409_not_503(client, monkeypatch):
    import pymysql
    from app.services import category_service

    def refuse(*_args, **_kwargs):
        raise IntegrityError("INSERT ...", {}, pymysql.err.IntegrityError(1062, "Duplicate entry"))

    monkeypatch.setattr(category_service, "list_categories", refuse)
    response = client.get("/api/categories")
    assert response.status_code == 409
    assert response.json() == {"detail": "The request conflicts with existing data"}
    assert "Duplicate" not in response.text
