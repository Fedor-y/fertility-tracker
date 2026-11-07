"""Аудит существующих контрактов для аналитики, без реализации её формул."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta
from threading import Event, get_ident
from zoneinfo import ZoneInfo

import pytest

from healthtracker.application.diary import Diary, KINDS
from healthtracker.application.observations import Observations
from healthtracker.domain.answers import AnswerStatus, CognitiveAnswer
from healthtracker.domain.catalogs import CaffeineStatus, MealCategory, SymptomStatus
from healthtracker.domain.cognitive import CognitiveAssessment, cognitive_index
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.time import local_date

DAY = date(2026, 11, 1)
START = datetime(2026, 11, 1, tzinfo=UTC)
END = START + timedelta(days=1)


def assessment():
    return CognitiveAssessment(CognitiveAnswer.numeric(0),
        CognitiveAnswer(AnswerStatus.NOT_ENGAGED), CognitiveAnswer(AnswerStatus.CANNOT_ASSESS))


def populate(db):
    service = Observations(db, clock=db.clock)
    ids = {}
    moment = START + timedelta(hours=12)
    ids['cognitive'] = service.save_cognitive(assessment(), moment)
    ids['physical'] = service.save_physical(score=0, observed_at=moment,
        symptom_status=SymptomStatus.UNKNOWN, symptoms=())
    ids['stress'] = service.save_stress(score=0, observed_at=moment)
    ids['mood'] = service.save_mood(score=0, observed_at=moment)
    ids['sleep'] = service.save_sleep(start=moment-timedelta(hours=8), end=moment)
    ids['meals'] = service.save_meal(entry_date=DAY, category=MealCategory.OTHER,
        items=({'name':'Искусственная позиция'},))
    ids['gym'] = service.save_gym(entry_date=DAY, attended=False)
    return service, ids


@pytest.mark.parametrize('kind', KINDS)
def test_existing_range_is_half_open_for_each_journal(db, kind):
    service = Observations(db, clock=db.clock)
    moments = (START-timedelta(microseconds=1), START, END-timedelta(microseconds=1), END)
    expected = []
    previous = moments[0]-timedelta(hours=1)
    for index, moment in enumerate(moments):
        if kind == 'cognitive': record_id = service.save_cognitive(assessment(), moment)
        elif kind == 'physical':
            record_id = service.save_physical(score=0, observed_at=moment,
                symptom_status=SymptomStatus.NONE_CONFIRMED, symptoms=())
        elif kind in ('stress','mood'):
            record_id = getattr(service,'save_'+kind)(score=0, observed_at=moment)
        elif kind == 'sleep':
            record_id = service.save_sleep(start=previous, end=moment, long_sleep_confirmed=True)
        else: break
        if index in (1,2): expected.append(record_id)
        previous = moment
    if kind in ('meals','gym'):
        for offset in (-1,0,1):
            day = DAY+timedelta(days=offset)
            record_id = (service.save_gym(entry_date=day, attended=False) if kind=='gym'
                else service.save_meal(entry_date=day,category=MealCategory.OTHER,items=({'name':'Вода'},)))
            if offset==0: expected.append(record_id)
        lower, upper = DAY, DAY+timedelta(days=1)
    else: lower, upper = START, END
    with db.read_snapshot() as session:
        repo = getattr(session,kind)
        assert [row.id for row in repo.between(lower,upper)] == expected
        with pytest.raises(DomainValidationError): repo.between(upper,lower)
        with pytest.raises(DomainValidationError): repo.between(lower,lower)


def test_worker_can_read_seven_journals_then_calculate_without_connection(db):
    _, ids = populate(db)
    caller_thread = get_ident()
    def read():
        with db.read_snapshot() as session:
            records = tuple((kind,getattr(session,kind).get(ids[kind])) for kind in KINDS)
            token = session.token
        return get_ident(), records, token
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker_thread, records, token = pool.submit(read).result(timeout=5)
    assert worker_thread != caller_thread and db.is_current(token)
    db.close()
    # Соединение уже закрыто; ниже только модели и Domain-функции.
    values = {kind:row.value for kind,row in records}
    assert cognitive_index(values['cognitive'].assessment) is None
    assert values['cognitive'].assessment.learning.value == 0
    assert values['physical'].symptom_status is SymptomStatus.UNKNOWN
    assert values['stress'].score == values['mood'].score == 0
    assert values['meals'].items[0].caffeine_status is CaffeineStatus.UNSPECIFIED
    assert values['gym'].attended is False and values['gym'].difficulty is None
    assert values['sleep'].interval.duration == timedelta(hours=8)
    assert local_date(values['mood'].observed_at,ZoneInfo('Pacific/Kiritimati')) == DAY+timedelta(days=1)
    with pytest.raises(FrozenInstanceError): values['mood'].score = 5
    assert not db.is_current(token)


def test_one_snapshot_keeps_all_seven_journals_during_compound_write(db):
    _, ids = populate(db)
    pending = Event()
    def remove_all():
        with db.write() as session:
            for kind in KINDS: getattr(session,kind).delete(ids[kind])
            pending.set()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with db.read_snapshot() as session:
            token = session.token
            assert session.cognitive.get(ids['cognitive']) is not None
            future = pool.submit(remove_all)
            assert pending.wait(1)
            # Пишущая транзакция не смешивается с исходным читающим снимком.
            for kind in KINDS: assert getattr(session,kind).get(ids[kind]) is not None
        future.result(timeout=5)
    assert not db.is_current(token)
    with db.read_snapshot() as session:
        for kind in KINDS: assert getattr(session,kind).get(ids[kind]) is None


def test_diary_keeps_zeros_specials_and_date_only_records_under_zone_change(db):
    _, ids = populate(db)
    before = Diary(db).day(DAY,UTC)
    after = Diary(db).day(DAY,ZoneInfo('Pacific/Kiritimati'))
    moved = Diary(db).day(DAY+timedelta(days=1),ZoneInfo('Pacific/Kiritimati'))
    assert {row.kind:row.id for row in before.timed+before.untimed} == ids
    assert {row.kind for row in after.untimed} == {'meals','gym'} and not after.timed
    assert {row.kind for row in moved.timed} == set(KINDS)-{'meals','gym'}
    assert not moved.untimed


def test_existing_schema_rejects_malformed_settings_without_losing_value(db):
    from healthtracker.application.errors import ConstraintViolation
    with db.write() as session:
        session.settings.set('compact_mode',False)
    with pytest.raises(ConstraintViolation):
        with db.write() as session:
            session.connection.execute('UPDATE application_settings SET value=? WHERE key=?',
                ('{','compact_mode'))
    with db.read_snapshot() as session:
        assert session.settings.get('compact_mode') is False
