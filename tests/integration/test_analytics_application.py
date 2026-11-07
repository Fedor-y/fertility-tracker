from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import FrozenInstanceError,replace
from datetime import UTC,date,datetime,timedelta
from threading import Event,get_ident
from zoneinfo import ZoneInfo

import pytest

from healthtracker.application.analytics import Analytics,calculate_snapshot,JOURNALS
from healthtracker.application.errors import StorageError
from healthtracker.application.observations import Observations
from healthtracker.application.session import ApplicationSession
from healthtracker.domain.analytics import AnalysisContext,Indicator
from healthtracker.domain.answers import AnswerStatus,CognitiveAnswer
from healthtracker.domain.catalogs import MealCategory,SymptomStatus
from healthtracker.domain.cognitive import CognitiveAssessment
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.periods import DateRange,PeriodPair
from healthtracker.infrastructure.sqlite.base import RecordRepository

NOW=datetime(2026,11,4,12,tzinfo=UTC)
DAY=date(2026,11,1)
MOMENT=datetime(2026,11,1,12,tzinfo=UTC)
PERIOD=DateRange(DAY,DAY)
CONTEXT=AnalysisContext(NOW,UTC)


def populate(db):
    obs=Observations(db,clock=db.clock)
    assessment=CognitiveAssessment(CognitiveAnswer.numeric(0),CognitiveAnswer(AnswerStatus.NOT_ENGAGED),
                                   CognitiveAnswer(AnswerStatus.CANNOT_ASSESS))
    ids={
        'cognitive':obs.save_cognitive(assessment,MOMENT),
        'physical':obs.save_physical(score=0,observed_at=MOMENT,symptom_status=SymptomStatus.UNKNOWN,symptoms=()),
        'stress':obs.save_stress(score=0,observed_at=MOMENT),
        'mood':obs.save_mood(score=0,observed_at=MOMENT),
        'sleep':obs.save_sleep(start=MOMENT-timedelta(hours=8),end=MOMENT),
        'meals':obs.save_meal(entry_date=DAY,category=MealCategory.OTHER,items=({'name':'Вода'},)),
        'gym':obs.save_gym(entry_date=DAY,attended=False),
    }
    return obs,ids


def test_snapshot_one_session_seven_repositories_preserves_ids_and_versions(db,monkeypatch):
    obs,ids=populate(db)
    original=db.read_snapshot
    calls=[]
    @contextmanager
    def counted():
        with original() as session:
            calls.append(session)
            yield session
    monkeypatch.setattr(db,'read_snapshot',counted)
    snapshot=Analytics(db).load(PERIOD,CONTEXT)
    assert len(calls)==1 and not calls[0].active
    for kind in JOURNALS:
        row=getattr(snapshot,kind)[0]
        assert row.id==ids[kind]
        assert row.value==obs.get(kind,row.id).value
    assert snapshot.cognitive[0].value.assessment.formula_version==1
    assert snapshot.physical[0].value.scale_version==1
    assert snapshot.stress[0].value.score==0 and snapshot.gym[0].value.attended is False
    assert snapshot.cognitive[0].value.assessment.application.value is None
    with pytest.raises(FrozenInstanceError): snapshot.period=PERIOD


def test_calculations_work_after_storage_closed_and_source_connection_cannot_be_reused(db):
    populate(db)
    snapshot=Analytics(db).load(PERIOD,CONTEXT)
    db.close()
    with ThreadPoolExecutor(max_workers=1) as pool:
        result=pool.submit(calculate_snapshot,snapshot,Indicator.LEARNING).result(timeout=5)
    assert result.statistics.daily[0].median==0
    assert result.statistics.measurements==1 and result.statistics.summary is None
    assert result.gym.attended.days==result.gym.absent.days==0 # индекс отсутствует
    assert result.sleep.excluded_days==1


@pytest.mark.parametrize('day,zone_name',[
    (date(2026,3,29),'Europe/Berlin'),(date(2026,10,25),'Europe/Berlin'),
    (date(2011,12,30),'Pacific/Apia'),(DAY,'Pacific/Kiritimati'),(DAY,'Etc/GMT+12'),
])
def test_range_filter_matches_local_dates_not_fixed_utc_days(db,day,zone_name):
    obs=Observations(db,clock=db.clock)
    zone=ZoneInfo(zone_name)
    base=datetime.combine(day,datetime.min.time(),UTC)
    # Независимый эталон: перебираем реальные UTC-моменты и сравниваем date().
    moments=tuple(base+timedelta(hours=h) for h in range(-36,61,3))
    for moment in moments: obs.save_mood(score=0,observed_at=moment)
    obs.save_gym(entry_date=day,attended=False)
    snapshot=Analytics(db).load(DateRange(day,day),AnalysisContext(NOW,zone))
    expected=tuple(moment for moment in moments if moment.astimezone(zone).date()==day)
    assert tuple(r.value.observed_at for r in snapshot.mood)==expected
    assert len(snapshot.gym)==1 and snapshot.gym[0].value.entry_date==day


@pytest.mark.parametrize('period',[DateRange(date.min,date.min),DateRange(date.max,date.max)])
def test_extreme_empty_calendar_ranges_do_not_overflow(db,period):
    snapshot=Analytics(db).load(period,CONTEXT)
    assert all(getattr(snapshot,kind)==() for kind in JOURNALS)


