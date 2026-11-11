"""Live API audit: every User Service route against the running services.

Registers two new users on the running Authentication Service (8001) and calls every
User Service endpoint (8002) with their real access tokens. Prints sanitized results only:
no token, no password. Exit code 1 if any check fails.

    python scripts/live_api_audit.py [token_file]

If token_file is given, the two tokens are written to it so the logs can be searched for
them afterwards. Delete that file when done.
"""
import re
import secrets
import sys
import time

import httpx

AUTH = "http://127.0.0.1:8001/api/auth"
BASE = "http://127.0.0.1:8002"
USERS = f"{BASE}/api/users"
token_file = sys.argv[1] if len(sys.argv) > 1 else None
results = []


def check(label, response, expected, condition=True, note=""):
    ok = response.status_code == expected and bool(condition)
    results.append(ok)
    body = re.sub(r'"access_token":"[^"]*', '"access_token":"<redacted>', response.text.replace("\n", " "))
    body = body if len(body) <= 160 else body[:160] + "..."
    print(f"{'PASS' if ok else 'FAIL'} | {label} | expected {expected}, got {response.status_code}"
          f"{' | ' + note if note else ''} | {body}")
    return response


def address(kind, line, **extra):
    return {"address_type": kind, "full_name": "Audit Customer", "phone_number": "9876543210",
            "address_line_1": line, "city": "Pune", "state": "Maharashtra", "country": "India",
            "postal_code": "411001", **extra}


stamp = int(time.time())
http = httpx.Client(timeout=10)

print("== Health ==")
check("GET /health", http.get(f"{BASE}/health"), 200)
check("GET /health/db (MySQL connection)", http.get(f"{BASE}/health/db"), 200,
      http.get(f"{BASE}/health/db").json().get("database") == "connected")
check("GET / (service info)", http.get(f"{BASE}/"), 200)

print("== Real users from the Authentication Service ==")
users = {}
for name in ("A", "B"):
    email = f"final.audit.{name.lower()}.{stamp}@example.com"
    password = "Fa!" + secrets.token_urlsafe(16) + "7z"
    check(f"register user {name} (8001)", http.post(f"{AUTH}/register", json={
        "full_name": f"Audit User {name}", "email": email, "password": password,
        "confirm_password": password}), 201)
    login = check(f"login user {name} (8001)", http.post(f"{AUTH}/login",
                  json={"email": email, "password": password}), 200)
    users[name] = {"email": email, "password": password, "token": login.json()["access_token"],
                   "id": login.json()["user"]["id"]}
    print(f"     user {name}: {email}, auth id {users[name]['id']}, token {users[name]['token'][:10]}... (redacted)")
if token_file:
    with open(token_file, "w") as f:
        f.write("\n".join(u["token"] for u in users.values()))
A = {"Authorization": f"Bearer {users['A']['token']}"}
B = {"Authorization": f"Bearer {users['B']['token']}"}

print("== JWT verification through the Authentication Service ==")
check("no token", http.get(f"{USERS}/profile"), 401)
check("malformed token", http.get(f"{USERS}/profile", headers={"Authorization": "Bearer not-a-jwt"}), 401)
tampered = users["A"]["token"][:-2] + ("AA" if users["A"]["token"][-2:] != "AA" else "BB")
check("token with altered signature", http.get(f"{USERS}/profile", headers={"Authorization": f"Bearer {tampered}"}), 401)
check("wrong scheme (Basic)", http.get(f"{USERS}/profile", headers={"Authorization": "Basic abc"}), 401)
acc = check("GET /account with A's real token, no profile yet", http.get(f"{USERS}/account", headers=A), 200)
check("  identity comes from the token", acc, 200,
      acc.json()["authentication_account"]["auth_user_id"] == users["A"]["id"]
      and acc.json()["profile_status"] == "NOT_CREATED", note="auth_user_id matches, NOT_CREATED")

print("== Profile API (user A) ==")
check("GET /profile before creation", http.get(f"{USERS}/profile", headers=A), 404)
check("POST /profile with client auth_user_id=999999", http.post(f"{USERS}/profile", headers=A,
      json={"full_name": "Audit User A", "auth_user_id": 999999}), 422, note="identity override refused")
