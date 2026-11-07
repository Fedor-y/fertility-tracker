"""Базовая замена из прежнего пакета; исходник сохранён, продолжение после перезапуска."""
from contextlib import contextmanager
import hashlib
import json
import os
from uuid import uuid4

from healthtracker.application.restoration import PreparedRestore, RestoreError, RestoreResult
from healthtracker.infrastructure.backup_files import private_directory, private_file
from healthtracker.infrastructure.sqlite.backup import inspect_backup
from healthtracker.infrastructure.sqlite.connections import connect
from healthtracker.infrastructure.sqlite.migrations import validate_schema

CANDIDATE = 'candidate.sqlite3'


def write_all(fd, payload):
    view = memoryview(payload)
    while view:
        count = os.write(fd, view)
        if count <= 0:
            raise RestoreError('Не удалось записать подготовленный файл.')
        view = view[count:]


class SQLiteRestore:
    def __init__(self, database):
        self.database = database

    def _validate_candidate(self, prepared):
        with private_directory(prepared.workspace) as fd:
            with private_file(fd, CANDIDATE) as file:
                digest = hashlib.sha256()
                size = 0
                while block := os.read(file, 1024*1024):
                    digest.update(block)
                    size += len(block)
        expected = prepared.backup.metadata
        if (size, digest.hexdigest()) != (expected.size_bytes, expected.sha256):
            raise RestoreError('Подготовленный файл не соответствует выбранной копии.')
        with connect(prepared.workspace / CANDIDATE, readonly=True) as connection:
            validate_schema(connection)

    @contextmanager
    def prepare(self, backup):
        if inspect_backup(backup.directory) != backup:
            raise RestoreError('Выбранная копия изменилась. Обновите список.')
        workspace = self.database.path.parent / ('.restore-' + uuid4().hex)
        prepared = PreparedRestore(workspace, backup)
        workspace.mkdir(mode=0o700)
        try:
            with private_directory(workspace) as target:
                with private_directory(backup.directory) as source:
                    with private_file(source, 'database.sqlite3') as reader:
                        with private_file(target, CANDIDATE, create=True) as writer:
                            # Архивный файл, не открытая основная база. Её защитная
                            # копия создаётся отдельно прежним Backup API.
                            while block := os.read(reader, 1024*1024):
                                write_all(writer, block)
                            os.fsync(writer)
                os.fsync(target)
            self._validate_candidate(prepared)
            yield prepared
        finally:
            if not prepared.retain:
                for suffix in ('', '-wal', '-shm', '-journal'):
                    try:
                        (workspace / (CANDIDATE + suffix)).unlink()
                    except FileNotFoundError:
                        pass
                workspace.rmdir()

    def _replace(self, workspace_fd, root_fd):
        os.replace(CANDIDATE, self.database.path.name, src_dir_fd=workspace_fd, dst_dir_fd=root_fd)

    def install(self, prepared, safety):
        failure = False
        self._validate_candidate(prepared)
        with self.database.exclusive() as access:
            # Даже запись между защитной копией и exclusive не теряется: замена
            # отменяется, если защитная копия относится к прежнему поколению.
            if access.token != safety.metadata.source:
                access.confirm_safe(unchanged=True)
                failure = True
            else:
                access.confirm_safe(unchanged=True)
                prepared.retain = True
                with private_directory(self.database.path.parent) as root:
                    with private_directory(prepared.workspace) as workspace:
                        moved = []
                        installed = False
                        marker_created = False
                        name = self.database.path.name
                        marker = self.database.restore_marker.name
                        try:
                            with private_file(root, marker, create=True) as fd:
                                marker_created = True
                                write_all(fd, json.dumps({'version':1, 'workspace':prepared.workspace.name}).encode())
                                os.fsync(fd)
                            os.fsync(root)
                            for suffix in ('', '-wal', '-shm', '-journal'):
                                original = name + suffix
                                try:
                                    with private_file(root, original):
                                        pass
                                except FileNotFoundError:
                                    if not suffix:
                                        raise
                                    continue
                                saved = 'original.sqlite3' + suffix
                                os.rename(original, saved, src_dir_fd=root, dst_dir_fd=workspace)
                                moved.append((original, saved))
                            os.fsync(workspace)
                            os.fsync(root)
                            self._replace(workspace, root)
                            installed = True
                            with private_file(root, name) as fd:
                                os.fsync(fd)
                            os.fsync(root)
                            access.confirm_safe(restart_required=True)
                            os.unlink(marker, dir_fd=root)
                            marker_created = False
                            os.fsync(root)
                        except Exception:
                            # Последний fsync мог отказать уже после unlink маркера.
                            # До любых обратных перемещений снова ставим guard.
                            if (moved or installed) and not marker_created:
                                with private_file(root, marker, create=True) as fd:
                                    marker_created = True
                                    write_all(fd, json.dumps({'version':1, 'workspace':prepared.workspace.name}).encode())
                                    os.fsync(fd)
                                os.fsync(root)
                            # Откат именно текущей операции, не автоматическое
                            # восстановление из произвольного архивного пакета.
                            if installed:
                                for suffix in ('', '-wal', '-shm', '-journal'):
                                    try:
                                        os.rename(name+suffix, 'failed.sqlite3'+suffix,
                                                  src_dir_fd=root, dst_dir_fd=workspace)
                                    except FileNotFoundError:
                                        if not suffix:
                                            raise
                            for original, saved in moved:
                                os.rename(saved, original, src_dir_fd=workspace, dst_dir_fd=root)
                            os.fsync(root)
                            os.fsync(workspace)
                            access.confirm_safe(unchanged=not moved, restart_required=bool(moved))
                            if marker_created:
                                os.unlink(marker, dir_fd=root)
                                os.fsync(root)
                            failure = True
        if failure:
            raise RestoreError('Замена отменена или выполнен откат; исходные данные не объявляются восстановленными.')
        return RestoreResult(prepared.backup, safety)
