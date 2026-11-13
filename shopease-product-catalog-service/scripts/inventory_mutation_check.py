"""Check that the inventory tests can fail: put one deliberate bug into the code at a time, run the
relevant tests, then restore the file. Every line of output should show failures.

    python scripts/inventory_mutation_check.py

The lock check runs on the MySQL test database (CATALOG_SERVICE_TEST_DB=mysql,
MYSQL_DATABASE=shopease_product_catalog_test_db is set for that run only). The files are always
restored, also when the run is interrupted.
"""
import os, subprocess, sys
from pathlib import Path
svc = Path("app/services/inventory_service.py"); guard = Path("app/models/stock_guard.py")
originals = {svc: svc.read_text(encoding="utf-8"), guard: guard.read_text(encoding="utf-8")}
mysql = dict(os.environ, CATALOG_SERVICE_TEST_DB="mysql", MYSQL_DATABASE="shopease_product_catalog_test_db")
mutations = [
    ("no FOR UPDATE lock", svc, "select(Product).where(Product.id == product_id).with_for_update()", "select(Product).where(Product.id == product_id)", "tests/test_inventory_concurrency.py", mysql),
    ("no rollback on failure", svc, "    except BaseException:\n        db.rollback()  # releases", "    except BaseException:\n        pass  # releases", "tests/test_inventory_api.py", None),
    ("no rollback on refusal", svc, "    except IntegrityError as exc:\n        db.rollback()", "    except IntegrityError as exc:\n        pass", "tests/test_inventory_api.py", None),
    ("guard disabled", guard, "    new_movements: dict", "    return\n    new_movements: dict", "tests/test_inventory_api.py", None),
    ("low stock strictly below", svc, "Product.stock_quantity <= low_stock_threshold()", "Product.stock_quantity < low_stock_threshold()", "tests/test_inventory_api.py", None),
    ("overdraw by one allowed", svc, "        if updated < 0:", "        if updated < -1:", "tests/test_inventory_api.py", None),
]
try:
    for name, path, old, new, target, env in mutations:
        assert originals[path].count(old) == 1, name
        path.write_text(originals[path].replace(old, new), encoding="utf-8")
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:warnings", target], capture_output=True, text=True, env=env)
        print(f"{name}: {r.stdout.strip().splitlines()[-1]}")
        path.write_text(originals[path], encoding="utf-8")
finally:
    for path, text in originals.items():
        path.write_text(text, encoding="utf-8")
