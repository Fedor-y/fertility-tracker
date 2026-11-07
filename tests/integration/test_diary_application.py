from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from healthtracker.application.diary import Diary, KINDS
from healthtracker.application.errors import ConfirmationRequired, RecordNotFound, StorageError
from healthtracker.application.observations import Observations
from healthtracker.domain.answers import AnswerStatus, CognitiveAnswer
from healthtracker.domain.catalogs import MealCategory, SymptomStatus, StressCause
from healthtracker.domain.cognitive import CognitiveAssessment

DAY=date(2026,11,1)
MOMENT=datetime(2026,11,1,0,30,tzinfo=UTC)


def seed(db):
    obs=Observations(db,clock=db.clock)
    assessment=CognitiveAssessment(CognitiveAnswer.numeric(0), CognitiveAnswer(AnswerStatus.NOT_ENGAGED),
                                   CognitiveAnswer(AnswerStatus.CANNOT_ASSESS))
    ids={}
    ids['cognitive']=obs.save_cognitive(assessment,MOMENT)
    ids['physical']=obs.save_physical(score=10,observed_at=MOMENT,symptom_status=SymptomStatus.UNKNOWN,symptoms=())
    ids['stress']=obs.save_stress(score=0,observed_at=MOMENT)
    ids['mood']=obs.save_mood(score=0,observed_at=MOMENT)
    ids['sleep']=obs.save_sleep(start=MOMENT-timedelta(hours=8),end=MOMENT)
    ids['meals']=obs.save_meal(entry_date=DAY,category=MealCategory.LUNCH,items=({'name':'Чай'},))
    ids['gym']=obs.save_gym(entry_date=DAY,attended=False)
    return ids,obs


def test_diary_empty_and_all_types_one_snapshot(db,monkeypatch):
    diary=Diary(db)
    assert not diary.day(DAY,ZoneInfo('UTC')).timed
    ids,obs=seed(db)
    read=db.read_snapshot;calls=[]
    @contextmanager
    def counted():
        calls.append(1)
        with read() as s:
            yield s
    monkeypatch.setattr(db,'read_snapshot',counted)
    day=diary.day(DAY,ZoneInfo('UTC'))
    assert len(calls)==1
    assert {r.kind:r.id for r in (*day.timed,*day.untimed)}==ids
    assert all(r.moment is None for r in day.untimed)
    summaries={r.kind:r.summary for r in day.timed+day.untimed}
    assert 'Не занимался' in summaries['cognitive'] and 'Не могу оценить' in summaries['cognitive']
    assert 'Новое: 0' in summaries['cognitive'] and 'Индекс не рассчитан' in summaries['cognitive']
    assert 'отсутствуют' in summaries['physical']
    assert 'нет (0)' in summaries['stress'] and '0/10' in summaries['mood']
    assert 'не был' in summaries['gym']


def test_diary_utc_order_equal_times_and_zone_regroup(db):
    ids,obs=seed(db);diary=Diary(db)
    extra=obs.save_cognitive(obs.get('cognitive',ids['cognitive']).value.assessment,MOMENT)
    day=diary.day(DAY,ZoneInfo('UTC'))
    assert [(r.kind,r.id) for r in day.timed][:2]==[('cognitive',ids['cognitive']),('cognitive',extra)]
    previous=diary.day(DAY-timedelta(days=1),ZoneInfo('America/New_York'))
    assert len(previous.timed)==6 and not previous.untimed
    shifted=diary.day(DAY,ZoneInfo('America/New_York'))
    assert not shifted.timed and len(shifted.untimed)==2
    assert obs.get('cognitive',extra).value.interval.end==MOMENT


def test_diary_multiple_sleep_meals_and_repeated_hour(db):
    obs=Observations(db,clock=db.clock);diary=Diary(db)
    first=datetime(2026,10,25,0,30,tzinfo=UTC)
    second=first+timedelta(hours=1)
    a=obs.save_mood(score=3,observed_at=first)
    b=obs.save_mood(score=7,observed_at=second)
    obs.save_sleep(start=first-timedelta(hours=4),end=first)
    obs.save_sleep(start=first,end=second)
    for _ in range(2):
        obs.save_meal(entry_date=first.date(),category=MealCategory.OTHER,items=({'name':'Вода'},))
    day=diary.day(first.date(),ZoneInfo('Europe/Berlin'))
    moods=[r for r in day.timed if r.kind=='mood']
    assert [r.id for r in moods]==[a,b]
    assert [r.moment.astimezone(ZoneInfo('Europe/Berlin')).hour for r in moods]==[2,2]
    assert len([r for r in day.timed if r.kind=='sleep'])==2 and len(day.untimed)==2


@pytest.mark.parametrize('kind',KINDS)
def test_diary_delete_confirm_cascade_and_other_records(db,kind):
    ids,obs=seed(db);diary=Diary(db)
    with pytest.raises(ConfirmationRequired):
        diary.delete(kind,ids[kind])
    assert len(diary.day(DAY,ZoneInfo('UTC')).timed)+len(diary.day(DAY,ZoneInfo('UTC')).untimed)==7
    diary.delete(kind,ids[kind],confirmed=True)
    remaining=diary.day(DAY,ZoneInfo('UTC'))
    assert len(remaining.timed)+len(remaining.untimed)==6
    for other in KINDS:
        if other!=kind:
            assert obs.get(other,ids[other])
    with pytest.raises(RecordNotFound):
        diary.delete(kind,ids[kind],confirmed=True)
    with db.read_snapshot() as s:
        assert not s.connection.execute('PRAGMA foreign_key_check').fetchall()
        assert s.definitions.scale('learning').version==1
        if kind=='meals':
            assert s.connection.execute('SELECT count(*) FROM meal_items').fetchone()[0]==0


