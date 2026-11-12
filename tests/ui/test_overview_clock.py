from datetime import datetime
from PySide6.QtCore import Qt
from healthtracker.presentation.overview_clock import OverviewClock
from test_chart_channel import channel


def test_clock_english_month_midnight_and_year(qtbot):
    moment=[datetime(2026,5,11,16,38)]
    clock=OverviewClock(now_provider=lambda:moment[0]);qtbot.addWidget(clock);clock.show()
    assert clock.date_label.text()=='11 MAY 2026'
    assert clock.time_label.text()=='16:38'
    moment[0]=datetime(2027,1,1,0,0);clock.refresh()
    assert clock.date_label.text()=='01 JAN 2027' and clock.time_label.text()=='00:00'
    clock.hide();assert not clock.timer.isActive()
    clock.show();assert clock.timer.isActive()


def test_clock_centered_only_on_overview_without_chart_request(channel,qtbot):
    w,_,c,b,_=channel
    clock=w.overview_clock
    qtbot.waitUntil(clock.isVisible)
    delivery=b.pending
    clock.refresh();clock.refresh()
    assert b.pending is delivery
    center=clock.mapTo(w,clock.rect().center()).x()
    assert abs(center-w.pages.mapTo(w,w.pages.rect().center()).x())<=2
    w.navigation.setCurrentRow(2)
    assert not clock.isVisible() and not clock.timer.isActive()
    w.navigation.setCurrentRow(0)
    assert clock.isVisible() and clock.timer.isActive()
