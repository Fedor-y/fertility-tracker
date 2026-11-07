"""Чистая дневная статистика. Источники — прежние неизменяемые модели."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from enum import StrEnum
from statistics import median

from healthtracker.domain.cognitive import cognitive_index
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.measurement import CognitiveMeasurement
from healthtracker.domain.periods import DateRange
from healthtracker.domain.records import (
    GymRecord, MealRecord, MoodRecord, PhysicalRecord, SleepRecord, StressRecord,
)
from healthtracker.domain.time import as_utc, local_date


class Indicator(StrEnum):
    COGNITIVE = "cognitive"
    LEARNING = "learning"
    APPLICATION = "application"
    SPEED = "speed"
    PHYSICAL = "physical"
    MOOD = "mood"


@dataclass(frozen=True, slots=True)
class AnalyticsData:
    cognitive: tuple[CognitiveMeasurement, ...] = ()
    physical: tuple[PhysicalRecord, ...] = ()
    stress: tuple[StressRecord, ...] = ()
    mood: tuple[MoodRecord, ...] = ()
    sleep: tuple[SleepRecord, ...] = ()
    meals: tuple[MealRecord, ...] = ()
    gym: tuple[GymRecord, ...] = ()

    def __post_init__(self) -> None:
        for name, model in (("cognitive", CognitiveMeasurement), ("physical", PhysicalRecord),
                            ("stress", StressRecord), ("mood", MoodRecord), ("sleep", SleepRecord),
                            ("meals", MealRecord), ("gym", GymRecord)):
            records = getattr(self, name)
            if type(records) is not tuple or any(not isinstance(row, model) for row in records):
                raise DomainValidationError("Нужны неизменяемые типизированные данные журналов.")


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    now: datetime
    zone: tzinfo

    def __post_init__(self) -> None:
        object.__setattr__(self, "now", as_utc(self.now))
        if not isinstance(self.zone, tzinfo):
            raise DomainValidationError("Необходим текущий часовой пояс расчёта.")

    @property
    def today(self):
        return local_date(self.now, self.zone)


@dataclass(frozen=True, slots=True)
class DailyStatistics:
    day: date
    median: float
    minimum: float
    maximum: float
    measurements: int


def daily_statistics(data: AnalyticsData, indicator: Indicator, period: DateRange,
                     context: AnalysisContext) -> tuple[DailyStatistics, ...]:
    """Только даты с числовыми данными, без округления и заполнения пропусков."""
    if not isinstance(indicator, Indicator):
        raise DomainValidationError("Неизвестный показатель аналитики.")
    grouped = defaultdict(list)
    if indicator in (Indicator.PHYSICAL, Indicator.MOOD):
        rows = ((row.observed_at, row.score) for row in getattr(data, indicator.value))
    else:
        def cognitive_values():
            for row in data.cognitive:
                value = (cognitive_index(row.assessment) if indicator is Indicator.COGNITIVE
                         else getattr(row.assessment, indicator.value).value)
                yield row.interval.end, value
        rows = cognitive_values()
    for moment, value in rows:
        if value is None or moment > context.now:
            continue
        day = local_date(moment, context.zone)
        if period.contains(day):
            grouped[day].append(value)
    return tuple(DailyStatistics(day, median(values), min(values), max(values), len(values))
                 for day, values in sorted(grouped.items()))


@dataclass(frozen=True, slots=True)
class PeriodSummary:
    median: float
    mean: float
    minimum: float
    maximum: float
    minimum_dates: tuple[date, ...]
    maximum_dates: tuple[date, ...]


@dataclass(frozen=True, slots=True)
class PeriodStatistics:
    period: DateRange
    indicator: Indicator
    context: AnalysisContext
    daily: tuple[DailyStatistics, ...]
    summary: PeriodSummary | None

    @property
    def observed_days(self) -> int:
        return len(self.daily)

    @property
    def measurements(self) -> int:
        return sum(day.measurements for day in self.daily)

    @property
    def calendar_days(self) -> int:
        return self.period.calendar_days

    @property
    def coverage_percent(self) -> float:
        return self.observed_days / self.calendar_days * 100

    @property
    def incomplete(self) -> bool:
        # Текущий календарный день ещё не завершён; будущие даты входят в размер.
        return self.period.end >= self.context.today


def period_statistics(data: AnalyticsData, indicator: Indicator, period: DateRange,
                      context: AnalysisContext) -> PeriodStatistics:
    daily = daily_statistics(data, indicator, period, context)
    summary = None
    if len(daily) >= 7:
        values = tuple(day.median for day in daily)
        low, high = min(values), max(values)
        summary = PeriodSummary(median(values), sum(values) / len(values), low, high,
            tuple(day.day for day in daily if day.median == low),
            tuple(day.day for day in daily if day.median == high))
    return PeriodStatistics(period, indicator, context, daily, summary)


@dataclass(frozen=True, slots=True)
class PeriodComparison:
    first: PeriodStatistics
    second: PeriodStatistics
    difference: float | None


def compare_periods(data: AnalyticsData, indicator: Indicator, first: DateRange,
                    second: DateRange, context: AnalysisContext) -> PeriodComparison:
    """Явные диапазоны; автосравнения задаёт comparison_periods. Разница в пунктах."""
    left = period_statistics(data,indicator,first,context)
    right = period_statistics(data,indicator,second,context)
    difference = (left.summary.median-right.summary.median
                  if left.summary is not None and right.summary is not None else None)
    return PeriodComparison(left,right,difference)
