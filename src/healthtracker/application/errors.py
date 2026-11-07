"""Общие ошибки порта хранения: Application не зависит от адаптера SQLite."""


class StorageError(RuntimeError):
    pass


class ConstraintViolation(StorageError):
    pass


class StorageBusy(StorageError):
    pass


class SchemaError(StorageError):
    pass


class StorageRecoveryRequired(StorageError):
    """Нужна проверка состояния до продолжения записи."""


class MigrationBackupRequired(SchemaError):
    pass


class RecordNotFound(StorageError):
    pass


class ConfirmationRequired(StorageError):
    """Операция требует явного подтверждения пользователя."""


class MealDuplicateConfirmationRequired(ConfirmationRequired):
    """Подтверждение повтора с ID существующих записей для открытия."""

    def __init__(self, record_ids):
        super().__init__("Категория уже использована за эту дату. Подтвердите сохранение.")
        self.record_ids = tuple(record_ids)
