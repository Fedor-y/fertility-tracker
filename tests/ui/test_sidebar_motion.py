"""Смена направления без скачка и усиленная заливка только допустимых сегментов."""
import json
from PySide6.QtCore import QAbstractAnimation
from test_chart_channel import channel,js
from test_smooth_chart import draw


def test_sidebar_animation_reverses_from_current_width_and_settles_chart(channel,qtbot):
    w,_,_,bridge,_=channel
    draw(channel,qtbot,'timeline')
    js(qtbot,w,'window.healthtrackerChannel.zoom(25,65)')
    expression='JSON.stringify(echarts.getInstanceByDom(document.getElementById("chart")).getOption().dataZoom.map(z=>[z.start,z.end]))'
    zoom=js(qtbot,w,expression);delivery=bridge.pending.delivery_id
    w.sidebar_toggle.click()
    qtbot.waitUntil(lambda:60<w.sidebar.width()<170)
    current=w.sidebar.width()
    w.sidebar_toggle.click()
    assert abs(w.sidebar.width()-current)<=1
    assert w.sidebar_animation.startValue()==current
    qtbot.waitUntil(lambda:w.sidebar.width()==176 and w.sidebar_animation.state()==QAbstractAnimation.State.Stopped)
    for _ in range(5):w.sidebar_toggle.click()
    qtbot.waitUntil(lambda:w.sidebar.width()==56 and w.sidebar_animation.state()==QAbstractAnimation.State.Stopped)
    assert not w.navigation.item(0).text()
    qtbot.waitUntil(lambda:js(qtbot,w,'window.healthtrackerChannel.rendering().width === window.healthtrackerChannel.rendering().domWidth'))
    assert js(qtbot,w,expression)==zoom
    assert bridge.pending.delivery_id==delivery


def test_gradient_stops_and_real_gaps_remain(channel,qtbot):
    result=draw(channel,qtbot,'timeline',broken=True)
    lines=[s for s in result['series'] if s['type']=='line']
    assert len(lines)>1
    for line in lines:
        stops=line['areaStyle']['color']['colorStops']
        assert [s['offset'] for s in stops]==[0,0.3,0.6,1]
        assert [s['color'] for s in stops]==['rgba(242,242,242,0.24)','rgba(242,242,242,0.11)','rgba(242,242,242,0.05)','rgba(242,242,242,0)']
        assert line['smooth']==0.3 and line['connectNulls'] is False
        assert all(0<b['value'][0]-a['value'][0]<=10800 for a,b in zip(line['data'],line['data'][1:]))
