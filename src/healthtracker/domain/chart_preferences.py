"""Сохраняемые предпочтения; без периода, состояния доставки и масштаба."""
from dataclasses import dataclass

from healthtracker.domain.analytics import Indicator
from healthtracker.domain.charts import SeriesKind, validate_line_gap
from healthtracker.domain.errors import DomainValidationError


@dataclass(frozen=True, slots=True)
class ChartPreferences:
    visible_series: tuple[SeriesKind, ...] = (SeriesKind.COGNITIVE, SeriesKind.PHYSICAL)
    compact_mode: bool = True
    line_gap_hours: float = 3
    analytics_indicator: Indicator = Indicator.COGNITIVE
    show_sleep: bool = True
    show_meals: bool = True
    show_gym: bool = True
    show_events: bool = True

    def __post_init__(self):
        if (type(self.visible_series) is not tuple
                or any(not isinstance(s, SeriesKind) for s in self.visible_series)
                or len(set(self.visible_series)) != len(self.visible_series)):
            raise DomainValidationError("Недопустимые показатели графика.")
        # Порядок флажков задан SeriesKind; иной порядок старого JSON не
        # является изменением предпочтений при переключении периода/zoom.
        object.__setattr__(self, 'visible_series', tuple(k for k in SeriesKind if k in self.visible_series))
        if any(type(v) is not bool for v in (self.compact_mode, self.show_sleep,
                                            self.show_meals, self.show_gym, self.show_events)):
            raise DomainValidationError("Недопустимые переключатели графика.")
        validate_line_gap(self.line_gap_hours)
        if (not isinstance(self.analytics_indicator, Indicator)
                or self.analytics_indicator.value not in ('cognitive', 'learning', 'application', 'speed')):
            raise DomainValidationError("Недопустимый показатель аналитики.")
