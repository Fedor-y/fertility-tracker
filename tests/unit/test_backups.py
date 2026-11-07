"""Контракт метаданных и последовательная очередь Application без SQLite/Qt."""
from concurrent.futures import CancelledError
from dataclasses import replace
from datetime import UTC, date, datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from threading import Event, get_ident
from types import SimpleNamespace

import pytest

from healthtracker.application.backups import (
    BackupCancelled, BackupError, BackupKind, BackupMetadata, BackupPhase, BackupProgress,
    BackupRequest, BackupService,
)
from healthtracker.application.errors import StorageBusy
from healthtracker.application.storage import SnapshotToken
from healthtracker.infrastructure.sqlite import backup as module
from healthtracker.infrastructure.sqlite.backup import SQLiteBackup, decode_metadata, encode_metadata


def metadata():
    return BackupMetadata('a'*32,datetime(2026,11,6,tzinfo=UTC),date(2026,11,6),
                          SnapshotToken('b'*32,4),1,'c'*64,BackupKind.MANUAL,512,'d'*64)


@pytest.mark.parametrize('kind',list(BackupKind))
def test_metadata_roundtrip_preserves_kind_and_provenance(kind):
    value=replace(metadata(),kind=kind)
    assert decode_metadata(encode_metadata(value))==value


@pytest.mark.parametrize('field,value',[
    ('protected_generation',True),('protected_generation',-1),('source_database_id','unknown'),
    ('schema_version',True),('schema_version',2),('format_version',2),('size_bytes',0),
    ('size_bytes',True),('sha256','x'*64),('migration_checksum','x'*64),
    ('verified',False),('verified',1),('kind','unknown'),('backup_id','../source'),
    ('created_at_utc','2026-11-06T00:00:00'),('archive_date','20261106'),
])
def test_metadata_validation_rejects_bad_types_even_with_recomputed_digest(field,value):
    data=json.loads(encode_metadata(metadata()))
    data[field]=value
    data.pop('metadata_sha256')
    data['metadata_sha256']=hashlib.sha256(json.dumps(data,ensure_ascii=False,allow_nan=False,sort_keys=True).encode()).hexdigest()
    with pytest.raises(BackupError):
        decode_metadata(json.dumps(data).encode())


@pytest.mark.parametrize('payload',[b'',b'[]',b'null',b'{}',b'\xff',b'{"format":1,"format":2}',b'{"verified":NaN}'])
def test_metadata_rejects_absence_duplicate_keys_and_non_json(payload):
    with pytest.raises(BackupError):
        decode_metadata(payload)


def test_metadata_detects_plausible_but_accidentally_changed_generation():
    payload=encode_metadata(metadata()).replace(b'"protected_generation": 4',b'"protected_generation": 5')
    with pytest.raises(BackupError):
        decode_metadata(payload)


@pytest.mark.parametrize('path',[Path('relative'),Path('/tmp/../unsafe')])
def test_request_requires_explicit_absolute_directory(path):
    with pytest.raises(BackupError):
        BackupRequest(path)


def test_queued_operations_are_serialized_outside_calling_thread_and_close_waits(tmp_path):
    entered,release,second=Event(),Event(),Event()
    owners=[]
    class Port:
        def inspect(self, directory):
            return BackupRequest(directory)

        def create(self,request,*,cancel,progress):
            owners.append(get_ident())
            if len(owners)==1:
                entered.set()
                assert release.wait(5)
            else:
                second.set()
            progress(BackupProgress(BackupPhase.COMPLETE))
            return request
    service=BackupService(Port())
    request=BackupRequest(tmp_path)
    try:
        first=service.create(request)
        assert entered.wait(3)
        other=service.create(request)
        assert not second.is_set()
        assert service.busy
        assert not service.begin_close()
        with pytest.raises(StorageBusy):
            service.create(request)
        release.set()
        assert first.result(3)==request
        assert other.result(3)==request
        assert second.is_set()
        assert len(set(owners))==1 and owners[0]!=get_ident()
        assert service.progress.phase is BackupPhase.COMPLETE
        assert service.begin_close()
    finally:
        release.set()
        service.shutdown()


def test_future_cancel_and_event_cancel_do_not_leak_pending_count(tmp_path):
    entered,release=Event(),Event()
    class Port:
        def inspect(self, directory):
            return BackupRequest(directory)

        def create(self,request,*,cancel,progress):
            entered.set()
            assert release.wait(5)
            return request
    service=BackupService(Port())
    request=BackupRequest(tmp_path)
    try:
        first=service.create(request)
        assert entered.wait(3)
        queued=service.create(request)
        assert queued.cancel()
        cancelled=Event()
        cancelled.set()
        other=service.create(request,cancel=cancelled)
        release.set()
        first.result(3)
        with pytest.raises(CancelledError):
            queued.result(3)
        with pytest.raises(BackupCancelled):
            other.result(3)
        assert service.begin_close()
    finally:
        release.set()
        service.shutdown()


def test_close_can_be_resumed_before_shutdown_but_not_after(tmp_path):
    class Port:
        def inspect(self, directory):
            return BackupRequest(directory)

        def create(self,request,**kwargs):
            return request
    service=BackupService(Port())
    assert service.begin_close()
    service.resume()
    assert service.create(BackupRequest(tmp_path)).result(3).directory==tmp_path
    service.shutdown()
    service.resume()
    with pytest.raises(StorageBusy):
        service.create(BackupRequest(tmp_path))


@pytest.mark.parametrize('status',[sqlite3.SQLITE_OK,sqlite3.SQLITE_DONE,sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED])
def test_backup_api_progress_and_busy_status_are_handled(status):
    observed=[]
    def backup(target,*,pages,progress,sleep):
        assert pages>0
        progress(status,2,10)
    SQLiteBackup(None)._copy(SimpleNamespace(backup=backup),object(),observed.append)
    assert observed==[BackupProgress(BackupPhase.COPYING,2,10)]


def test_backup_api_timeout_interrupts_retries_without_claiming_cancellation(monkeypatch):
    times=iter((0,31))
    monkeypatch.setattr(module,'monotonic',lambda:next(times))
    def backup(target,*,pages,progress,sleep):
        progress(sqlite3.SQLITE_BUSY,2,10)
    with pytest.raises(BackupError):
        SQLiteBackup(None)._copy(SimpleNamespace(backup=backup),object(),lambda value:None)
