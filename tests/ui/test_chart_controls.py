from dataclasses import replace
from datetime import UTC,date,datetime,timedelta
import json,os
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtCore import QDate,Qt
from test_chart_channel import channel,js,snapshot
from test_chart_rendering import picture,seed
from healthtracker.domain.charts import ChartMode,SeriesKind
from healthtracker.domain.periods import QuickPeriod

NOW=datetime(2026,11,4,12,tzinfo=UTC)

@pytest.fixture
def controls(channel,qtbot):
    window,db,c,b,clock=channel
    window.chart_now=lambda:NOW
    seed(window,day=date(2026,11,1))
    panel=window.chart_controls
    window._request_controls()  # Начальный запрос, без нажатия скрытого сброса.
    wait(qtbot,window)
    return window,db,c,b,panel


def wait(qtbot,window):
    b=window.chart.bridge;c=window.chart_controller
    qtbot.waitUntil(lambda:b.state=='confirmed' and c.last_request_id==c.requests.latest_id,timeout=20000)
    def current_picture():
        rendered=picture(qtbot,window)['rendered']  # JS допускает события Qt/commit предпочтений.
        return (b.state=='confirmed' and b.pending is not None
                and rendered==b.pending.delivery_id and c.last_request_id==c.requests.latest_id)
    qtbot.waitUntil(current_picture,timeout=15000)
    period=c.last_query.period
    caption = f'{period.start:%d.%m.%Y}' if period.start == period.end else f'{period.start:%d.%m.%Y} — {period.end:%d.%m.%Y}'
    assert picture(qtbot,window)['option']['title'][1]['text'] == caption


def settle_picture(qtbot,window):
    qtbot.waitUntil(lambda:(lambda r:r['width']==r['domWidth'] and r['height']==r['domHeight'])(picture(qtbot,window)))
    js(qtbot,window,'window.__captureReady=false;requestAnimationFrame(()=>requestAnimationFrame(()=>{window.__captureReady=true;}));')
    qtbot.waitUntil(lambda:js(qtbot,window,'window.__captureReady') is True,timeout=10000)


def choose(qtbot,combo,key):
    index=combo.findData(key)
    assert index>=0
    combo.setFocus()
    qtbot.keyClick(combo,Qt.Key.Key_Home)
    for _ in range(index): qtbot.keyClick(combo,Qt.Key.Key_Down)
    assert combo.currentData()==key


def custom(qtbot,panel,start,end):
    choose(qtbot,panel.period,'custom')
    panel.start.setDate(QDate(start));panel.end.setDate(QDate(end))
    qtbot.mouseClick(panel.apply,Qt.MouseButton.LeftButton)


@pytest.mark.parametrize('key,start,end',[
    (QuickPeriod.DAY,date(2026,11,4),date(2026,11,4)),
    (QuickPeriod.SEVEN_DAYS,date(2026,10,29),date(2026,11,4)),
    (QuickPeriod.TEN_DAYS,date(2026,10,26),date(2026,11,4)),
    (QuickPeriod.MONTH,date(2026,11,1),date(2026,11,30)),
    (QuickPeriod.PREVIOUS_MONTH,date(2026,10,1),date(2026,10,31)),
    (QuickPeriod.YEAR,date(2026,1,1),date(2026,12,31)),
])
def test_each_quick_period_via_keyboard_and_real_webchannel(controls,qtbot,key,start,end):
    window,_,c,b,panel=controls
    choose(qtbot,panel.period,QuickPeriod.SEVEN_DAYS if key is QuickPeriod.DAY else QuickPeriod.DAY)
    old=c.requests.latest_id
    choose(qtbot,panel.period,key)
    assert c.requests.latest_id!=old
    wait(qtbot,window)
    assert (c.last_query.period.start,c.last_query.period.end)==(start,end)
    assert snapshot(qtbot,window)['candidate']['data']['period']=={'start':start.isoformat(),'end':end.isoformat()}
    assert c.last_result.analytics.statistics.calendar_days==(end-start).days+1


