"""Одна копия, включая отказы носителя и гонки. Только искусственные базы."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
import errno
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from threading import Event
from types import SimpleNamespace

import pytest

from healthtracker.application.backups import BackupCancelled, BackupError, BackupKind, BackupPhase, BackupRequest, BackupService
from healthtracker.application.errors import StorageBusy, StorageRecoveryRequired
from healthtracker.application.session import ApplicationSession
from healthtracker.application.storage import AccessState
from healthtracker.domain.answers import AnswerStatus, CognitiveAnswer
from healthtracker.domain.catalogs import MealCategory, SymptomStatus
from healthtracker.domain.cognitive import CognitiveAssessment
from healthtracker.domain.intervals import CognitiveInterval, SleepInterval
from healthtracker.domain.measurement import CognitiveMeasurement
from healthtracker.domain.records import GymRecord, MealItem, MealRecord, MoodRecord, PhysicalRecord, SleepRecord, StressRecord
from healthtracker.infrastructure import backup_files
from healthtracker.infrastructure.sqlite import backup as module
from healthtracker.infrastructure.sqlite.backup import SQLiteBackup, inspect_backup
from healthtracker.infrastructure.sqlite.connections import connect, transaction
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.infrastructure.sqlite.migrations import MIGRATIONS, validate_schema

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)
META = dict(created_at=NOW, updated_at=NOW)


def create(db, root, **kwargs):
    return SQLiteBackup(db, clock=lambda: NOW).create(BackupRequest(root), cancel=Event(), **kwargs)


def archive_bytes(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()}


def wait_exclusive(db):
    with db._gate:
        assert db._gate.wait_for(lambda: db.access_status.state is AccessState.EXCLUSIVE, timeout=3)


def test_empty_copy_is_verified_private_durable_and_source_unchanged(db, tmp_path):
    token, before = db.capture_token(), db.path.read_bytes()
    progress = []
    result = create(db, tmp_path/'backups', progress=progress.append)
    assert db.capture_token() == token == result.metadata.source
    assert db.path.read_bytes() == before
    assert inspect_backup(result.directory) == result
    assert result.metadata.created_at_utc == NOW
    assert result.metadata.archive_date == NOW.astimezone().date()
    assert result.metadata.kind is BackupKind.MANUAL
    assert result.metadata.schema_version == 1
    assert result.metadata.migration_checksum == MIGRATIONS[0].checksum
    assert result.metadata.sha256 == hashlib.sha256(result.database_path.read_bytes()).hexdigest()
    assert result.metadata.size_bytes == result.database_path.stat().st_size
    assert progress[-1].phase is BackupPhase.COMPLETE
    assert any(p.phase is BackupPhase.COPYING and p.total_pages > 0 and p.remaining_pages == 0 for p in progress)
    assert result.directory.stat().st_mode & 0o777 == 0o700
    assert result.directory.parent.stat().st_mode & 0o777 == 0o700
    for file in result.directory.iterdir():
        assert file.stat().st_mode & 0o777 == 0o600
    with connect(result.database_path, readonly=True) as connection:
        validate_schema(connection)
        assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
    assert not list(result.directory.parent.glob('.pending-*'))


def test_all_seven_journals_settings_and_versions_survive_separate_open(db, tmp_path):
    values = dict(
        cognitive=CognitiveMeasurement(CognitiveAssessment(CognitiveAnswer.numeric(0), CognitiveAnswer.numeric(10),
            CognitiveAnswer(AnswerStatus.CANNOT_ASSESS)), CognitiveInterval(NOW, now=NOW), NOW, NOW),
        physical=PhysicalRecord(observed_at=NOW, score=0, symptom_status=SymptomStatus.UNKNOWN, **META),
        stress=StressRecord(observed_at=NOW, score=0, **META),
        mood=MoodRecord(observed_at=NOW, score=0, **META),
        sleep=SleepRecord(interval=SleepInterval(NOW-timedelta(hours=8), NOW, now=NOW), **META),
        meals=MealRecord(entry_date=date(2026,11,3), category=MealCategory.OTHER,
                         items=(MealItem(name='Искусственная еда', **META),), **META),
        gym=GymRecord(entry_date=date(2026,11,3), attended=False, **META))
    with db.write() as session:
        ids = {name: getattr(session,name).create(value) for name,value in values.items()}
        session.settings.set('compact_mode', False)
        session.settings.set('visible_series', [])
    token = db.capture_token()
    result = create(db,tmp_path/'backups')
    with Database(result.database_path, clock=lambda: NOW) as copied:
        with copied.read_snapshot() as session:
            for name,value in values.items():
                assert getattr(session,name).get(ids[name]).value == value
            assert session.settings.get('compact_mode') is False
            assert session.settings.get('visible_series') == []
            assert session.definitions.scale('stress').version == 1
    assert result.metadata.source == token
    assert inspect_backup(result.directory) == result


@pytest.mark.parametrize('write', [False, True])
def test_backup_waits_for_reader_or_writer_and_captures_commit_before_snapshot(db, tmp_path, write):
    active, release = Event(), Event()
    def hold():
        with (db.write() if write else db.read_snapshot()) as session:
            if write:
                session.mood.create(MoodRecord(observed_at=NOW, score=7, **META))
            active.set()
            assert release.wait(5)
    token = db.capture_token()
    service = BackupService(SQLiteBackup(db))
    try:
        with ThreadPoolExecutor(1) as pool:
            first = pool.submit(hold)
            assert active.wait(3)
            future = service.create(BackupRequest(tmp_path/'backups'))
            wait_exclusive(db)
            assert not future.done()
            with pytest.raises(StorageBusy):
                with db.write():
                    pass
            release.set()
            first.result(3)
            result = future.result(5)
        assert result.metadata.source.generation == token.generation + int(write)
        with connect(result.database_path,readonly=True) as connection:
            assert connection.execute('SELECT count(*) FROM mood_entries').fetchone()[0] == int(write)
    finally:
        release.set()
        service.shutdown()


def test_no_commit_during_backup_and_later_commit_not_claimed(db, tmp_path, monkeypatch):
    copying, finish_copy, verifying, finish_verify = (Event() for _ in range(4))
    adapter = SQLiteBackup(db)
    original = adapter._copy
    def copy(source,target,progress):
        copying.set()
        assert finish_copy.wait(5)
        original(source,target,progress)
    monkeypatch.setattr(adapter,'_copy',copy)
    token = db.capture_token()
    def progress(value):
        if value.phase is BackupPhase.VERIFYING:
            verifying.set()
            assert finish_verify.wait(5)
    with ThreadPoolExecutor(1) as pool:
        task = pool.submit(adapter.create, BackupRequest(tmp_path/'backups'), cancel=Event(), progress=progress)
        try:
            assert copying.wait(3)
            for factory in (db.write,db.read_snapshot):
                with pytest.raises(StorageBusy):
                    with factory():
                        pass
            finish_copy.set()
            assert verifying.wait(3)
            with db.write() as session:
                session.mood.create(MoodRecord(observed_at=NOW,score=9,**META))
            finish_verify.set()
            result = task.result(5)
        finally:
            finish_copy.set()
            finish_verify.set()
    assert result.metadata.source == token
    assert db.capture_token().generation == token.generation+1
    with connect(result.database_path,readonly=True) as connection:
        assert connection.execute('SELECT count(*) FROM mood_entries').fetchone()[0] == 0


@pytest.mark.parametrize('failure', ['api', 'enospc', 'permission', 'partial'])
def test_backup_api_failure_preserves_source_and_previous_archive(db,tmp_path,monkeypatch,failure):
    root = tmp_path/'backups'
    create(db,root)
    previous, source, token = archive_bytes(root), db.path.read_bytes(), db.capture_token()
    def fail(self,source_connection,target,progress):
        if failure == 'partial':
            target.execute('CREATE TABLE incomplete(id INTEGER)')
        if failure == 'api':
            raise sqlite3.OperationalError('injected')
        raise OSError(errno.ENOSPC if failure=='enospc' else errno.EACCES,'injected')
    monkeypatch.setattr(SQLiteBackup,'_copy',fail)
    with pytest.raises(BackupError):
        create(db,root)
    assert archive_bytes(root) == previous
    assert sorted(p.name for p in root.iterdir()) == sorted({Path(name).parts[0] for name in previous})
    assert db.path.read_bytes() == source
    assert db.capture_token() == token
    assert db.access_status.available


@pytest.mark.parametrize('nth', [1,2,3,4])
def test_fsync_failure_never_registers_new_copy_or_deletes_previous(db,tmp_path,monkeypatch,nth):
    root=tmp_path/'backups'
    create(db,root)
    previous=archive_bytes(root)
    original=os.fsync
    calls=0
    def fail(fd):
        nonlocal calls
        calls+=1
        if calls==nth:
            raise OSError(errno.ENOSPC,'injected fsync')
        return original(fd)
    monkeypatch.setattr(backup_files.os,'fsync',fail)
    with pytest.raises(BackupError):
        create(db,root)
    assert calls>=nth
    assert archive_bytes(root)==previous
    assert not list(root.glob('.pending-*'))
    assert len(list(root.iterdir()))==1
    assert db.access_status.available


@pytest.mark.parametrize('step', ['write', 'rename', 'file_create', 'metadata_corrupt', 'copy_corrupt', 'file_corrupt'])
def test_publication_failures_cleanup_only_new_files(db,tmp_path,monkeypatch,step):
    root=tmp_path/'backups'
    create(db,root)
    previous=archive_bytes(root)
    def fail(*args,**kwargs):
        raise OSError(errno.EIO,'injected')
    if step=='write':
        monkeypatch.setattr(backup_files.os,'write',fail)
    elif step=='rename':
        monkeypatch.setattr(backup_files,'rename_noreplace',fail)
    elif step=='file_create':
        original=backup_files.private_file
        def bad(directory_fd,name,**kwargs):
            if kwargs.get('create'):
                fail()
            return original(directory_fd,name,**kwargs)
        monkeypatch.setattr(backup_files,'private_file',bad)
    elif step=='file_corrupt':
        original=module.verify_data
        def corrupt_file(directory_fd):
            fd=os.open('database.sqlite3',os.O_WRONLY | os.O_NOFOLLOW,dir_fd=directory_fd)
            try:
                os.write(fd,b'NOT A SQLITE DB!')
            finally:
                os.close(fd)
            return original(directory_fd)
        monkeypatch.setattr(module,'verify_data',corrupt_file)
    elif step=='metadata_corrupt':
        original=backup_files.StagedBackup.write_metadata
        monkeypatch.setattr(backup_files.StagedBackup,'write_metadata',lambda self,payload: original(self,b'{}'))
    else:
        original=SQLiteBackup._copy
        def corrupt(self,source,target,progress):
            original(self,source,target,progress)
            target.execute('DROP INDEX ix_mood_entries_observed_at_utc')
        monkeypatch.setattr(SQLiteBackup,'_copy',corrupt)
    with pytest.raises(BackupError):
        create(db,root)
    assert archive_bytes(root)==previous
    assert len(list(root.iterdir()))==1
    assert db.access_status.available


@pytest.mark.parametrize('existing', ['directory','symlink','file'])
def test_existing_final_name_is_not_overwritten(db,tmp_path,monkeypatch,existing):
    root=tmp_path/'backups'
    root.mkdir(mode=0o700)
    identity='a'*32
    target=root/identity
    if existing=='directory':
        target.mkdir(mode=0o700)
    elif existing=='symlink':
        target.symlink_to(db.path)
    else:
        target.write_bytes(b'keep')
    source=db.path.read_bytes()
    monkeypatch.setattr(module,'uuid4',lambda:SimpleNamespace(hex=identity))
    with pytest.raises(BackupError):
        create(db,root)
    assert list(root.iterdir())==[target]
    assert db.path.read_bytes()==source
    if existing=='file':
        assert target.read_bytes()==b'keep'
    elif existing=='symlink':
        assert target.is_symlink()
    else:
        assert target.is_dir() and not list(target.iterdir())


@pytest.mark.parametrize('damage', ['unknown_version','checksum','index','trigger','corrupt','foreign_key'])
def test_invalid_source_never_produces_copy_and_stays_blocked(db,tmp_path,damage):
    if damage=='corrupt':
        with db.path.open('r+b') as file:
            file.write(b'NOT A SQLITE DB!')
    else:
        connection=sqlite3.connect(db.path)
        if damage=='unknown_version':
            connection.execute('UPDATE schema_migrations SET version=99')
        elif damage=='checksum':
            connection.execute("UPDATE schema_migrations SET checksum=printf('%064d',0)")
        elif damage=='index':
            connection.execute('DROP INDEX ix_mood_entries_observed_at_utc')
        elif damage=='trigger':
            connection.execute('DROP TRIGGER sleep_overlap_insert')
        else:
            connection.execute("INSERT INTO meal_items(meal_id,position,name,created_at_utc,updated_at_utc) VALUES(999999,0,'Искусственное нарушение FK','2026-11-04T12:00:00.000000Z','2026-11-04T12:00:00.000000Z')")
        connection.commit()
        connection.close()
    source=db.path.read_bytes()
    root=tmp_path/'backups'
    with pytest.raises(BackupError):
        create(db,root)
    assert not list(root.iterdir())
    assert db.path.read_bytes()==source
    assert db.access_status.state is AccessState.RECOVERY_REQUIRED


@pytest.mark.parametrize('damage',['missing_metadata','invalid_json','changed_generation','missing_database','bad_checksum','symlink_database','file_mode','directory_mode','hardlink'])
def test_inspection_rejects_incomplete_or_tampered_bundle(db,tmp_path,damage):
    result=create(db,tmp_path/'backups')
    metadata=result.directory/'metadata.json'
    if damage=='missing_metadata':
        metadata.unlink()
    elif damage=='invalid_json':
        metadata.write_bytes(b'[]')
    elif damage=='changed_generation':
        value=json.loads(metadata.read_bytes())
        value['protected_generation']+=1
        metadata.write_text(json.dumps(value))
    elif damage=='missing_database':
        result.database_path.unlink()
    elif damage=='bad_checksum':
        with result.database_path.open('r+b') as file:
            file.write(b'changed')
    elif damage=='symlink_database':
        result.database_path.unlink()
        result.database_path.symlink_to(db.path)
    elif damage=='file_mode':
        metadata.chmod(0o644)
    elif damage=='directory_mode':
        result.directory.chmod(0o755)
    else:
        os.link(metadata,result.directory/'hardlink')
    with pytest.raises(BackupError):
        inspect_backup(result.directory)


@pytest.mark.parametrize('unsafe', ['permissions','symlink','ancestor_symlink'])
def test_unsafe_target_directory_is_rejected(db,tmp_path,unsafe):
    root=tmp_path/'backups'
    if unsafe=='permissions':
        root.mkdir(mode=0o755)
    else:
        actual=tmp_path/'actual'
        actual.mkdir(mode=0o700)
        root.symlink_to(actual,target_is_directory=True)
        if unsafe=='ancestor_symlink':
            root=root/'nested'
    with pytest.raises(BackupError):
        create(db,root)
    assert db.access_status.available


def test_cancel_before_exclusive_waits_cleanup_and_source_stays_normal(db,tmp_path):
    cancel, active, release=Event(),Event(),Event()
    def read():
        with db.read_snapshot():
            active.set()
            assert release.wait(5)
    with ThreadPoolExecutor(2) as pool:
        reader=pool.submit(read)
        assert active.wait(3)
        task=pool.submit(SQLiteBackup(db).create,BackupRequest(tmp_path/'backups'),cancel=cancel)
        try:
            wait_exclusive(db)
            cancel.set()
            with pytest.raises(BackupCancelled):
                task.result(3)
        finally:
            release.set()
        reader.result(3)
    assert db.access_status.available
    assert not list((tmp_path/'backups').iterdir())


@pytest.mark.parametrize('fail', [False, True])
def test_cancel_after_copy_started_does_not_claim_safe_cancellation(db,tmp_path,monkeypatch,fail):
    cancel, entered,release=Event(),Event(),Event()
    adapter=SQLiteBackup(db)
    original=adapter._copy
    def copy(source,target,progress):
        entered.set()
        assert release.wait(5)
        if fail:
            raise OSError(errno.ENOSPC,'injected')
        original(source,target,progress)
    monkeypatch.setattr(adapter,'_copy',copy)
    with ThreadPoolExecutor(1) as pool:
        task=pool.submit(adapter.create,BackupRequest(tmp_path/'backups'),cancel=cancel)
        try:
            assert entered.wait(3)
            cancel.set()
        finally:
            release.set()
        if fail:
            with pytest.raises(BackupError) as error:
                task.result(5)
            assert not isinstance(error.value,BackupCancelled)
        else:
            result=task.result(5)
            assert inspect_backup(result.directory)==result
    assert db.access_status.available


def test_reopen_application_keeps_old_copy_verifiable_and_uses_new_identity(tmp_path):
    path=tmp_path/'source.sqlite3'
    db=Database(path)
    app=ApplicationSession(db,backup_port=SQLiteBackup(db))
    assert app.open()
    first=app.backups.create(BackupRequest(tmp_path/'backups')).result(5)
    assert app.close()
    db=Database(path)
    reopened=ApplicationSession(db,backup_port=SQLiteBackup(db))
    try:
        assert reopened.open()
        assert inspect_backup(first.directory)==first
        second=reopened.backups.create(BackupRequest(tmp_path/'backups')).result(5)
        assert second.metadata.source.database_id!=first.metadata.source.database_id
        assert second.metadata.source==db.capture_token()
    finally:
        reopened.shutdown_backups()
        reopened.close()


def test_backup_connections_are_opened_and_closed_in_worker_thread(db,tmp_path,monkeypatch):
    from contextlib import contextmanager
    from threading import get_ident
    original=module.backup_connection
    lifecycle=[]
    @contextmanager
    def traced(*args,**kwargs):
        thread=get_ident()
        with original(*args,**kwargs) as connection:
            lifecycle.append(('open',thread))
            yield connection
        assert get_ident()==thread
        lifecycle.append(('close',thread))
    monkeypatch.setattr(module,'backup_connection',traced)
    service=BackupService(SQLiteBackup(db))
    try:
        service.create(BackupRequest(tmp_path/'backups')).result(5)
    finally:
        service.shutdown()
    assert lifecycle and len(lifecycle)%2==0
    assert {owner for _,owner in lifecycle}!={get_ident()}
    assert len({owner for _,owner in lifecycle})==1
    assert [action for action,_ in lifecycle]==['open','close']*(len(lifecycle)//2)


def test_application_close_waits_through_verification_after_source_released(db,tmp_path,monkeypatch):
    entered,release=Event(),Event()
    original=module.verify_data
    def verify(fd):
        entered.set()
        assert release.wait(5)
        return original(fd)
    monkeypatch.setattr(module,'verify_data',verify)
    app=ApplicationSession(db,backup_port=SQLiteBackup(db))
    assert app.open()
    task=app.backups.create(BackupRequest(tmp_path/'backups'))
    try:
        assert entered.wait(3)
        assert db.access_status.available
        assert not app.close()
        assert db.access_status.opened
        with pytest.raises(StorageBusy):
            app.backups.create(BackupRequest(tmp_path/'backups'))
        release.set()
        task.result(5)
        assert app.close()
        assert not db.access_status.opened
    finally:
        release.set()
        app.shutdown_backups()


def test_complete_observer_failure_does_not_turn_published_copy_into_failure(db,tmp_path):
    def observer(value):
        if value.phase is BackupPhase.COMPLETE:
            raise RuntimeError('observer failure')
    result=create(db,tmp_path/'backups',progress=observer)
    assert inspect_backup(result.directory)==result


def test_backup_includes_committed_wal_pages_without_file_copy(db,tmp_path):
    keeper=sqlite3.connect(db.path)
    assert keeper.execute('PRAGMA journal_mode=WAL').fetchone()[0]=='wal'
    keeper.execute('BEGIN')
    keeper.execute('SELECT count(*) FROM mood_entries').fetchone()
    try:
        with db.write() as session:
            session.mood.create(MoodRecord(observed_at=NOW,score=8,**META))
        assert Path(str(db.path)+'-wal').stat().st_size>0
        result=create(db,tmp_path/'backups')
        assert inspect_backup(result.directory)==result
        with connect(result.database_path,readonly=True) as connection:
            assert connection.execute('SELECT score FROM mood_entries').fetchone()[0]==8
    finally:
        keeper.close()


def test_failed_cleanup_leaves_only_unpublished_pending_package(db,tmp_path,monkeypatch):
    root=tmp_path/'backups'
    previous=create(db,root)
    before=archive_bytes(root)
    original_unlink=os.unlink
    def fail_copy(*args,**kwargs):
        raise OSError(errno.ENOSPC,'injected')
    def fail_unlink(*args,**kwargs):
        raise OSError(errno.EACCES,'injected cleanup')
    with monkeypatch.context() as patch:
        patch.setattr(SQLiteBackup,'_copy',fail_copy)
        patch.setattr(backup_files.os,'unlink',fail_unlink)
        with pytest.raises(BackupError):
            create(db,root)
    pending=list(root.glob('.pending-*'))
    assert len(pending)==1
    with pytest.raises(BackupError):
        inspect_backup(pending[0])
    assert inspect_backup(previous.directory)==previous
    assert all(archive_bytes(root)[name]==content for name,content in before.items())
    # Очистка искусственного следа отказа: автоматической уборки старых пакетов нет.
    for file in pending[0].iterdir():
        original_unlink(file)
    pending[0].rmdir()


def test_invalid_clock_does_not_mark_valid_source_as_corrupt(db,tmp_path):
    token=db.capture_token()
    with pytest.raises(BackupError):
        SQLiteBackup(db,clock=lambda:NOW.replace(tzinfo=None)).create(BackupRequest(tmp_path/'backups'),cancel=Event())
    assert db.access_status.available
    assert db.capture_token()==token
    assert not list((tmp_path/'backups').iterdir())
