"""Явные транзакции и ограниченные владельцем локальные файлы."""

from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
import stat

from healthtracker.infrastructure.sqlite.errors import (
    ConstraintViolation, StorageBusy, StorageError, StorageRecoveryRequired,
)


@contextmanager
def storage_errors():
    try:
        yield
    except sqlite3.IntegrityError:
        raise ConstraintViolation("Данные нарушают ограничения хранения.") from None
    except sqlite3.Error as error:
        code = getattr(error, "sqlite_errorcode", 0) & 0xff
        if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise StorageBusy("Хранилище занято. Повторите операцию.") from None
        if code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
            raise StorageRecoveryRequired("База повреждена или имеет неизвестный формат. Запись запрещена.") from None
        raise StorageError("Не удалось выполнить операцию хранения.") from None
    except OSError:
        raise StorageError("Ошибка доступа к локальному хранилищу.") from None


def prepare_private_file(path: Path) -> bool:
    """Создать новый файл 0600; существующий не переписывать и не chmod вслепую."""
    with storage_errors():
        missing = []
        parent = path.parent
        while not parent.exists():
            missing.append(parent)
            parent = parent.parent
        for directory in reversed(missing):
            directory.mkdir(mode=0o700)
        parent_info = path.parent.stat()
        if parent_info.st_uid != os.getuid() or stat.S_IMODE(parent_info.st_mode) & 0o077:
            raise StorageError("Каталог данных должен быть доступен только владельцу.")
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) & 0o077):
                raise StorageError("Небезопасные права или тип файла базы.")
            return False
        else:
            os.close(fd)
            return True


@contextmanager
def connect(path: Path, *, readonly: bool = False):
    """Только открыть существующий файл; создание всегда отдельное явное действие."""
    connection = None
    with storage_errors():
        try:
            mode = "ro" if readonly else "rw"
            connection = sqlite3.connect(
                path.resolve().as_uri() + "?mode=" + mode, uri=True,
                isolation_level=None, autocommit=sqlite3.LEGACY_TRANSACTION_CONTROL,
                timeout=2.0, check_same_thread=True,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
                raise StorageError("SQLite не обеспечивает внешние ключи.")
            if readonly:
                connection.execute("PRAGMA query_only=ON")
            yield connection
        finally:
            if connection is not None:
                connection.close()


@contextmanager
def transaction(connection: sqlite3.Connection, *, write: bool = False):
    """Без executescript: DDL и регистрация версии не должны коммититься отдельно."""
    if connection.in_transaction:
        raise StorageError("Вложенная транзакция не допускается.")
    with storage_errors():
        committing = False
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            committing = True
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    raise StorageRecoveryRequired("Откат не завершён. Нужна проверка базы.") from None
            elif committing:
                raise StorageRecoveryRequired("Результат фиксации не определён. Нужна проверка базы.") from None
            raise
