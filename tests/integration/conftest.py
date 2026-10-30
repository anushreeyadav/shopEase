"""Cross-service integration tests against a running ShopEase stack.

They run only with SHOPEASE_INTEGRATION=1, against a **disposable** Docker Compose project
started by `python scripts/run_integration.py` (its own database volume, removed afterwards).
Never point them at a stack holding data you care about: they create users, products,
orders and payments, and stop/restart containers.

Environment (set by the runner):
  GATEWAY_URL, AUTH_SERVICE_URL ... PAYMENT_SERVICE_URL   published URLs of the stack
  COMPOSE_PROJECT, COMPOSE_ENV_FILE                        to exec/stop/start containers
"""

import os
import subprocess
import time
import uuid
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "integration-Password-123"  # placeholder; accounts exist only in the disposable stack


def pytest_collection_modifyitems(config, items):
    for item in items:
        item.add_marker(pytest.mark.integration)
    if os.getenv("SHOPEASE_INTEGRATION") != "1":
        skip = pytest.mark.skip(reason="needs a disposable stack: python scripts/run_integration.py")
        for item in items:
            item.add_marker(skip)


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: needs the disposable Docker Compose stack")


def url(name: str, default: str) -> str:
    return os.getenv(name, default).rstrip("/")


GATEWAY = url("GATEWAY_URL", "http://127.0.0.1:18000")
SERVICES = {
    "auth_service": url("AUTH_SERVICE_URL", "http://127.0.0.1:18001"),
    "user_service": url("USER_SERVICE_URL", "http://127.0.0.1:18002"),
    "product_service": url("PRODUCT_SERVICE_URL", "http://127.0.0.1:18003"),
    "order_service": url("ORDER_SERVICE_URL", "http://127.0.0.1:18004"),
    "payment_service": url("PAYMENT_SERVICE_URL", "http://127.0.0.1:18005"),
}


class Compose:
    """docker compose for the disposable project the runner started."""

    def __init__(self) -> None:
        self.base = ["docker", "compose", "-p", os.getenv("COMPOSE_PROJECT", "shopease_it")]
        if os.getenv("COMPOSE_ENV_FILE"):
            self.base += ["--env-file", os.environ["COMPOSE_ENV_FILE"]]

    def run(self, *args: str, timeout: int = 180) -> subprocess.CompletedProcess:
        return subprocess.run([*self.base, *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout)

    def healthy(self, service: str, timeout: int = 120) -> bool:
        return wait_until(lambda: '"Health":"healthy"' in self.run("ps", "--format", "json", service).stdout.replace(" ", ""),
                          timeout=timeout)


def wait_until(condition, timeout: float = 30, step: float = 1.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if condition():
                return True
        except httpx.HTTPError:
            pass
        time.sleep(step)
    return False


@pytest.fixture(scope="session")
def compose() -> Compose:
    return Compose()


@pytest.fixture(scope="session")
def gw():
    with httpx.Client(base_url=GATEWAY, timeout=30) as client:
        yield client


class Shopper:
    """A registered, logged-in customer with one delivery address."""

    def __init__(self, gw: httpx.Client, email: str | None = None) -> None:
        self.gw = gw
        self.email = email or f"it-{uuid.uuid4().hex[:10]}@example.com"
        assert gw.post("/api/auth/register", json={"email": self.email, "password": PASSWORD}).status_code == 201
        self.login()
        self.id = gw.get("/api/users/me", headers=self.headers).json()["user_id"]
        self.address_id = None

    def login(self) -> None:
        tokens = self.gw.post("/api/auth/login", json={"email": self.email, "password": PASSWORD}).json()
        self.headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        self.refresh_token = tokens["refresh_token"]

    def address(self) -> str:
        if self.address_id is None:
            response = self.gw.post("/api/users/me/addresses", headers=self.headers, json={
                "line1": "12 Example Street", "city": "Pune", "postal_code": "411001", "country": "IN"})
            assert response.status_code == 201, response.text
            self.address_id = response.json()["address_id"]
        return self.address_id

    def order(self, items, key: str | None = None) -> httpx.Response:
        return self.gw.post(
            "/api/orders", headers={**self.headers, "Idempotency-Key": key or str(uuid.uuid4())},
            json={"items": [{"product_id": p, "quantity": q} for p, q in items], "shipping_address_id": self.address()})

    def pay(self, order_id: str, token: str = "mock_tok_success", key: str | None = None) -> httpx.Response:
        return self.gw.post(
            "/api/payments", headers={**self.headers, "Idempotency-Key": key or str(uuid.uuid4())},
            json={"order_id": order_id, "payment_method_token": token})


@pytest.fixture
def shopper(gw) -> Shopper:
    return Shopper(gw)


@pytest.fixture(scope="session")
def admin(gw, compose) -> Shopper:
    user = Shopper(gw)
    promoted = compose.run("exec", "-T", "auth_service", "python", "-m", "app.cli", "promote-admin", user.email)
    assert promoted.returncode == 0, promoted.stderr
    user.login()  # the new role is in tokens issued from now on
    return user


@pytest.fixture
def make_product(gw, admin):
    def make(stock: int = 10, price: str = "2499.00", name: str = "Integration Shoe") -> str:
        response = gw.post("/api/products", headers=admin.headers, json={
            "sku": f"IT-{uuid.uuid4().hex[:12]}", "name": name, "price": price, "initial_stock": stock})
        assert response.status_code == 201, response.text
        return response.json()["product_id"]

    return make
