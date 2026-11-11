"""Capture the Swagger UI evidence screenshots from the running services.

Registers one new dummy user on the running Authentication Service (8001), then drives the real
Swagger UI pages on 8001 and 8002 in Microsoft Edge (headless, via Playwright) through the whole
customer flow, and saves a screenshot of each step in DELIVERABELS/screenshots/.

Before every screenshot, any JWT on the page is shortened to its first 10 characters and the test
password is replaced with <redacted>; the script then checks that neither value is left in the page
and stops if one is. The curl box (which repeats the token) and the static response documentation
below each live response are hidden. Nothing else on the page is changed.

    python scripts/capture_swagger_screenshots.py
"""
import json
import re
import secrets
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

AUTH = "http://127.0.0.1:8001"
USER = "http://127.0.0.1:8002"
OUT = Path(__file__).resolve().parent.parent / "DELIVERABELS" / "screenshots"
HIDE_CSS = ".curl-command, .responses-table:not(.live-responses-table) { display: none !important; }"
MASK_JS = r"""(secrets) => {
  const jwt = /eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*/g;
  const clean = s => {
    s = s.replace(jwt, m => m.slice(0, 10) + '…<redacted>');
    for (const v of secrets) s = s.split(v).join('<redacted>');
    return s;
  };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) n.nodeValue = clean(n.nodeValue);
  document.querySelectorAll('textarea, input').forEach(e => { e.value = clean(e.value); });
  const text = document.body.innerText + [...document.querySelectorAll('textarea, input')].map(e => e.value).join(' ');
  return secrets.some(v => text.includes(v)) || /eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}/.test(text);
}"""

# Every password and token used on the pages; mask() hides them and refuses to save if one is left.
SECRETS = []
saved = []


def mask(page):
    if page.evaluate(MASK_JS, SECRETS):
        sys.exit("A token or a password is still visible; screenshot not saved.")


def shot(target, name):
    page = target.page if hasattr(target, "page") else target
    mask(page)
    path = OUT / name
    if hasattr(target, "page"):
        target.screenshot(path=path)
    else:
        target.screenshot(path=path, full_page=True)
    saved.append(name)
    print(f"saved {name}")


def operation(page, method, path):
    block = page.locator(f'div.opblock.opblock-{method}:has(.opblock-summary-path[data-path="{path}"])')
    if "is-open" not in (block.get_attribute("class") or ""):
        block.locator(".opblock-summary-control").click()
    return block


def execute(page, method, path, expected, body=None, address_id=None):
    block = operation(page, method, path)
    try_out = block.locator("button.try-out__btn").first
    try_out.wait_for()
    if try_out.inner_text().strip() == "Try it out":
        try_out.click()
    clear = block.locator("button.btn-clear")
    if clear.count():
        clear.click()
        block.locator(".live-responses-table").wait_for(state="detached")
    if body is not None:
        block.locator("textarea.body-param__text").fill(json.dumps(body, indent=2))
    if address_id is not None:
        block.locator('input[placeholder="address_id"]').fill(str(address_id))
    block.locator("button.execute").click()
    status = block.locator(".live-responses-table .response .response-col_status")
    status.wait_for()
    code = int(status.inner_text().strip())
    if code != expected:
        sys.exit(f"{method.upper()} {path}: expected {expected}, got {code}")
    text = block.locator(".live-responses-table .response-col_description pre").first.inner_text()
    block.scroll_into_view_if_needed()
    return block, (json.loads(text) if text.strip().startswith(("{", "[")) else text)


def open_docs(page, base):
    page.goto(f"{base}/docs")
    page.locator("div.opblock").first.wait_for()
    page.add_style_tag(content=HIDE_CSS)


def address(kind, line, city):
    return {"address_type": kind, "full_name": "Asha Test", "phone_number": "9876543210",
            "address_line_1": line, "city": city, "state": "Maharashtra", "country": "India",
            "postal_code": "411001"}


def register(email, password, full_name):
    """Register a dummy user on the running Authentication Service; return its access token."""
    SECRETS.append(password)
    response = httpx.post(f"{AUTH}/api/auth/register", json={
        "full_name": full_name, "email": email, "password": password, "confirm_password": password})
    if response.status_code != 201:
        sys.exit(f"register: expected 201, got {response.status_code}")
    token = httpx.post(f"{AUTH}/api/auth/login", json={"email": email, "password": password}).json()["access_token"]
    SECRETS.append(token)
    return token


