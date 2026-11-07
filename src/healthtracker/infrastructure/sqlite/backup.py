"""Одна проверенная копия через SQLite Backup API, без расписания и ротации."""
from contextlib import contextmanager
from datetime import UTC, date, datetime
import hashlib
import json
import hmac
import math
import os
import re
from pathlib import Path
import sqlite3
from threading import Event
from time import monotonic
from uuid import uuid4

from healthtracker.application.backups import (
    BackupCancelled, BackupError, BackupKind, BackupListing, BackupMetadata, BackupPhase, BackupProgress,
    BackupRequest, BackupResult,
)
from healthtracker.application.errors import StorageBusy
from healthtracker.application.storage import SnapshotToken
from healthtracker.infrastructure.backup_files import (
    DATABASE_NAME, METADATA_NAME, StagedBackup, private_directory, private_file,
)
from healthtracker.infrastructure.sqlite.codecs import decode_time, encode_time
from healthtracker.infrastructure.sqlite.connections import connect
from healthtracker.infrastructure.sqlite.migrations import validate_schema

FORMAT = 'healthtracker.sqlite-backup'


def encode_metadata(value: BackupMetadata) -> bytes:
    payload = dict(format=FORMAT, format_version=value.format_version, backup_id=value.backup_id,
                   created_at_utc=encode_time(value.created_at_utc), archive_date=value.archive_date.isoformat(),
                   source_database_id=value.source.database_id, protected_generation=value.source.generation,
                   schema_version=value.schema_version, migration_checksum=value.migration_checksum,
                   kind=value.kind.value, size_bytes=value.size_bytes, sha256=value.sha256, verified=value.verified)
    canonical = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True).encode('utf-8')
    payload['metadata_sha256'] = hashlib.sha256(canonical).hexdigest()
    return json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True).encode('utf-8')


def decode_metadata(payload: bytes) -> BackupMetadata:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate')
            result[key] = value
        return result
    try:
        value = json.loads(payload, object_pairs_hook=unique)
        fields = {'format', 'format_version', 'backup_id', 'created_at_utc', 'archive_date',
                  'source_database_id', 'protected_generation', 'schema_version', 'migration_checksum',
                  'kind', 'size_bytes', 'sha256', 'verified', 'metadata_sha256'}
        if not isinstance(value, dict) or set(value) != fields or value['format'] != FORMAT:
            raise ValueError('format')
        metadata_digest = value.pop('metadata_sha256')
        canonical = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True).encode('utf-8')
        if not isinstance(metadata_digest, str) or not hmac.compare_digest(metadata_digest, hashlib.sha256(canonical).hexdigest()):
            raise ValueError('metadata checksum')
        archive_date = date.fromisoformat(value['archive_date'])
        if archive_date.isoformat() != value['archive_date']:
            raise ValueError('date')
        return BackupMetadata(value['backup_id'], decode_time(value['created_at_utc']), archive_date,
                              SnapshotToken(value['source_database_id'], value['protected_generation']),
                              value['schema_version'], value['migration_checksum'], BackupKind(value['kind']),
                              value['size_bytes'], value['sha256'], value['verified'], value['format_version'])
    except Exception:
        raise BackupError('Метаданные копии отсутствуют или повреждены.') from None


@contextmanager
def backup_connection(directory_fd, *, readonly):
    """Открывать заранее проверенный файл через закреплённый каталог /proc, без resolve."""
    connection = None
    try:
        mode = 'ro' if readonly else 'rw'
        connection = sqlite3.connect(f'file:/proc/self/fd/{directory_fd}/{DATABASE_NAME}?mode={mode}',
                                     uri=True, isolation_level=None, timeout=2, check_same_thread=True)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA synchronous=FULL')
        if connection.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
            raise BackupError('SQLite не обеспечивает внешние ключи.')
        if readonly:
            connection.execute('PRAGMA query_only=ON')
        yield connection
    finally:
        if connection is not None:
            connection.close()


def fingerprint(directory_fd):
    with private_file(directory_fd, DATABASE_NAME) as fd:
        before = os.fstat(fd)
        digest = hashlib.sha256()
        while block := os.read(fd, 1024 * 1024):
            digest.update(block)
        after = os.fstat(fd)
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise BackupError('Файл копии изменился во время проверки.')
        return after.st_size, digest.hexdigest()


def verify_data(directory_fd):
    with private_file(directory_fd, DATABASE_NAME):
        pass
    with backup_connection(directory_fd, readonly=True) as connection:
        validate_schema(connection)
        version, checksum = connection.execute(
            'SELECT version,checksum FROM schema_migrations ORDER BY version DESC LIMIT 1').fetchone()
    return version, checksum


def verify_bundle(directory_fd, *, expected_id=None):
    with private_file(directory_fd, METADATA_NAME) as fd:
        if os.fstat(fd).st_size > 65536:
            raise BackupError('Слишком большой файл метаданных.')
        payload = b''
        while block := os.read(fd, 65537-len(payload)):
            payload += block
            if len(payload) > 65536:
                raise BackupError('Слишком большой файл метаданных.')
    metadata = decode_metadata(payload)
    if expected_id is not None and metadata.backup_id != expected_id:
        raise BackupError('Идентификатор пакета не совпадает с метаданными.')
    size, digest = fingerprint(directory_fd)
    if (size, digest) != (metadata.size_bytes, metadata.sha256):
        raise BackupError('Размер или контрольная сумма копии не совпадают.')
    version, checksum = verify_data(directory_fd)
    if (version, checksum) != (metadata.schema_version, metadata.migration_checksum):
        raise BackupError('Метаданные не соответствуют схеме копии.')
    if fingerprint(directory_fd) != (size, digest):
        raise BackupError('Копия изменилась во время проверки.')
    return metadata


