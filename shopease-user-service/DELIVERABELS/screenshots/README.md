# Evidence Screenshots

Every image in this folder is a **real capture from the running system**, taken on 11 November 2026 between 17:14 and 17:22 (IST) against the Docker stacks of the User Service (8002) and the Authentication Service (8001). No image is a mock-up, and no response was edited. The only changes are the redactions listed below.

> **Status: 20 of 20 captured**, plus 5 extra images (`01b`, `18a`, and cross-user access `21`, `21b`, `21c`).

## How they were captured

| Images | Method |
| --- | --- |
| 05–18a, 21–21c (Swagger UI) | [`scripts/capture_swagger_screenshots.py`](../../scripts/capture_swagger_screenshots.py) registers a new dummy user (`asha.screenshot.1794397516@example.com`) on the real Authentication Service. It then drives the real Swagger UI pages in Microsoft Edge (headless, Playwright) through the whole flow: Login, Authorize, Try it out and Execute. Every request went to the running containers, and the script stopped if any status differed from the expected one. These steps were clicked by a script, not by hand |
| 01–04, 19, 20 (terminal) | Each command was run in a real PowerShell console window, and that window was captured. The first line in each image shows the exact command |

**Redactions:**
- **Token:** shortened to `eyJhbGciOi…<redacted>` before each capture.
- **Password:** the test password is shown as `<redacted>`.
- **Hidden in Swagger UI:**
  - the `curl` box, which repeats the token;
  - the static response documentation under each live response.
- **Check:** before saving each image, the script confirmed that neither the token nor the password was left on the page.
- **MySQL:** passwords are read inside the container (`$MYSQL_PASSWORD`) and never appear on screen.

## Required screenshots

| Done | File | What it shows |
| --- | --- | --- |
| [x] | `01_project_structure.png` | Project tree without `.venv` or caches. `app/`, `tests/` and the evidence folders are collapsed to file counts |
| [x] | `01b_project_structure_app_tests.png` | *(extra)* Full tree of `app/` and `tests/` |
| [x] | `02_docker_containers.png` | `docker compose ps`: `user-mysql` and `user-service` both **healthy**; only 8002 published, on 127.0.0.1 |
| [x] | `03_migration_log.png` | The service image started against a **throwaway, empty** MySQL 8.4 container (0 tables). The log shows `Running upgrade -> 8c2e3b6d4acf` and `8c2e3b6d4acf -> 4f1a9d27c5e3` before Uvicorn starts; the tables and `alembic_version` exist afterwards. The running stack's database was already at head, so its own log has nothing to upgrade. The throwaway containers were removed afterwards |
| [x] | `04_mysql_tables.png` | `SHOW TABLES`, `DESCRIBE user_profiles`, `DESCRIBE user_addresses` on `shopease_user_db` |
| [x] | `05_health_endpoints.png` | `GET /health` → `ok`; `GET /health/db` → `connected` |
| [x] | `06_swagger_ui.png` | Swagger UI on 8002 with all 18 operations and **Authorize** |
| [x] | `07_auth_login_token.png` | `POST /api/auth/login` on the Authentication Service (8001): 200; token and password redacted |
| [x] | `08_authorize_with_token.png` | Authorize dialog on 8002 after pasting the token: "Authorized", value `******` |
| [x] | `09_create_profile.png` | `POST /api/users/profile`: 201; `auth_user_id` 11 comes from the token |
| [x] | `10_get_profile.png` | `GET /api/users/profile`: 200 |
| [x] | `11_update_profile.png` | `PATCH /api/users/profile` (phone number): 200 |
| [x] | `12_create_address.png` | `POST /api/users/addresses` (HOME): 201, the first address becomes the default |
| [x] | `13_list_addresses.png` | `GET /api/users/addresses`: 200, three addresses (the response box scrolls) |
| [x] | `14_update_address.png` | `PUT /api/users/addresses/2077`: 200 |
| [x] | `15_set_default_address.png` | `PATCH /api/users/addresses/2077/default`: 200, `is_default: true` |
| [x] | `16_delete_address.png` | `DELETE /api/users/addresses/2078`: 200 `Address deleted` |
| [x] | `17_unauthorized_401.png` | `GET /api/users/profile` without a token: 401 `Could not validate credentials` |
| [x] | `18a_deactivate_account.png` | *(extra)* `PATCH /api/users/account/deactivate`: 200, `authentication_account_changed: false` |
| [x] | `18_forbidden_403.png` | Then `GET /api/users/profile`: 403 `User profile is deactivated`. Admin endpoints are not implemented, so there is no admin 403 |
| [x] | `19_mysql_data.png` | `SELECT` from `user_profiles` and `user_addresses`. Profile 2330 is the screenshot user (deactivated, `is_active` 0) with addresses 2076 and 2077 (2077 default); 2078 is gone |
| [x] | `20_pytest_results.png` | `pytest -v` in the project venv (SQLite): **518 passed, 1 warning in 17.49s** |

## Cross-user access denial (extra)

Captured by [`scripts/capture_cross_user_screenshots.py`](../../scripts/capture_cross_user_screenshots.py) at 17:38 IST. Two new dummy users each have a profile (A: `cross.a.1794398903@example.com`, profile 2332; B: `cross.b.1794398903@example.com`, profile 2333). A owns address 2081.

| Done | File | What it shows |
| --- | --- | --- |
| [x] | `21_cross_user_access_denied.png` | Swagger UI authorized as **B**: `GET /api/users/addresses/2081` (A's address): 404 `Address not found`, the same answer as for an address that does not exist |
| [x] | `21b_cross_user_delete_denied.png` | Authorized as **B**: `DELETE /api/users/addresses/2081`: 404 |
| [x] | `21c_owner_still_has_address.png` | Authorized as **A**: `GET /api/users/addresses/2081`: 200, address unchanged and still A's (`user_id` 2332) |

The images do not show which user is authorized (Swagger UI shows only `******`). The script authorized B's token for 21 and 21b and A's for 21c, and stopped if any status differed.

## Notes

- **Extra test data:** two earlier capture attempts stopped because of script timing errors, not API errors.
  - Auth user 9 was registered but has no profile.
  - Auth user 10 has an active profile (2329) with one address (2075).
  - Both are dummy `@example.com` accounts and are visible in `19_mysql_data.png`.
- **To repeat the Swagger captures:** run `python scripts/capture_swagger_screenshots.py` with both stacks running. It needs `playwright` and `httpx`, which are not in `requirements.txt`, and Microsoft Edge.
- **To delete the test data:** run `docker compose down -v` (this deletes all User Service data).
