"""Сценарии открытия/закрытия хранилища без Qt и конкретного SQLite-адаптера."""

from healthtracker.application.errors import (
    MigrationBackupRequired, SchemaError, StorageBusy, StorageError,
    StorageRecoveryRequired,
)
from healthtracker.application.storage import AccessState, Storage
from healthtracker.application.backups import BackupPort, BackupService
from healthtracker.application.restoration import RestorePort
from healthtracker.application.observations import Observations
from healthtracker.application.diary import Diary
from healthtracker.application.analytics import Analytics
from healthtracker.application.chart_preferences import ChartPreferencesService


class ApplicationSession:
    def __init__(self, storage: Storage, *, backup_port: BackupPort | None = None, restore_port: RestorePort | None = None):
        self._storage = storage
        self.backups = BackupService(backup_port, restore_port) if backup_port is not None else None
        self.observations = Observations(storage)
        self.diary = Diary(storage)
        self.analytics = Analytics(storage)
        self.chart_preferences = ChartPreferencesService(storage)
        self._error_message = ""

    @property
    def storage_available(self):
        return self._storage.access_status.available and not (self.backups is not None and self.backups.restoring)

    @property
    def restart_required(self):
        return self._storage.access_status.restart_required

    @property
    def recovery_required(self):
        return self._storage.access_status.state is AccessState.RECOVERY_REQUIRED

    @property
    def error_message(self):
        status = self._storage.access_status
        if status.restart_required:
            return "Требуется перезапуск приложения. Работа с базой приостановлена."
        if self.backups is not None and self.backups.restoring:
            return "Выполняется восстановление. Работа с базой приостановлена."
        if status.state is AccessState.RECOVERY_REQUIRED:
            return "Нужна проверка состояния базы. Запись недоступна."
        if status.state is AccessState.EXCLUSIVE:
            return "Выполняется эксклюзивная операция. Работа с базой приостановлена."
        return self._error_message

    @error_message.setter
    def error_message(self, value):
        self._error_message = value

    def open(self) -> bool:
        if self.storage_available:
            return True
        if self._storage.access_status.state is not AccessState.NORMAL:
            return False
        try:
            self._storage.initialize()
        except MigrationBackupRequired:
            self._error_message = (
                "Для этой базы требуется обновление с защитной копией. "
                "Обновление сейчас недоступно; исходная база сохранена."
            )
        except SchemaError:
            self._error_message = (
                "Схема базы несовместима с приложением или была изменена. "
                "База не заменена; запись недоступна."
            )
        except StorageRecoveryRequired:
            self._error_message = (
                "Не удалось проверить целостность базы. "
                "Исходные файлы сохранены; запись недоступна."
            )
        except StorageBusy:
            self._error_message = "База занята другим экземпляром приложения. Запись недоступна."
        except StorageError:
            self._error_message = (
                "Не удалось открыть локальное хранилище. "
                "Проверьте доступ к каталогу данных."
            )
        else:
            self._error_message = ""
            return True
        return False

    def prepare_close(self) -> bool:
        return self.backups is None or self.backups.begin_close()

    def cancel_close(self):
        if self.backups is not None:
            self.backups.resume()

    def shutdown_backups(self):
        """Вне event loop: дождаться worker без замков SQLite/WebChannel."""
        if self.backups is not None:
            self.backups.shutdown(wait=True)

    def close(self) -> bool:
        if not self.prepare_close():
            return False
        try:
            self._storage.close()
        except StorageError:
            self.cancel_close()
            if self._storage.access_status.state is AccessState.NORMAL:
                self._error_message = "Не удалось завершить работу с базой. Закрытие окна отменено."
            return False
        if self.backups is not None:
            self.backups.shutdown(wait=False)
        return True
