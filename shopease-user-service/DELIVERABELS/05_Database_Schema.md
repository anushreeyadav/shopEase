# 05 â€“ Database Schema

| | |
| --- | --- |
| Database | `shopease_user_db` (MySQL 8.4, container `user-mysql`; published on host port 3309 only with `docker-compose.dev.yml`) |
| Owned by | ShopEase User Service only. Separate from the Authentication Service's `shopease_auth_db` |
| Created by | Alembic migrations `8c2e3b6d4acf` (create user and address tables) and `4f1a9d27c5e3` (rename WORK address type to OFFICE). No table is created by hand or by `create_all()` |
| Models | [user_model.py](../app/models/user_model.py), [address_model.py](../app/models/address_model.py) |
| Verified | 10 November 2026 (tables) and 11 November 2026 (address types, address transactions), against the running `user-mysql` container. All output below is from that database |

## Relationship diagram

```
 shopease_auth_db  (Authentication Service)
 +------------------+
 | users            |
 |  id  ------------+---- returned as user.id by POST /api/auth/verify-token
 |  email, password |     (logical reference only, no foreign key across databases)
 |  role, is_active |
 +------------------+
          :
          :  auth_user_id
          v
 shopease_user_db  (this service)
 +----------------------------+  1        0..n  +------------------------------------+
 | user_profiles              |<----------------| user_addresses                     |
 |  id               PK       |                 |  id               PK               |
 |  auth_user_id     UNIQUE   |                 |  user_id          FK -> user_profiles.id
 |  full_name                 |                 |                   ON DELETE CASCADE, indexed
 |  phone_number              |                 |  address_type   HOME/OFFICE/OTHER  |
 |  date_of_birth             |                 |  full_name, phone_number           |
 |  gender                    |                 |  address_line_1/2, city, state,    |
 |  profile_image             |                 |  country, postal_code              |
 |  is_active                 |                 |  is_default                        |
 |  created_at, updated_at    |                 |  default_marker   (generated)      |
 +----------------------------+                 |  created_at                        |
                                                +------------------------------------+
```

## How the tables relate

**1. Authentication Service user â†’ `user_profiles` (one to zero-or-one).**
Every request to this service carries a token. The Authentication Service checks it and returns the user's ID, which is stored as `user_profiles.auth_user_id`.
- The unique constraint `uq_user_profiles_auth_user_id` allows at most one profile per user. MySQL backs it with a unique index, which also makes the lookup on every request fast.
- It cannot be a foreign key, because the `users` table is in a different service's database. The link is trusted because only the Authentication Service supplies the ID, never the request body.
- Deleting a user in the Authentication Service does not delete the profile here. That user's tokens are rejected from then on, so the profile can no longer be reached.

**2. `user_profiles` â†’ `user_addresses` (one to many).**
`user_addresses.user_id` is a real foreign key to `user_profiles.id`. It is the **local profile ID, not the Authentication Service user ID**.

| Level | Setting | Effect |
| --- | --- | --- |
| Database | `fk_user_addresses_user_id_user_profiles`, `ON DELETE CASCADE` | Deleting a profile row deletes its addresses, even when done in SQL |
| Database | `ON UPDATE NO ACTION` | Profile IDs are auto-increment and never change |
| Database | `ix_user_addresses_user_id` | Index for the foreign key and for listing a user's addresses |
| ORM | `UserProfile.addresses`, `cascade="all, delete-orphan"` | An address removed from `profile.addresses` is deleted. New addresses are saved with their profile |
| ORM | `passive_deletes=True` | Deleting a profile leaves the address rows to the database cascade, instead of loading them first |
| ORM | `UserAddress.user_profile` (`back_populates`) | Navigation from an address to its profile |

**3. Profile deactivation is not deletion.**
`user_profiles.is_active` belongs to this service. Setting it to false hides the profile and keeps its addresses, and setting it back restores them. It is separate from the user's `is_active` in the Authentication Service:

| Authentication Service `is_active` | User Service `is_active` | Result |
| --- | --- | --- |
| true | true | Normal access |
| true | false | Token accepted, profile treated as deactivated |
| false | any | Token rejected with 403 before the database is queried |

## `user_profiles`

