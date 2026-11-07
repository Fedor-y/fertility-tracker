"""Единый координатор коротких сессий и согласованных снимков SQLite."""

from contextlib import contextmanager
from datetime import UTC, datetime
import fcntl
import os
from pathlib import Path
from threading import Condition, RLock, local, get_ident
from uuid import uuid4

from healthtracker.application.storage import AccessState, AccessStatus, SnapshotToken
from healthtracker.domain.time import as_utc
from healthtracker.infrastructure.sqlite.connections import connect, prepare_private_file, storage_errors, transaction
from healthtracker.infrastructure.sqlite.errors import StorageBusy, StorageError, StorageRecoveryRequired
from healthtracker.infrastructure.sqlite.migrations import initialize_schema, inspect_existing_schema


def default_database_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    directory = Path(base) if base and Path(base).is_absolute() else Path.home() / ".local/share"
    return directory / "healthtracker/healthtracker.sqlite3"


class Session:
    def __init__(self, connection, *, now, token, writable):
        self.connection = connection
        self.now = now
        self.today = now.astimezone().date()
        self.token = token
        self.writable = writable
        self.active = True
        self.poisoned = False

    def ensure_active(self, *, write=False):
        if not self.active or self.poisoned or (write and not self.writable):
            raise StorageError("Сессия закрыта или не допускает запись.")

    @contextmanager
    def operation(self):
        """Связанная запись атомарна даже при перехвате ошибки вызывающим кодом."""
        self.ensure_active(write=True)
        with storage_errors():
            self.connection.execute("SAVEPOINT repository_operation")
            try:
                yield
                self.connection.execute("RELEASE repository_operation")
            except BaseException:
                try:
                    self.connection.execute("ROLLBACK TO repository_operation")
                    self.connection.execute("RELEASE repository_operation")
                except Exception:
                    self.poisoned = True
                    raise StorageRecoveryRequired("Операцию не удалось откатить. Запись заблокирована.") from None
                raise

    @property
    def cognitive(self):
        from healthtracker.infrastructure.sqlite.cognitive import CognitiveRepository
        return CognitiveRepository(self)

    @property
    def physical(self):
        from healthtracker.infrastructure.sqlite.physical import PhysicalRepository
        return PhysicalRepository(self)

    @property
    def stress(self):
        from healthtracker.infrastructure.sqlite.stress import StressRepository
        return StressRepository(self)

    @property
    def mood(self):
        from healthtracker.infrastructure.sqlite.mood import MoodRepository
        return MoodRepository(self)

    @property
    def sleep(self):
        from healthtracker.infrastructure.sqlite.sleep import SleepRepository
        return SleepRepository(self)

    @property
    def meals(self):
        from healthtracker.infrastructure.sqlite.meals import MealRepository
        return MealRepository(self)

    @property
    def gym(self):
        from healthtracker.infrastructure.sqlite.gym import GymRepository
        return GymRepository(self)

    @property
    def settings(self):
        from healthtracker.infrastructure.sqlite.settings import SettingsRepository
        return SettingsRepository(self)

    @property
    def definitions(self):
        from healthtracker.infrastructure.sqlite.definitions import DefinitionsRepository
        return DefinitionsRepository(self)


class ExclusiveAccess:
    """Разрешение принадлежит потоку; безопасность подтверждает SQLite, не UI."""
    def __init__(self, database):
        self._database = database
        self._owner = get_ident()
        self._active = True
        self._safe = False
        self._preserve_identity = False
        self._restart_required = False
        self.token = database.capture_token()

    def confirm_safe(self, *, unchanged=False, restart_required=False):
        if not self._active or get_ident() != self._owner:
            raise StorageError("Эксклюзивное разрешение закрыто или принадлежит другому потоку.")
        self._safe = False
        self._preserve_identity = False
        with connect(self._database.path, readonly=True) as connection:
            if not inspect_existing_schema(connection):
                raise StorageRecoveryRequired("Отсутствует проверенная схема базы.")
        self._safe = True
        self._preserve_identity = unchanged is True
        self._restart_required = restart_required is True


