"""Небольшая визуальная регрессия без изменения временной семантики данных."""
from datetime import date, timedelta
from zoneinfo import ZoneInfo
import json
import re

import pytest
from test_chart_channel import channel, js
from test_chart_rendering import seed, render, picture, MOMENT
from healthtracker.domain.charts import SeriesKind
from healthtracker.domain.catalogs import SymptomStatus


@pytest.mark.parametrize('days,compact', [(1,True),(3,True),(3,False),(10,True)])
def test_black_hole_axes_and_labels_for_all_modes(channel,qtbot,days,compact):
    window,db,c,b,_=channel
    seed(window)
    result=render(channel,qtbot,days=days,compact=compact)
    assert all(not axis['splitLine']['show'] for axis in result['option']['xAxis']+result['option']['yAxis'])
    marks=[s.get('markLine',{}).get('data',[]) for s in result['series']]
    assert sum(map(len,marks)) == (days-1 if days==3 else 0)
    labels=json.loads(js(qtbot,window,"""(() => {
        const c=echarts.getInstanceByDom(document.getElementById('chart'));
        const a=c.getOption().xAxis[0];
        return JSON.stringify(Array.from({length:Math.floor((a.max-a.min)/a.interval)+1},(_,i)=>a.axisLabel.formatter(a.min+i*a.interval)).filter(Boolean));
    })()"""))
    assert labels
    pattern=r'\d{2}:\d{2}' if days==1 else r'\d{2}\.\d{2}'
    assert all(re.fullmatch(pattern,label) for label in labels)
    assert len(labels)<=15


@pytest.mark.parametrize('day',[date(2026,3,29),date(2026,10,25)])
def test_label_format_keeps_dst_coordinates(channel,qtbot,day):
    window,_,_,_,_=channel
    seed(window,day=day)
    result=render(channel,qtbot,start=day,zone=ZoneInfo('Europe/Berlin'))
    point=next(s for s in result['series'] if s['id']=='cognitive-points')['data'][0]
    # Координата UTC взята из готовой проекции, renderer не переставляет точку.
    assert result['option']['xAxis'][0]['max'] in (23*3600,25*3600)
    assert point['value'][0] == (13*3600 if day.month==3 else 14*3600)
    assert any('UTC ' in line for line in point['lines'])


def test_fill_only_existing_primary_segments_and_single_point(channel,qtbot):
    window,_,_,_,_=channel
    seed(window)
    one=render(channel,qtbot,kinds=(SeriesKind.COGNITIVE,))
    assert not any(s['type']=='line' for s in one['series'])
    obs=window.application.observations
    with obs.storage.read_snapshot() as session:
        assessment=session.cognitive.all()[0].value.assessment
    obs.save_cognitive(assessment,MOMENT+timedelta(hours=1))
    obs.save_physical(score=4,observed_at=MOMENT+timedelta(hours=1),symptom_status=SymptomStatus.UNKNOWN,symptoms=())
    many=render(channel,qtbot)
    lines=[s for s in many['series'] if s['type']=='line']
    assert lines
    assert all(s['smooth'] == 0.3 and s['connectNulls'] is False for s in lines)
    fills=[s for s in lines if s.get('areaStyle')]
    assert all(s['id'].startswith('cognitive-') for s in fills)
    assert fills and fills[0]['areaStyle']['color']['colorStops'][-1]['color']=='rgba(242,242,242,0)'


def test_compact_overview_zoom_and_transient_notice(channel,qtbot):
    window,_,_,_,_=channel
    seed(window)
    render(channel,qtbot)
    assert not window.page_subtitle.isVisible()
    assert not window.chart_controls.info.isVisible()
    window._poll_chart_zoom()
    qtbot.waitUntil(lambda:not window.chart_controls.reset_zoom.isVisible())
    window.chart_settings_button.click()
    js(qtbot,window,'window.healthtrackerChannel.zoom(20,70)')
    window._poll_chart_zoom()
    qtbot.waitUntil(window.chart_controls.reset_zoom.isVisible)
    window.resize(850,600)
    qtbot.waitUntil(lambda:picture(qtbot,window)['option']['dataZoom'][0]['start']==20)
    assert picture(qtbot,window)['option']['dataZoom'][0]['end']==70
    window.chart_controls.reset_zoom.click()
    qtbot.waitUntil(lambda:window.chart.bridge.state=='confirmed')
    window.saved_notice_timer.setInterval(30)
    window._observation_saved('mood',1)
    assert window.storage_status.isVisible() and window.last_saved_action.isEnabled()
    qtbot.waitUntil(lambda:not window.storage_status.isVisible())
    assert window.last_saved_action.data()=='mood:1'