created = check("POST /profile", http.post(f"{USERS}/profile", headers=A, json={
    "full_name": "Audit User A", "phone_number": "9876543210", "gender": "FEMALE"}), 201)
check("  profile linked to token identity", created, 201, created.json()["auth_user_id"] == users["A"]["id"])
check("POST /profile again", http.post(f"{USERS}/profile", headers=A, json={"full_name": "Dup"}), 409)
check("GET /profile", http.get(f"{USERS}/profile", headers=A), 200)
put = check("PUT /profile (full replacement)", http.put(f"{USERS}/profile", headers=A, json={
    "full_name": "Audit User A Replaced", "date_of_birth": "1995-04-12"}), 200)
check("  PUT cleared omitted fields", put, 200, put.json()["phone_number"] is None and put.json()["gender"] is None)
check("PATCH /profile (partial)", http.patch(f"{USERS}/profile", headers=A, json={"gender": "FEMALE"}), 200)
check("PATCH /profile invalid phone", http.patch(f"{USERS}/profile", headers=A, json={"phone_number": "12ab"}), 422)

print("== Account API (user A) ==")
contact = check("PATCH /account/contact", http.patch(f"{USERS}/account/contact", headers=A,
                json={"phone_number": "+91 98765 43210"}), 200)
check("PATCH /account/contact with email", http.patch(f"{USERS}/account/contact", headers=A,
      json={"phone_number": None, "email": "x@example.com"}), 422, note="email belongs to the auth service")
acc = check("GET /account", http.get(f"{USERS}/account", headers=A), 200)
check("  profile ACTIVE", acc, 200, acc.json()["profile_status"] == "ACTIVE")

print("== Address API (user A) ==")
check("GET /addresses (empty)", http.get(f"{USERS}/addresses", headers=A), 200,
      http.get(f"{USERS}/addresses", headers=A).json() == [])
check("GET /addresses/default with none", http.get(f"{USERS}/addresses/default", headers=A), 404)
a1 = check("POST /addresses HOME (first)", http.post(f"{USERS}/addresses", headers=A,
           json=address("HOME", "1 First Street")), 201)
check("  first address becomes default", a1, 201, a1.json()["is_default"] is True)
a2 = check("POST /addresses OFFICE is_default=true", http.post(f"{USERS}/addresses", headers=A,
           json=address("OFFICE", "2 Office Park", is_default=True)), 201)
a3 = check("POST /addresses OTHER", http.post(f"{USERS}/addresses", headers=A,
           json=address("OTHER", "3 Other Lane", address_line_2="Floor 2")), 201)
id1, id2, id3 = a1.json()["id"], a2.json()["id"], a3.json()["id"]
check("POST /addresses with client user_id", http.post(f"{USERS}/addresses", headers=A,
      json=address("HOME", "4 X", user_id=1)), 422, note="identity override refused")
check("POST /addresses type WORK", http.post(f"{USERS}/addresses", headers=A,
      json=address("WORK", "4 X")), 422)
check("POST /addresses missing city", http.post(f"{USERS}/addresses", headers=A,
      json={k: v for k, v in address("HOME", "4 X").items() if k != "city"}), 422)
listed = check("GET /addresses", http.get(f"{USERS}/addresses", headers=A), 200)
defaults = [x["id"] for x in listed.json() if x["is_default"]]
check("  3 addresses, exactly one default (the OFFICE one), listed first", listed, 200,
      len(listed.json()) == 3 and defaults == [id2] and listed.json()[0]["id"] == id2)
check("GET /addresses/{id}", http.get(f"{USERS}/addresses/{id1}", headers=A), 200)
check("PUT /addresses/{id}", http.put(f"{USERS}/addresses/{id1}", headers=A,
      json=address("HOME", "1 First Street, Updated")), 200)
check("PATCH /addresses/{id}/default", http.patch(f"{USERS}/addresses/{id3}/default", headers=A), 200)
listed = http.get(f"{USERS}/addresses", headers=A).json()
check("  exactly one default after the change", httpx.Response(200), 200,
      [x["id"] for x in listed if x["is_default"]] == [id3])
