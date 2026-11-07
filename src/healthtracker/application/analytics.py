"""Снимок семи прежних журналов и расчёты после закрытия читающей транзакции."""
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from healthtracker.application.storage import SnapshotToken, Storage, StoredRecord
from healthtracker.domain.analytics import (
    AnalyticsData, AnalysisContext, Indicator, PeriodStatistics, PeriodComparison,
    period_statistics, compare_periods,
)
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.factors import SleepComparison, GymComparison, sleep_comparison, gym_comparison
from healthtracker.domain.measurement import CognitiveMeasurement
from healthtracker.domain.periods import DateRange, PeriodPair
from healthtracker.domain.records import (
    PhysicalRecord, StressRecord, MoodRecord, SleepRecord, MealRecord, GymRecord,
)
from healthtracker.domain.time import local_date


JOURNALS = ("cognitive", "physical", "stress", "mood", "sleep", "meals", "gym")


@dataclass(frozen=True, slots=True)
class AnalyticsSnapshot:
    period: DateRange
    context: AnalysisContext
    token: SnapshotToken
    cognitive: tuple[StoredRecord[CognitiveMeasurement], ...]
    physical: tuple[StoredRecord[PhysicalRecord], ...]
    stress: tuple[StoredRecord[StressRecord], ...]
    mood: tuple[StoredRecord[MoodRecord], ...]
    sleep: tuple[StoredRecord[SleepRecord], ...]
    meals: tuple[StoredRecord[MealRecord], ...]
    gym: tuple[StoredRecord[GymRecord], ...]

    @property
    def data(self) -> AnalyticsData:
        # Только представление тех же моделей, без новой загрузки/источника истины.
        return AnalyticsData(**{name:tuple(record.value for record in getattr(self,name)) for name in JOURNALS})


@dataclass(frozen=True, slots=True)
class AnalyticsResult:
    token: SnapshotToken
    statistics: PeriodStatistics
    sleep: SleepComparison
    gym: GymComparison


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    token: SnapshotToken
    comparison: PeriodComparison


def calculate_snapshot(snapshot: AnalyticsSnapshot, indicator: Indicator) -> AnalyticsResult:
    """Не обращается к хранилищу; доступен и после полного закрытия Database."""
    data = snapshot.data
    return AnalyticsResult(snapshot.token,
        period_statistics(data,indicator,snapshot.period,snapshot.context),
        sleep_comparison(data,snapshot.period,snapshot.context),
        gym_comparison(data,snapshot.period,snapshot.context))


class Analytics:
    def __init__(self, storage: Storage):
        self.storage = storage

    def load(self, period: DateRange, context: AnalysisContext) -> AnalyticsSnapshot:
        if not isinstance(period,DateRange) or not isinstance(context,AnalysisContext):
            raise DomainValidationError("Нужны диапазон и единый контекст расчёта.")
        # Как у дневника: широкий UTC-отбор, затем точная местная дата.
        # Не разрешаем неоднозначную местную полночь и не считаем сутки 24 часами.
        try:
            lower = datetime.combine(period.start,datetime.min.time(),UTC)-timedelta(days=1)
            upper = datetime.combine(period.end,datetime.min.time(),UTC)+timedelta(days=2)
            next_date = period.end+timedelta(days=1)
        except OverflowError:
            lower = upper = next_date = None
        records = {}
        with self.storage.read_snapshot() as session:
            token = session.token
            for name in JOURNALS:
                repo = getattr(session,name)
                if lower is None:
                    rows = repo.all()
                elif name in ("meals","gym"):
                    rows = repo.between(period.start,next_date)
                else:
                    rows = repo.between(lower,upper)
                selected = []
                for record in rows:
                    value = record.value
                    if name in ("meals","gym"):
                        day = value.entry_date
                        eligible = day <= context.today
                    else:
                        moment = value.interval.end if name in ("cognitive","sleep") else value.observed_at
                        day = local_date(moment,context.zone)
                        eligible = moment <= context.now
                    if eligible and period.contains(day):
                        selected.append(record)
                records[name] = tuple(selected)
        return AnalyticsSnapshot(period,context,token,**records)

    def run(self, period: DateRange, indicator: Indicator, context: AnalysisContext) -> AnalyticsResult:
        return calculate_snapshot(self.load(period,context),indicator)

    def compare(self, periods: PeriodPair, indicator: Indicator, context: AnalysisContext) -> ComparisonResult:
        # Даже два непересекающихся периода читаются одной транзакцией.
        bounds = DateRange(min(periods.first.start,periods.second.start),max(periods.first.end,periods.second.end))
        snapshot = self.load(bounds,context)
        return ComparisonResult(snapshot.token,
            compare_periods(snapshot.data,indicator,periods.first,periods.second,context))

    def is_current(self, token: SnapshotToken) -> bool:
        # Только существующая проверка поколения, не контроллер асинхронности/UI.
        return self.storage.is_current(token)