def inspect_backup(directory: Path) -> BackupResult:
    """Проверка отдельного опубликованного пакета, в том числе после перезапуска."""
    try:
        with private_directory(directory) as fd:
            metadata = verify_bundle(fd, expected_id=directory.name)
        return BackupResult(directory, metadata)
    except Exception:
        raise BackupError('Резервная копия не прошла проверку.') from None


class SQLiteBackup:
    def __init__(self, database, *, clock=lambda: datetime.now(UTC), timeout=30.0):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Нужен положительный тайм-аут Backup API.')
        self.database = database
        self.clock = clock
        self.timeout = timeout

    @property
    def default_directory(self):
        return self.database.path.parent / 'backups'

    def inspect(self, directory):
        return inspect_backup(directory)

    def scan(self, directory):
        """Список только проверенных пакетов; это не реестр и не ротация."""
        BackupRequest(directory)
        copies = []
        unverified = 0
        try:
            # При первом посещении создаётся только пустая стандартная папка 0700.
            # Недоступный пользовательский путь не заменяется и не создаётся заново.
            with private_directory(directory, create=directory == self.default_directory) as fd:
                with os.scandir(fd) as entries:
                    names = [entry.name for entry in entries
                             if re.fullmatch('[0-9a-f]{32}', entry.name) and entry.is_dir(follow_symlinks=False)]
                for name in names:
                    try:
                        copies.append(inspect_backup(directory / name))
                    except BackupError:
                        unverified += 1
            copies.sort(key=lambda item: (item.metadata.created_at_utc, item.metadata.backup_id), reverse=True)
            return BackupListing(directory, tuple(copies), unverified)
        except Exception:
            raise BackupError('Не удалось прочитать каталог резервных копий.') from None

    def _copy(self, source, target, progress):
        deadline = monotonic() + self.timeout
        def report(status, remaining, total):
            if monotonic() >= deadline:
                raise BackupError('Превышено время получения снимка SQLite.')
            if status not in (sqlite3.SQLITE_OK, sqlite3.SQLITE_DONE, sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise BackupError('Ошибка получения снимка SQLite.')
            progress(BackupProgress(BackupPhase.COPYING, remaining, total))
        source.backup(target, pages=128, progress=report, sleep=0.01)

    def _snapshot(self, stage, cancel, progress):
        failure = None
        started = False
        try:
            with self.database.exclusive(cancel=cancel) as access:
                started = True
                # Проверяем источник до Backup API: неизвестная/повреждённая схема — критическая ошибка.
                access.confirm_safe(unchanged=True)
                token = access.token
                try:
                    now = self.clock()
                    if not isinstance(now, datetime) or now.tzinfo is None:
                        raise BackupError('Нужен определённый UTC-момент создания копии.')
                    now = now.astimezone(UTC)
                    archive_date = now.astimezone().date()
                    progress(BackupProgress(BackupPhase.COPYING))
                    with connect(self.database.path, readonly=True) as source:
                        with backup_connection(stage.fd, readonly=False) as target:
                            self._copy(source, target, progress)
                except Exception:
                    failure = BackupError('Не удалось получить резервный снимок SQLite.')
                # Ошибка целевого носителя не объявляет повреждённой исправную основную базу.
                access.confirm_safe(unchanged=True)
        except StorageBusy:
            if not started and cancel.is_set():
                raise BackupCancelled('Создание копии отменено до начала операции.') from None
            raise
        if failure is not None:
            raise failure
        return token, now, archive_date

    def create(self, request: BackupRequest, *, cancel: Event, progress=lambda value: None) -> BackupResult:
        if not isinstance(request, BackupRequest):
            raise BackupError('Нужен типизированный запрос копии.')
        if cancel.is_set():
            raise BackupCancelled('Создание копии отменено до начала операции.')
        try:
            progress(BackupProgress(BackupPhase.WAITING))
            with private_directory(request.directory, create=True) as root_fd:
                backup_id = uuid4().hex
                with StagedBackup(root_fd, backup_id) as stage:
                    token, now, archive_date = self._snapshot(stage, cancel, progress)
                    progress(BackupProgress(BackupPhase.VERIFYING))
                    version, checksum = verify_data(stage.fd)
                    size, digest = fingerprint(stage.fd)
                    metadata = BackupMetadata(backup_id, now, archive_date, token, version, checksum,
                                              request.kind, size, digest)
                    stage.write_metadata(encode_metadata(metadata))
                    verified = verify_bundle(stage.fd, expected_id=backup_id)
                    if verified != metadata:
                        raise BackupError('Метаданные изменились перед публикацией.')
                    progress(BackupProgress(BackupPhase.PUBLISHING))
                    stage.publish()
                result = BackupResult(request.directory / backup_id, metadata)
            # COMPLETE выдаётся только после закрытия файлов и успешной публикации.
            try:
                progress(BackupProgress(BackupPhase.COMPLETE))
            except Exception:
                pass  # Наблюдатель не может отменить уже зафиксированную публикацию.
            return result
        except BackupCancelled:
            raise
        except Exception:
            # Состояние источника при критическом отказе уже установлено координатором.
            raise BackupError('Не удалось создать проверенную резервную копию.') from None
