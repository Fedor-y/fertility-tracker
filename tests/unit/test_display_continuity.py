"""Полуночные соединения проекции не меняют Domain и не обходят настоящие разрывы."""
from datetime import datetime, timedelta, UTC, date
from zoneinfo import ZoneInfo
import json
from healthtracker.application.chart_serialization import PreparedChartData
import pytest
from test_chart_projection import chart, sample
from healthtracker.application.chart_projection import project_chart


@pytest.mark.parametrize('compact',[True,False])
def test_display_crosses_midnight_without_mutating_domain(compact):
    start=datetime(2026,11,1,23,tzinfo=UTC)
    data=chart([sample(start,7),sample(start+timedelta(hours=1),6,2),sample(start+timedelta(hours=2),4,3)],days=3,compact=compact)
    original=data.series[0].segments
    assert [s.indices for s in original]==[(1,2)]
    view=project_chart(data)['series'][0]
    assert view['segments']==[[0,1,2]]
    assert data.series[0].segments==original
    wire=json.loads(PreparedChartData.prepare(data).json_text)
    assert wire['series'][0]['segments']==[{'indices':[1,2]}]
    assert wire['view']['series'][0]['segments']==[[0,1,2]]
    assert [p['value'][1] for p in view['points']]==[7,6,4]
    assert view['points'][1]['value'][0]-view['points'][0]['value'][0]==3600


def test_display_keeps_null_long_gap_and_duplicate_boundaries():
    start=datetime(2026,11,1,23,tzinfo=UTC)
    cases=[([sample(start,7),sample(start+timedelta(hours=1),None,2),sample(start+timedelta(hours=2),4,3)],[]),
           ([sample(start,7),sample(start+timedelta(hours=6),4,2)],[]),
           ([sample(start,7),sample(start,4,2),sample(start+timedelta(hours=1),5,3)],[])]
    for samples,expected in cases:
        assert project_chart(chart(samples,days=3))['series'][0]['segments']==expected


@pytest.mark.parametrize('compact',[True,False])
def test_midnight_bridge_preserves_dst_fold_semantics(compact):
    zone=ZoneInfo('America/Havana')
    start=datetime(2025,11,2,3,tzinfo=UTC)  # 01.11 23:00, затем два раза 02.11 00:00.
    data=chart([sample(start,4),sample(start+timedelta(hours=1),7,2),sample(start+timedelta(hours=2),6,3)],
               start=date(2025,11,1),days=3,zone=zone,compact=compact)
    assert (start+timedelta(hours=2)).astimezone(zone).fold==1
    view=project_chart(data)['series'][0]
    assert view['segments']==([[0,1]] if compact else [[0,1,2]])
    assert view['points'][2]['value'][0]-view['points'][1]['value'][0]==(0 if compact else 3600)