default = check("GET /addresses/default", http.get(f"{USERS}/addresses/default", headers=A), 200)
check("  default is the new one", default, 200, default.json()["id"] == id3)
check("DELETE /addresses/{id} (the default)", http.delete(f"{USERS}/addresses/{id3}", headers=A), 200)
check("GET deleted address", http.get(f"{USERS}/addresses/{id3}", headers=A), 404)
default = check("GET /addresses/default after deleting it", http.get(f"{USERS}/addresses/default", headers=A), 200)
check("  oldest remaining address promoted", default, 200, default.json()["id"] == id1)
check("GET /addresses/0 (invalid id)", http.get(f"{USERS}/addresses/0", headers=A), 422)

print("== Ownership: user B against user A's data ==")
check("B: POST /profile", http.post(f"{USERS}/profile", headers=B, json={"full_name": "Audit User B"}), 201)
check("B: GET A's address", http.get(f"{USERS}/addresses/{id1}", headers=B), 404)
check("B: PUT A's address", http.put(f"{USERS}/addresses/{id1}", headers=B, json=address("HOME", "hijack")), 404)
check("B: PATCH A's address default", http.patch(f"{USERS}/addresses/{id2}/default", headers=B), 404)
check("B: DELETE A's address", http.delete(f"{USERS}/addresses/{id2}", headers=B), 404)
check("B: GET /addresses shows none of A's", http.get(f"{USERS}/addresses", headers=B), 200,
      http.get(f"{USERS}/addresses", headers=B).json() == [])
b1 = check("B: POST /addresses", http.post(f"{USERS}/addresses", headers=B, json=address("HOME", "9 B Road")), 201)
check("A: GET B's address", http.get(f"{USERS}/addresses/{b1.json()['id']}", headers=A), 404)
after = http.get(f"{USERS}/addresses", headers=A).json()
check("A's addresses unchanged after B's attempts", httpx.Response(200), 200,
      sorted(x["id"] for x in after) == sorted([id1, id2])
      and next(x for x in after if x["id"] == id1)["address_line_1"] == "1 First Street, Updated")
b_profile = http.get(f"{USERS}/profile", headers=B).json()
check("B's profile is B's own", httpx.Response(200), 200, b_profile["auth_user_id"] == users["B"]["id"])
check("GET /api/users/{id} (admin route)", http.get(f"{USERS}/{users['A']['id']}", headers=A), 404,
      note="not implemented")

print("== Account deactivation (user A) ==")
deact = check("PATCH /account/deactivate", http.patch(f"{USERS}/account/deactivate", headers=A), 200)
check("  local profile only", deact, 200, deact.json()["authentication_account_changed"] is False
      and deact.json()["profile_status"] == "DEACTIVATED")
check("deactivated: GET /profile", http.get(f"{USERS}/profile", headers=A), 403)
check("deactivated: PATCH /profile", http.patch(f"{USERS}/profile", headers=A, json={"gender": "OTHER"}), 403)
check("deactivated: GET /addresses", http.get(f"{USERS}/addresses", headers=A), 403)
check("deactivated: POST /addresses", http.post(f"{USERS}/addresses", headers=A, json=address("HOME", "5 X")), 403)
check("deactivated: GET /addresses/default", http.get(f"{USERS}/addresses/default", headers=A), 403)
check("deactivated: GET /account", http.get(f"{USERS}/account", headers=A), 403)
check("deactivated: PATCH /account/deactivate again", http.patch(f"{USERS}/account/deactivate", headers=A), 403)
verify = check("auth service: verify-token for A still valid", http.post(f"{AUTH}/verify-token", headers=A), 200)
check("  auth account still active", verify, 200, verify.json()["user"]["is_active"] is True)
check("auth service: A can still log in", http.post(f"{AUTH}/login", json={
    "email": users["A"]["email"], "password": users["A"]["password"]}), 200)
check("B unaffected by A's deactivation", http.get(f"{USERS}/profile", headers=B), 200)

print(f"\nauth ids: A={users['A']['id']} B={users['B']['id']}; A addresses kept: {id1},{id2}")
print(f"RESULT: {sum(results)} passed, {len(results) - sum(results)} failed, {len(results)} checks")
sys.exit(0 if all(results) else 1)
