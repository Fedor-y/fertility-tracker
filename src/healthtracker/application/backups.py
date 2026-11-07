"""Типизированный сценарий одной копии; очередь worker без Qt и файлового ввода-вывода."""
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, UTC
from enum import Enum
from pathlib import Path
import re
from threading import Event, Lock
from typing import Callable, Protocol

from healthtracker.application.errors import StorageError, StorageBusy
from healthtracker.application.storage import SnapshotToken
from healthtracker.application.restoration import RestorePort, RestoreRequest, RestoreResult, Restoration


class BackupError(StorageError):
    """Копия не опубликована как пригодная; сообщение не содержит личных данных."""


class BackupCancelled(BackupError):
    """Отмена до входа в критическую последовательность."""


class BackupKind(Enum):
    AUTOMATIC = 'automatic'
    MANUAL = 'manual'
    PRE_MIGRATION = 'pre_migration'
    PRE_RESTORE = 'pre_restore'


class BackupPhase(Enum):
    WAITING = 'waiting'
    COPYING = 'copying'
    VERIFYING = 'verifying'
    PUBLISHING = 'publishing'
    COMPLETE = 'complete'
    RESTORE_PREPARING = 'restore_preparing'
    RESTORE_REPLACING = 'restore_replacing'


@dataclass(frozen=True, slots=True)
class BackupProgress:
    phase: BackupPhase
    remaining_pages: int = 0
    total_pages: int = 0


@dataclass(frozen=True, slots=True)
class BackupRequest:
    directory: Path
    kind: BackupKind = BackupKind.MANUAL

    def __post_init__(self):
        if not isinstance(self.directory, Path) or not self.directory.is_absolute() or '..' in self.directory.parts:
            raise BackupError('Нужен явный абсолютный каталог копии.')
        if not isinstance(self.kind, BackupKind):
            raise BackupError('Неизвестный тип копии.')


@dataclass(frozen=True, slots=True)
class BackupMetadata:
    backup_id: str
    created_at_utc: datetime
    archive_date: date
    source: SnapshotToken
    schema_version: int
    migration_checksum: str
    kind: BackupKind
    size_bytes: int
    sha256: str
    verified: bool = True
    format_version: int = 1

    def __post_init__(self):
        hex32 = lambda value: isinstance(value, str) and re.fullmatch('[0-9a-f]{32}', value) is not None
        hex64 = lambda value: isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None
        if (not hex32(self.backup_id) or not isinstance(self.source, SnapshotToken)
                or not hex32(self.source.database_id) or type(self.source.generation) is not int
                or self.source.generation < 0 or type(self.schema_version) is not int or self.schema_version != 1
                or not hex64(self.migration_checksum) or not hex64(self.sha256)
                or type(self.size_bytes) is not int or self.size_bytes <= 0
                or type(self.format_version) is not int or self.format_version != 1
                or self.verified is not True or not isinstance(self.kind, BackupKind)
                or not isinstance(self.created_at_utc, datetime) or self.created_at_utc.tzinfo is None
                or self.created_at_utc.utcoffset() != UTC.utcoffset(None)
                or type(self.archive_date) is not date):
            raise BackupError('Метаданные копии некорректны.')


@dataclass(frozen=True, slots=True)
class BackupResult:
    directory: Path
    metadata: BackupMetadata

    @property
    def database_path(self):
        return self.directory / 'database.sqlite3'


@dataclass(frozen=True, slots=True)
class BackupListing:
    directory: Path
    copies: tuple[BackupResult, ...] = ()
    unverified_count: int = 0


class BackupPort(Protocol):
    @property
    def default_directory(self) -> Path: ...
    def inspect(self, directory: Path) -> BackupResult: ...
    def scan(self, directory: Path) -> BackupListing: ...
    def create(self, request: BackupRequest, *, cancel: Event,
               progress: Callable[[BackupProgress], None]) -> BackupResult: ...


class BackupService:
    """Одна последовательная очередь всех типов. Соединения создаёт worker адаптера."""
    def __init__(self, port: BackupPort, restore_port: RestorePort | None = None):
        self._port = port
        self._restore_port = restore_port
        self._restoring = False
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='healthtracker-backup')
        self._guard = Lock()  # Только очередь/состояние worker, не координация SQLite.
        self._pending = 0
        self._closing = False
        self._stopped = False
        self._progress = BackupProgress(BackupPhase.WAITING)

    @property
    def busy(self):
        with self._guard:
            return self._pending != 0

    @property
    def progress(self):
        with self._guard:
            return self._progress

    def _update(self, progress):
        with self._guard:
            self._progress = progress

    def create(self, request: BackupRequest, *, cancel: Event | None = None) -> Future[BackupResult]:
        if not isinstance(request, BackupRequest):
            raise BackupError('Нужен типизированный запрос копии.')
        cancellation = cancel if cancel is not None else Event()
        return self._submit(self._run, request, cancellation)

    @property
    def default_directory(self) -> Path:
        return self._port.default_directory

    def scan(self, directory: Path) -> Future[BackupListing]:
        BackupRequest(directory)  # Проверка пути без файловых операций в вызывающем потоке.
        return self._submit(self._port.scan, directory)

    @property
    def can_restore(self):
        return self._restore_port is not None

    @property
    def restoring(self):
        with self._guard:
            return self._restoring

    def restore(self, request: RestoreRequest) -> Future[RestoreResult]:
        if not isinstance(request, RestoreRequest) or self._restore_port is None:
            raise StorageError('Восстановление недоступно.')
        scenario = Restoration(self._restore_port, self._run)
        return self._submit(scenario.restore, request, self._update, restoring=True)

    def _submit(self, operation, *args, restoring=False):
        with self._guard:
            if self._closing or self._restoring or restoring and self._pending:
                raise StorageBusy('Работа с копиями занята или завершается.')
            if restoring:
                self._restoring = True
            self._pending += 1
            try:
                future = self._pool.submit(operation, *args)
            except BaseException:
                self._pending -= 1
                if restoring:
                    self._restoring = False
                raise
        # add_done_callback может вызываться синхронно для уже завершённого Future.
        # Регистрировать вне guard; учитывается также Future.cancel до запуска worker.
        future.add_done_callback(self._restore_finished if restoring else self._finished)
        return future

    def _restore_finished(self, future):
        with self._guard:
            self._restoring = False
            self._pending -= 1

    def _finished(self, future):
        with self._guard:
            self._pending -= 1

    def _run(self, request, cancel):
        if cancel.is_set():
            raise BackupCancelled('Создание копии отменено до начала операции.')
        result = self._port.create(request, cancel=cancel, progress=self._update)
        self._update(BackupProgress(BackupPhase.VERIFYING))
        verified = self._port.inspect(result.directory)
        if verified != result:
            raise BackupError('Опубликованная копия не соответствует результату проверки.')
        self._update(BackupProgress(BackupPhase.COMPLETE))
        return verified

    def resume(self):
        with self._guard:
            if not self._stopped:
                self._closing = False

    def begin_close(self):
        with self._guard:
            self._closing = True
            return self._pending == 0

    def shutdown(self, *, wait=True):
        self.begin_close()
        with self._guard:
            self._stopped = True
        self._pool.shutdown(wait=wait, cancel_futures=False)
