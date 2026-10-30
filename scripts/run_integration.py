"""Run the cross-service integration suite against a DISPOSABLE Docker Compose stack.

    python scripts/run_integration.py                 # build, start, test, remove everything
    python scripts/run_integration.py --keep          # leave the stack running afterwards
    python scripts/run_integration.py --newman PATH   # also run the Postman collection with Newman

The stack is a separate Compose project (`shopease_it`) with its own random secrets, its own
signing key, its own database volume and its own host ports (18000-18005). Your development
stack, its volume and its .env are never touched. Everything is deleted afterwards
(`down -v`) unless --keep is given.

Exit codes: 0 all passed, 1 test failures, 2 not executed (Docker unavailable or startup failed).
"""

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "shopease_it"
PORTS = {"GATEWAY": 18000, "AUTH_SERVICE": 18001, "USER_SERVICE": 18002, "PRODUCT_SERVICE": 18003,
         "ORDER_SERVICE": 18004, "PAYMENT_SERVICE": 18005}
# Fast background jobs so reconciliation can be observed within a test.
OVERRIDES = {"RATE_LIMIT_AUTH_PER_MINUTE": "1000", "PAYMENT_SWEEP_SECONDS": "1",
             "RECONCILE_SCHEDULE_SECONDS": "[1, 1, 1, 1, 1, 1]", "ORDER_SWEEP_SECONDS": "5"}


def build_env_file(directory: Path) -> Path:
    lines = []
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.startswith("#") and value.strip() == "change-me":
            line = f"{key}={secrets.token_urlsafe(24)}"
        lines.append(line)
    lines += [f"{name}_HOST_PORT={port}" for name, port in PORTS.items()]
    lines += [f"{k}={v}" for k, v in OVERRIDES.items()]
    key_file = directory / "jwt_private.pem"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_jwt_key.py"), "--out", str(key_file)],
                   check=True, capture_output=True)
    lines.append(f"JWT_PRIVATE_KEY_FILE={key_file.as_posix()}")
    env_file = directory / "integration.env"
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env_file


def run_newman(newman: str, compose: list[str]) -> int:
    """Run the Postman collection. The admin account is created and promoted here, because
    promotion is an operator command, not an API call. Credentials are placeholders that
    exist only inside the disposable stack."""
    import json
    import urllib.request

    gateway = f"http://127.0.0.1:{PORTS['GATEWAY']}"
    email, password = f"postman-admin-{secrets.token_hex(4)}@example.com", "Postman-Admin-Password-123"
    request = urllib.request.Request(f"{gateway}/api/auth/register", method="POST",
                                     data=json.dumps({"email": email, "password": password}).encode(),
                                     headers={"Content-Type": "application/json"})
    urllib.request.urlopen(request, timeout=10).close()
    subprocess.run([*compose, "exec", "-T", "auth_service", "python", "-m", "app.cli", "promote-admin", email],
                   cwd=ROOT, check=True, capture_output=True)
    print("Running the Postman collection with Newman ...", flush=True)
    result = subprocess.run([
        newman, "run", "postman/ShopEase.postman_collection.json",
        "-e", "postman/ShopEase.local.postman_environment.json",
        "--env-var", f"baseUrl={gateway}", "--env-var", f"adminEmail={email}",
        "--env-var", f"adminPassword={password}", "--reporters", "cli",
    ], cwd=ROOT)
    return 0 if result.returncode == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep", action="store_true", help="leave the disposable stack running")
    parser.add_argument("--newman", help="path to the newman executable to also run the Postman collection")
    parser.add_argument("pytest_args", nargs="*", help="extra arguments for pytest")
    args = parser.parse_args()

    if shutil.which("docker") is None or subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        print("NOT EXECUTED: Docker is not available.", file=sys.stderr)
        return 2

    workdir = Path(tempfile.mkdtemp(prefix="shopease-it-"))
    env_file = build_env_file(workdir)
    compose = ["docker", "compose", "-p", PROJECT, "--env-file", str(env_file)]
    try:
        print(f"Starting disposable stack '{PROJECT}' ...", flush=True)
        up = subprocess.run([*compose, "up", "--build", "-d", "--wait", "--wait-timeout", "300"], cwd=ROOT)
        if up.returncode != 0:
            subprocess.run([*compose, "ps", "--all"], cwd=ROOT)
            print("NOT EXECUTED: the stack did not become healthy.", file=sys.stderr)
            return 2

        env = {**os.environ, "SHOPEASE_INTEGRATION": "1", "COMPOSE_PROJECT": PROJECT,
               "COMPOSE_ENV_FILE": str(env_file), "GATEWAY_URL": f"http://127.0.0.1:{PORTS['GATEWAY']}"}
        env.update({f"{name}_URL": f"http://127.0.0.1:{port}" for name, port in PORTS.items() if name != "GATEWAY"})
        result = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-rA", "-q",
                                 "tests/integration", *args.pytest_args], cwd=ROOT, env=env)
        code = 0 if result.returncode == 0 else 1

        if args.newman:
            code = run_newman(args.newman, compose) or code
        return code
    finally:
        if args.keep:
            print(f"Stack left running: docker compose -p {PROJECT} --env-file {env_file} down -v")
        else:
            subprocess.run([*compose, "down", "-v", "--remove-orphans"], cwd=ROOT, capture_output=True)
            shutil.rmtree(workdir, ignore_errors=True)
            print(f"Disposable stack '{PROJECT}' and its volume removed.")


if __name__ == "__main__":
    sys.exit(main())
