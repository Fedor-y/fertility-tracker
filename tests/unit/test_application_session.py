import pytest

from healthtracker.application.errors import (
    MigrationBackupRequired, SchemaError, StorageBusy, StorageError, StorageRecoveryRequired,
)
from healthtracker.application.session import ApplicationSession
from healthtracker.application.storage import AccessState, AccessStatus


class FakeStorage:
    def __init__(self, error=None):
        self.access_status = AccessStatus(AccessState.NORMAL, False)
        self.error = error
        self.opens = 0
        self.closes = 0
        self.block_close = False

    def initialize(self):
        self.opens += 1
        if self.error is not None:
            raise self.error("private detail must not reach UI")
        self.access_status = AccessStatus(AccessState.NORMAL, True)

    def close(self):
        self.closes += 1
        if self.block_close:
            raise StorageBusy("private detail")
        self.access_status = AccessStatus(AccessState.NORMAL, False)


@pytest.mark.parametrize("error, text", [
    (MigrationBackupRequired, "защитной копией"),
    (SchemaError, "несовместима"),
    (StorageRecoveryRequired, "целостность"),
    (StorageBusy, "другим экземпляром"),
    (StorageError, "доступ к каталогу"),
])
def test_open_failure_is_safe_and_never_retries_with_an_empty_database(error, text):
    storage = FakeStorage(error)
    application = ApplicationSession(storage)
    assert not application.open()
    assert not application.storage_available
    assert text in application.error_message
    assert "private" not in application.error_message
    assert storage.opens == 1


def test_open_is_idempotent_and_failed_close_does_not_claim_success():
    storage = FakeStorage()
    application = ApplicationSession(storage)
    assert application.open() and application.open()
    assert storage.opens == 1
    storage.block_close = True
    assert not application.close()
    assert application.storage_available
    assert "отменено" in application.error_message
    storage.block_close = False
    assert application.close()
    assert not application.storage_available


def test_legacy_infrastructure_errors_are_the_same_contract_classes():
    from healthtracker.infrastructure.sqlite import errors
    assert errors.StorageError is StorageError
    assert errors.SchemaError is SchemaError


@pytest.mark.parametrize("state", [AccessState.EXCLUSIVE, AccessState.RECOVERY_REQUIRED])
def test_storage_state_is_the_only_source_and_open_cannot_clear_it(state):
    storage = FakeStorage()
    app = ApplicationSession(storage)
    assert app.open()
    storage.access_status = AccessStatus(state, True)
    assert not app.storage_available
    assert app.error_message
    assert not app.open()
    assert storage.opens == 1
    storage.access_status = AccessStatus(AccessState.NORMAL, True)
    assert app.storage_available
    assert not app.error_message
