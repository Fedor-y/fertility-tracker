"""Календарные диапазоны включительно. Без системных часов и интерфейса."""
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from healthtracker.domain.errors import DomainValidationError


@dataclass(frozen=True, slots=True)
class DateRange:
    start: date
    end: date

    def __post_init__(self) -> None:
        if type(self.start) is not date or type(self.end) is not date or self.end < self.start:
            raise DomainValidationError("Нужны календарные даты: начало не позже окончания.")

    @property
    def calendar_days(self) -> int:
        return (self.end - self.start).days + 1

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end

    def dates(self):
        for ordinal in range(self.start.toordinal(), self.end.toordinal() + 1):
            yield date.fromordinal(ordinal)


class QuickPeriod(StrEnum):
    DAY = "day"
    SEVEN_DAYS = "7_days"
    TEN_DAYS = "10_days"
    MONTH = "month"
    PREVIOUS_MONTH = "previous_month"
    YEAR = "year"


class ComparisonPeriod(StrEnum):
    WEEK = "week"
    MONTH = "month"


@dataclass(frozen=True, slots=True)
class PeriodPair:
    first: DateRange
    second: DateRange


def quick_period(kind: QuickPeriod, today: date) -> DateRange:
    if not isinstance(kind, QuickPeriod) or type(today) is not date:
        raise DomainValidationError("Нужны известный быстрый период и текущая дата.")
    try:
        if kind is QuickPeriod.PREVIOUS_MONTH:
            return quick_period(QuickPeriod.MONTH, today.replace(day=1)-timedelta(days=1))
        if kind is QuickPeriod.MONTH:
            return DateRange(today.replace(day=1), today.replace(day=monthrange(today.year,today.month)[1]))
        if kind is QuickPeriod.YEAR:
            return DateRange(date(today.year,1,1), date(today.year,12,31))
        days = {QuickPeriod.DAY:1, QuickPeriod.SEVEN_DAYS:7, QuickPeriod.TEN_DAYS:10}[kind]
        return DateRange(today-timedelta(days=days-1),today)
    except (OverflowError,ValueError):
        raise DomainValidationError("Период выходит за поддерживаемый диапазон дат.") from None


def comparison_periods(kind: ComparisonPeriod, today: date) -> PeriodPair:
    """Текущая неделя/месяц до сегодня и та же прошедшая календарная часть."""
    if not isinstance(kind, ComparisonPeriod) or type(today) is not date:
        raise DomainValidationError("Нужны известное сравнение и текущая дата.")
    try:
        if kind is ComparisonPeriod.WEEK:
            start = today-timedelta(days=today.weekday())
            return PeriodPair(DateRange(start,today),DateRange(start-timedelta(days=7),today-timedelta(days=7)))
        start = today.replace(day=1)
        previous_end = start-timedelta(days=1)
        return PeriodPair(DateRange(start,today),DateRange(previous_end.replace(day=1),
            previous_end.replace(day=min(today.day,previous_end.day))))
    except (OverflowError,ValueError):
        raise DomainValidationError("Предыдущий период вне поддерживаемого диапазона дат.") from None
