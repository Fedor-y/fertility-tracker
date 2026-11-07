"""Типизированные данные остальных журналов для репозиториев, без хранения и UI."""

from dataclasses import dataclass, replace
from datetime import date, datetime

from healthtracker.domain.catalogs import (
    CaffeineStatus, MealCategory, StressCause, SymptomCode, SymptomStatus,
)
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.intervals import SleepInterval
from healthtracker.domain.scales import SymptomIntensity, get_numeric_scale, validate_score
from healthtracker.domain.time import as_utc


def optional_text(value: str | None) -> str | None:
    if value is not None and not isinstance(value, str):
        raise DomainValidationError("Необязательное описание должно быть текстом.")
    return value if value is not None and value.strip() else None


def _enum(value, enum_type) -> None:
    if not isinstance(value, enum_type):
        raise DomainValidationError("Неизвестная категория.")


def _date(value) -> None:
    if type(value) is not date:
        raise DomainValidationError("Нужна календарная дата без времени.")


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordMetadata:
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        created, updated = as_utc(self.created_at), as_utc(self.updated_at)
        if updated < created:
            raise DomainValidationError("Изменение не может предшествовать созданию.")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "updated_at", updated)


@dataclass(frozen=True, slots=True, kw_only=True)
class MomentRecord(RecordMetadata):
    observed_at: datetime

    def __post_init__(self) -> None:
        RecordMetadata.__post_init__(self)
        object.__setattr__(self, "observed_at", as_utc(self.observed_at))


@dataclass(frozen=True, slots=True)
class Symptom:
    code: SymptomCode
    intensity: SymptomIntensity | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        _enum(self.code, SymptomCode)
        if self.intensity is not None:
            _enum(self.intensity, SymptomIntensity)
        object.__setattr__(self, "detail", optional_text(self.detail))


@dataclass(frozen=True, slots=True, kw_only=True)
class PhysicalRecord(MomentRecord):
    score: int
    symptom_status: SymptomStatus
    symptoms: tuple[Symptom, ...] = ()
    scale_version: int = 1

    def __post_init__(self) -> None:
        MomentRecord.__post_init__(self)
        validate_score(self.score)
        get_numeric_scale("physical", self.scale_version)
        _enum(self.symptom_status, SymptomStatus)
        if type(self.symptoms) is not tuple or any(not isinstance(s, Symptom) for s in self.symptoms):
            raise DomainValidationError("Нужен определённый список симптомов.")
        if (self.symptom_status is SymptomStatus.LISTED) != bool(self.symptoms):
            raise DomainValidationError("Симптомы не соответствуют статусу сведений.")
        if len({s.code for s in self.symptoms}) != len(self.symptoms):
            raise DomainValidationError("Симптом не должен повторяться в записи.")


@dataclass(frozen=True, slots=True, kw_only=True)
class StressRecord(MomentRecord):
    score: int
    causes: tuple[StressCause, ...] = ()
    comment: str | None = None
    scale_version: int = 1

    def __post_init__(self) -> None:
        MomentRecord.__post_init__(self)
        validate_score(self.score)
        get_numeric_scale("stress", self.scale_version)
        if type(self.causes) is not tuple:
            raise DomainValidationError("Нужен определённый список причин.")
        for cause in self.causes:
            _enum(cause, StressCause)
        if len(set(self.causes)) != len(self.causes):
            raise DomainValidationError("Причина не должна повторяться в записи.")
        object.__setattr__(self, "comment", optional_text(self.comment))


@dataclass(frozen=True, slots=True, kw_only=True)
class MoodRecord(MomentRecord):
    score: int
    scale_version: int = 1

    def __post_init__(self) -> None:
        MomentRecord.__post_init__(self)
        validate_score(self.score)
        get_numeric_scale("mood", self.scale_version)


@dataclass(frozen=True, slots=True, kw_only=True)
class SleepRecord(RecordMetadata):
    interval: SleepInterval

    def __post_init__(self) -> None:
        RecordMetadata.__post_init__(self)
        if not isinstance(self.interval, SleepInterval):
            raise DomainValidationError("Необходим определённый интервал сна.")


@dataclass(frozen=True, slots=True, kw_only=True)
class MealItem(RecordMetadata):
    name: str
    composition: str | None = None
    quantity_text: str | None = None
    caffeine_status: CaffeineStatus = CaffeineStatus.UNSPECIFIED

    def __post_init__(self) -> None:
        RecordMetadata.__post_init__(self)
        if not isinstance(self.name, str) or not self.name.strip():
            raise DomainValidationError("Необходимо название позиции питания.")
        _enum(self.caffeine_status, CaffeineStatus)
        for field in ("composition", "quantity_text"):
            object.__setattr__(self, field, optional_text(getattr(self, field)))


@dataclass(frozen=True, slots=True, kw_only=True)
class MealRecord(RecordMetadata):
    entry_date: date
    category: MealCategory
    items: tuple[MealItem, ...]
    note: str | None = None

    def __post_init__(self) -> None:
        RecordMetadata.__post_init__(self)
        _date(self.entry_date)
        _enum(self.category, MealCategory)
        if (type(self.items) is not tuple or not self.items
                or any(not isinstance(item, MealItem) for item in self.items)):
            raise DomainValidationError("Приём пищи должен содержать позиции.")
        object.__setattr__(self, "note", optional_text(self.note))


@dataclass(frozen=True, slots=True, kw_only=True)
class GymRecord(RecordMetadata):
    entry_date: date
    attended: bool
    difficulty: int | None = None
    difficulty_scale_version: int | None = None

    def __post_init__(self) -> None:
        RecordMetadata.__post_init__(self)
        _date(self.entry_date)
        if type(self.attended) is not bool:
            raise DomainValidationError("Посещение должно быть явным ответом да/нет.")
        if self.attended:
            validate_score(self.difficulty)
            get_numeric_scale("gym_difficulty", self.difficulty_scale_version)
        elif self.difficulty is not None or self.difficulty_scale_version is not None:
            raise DomainValidationError("При отсутствии посещения сложность не задаётся.")


def validate_record_time(value, *, now: datetime, today: date) -> None:
    """Повторная проверка на границе сохранения с явно переданными часами."""
    now = as_utc(now)
    _date(today)
    if value.created_at > now or value.updated_at > now:
        raise DomainValidationError("Служебное время не может быть в будущем.")
    if isinstance(value, (MealRecord, GymRecord)):
        if value.entry_date > today:
            raise DomainValidationError("Дата события не может быть в будущем.")
        if isinstance(value, MealRecord):
            for item in value.items:
                if item.created_at > now or item.updated_at > now:
                    raise DomainValidationError("Служебное время позиции не может быть в будущем.")
    else:
        end = value.observed_at if isinstance(value, MomentRecord) else value.interval.end
        if end > now:
            raise DomainValidationError("Время наблюдения не может быть в будущем.")


def prepare_stress_edit(previous: StressRecord | None, replacement: StressRecord) -> StressRecord:
    if previous is not None and previous.score > 0 and replacement.score == 0:
        return replace(replacement, causes=(), comment=None)
    return replacement


def meal_duplicate_warning_needed(value: MealRecord, previous: MealRecord | None, *, has_duplicates: bool) -> bool:
    if value.category is MealCategory.OTHER:
        return False
    changed = previous is None or (previous.entry_date, previous.category) != (value.entry_date, value.category)
    return changed and has_duplicates
