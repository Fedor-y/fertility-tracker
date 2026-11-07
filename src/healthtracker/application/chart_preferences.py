"""Чтение и атомарная запись через порт существующего хранилища."""
from dataclasses import fields

from healthtracker.application.errors import StorageError
from healthtracker.domain.analytics import Indicator
from healthtracker.domain.chart_preferences import ChartPreferences
from healthtracker.domain.charts import SeriesKind
from healthtracker.domain.errors import DomainValidationError


class PreferencesError(Exception):
    """Безопасная ошибка; исходные значения не передаются интерфейсу."""


class ChartPreferencesService:
    def __init__(self, storage):
        self.storage = storage

    def load(self) -> ChartPreferences:
        try:
            with self.storage.read_snapshot() as session:
                values = {f.name: session.settings.get(f.name) for f in fields(ChartPreferences)}
            values = {key: value for key, value in values.items() if value is not None}
            if 'visible_series' in values:
                values['visible_series'] = tuple(SeriesKind(s) for s in values['visible_series'])
            if 'analytics_indicator' in values:
                values['analytics_indicator'] = Indicator(values['analytics_indicator'])
            return ChartPreferences(**values)
        except (StorageError, ValueError, TypeError):
            raise PreferencesError("Не удалось прочитать настройки графика. Используются значения по умолчанию; сохранённые настройки не изменены.") from None

    def save(self, preferences: ChartPreferences) -> None:
        if not isinstance(preferences, ChartPreferences):
            raise DomainValidationError("Нужны типизированные предпочтения графика.")
        try:
            with self.storage.write() as session:
                # Не затирать повреждённое прежнее значение набором defaults
                # после ошибки чтения. Проверка и запись — одна транзакция.
                for field in fields(preferences):
                    session.settings.get(field.name)
                for field in fields(preferences):
                    value = getattr(preferences, field.name)
                    if field.name == 'visible_series':
                        value = [s.value for s in value]
                    elif field.name == 'analytics_indicator':
                        value = value.value
                    session.settings.set(field.name, value)
        except (StorageError, ValueError, TypeError):
            raise PreferencesError("Не удалось сохранить настройки графика. Текущий выбор сохранён в окне; повторите сохранение.") from None
