"""Load sample categories and products into the Catalog Service database.

Run from the project root, with MySQL reachable at MYSQL_HOST:MYSQL_PORT from .env
(docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d), after
"alembic upgrade head":

    python -m scripts.seed_sample_data

Safe to run more than once: existing categories (by name) and products (by SKU) are skipped.
Writes go through the service layer, so the same validation as the API applies, and each
product's initial stock is recorded as an IN inventory transaction.
"""

from decimal import Decimal

from sqlalchemy import func, select

from app.database.connection import SessionLocal
from app.models import Category, Product
from app.schemas.category_schema import CategoryCreate
from app.schemas.product_schema import ProductCreate
from app.services import category_service, product_service

CATEGORIES = [
    ("Mobile Phones", "Smartphones and feature phones"),
    ("Laptops", "Notebooks and ultrabooks"),
    ("Footwear", "Shoes, sandals and boots"),
    ("Home & Kitchen", "Cookware, appliances and decor"),
]

# sku, name, category, brand, price, discount_price, stock
PRODUCTS = [
    ("PHN-NOVA-128", "Nova 5G Smartphone 128 GB", "Mobile Phones", "Nova", "24999.00", "22999.00", 40),
    ("PHN-NOVA-256", "Nova 5G Smartphone 256 GB", "Mobile Phones", "Nova", "28999.00", None, 25),
    ("LAP-AERO-14", "AeroBook 14 Laptop", "Laptops", "Aero", "62999.00", None, 12),
    ("LAP-AERO-16", "AeroBook 16 Laptop", "Laptops", "Aero", "74999.00", "69999.00", 3),
    ("SHO-TRAIL-42", "Trail Runner Shoes, Size 42", "Footwear", "Stride", "3499.00", None, 60),
    ("SHO-CITY-41", "City Sneakers, Size 41", "Footwear", "Stride", "2799.00", "2299.00", 0),
    ("KIT-PAN-28", "Non-stick Frying Pan 28 cm", "Home & Kitchen", "Kitchenly", "1299.00", None, 85),
]


def main() -> None:
    with SessionLocal() as db:
        category_ids: dict[str, int] = {}
        for name, description in CATEGORIES:
            existing = db.scalars(select(Category).where(func.lower(Category.name) == name.lower())).first()
            if existing is None:
                existing = category_service.create_category(db, CategoryCreate(name=name, description=description))
                print(f"created category {existing.name}")
            category_ids[name] = existing.id

        for sku, name, category, brand, price, discount, stock in PRODUCTS:
            if db.scalars(select(Product.id).where(Product.sku == sku)).first() is not None:
                continue
            product_service.create_product(db, ProductCreate(
                sku=sku, name=name, brand=brand, category_id=category_ids[category],
                price=Decimal(price), discount_price=Decimal(discount) if discount else None,
                initial_stock=stock,
            ))
            print(f"created product {sku}")
    print("Sample data loaded.")


if __name__ == "__main__":
    main()
