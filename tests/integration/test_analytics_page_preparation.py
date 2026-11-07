from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC,date,datetime,timedelta
from threading import get_ident
from concurrent.futures import ThreadPoolExecutor
import json
from zoneinfo import ZoneInfo

import pytest

from healthtracker.application.analytics import Analytics
from healthtracker.application.analytics_page import AnalyticsPagePreparation,AnalyticsQuery
from healthtracker.application.observations import Observations
from healthtracker.domain.analytics import AnalysisContext,Indicator,period_statistics,compare_periods
from healthtracker.domain.answers import CognitiveAnswer,AnswerStatus
from healthtracker.domain.cognitive import CognitiveAssessment
from healthtracker.domain.charts import ChartMode
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.factors import sleep_comparison,gym_comparison
from healthtracker.domain.periods import DateRange,ComparisonPeriod,PeriodPair,comparison_periods

NOW=datetime(2026,11,4,12,tzinfo=UTC)
CONTEXT=AnalysisContext(NOW,UTC)
PERIOD=DateRange(date(2026,10,1),date(2026,10,10))


def seed(db,days=10,special=False):
    obs=Observations(db)
    for i in range(days):
        day=datetime(2026,10,1,10,tzinfo=UTC)+timedelta(days=i)
        answer=CognitiveAnswer(AnswerStatus.NOT_ENGAGED) if special else CognitiveAnswer.numeric(i%11)
        obs.save_cognitive(CognitiveAssessment(answer,CognitiveAnswer.numeric(0),CognitiveAnswer.numeric(i%11)),day)
        obs.save_mood(score=0,observed_at=day)
        obs.save_sleep(start=day-timedelta(hours=10),end=day-timedelta(hours=2))
        obs.save_gym(entry_date=day.date(),attended=i%2==0,difficulty=0 if i%2==0 else None)


def query(**kw):
    return AnalyticsQuery(PERIOD,CONTEXT,**kw)


@pytest.mark.parametrize('days',[0,1,6,7,10])
def test_existing_statistics_thresholds_and_single_snapshot(db,monkeypatch,days):
    seed(db,days)
    calls=[];original=db.read_snapshot
    @contextmanager
    def snapshot():
        with original() as session:
            calls.append(session);yield session
    monkeypatch.setattr(db,'read_snapshot',snapshot)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result=pool.submit(AnalyticsPagePreparation(Analytics(db)).prepare,query()).result(timeout=10)
    assert len(calls)==1 and not calls[0].active
    assert result.analytics.statistics.observed_days==days
    assert (result.analytics.statistics.summary is not None)==(days>=7)
    assert result.chart.mode==ChartMode.DAILY
    assert len(result.page_view.summary_rows)==6 and len(result.page_view.daily_rows)==10
    assert ('нужно 7' in result.page_view.caption)==(0<days<7)
    assert len(json.loads(result.projection_json)['factors']['gym']) == days


def test_all_results_are_existing_domain_results_and_observations_unchanged(db):
    seed(db)
    analytics=Analytics(db);snapshot=analytics.load(PERIOD,CONTEXT)
    pair=PeriodPair(DateRange(date(2026,10,1),date(2026,10,7)),DateRange(date(2026,10,4),date(2026,10,10)))
    result=AnalyticsPagePreparation(analytics).prepare(query(comparison_ranges=pair))
    assert result.statistics==tuple(period_statistics(snapshot.data,i,PERIOD,CONTEXT) for i in Indicator)
    assert result.analytics.sleep==sleep_comparison(snapshot.data,PERIOD,CONTEXT)
    assert result.analytics.gym==gym_comparison(snapshot.data,PERIOD,CONTEXT)
    assert result.comparison==compare_periods(snapshot.data,Indicator.COGNITIVE,pair.first,pair.second,CONTEXT)
    assert analytics.load(PERIOD,CONTEXT)==snapshot
    factors=json.loads(result.projection_json)['factors']
    assert len(factors['sleep'])==10 and len(factors['gym'])==10
    assert factors['gym'][0]['lines'][-1]=='Сложность: 0.00'
    assert 'Был: 5' in result.page_view.gym_text and 'Не был: 5' in result.page_view.gym_text
    assert result.analytics.gym.warning is None


@pytest.mark.parametrize('kind',list(ComparisonPeriod))
def test_automatic_comparisons_use_same_elapsed_calendar_part_and_one_snapshot(db,monkeypatch,kind):
    seed(db)
    analytics=Analytics(db);calls=[];original=analytics.load
    def load(period,context):
        calls.append(period);return original(period,context)
    monkeypatch.setattr(analytics,'load',load)
    result=AnalyticsPagePreparation(analytics).prepare(query(comparison_kind=kind))
    pair=comparison_periods(kind,CONTEXT.today)
    assert len(calls)==1 and result.comparison.first.period==pair.first and result.comparison.second.period==pair.second
    # Данные октября вне выбранного сравнения не попадают в ноябрьские сводки.
    assert result.comparison.first.measurements==0
    assert result.analytics.statistics.observed_days==10
    assert 'Разница: недоступна' in result.page_view.comparison_text


def test_specials_zero_missing_future_and_empty_gym_are_distinct(db):
    seed(db,days=1,special=True)
    result=AnalyticsPagePreparation(Analytics(db)).prepare(query())
    row=result.page_view.daily_rows[0]
    assert row[1]=='—' and 'Не занимался' in row[-1]
    learning=result.statistics[1];application=result.statistics[2]
    assert learning.measurements==0 and application.daily[0].median==0
    assert result.statistics[-1].daily[0].median==0
    assert result.analytics.gym.difference is None
    assert 'Мало наблюдений' in result.page_view.gym_text
    assert result.analytics.sleep.excluded_days==10
    assert len(result.page_view.exclusions)==10
    future=replace(query(),period=DateRange(date(2026,11,4),date(2026,11,6)))
    assert AnalyticsPagePreparation(Analytics(db)).prepare(future).page_view.daily_rows[-1][-1]=='Будущая часть периода'


@pytest.mark.parametrize('zone',['UTC','America/New_York','Europe/Berlin'])
def test_context_and_dst_are_not_changed(db,zone):
    context=AnalysisContext(NOW,ZoneInfo(zone))
    q=AnalyticsQuery(DateRange(date(2026,11,1),date(2026,11,1)),context)
    result=AnalyticsPagePreparation(Analytics(db)).prepare(q)
    assert result.query.context==context and result.analytics.statistics.context==context
    assert result.analytics.statistics.calendar_days==1


def test_database_can_close_before_calculation_and_token_invalidates_on_commit(db):
    seed(db)
    preparation=AnalyticsPagePreparation(Analytics(db))
    result=preparation.prepare(query(),snapshot_ready=lambda token:db.close())
    assert result.analytics.statistics.observed_days==10
    db.initialize()
    assert not db.is_current(result.token)


@pytest.mark.parametrize('changes',[{'comparison_kind':'week'}, {'comparison_ranges':'bad'},
    {'comparison_ranges':PeriodPair(PERIOD,'bad')},
    {'comparison_kind':ComparisonPeriod.MONTH,'comparison_ranges':PeriodPair(PERIOD,PERIOD)}])
def test_bad_query_rejected(changes):
    with pytest.raises(DomainValidationError):query(**changes)
