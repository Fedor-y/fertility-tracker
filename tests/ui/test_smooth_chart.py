"""Проверяется геометрия настоящего canvas ECharts, а не только значение smooth."""
from datetime import timedelta
from pathlib import Path
import json
import runpy
import pytest
from test_chart_channel import channel,js
from test_chart_rendering import picture
from test_chart_controls import settle_picture
from healthtracker.application.charts import ChartQuery
from healthtracker.domain.periods import DateRange
from healthtracker.domain.analytics import AnalysisContext
from healthtracker.domain.charts import SeriesKind

HELPER=runpy.run_path(str(Path(__file__).resolve().parents[1]/'manual/smooth_chart_preview.py'))
DAY,NOW=HELPER['DAY'],HELPER['NOW']


def draw(channel,qtbot,mode,broken=False):
    window,db,c,b,_=channel
    db.clock=lambda:NOW;window.chart_now=lambda:NOW
    HELPER['populate'](window.application,broken=broken)
    period=DateRange(DAY,DAY) if mode=='day' else DateRange(DAY-timedelta(days=7),DAY+timedelta(days=2)) if mode=='daily' else DateRange(DAY,DAY+timedelta(days=2))
    c.request(ChartQuery(period,AnalysisContext(NOW,NOW.tzinfo),visible_series=(SeriesKind.COGNITIVE,),compact=mode!='timeline',show_sleep=False,show_events=False))
    def ready():
        result=picture(qtbot,window)
        return b.state=='confirmed' and b.pending is not None and result['rendered']==b.pending.delivery_id
    qtbot.waitUntil(ready,timeout=15000);settle_picture(qtbot,window)
    return picture(qtbot,window)


CURVES="""(() => {
 const c=echarts.getInstanceByDom(document.getElementById('chart'));
 return JSON.stringify(c.getModel().getSeries().filter(m=>m.subType==='line').map(m=>{
   const p=c.getViewOfSeriesModel(m)._polyline, commands=[];
   p.buildPath({moveTo:(...p)=>commands.push({op:'M',p}),lineTo:(...p)=>commands.push({op:'L',p}),
     bezierCurveTo:(...p)=>commands.push({op:'C',p})},p.shape);
   const y=c.getModel().getComponent('yAxis',0).axis;
   return {commands,zero:y.toGlobalCoord(y.dataToCoord(0)),ten:y.toGlobalCoord(y.dataToCoord(10))};
 }));
})()"""


@pytest.mark.parametrize('mode',['day','compact','timeline','daily'])
def test_real_bezier_controls_and_samples_never_overshoot(channel,qtbot,mode):
    window,*_=channel
    result=draw(channel,qtbot,mode)
    lines=[s for s in result['series'] if s['type']=='line']
    assert lines and all(s['smooth']==0.3 and s['smoothMonotone']=='x' and s['connectNulls'] is False for s in lines)
    curves=json.loads(js(qtbot,window,CURVES));count=0
    for curve in curves:
        previous=None
        for command in curve['commands']:
            points=command['p']
            if command['op']=='C':
                count+=1
                end=points[-2:]
                left,right=sorted((previous[0],end[0]))
                assert left-1e-4<=points[0]<=points[2]<=right+1e-4
                low,high=sorted((previous[1],end[1]))
                assert low-1e-4<=points[1]<=high+1e-4
                assert low-1e-4<=points[3]<=high+1e-4
                for step in range(21):
                    t=step/20;u=1-t
                    y=u**3*previous[1]+3*u*u*t*points[1]+3*u*t*t*points[3]+t**3*end[1]
                    assert curve['ten']-1e-3<=y<=curve['zero']+1e-3
                previous=end
            else:previous=points[-2:]
    assert count>0


def test_three_days_are_one_display_curve_with_original_real_points(channel,qtbot):
    result=draw(channel,qtbot,'timeline')
    lines=[s for s in result['series'] if s['type']=='line']
    assert len(lines)==1 and len(lines[0]['data'])==72
    values=[p['value'] for p in lines[0]['data']]
    assert all(b[0]-a[0]==3600 for a,b in zip(values,values[1:]))
    assert values[23][1]==HELPER['PROFILE'][23]
    assert values[24][1]==HELPER['PROFILE'][2]
    scatter=next(s for s in result['series'] if s['type']=='scatter')
    assert [p['value'] for p in scatter['data']]==values
    assert scatter['symbolSize']<7
    assert result['option']['dataZoom'][0]['filterMode']=='none'


def test_display_curve_and_fill_stop_at_real_breaks(channel,qtbot):
    result=draw(channel,qtbot,'timeline',broken=True)
    lines=[s for s in result['series'] if s['type']=='line']
    for line in lines:
        values=[p['value'] for p in line['data']]
        assert all(0<b[0]-a[0]<=3*3600 for a,b in zip(values,values[1:]))
        assert not any(a[0]<47*3600<b[0] for a,b in zip(values,values[1:]))
        assert all(x!=27*3600 for x,y in values)  # Совпадающие UTC-точки не соединяются.
    assert len(lines)>=3
    assert all(s['areaStyle']['origin']==0 for s in lines)

    # DAILY: отсутствие целой даты не становится мостом после сглаживания.
    window,_,c,b,_=channel
    c.request(ChartQuery(DateRange(DAY-timedelta(days=7),DAY+timedelta(days=2)),AnalysisContext(NOW,NOW.tzinfo),
        visible_series=(SeriesKind.COGNITIVE,),show_sleep=False,show_events=False))
    def ready_daily():
        current=picture(qtbot,window)
        return b.state=='confirmed' and b.pending is not None and current['rendered']==b.pending.delivery_id
    qtbot.waitUntil(ready_daily,timeout=15000)
    daily=[s for s in picture(qtbot,window)['series'] if s['type']=='line']
    assert len(daily)==2
    assert all(b['value'][0]-a['value'][0]==1 for s in daily for a,b in zip(s['data'],s['data'][1:]))
