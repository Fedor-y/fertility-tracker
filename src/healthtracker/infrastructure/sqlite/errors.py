"""Совместимые импорты ошибок порта. Не включают SQL и личные значения."""

from healthtracker.application.errors import (
    ConfirmationRequired, ConstraintViolation, MigrationBackupRequired,
    RecordNotFound, SchemaError, StorageBusy, StorageError, StorageRecoveryRequired,
)

__all__ = [
    "ConfirmationRequired", "ConstraintViolation", "MigrationBackupRequired",
    "RecordNotFound", "SchemaError", "StorageBusy", "StorageError", "StorageRecoveryRequired",
]