def test_custom_invalid_and_future_periods(controls,qtbot):
    window,_,c,b,panel=controls
    custom(qtbot,panel,date(2024,2,1),date(2024,2,29));wait(qtbot,window)
    assert c.last_query.period.calendar_days==29
    assert c.last_query.period.end==date(2024,2,29)
    custom(qtbot,panel,date(2026,12,10),date(2026,12,1))
    assert panel.error.isVisible() and c.requests.latest_id is None
    assert panel.start.date().toPython()==date(2026,12,10)
    custom(qtbot,panel,date(2026,12,1),date(2026,12,3));wait(qtbot,window)
    assert c.last_result.analytics.statistics.incomplete
    assert 'не завершён' in panel.info.text()
    assert all(m['count']==0 for m in picture(qtbot,window)['models'])


@pytest.mark.parametrize('kind',list(SeriesKind))
def test_each_series_checkbox_changes_echarts(controls,qtbot,kind):
    window,_,c,b,panel=controls
    choose(qtbot,panel.period,QuickPeriod.SEVEN_DAYS)
    panel.details_button.setChecked(True)
    check=panel.series[kind]
    before=check.isChecked()
    old=c.requests.latest_id
    check.setFocus();qtbot.keyClick(check,Qt.Key.Key_Space)
    assert check.isChecked()!=before and c.requests.latest_id!=old
    wait(qtbot,window)
    expected={k.value+'-points' for k,v in panel.series.items() if v.isChecked()}
    assert {m['id'] for m in picture(qtbot,window)['models'] if m['type']=='scatter'}==expected
    check.setFocus();qtbot.keyClick(check,Qt.Key.Key_Space);wait(qtbot,window)
    assert check.isChecked()==before


def test_mode_choices_and_parameters_survive_period_changes(controls,qtbot):
    window,_,c,b,panel=controls
    choose(qtbot,panel.period,QuickPeriod.SEVEN_DAYS)
    assert [panel.mode.itemData(i) for i in range(panel.mode.count())]==[ChartMode.COMPACT,ChartMode.TIMELINE]
    choose(qtbot,panel.mode,ChartMode.TIMELINE);wait(qtbot,window)
    before=c.last_query
    panel.series[SeriesKind.MOOD].setChecked(True)
    panel.layers['sleep'].setChecked(False)
    choose(qtbot,panel.period,QuickPeriod.TEN_DAYS);wait(qtbot,window)
    assert panel.mode.count()==1 and panel.mode.currentData()==ChartMode.DAILY and not panel.mode.isEnabled()
    assert c.last_query.compact is False and SeriesKind.MOOD in c.last_query.visible_series and not c.last_query.show_sleep
    choose(qtbot,panel.period,QuickPeriod.DAY);wait(qtbot,window)
    assert panel.mode.currentData()==ChartMode.DAY and not panel.mode.isEnabled()
    choose(qtbot,panel.period,QuickPeriod.SEVEN_DAYS);wait(qtbot,window)
    assert panel.mode.currentData()==ChartMode.TIMELINE
    assert c.last_query.period==before.period and c.last_query.line_gap_hours==before.line_gap_hours
    assert panel.mode.findData(ChartMode.DAILY)==-1


@pytest.mark.parametrize('layer',['sleep','meals','gym','events'])
def test_layer_controls_reach_actual_rendering(controls,qtbot,layer):
    window,_,c,b,panel=controls
    choose(qtbot,panel.period,QuickPeriod.SEVEN_DAYS);wait(qtbot,window)
    baseline=c.last_result.analytics
    panel.layers[layer].setChecked(False);wait(qtbot,window)
    view=snapshot(qtbot,window)['candidate']['data']['view']
    assert c.last_result.analytics==baseline
    if layer=='sleep': assert not any(m['id']=='sleep' for m in picture(qtbot,window)['models'])
    elif layer=='events': assert view['events']==view['nonnumeric']==[]
    else: assert all(s['kind']!=layer for e in view['events'] for s in e['sources'])
    panel.layers[layer].setChecked(True);wait(qtbot,window)
    assert panel.layers['meals'].isChecked() and panel.layers['gym'].isChecked()


def test_combination_and_no_selected_series(controls,qtbot):
    window,_,c,b,panel=controls
    choose(qtbot,panel.period,QuickPeriod.SEVEN_DAYS)
    for kind,check in panel.series.items(): check.setChecked(kind in (SeriesKind.LEARNING,SeriesKind.STRESS))
    wait(qtbot,window)
    assert c.last_query.visible_series==(SeriesKind.LEARNING,SeriesKind.STRESS)
    for check in panel.series.values():check.setChecked(False)
    wait(qtbot,window)
    assert c.last_query.visible_series==()
    assert picture(qtbot,window)['option']['title'][0]['text']=='Показатели отключены'
    assert all(m['id']=='sleep' for m in picture(qtbot,window)['models'])


