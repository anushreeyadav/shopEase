"""app.database.wait: retries until the database answers, gives up after the timeout."""

from contextlib import contextmanager

from sqlalchemy.exc import OperationalError

from app.database import wait


class FakeEngine:
    """Refuses the first `failures` connections, then accepts."""

    def __init__(self, failures: int):
        self.failures = failures
        self.attempts = 0

    @contextmanager
    def connect(self):
        self.attempts += 1
        if self.attempts <= self.failures:
            raise OperationalError("SELECT 1", {}, ConnectionRefusedError("db.internal:3306 user catalog_svc"))
        yield self

    def execute(self, _statement):
        return None

    def dispose(self):
        pass


def test_waits_until_the_database_answers(monkeypatch, caplog):
    engine = FakeEngine(failures=2)
    monkeypatch.setattr(wait, "engine", engine)
    monkeypatch.setattr(wait.time, "sleep", lambda _seconds: None)
    assert wait.wait_for_database(timeout=30) is True
    assert engine.attempts == 3
    assert "Database ready after 3 attempt(s)" in caplog.text


def test_gives_up_after_the_timeout(monkeypatch, caplog):
    engine = FakeEngine(failures=10**6)
    clock = iter(range(0, 10**6, 2))
    monkeypatch.setattr(wait, "engine", engine)
    monkeypatch.setattr(wait.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(wait.time, "sleep", lambda _seconds: None)
    assert wait.wait_for_database(timeout=10) is False
    assert "Database not ready after" in caplog.text
    assert "catalog_svc" not in caplog.text and "db.internal" not in caplog.text  # only the error class is logged, never the driver message
