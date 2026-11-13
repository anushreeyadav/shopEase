"""Custom column types."""

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """A DATETIME column that always holds UTC.

    MySQL DATETIME has no time zone, so the rule is enforced here:
      - writing: the value must be timezone-aware; it is converted to UTC and stored without zone.
      - reading: the stored value is returned as an aware UTC datetime, so API responses carry
        an explicit offset ("2026-11-12T10:00:00Z") instead of an ambiguous local time.
    A naive datetime is refused rather than guessed at.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, datetime):
            # SQL expressions such as func.now() never reach this method; anything else is a bug.
            raise TypeError("UTCDateTime needs a datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("UTCDateTime needs a timezone-aware datetime")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)
