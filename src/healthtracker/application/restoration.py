"""Отдельный сценарий восстановления: кандидат, прежняя очередь копий, замена."""
from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Protocol

from healthtracker.application.errors import StorageError

if TYPE_CHECKING:
    from healthtracker.application.backups import BackupResult


class RestoreError(StorageError):
    pass


@dataclass(frozen=True, slots=True)
class RestoreRequest:
    backup: BackupResult
    safety_directory: Path

    def __post_init__(self):
        from healthtracker.application.backups import BackupRequest, BackupResult
        if not isinstance(self.backup, BackupResult):
            raise RestoreError('Нужна выбранная проверенная копия.')
        BackupRequest(self.backup.directory)
        BackupRequest(self.safety_directory)


@dataclass(slots=True)
class PreparedRestore:
    workspace: Path
    backup: BackupResult
    retain: bool = False


@dataclass(frozen=True, slots=True)
class RestoreResult:
    backup: BackupResult
    safety: BackupResult
    restart_required: bool = True


class RestorePort(Protocol):
    def prepare(self, backup: BackupResult) -> AbstractContextManager[PreparedRestore]: ...
    def install(self, prepared: PreparedRestore, safety: BackupResult) -> RestoreResult: ...


class Restoration:
    def __init__(self, port: RestorePort, create_backup):
        self.port = port
        self.create_backup = create_backup

    def restore(self, request: RestoreRequest, progress) -> RestoreResult:
        from healthtracker.application.backups import BackupKind, BackupPhase, BackupProgress, BackupRequest
        try:
            progress(BackupProgress(BackupPhase.RESTORE_PREPARING))
            with self.port.prepare(request.backup) as prepared:
                # Не submit/result в собственный пул: прежний сценарий копирования
                # исполняется непосредственно тем же единственным worker.
                safety = self.create_backup(BackupRequest(request.safety_directory, BackupKind.PRE_RESTORE), Event())
                progress(BackupProgress(BackupPhase.RESTORE_REPLACING))
                return self.port.install(prepared, safety)
        except Exception:
            raise RestoreError('Не удалось завершить восстановление. Проверьте сообщения о состоянии базы; защитные файлы не удаляются.') from None
