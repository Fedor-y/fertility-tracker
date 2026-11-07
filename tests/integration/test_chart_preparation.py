from dataclasses import FrozenInstanceError
from datetime import UTC,date,datetime,timedelta

import pytest

from healthtracker.application.analytics import Analytics
from healthtracker.application.charts import ChartPreparation,ChartQuery
from healthtracker.application.observations import Observations
from healthtracker.domain.analytics import AnalysisContext,Indicator
from healthtracker.domain.answers import AnswerStatus,CognitiveAnswer
from healthtracker.domain.catalogs import MealCategory,SymptomStatus
from healthtracker.domain.charts import ChartMode,SeriesKind
from healthtracker.domain.cognitive import CognitiveAssessment
from healthtracker.domain.periods import DateRange

NOW=datetime(2026,11,4,12,tzinfo=UTC)
MOMENT=datetime(2026,11,1,12,tzinfo=UTC)
DAY=MOMENT.date()
QUERY=ChartQuery(DateRange(DAY,DAY),AnalysisContext(NOW,UTC),visible_series=tuple(SeriesKind))


def test_preparation_preserves_seven_journal_links_and_closes_read_before_math(db,monkeypatch):
    obs=Observations(db,clock=db.clock)
    cognitive=obs.save_cognitive(CognitiveAssessment(CognitiveAnswer.numeric(0),CognitiveAnswer(AnswerStatus.NOT_ENGAGED),
        CognitiveAnswer(AnswerStatus.CANNOT_ASSESS)),MOMENT)
    obs.save_physical(score=0,observed_at=MOMENT,symptom_status=SymptomStatus.UNKNOWN,symptoms=())
    obs.save_mood(score=0,observed_at=MOMENT)
    obs.save_stress(score=0,observed_at=MOMENT)
    sleep=obs.save_sleep(start=MOMENT-timedelta(hours=8),end=MOMENT)
    meal=obs.save_meal(entry_date=DAY,category=MealCategory.OTHER,items=({'name':'Вода'},))
    gym=obs.save_gym(entry_date=DAY,attended=True,difficulty=0)
    import healthtracker.application.charts as module
    original=module.calculate_snapshot
    def calculate(snapshot,indicator):
        assert db._active==0
        # Ни вычисления, ни последующая подготовка не обращаются к SQLite.
        db.close()
        return original(snapshot,indicator)
    monkeypatch.setattr(module,'calculate_snapshot',calculate)
    result=ChartPreparation(Analytics(db)).prepare(QUERY)
    point=result.chart.series[0].points[0]
    assert point.value is None and point.sources[0].record_id==cognitive
    assert tuple(answer.status for answer in point.sources[0].cognitive_answers)==(
        AnswerStatus.NUMERIC,AnswerStatus.NOT_ENGAGED,AnswerStatus.CANNOT_ASSESS)
    assert point.sources[0].cognitive_answers[0].value==0
    assert [(d.code,d.version) for d in point.sources[0].definitions]==[
        ('learning',1),('application',1),('speed',1),('cognitive_index',1)]
    assert point.interval_start==MOMENT-timedelta(hours=1)
    assert {s.kind.value: s.points[0].value for s in result.chart.series[1:]} == {
        'learning': 0, 'application': None, 'speed': None, 'physical': 0, 'mood': 0, 'stress': 0}
    assert {e.source.record_id for e in result.chart.calendar_events if e.source.kind=='meals'}=={meal}
    assert result.chart.calendar_events[1].source.record_id==gym
    assert result.chart.calendar_events[1].source.definitions[0].code=='gym_difficulty'
    assert result.chart.sleep[0].source.record_id==sleep and result.chart.sleep[0].wake_day==DAY
    with pytest.raises(FrozenInstanceError): result.query=QUERY


def test_daily_preparation_uses_existing_median_and_preserves_duplicate_observations(db):
    obs=Observations(db,clock=db.clock)
    ids=[]
    for score in (2,8):
        ids.append(obs.save_cognitive(CognitiveAssessment(*(CognitiveAnswer.numeric(score) for _ in range(3))),MOMENT))
    query=ChartQuery(DateRange(date(2026,10,26),DAY+timedelta(days=1)),QUERY.context)
    result=ChartPreparation(Analytics(db)).prepare(query)
    assert result.chart.mode is ChartMode.DAILY
    point=result.chart.series[0].points[0]
    assert point.value==5 and point.measurements==2 and point.minimum==2 and point.maximum==8
    assert tuple(ref.record_id for ref in point.sources)==tuple(ids)
    assert point.utc_moment is None


def test_selected_analytics_indicator_does_not_change_cognitive_chart_formula(db):
    obs=Observations(db,clock=db.clock)
    obs.save_cognitive(CognitiveAssessment(CognitiveAnswer.numeric(0),CognitiveAnswer.numeric(6),CognitiveAnswer.numeric(9)),MOMENT)
    query=ChartQuery(QUERY.period,QUERY.context,indicator=Indicator.LEARNING)
    result=ChartPreparation(Analytics(db)).prepare(query)
    assert result.analytics.statistics.daily[0].median==0
    assert result.chart.series[0].points[0].value==5


def test_empty_preparation_has_no_fictitious_points_or_segments(db):
    result=ChartPreparation(Analytics(db)).prepare(QUERY)
    assert all(s.points==s.segments==() for s in result.chart.series)
    assert result.chart.calendar_events==result.chart.sleep==()