def test_single_moment_cutoff_and_future_dates_are_filtered_from_all_seven_journals(db):
    populate(db)
    context=AnalysisContext(MOMENT-timedelta(days=1),UTC)
    snapshot=Analytics(db).load(PERIOD,context)
    assert all(getattr(snapshot,kind)==() for kind in JOURNALS)
    current=Analytics(db).load(PERIOD,AnalysisContext(MOMENT-timedelta(seconds=1),UTC))
    assert current.mood==() and current.cognitive==() and current.sleep==()
    assert len(current.meals)==len(current.gym)==1 # только дата, час не выдумывается


def test_compare_reads_both_ranges_once_and_keeps_independent_coverage(db,monkeypatch):
    obs=Observations(db,clock=db.clock)
    for month,score in ((9,2),(10,8)):
        assessment=CognitiveAssessment(*(CognitiveAnswer.numeric(score) for _ in range(3)))
        for day in range(1,8): obs.save_cognitive(assessment,datetime(2026,month,day,12,tzinfo=UTC))
    reads=[]
    original=db.read_snapshot
    @contextmanager
    def counted():
        reads.append(1)
        with original() as session: yield session
    monkeypatch.setattr(db,'read_snapshot',counted)
    result=Analytics(db).compare(PeriodPair(DateRange(date(2026,10,1),date(2026,10,14)),
        DateRange(date(2026,9,1),date(2026,9,7))),Indicator.COGNITIVE,CONTEXT)
    assert reads==[1] and result.comparison.difference==6
    assert result.comparison.first.coverage_percent==50
    assert result.comparison.second.coverage_percent==100


def test_snapshot_does_not_mix_data_during_concurrent_write_and_token_invalidates(db,monkeypatch):
    obs,ids=populate(db)
    started,pending=Event(),Event()
    original=RecordRepository.between
    loader_thread=[]
    def tracked(repo,start,end):
        rows=original(repo,start,end)
        if repo.table=='cognitive_entries':
            loader_thread.append(get_ident())
            started.set()
            assert pending.wait(2)
        return rows
    monkeypatch.setattr(RecordRepository,'between',tracked)
    old=obs.get('mood',ids['mood']).value
    def writer():
        assert started.wait(2)
        with db.write() as session:
            session.mood.update(ids['mood'],replace(old,score=10))
            session.gym.delete(ids['gym'])
            pending.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        write=pool.submit(writer)
        read=pool.submit(Analytics(db).load,PERIOD,CONTEXT)
        snapshot=read.result(timeout=5)
        write.result(timeout=5)
    assert loader_thread[0]!=get_ident()
    assert snapshot.mood[0].value.score==0 and len(snapshot.gym)==1
    assert not Analytics(db).is_current(snapshot.token)
    assert obs.get('mood',ids['mood']).value.score==10
    with db.read_snapshot() as session: assert session.gym.all()==()


def test_read_error_is_propagated_not_replaced_with_empty_statistics(db,monkeypatch):
    def fail(*args): raise StorageError('synthetic failure')
    monkeypatch.setattr(RecordRepository,'between',fail)
    with pytest.raises(StorageError): Analytics(db).run(PERIOD,Indicator.COGNITIVE,CONTEXT)


def test_unknown_historical_version_fails_without_substitution(db):
    _,ids=populate(db)
    with db.write() as session:
        session.connection.execute("INSERT INTO scale_versions(scale_code,version,definition,created_at_utc) SELECT scale_code,2,definition,created_at_utc FROM scale_versions WHERE scale_code='mood'")
        version=session.connection.execute("SELECT id FROM scale_versions WHERE scale_code='mood' AND version=2").fetchone()[0]
        session.connection.execute('UPDATE mood_entries SET scale_version_id=? WHERE id=?',(version,ids['mood']))
    with pytest.raises(DomainValidationError): Analytics(db).load(PERIOD,CONTEXT)
    with db.read_snapshot() as session:
        assert session.connection.execute('SELECT scale_version_id FROM mood_entries WHERE id=?',(ids['mood'],)).fetchone()[0]==version


def test_application_session_exposes_analytics_on_existing_storage(db):
    application=ApplicationSession(db)
    assert application.open()
    result=application.analytics.run(PERIOD,Indicator.COGNITIVE,CONTEXT)
    assert result.statistics.daily==() and result.statistics.coverage_percent==0
    assert application.analytics.is_current(result.token)


def test_unknown_formula_version_is_not_recalculated_as_version_one(db):
    from healthtracker.application.errors import SchemaError
    _,ids=populate(db)
    with db.write() as session:
        session.connection.execute("INSERT INTO formula_versions(formula_code,version,definition,created_at_utc) SELECT formula_code,2,definition,created_at_utc FROM formula_versions WHERE formula_code='cognitive_index'")
        version=session.connection.execute("SELECT id FROM formula_versions WHERE formula_code='cognitive_index' AND version=2").fetchone()[0]
        session.connection.execute('UPDATE cognitive_entries SET formula_version_id=? WHERE id=?',(version,ids['cognitive']))
    with pytest.raises(SchemaError): Analytics(db).load(PERIOD,CONTEXT)
    with db.read_snapshot() as session:
        assert session.connection.execute('SELECT formula_version_id FROM cognitive_entries WHERE id=?',(ids['cognitive'],)).fetchone()[0]==version
