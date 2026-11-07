from dataclasses import replace
from datetime import UTC,date,datetime,timedelta
import json
import pytest
from healthtracker.application.analytics import Analytics
from healthtracker.application.charts import ChartPreparation,ChartQuery
from healthtracker.application.observations import Observations
from healthtracker.domain.analytics import AnalysisContext
from healthtracker.domain.answers import CognitiveAnswer,AnswerStatus
from healthtracker.domain.catalogs import MealCategory
from healthtracker.domain.cognitive import CognitiveAssessment
from healthtracker.domain.periods import DateRange

NOW=datetime(2026,11,4,12,tzinfo=UTC)
MOMENT=NOW-timedelta(days=1)
QUERY=ChartQuery(DateRange(MOMENT.date(),MOMENT.date()),AnalysisContext(NOW,UTC))


def seed(db):
    obs=Observations(db,clock=db.clock)
    obs.save_cognitive(CognitiveAssessment(*(CognitiveAnswer.numeric(6) for _ in range(3))),MOMENT)
    obs.save_cognitive(CognitiveAssessment(CognitiveAnswer.numeric(0),CognitiveAnswer(AnswerStatus.NOT_ENGAGED),CognitiveAnswer(AnswerStatus.CANNOT_ASSESS)),MOMENT)
    obs.save_sleep(start=MOMENT-timedelta(hours=8),end=MOMENT)
    obs.save_meal(entry_date=MOMENT.date(),category=MealCategory.OTHER,items=({'name':'Вода'},))
    obs.save_gym(entry_date=MOMENT.date(),attended=False)


@pytest.mark.parametrize('layer', ['sleep','meals','gym','events'])
def test_layers_change_only_chart_view_not_calculations(db,layer):
    seed(db)
    preparation=ChartPreparation(Analytics(db))
    baseline=preparation.prepare(QUERY)
    hidden=preparation.prepare(replace(QUERY,**{'show_'+layer:False}))
    assert hidden.analytics==baseline.analytics
    view=json.loads(hidden.projection_json)
    if layer=='sleep': assert hidden.chart.sleep==() and view['sleep']==[]
    elif layer=='events': assert view['events']==view['nonnumeric']==[] and hidden.chart.series==baseline.chart.series
    else: assert all(e.source.kind!=layer for e in hidden.chart.calendar_events)
    assert len(preparation.analytics.load(QUERY.period,QUERY.context).gym)==1


@pytest.mark.parametrize('layer', ['sleep','meals','gym','events'])
@pytest.mark.parametrize('value',[0,None])
def test_layer_flags_require_explicit_bool(layer,value):
    with pytest.raises(ValueError): replace(QUERY,**{'show_'+layer:value})


@pytest.mark.parametrize('visible',[(),('learning','stress')])
def test_visible_rows_do_not_change_analytics_or_stored_observations(db,visible):
    from healthtracker.domain.charts import SeriesKind
    seed(db)
    preparation=ChartPreparation(Analytics(db))
    before=preparation.prepare(QUERY)
    rows=preparation.analytics.load(QUERY.period,QUERY.context)
    after=preparation.prepare(replace(QUERY,visible_series=tuple(SeriesKind(v) for v in visible)))
    assert after.analytics==before.analytics
    assert preparation.analytics.load(QUERY.period,QUERY.context)==rows
