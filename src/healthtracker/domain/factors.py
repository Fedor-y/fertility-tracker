"""Только утверждённые сравнения сна и зала с дневным когнитивным индексом."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from statistics import median

from healthtracker.domain.analytics import AnalyticsData, AnalysisContext, Indicator, daily_statistics
from healthtracker.domain.cognitive import cognitive_index
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.periods import DateRange
from healthtracker.domain.time import local_date


class SleepExclusion(StrEnum):
    NO_SLEEP = "no_sleep"
    NO_COGNITIVE_MEDIAN = "no_cognitive_median"
    MULTIPLE_SLEEP_INTERVALS = "multiple_sleep_intervals"
    COGNITIVE_HOUR_BEFORE_WAKE = "cognitive_hour_before_wake"


@dataclass(frozen=True, slots=True)
class SleepPoint:
    day: date
    sleep_hours: float
    cognitive_median: float


@dataclass(frozen=True, slots=True)
class ExcludedSleepDay:
    day: date
    reasons: tuple[SleepExclusion, ...]


@dataclass(frozen=True, slots=True)
class SleepComparison:
    points: tuple[SleepPoint, ...]
    excluded: tuple[ExcludedSleepDay, ...]

    @property
    def used_days(self) -> int:
        return len(self.points)

    @property
    def excluded_days(self) -> int:
        return len(self.excluded)


def sleep_comparison(data: AnalyticsData, period: DateRange, context: AnalysisContext) -> SleepComparison:
    daily = {row.day:row.median for row in daily_statistics(data,Indicator.COGNITIVE,period,context)}
    sleeps, full_hours = defaultdict(list), defaultdict(list)
    for row in data.sleep:
        if row.interval.end <= context.now:
            day = local_date(row.interval.end,context.zone)
            if period.contains(day):
                sleeps[day].append(row.interval)
    for row in data.cognitive:
        if row.interval.end <= context.now and cognitive_index(row.assessment) is not None:
            day = local_date(row.interval.end,context.zone)
            if period.contains(day):
                full_hours[day].append(row.interval)
    points, excluded = [], []
    for day in period.dates():
        intervals = sleeps[day]
        reasons = []
        if not intervals:
            reasons.append(SleepExclusion.NO_SLEEP)
        if day not in daily:
            reasons.append(SleepExclusion.NO_COGNITIVE_MEDIAN)
        if len(intervals) > 1:
            reasons.append(SleepExclusion.MULTIPLE_SLEEP_INTERVALS)
        # Только у единственного сна есть однозначное пробуждение для сравнения.
        if len(intervals) == 1 and any(hour.start < intervals[0].end for hour in full_hours[day]):
            reasons.append(SleepExclusion.COGNITIVE_HOUR_BEFORE_WAKE)
        if reasons:
            excluded.append(ExcludedSleepDay(day,tuple(reasons)))
        else:
            points.append(SleepPoint(day,intervals[0].duration.total_seconds()/3600,daily[day]))
    return SleepComparison(tuple(points),tuple(excluded))


@dataclass(frozen=True, slots=True)
class GymPoint:
    day: date
    cognitive_median: float
    difficulty: int | None


@dataclass(frozen=True, slots=True)
class GymGroup:
    points: tuple[GymPoint, ...]
    median: float | None

    @property
    def days(self) -> int:
        return len(self.points)


@dataclass(frozen=True, slots=True)
class GymComparison:
    attended: GymGroup
    absent: GymGroup
    difference: float | None  # Был минус Не был, пункты.
    excluded_dates: tuple[date, ...]

    @property
    def warning(self) -> str | None:
        return "Мало наблюдений для сравнения" if self.attended.days < 5 or self.absent.days < 5 else None


def gym_comparison(data: AnalyticsData, period: DateRange, context: AnalysisContext) -> GymComparison:
    daily = {row.day:row.median for row in daily_statistics(data,Indicator.COGNITIVE,period,context)}
    marks = {}
    for row in data.gym:
        if period.contains(row.entry_date) and row.entry_date <= context.today:
            if row.entry_date in marks:
                raise DomainValidationError("Повторная отметка спортзала за одну дату недопустима.")
            marks[row.entry_date] = row
    yes, no, excluded = [], [], []
    for day in period.dates():
        mark = marks.get(day)
        if day not in daily or mark is None:
            excluded.append(day)
        else:
            (yes if mark.attended else no).append(GymPoint(day,daily[day],mark.difficulty))
    attended = GymGroup(tuple(yes),median(point.cognitive_median for point in yes) if yes else None)
    absent = GymGroup(tuple(no),median(point.cognitive_median for point in no) if no else None)
    difference = attended.median-absent.median if attended.median is not None and absent.median is not None else None
    return GymComparison(attended,absent,difference,tuple(excluded))
