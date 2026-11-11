import json,re
from test_chart_channel import channel,js
from test_chart_rendering import seed,render

GRAPHICS="""(() => {const c=echarts.getInstanceByDom(document.getElementById('chart'));
const elements=(c.getOption().graphic||[]).flatMap(g=>g.elements||[]).filter(e=>/^(hour|date)-/.test(e.id));
const rect=c.getModel().getComponent('grid',0).coordinateSystem.getRect();
const extent=c.getModel().getComponent('xAxis',0).axis.scale.getExtent();
return JSON.stringify({elements,rect,extent,painted:c.getZr().storage.getDisplayList().filter(e=>e.style?.fill==='#e5e5e5' && /^\\d{1,2}$/.test(e.style?.text)).length});})()"""


def graphics(qtbot,w):return json.loads(js(qtbot,w,GRAPHICS))


def test_hours_above_dates_real_coordinates_and_zoom(channel,qtbot):
    w,*_=channel;seed(w);render(channel,qtbot,days=3,compact=False)
    result=graphics(qtbot,w);hours=[e for e in result['elements'] if e['id'].startswith('hour-')]
    dates=[e for e in result['elements'] if e['id'].startswith('date-')]
    assert len(hours)>=18 and len(dates)==3 and result['painted']==len(hours)
    assert all(re.fullmatch(r'\d{1,2}',e['style']['text']) and 0<=int(e['style']['text'])<=23 for e in hours)
    assert max(e['y'] for e in hours)<min(e['y'] for e in dates)
    expected=json.loads(js(qtbot,w,"JSON.stringify(echarts.getInstanceByDom(document.getElementById('chart')).convertToPixel({xAxisIndex:0},86400))"))
    assert abs(next(e['x'] for e in hours if e['id']=='hour-86400')-expected)<.01
    js(qtbot,w,'window.healthtrackerChannel.zoom(24,40)')
    result=graphics(qtbot,w)
    assert all(result['extent'][0]<=int(e['id'].split('-')[1])<=result['extent'][1] for e in result['elements'] if e['id'].startswith('hour-'))
    assert len([e['id'] for e in result['elements']])==len({e['id'] for e in result['elements']})
    js(qtbot,w,'window.healthtrackerChannel.zoom(24,33.4)')
    result=graphics(qtbot,w)
    assert all(e['x']+36<=result['rect']['x']+result['rect']['width'] for e in result['elements'] if e['id'].startswith('date-'))



def test_mode_switch_clears_hours_without_extra_band(channel,qtbot):
    w,*_=channel;seed(w)
    render(channel,qtbot)
    assert any(e['id'].startswith('hour-') for e in graphics(qtbot,w)['elements'])
    for days,compact in ((3,True),(10,True)):
        result=render(channel,qtbot,days=days,compact=compact)
        assert graphics(qtbot,w)['elements']==[]
        assert result['option']['grid'][0]['bottom']==95  # Есть слой сна, прежний отступ.
        assert result['option']['xAxis'][0]['axisLabel']['show']
