# 10 – Teams Progress Updates

Short updates for the team channel, ready to copy. Every number comes from a run recorded in this folder. These texts have been prepared but **not posted**: posting them is up to the author.

## Day 1 – 10 November 2026

> **ShopEase User Service – Day 1 update**
>
> **Done:**
> - Set up the User Service as an independent FastAPI microservice (port 8002) with its own MySQL database `shopease_user_db`.
> - Created the SQLAlchemy models `user_profiles` and `user_addresses`, and an Alembic migration that creates both tables. Upgrade and downgrade were verified on MySQL.
> - Added JWT integration: every request's token is checked by the Authentication Service's `POST /api/auth/verify-token`. The User Service holds no JWT secret, and takes the user's identity only from that response.
> - Built the profile API (`POST`, `GET`, `PUT`, `PATCH`, `DELETE /api/users/profile`). Each user can reach only their own profile, and DELETE deactivates the profile without deleting it.
>
> **Tests:** 168 passed on SQLite and on MySQL: 87 profile, 57 token verification, 17 database, and 7 startup tests.
>
> **Next:** address API, account management, Docker, and a live test with the real Authentication Service.
>
> **Blockers:** none.

## Day 2 – 11 November 2026

> **ShopEase User Service – Day 2 update**
>
> **Done:**
> - **Address API:** create, list, get, update and delete addresses, set a default, and read the default address.
>   - Address types are Home, Office and Other.
>   - Each profile always has exactly one default. Writes are protected by a transaction and a row lock, and 300 concurrent changes left exactly 1 default.
> - **Account management:** an account overview, a contact (phone) update, and deactivation. Deactivation affects only the User Service profile and never the login account.
> - **Security audit (20 test cases):** no way found for one customer to read or change another customer's data. One low issue was fixed.
> - **Docker Compose:** the service and MySQL both run healthy, migrations run before the API starts, and MySQL is not published. The container reaches the Authentication Service through `host.docker.internal`.
> - **Live test with the real Authentication Service:** real tokens accepted, and invalid or missing tokens get 401. With the Authentication Service down, requests get 503.
> - **Documentation:** README, reports 01–10, 4 Word documents, a Postman collection, and screenshots of the live system (including cross-user access denial).
>
> **Tests:**
> - 518/518 pytest tests pass on SQLite and MySQL.
> - Live audit against Docker: 73/73.
> - Postman (Newman): 38/38 assertions.
>
> **Open:**
> - Admin endpoints (list, read, reactivate) are not implemented.
>
> **Blockers:** none.

## Shorter versions (one message each)

**Day 1:** User Service set up (FastAPI, port 8002, own MySQL database). Models and the Alembic migration are done. JWT verification goes through the Auth Service's verify-token endpoint, with no shared secret. The profile API is complete, and its tests pass on SQLite and MySQL. Next: addresses and Docker.

**Day 2:** The address API (with exactly one default address), account management and deactivation are done. Security audit: 20 test cases, no cross-customer access found. Docker Compose runs healthy, with a live token test against the real Auth Service. 518/518 tests pass, the live audit 73/73, and Postman 38/38. Docs, reports and Word files are done. 20 live screenshots captured. Open: admin endpoints.
