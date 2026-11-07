"""Каноническое представление моментов без потери микросекунд."""

from datetime import UTC, date, datetime

from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.time import as_utc


def encode_time(value: datetime) -> str:
    value = as_utc(value)
    return (f"{value.year:04d}-{value.month:02d}-{value.day:02d}T"
            f"{value.hour:02d}:{value.minute:02d}:{value.second:02d}.{value.microsecond:06d}Z")


def decode_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0 or encode_time(parsed) != value:
        raise DomainValidationError("Некорректное сохранённое UTC-время.")
    return parsed.astimezone(UTC)


def encode_date(value: date) -> str:
    if type(value) is not date:
        raise DomainValidationError("Нужна календарная дата без времени.")
    return value.isoformat()
