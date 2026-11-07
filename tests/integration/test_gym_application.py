from contextlib import contextmanager
from datetime import date, timedelta

import pytest

from healthtracker.application.errors import ConstraintViolation, RecordNotFound, StorageError
from healthtracker.application.observations import Observations
from healthtracker.domain.errors import DomainValidationError
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.infrastructure.sqlite.gym import GymRepository

DAY=date(2026,11,1)


@pytest.fixture
def service(db):
    return Observations(db,clock=db.clock)


@pytest.mark.parametrize('score',range(11))
def test_gym_every_score_and_reopen(service,score):
    record_id=service.save_gym(entry_date=DAY,attended=True,difficulty=score)
    old=service.get('gym',record_id)
    assert old.value.difficulty==score and old.value.attended is True
    assert old.value.difficulty_scale_version==1 and old.value.created_at.date()>DAY
    assert not hasattr(old.value,'observed_at')
    path=service.storage.path;service.storage.close()
    with Database(path,clock=service.clock) as reopened:
        assert Observations(reopened).get('gym',record_id)==old


def test_gym_absent_row_explicit_no_and_unknown_score(service):
    with service.storage.read_snapshot() as s:
        assert not s.gym.all()
    with pytest.raises(DomainValidationError):
        service.save_gym(entry_date=DAY,attended=True,difficulty=None)
    with service.storage.read_snapshot() as s:
        assert not s.gym.all() # no unknown-to-zero conversion
    record_id=service.save_gym(entry_date=DAY,attended=False)
    value=service.get('gym',record_id).value
    assert value.attended is False and value.difficulty is None and value.difficulty_scale_version is None


def test_gym_application_uniqueness_before_repository_and_sqlite_guard(service,monkeypatch):
    first=service.save_gym(entry_date=DAY,attended=True,difficulty=0)
    old=service.get('gym',first)
    def forbidden(*args,**kwargs):
        pytest.fail('Application should reject duplicate before repo.create')
    with monkeypatch.context() as scoped:
        scoped.setattr(GymRepository,'create',forbidden)
        with pytest.raises(DomainValidationError,match='уже существует'):
            service.save_gym(entry_date=DAY,attended=False)
    with service.storage.write() as s:
        with pytest.raises(ConstraintViolation):
            s.gym.create(old.value) # SQLite UNIQUE is independent protection
    assert service.get('gym',first)==old


def test_gym_edit_date_self_exclusion_and_metadata(service):
    first=service.save_gym(entry_date=DAY,attended=True,difficulty=5)
    old=service.get('gym',first)
    assert service.save_gym(entry_date=DAY,attended=True,difficulty=7,record_id=first)==first
    edited=service.get('gym',first).value
    assert edited.created_at==old.value.created_at and edited.difficulty_scale_version==old.value.difficulty_scale_version
    assert edited.updated_at>=old.value.updated_at
    second=service.save_gym(entry_date=DAY+timedelta(days=1),attended=False)
    with pytest.raises(DomainValidationError):
        service.save_gym(entry_date=DAY+timedelta(days=1),attended=True,difficulty=9,record_id=first)
    assert service.get('gym',first).value==edited
    assert service.get('gym',second).value.attended is False
    service.save_gym(entry_date=DAY+timedelta(days=2),attended=True,difficulty=10,record_id=first)
    assert service.get('gym',first).value.entry_date==DAY+timedelta(days=2)


def test_gym_yes_no_yes_preserves_null_not_zero(service):
    record_id=service.save_gym(entry_date=DAY,attended=True,difficulty=0)
    service.save_gym(entry_date=DAY,attended=False,record_id=record_id)
    old=service.get('gym',record_id)
    assert old.value.difficulty is None
    with pytest.raises(DomainValidationError):
        service.save_gym(entry_date=DAY,attended=True,difficulty=None,record_id=record_id)
    assert service.get('gym',record_id)==old
    service.save_gym(entry_date=DAY,attended=True,difficulty=8,record_id=record_id)
    assert service.get('gym',record_id).value.difficulty==8


@pytest.mark.parametrize('fields',[
    dict(entry_date=None,attended=False),dict(entry_date=date(2030,1,1),attended=False),
    dict(entry_date=DAY,attended=None),dict(entry_date=DAY,attended=True,difficulty=-1),
    dict(entry_date=DAY,attended=True,difficulty=11),dict(entry_date=DAY,attended=True,difficulty=True),
    dict(entry_date=DAY,attended=False,difficulty=0),
])
def test_gym_invalid_input(service,fields):
    with pytest.raises(DomainValidationError):
        service.save_gym(**fields)


@pytest.mark.parametrize('existing',[False,True])
def test_gym_rollback_before_commit(service,monkeypatch,existing):
    record_id=service.save_gym(entry_date=DAY,attended=False) if existing else None
    old=service.get('gym',record_id) if existing else None
    write=service.storage.write
    @contextmanager
    def fail():
        with write() as s:
            yield s
            raise StorageError('before commit')
    monkeypatch.setattr(service.storage,'write',fail)
    with pytest.raises(StorageError):
        service.save_gym(entry_date=DAY,attended=True,difficulty=4,record_id=record_id)
    if existing:
        assert service.get('gym',record_id)==old
    else:
        with service.storage.read_snapshot() as s:
            assert not s.gym.all()


def test_gym_missing_id_never_creates(service):
    with pytest.raises(RecordNotFound):
        service.save_gym(entry_date=DAY,attended=False,record_id=999)


def test_gym_updated_at_uses_new_transaction_time(service):
    record_id=service.save_gym(entry_date=DAY,attended=False)
    old=service.get('gym',record_id).value
    service.storage.clock=lambda: old.updated_at+timedelta(minutes=1)
    service.save_gym(entry_date=DAY,attended=True,difficulty=0,record_id=record_id)
    saved=service.get('gym',record_id).value
    assert saved.created_at==old.created_at and saved.updated_at>old.updated_at