def test_calendar_clock_and_timezone_refresh_same_ui_state(controls,qtbot):
    from zoneinfo import ZoneInfo
    window,_,c,b,panel=controls
    now=[datetime(2026,12,31,23,30,tzinfo=UTC)]
    window.chart_now=lambda:now[0]
    window._check_chart_context();wait(qtbot,window)
    assert c.last_query.period.start==date(2026,12,31)
    c.zone_provider=lambda:ZoneInfo('Pacific/Kiritimati')
    old=c.requests.latest_id
    window._check_chart_context();wait(qtbot,window)
    assert c.requests.latest_id!=old and c.last_query.period.start==date(2027,1,1)
    assert c.last_query.context.zone==ZoneInfo('Pacific/Kiritimati')


def test_ui_custom_dst_has_23_hour_axis(controls,qtbot):
    from zoneinfo import ZoneInfo
    window,_,c,b,panel=controls
    c.zone_provider=lambda:ZoneInfo('Europe/Berlin')
    custom(qtbot,panel,date(2026,3,29),date(2026,3,29));wait(qtbot,window)
    assert snapshot(qtbot,window)['candidate']['data']['view']['axis']['max']==23*3600


def test_reload_keeps_controls_and_current_selection(controls,qtbot):
    window,_,c,b,panel=controls
    choose(qtbot,panel.period,QuickPeriod.SEVEN_DAYS)
    panel.series[SeriesKind.STRESS].setChecked(True)
    choose(qtbot,panel.mode,ChartMode.TIMELINE);wait(qtbot,window)
    query=c.last_query;page=b.pageId
    window.chart.reload()
    qtbot.waitUntil(lambda:b.pageId!=page and b.state=='confirmed',timeout=20000)
    wait(qtbot,window)
    assert c.last_query==query and panel.mode.currentData()==ChartMode.TIMELINE
    assert panel.series[SeriesKind.STRESS].isChecked()


def test_zoom_does_not_change_calendar_mode_and_reset_uses_current_controls(controls,qtbot):
    window,_,c,b,panel=controls
    choose(qtbot,panel.period,QuickPeriod.SEVEN_DAYS);wait(qtbot,window)
    before=c.last_query;request_id=c.requests.latest_id
    js(qtbot,window,'window.healthtrackerChannel.zoom(45,46)')
    zoomed=picture(qtbot,window)
    assert zoomed['option']['dataZoom'][0]['start']==45
    assert next(m for m in zoomed['models'] if m['id']=='sleep')['graphics']>=1
    assert next(m for m in zoomed['models'] if m['id']=='cognitive-points')['count']==len(next(s for s in zoomed['series'] if s['id']=='cognitive-points')['data'])
    assert next(s for s in zoomed['series'] if s['id']=='cognitive-points')['clip'] is True
    assert zoomed['option']['dataZoom'][0]['filterMode']=='none'
    assert c.last_query==before and c.requests.latest_id==request_id
    qtbot.mouseClick(panel.reset_zoom,Qt.MouseButton.LeftButton);wait(qtbot,window)
    assert c.last_query==before and c.requests.latest_id!=request_id
    assert picture(qtbot,window)['option']['dataZoom'][0]['start']==0


def test_controls_layout_screenshot_and_resize(controls,qtbot):
    window,_,c,b,panel=controls
    choose(qtbot,panel.period,QuickPeriod.SEVEN_DAYS);wait(qtbot,window)
    qtbot.mouseClick(panel.details_button,Qt.MouseButton.LeftButton)
    assert panel.details.isVisible()
    window.resize(900,650)
    path=Path('/tmp/healthtracker-controls-preview')/os.environ.get('QT_SCALE_FACTOR','1')
    path.mkdir(parents=True,exist_ok=True)
    settle_picture(qtbot,window)
    assert js(qtbot,window,'document.documentElement.scrollWidth <= document.documentElement.clientWidth')
    assert window.grab().save(str(path/'controls.png'))
    assert panel.details.verticalScrollBar().maximum()>=0
    panel.details_button.setChecked(False)
    settle_picture(qtbot,window)
    assert window.grab().save(str(path/'collapsed.png'))
    assert panel.mode.currentData()==ChartMode.COMPACT