def authorize(page, token):
    page.locator("button.authorize").first.click()
    dialog = page.locator(".dialog-ux .modal-ux")
    dialog.locator("input").first.fill(token)
    dialog.locator("button.authorize").click()
    dialog.locator("button.btn-done").wait_for()
    return dialog


def main():
    stamp = int(time.time())
    email = f"asha.screenshot.{stamp}@example.com"
    password = "Sc!" + secrets.token_urlsafe(16) + "7z"
    SECRETS.append(password)
    registered = httpx.post(f"{AUTH}/api/auth/register", json={
        "full_name": "Asha Test", "email": email, "password": password, "confirm_password": password})
    if registered.status_code != 201:
        sys.exit(f"register: expected 201, got {registered.status_code}")
    print(f"registered {email} on the Authentication Service")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        open_docs(page, USER)
        page.screenshot(path=OUT / "06_swagger_ui.png", full_page=True)
        saved.append("06_swagger_ui.png")
        print("saved 06_swagger_ui.png")

        first, _ = execute(page, "get", "/health", 200)
        second, db = execute(page, "get", "/health/db", 200)
        if db.get("database") != "connected":
            sys.exit("/health/db did not report connected")
        mask(page)
        page.evaluate("window.scrollTo(0, 0)")
        a, b = first.bounding_box(), second.bounding_box()
        page.screenshot(path=OUT / "05_health_endpoints.png", full_page=True,
                        clip={"x": a["x"], "y": a["y"], "width": a["width"], "height": b["y"] + b["height"] - a["y"]})
        saved.append("05_health_endpoints.png")
        print("saved 05_health_endpoints.png")

        auth_page = browser.new_page(viewport={"width": 1280, "height": 900})
        open_docs(auth_page, AUTH)
        block, login = execute(auth_page, "post", "/api/auth/login", 200, {"email": email, "password": password})
        token = login["access_token"]
        SECRETS.append(token)
        shot(block, "07_auth_login_token.png")

        page.reload()
        open_docs(page, USER)
        dialog = authorize(page, token)
        shot(dialog, "08_authorize_with_token.png")
        dialog.locator("button.btn-done").click()

        profile = {"full_name": "Asha Test", "phone_number": "9876543210", "date_of_birth": "1998-04-12",
                   "gender": "FEMALE"}
        block, _ = execute(page, "post", "/api/users/profile", 201, profile)
        shot(block, "09_create_profile.png")
        block, _ = execute(page, "get", "/api/users/profile", 200)
        shot(block, "10_get_profile.png")
        block, _ = execute(page, "patch", "/api/users/profile", 200, {"phone_number": "9123456780"})
        shot(block, "11_update_profile.png")

        block, home = execute(page, "post", "/api/users/addresses", 201, address("HOME", "12 MG Road", "Pune"))
        shot(block, "12_create_address.png")
        _, office = execute(page, "post", "/api/users/addresses", 201, address("OFFICE", "4th Floor, Tech Park", "Pune"))
        _, other = execute(page, "post", "/api/users/addresses", 201, address("OTHER", "7 Lake View", "Nashik"))
        block, listed = execute(page, "get", "/api/users/addresses", 200)
        if len(listed) < 2:
            sys.exit("expected more than one address")
        shot(block, "13_list_addresses.png")
        block, _ = execute(page, "put", "/api/users/addresses/{address_id}", 200,
                           address("OFFICE", "5th Floor, Tech Park", "Pune"), office["id"])
        shot(block, "14_update_address.png")
        block, default = execute(page, "patch", "/api/users/addresses/{address_id}/default", 200, address_id=office["id"])
        if default.get("is_default") is not True:
            sys.exit("set default did not return is_default true")
        shot(block, "15_set_default_address.png")
        block, _ = execute(page, "delete", "/api/users/addresses/{address_id}", 200, address_id=other["id"])
        shot(block, "16_delete_address.png")

        anonymous = browser.new_page(viewport={"width": 1280, "height": 900})
        open_docs(anonymous, USER)
        block, _ = execute(anonymous, "get", "/api/users/profile", 401)
        shot(block, "17_unauthorized_401.png")

        block, _ = execute(page, "patch", "/api/users/account/deactivate", 200)
        shot(block, "18a_deactivate_account.png")
        block, forbidden = execute(page, "get", "/api/users/profile", 403)
        if forbidden.get("detail") != "User profile is deactivated":
            sys.exit("unexpected 403 detail")
        shot(block, "18_forbidden_403.png")

        browser.close()

    print(f"{len(saved)} screenshots saved; test user {email} (profile now deactivated)")


if __name__ == "__main__":
    main()