@pytest.mark.parametrize('kind',KINDS)
def test_diary_delete_rollback_restores_aggregate(db,monkeypatch,kind):
    ids,obs=seed(db);diary=Diary(db)
    original=obs.get(kind,ids[kind])
    write=db.write
    @contextmanager
    def fail():
        with write() as s:
            yield s
            raise StorageError('before commit')
    monkeypatch.setattr(db,'write',fail)
    with pytest.raises(StorageError):
        diary.delete(kind,ids[kind],confirmed=True)
    assert obs.get(kind,ids[kind])==original


@pytest.mark.parametrize('kind',['physical','stress','meals'])
def test_diary_real_children_cascade_and_catalogs(db,kind):
    from healthtracker.domain.catalogs import SymptomCode
    from healthtracker.domain.records import Symptom
    ids,obs=seed(db);diary=Diary(db)
    if kind=='physical':
        record_id=obs.save_physical(score=4,observed_at=MOMENT,symptom_status=SymptomStatus.LISTED,
            symptoms=(Symptom(SymptomCode.HEADACHE),))
        child,column='physical_symptoms','physical_entry_id'
    elif kind=='stress':
        record_id=obs.save_stress(score=5,observed_at=MOMENT,causes=(StressCause.WORK,),comment='Причина')
        child,column='stress_causes','stress_entry_id'
    else:
        record_id=obs.save_meal(entry_date=DAY,category=MealCategory.OTHER,items=({'name':'Вода'},))
        child,column='meal_items','meal_id'
    with db.read_snapshot() as s:
        assert s.connection.execute(f'SELECT count(*) FROM {child} WHERE {column}=?',(record_id,)).fetchone()[0]==1
        before=s.connection.execute('SELECT count(*) FROM symptom_catalog').fetchone()[0]
        tables=s.connection.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name").fetchall()
    diary.delete(kind,record_id,confirmed=True)
    with db.read_snapshot() as s:
        assert s.connection.execute(f'SELECT count(*) FROM {child} WHERE {column}=?',(record_id,)).fetchone()[0]==0
        assert s.connection.execute('SELECT count(*) FROM symptom_catalog').fetchone()[0]==before
        assert len(s.definitions.stress_causes())==6
        assert s.connection.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name").fetchall()==tables
    assert obs.get(kind,ids[kind])


def test_diary_reopen_after_deletes_no_history_or_report_table(db):
    from healthtracker.infrastructure.sqlite.database import Database
    ids,obs=seed(db);diary=Diary(db)
    for kind in KINDS:
        diary.delete(kind,ids[kind],confirmed=True)
    path=db.path;clock=db.clock;db.close()
    with Database(path,clock=clock) as reopened:
        day=Diary(reopened).day(DAY,ZoneInfo('UTC'))
        assert not day.timed and not day.untimed


def test_diary_single_type_and_unknown_delete_kind(db):
    from healthtracker.domain.errors import DomainValidationError
    obs=Observations(db);obs.save_mood(score=0,observed_at=MOMENT)
    day=Diary(db).day(DAY,ZoneInfo('UTC'))
    assert len(day.timed)==1 and not day.untimed
    with pytest.raises(DomainValidationError):
        Diary(db).delete('settings',1,confirmed=True)


@pytest.mark.parametrize('day,zone_name', [
    (date(2026,3,29),'Europe/Berlin'),
    (date(2026,10,25),'Europe/Berlin'),
    (date(2011,12,30),'Pacific/Apia'),
    (date(2026,11,1),'Pacific/Kiritimati'),
    (date(2026,11,1),'Etc/GMT+12'),
])
def test_day_range_matches_full_snapshot_at_timezone_boundaries(db, day, zone_name, monkeypatch):
    """Сужение SQL-диапазона не теряет события у полуночи/DST/пропущенной даты."""
    from healthtracker.domain.time import local_date
    from healthtracker.infrastructure.sqlite.base import RecordRepository
    obs=Observations(db,clock=db.clock)
    zone=ZoneInfo(zone_name)
    base=datetime.combine(day,datetime.min.time(),UTC)
    for hours in range(-36,61,3):
        obs.save_mood(score=hours%11,observed_at=base+timedelta(hours=hours))
    obs.save_meal(entry_date=day,category=MealCategory.OTHER,items=({'name':'Вода'},))
    obs.save_gym(entry_date=day,attended=False)
    with db.read_snapshot() as session:
        expected=[r.id for r in session.mood.all() if local_date(r.value.observed_at,zone)==day]
    def forbidden(self):
        raise AssertionError('Дневник обычной даты не должен читать весь архив')
    monkeypatch.setattr(RecordRepository,'all',forbidden)
    result=Diary(db).day(day,zone)
    assert [r.id for r in result.timed]==expected
    assert {r.kind for r in result.untimed}=={'meals','gym'}


@pytest.mark.parametrize('day',[date.min,date.max])
def test_diary_calendar_limits_do_not_overflow(db,day):
    result=Diary(db).day(day,UTC)
    assert not result.timed and not result.untimed
