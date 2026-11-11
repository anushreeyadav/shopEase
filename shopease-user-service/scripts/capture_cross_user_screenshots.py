"""Capture the cross-user access screenshots from the running services.

Registers two new dummy users (A and B) on the running Authentication Service. Both get a profile,
and A adds an address. Then, in the real Swagger UI on 8002 authorized as B, it tries to read and
delete A's address (both must return 404), and finally reads the same address as A (must return 200,
unchanged). Tokens and passwords are masked as in capture_swagger_screenshots.py.

    python scripts/capture_cross_user_screenshots.py
"""
import secrets
import sys
import time

import httpx
from playwright.sync_api import sync_playwright

from capture_swagger_screenshots import USER, authorize, execute, open_docs, register, saved, shot

stamp = int(time.time())
users = {}
for name, full_name in (("a", "Ravi Owner"), ("b", "Meera Other")):
    email = f"cross.{name}.{stamp}@example.com"
    users[name] = register(email, "Cu!" + secrets.token_urlsafe(16) + "7z", full_name)
    profile = httpx.post(f"{USER}/api/users/profile", json={"full_name": full_name},
                         headers={"Authorization": f"Bearer {users[name]}"})
    if profile.status_code != 201:
        sys.exit(f"profile {name}: expected 201, got {profile.status_code}")
    print(f"user {name.upper()}: {email}, profile {profile.json()['id']}")

address = httpx.post(f"{USER}/api/users/addresses", headers={"Authorization": f"Bearer {users['a']}"}, json={
    "address_type": "HOME", "full_name": "Ravi Owner", "phone_number": "9876543210",
    "address_line_1": "21 Residency Road", "city": "Bengaluru", "state": "Karnataka",
    "country": "India", "postal_code": "560025"})
if address.status_code != 201:
    sys.exit(f"address: expected 201, got {address.status_code}")
address_id = address.json()["id"]
print(f"user A's address: {address_id}")

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)

    as_b = browser.new_page(viewport={"width": 1280, "height": 900})
    open_docs(as_b, USER)
    authorize(as_b, users["b"]).locator("button.btn-done").click()
    block, _ = execute(as_b, "get", "/api/users/addresses/{address_id}", 404, address_id=address_id)
    shot(block, "21_cross_user_access_denied.png")
    block, _ = execute(as_b, "delete", "/api/users/addresses/{address_id}", 404, address_id=address_id)
    shot(block, "21b_cross_user_delete_denied.png")

    as_a = browser.new_page(viewport={"width": 1280, "height": 900})
    open_docs(as_a, USER)
    authorize(as_a, users["a"]).locator("button.btn-done").click()
    block, owned = execute(as_a, "get", "/api/users/addresses/{address_id}", 200, address_id=address_id)
    if owned.get("address_line_1") != "21 Residency Road":
        sys.exit("user A's address changed")
    shot(block, "21c_owner_still_has_address.png")

    browser.close()

print(f"{len(saved)} screenshots saved")
