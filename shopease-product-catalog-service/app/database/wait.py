"""Wait until MySQL accepts connections from this service, then exit 0 (or 1 after the timeout).

    python -m app.database.wait [--timeout SECONDS]

The container runs it before "alembic upgrade head". Docker Compose already starts the service
only once the MySQL health check passes; this also covers a plain "docker run", a database on
another host, and a MySQL restart between the health check and the migration.

It connects with the service's own settings (MYSQL_* variables) and runs SELECT 1, so it
succeeds only when the database exists and the service's user can log in to it. Errors are
logged by class name only: driver messages can include the host, user or database name.
"""

import argparse
import logging
import sys
import time

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database.connection import engine

logger = logging.getLogger("app.database.wait")
RETRY_SECONDS = 2


def wait_for_database(timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    attempt = 0
    while True:
        attempt += 1
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Database ready after %d attempt(s)", attempt)
            return True
        except SQLAlchemyError as exc:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.error("Database not ready after %d attempt(s) in %.0f s: %s",
                             attempt, timeout, type(getattr(exc, "orig", None) or exc).__name__)
                return False
            logger.info("Database not ready yet (%s); retrying in %d s", type(getattr(exc, "orig", None) or exc).__name__,
                        RETRY_SECONDS)
            time.sleep(min(RETRY_SECONDS, remaining))
        finally:
            engine.dispose()  # no pooled connection is carried over into the server process


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--timeout", type=float, default=60, help="seconds to keep trying (default 60)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return 0 if wait_for_database(args.timeout) else 1


if __name__ == "__main__":
    sys.exit(main())
