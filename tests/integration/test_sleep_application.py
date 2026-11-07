"""Сценарии Application поверх существующей SQLite-схемы сна."""
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from healthtracker.application.errors import ConfirmationRequired, RecordNotFound, StorageError
from healthtracker.application.observations import Observations
from healthtracker.domain.errors import DomainValidationError
from healthtracker.infrastructure.sqlite.database import Database

BASE = datetime(2026, 11, 1, tzinfo=UTC)


@pytest.fixture
def service(db):
    return Observations(db, clock=db.clock)


def test_sleep_create_edit_metadata_and_precision(service):
    start = BASE.replace(microsecond=123456)
    end = start + timedelta(hours=7)
    record_id = service.save_sleep(start=start, end=end)
    original = service.get('sleep', record_id).value
    assert original.interval.duration == timedelta(hours=7)
    assert original.created_at > end
    assert service.save_sleep(start=start, end=end, record_id=record_id) == record_id
    edited = service.get('sleep', record_id).value
    assert edited.created_at == original.created_at
    assert edited.interval.start == start and edited.interval.end == end
    assert edited.updated_at >= original.updated_at


@pytest.mark.parametrize('start,end', [(1,7),(-1,4),(6,10),(-1,10),(0,8)])
def test_sleep_rejects_each_overlap_without_touching_old(service, start, end):
    record_id = service.save_sleep(start=BASE, end=BASE+timedelta(hours=8))
    original = service.get('sleep',record_id)
    with pytest.raises(DomainValidationError, match='пересек'):
        service.save_sleep(start=BASE+timedelta(hours=start),end=BASE+timedelta(hours=end))
    assert service.get('sleep',record_id) == original
    with service.storage.read_snapshot() as s:
        assert len(s.sleep.all()) == 1


def test_sleep_touching_multiple_dates_and_edit_exclusion(service):
    first = service.save_sleep(start=BASE, end=BASE+timedelta(hours=4))
    second = service.save_sleep(start=BASE+timedelta(hours=4),end=BASE+timedelta(hours=8))
    third = service.save_sleep(start=BASE+timedelta(days=1),end=BASE+timedelta(days=1,hours=8))
    service.save_sleep(start=BASE, end=BASE+timedelta(hours=4), record_id=first)
    unchanged = service.get('sleep',first)
    with pytest.raises(DomainValidationError):
        service.save_sleep(start=BASE,end=BASE+timedelta(hours=5),record_id=first)
    assert service.get('sleep',first) == unchanged
    with service.storage.read_snapshot() as s:
        records=s.sleep.all()
        assert [r.id for r in records] == [first,second,third]
        assert records[0].value.interval.date_in(ZoneInfo('UTC')) == records[1].value.interval.date_in(ZoneInfo('UTC'))


@pytest.mark.parametrize('hours,confirmation', [(15,False),(16,False),(17,False),(17,True)])
def test_sleep_application_requires_long_confirmation(service,hours,confirmation):
    if hours>16 and not confirmation:
        with pytest.raises(ConfirmationRequired):
            service.save_sleep(start=BASE,end=BASE+timedelta(hours=hours))
        with service.storage.read_snapshot() as s:
            assert not s.sleep.all()
    else:
        service.save_sleep(start=BASE,end=BASE+timedelta(hours=hours),long_sleep_confirmed=confirmation)


@pytest.mark.parametrize('start,end', [(BASE,BASE),(BASE+timedelta(hours=1),BASE),(BASE,datetime(2030,1,1,tzinfo=UTC))])
def test_sleep_invalid_interval_rejected(service,start,end):
    with pytest.raises(DomainValidationError):
        service.save_sleep(start=start,end=end)


def test_sleep_unknown_id_does_not_create(service):
    with pytest.raises(RecordNotFound):
        service.save_sleep(start=BASE,end=BASE+timedelta(hours=7),record_id=999)
    with service.storage.read_snapshot() as s:
        assert not s.sleep.all()


def test_sleep_rollback_after_write_and_reopen(service,monkeypatch):
    record_id=service.save_sleep(start=BASE,end=BASE+timedelta(hours=8))
    original=service.get('sleep',record_id)
    write=service.storage.write
    @contextmanager
    def fail():
        with write() as s:
            yield s
            raise StorageError('failure before commit')
    monkeypatch.setattr(service.storage,'write',fail)
    with pytest.raises(StorageError):
        service.save_sleep(start=BASE,end=BASE+timedelta(hours=17),record_id=record_id,long_sleep_confirmed=True)
    assert service.get('sleep',record_id) == original
    path=service.storage.path
    service.storage.close()
    with Database(path,clock=service.clock) as reopened:
        assert Observations(reopened).get('sleep',record_id) == original
