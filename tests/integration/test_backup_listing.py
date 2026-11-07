"""Чтение списка не заменяет проверку файлов и не меняет прежний архив."""
from threading import Event

import pytest

from healthtracker.application.backups import BackupError, BackupRequest, BackupService
from healthtracker.infrastructure.sqlite.backup import SQLiteBackup


def test_listing_uses_inspect_and_ignores_pending_foreign_and_bad_packages(db,tmp_path):
    adapter=SQLiteBackup(db)
    service=BackupService(adapter)
    try:
        first=service.create(BackupRequest(adapter.default_directory)).result(5)
        second=service.create(BackupRequest(adapter.default_directory)).result(5)
        invalid=adapter.default_directory/('c'*32)
        invalid.mkdir(mode=0o700)
        (adapter.default_directory/'.pending-example').mkdir(mode=0o700)
        (adapter.default_directory/'ordinary.txt').write_text('leave alone')
        listing=service.scan(adapter.default_directory).result(5)
        assert listing.copies==(second,first)
        assert listing.unverified_count==1
        assert invalid.is_dir()
        assert (adapter.default_directory/'ordinary.txt').read_text()=='leave alone'
        assert db.access_status.available
    finally:
        service.shutdown()


def test_scan_missing_custom_directory_does_not_create_or_substitute_it(db,tmp_path):
    adapter=SQLiteBackup(db)
    missing=tmp_path/'missing-custom'
    with pytest.raises(BackupError):
        adapter.scan(missing)
    assert not missing.exists()
    assert db.access_status.available


def test_listing_is_available_after_source_closed(db):
    adapter=SQLiteBackup(db)
    result=adapter.create(BackupRequest(adapter.default_directory),cancel=Event())
    db.close()
    assert adapter.scan(adapter.default_directory).copies==(result,)
