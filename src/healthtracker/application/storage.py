"""Минимальные контракты хранилища, независимые от SQLite."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Protocol
from enum import Enum

from healthtracker.domain.measurement import CognitiveMeasurement
from healthtracker.domain.records import (
    PhysicalRecord, StressRecord, MoodRecord, SleepRecord, MealRecord, GymRecord,
)


class AccessState(Enum):
    NORMAL = "normal"
    EXCLUSIVE = "exclusive"
    RECOVERY_REQUIRED = "recovery_required"


@dataclass(frozen=True, slots=True)
class AccessStatus:
    state: AccessState
    opened: bool
    active_sessions: int = 0
    restart_required: bool = False

    @property
    def available(self):
        return self.opened and self.state is AccessState.NORMAL and not self.restart_required


@dataclass(frozen=True, slots=True)
class StoredRecord[T]:
    id: int
    value: T


@dataclass(frozen=True, slots=True)
class SnapshotToken:
    database_id: str
    generation: int


class ExclusivePermission(Protocol):
    token: SnapshotToken
    def confirm_safe(self, *, unchanged: bool = False, restart_required: bool = False) -> None: ...


class ReadRepository[T](Protocol):
    def get(self, record_id: int) -> StoredRecord[T] | None: ...
    def all(self) -> tuple[StoredRecord[T], ...]: ...
    def between(self, start: date | datetime, end: date | datetime) -> tuple[StoredRecord[T], ...]: ...


class Repository[T](ReadRepository[T], Protocol):
    def create(self, value: T) -> int: ...
    def update(self, record_id: int, value: T) -> None: ...
    def delete(self, record_id: int) -> None: ...


class SettingsRepository(Protocol):
    def get(self, key: str): ...
    def set(self, key: str, value) -> None: ...
    def delete(self, key: str) -> None: ...


class ReadSession(Protocol):
    token: SnapshotToken
    settings: SettingsRepository
    cognitive: ReadRepository[CognitiveMeasurement]
    physical: ReadRepository[PhysicalRecord]
    stress: ReadRepository[StressRecord]
    mood: ReadRepository[MoodRecord]
    sleep: ReadRepository[SleepRecord]
    meals: ReadRepository[MealRecord]
    gym: ReadRepository[GymRecord]


class Storage(Protocol):
    @property
    def access_status(self) -> AccessStatus: ...
    def exclusive(self, *, cancel=None) -> AbstractContextManager[ExclusivePermission]: ...
    def initialize(self): ...
    def close(self) -> None: ...
    def write(self) -> AbstractContextManager: ...
    def read_snapshot(self) -> AbstractContextManager[ReadSession]: ...
    def is_current(self, token: SnapshotToken) -> bool: ...
    def capture_token(self) -> SnapshotToken: ...
    def apply_if_current(self, token: SnapshotToken, action: Callable[[], None], *, require_ready: bool = True) -> bool | None: ...
