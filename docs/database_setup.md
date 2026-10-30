# Database Setup and Migrations

How to create the five ShopEase databases and run each service's migrations safely.
Ownership rules are in [database_ownership.md](database_ownership.md).

## What each service owns

| Service | Database | Runtime user (DML only) | Migration user (DDL) | Alembic config | Initial revision |
|---------|----------|-------------------------|----------------------|----------------|------------------|
| auth_service | `auth_db` | `auth_svc` | `auth_migrator` | `services/auth_service/alembic.ini` | `auth_0001` |
| user_service | `user_db` | `user_svc` | `user_migrator` | `services/user_service/alembic.ini` | `user_0001` |
| product_service | `product_db` | `product_svc` | `product_migrator` | `services/product_service/alembic.ini` | `product_0001` |
| order_service | `order_db` | `order_svc` | `order_migrator` | `services/order_service/alembic.ini` | `order_0001` |
| payment_service | `payment_db` | `payment_svc` | `payment_migrator` | `services/payment_service/alembic.ini` | `payment_0001` |

Each service has its own SQLAlchemy engine and session factory (`app/db.py`), declarative
base and metadata (`app/models/base.py`), models (`app/models/`), Pydantic schemas
(`app/schemas/`) and Alembic history (`migrations/`). Nothing database-related is shared.

Revision IDs are prefixed with the service name on purpose. If a service's migrations are
ever pointed at another service's database, Alembic stops with
`Can't locate revision identified by 'auth_0001'` instead of silently doing nothing.

## Safety rules

- Every step below is **additive**: `CREATE ... IF NOT EXISTS`, `GRANT`, `alembic upgrade`.
  Nothing here drops a database, truncates a table or resets a password.
- `alembic downgrade` **drops tables and their data**. Use it only on a disposable database.
- Services never connect as `root` or as the migration user. Only Alembic uses migration users.
- Real passwords live in `.env` (git-ignored) or a secret store, never in the repository.
- MySQL DDL is not transactional. If a migration fails part-way, the tables created before the
  failure stay. Fix the cause, remove those tables by hand (on a disposable database), and
  upgrade again.

## Option A: Docker Compose (recommended)

```bash
python scripts/generate_jwt_key.py   # once
python scripts/init_dev_env.py       # once: .env with random passwords
docker compose up --build -d --wait  # init script (empty volume only) → migrations → services
docker compose run --rm order_migrate alembic current   # inspect one service's revision
```

The init script runs only when the `mysql_data` volume is empty. Each `*_migrate` job runs
`alembic upgrade head` with only its own service's migration credentials before that service
starts; each service container gets only its runtime credentials. Details, startup order and
recovery behaviour: [local_development.md](local_development.md).

## Option B: a MySQL server you run yourself

Use a server that holds nothing you care about, or one where creating these five databases
is acceptable. Do not use a shared or production server.

1. Put the server address and an admin account in `.env`:
   `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_ADMIN_USER`, `MYSQL_ADMIN_PASSWORD`, plus real
   passwords for every `*_DB_PASSWORD` and `*_DB_MIGRATION_PASSWORD`.
2. Review the SQL first, then create the databases and users:

   ```bash
   python scripts/init_local_databases.py --dry-run   # passwords are masked
   python scripts/init_local_databases.py
   ```

   The script refuses placeholder passwords and unsafe names. Re-running it is harmless. It
   never changes the password of a user that already exists.
3. Run the migrations from the repository root, so `.env` is found:

   ```bash
   alembic -c services/auth_service/alembic.ini upgrade head
   alembic -c services/user_service/alembic.ini upgrade head
   alembic -c services/product_service/alembic.ini upgrade head
   alembic -c services/order_service/alembic.ini upgrade head
   alembic -c services/payment_service/alembic.ini upgrade head
   ```

4. Check them: `alembic -c services/<svc>/alembic.ini current` shows `<svc>_0001 (head)`,
   and `curl http://localhost:<port>/health/ready` returns `200` once the service runs.

To read the SQL a migration would run without touching a database:
`alembic -c services/<svc>/alembic.ini upgrade head --sql`.

## Writing a new migration

```bash
alembic -c services/order_service/alembic.ini revision --autogenerate -m "add order notes" --rev-id order_0002
```

Then review the file by hand before committing:
- Is every operation expected, and inside this service's database only?
- Are enum CHECK constraint names frozen with `op.f('ck_<table>_<column>')`?
- Does `downgrade()` drop tables directly, children first? (MySQL refuses to drop an index a
  foreign key relies on, error 1553.)
- Use expand-and-contract for breaking changes ([database_ownership.md](database_ownership.md) §6).

## Tests

```bash
python scripts/run_tests.py
```

This runs without MySQL. Each service checks its own model metadata, foreign-key boundaries,
external-ID indexes, constraints, schemas and session handling, and runs its migrations up,
down and up again on SQLite.

Integration tests against a **disposable** MySQL (same environment variables as the services):

```bash
SHOPEASE_MYSQL_TESTS=1 python scripts/run_tests.py
SHOPEASE_MYSQL_TESTS=1 SHOPEASE_ALLOW_DESTRUCTIVE_DB_TESTS=1 python scripts/run_tests.py   # also downgrade/upgrade
```

They check that the migrations apply twice cleanly, that the live schema matches the models
(including column types), that the runtime user can read and write its own tables but can't
change the schema, and that neither user can see any other service's database.