@pytest.mark.parametrize('old_failure',[False,True])
def test_fast_ui_b_finishes_before_a_and_old_result_or_error_cannot_replace_b(controls,qtbot,old_failure):
    window,_,c,b,panel=controls
    actual=c.requests.preparation
    started,release=Event(),Event()
    class Gate:
        analytics=actual.analytics
        def prepare(self,query,checkpoint,snapshot_ready):
            if query.period.calendar_days==7 and SeriesKind.MOOD not in query.visible_series:
                result=actual.prepare(query,lambda:None,snapshot_ready)
                started.set()
                assert release.wait(5)
                if old_failure:raise RuntimeError('synthetic private details')
                return result
            return actual.prepare(query,checkpoint,snapshot_ready)
    c.requests.preparation=Gate()
    try:
        panel.period.setCurrentIndex(panel.period.findData(QuickPeriod.SEVEN_DAYS))
        old=c.requests.latest_id
        assert started.wait(2)
        panel.series[SeriesKind.MOOD].setChecked(True)
        wait(qtbot,window)
        fresh=b.pending.delivery_id
        assert c.requests.latest_id!=old
        release.set()
        qtbot.waitUntil(lambda:c.requests.idle)
        c.poll();b.poll()
        assert b.state=='confirmed' and picture(qtbot,window)['rendered']==fresh
        assert c.error is None and panel.series[SeriesKind.MOOD].isChecked()
    finally:release.set()


def test_chart_failure_and_retry_keep_persisted_preferences(controls,qtbot):
    window,db,c,b,panel=controls
    actual=c.requests.preparation
    panel.series[SeriesKind.STRESS].setChecked(True)
    panel.layers['sleep'].setChecked(False)
    p=window.preferences_controller
    qtbot.waitUntil(lambda: p.future is None and not p.dirty,timeout=10000)
    wait(qtbot,window)
    preferences=window.application.chart_preferences.load()
    previous=picture(qtbot,window)['rendered']
    class Failure:
        analytics=actual.analytics
        def prepare(self,*args):raise RuntimeError('synthetic private details')
    c.requests.preparation=Failure()
    choose(qtbot,panel.period,QuickPeriod.TEN_DAYS)
    qtbot.waitUntil(lambda:b.state=='error')
    assert panel.period.currentData()==QuickPeriod.TEN_DAYS
    assert panel.series[SeriesKind.STRESS].isChecked() and not panel.layers['sleep'].isChecked()
    assert picture(qtbot,window)['rendered']==previous
    with db.read_snapshot() as session:
        assert session.settings.get('visible_series') == [s.value for s in preferences.visible_series]
        assert session.settings.get('compact_mode') == preferences.compact_mode
    c.requests.preparation=actual
    qtbot.mouseClick(window.chart_retry,Qt.MouseButton.LeftButton);wait(qtbot,window)
    assert c.last_query.period.calendar_days==10 and c.last_query.show_sleep is False


def test_events_master_preserves_individual_layer_selection(controls,qtbot):
    window,_,c,b,panel=controls
    choose(qtbot,panel.period,QuickPeriod.SEVEN_DAYS)
    panel.layers['meals'].setChecked(False)
    panel.layers['events'].setChecked(False);wait(qtbot,window)
    assert snapshot(qtbot,window)['candidate']['data']['view']['events']==[]
    panel.layers['events'].setChecked(True);wait(qtbot,window)
    kinds={s['kind'] for e in snapshot(qtbot,window)['candidate']['data']['view']['events'] for s in e['sources']}
    assert kinds=={'gym'} and panel.layers['meals'].isChecked() is False


def test_invalid_draft_remains_error_after_calendar_change(controls,qtbot):
    window,_,c,b,panel=controls
    custom(qtbot,panel,date(2026,11,4),date(2026,11,1))
    window.chart_now=lambda:NOW+timedelta(days=1)
    window._check_chart_context()
    assert c.requests.latest_id is None
    assert panel.error.isVisible() and 'Диапазон не применён' in window.status.text()
