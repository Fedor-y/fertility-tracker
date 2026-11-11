"""Штатный fullscreen Qt/Wayland, без управления панелями Plasma."""
from PySide6.QtCore import Qt,QSettings
from test_chart_channel import channel,js
from test_smooth_chart import draw
from healthtracker.presentation.main_window import MainWindow


def test_f11_escape_button_restore_normal_and_maximized(channel,qtbot):
    w,*_=channel
    available=w.screen().availableGeometry()
    width,height=min(900,available.width()-40),min(650,available.height()-80)
    w.showNormal();w.resize(width,height)
    qtbot.waitUntil(lambda:w.isVisible() and not w.isMaximized() and w.width()==width and w.height()==height)
    old=w.size()
    qtbot.keyClick(w,Qt.Key.Key_F11)
    qtbot.waitUntil(w.isFullScreen)
    assert w.fullscreen_escape.isEnabled() and 'Выйти' in w.fullscreen_button.toolTip()
    qtbot.keyClick(w,Qt.Key.Key_F11)
    qtbot.waitUntil(lambda:not w.isFullScreen())
    qtbot.waitUntil(lambda:w.size()==old)
    w.showMaximized();qtbot.waitUntil(w.isMaximized)
    w.fullscreen_button.click();qtbot.waitUntil(w.isFullScreen)
    qtbot.keyClick(w,Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda:w.isMaximized() and not w.isFullScreen())
    assert not w.fullscreen_escape.isEnabled()
    w.chart_settings_popup.show_for_anchor()
    combo=w.chart_controls.period;combo.showPopup();qtbot.waitUntil(combo.view().isVisible)
    qtbot.keyClick(combo.view(),Qt.Key.Key_Escape)
    assert not combo.view().isVisible() and not w.isFullScreen()


def test_fullscreen_keeps_graph_zoom_period_and_sidebar_animation(channel,qtbot):
    w,_,controller,bridge,_=channel
    draw(channel,qtbot,'timeline')
    delivery=bridge.pending.delivery_id;view=w.chart
    expression='JSON.stringify(echarts.getInstanceByDom(document.getElementById("chart")).getOption().dataZoom.map(z=>[z.start,z.end]))'
    js(qtbot,w,'window.healthtrackerChannel.zoom(20,65)');zoom=js(qtbot,w,expression)
    w.fullscreen_button.click();qtbot.waitUntil(w.isFullScreen)
    w.sidebar_toggle.click();qtbot.waitUntil(lambda:w.sidebar.width()==56)
    qtbot.waitUntil(lambda:js(qtbot,w,'(() => {const r=window.healthtrackerChannel.rendering();return r.width===r.domWidth && r.height===r.domHeight;})()'))
    assert w.chart is view and bridge.pending.delivery_id==delivery
    assert js(qtbot,w,expression)==zoom
    # F11 must also work while WebEngine has keyboard focus.
    w.chart.setFocus();qtbot.keyClick(w.chart,Qt.Key.Key_F11)
    qtbot.waitUntil(lambda:not w.isFullScreen())
    assert w.sidebar_collapsed and w.sidebar.width()==56
    assert js(qtbot,w,expression)==zoom
    assert bridge.pending.delivery_id==delivery


def test_close_fullscreen_reopens_previous_window_mode(qtbot,tmp_path):
    settings=QSettings(str(tmp_path/'window.ini'),QSettings.Format.IniFormat)
    for maximized in (False,True):
        w=MainWindow(settings=settings,start_chart=False);qtbot.addWidget(w);w.show()
        w.showNormal();w.resize(850,600)
        if maximized:w.showMaximized();qtbot.waitUntil(w.isMaximized)
        w.toggle_fullscreen();qtbot.waitUntil(w.isFullScreen);w.close()
        qtbot.waitUntil(lambda:not w.isVisible())
        other=MainWindow(settings=settings,start_chart=False);qtbot.addWidget(other);other.show()
        qtbot.waitUntil(lambda:other.isMaximized()==maximized)
        assert not other.isFullScreen()
        other.close()
