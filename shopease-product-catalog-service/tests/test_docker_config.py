"""Static checks of the Docker files, so that a later edit cannot silently drop a requirement.

The running stack itself is verified by DELIVERABELS/Docker_Evidence (docker compose up, ps,
logs, /health and /docs from inside the container, down without removing the volume).
"""

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parent.parent
DATABASE = "shopease_product_catalog_db"


def load(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def compose() -> dict:
    return load("docker-compose.yml")


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return (ROOT / "Dockerfile").read_text(encoding="utf-8")


def instructions(dockerfile: str) -> list[str]:
    return [line for line in dockerfile.splitlines() if line and not line.startswith(("#", " "))]


# --- Dockerfile ---

def test_python_311_base_image(dockerfile):
    [base] = [line for line in instructions(dockerfile) if line.startswith("FROM ")]
    assert re.fullmatch(r"FROM python:3\.11(\.\d+)?-slim(-\w+)?", base)


def test_dependencies_from_requirements(dockerfile):
    assert "COPY requirements.txt ." in dockerfile
    assert "RUN pip install -r requirements.txt" in dockerfile


def test_no_env_file_or_secret_in_the_image(dockerfile):
    copies = [line for line in instructions(dockerfile) if line.startswith(("COPY", "ADD"))]
    assert copies == ["COPY requirements.txt .", "COPY app/ ./app/", "COPY alembic/ ./alembic/", "COPY alembic.ini ."]
    env_lines = " ".join(line for line in dockerfile.splitlines() if "ENV" in line or "=" in line)
    for secret in ("PASSWORD", "SECRET", "TOKEN"):
        assert secret not in env_lines.upper()


def test_dockerignore_keeps_secrets_out():
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert {".env", ".env.*", "**/.env", ".venv/", "tests/", ".git/"} <= set(ignored)


def test_port_exposed_and_unprivileged_user(dockerfile):
    assert "EXPOSE 8006" in instructions(dockerfile)
    assert "USER app" in instructions(dockerfile)


def test_startup_waits_then_migrates_then_serves(dockerfile):
    [cmd] = [line for line in instructions(dockerfile) if line.startswith("CMD ")]
    steps = cmd.split("&&")
    assert "python -m app.database.wait" in steps[0]
    assert "alembic upgrade head" in steps[1]
    assert "exec python -m app" in steps[2]


def test_container_health_check_uses_health_endpoint(dockerfile):
    assert "HEALTHCHECK" in dockerfile and "/health" in dockerfile


# --- docker-compose.yml ---

def test_two_services(compose):
    assert set(compose["services"]) == {"catalog-service", "catalog-mysql"}


def test_mysql_8_with_fixed_database_name(compose):
    mysql = compose["services"]["catalog-mysql"]
    assert mysql["image"].startswith("mysql:8")
    assert mysql["environment"]["MYSQL_DATABASE"] == DATABASE
    assert compose["services"]["catalog-service"]["environment"]["MYSQL_DATABASE"] == DATABASE


def test_credentials_come_from_the_environment(compose):
    for service in ("catalog-mysql", "catalog-service"):
        env = compose["services"][service]["environment"]
        for name, value in env.items():
            if "PASSWORD" in name or name == "MYSQL_USER":
                assert value.startswith("${") and ":?" in value, (service, name)  # required, no default


def test_named_volume_for_mysql_data(compose):
    assert "catalog_mysql_data" in compose["volumes"]
    assert "catalog_mysql_data:/var/lib/mysql" in compose["services"]["catalog-mysql"]["volumes"]


def test_mysql_health_check(compose):
    check = compose["services"]["catalog-mysql"]["healthcheck"]
    test = " ".join(check["test"])
    assert "SELECT 1" in test and "MYSQL_DATABASE" in test and "MYSQL_USER" in test
    assert "-p" not in test.split()  # password not on the command line


def test_service_waits_for_healthy_mysql(compose):
    assert compose["services"]["catalog-service"]["depends_on"]["catalog-mysql"]["condition"] == "service_healthy"


def test_database_reached_by_service_name(compose):
    env = compose["services"]["catalog-service"]["environment"]
    assert (env["MYSQL_HOST"], env["MYSQL_PORT"]) == ("catalog-mysql", "3306")
    assert "ports" not in compose["services"]["catalog-mysql"]  # not published by default


def test_auth_service_via_host_docker_internal(compose):
    service = compose["services"]["catalog-service"]
    assert "host.docker.internal:8001/api/auth/verify-token" in service["environment"]["AUTH_SERVICE_VERIFY_URL"]
    assert "host.docker.internal:host-gateway" in service["extra_hosts"]
    assert "networks" not in compose  # no assumption about the Auth Service's network


def test_application_port_published(compose):
    assert compose["services"]["catalog-service"]["ports"] == ["127.0.0.1:${SERVICE_PORT:-8006}:${SERVICE_PORT:-8006}"]


# --- Optional overrides ---

def test_shared_network_override_is_external():
    override = load("docker-compose.auth-network.yml")
    network = override["networks"]["auth"]
    assert network["external"] is True
    assert "shopease-auth-service_default" in network["name"]
    service = override["services"]["catalog-service"]
    assert service["networks"] == ["default", "auth"]
    assert "auth-service:8001/api/auth/verify-token" in service["environment"]["AUTH_SERVICE_VERIFY_URL"]


def test_dev_override_publishes_mysql_on_loopback_only():
    ports = load("docker-compose.dev.yml")["services"]["catalog-mysql"]["ports"]
    assert all(port.startswith("127.0.0.1:") for port in ports)
