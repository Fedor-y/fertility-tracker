"""Приватный пакет копии: привязанные к fd пути, fsync и Linux renameat2 NOREPLACE."""
from contextlib import contextmanager
import ctypes
import os
from pathlib import Path
import stat
from uuid import uuid4

from healthtracker.application.backups import BackupError

DATABASE_NAME = 'database.sqlite3'
METADATA_NAME = 'metadata.json'


def check_private(info, *, directory=False):
    correct_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (not correct_type or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077
            or not directory and info.st_nlink != 1):
        raise BackupError('Небезопасные права или тип файла копии.')


@contextmanager
def private_directory(path: Path, *, create=False):
    """Не следовать symlink ни в одном компоненте. Финальный каталог — только владельцу."""
    if not path.is_absolute() or '..' in path.parts:
        raise BackupError('Нужен абсолютный безопасный каталог.')
    current = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=current)
                    os.fsync(current)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=current)
            os.close(current)
            current = child
        check_private(os.fstat(current), directory=True)
        yield current
    finally:
        os.close(current)


@contextmanager
def private_file(directory_fd, name, *, create=False):
    flags = os.O_NOFOLLOW | os.O_CLOEXEC | (os.O_RDWR | os.O_CREAT | os.O_EXCL if create else os.O_RDONLY)
    fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
    try:
        check_private(os.fstat(fd))
        yield fd
    finally:
        os.close(fd)


def rename_noreplace(directory_fd, source, target):
    """Нет небезопасного fallback с перезаписью при отсутствии renameat2."""
    libc = ctypes.CDLL(None, use_errno=True)
    function = getattr(libc, 'renameat2', None)
    if function is None:
        raise BackupError('Файловая система не поддерживает безопасную публикацию.')
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(directory_fd, os.fsencode(source), directory_fd, os.fsencode(target), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


class StagedBackup:
    def __init__(self, root_fd, backup_id):
        self.root_fd = root_fd
        self.backup_id = backup_id
        self.name = '.pending-' + uuid4().hex
        self.fd = None
        self.complete = False
        self._created = False

    def __enter__(self):
        try:
            os.mkdir(self.name, 0o700, dir_fd=self.root_fd)
            self._created = True
            self.fd = os.open(self.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                              dir_fd=self.root_fd)
            check_private(os.fstat(self.fd), directory=True)
            with private_file(self.fd, DATABASE_NAME, create=True):
                pass
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def write_metadata(self, payload):
        with private_file(self.fd, METADATA_NAME, create=True) as fd:
            view = memoryview(payload)
            while view:
                count = os.write(fd, view)
                if count <= 0:
                    raise BackupError('Не удалось записать метаданные копии.')
                view = view[count:]
            os.fsync(fd)

    def publish(self):
        with private_file(self.fd, DATABASE_NAME) as fd:
            os.fsync(fd)
        os.fsync(self.fd)
        rename_noreplace(self.root_fd, self.name, self.backup_id)
        self.name = self.backup_id
        os.fsync(self.root_fd)
        self.complete = True

    def __exit__(self, *args):
        try:
            if self._created and not self.complete:
                if self.fd is not None:
                    # Только файлы, принадлежащие этой новой операции; старый архив не трогаем.
                    for name in (DATABASE_NAME, METADATA_NAME, DATABASE_NAME+'-journal',
                                 DATABASE_NAME+'-wal', DATABASE_NAME+'-shm'):
                        try:
                            os.unlink(name, dir_fd=self.fd)
                        except FileNotFoundError:
                            pass
                    before = os.fstat(self.fd)
                    current = os.stat(self.name, dir_fd=self.root_fd, follow_symlinks=False)
                    if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
                        raise BackupError('Путь временного пакета изменился; очистка остановлена.')
                os.rmdir(self.name, dir_fd=self.root_fd)
                os.fsync(self.root_fd)
        finally:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