```
+---------------+--------------+------+-----+---------+-------------------+
| Field         | Type         | Null | Key | Default | Extra             |
+---------------+--------------+------+-----+---------+-------------------+
| id            | int          | NO   | PRI | NULL    | auto_increment    |
| auth_user_id  | int          | NO   | UNI | NULL    |                   |
| full_name     | varchar(255) | NO   |     | NULL    |                   |
| phone_number  | varchar(20)  | YES  |     | NULL    |                   |
| date_of_birth | date         | YES  |     | NULL    |                   |
| gender        | varchar(20)  | YES  |     | NULL    |                   |
| profile_image | varchar(500) | YES  |     | NULL    |                   |
| is_active     | tinyint(1)   | NO   |     | 1       |                   |
| created_at    | datetime     | NO   |     | now()   | DEFAULT_GENERATED |
| updated_at    | datetime     | NO   |     | now()   | DEFAULT_GENERATED |
+---------------+--------------+------+-----+---------+-------------------+
```

| Column | Rules |
| --- | --- |
| `auth_user_id` | Authentication Service user ID. Unique constraint `uq_user_profiles_auth_user_id` |
| `phone_number` | Normalized (see below). Optional |
| `date_of_birth` | Not in the future (request schema) |
| `gender` | `MALE`, `FEMALE`, `OTHER`, `PREFER_NOT_TO_SAY`, or NULL. CHECK `ck_user_profiles_gender` |
| `profile_image` | Image URL, `http` or `https` (request schema). The file itself is not stored |
| `is_active` | Local profile status. `NOT NULL DEFAULT 1` |
| `created_at`, `updated_at` | UTC. `updated_at` changes on every ORM update |

**No credentials:** this table has no email, password, password hash, token, username, or login column. A unit test fails if one is added.

## `user_addresses`

```
+----------------+--------------+------+-----+---------+-------------------+
| Field          | Type         | Null | Key | Default | Extra             |
+----------------+--------------+------+-----+---------+-------------------+
| id             | int          | NO   | PRI | NULL    | auto_increment    |
| user_id        | int          | NO   | MUL | NULL    |                   |
| address_type   | varchar(20)  | NO   |     | HOME    |                   |
| full_name      | varchar(255) | NO   |     | NULL    |                   |
| phone_number   | varchar(20)  | NO   |     | NULL    |                   |
| address_line_1 | varchar(255) | NO   |     | NULL    |                   |
| address_line_2 | varchar(255) | YES  |     | NULL    |                   |
| city           | varchar(100) | NO   |     | NULL    |                   |
| state          | varchar(100) | NO   |     | NULL    |                   |
| country        | varchar(100) | NO   |     | NULL    |                   |
| postal_code    | varchar(20)  | NO   |     | NULL    |                   |
| is_default     | tinyint(1)   | NO   |     | 0       |                   |
| default_marker | int          | YES  |     | NULL    | STORED GENERATED  |
| created_at     | datetime     | NO   |     | now()   | DEFAULT_GENERATED |
+----------------+--------------+------+-----+---------+-------------------+
```

| Column | Rules |
| --- | --- |
| `user_id` | FK to `user_profiles.id`, ON DELETE CASCADE, indexed |
| `address_type` | `HOME`, `OFFICE`, or `OTHER`. Default `HOME`. CHECK `ck_user_addresses_address_type`: ``(`address_type` in ('HOME','OFFICE','OTHER'))`` |
| `full_name` | The recipient's name, which may differ from the profile's name |
| `phone_number` | The recipient's phone number, normalized. Required |
| `is_default` | At most one true per user (see below) |
| `default_marker` | Generated by MySQL: 1 when `is_default`, otherwise NULL. Never written by the application |

### One default address per user

MySQL has no partial unique index, such as "unique `user_id` where `is_default`". The table uses a stored generated column instead:

```sql
default_marker INT GENERATED ALWAYS AS (CASE WHEN is_default THEN 1 ELSE NULL END) STORED,
CONSTRAINT uq_user_addresses_one_default_per_user UNIQUE (user_id, default_marker)
```

