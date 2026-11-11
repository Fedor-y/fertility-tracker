"""Точечные проверки стандартного popup и границ дней настоящего ECharts."""
import json
from datetime import date
from zoneinfo import ZoneInfo
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListView,QStyle
from test_chart_channel import channel,js
from test_chart_rendering import seed,render


def test_combo_popup_dark_standard_view_and_button_states(channel,qtbot):
    window,*_=channel
    window.chart_settings_popup.show_for_anchor()
    for combo in (window.chart_controls.period,window.chart_controls.mode):
        assert isinstance(combo.view(),QListView)
        assert not combo.style().styleHint(QStyle.StyleHint.SH_ComboBox_Popup,None,combo)
        combo.showPopup();qtbot.waitUntil(combo.view().isVisible)
        image=combo.view().window().grab().toImage()
        # Верхний и нижний край должны оставаться тёмными, без светлых полос.
        for y in (0,2,image.height()-3,image.height()-1):
            color=image.pixelColor(image.width()//2,y)
            assert max(color.red(),color.green(),color.blue())<65
        combo.hidePopup()
    assert window.font().weight()==500
    button=window.add_button
    for event in ('hover','press','release'):
        if event=='hover':qtbot.mouseMove(button,button.rect().center())
        elif event=='press':qtbot.mousePress(window.chart_controls.details_button,Qt.MouseButton.LeftButton)
        else:qtbot.mouseRelease(window.chart_controls.details_button,Qt.MouseButton.LeftButton)
    assert button.isEnabled()


@pytest.mark.parametrize('compact',[True,False])
def test_midnight_markers_dst_zoom_and_continuity(channel,qtbot,compact):
    window,*_=channel
    day=date(2026,10,31);zone=ZoneInfo('America/New_York')
    seed(window,day=day)
    result=render(channel,qtbot,start=day,days=3,zone=zone,compact=compact)
    marks=[m['xAxis'] for s in result['series'] for m in s.get('markLine',{}).get('data',[])]
    assert marks==([86400,172800] if compact else [86400,176400])
    lines=[s for s in result['series'] if s['type']=='line']
    assert all(s['smooth']==0.3 and s['smoothMonotone']=='x' for s in lines)
    js(qtbot,window,'window.healthtrackerChannel.zoom(20,70)')
    actual=json.loads(js(qtbot,window,"JSON.stringify(echarts.getInstanceByDom(document.getElementById('chart')).getOption().series.flatMap(s=>(s.markLine?.data||[]).map(m=>m.xAxis)))"))
    assert actual==marks