class Database:
    def __init__(self, path: Path, *, clock=lambda: datetime.now(UTC)):
        self.path = Path(path).absolute()
        self.clock = clock
        self._lock = RLock()
        # Допуск не удерживается при ожидании SQLite/commit или пользовательского кода.
        self._gate = Condition(RLock())
        self._state = AccessState.NORMAL
        self._exclusive_owner = None
        self._local = local()
        self._active = 0
        self._lock_fd = None
        self._lock_release_failed = False
        self._ready = False
        self._restart_required = False
        self._identity = uuid4().hex
        self._generation = 0

    @property
    def access_status(self):
        with self._gate:
            return AccessStatus(self._state, self._ready, self._active, self._restart_required)

    def _recovery_required(self):
        with self._gate:
            self._state = AccessState.RECOVERY_REQUIRED
            self._ready = False
            self._gate.notify_all()

    def _admit(self):
        with self._gate:
            if self._restart_required:
                raise StorageBusy("Перезапустите приложение перед работой с базой.")
            if self._state is AccessState.RECOVERY_REQUIRED:
                raise StorageRecoveryRequired("Нужна проверка состояния базы.")
            if self._state is AccessState.EXCLUSIVE:
                raise StorageBusy("Выполняется эксклюзивная операция.")
            self._check()
            self._active += 1
            self._local.active = True

    def _depart(self):
        with self._gate:
            self._active -= 1
            self._local.active = False
            self._gate.notify_all()

    @contextmanager
    def exclusive(self, *, cancel=None, _recovery=False):
        """Сериализация запросов; отмена Event проверяется также во время ожидания.

        Порядок: gate (только допуск) → отпустить gate → SQLite lock.
        Condition.wait освобождает gate; ожидающий не держит SQLite lock.
        Закрытие при владельце exclusive отклоняется и не освобождает flock.
        """
        if getattr(self._local, "active", False):
            raise StorageError("Эксклюзивный доступ внутри сессии запрещён.")
        owner = get_ident()
        acquired = False
        entered = False
        lease = None
        previous_state = None
        try:
            with self._gate:
                if self._exclusive_owner == owner:
                    raise StorageError("Вложенный эксклюзивный доступ запрещён.")
                while self._exclusive_owner is not None:
                    if cancel is not None and cancel.is_set():
                        raise StorageBusy("Ожидание отменено.")
                    self._gate.wait(timeout=0.05 if cancel is not None else None)
                if cancel is not None and cancel.is_set():
                    raise StorageBusy("Ожидание отменено.")
                if self._restart_required:
                    raise StorageBusy("Перезапустите приложение перед эксклюзивной операцией.")
                if _recovery:
                    if self._lock_fd is None or self._lock_release_failed:
                        raise StorageRecoveryRequired("Проверка требует удерживаемой блокировки экземпляра.")
                else:
                    if self._state is AccessState.RECOVERY_REQUIRED:
                        raise StorageRecoveryRequired("Нужна проверка состояния базы.")
                    self._check()
                previous_state = self._state
                self._exclusive_owner = owner
                self._state = AccessState.EXCLUSIVE
                acquired = True
                self._gate.notify_all()
                while self._active:
                    if cancel is not None and cancel.is_set():
                        raise StorageBusy("Ожидание отменено.")
                    self._gate.wait(timeout=0.05 if cancel is not None else None)
                if cancel is not None and cancel.is_set():
                    raise StorageBusy("Ожидание отменено.")
                if self._state is AccessState.RECOVERY_REQUIRED:
                    raise StorageRecoveryRequired("Активная сессия обнаружила повреждение.")
            lease = ExclusiveAccess(self)
            entered = True
            yield lease
            if not lease._safe:
                raise StorageRecoveryRequired("Безопасность базы не подтверждена.")
            with self._lock:
                with self._gate:
                    if not lease._preserve_identity or _recovery:
                        self._identity = uuid4().hex
                        self._generation = 0
                    if _recovery:
                        self._ready = True
                    if lease._restart_required:
                        self._restart_required = True
                        self._ready = False
        except BaseException:
            if entered:
                self._recovery_required()
            raise
        finally:
            if lease is not None:
                lease._active = False
            if acquired:
                with self._gate:
                    if self._state is AccessState.EXCLUSIVE:
                        self._state = AccessState.NORMAL if entered else previous_state
                    self._exclusive_owner = None
                    self._gate.notify_all()

    def verify_access(self):
        """Явная проверка Infrastructure; не восстанавливает файлы и не меняет схему."""
        if self._restart_required:
            raise StorageBusy("Перезапустите приложение перед повторной проверкой.")
        with self.exclusive(_recovery=True) as access:
            access.confirm_safe()

    @property
    def restore_marker(self):
        return self.path.with_suffix(self.path.suffix + '.restore-pending')

    def initialize(self):
        with self._gate:
            if self._restart_required:
                raise StorageBusy("Для продолжения перезапустите приложение.")
            if self._state is AccessState.RECOVERY_REQUIRED:
                raise StorageRecoveryRequired("Требуется явная проверка состояния базы.")
            if self._exclusive_owner is not None:
                raise StorageBusy("Выполняется эксклюзивная операция.")
            if self._ready:
                return self
            if self._lock_fd is not None:
                raise StorageRecoveryRequired("Сначала закройте базу и проверьте её состояние.")
            lock_path = self.path.with_suffix(self.path.suffix + ".lock")
            prepare_private_file(lock_path)
            try:
                with storage_errors():
                    self._lock_fd = os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW)
                    try:
                        fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        raise StorageBusy("База уже открыта другим экземпляром.") from None
                if os.path.lexists(self.restore_marker):
                    raise StorageRecoveryRequired("Обнаружено незавершённое восстановление. Исходные файлы сохранены.")
                prepare_private_file(self.path)
                with connect(self.path, readonly=True) as connection:
                    existing = inspect_existing_schema(connection)
                if not existing:
                    with connect(self.path) as connection:
                        initialize_schema(connection, now=as_utc(self.clock()))
                self._identity = uuid4().hex
                self._generation = 0
                self._ready = True
                return self
            except BaseException as error:
                self.close()
                if isinstance(error, StorageRecoveryRequired):
                    self._recovery_required()
                raise

    def _check(self):
        if not self._ready:
            raise StorageError("База не инициализирована или закрыта.")
        if getattr(self._local, "active", False):
            raise StorageError("Вложенные сессии не допускаются.")

    @contextmanager
    def write(self):
        self._admit()
        try:
            with self._lock:
                if not self._ready:
                    raise StorageRecoveryRequired("Работа с базой заблокирована.")
                session = None
                try:
                    with connect(self.path) as connection:
                        with transaction(connection, write=True):
                            session = Session(connection, now=as_utc(self.clock()),
                                              token=SnapshotToken(self._identity, self._generation), writable=True)
                            yield session
                            if session.poisoned:
                                raise StorageRecoveryRequired("Сессия повреждена и будет отменена.")
                        self._generation += 1
                except StorageRecoveryRequired:
                    self._recovery_required()
                    raise
                finally:
                    if session is not None:
                        session.active = False
        finally:
            self._depart()

    @contextmanager
    def read_snapshot(self):
        session = None
        self._admit()
        try:
            with connect(self.path, readonly=True) as connection:
                with transaction(connection):
                    with self._lock:
                        if not self._ready:
                            raise StorageRecoveryRequired("Работа с базой заблокирована.")
                        connection.execute("SELECT count(*) FROM schema_migrations").fetchone()
                        session = Session(connection, now=as_utc(self.clock()),
                                          token=SnapshotToken(self._identity, self._generation), writable=False)
                    yield session
        except StorageRecoveryRequired:
            self._recovery_required()
            raise
        finally:
            if session is not None:
                session.active = False
            self._depart()

    def is_current(self, token: SnapshotToken) -> bool:
        if getattr(self._local, "active", False):
            raise StorageError("Проверяйте актуальность после закрытия снимка.")
        with self._lock:
            return self.access_status.available and token == SnapshotToken(self._identity, self._generation)

    def capture_token(self) -> SnapshotToken:
        """Для рабочего потока: привязка также ошибки чтения к состоянию базы."""
        with self._lock:
            return SnapshotToken(self._identity, self._generation)

    def apply_if_current(self, token, action, *, require_ready=True):
        """Короткое применение без ожидания SQL/замка в GUI.

        None — координатор занят, можно повторить позднее; False — устарело.
        Проверка и action атомарны относительно commit/повторного открытия.
        action не должен читать базу, выполнять расчёты или запускать event loop.
        """
        if not self._lock.acquire(blocking=False):
            return None
        try:
            if ((require_ready and not self.access_status.available)
                    or token != SnapshotToken(self._identity, self._generation)):
                return False
            action()
            return True
        finally:
            self._lock.release()

    def close(self):
        with self._gate:
            if self._active or self._exclusive_owner is not None:
                raise StorageBusy("Нельзя закрыть базу с активными операциями.")
            self._ready = False
            if self._lock_release_failed:
                raise StorageRecoveryRequired("Результат освобождения блокировки не определён.")
            if self._lock_fd is not None:
                try:
                    with storage_errors():
                        os.close(self._lock_fd)
                except BaseException:
                    self._lock_release_failed = True
                    self._state = AccessState.RECOVERY_REQUIRED
                    self._gate.notify_all()
                    raise
                else:
                    self._lock_fd = None
            self._gate.notify_all()

    def __enter__(self):
        return self.initialize()

    def __exit__(self, exc_type, exc, traceback):
        self.close()
