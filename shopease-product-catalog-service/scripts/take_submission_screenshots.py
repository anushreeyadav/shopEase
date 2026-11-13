"""Take the Swagger UI submission screenshots (Task 12, items 2, 4-15, 17).

    $env:CUSTOMER_EMAIL="..."; $env:CUSTOMER_PASSWORD="..."      a USER account of the Authentication Service
    $env:ADMIN_EMAIL="..."; $env:ADMIN_PASSWORD="..."            optional: an ADMIN account
    $env:NODE_PATH="<folder with playwright-core>"
    python -m scripts.take_submission_screenshots

Logs in to the real Authentication Service (port 8001). If the ADMIN account logs in with the role
ADMIN, the ADMIN screenshots are taken on the live service (port 8006); this creates a category and
three products in the configured database, as an administrator would. Otherwise they are taken on
the test instance (scripts/screenshot_test_instance.py: port 8016, test database, stand-in
Authentication Service), whose rows are deleted afterwards, and the files are named
"..._test_instance.png". The live 401, health and customer 403 screenshots always use the live service.

Credentials come from environment variables only; tokens are hidden in every image.
"""

import os
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
AUTH, LIVE = "http://127.0.0.1:8001", "http://127.0.0.1:8006"
OUT = ROOT / "DELIVERABELS" / "screenshots" / "submission"
SCRIPT = ROOT / "scripts" / "submission_screenshots.js"


def login(prefix: str) -> tuple[str | None, str | None]:
    email, password = os.environ.get(f"{prefix}_EMAIL"), os.environ.get(f"{prefix}_PASSWORD")
    if not email or not password:
        return None, None
    r = httpx.post(f"{AUTH}/api/auth/login", json={"email": email, "password": password}, timeout=10)
    body = r.json() if r.status_code == 200 else {}
    return body.get("access_token"), (body.get("user") or {}).get("role")


def main() -> int:
    customer, customer_role = login("CUSTOMER")
    admin, admin_role = login("ADMIN")
    print(f"customer login: {'token' if customer else 'none'} (role {customer_role}); "
          f"admin login: {'token' if admin else 'none'} (role {admin_role})")
    env = dict(os.environ, LIVE_URL=LIVE, OUT_DIR=str(OUT), LIVE_CUSTOMER_TOKEN=customer or "")
    node = ["node", str(SCRIPT)]
    if admin and admin_role == "ADMIN":
        print("ADMIN screenshots: live service")
        env.update(ADMIN_KIND="live", ADMIN_URL=LIVE, ADMIN_TOKEN=admin, ADMIN_URL_USER_TOKEN=customer or "")
        return subprocess.run(node, cwd=ROOT, env=env).returncode
    print("ADMIN screenshots: test instance (no live ADMIN account)")
    # The test instance passes TEST_URL / TEST_ADMIN_TOKEN / TEST_USER_TOKEN to the command; map them.
    wrapper = [sys.executable, "-c",
               "import os,subprocess,sys;e=dict(os.environ,ADMIN_KIND='test',ADMIN_URL=os.environ['TEST_URL'],"
               "ADMIN_TOKEN=os.environ['TEST_ADMIN_TOKEN'],ADMIN_URL_USER_TOKEN=os.environ['TEST_USER_TOKEN']);"
               f"sys.exit(subprocess.run({node!r},env=e).returncode)"]
    return subprocess.run([sys.executable, "-m", "scripts.screenshot_test_instance", "--run", *wrapper],
                          cwd=ROOT, env=env).returncode


if __name__ == "__main__":
    sys.exit(main())
