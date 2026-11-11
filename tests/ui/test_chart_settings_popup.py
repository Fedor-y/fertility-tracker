"""Панель использует прежние контролы; вложенные popup остаются в стеке Qt."""
from datetime import UTC,date,datetime
from PySide6.QtCore import Qt,QDate,QPoint
from test_chart_channel import channel,js
from test_chart_controls import wait
from test_chart_rendering import seed
from test_smooth_chart import draw
from healthtracker.domain.periods import QuickPeriod


def test_gear_toggles_escape_outside_and_preserves_chart(channel,qtbot):
    w,_,c,b,_=channel;draw(channel,qtbot,'timeline')
    delivery=b.pending.delivery_id;old_height=w.chart.height()
    assert not w.chart_settings_popup.isVisible() and not w.chart_controls.isVisible()
    assert w.chart_settings_button.text()=='' and not w.chart_settings_button.icon().isNull()
    w.chart_settings_button.click();qtbot.waitUntil(w.chart_settings_popup.isVisible)
    assert w.chart_controls.isVisible() and w.chart_settings_button.isChecked()
    image=w.chart_settings_popup.grab().toImage()
    color=image.pixelColor(image.width()-10,40)
    assert color.alpha()==255 and color.red()==11
    assert w.chart.height()==old_height
    w.chart_settings_button.click();assert not w.chart_settings_popup.isVisible()
    w.chart_settings_button.click();qtbot.keyClick(w.chart_settings_popup,Qt.Key.Key_Escape)
    assert not w.chart_settings_popup.isVisible() and not w.chart_settings_button.isChecked()
    w.chart_settings_button.click()
    # Клик вне прямоугольника панели закрывает её.
    qtbot.mouseClick(w.chart_settings_popup,Qt.MouseButton.LeftButton,pos=w.chart_settings_popup.rect().topLeft()-QPoint(20,20))
    qtbot.waitUntil(lambda:not w.chart_settings_popup.isVisible())
    w.chart_settings_button.click()
    qtbot.mouseClick(w.chart,Qt.MouseButton.LeftButton,pos=w.chart.rect().bottomRight()-QPoint(10,10))
    assert not w.chart_settings_popup.isVisible()
    assert b.pending.delivery_id==delivery
    w.toggle_fullscreen();qtbot.waitUntil(w.isFullScreen)
    w.chart_settings_button.click();qtbot.keyClick(w.chart_settings_popup,Qt.Key.Key_Escape)
    assert not w.chart_settings_popup.isVisible() and w.isFullScreen()
    w.leave_fullscreen()


def test_nested_combo_dates_and_layers_stay_in_panel(channel,qtbot):
    w,_,c,b,_=channel;seed(w)
    w.chart_now=lambda:datetime(2026,11,4,12,tzinfo=UTC)
    w.chart_settings_button.click();p=w.chart_controls;popup=w.chart_settings_popup
    combo=p.period;combo.showPopup();qtbot.waitUntil(combo.view().isVisible)
    index=combo.model().index(combo.findData('custom'),0)
    qtbot.mouseClick(combo.view().viewport(),Qt.MouseButton.LeftButton,pos=combo.view().visualRect(index).center())
    assert popup.isVisible() and p.custom.isVisible()
    qtbot.mouseClick(p.start,Qt.MouseButton.LeftButton,pos=QPoint(p.start.width()-8,p.start.height()//2))
    qtbot.waitUntil(p.start.calendarWidget().isVisible)
    assert popup.isVisible()
    qtbot.keyClick(p.start.calendarWidget(),Qt.Key.Key_Escape)
    assert popup.isVisible()
    p.start.setDate(QDate(2026,11,1));p.end.setDate(QDate(2026,11,3))
    qtbot.mouseClick(p.apply,Qt.MouseButton.LeftButton);wait(qtbot,w)
    assert c.last_query.period.start==date(2026,11,1) and c.last_query.period.end==date(2026,11,3)
    assert popup.isVisible()
    p.mode.showPopup();qtbot.waitUntil(p.mode.view().isVisible)
    qtbot.keyClick(p.mode.view(),Qt.Key.Key_Down);qtbot.keyClick(p.mode.view(),Qt.Key.Key_Return)
    assert popup.isVisible()
    p.details_button.click();assert p.details.isVisible()
    saved=p.preferences();popup.hide();w.chart_settings_button.click()
    assert p.preferences()==saved and p.start.date()==QDate(2026,11,1)
    assert p.details.isVisible()
    bounds=popup.screen().availableGeometry()
    qtbot.waitUntil(lambda:w.rect().contains(popup.geometry()))
