"""Только настройки графика/аналитики. Путь копий и окно остаются в QSettings."""

import json
import math

from healthtracker.domain.errors import DomainValidationError
from healthtracker.infrastructure.sqlite.codecs import encode_time


def _validate(key, value):
    if key == "visible_series":
        valid = (type(value) is list and all(type(item) is str for item in value)
                 and len(set(value)) == len(value) and set(value) <= {"cognitive", "learning", "application", "speed", "physical", "mood", "stress"})
    elif key in ("compact_mode", "show_sleep", "show_meals", "show_gym", "show_events"):
        valid = type(value) is bool
    elif key == "line_gap_hours":
        valid = type(value) in (int, float) and math.isfinite(value) and value > 0
    elif key == "analytics_indicator":
        valid = type(value) is str and value in ("cognitive", "learning", "application", "speed")
    else:
        raise DomainValidationError("Настройка неизвестна или принадлежит QSettings.")
    if not valid:
        raise DomainValidationError("Недопустимое значение настройки.")


class SettingsRepository:
    def __init__(self, session):
        self.session = session

    def get(self, key):
        self.session.ensure_active()
        if key not in ("visible_series", "compact_mode", "line_gap_hours", "analytics_indicator",
                       "show_sleep", "show_meals", "show_gym", "show_events"):
            raise DomainValidationError("Настройка неизвестна или принадлежит QSettings.")
        row = self.session.connection.execute("SELECT value FROM application_settings WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        value = json.loads(row[0])
        _validate(key, value)
        return value

    def set(self, key, value):
        with self.session.operation():
            _validate(key, value)
            self.session.connection.execute(
                "INSERT INTO application_settings VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at_utc=excluded.updated_at_utc",
                (key, json.dumps(value, ensure_ascii=False, allow_nan=False), encode_time(self.session.now)),
            )

    def delete(self, key):
        with self.session.operation():
            self.get(key)  # Проверка принадлежности хранилищу.
            self.session.connection.execute("DELETE FROM application_settings WHERE key=?", (key,))
