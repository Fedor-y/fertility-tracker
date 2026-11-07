"""Крайние значения и видимость допустимых сегментов при zoom — реальный ECharts."""
from datetime import timedelta
from pathlib import Path
import json
import runpy

import pytest
from test_chart_channel import channel, js
from test_chart_rendering import picture
from test_chart_controls import settle_picture
from healthtracker.application.charts import ChartQuery
from healthtracker.domain.analytics import AnalysisContext
from healthtracker.domain.charts import SeriesKind
from healthtracker.domain.periods import DateRange

HELPER=runpy.run_path(str(Path(__file__).resolve().parents[1]/'manual/chart_edges_preview.py'))
DAY,NOW=HELPER['DAY'],HELPER['NOW']


@pytest.fixture
def edges(channel):
    window,db,*_=channel
    db.clock=lambda:NOW
    window.chart_now=lambda:NOW
    HELPER['populate'](window.application)
    return channel


def draw(edges,qtbot,days=1,compact=True,kinds=tuple(SeriesKind),single=False):
    window,_,c,b,_=edges
    day=NOW.date() if single else DAY
    c.request(ChartQuery(DateRange(day-timedelta(days=days-1),day),AnalysisContext(NOW,NOW.tzinfo),
        visible_series=kinds,compact=compact,show_sleep=False,show_events=False))
    def ready():
        result=picture(qtbot,window)
        return b.state=='confirmed' and b.pending is not None and result['rendered']==b.pending.delivery_id
    qtbot.waitUntil(ready,timeout=15000)
    settle_picture(qtbot,window)
    return picture(qtbot,window)


def light_at(qtbot,window,x,y):
    point=json.loads(js(qtbot,window,f"JSON.stringify(echarts.getInstanceByDom(document.getElementById('chart')).convertToPixel({{xAxisIndex:0,yAxisIndex:0}},[{x},{y}]))"))
    image=window.chart.grab().toImage()
    dpr=image.devicePixelRatio()
    px,py=round(point[0]*dpr),round(point[1]*dpr)
    radius=max(2,round(2*dpr))
    return any(min(image.pixelColor(i,j).red(),image.pixelColor(i,j).green(),image.pixelColor(i,j).blue())>160
        for i in range(max(0,px-radius),min(image.width(),px+radius+1))
        for j in range(max(0,py-radius),min(image.height(),py+radius+1)))


@pytest.mark.parametrize('days,compact',[(1,True),(3,True),(3,False),(10,True)])
def test_score_edges_have_display_margin_in_all_modes(edges,qtbot,days,compact):
    window,*_=edges
    result=draw(edges,qtbot,days,compact)
    geometry=json.loads(js(qtbot,window,HELPER['GEOMETRY']))
    rect=geometry['grid']
    assert geometry['zero'][1] < rect['y']+rect['height']-4
    assert geometry['ten'][1] > rect['y']+4
    assert result['option']['xAxis'][0]['axisLine']['onZero'] is False
    assert not result['option']['yAxis'][0]['splitLine']['show']
    assert all(0<=p['value'][1]<=10 for s in result['series'] if s['type']=='scatter' for p in s['data'])


def test_real_pixels_of_edge_lines_and_real_gaps(edges,qtbot):
    window,*_=edges
    result=draw(edges,qtbot,kinds=(SeriesKind.COGNITIVE,))
    assert light_at(qtbot,window,6.5*3600,0)  # Между точками, не пиксель маркера.
    assert light_at(qtbot,window,1.5*3600,10)
    assert not light_at(qtbot,window,14*3600,8.5)  # Специальный ответ без числа.
    assert not light_at(qtbot,window,18.5*3600,2)  # Настоящий пропуск >3 ч.
    lines=[s for s in result['series'] if s['type']=='line']
    assert [len(s['data']) for s in lines]==[14,2,3]
    assert all(s['connectNulls'] is False and s['smooth'] == 0.3 for s in lines)


def test_zoom_and_pan_between_samples_keep_continuous_segment(edges,qtbot):
    window,*_=edges
    result=draw(edges,qtbot,kinds=(SeriesKind.COGNITIVE,))
    original=[s['data'] for s in result['series'] if s['type']=='line']
    for start,end,x,y in ((13.333333,15.833333,3.5*3600,7),(26,28,6.5*3600,0)):
        js(qtbot,window,f'window.healthtrackerChannel.zoom({start},{end})')
        settle_picture(qtbot,window)
        after=picture(qtbot,window)
        assert after['option']['dataZoom'][0]['filterMode']=='none'
        assert [s['data'] for s in after['series'] if s['type']=='line']==original
        assert light_at(qtbot,window,x,y)
    js(qtbot,window,'window.healthtrackerChannel.zoom(56,61)')
    settle_picture(qtbot,window)
    assert not light_at(qtbot,window,14*3600,8.5)


def test_single_zero_and_secondary_selection(edges,qtbot):
    window,*_=edges
    single=draw(edges,qtbot,kinds=(SeriesKind.COGNITIVE,),single=True)
    assert not any(s['type']=='line' for s in single['series'])
    assert light_at(qtbot,window,12*3600,0)
    selected=draw(edges,qtbot,kinds=(SeriesKind.PHYSICAL,))
    line=next(s for s in selected['series'] if s['type']=='line')
    assert line['lineStyle']['color']=='#f0f0f0' and line['lineStyle']['opacity']==1
    assert light_at(qtbot,window,6.5*3600,10)
