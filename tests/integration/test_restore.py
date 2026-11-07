"""Базовое восстановление; искусственные базы, сохранённый исходник и явный restart."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
import hashlib
import sqlite3
from threading import Event

import pytest

from healthtracker.application.backups import BackupKind, BackupRequest
from healthtracker.application.errors import StorageBusy, StorageRecoveryRequired
from healthtracker.application.restoration import RestoreError, RestoreRequest
from healthtracker.application.session import ApplicationSession
from healthtracker.domain.answers import CognitiveAnswer
from healthtracker.domain.catalogs import MealCategory, SymptomStatus
from healthtracker.domain.cognitive import CognitiveAssessment
from healthtracker.domain.intervals import CognitiveInterval, SleepInterval
from healthtracker.domain.measurement import CognitiveMeasurement
from healthtracker.domain.records import GymRecord, MealItem, MealRecord, MoodRecord, PhysicalRecord, SleepRecord, StressRecord
from healthtracker.infrastructure.sqlite.backup import SQLiteBackup, encode_metadata, inspect_backup
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.infrastructure.sqlite.restore import SQLiteRestore

NOW=datetime(2026,11,4,12,tzinfo=UTC)
META=dict(created_at=NOW,updated_at=NOW)


@pytest.fixture
def system(tmp_path):
    db=Database(tmp_path/'source.sqlite3',clock=lambda:NOW)
    backup=SQLiteBackup(db)
    restore=SQLiteRestore(db)
    app=ApplicationSession(db,backup_port=backup,restore_port=restore)
    assert app.open()
    yield db,backup,restore,app,tmp_path/'backups'
    app.shutdown_backups()
    app.close()


def save(system):
    db,_,_,app,root=system
    return app.backups.create(BackupRequest(root)).result(5)


def restore(system,selected):
    return system[3].backups.restore(RestoreRequest(selected,system[4])).result(5)


def values():
    return dict(cognitive=CognitiveMeasurement(CognitiveAssessment(*(CognitiveAnswer.numeric(7) for _ in range(3))),
                            CognitiveInterval(NOW,now=NOW),NOW,NOW),
                physical=PhysicalRecord(observed_at=NOW,score=4,symptom_status=SymptomStatus.UNKNOWN,**META),
                stress=StressRecord(observed_at=NOW,score=0,**META),
                mood=MoodRecord(observed_at=NOW,score=3,**META),
                sleep=SleepRecord(interval=SleepInterval(NOW-timedelta(hours=8),NOW,now=NOW),**META),
                meals=MealRecord(entry_date=date(2026,11,3),category=MealCategory.OTHER,
                                 items=(MealItem(name='Искусственная еда',**META),),**META),
                gym=GymRecord(entry_date=date(2026,11,3),attended=False,**META))


def test_all_seven_settings_safety_copy_and_reopen(system):
    db,_,_,app,root=system
    records=values()
    with db.write() as session:
        ids={kind:getattr(session,kind).create(value) for kind,value in records.items()}
        session.settings.set('compact_mode',False)
    selected=save(system)
    with db.write() as session:
        for kind,identifier in ids.items():
            getattr(session,kind).delete(identifier)
        session.settings.set('compact_mode',True)
    previous=db.capture_token()
    result=restore(system,selected)
    assert result.safety.metadata.kind is BackupKind.PRE_RESTORE
    assert result.safety.metadata.source==previous
    assert inspect_backup(result.safety.directory)==result.safety
    assert inspect_backup(selected.directory)==selected
    assert app.restart_required and not app.storage_available
    assert db.capture_token().database_id!=previous.database_id
    assert not db.is_current(previous)
    with pytest.raises(StorageBusy):
        with db.write():
            pass
    with pytest.raises(StorageBusy):
        db.verify_access()
    with pytest.raises(StorageBusy):
        db.initialize()
    assert not db.restore_marker.exists()
    assert list(db.path.parent.glob('.restore-*/original.sqlite3'))
    assert app.close()
    with Database(result.safety.database_path,clock=lambda:NOW) as safety:
        with safety.read_snapshot() as session:
            assert session.settings.get('compact_mode') is True
            assert session.mood.all()==()
    reopened=Database(db.path,clock=lambda:NOW)
    restarted=ApplicationSession(reopened)
    assert restarted.open()
    try:
        with reopened.read_snapshot() as session:
            for kind,value in records.items():
                assert getattr(session,kind).get(ids[kind]).value==value
            assert session.settings.get('compact_mode') is False
            assert session.connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert session.connection.execute('PRAGMA foreign_key_check').fetchall()==[]
    finally:
        restarted.close()


@pytest.mark.parametrize('damage',['corrupt','future','foreign_key'])
def test_invalid_copy_is_rejected_before_current_backup_or_replacement(system,damage):
    db,_,_,app,root=system
    selected=save(system)
    before=db.path.read_bytes()
    if damage=='corrupt':
        selected.database_path.write_bytes(b'not sqlite')
    else:
        connection=sqlite3.connect(selected.database_path)
        if damage=='future':
            connection.execute('UPDATE schema_migrations SET version=99')
        else:
            connection.execute("INSERT INTO meal_items(meal_id,position,name,created_at_utc,updated_at_utc) VALUES(999999,0,'test','2026-11-04T12:00:00.000000Z','2026-11-04T12:00:00.000000Z')")
        connection.commit()
        connection.close()
        # Даже когда checksum файла обновлён, несовместимая схема/FK не принимаются.
        metadata=replace(selected.metadata,size_bytes=selected.database_path.stat().st_size,
                         sha256=hashlib.sha256(selected.database_path.read_bytes()).hexdigest())
        (selected.directory/'metadata.json').write_bytes(encode_metadata(metadata))
        selected=replace(selected,metadata=metadata)
    with pytest.raises(RestoreError):
        restore(system,selected)
    assert db.path.read_bytes()==before
    assert db.access_status.available
    assert not db.restore_marker.exists()
    assert len(list(root.iterdir()))==1


def test_safety_backup_failure_prevents_replace(system,monkeypatch):
    db,backup,installer,app,root=system
    selected=save(system)
    before=db.path.read_bytes()
    def fail(*args,**kwargs):
        raise OSError('synthetic target failure')
    monkeypatch.setattr(backup,'_copy',fail)
    monkeypatch.setattr(installer,'_replace',lambda *args:pytest.fail('must not replace'))
    with pytest.raises(RestoreError):
        restore(system,selected)
    assert db.path.read_bytes()==before
    assert db.access_status.available
    assert not db.restore_marker.exists()
    assert len(list(root.iterdir()))==1


def test_commit_after_safety_copy_aborts_instead_of_losing_unprotected_change(system,monkeypatch):
    db,_,installer,_,root=system
    selected=save(system)
    original=installer.install
    def intervening(prepared,safety):
        with db.write() as session:
            session.mood.create(MoodRecord(observed_at=NOW,score=10,**META))
        return original(prepared,safety)
    monkeypatch.setattr(installer,'install',intervening)
    with pytest.raises(RestoreError):
        restore(system,selected)
    assert db.access_status.available
    with db.read_snapshot() as session:
        assert session.mood.all()[0].value.score==10
    assert not db.restore_marker.exists()
    assert len(list(root.iterdir()))==2


@pytest.mark.parametrize('write',[False,True])
def test_active_session_finishes_and_no_connections_or_lock_gap_during_replace(system,monkeypatch,write):
    db,_,installer,app,_=system
    selected=save(system)
    active,release=Event(),Event()
    original=installer._replace
    replacements=[]
    def checked(*args):
        assert db.access_status.active_sessions==0
        assert not db.path.exists()  # Исходник уже отдельно, flock всё ещё удерживается.
        with pytest.raises(StorageBusy):
            Database(db.path).initialize()
        assert not db.path.exists()  # Второй экземпляр не создал пустую базу.
        replacements.append(True)
        return original(*args)
    monkeypatch.setattr(installer,'_replace',checked)
    def hold():
        with (db.write() if write else db.read_snapshot()) as session:
            if write:
                session.mood.create(MoodRecord(observed_at=NOW,score=6,**META))
            active.set()
            assert release.wait(5)
    with ThreadPoolExecutor(1) as pool:
        holder=pool.submit(hold)
        assert active.wait(3)
        future=app.backups.restore(RestoreRequest(selected,system[4]))
        try:
            with db._gate:
                assert db._gate.wait_for(lambda:db._exclusive_owner is not None,timeout=3)
            assert not app.close()
        finally:
            release.set()
        holder.result(3)
        result=future.result(5)
    assert replacements==[True]
    with Database(result.safety.database_path,clock=lambda:NOW) as saved:
        with saved.read_snapshot() as session:
            assert len(session.mood.all())==int(write)


@pytest.mark.parametrize('when',['replace','validation'])
def test_failed_replace_or_final_check_rolls_back_and_preserves_safety(system,monkeypatch,when):
    db,_,installer,app,root=system
    selected=save(system)
    with db.write() as session:
        session.settings.set('compact_mode',True)
    original=installer._replace
    def fail(*args):
        if when=='validation':
            original(*args)
            with db.path.open('r+b') as file:
                file.write(b'NOT A SQLITE DB!')
        else:
            raise OSError('synthetic replace failure')
    monkeypatch.setattr(installer,'_replace',fail)
    with pytest.raises(RestoreError):
        restore(system,selected)
    assert app.restart_required
    assert not db.restore_marker.exists()
    assert len(list(root.iterdir()))==2
    assert app.close()
    with Database(db.path) as reopened:
        with reopened.read_snapshot() as session:
            assert session.settings.get('compact_mode') is True
    assert inspect_backup(selected.directory)==selected


def test_old_wal_shm_files_are_saved_away_from_replacement(system):
    db,_,_,app,_=system
    selected=save(system)
    # Искусственные остаточные файлы при DELETE-mode: они не принадлежат кандидату.
    for suffix in ('-wal','-shm'):
        path=db.path.with_name(db.path.name+suffix)
        path.write_bytes(b'old auxiliary file')
        path.chmod(0o600)
    restore(system,selected)
    workspaces=list(db.path.parent.glob('.restore-*'))
    assert len(workspaces)==1
    for suffix in ('-wal','-shm'):
        assert (workspaces[0]/('original.sqlite3'+suffix)).is_file()
        # SQLite вправе обновить служебные байты до закрытия проверочных соединений.
        assert not db.path.with_name(db.path.name+suffix).exists()
    assert app.close()
    with Database(db.path):
        pass


def test_interrupted_replacement_marker_prevents_empty_database_on_next_open(system,monkeypatch):
    db,_,installer,app,_=system
    selected=save(system)
    def interrupt(*args):
        raise SystemExit('synthetic worker interruption')
    monkeypatch.setattr(installer,'_replace',interrupt)
    future=app.backups.restore(RestoreRequest(selected,system[4]))
    with pytest.raises(SystemExit):
        future.result(5)
    assert db.restore_marker.exists()
    assert not db.path.exists()
    assert list(db.path.parent.glob('.restore-*/original.sqlite3'))
    assert app.close()
    with pytest.raises(StorageRecoveryRequired):
        Database(db.path).initialize()
    assert not db.path.exists()


def test_restore_from_wal_mode_source_preserves_current_data_in_protective_copy(system):
    db,_,_,app,_=system
    selected=save(system)
    connection=sqlite3.connect(db.path)
    assert connection.execute('PRAGMA journal_mode=WAL').fetchone()[0]=='wal'
    connection.close()
    with db.write() as session:
        session.mood.create(MoodRecord(observed_at=NOW,score=8,**META))
    result=restore(system,selected)
    assert app.close()
    with Database(result.safety.database_path,clock=lambda:NOW) as protection:
        with protection.read_snapshot() as session:
            assert session.mood.all()[0].value.score==8
    with Database(db.path) as current:
        with current.read_snapshot() as session:
            assert session.mood.all()==()


def test_final_directory_fsync_failure_reinstates_guard_before_rollback(system,monkeypatch):
    import os
    import healthtracker.infrastructure.sqlite.restore as module
    db,_,_,app,_=system
    selected=save(system)
    with db.write() as session:
        session.settings.set('compact_mode',True)
    original=os.fsync
    failed=False
    def fail_once(fd):
        nonlocal failed
        info=os.fstat(fd)
        parent=db.path.parent.stat()
        if (not failed and (info.st_dev,info.st_ino)==(parent.st_dev,parent.st_ino)
                and not db.restore_marker.exists() and db.path.exists()
                and list(db.path.parent.glob('.restore-*/original.sqlite3'))):
            failed=True
            raise OSError('synthetic final fsync failure')
        return original(fd)
    monkeypatch.setattr(module.os,'fsync',fail_once)
    with pytest.raises(RestoreError):
        restore(system,selected)
    assert failed and app.restart_required
    assert not db.restore_marker.exists()  # Удалён только после проверенного отката.
    assert app.close()
    with Database(db.path) as reopened:
        with reopened.read_snapshot() as session:
            assert session.settings.get('compact_mode') is True
