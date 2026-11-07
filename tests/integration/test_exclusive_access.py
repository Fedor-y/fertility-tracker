"""Координация допуска: только временные базы и управляемые события."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event, get_ident
import os
import subprocess
import sys

import pytest

from healthtracker.application.session import ApplicationSession
from healthtracker.application.storage import AccessState
from healthtracker.application.errors import StorageBusy, StorageError, StorageRecoveryRequired
from healthtracker.infrastructure.sqlite.database import Database


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / 'database.sqlite3').initialize()
    yield database
    database.close()


def waiting(db):
    with db._gate:
        assert db._gate.wait_for(lambda: db.access_status.state is AccessState.EXCLUSIVE, timeout=3)


def exclusive(db, entered=None, release=None, cancel=None):
    with db.exclusive(cancel=cancel) as access:
        assert db.access_status.active_sessions == 0
        if entered:
            entered.set()
        if release:
            assert release.wait(3)
        access.confirm_safe()


@pytest.mark.parametrize('write', [False, True])
def test_active_session_drains_without_deadlock_and_new_sessions_rejected(db, write):
    entered, release, active = Event(), Event(), Event()
    def session():
        with (db.write() if write else db.read_snapshot()):
            active.set()
            assert release.wait(3)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(session)
        assert active.wait(3)
        second = pool.submit(exclusive, db, entered)
        waiting(db)
        assert not entered.is_set()
        for create in (db.read_snapshot, db.write):
            with pytest.raises(StorageBusy):
                with create():
                    pytest.fail('new session admitted')
        with pytest.raises(StorageBusy):
            db.close()
        release.set()
        first.result(3)
        second.result(3)
    assert entered.is_set()
    assert db.access_status.available


def test_multiple_readers_all_finish_before_exclusive(db):
    release = Event()
    entered = [Event(), Event()]
    def read(event):
        with db.read_snapshot():
            event.set()
            assert release.wait(3)
    with ThreadPoolExecutor(3) as pool:
        readers = [pool.submit(read, event) for event in entered]
        assert all(event.wait(3) for event in entered)
        task = pool.submit(exclusive, db)
        waiting(db)
        assert db.access_status.active_sessions == 2
        release.set()
        for reader in readers:
            reader.result(3)
        task.result(3)


def test_exclusive_requests_are_serialized(db):
    entered, release, second = Event(), Event(), Event()
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(exclusive, db, entered, release)
        assert entered.wait(3)
        other = pool.submit(exclusive, db, second)
        assert not second.is_set()
        release.set()
        first.result(3)
        other.result(3)
    assert second.is_set()


@pytest.mark.parametrize('during_operation', [False, True])
def test_cancel_wait_preserves_database(db, during_operation):
    cancel, entered, release = Event(), Event(), Event()
    with ThreadPoolExecutor(2) as pool:
        if during_operation:
            holder = pool.submit(exclusive, db, entered, release)
        else:
            def read():
                with db.read_snapshot():
                    entered.set()
                    assert release.wait(3)
            holder = pool.submit(read)
        assert entered.wait(3)
        task = pool.submit(exclusive, db, cancel=cancel)
        if not during_operation:
            waiting(db)
        cancel.set()
        with pytest.raises(StorageBusy):
            task.result(3)
        release.set()
        holder.result(3)
    assert db.access_status.available


@pytest.mark.parametrize('failure', ['exception', 'unconfirmed', 'critical'])
def test_failed_exclusive_requires_explicit_database_validation(db, failure):
    before = db.path.read_bytes()
    with pytest.raises((RuntimeError, StorageRecoveryRequired)):
        with db.exclusive() as access:
            if failure == 'exception':
                raise RuntimeError('injected')
            if failure == 'critical':
                access.confirm_safe()
                raise StorageRecoveryRequired('injected')
    assert db.path.read_bytes() == before
    assert db.access_status.state is AccessState.RECOVERY_REQUIRED
    for create in (db.read_snapshot, db.write):
        with pytest.raises(StorageRecoveryRequired):
            with create():
                pass
    with pytest.raises(StorageRecoveryRequired):
        db.initialize()
    db.verify_access()
    assert db.access_status.available


@pytest.mark.parametrize('write', [False, True])
def test_critical_session_updates_application_and_rejects_writes(db, write):
    app = ApplicationSession(db)
    assert app.open()
    token = db.capture_token()
    with pytest.raises(StorageRecoveryRequired):
        with (db.write() if write else db.read_snapshot()):
            raise StorageRecoveryRequired('injected private detail')
    assert not app.storage_available
    assert 'private' not in app.error_message
    assert not db.is_current(token)
    with pytest.raises(StorageRecoveryRequired):
        with db.write():
            pass
    db.verify_access()
    assert app.storage_available
    assert not app.error_message
    assert not db.is_current(token)


def test_application_tracks_exclusive_and_close_without_cached_availability(db):
    app = ApplicationSession(db)
    assert app.open()
    with db.exclusive() as access:
        assert not app.storage_available
        assert 'приостановлена' in app.error_message
        assert not app.close()
        access.confirm_safe()
    assert app.storage_available
    assert not app.error_message
    assert app.close()
    assert not app.storage_available


def test_closed_database_rejects_exclusive_and_reopens_normally(db):
    db.close()
    with pytest.raises(StorageError):
        exclusive(db)
    db.initialize()
    exclusive(db)


def test_flock_retained_without_connections_during_exclusive(db):
    code = '''
import sys
from pathlib import Path
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.application.errors import StorageBusy
try:
    Database(Path(sys.argv[1])).initialize()
except StorageBusy:
    sys.exit(0)
sys.exit(1)
'''
    with db.exclusive() as access:
        result = subprocess.run([sys.executable, '-c', code, str(db.path)], timeout=5, capture_output=True)
        assert result.returncode == 0, result.stderr
        access.confirm_safe()


def test_connection_lifecycle_stays_on_owner_thread(db, monkeypatch):
    import healthtracker.infrastructure.sqlite.database as module
    original = module.connect
    calls = []
    @contextmanager
    def traced(*args, **kwargs):
        owner = get_ident()
        with original(*args, **kwargs) as connection:
            calls.append(('open', owner))
            yield connection
        assert get_ident() == owner
        calls.append(('close', owner))
    monkeypatch.setattr(module, 'connect', traced)
    def work():
        with db.write():
            pass
        with db.read_snapshot():
            pass
        exclusive(db)
    with ThreadPoolExecutor(1) as pool:
        pool.submit(work).result(3)
    assert len(calls) == 6
    assert len({owner for _, owner in calls}) == 1
    assert calls[0][1] != get_ident()
    assert [kind for kind, _ in calls] == ['open', 'close'] * 3


def test_release_flock_failure_blocks_access_and_does_not_claim_closed(db, monkeypatch):
    import healthtracker.infrastructure.sqlite.database as module
    original = os.close
    fd = db._lock_fd
    def fail(value):
        if value == fd:
            raise OSError('injected')
        original(value)
    with monkeypatch.context() as patch:
        patch.setattr(module.os, 'close', fail)
        with pytest.raises(StorageError):
            db.close()
        assert db.access_status.state is AccessState.RECOVERY_REQUIRED
        assert db._lock_fd == fd
        with pytest.raises(StorageBusy):
            Database(db.path).initialize()
        with pytest.raises(StorageRecoveryRequired):
            db.verify_access()
        with pytest.raises(StorageRecoveryRequired):
            db.close()
    # Внедрённый отказ точно не закрывал fd; очистка только искусственного ресурса.
    original(fd)
    db._lock_fd = None
    db._lock_release_failed = False


def test_nested_and_expired_exclusive_permissions_rejected(db):
    with db.read_snapshot():
        with pytest.raises(StorageError):
            exclusive(db)
    with db.exclusive() as access:
        with pytest.raises(StorageError):
            exclusive(db)
        access.confirm_safe()
    with pytest.raises(StorageError):
        access.confirm_safe()


def test_critical_reader_during_drain_cannot_return_normal(db):
    active, release = Event(), Event()
    def read():
        with db.read_snapshot():
            active.set()
            assert release.wait(3)
            raise StorageRecoveryRequired('injected')
    with ThreadPoolExecutor(2) as pool:
        reader = pool.submit(read)
        assert active.wait(3)
        task = pool.submit(exclusive, db)
        waiting(db)
        release.set()
        with pytest.raises(StorageRecoveryRequired):
            reader.result(3)
        with pytest.raises(StorageRecoveryRequired):
            task.result(3)
    assert db.access_status.state is AccessState.RECOVERY_REQUIRED


def test_critical_write_rolls_back_data_and_generation(db):
    before = db.path.read_bytes()
    token = db.capture_token()
    with pytest.raises(StorageRecoveryRequired):
        with db.write() as session:
            session.connection.execute("INSERT INTO application_settings VALUES('test','1','2026-11-06T00:00:00.000000Z')")
            raise StorageRecoveryRequired('injected')
    assert db.path.read_bytes() == before
    assert db.capture_token() == token
    db.verify_access()
    with db.read_snapshot() as session:
        assert session.connection.execute('SELECT count(*) FROM application_settings').fetchone()[0] == 0


def test_explicit_validation_does_not_unlock_invalid_schema(db):
    import sqlite3
    with pytest.raises(RuntimeError):
        with db.exclusive():
            raise RuntimeError('injected')
    connection = sqlite3.connect(db.path)
    connection.execute('UPDATE schema_migrations SET version=99')
    connection.commit()
    connection.close()
    with pytest.raises(StorageError):
        db.verify_access()
    assert db.access_status.state is AccessState.RECOVERY_REQUIRED


def test_permission_cannot_be_confirmed_from_another_thread(db):
    with db.exclusive() as access:
        with ThreadPoolExecutor(1) as pool:
            with pytest.raises(StorageError):
                pool.submit(access.confirm_safe).result(3)
        access.confirm_safe()


def test_initial_corruption_is_reported_as_recovery_required(tmp_path):
    path = tmp_path / 'damaged.sqlite3'
    path.write_bytes(b'not a sqlite database')
    path.chmod(0o600)
    db = Database(path)
    app = ApplicationSession(db)
    assert not app.open()
    assert db.access_status.state is AccessState.RECOVERY_REQUIRED
    assert not app.storage_available
    assert path.read_bytes() == b'not a sqlite database'
    assert app.close()