A unique index allows any number of NULLs, so a user can have many non-default addresses, but only one row with `(user_id, 1)`. To change the default, the service clears the old default and flushes before setting the new one, all in one transaction (see [Address transactions](#address-transactions-and-locking)).

The generated column deliberately reads only `is_default`, not `user_id`. MySQL does not allow `ON DELETE CASCADE` on a column that a stored generated column is computed from (error 1215). An earlier draft did this and was rejected, so it was redesigned before any migration was kept.

## Constraints, indexes and foreign keys (from `information_schema`)

```
+----------------+-----------------------------------------+-----------------+
| TABLE_NAME     | CONSTRAINT_NAME                         | CONSTRAINT_TYPE |
+----------------+-----------------------------------------+-----------------+
| user_addresses | ck_user_addresses_address_type          | CHECK           |
| user_addresses | fk_user_addresses_user_id_user_profiles | FOREIGN KEY     |
| user_addresses | PRIMARY                                 | PRIMARY KEY     |
| user_addresses | uq_user_addresses_one_default_per_user  | UNIQUE          |
| user_profiles  | ck_user_profiles_gender                 | CHECK           |
| user_profiles  | PRIMARY                                 | PRIMARY KEY     |
| user_profiles  | uq_user_profiles_auth_user_id           | UNIQUE          |
+----------------+-----------------------------------------+-----------------+

+----------------+----------------------------------------+------------------------+------------+
| TABLE_NAME     | INDEX_NAME                             | cols                   | kind       |
+----------------+----------------------------------------+------------------------+------------+
| user_addresses | ix_user_addresses_user_id              | user_id                | non-unique |
| user_addresses | PRIMARY                                | id                     | unique     |
| user_addresses | uq_user_addresses_one_default_per_user | user_id,default_marker | unique     |
| user_profiles  | PRIMARY                                | id                     | unique     |
| user_profiles  | uq_user_profiles_auth_user_id          | auth_user_id           | unique     |
+----------------+----------------------------------------+------------------------+------------+

+-----------------------------------------+----------------+-----------------------+-------------+-------------+
| CONSTRAINT_NAME                         | TABLE_NAME     | REFERENCED_TABLE_NAME | DELETE_RULE | UPDATE_RULE |
+-----------------------------------------+----------------+-----------------------+-------------+-------------+
| fk_user_addresses_user_id_user_profiles | user_addresses | user_profiles         | CASCADE     | NO ACTION   |
+-----------------------------------------+----------------+-----------------------+-------------+-------------+
```

## Address transactions and locking

Code: [address_service.py](../app/services/address_service.py). Every address write (create, replace, delete, set default) works like this:

```
BEGIN
  SELECT ... FROM user_profiles WHERE auth_user_id = :caller FOR UPDATE   -- lock the owner
  SELECT ... FROM user_addresses WHERE id = :address_id AND user_id = :profile_id
  UPDATE user_addresses SET is_default = 0 WHERE id = :old_default        -- flushed first
  UPDATE user_addresses SET is_default = 1 WHERE id = :new_default
COMMIT          -- or ROLLBACK if any statement fails
```

| Rule | How |
| --- | --- |
| **Ownership** | Every address query filters on `user_id` = the caller's profile ID, which comes from the verified token. Another user's address is simply not found |
| **One transaction** | `_transaction()` commits once at the end. On any exception it rolls back everything and re-raises, so clearing the old default and setting the new one succeed or fail together |
| **Profile row lock** | `SELECT ... FOR UPDATE` on the owner's `user_profiles` row before reading any address. A second write for the same user waits until the first commits, then sees its result. The lock is per profile, so different users never wait for each other |
| **No deadlocks between writes** | Every write takes the profile lock before touching addresses, always in the same order |
| **Database backstop** | `uq_user_addresses_one_default_per_user` rejects a second default even if code were wrong |
| **Deleting the default** | In the same transaction, the oldest remaining address (lowest `id`) becomes the default |

Reads (list, get) do not lock.

### Concurrency check against MySQL (11 November 2026)

A scratch script (`address_concurrency_check.py`, run from the project folder and not part of the repository) used `SessionLocal` with real commits on `shopease_user_db`. It created a profile with 5 addresses, then started 20 threads at the same moment. Each thread made 15 calls: either `set_default_address` on a random address, or `create_address` with `is_default=True`. Afterwards it counted the defaults and deleted the test profile (the addresses were removed by `ON DELETE CASCADE`).

| Run | Operations | Errors | Defaults at the end | Rows left |
| --- | --- | --- | --- | --- |
| Service as built (profile row locked) | 300 succeeded | none | **1** | 0 profiles, 0 addresses |
| Same script with the lock disabled (comparison only) | 81 succeeded | 194 `IntegrityError` (unique key), 25 `OperationalError` (deadlock) | 1 | 0, 0 |

Without the lock, the unique key still stopped a second default, but 219 of 300 requests failed and would have returned 503 to callers. With the lock, every request succeeded.

## Phone number normalization

Code: [phone_utils.py](../app/core/phone_utils.py). It is applied in the request schemas (`PhoneNumber` type) and again in the models (`@validates`), so every write path stores the same format.

| Input | Stored |
| --- | --- |
| `+91 98765-43210` | `+919876543210` |
| `0091 98765 43210` | `+919876543210` |
| `(020) 7946-0958` | `02079460958` |
| `555.123.4567` | `5551234567` |
| `12345`, `+0123456789`, letters | rejected with 422 |

Rule: spaces, `-`, `(`, `)` and `.` are removed, and a leading `00` becomes `+`. The result must have 7 to 15 digits. A number starting with `+` follows E.164, so it cannot start with 0. The rejected value is never repeated in the error message.

## Session and transaction handling

Code: [connection.py](../app/database/connection.py).

- **Engine:** `pool_pre_ping` replaces dropped connections, `pool_recycle=3600`, a 5-second connect timeout, the session time zone set to UTC, and `hide_parameters` keeps values out of errors.
- **`SessionLocal`:** `autoflush=False`, and `expire_on_commit=False`, so returned objects can be read after commit.
- **`get_db()`:** one session per request. On any exception it calls `rollback()`, and it always calls `close()`, which returns the connection to the pool. Unit tests cover both paths.
- **Errors:** an `SQLAlchemyError` that reaches the app returns `503 {"detail": "Service temporarily unavailable"}`. Only the exception class name is logged.

## Migrations

### Configuration

| File | Setting |
| --- | --- |
| [alembic.ini](../alembic.ini) | No `sqlalchemy.url` and no credentials. The script location is `alembic/` |
| [alembic/env.py](../alembic/env.py) | The URL comes from `app.core.config`: `MYSQL_*` environment variables, or `.env` |
| | `target_metadata = Base.metadata`, with `UserProfile` and `UserAddress` imported explicitly |
| | Autogenerate compares tables, columns, indexes and constraints, plus column types (`compare_type`) and server defaults (`compare_server_default`) |
| | Stops with an error if `SELECT DATABASE()` is not `shopease_user_db` |

### Revision history

| Revision | Parent | Description | Applied |
| --- | --- | --- | --- |
| `8c2e3b6d4acf` | none (initial) | create user and address tables | 10 November 2026, local `user-mysql` container |
| `4f1a9d27c5e3` | `8c2e3b6d4acf` | rename WORK address type to OFFICE | 11 November 2026, local `user-mysql` container. **Current head** |

File: `alembic/versions/8c2e3b6d4acf_create_user_and_address_tables.py`. Generated with:

```powershell
alembic revision --autogenerate -m "create user and address tables"
```

| Operation | Objects |
| --- | --- |
| `upgrade()` | Creates `user_profiles` (PK, `uq_user_profiles_auth_user_id`, `ck_user_profiles_gender`, `is_active NOT NULL DEFAULT 1`). Creates `user_addresses` (PK, `fk_user_addresses_user_id_user_profiles` ON DELETE CASCADE, `uq_user_addresses_one_default_per_user`, `ck_user_addresses_address_type`, generated `default_marker`). Creates index `ix_user_addresses_user_id` |
| `downgrade()` | Drops `user_addresses` first, then `user_profiles`. Dropping a table removes its indexes and constraints. Nothing outside these two tables is touched |

Review changes made to the generated file: added a description, removed the generated comment markers, and removed a separate `drop_index` before `drop_table` (the table drop removes it anyway). Boolean defaults are written as `'1'`/`'0'`, which is how MySQL reports them, so autogenerate does not detect false differences.

### `4f1a9d27c5e3`: rename WORK address type to OFFICE

The address types became `HOME`, `OFFICE` and `OTHER`. Written by hand, because autogenerate does not compare CHECK constraints.

| Operation | Steps |
| --- | --- |
| `upgrade()` | Drop CHECK `ck_user_addresses_address_type`; `UPDATE user_addresses SET address_type = 'OFFICE' WHERE address_type = 'WORK'`; recreate the CHECK with `HOME`, `OFFICE`, `OTHER` |
| `downgrade()` | The reverse: drop the CHECK, convert `OFFICE` back to `WORK`, recreate the CHECK with `HOME`, `WORK`, `OTHER` |

Verified on 11 November 2026 against `shopease_user_db`:

| # | Check | Result |
| --- | --- | --- |
| 1 | Seeded one profile and one address with `address_type = 'WORK'` at revision `8c2e3b6d4acf` | Inserted |
| 2 | `alembic upgrade head` | `Running upgrade 8c2e3b6d4acf -> 4f1a9d27c5e3`. The row became `OFFICE`. CHECK: ``(`address_type` in ('HOME','OFFICE','OTHER'))`` |
| 3 | `UPDATE user_addresses SET address_type='WORK'` | `ERROR 3819: Check constraint 'ck_user_addresses_address_type' is violated` |
| 4 | `alembic downgrade -1` | `Running downgrade 4f1a9d27c5e3 -> 8c2e3b6d4acf`. The row became `WORK` again, and the CHECK listed `HOME`, `WORK`, `OTHER` |
| 5 | `alembic upgrade head` again | Succeeded |
| 6 | Test rows deleted | 0 profiles, 0 addresses |
| 7 | `alembic current` / `alembic check` | `4f1a9d27c5e3 (head)` / "No new upgrade operations detected." |

### Verification of `8c2e3b6d4acf`

All results below are from commands actually run against `shopease_user_db` in the `user-mysql` container on 10 November 2026.

| # | Check | Result |
| --- | --- | --- |
| 1 | `alembic upgrade head` | `Running upgrade -> 8c2e3b6d4acf`. `alembic current`: `8c2e3b6d4acf (head)` |
| 2 | Objects after upgrade | 2 tables, 7 constraints, 5 indexes, 1 foreign key (as listed above) |
| 3 | `alembic check` | "No new upgrade operations detected." |
| 4 | Live constraint test (ORM, inside a transaction that was rolled back) | 15/15 passed: duplicate `auth_user_id`, invalid gender, invalid address type, missing profile FK, second default, default switch, cascade delete, phone normalization, defaults and timestamps |
| 5 | `alembic downgrade -1` | `Running downgrade 8c2e3b6d4acf -> `. `alembic current` empty, and `alembic_version` has 0 rows |
| 6 | Objects after downgrade | 0 tables, 0 constraints, 0 indexes, 0 foreign keys in `shopease_user_db`. Only the empty `alembic_version` table remains |
| 7 | Unrelated database | A database `unrelated_sentinel_db` was created with its own `user_profiles` and `user_addresses` tables, a foreign key, and rows. After the downgrade its tables and rows were unchanged. It was then dropped |
| 8 | Other databases on the server | Table counts of `information_schema`, `mysql`, `performance_schema` and `sys` were identical before and after |
| 9 | Wrong-database guard | With `MYSQL_DATABASE=unrelated_sentinel_db`, `alembic upgrade head` stopped with `Refusing to migrate database 'unrelated_sentinel_db': expected 'shopease_user_db'` and created nothing |
| 10 | Downgrade and upgrade again | Both succeeded, and `alembic check` was still clean |
| 11 | `pytest` (no database needed) | 29 passed |

### Problems found during verification

| Problem | Fix |
| --- | --- |
| The new database check in `env.py` started a transaction, so Alembic did not commit its own. A downgrade dropped the tables (MySQL DDL commits itself), but the `alembic_version` update was rolled back | `env.py` commits that transaction before handing over to Alembic. The stale row was cleared with `alembic stamp --purge base`, and the full cycle was rerun |
| With server-default comparison on, autogenerate saw `true()`/`false()` and MySQL's `1`/`0` as different | Boolean server defaults declared as `"1"`/`"0"` |
