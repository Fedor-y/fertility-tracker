"""Интервалы измерений и сна. Без SQL, системных часов и аналитики периодов."""

from collections.abc import Iterable
from dataclasses import InitVar, dataclass, field
from datetime import date, datetime, timedelta, tzinfo

from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.time import as_utc, local_date


COGNITIVE_WINDOW = timedelta(minutes=60)
LONG_SLEEP_THRESHOLD = timedelta(hours=16)


def _not_future(end: datetime, now: datetime) -> None:
    if end > as_utc(now):
        raise DomainValidationError("Нельзя сохранить наблюдение из будущего.")


@dataclass(frozen=True, slots=True)
class CognitiveInterval:
    end: datetime
    now: InitVar[datetime] = field(kw_only=True)
    start: datetime = field(init=False)

    def __post_init__(self, now: datetime) -> None:
        end = as_utc(self.end)
        _not_future(end, now)
        try:
            start = end - COGNITIVE_WINDOW
        except OverflowError as error:
            raise DomainValidationError("Начало оцениваемого часа вне диапазона дат.") from error
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "start", start)

    def date_in(self, zone: tzinfo) -> date:
        return local_date(self.end, zone)


@dataclass(frozen=True, slots=True)
class SleepInterval:
    start: datetime
    end: datetime
    now: InitVar[datetime] = field(kw_only=True)

    def __post_init__(self, now: datetime) -> None:
        start, end = as_utc(self.start), as_utc(self.end)
        if end <= start:
            raise DomainValidationError("Пробуждение должно быть позже засыпания.")
        _not_future(end, now)
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    @property
    def requires_confirmation(self) -> bool:
        """Предупреждение, а не запрет: подтверждение получает будущая форма."""
        return self.duration > LONG_SLEEP_THRESHOLD

    def date_in(self, zone: tzinfo) -> date:
        return local_date(self.end, zone)


def ensure_no_sleep_overlap(
    candidate: SleepInterval, existing: Iterable[SleepInterval],
) -> None:
    """При редактировании Application исключает старую запись по её ID.

    Касание границ допустимо: интервалы полуоткрытые. Проверка обязательна
    внутри будущей транзакции сохранения, а не только при вводе формы.
    """
    if not isinstance(candidate, SleepInterval):
        raise DomainValidationError("Ожидается интервал сна.")
    for other in existing:
        if not isinstance(other, SleepInterval):
            raise DomainValidationError("Список сна содержит неопределённый интервал.")
        if candidate.start < other.end and other.start < candidate.end:
            raise DomainValidationError("Интервалы сна не должны пересекаться.")
