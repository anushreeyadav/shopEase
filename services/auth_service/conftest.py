"""pytest setup for auth_service.

Present so pytest puts services/auth_service/ on sys.path and `import app` resolves to this component. Run
each component's tests in its own process (scripts/run_tests.py): every package is `app`.

Every test is tagged with its layer, so one layer can be run alone (`pytest -m unit`):
- unit:        models, schemas, migrations on SQLite, session handling (no HTTP)
- api:         HTTP behaviour through FastAPI's TestClient, dependencies faked (no network)
- integration: needs a real, disposable MySQL (opt-in: SHOPEASE_MYSQL_TESTS=1)
"""

import pytest

LAYERS = {
    "unit": "no HTTP, no network: models, schemas, migrations on SQLite",
    "api": "HTTP through TestClient with faked dependencies; no network",
    "integration": "needs a disposable MySQL (SHOPEASE_MYSQL_TESTS=1)",
}
UNIT_FILES = {"test_models.py", "test_database.py"}


def pytest_configure(config):
    for name, description in LAYERS.items():
        config.addinivalue_line("markers", f"{name}: {description}")


def pytest_collection_modifyitems(items):
    for item in items:
        name = item.path.name
        if name.startswith("test_mysql"):
            layer = "integration"
        elif name in UNIT_FILES:
            layer = "unit"
        else:
            layer = "api"
        item.add_marker(getattr(pytest.mark, layer))
