"""Аналитика в настоящем WebEngine, искусственные наблюдения, управляемые гонки."""
from datetime import UTC,date,datetime,timedelta
from threading import Event
import os,signal

import pytest
from PySide6.QtCore import QDate,QTimer,Qt
from PySide6.QtWidgets import QApplication

from healthtracker.application.session import ApplicationSession
from healthtracker.domain.answers import CognitiveAnswer,AnswerStatus
from healthtracker.domain.cognitive import CognitiveAssessment
from healthtracker.domain.charts import SeriesKind
from healthtracker.domain.periods import QuickPeriod
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.presentation.main_window import MainWindow
from test_chart_channel import js
from test_chart_rendering import picture

NOW=datetime(2026,11,4,12,tzinfo=UTC)


def seed(app,days=14,special=False):
    obs=app.observations
    for i in range(days):
        moment=datetime(2026,10,1,10,tzinfo=UTC)+timedelta(days=i)
        a=CognitiveAnswer(AnswerStatus.CANNOT_ASSESS) if special else CognitiveAnswer.numeric(i%11)
        obs.save_cognitive(CognitiveAssessment(a,CognitiveAnswer.numeric(0),CognitiveAnswer.numeric(i%11)),moment)
        obs.save_mood(score=0,observed_at=moment)
        obs.save_sleep(start=moment-timedelta(hours=10),end=moment-timedelta(hours=2))
        obs.save_gym(entry_date=moment.date(),attended=i%2==0,difficulty=0 if i%2==0 else None)


@pytest.fixture
def analytics_window(qtbot,tmp_path):
    db=Database(tmp_path/'synthetic.sqlite3')
    app=ApplicationSession(db);assert app.open()
    window=MainWindow(app,start_chart=False)
    window.chart_now=lambda:NOW
    window.chart_controller.zone_provider=lambda:UTC
    qtbot.addWidget(window);window.show()
    qtbot.waitUntil(lambda:window._preferences_ready)
    seed(app)
    yield window,db,app
    window.close()
    qtbot.waitUntil(lambda:not window.isVisible(),timeout=20000)


def open_page(qtbot,window):
    window.navigation.setCurrentRow(1)
    p=window.analytics_page
    qtbot.waitUntil(lambda:p.controller is not None and p.chart.bridge.is_ready,timeout=20000)
    wait_page(qtbot,window)
    return p


def wait_page(qtbot,window):
    p=window.analytics_page;c=p.controller;b=p.chart.bridge
    prefs=window.preferences_controller
    qtbot.waitUntil(lambda:prefs.future is None and not prefs.dirty,timeout=15000)
    qtbot.waitUntil(lambda:b.state=='confirmed' and c.last_request_id==c.requests.latest_id
                   and p._shown_request==c.requests.latest_id,timeout=20000)
    qtbot.waitUntil(lambda:picture(qtbot,p)['rendered']==b.pending.delivery_id,timeout=15000)


def custom(qtbot,window,start=date(2026,10,1),end=date(2026,10,14)):
    p=window.analytics_page
    p.controls.period.setCurrentIndex(p.controls.period.findData('custom'))
    p.controls.start.setDate(QDate(start));p.controls.end.setDate(QDate(end));p.controls.apply.click()
    wait_page(qtbot,window)


def test_lazy_page_initial_query_and_roundtrip_navigation(analytics_window,qtbot,monkeypatch):
    window,db,app=analytics_window
    from healthtracker.application.chart_requests import ChartRequests
    original=ChartRequests.request;queries=[]
    def request(self,query):queries.append(query);return original(self,query)
    monkeypatch.setattr(ChartRequests,'request',request)
    assert window.analytics_page.chart is None
    p=open_page(qtbot,window)
    assert len(queries)==1 and p.controller.last_query.period.start==date(2026,11,1)
    assert 'Нет числовых данных' in p.sections.caption.text()
    window.navigation.setCurrentRow(0)
    assert not p.active and p.controller.requests.latest_id is None
    window.navigation.setCurrentRow(1);wait_page(qtbot,window)
    assert len(queries)==2 and p.sections.isEnabled()


def test_summary_daily_and_factor_values_are_domain_results(analytics_window,qtbot):
    window,db,app=analytics_window
    p=open_page(qtbot,window);custom(qtbot,window)
    result=p.controller.last_result
    summary=p.sections.summary_table.model()
    assert summary.rowCount()==6 and summary.data(summary.index(0,1))==f'{result.analytics.statistics.summary.median:.2f}'
    assert summary.data(summary.index(0,5))=='14' and '14 из 14' in summary.data(summary.index(0,7))
    daily=p.sections.daily_table.model()
    assert daily.rowCount()==14 and daily.data(daily.index(0,1))=='0.00'
    assert 'Использовано дат: 14; исключено: 0' in p.sections.sleep.text()
    assert 'Был: 7' in p.sections.gym.text() and 'Не был: 7' in p.sections.gym.text()
    assert p.controller.last_result.chart.mode.value=='daily'
    assert 'Даты минимума:' in p.sections.extrema.toPlainText()
    assert all(str(day) in p.sections.extrema.toPlainText() for day in result.analytics.statistics.summary.minimum_dates)
    assert picture(qtbot,p)['models'][0]['count']==14


@pytest.mark.parametrize('days',[1,6,7])
def test_summary_threshold_and_daily_data_visible(analytics_window,qtbot,days):
    window,_,_=analytics_window;p=open_page(qtbot,window)
    custom(qtbot,window,end=date(2026,10,days))
    cell=p.sections.summary_table.model().data(p.sections.summary_table.model().index(0,1))
    assert (cell=='—')==(days<7)
    assert p.sections.daily_table.model().rowCount()==days


@pytest.mark.parametrize('comparison',['week','month','custom'])
def test_period_comparison(analytics_window,qtbot,comparison):
    window,_,_=analytics_window;p=open_page(qtbot,window);custom(qtbot,window)
    p.sections.tabs.setCurrentIndex(2)
    p.comparison.setCurrentIndex(p.comparison.findData(comparison))
    if comparison=='custom':
        for (a,b),left,right in zip(p.ranges,(date(2026,10,1),date(2026,10,8)),(date(2026,10,7),date(2026,10,14))):
            a.setDate(QDate(left));b.setDate(QDate(right))
        p.apply_comparison.click()
    wait_page(qtbot,window)
    text=p.sections.comparison.text()
    assert 'Первый:' in text and 'Второй:' in text and 'Разница:' in text and 'из' in text
    assert p.controller.last_result.comparison is not None
    assert p.sections.tabs.currentIndex()==2


def test_current_week_and_invalid_comparison_keep_last_view(analytics_window,qtbot):
    window,_,_=analytics_window;p=open_page(qtbot,window)
    p.controls.period.setCurrentIndex(p.controls.period.findData('week'));wait_page(qtbot,window)
    assert p.controller.last_query.period.start==date(2026,11,2)
    p.comparison.setCurrentIndex(p.comparison.findData('custom'));wait_page(qtbot,window)
    previous=p.sections
    p.ranges[0][0].setDate(QDate(2026,11,5));p.ranges[0][1].setDate(QDate(2026,11,1));p.apply_comparison.click()
    assert p.controller.requests.latest_id is None
    assert p.sections is previous and not p.sections.isEnabled()
    assert 'Проверьте границы' in p.status.text()


def test_error_retry_keeps_last_correct_view(analytics_window,qtbot):
    window,_,_=analytics_window;p=open_page(qtbot,window);custom(qtbot,window)
    original=p.controller.requests.preparation;previous=p.sections
    class Failure:
        analytics=original.analytics
        def prepare(self,*args):raise RuntimeError('private details')
    p.controller.requests.preparation=Failure()
    p.request();qtbot.waitUntil(lambda:p.chart.bridge.state=='error')
    assert p.sections is previous and not p.sections.isEnabled() and 'private' not in p.status.text()
    p.controller.requests.preparation=original;p.retry.click();wait_page(qtbot,window)
    assert p.sections is not previous


@pytest.mark.parametrize('old_failure',[False,True])
def test_a_after_b_cannot_replace_analytics_or_error(analytics_window,qtbot,old_failure):
    window,_,_=analytics_window;p=open_page(qtbot,window)
    actual=p.controller.requests.preparation;entered,release=Event(),Event()
    class Gate:
        analytics=actual.analytics
        def prepare(self,query,*args):
            if query.period.start==date(2026,10,1):
                entered.set();assert release.wait(15)
                if old_failure:raise RuntimeError('private A')
            return actual.prepare(query,*args)
    p.controller.requests.preparation=Gate()
    try:
        p.controls.period.setCurrentIndex(p.controls.period.findData('custom'))
        p.controls.start.setDate(QDate(2026,10,1));p.controls.end.setDate(QDate(2026,10,14));p.controls.apply.click()
        qtbot.waitUntil(entered.is_set)
        p.controls.period.setCurrentIndex(p.controls.period.findData(QuickPeriod.MONTH));wait_page(qtbot,window)
        current=p.sections;current_id=p.controller.requests.latest_id
    finally:release.set()
    qtbot.waitUntil(lambda:p.controller.requests.idle)
    p.controller.poll()
    assert p.sections is current and p.controller.requests.latest_id==current_id
    assert p.controller.error is None


def test_reload_restores_page_period_and_preferences(analytics_window,qtbot):
    window,_,_=analytics_window;p=open_page(qtbot,window);custom(qtbot,window)
    query=p.controller.last_query;old_page=p.chart.bridge.pageId
    p.chart.reload()
    qtbot.waitUntil(lambda:p.chart.bridge.pageId!=old_page and p.chart.bridge.is_ready,timeout=20000)
    wait_page(qtbot,window)
    assert p.controller.last_query==query and picture(qtbot,p)['models'][0]['count']==14


def test_close_during_analytics_task_is_nonblocking(analytics_window,qtbot):
    window,db,app=analytics_window;p=open_page(qtbot,window)
    actual=p.controller.requests.preparation;entered,release=Event(),Event()
    class Gate:
        analytics=actual.analytics
        def prepare(self,*args):
            entered.set();assert release.wait(15);return actual.prepare(*args)
    p.controller.requests.preparation=Gate();p.request()
    try:
        qtbot.waitUntil(entered.is_set);window.close()
        assert window.isVisible() and p.closing
        marker=[];QTimer.singleShot(0,lambda:marker.append(True));qtbot.waitUntil(lambda:bool(marker))
    finally:release.set()
    qtbot.waitUntil(lambda:not window.isVisible(),timeout=15000)
    assert not app.storage_available and p.controller.closed


def test_factor_scatter_has_real_graphics_and_safe_tooltips(analytics_window,qtbot):
    window,_,_=analytics_window;p=open_page(qtbot,window);custom(qtbot,window)
    rendering=picture(qtbot,p)
    assert p.chart.bridge.echarts_version=='6.0.0'
    for name in ('sleep-analysis','gym-analysis'):
        model=next(m for m in rendering['models'] if m['id']==name)
        assert model['count']==14 and model['graphics']==14 and model['type']=='scatter'
    assert rendering['paintCount']>0 and rendering['plotHeight']==300
    assert len(rendering['option']['grid'])==4
    text=js(qtbot,p,"(()=>{let s=window.healthtrackerChannel.rendering().series.find(s=>s.id==='sleep-analysis');return window.healthtrackerChannel.tooltip(s.data[0]).textContent;})()")
    assert '2026-10-01' in text and '8.00 ч по UTC' in text
    assert '0.00' in text


def test_empty_factors_do_not_create_fake_points(analytics_window,qtbot):
    window,_,_=analytics_window;p=open_page(qtbot,window)
    rendering=picture(qtbot,p)
    for name in ('sleep-analysis','gym-analysis'):
        assert next(m for m in rendering['models'] if m['id']==name)['count']==0
    assert 'Нет подходящих дат' in p.sections.sleep.text()
    assert 'Разница: —' in p.sections.gym.text()


@pytest.mark.parametrize('days',[8,10])
def test_gym_four_five_boundary_remains_visible(analytics_window,qtbot,days):
    window,_,_=analytics_window;p=open_page(qtbot,window)
    custom(qtbot,window,end=date(2026,10,days))
    assert ('Мало наблюдений' in p.sections.gym.text())==(days==8)
    assert f'Был: {days//2}' in p.sections.gym.text()
    assert next(m for m in picture(qtbot,p)['models'] if m['id']=='gym-analysis')['count']==days


def test_sleep_exclusions_and_special_answers_remain_distinct(analytics_window,qtbot):
    window,_,app=analytics_window
    obs=app.observations
    obs.save_sleep(start=datetime(2026,10,1,12,tzinfo=UTC),end=datetime(2026,10,1,13,tzinfo=UTC))
    obs.save_cognitive(CognitiveAssessment(*(CognitiveAnswer.numeric(0) for _ in range(3))),datetime(2026,10,2,7,tzinfo=UTC))
    obs.save_cognitive(CognitiveAssessment(CognitiveAnswer(AnswerStatus.NOT_ENGAGED),
                      CognitiveAnswer.numeric(0),CognitiveAnswer.numeric(0)),datetime(2026,10,15,10,tzinfo=UTC))
    p=open_page(qtbot,window);custom(qtbot,window,end=date(2026,10,15))
    result=p.controller.last_result
    assert result.analytics.statistics.observed_days==14
    exclusions=p.sections.exclusions_table.model().rows
    assert 'Несколько интервалов' in exclusions[0][1]
    assert 'час начался до пробуждения' in exclusions[1][1]
    assert len(exclusions)==3 and result.analytics.sleep.used_days==12
    daily=p.sections.daily_table.model().rows
    assert daily[-1][1]=='—' and 'Не занимался' in daily[-1][-1]
    assert daily[0][1]=='0.00'


@pytest.mark.parametrize('indicator',['cognitive','learning','application','speed','physical','mood'])
def test_indicator_uses_existing_persistent_preference(analytics_window,qtbot,indicator):
    window,_,app=analytics_window;p=open_page(qtbot,window);custom(qtbot,window)
    p.indicator.setCurrentIndex(p.indicator.findData(indicator));wait_page(qtbot,window)
    assert p.controller.last_query.indicator.value==indicator
    assert 'Когнитивный индекс: дневные медианы' in p.sections.gym.text()
    stored=indicator if indicator not in ('physical','mood') else 'cognitive'
    assert app.chart_preferences.load().analytics_indicator.value==stored
    assert window.chart_controls.preferences().analytics_indicator.value==stored


def test_renderer_loss_keeps_native_stats_and_reload_recovers(analytics_window,qtbot):
    window,_,app=analytics_window;p=open_page(qtbot,window);custom(qtbot,window)
    previous=p.sections;pid=p.chart.page().renderProcessPid()
    assert pid>0 and pid!=os.getpid()
    os.kill(pid,signal.SIGKILL)
    qtbot.waitUntil(lambda:p.chart.bridge.state=='error',timeout=15000)
    assert p.sections is previous and window.isVisible() and app.storage_available
    p.retry.click();wait_page(qtbot,window)
    assert next(m for m in picture(qtbot,p)['models'] if m['id']=='sleep-analysis')['graphics']==14


def test_timezone_requeries_without_changing_utc_records(analytics_window,qtbot):
    from zoneinfo import ZoneInfo
    window,_,app=analytics_window;p=open_page(qtbot,window);custom(qtbot,window)
    before=app.analytics.load(p.controller.last_query.period,p.controller.last_query.context).cognitive
    previous=p.controller.requests.latest_id
    window.chart_controller.zone_provider=lambda:ZoneInfo('America/New_York')
    p._check_context();wait_page(qtbot,window)
    assert p.controller.requests.latest_id!=previous
    assert str(p.controller.last_query.context.zone)=='America/New_York'
    after=app.analytics.load(p.controller.last_query.period,p.controller.last_query.context).cognitive
    assert before==after


def test_overview_brief_and_analytics_layout_screenshots(analytics_window,qtbot):
    from pathlib import Path
    from test_chart_controls import settle_picture
    window,_,_=analytics_window;p=open_page(qtbot,window);custom(qtbot,window)
    window.resize(900,650)
    path=Path('/tmp/healthtracker-analytics-preview')/os.environ.get('QT_SCALE_FACTOR','1')
    path.mkdir(parents=True,exist_ok=True)
    p.scroll.ensureWidgetVisible(p.controls)
    with pytest.warns(DeprecationWarning,match='setActiveWindow'):
        QApplication.setActiveWindow(window)
    p.indicator.setFocus();qtbot.waitUntil(p.indicator.hasFocus)
    assert p.scroll.horizontalScrollBar().maximum()==0
    assert window.grab().save(str(path/'analytics-summary.png'))
    p.scroll.ensureWidgetVisible(p.chart)
    settle_picture(qtbot,p)
    assert js(qtbot,p,'document.documentElement.scrollWidth <= document.documentElement.clientWidth')
    assert picture(qtbot,p)['height']==picture(qtbot,p)['domHeight']
    p.scroll.verticalScrollBar().setValue(p.chart.y()+500)
    qtbot.waitUntil(lambda:p.scroll.verticalScrollBar().value()>0)
    settle_picture(qtbot,p)
    assert window.grab().save(str(path/'analytics-factors.png'))
    p.scroll.verticalScrollBar().setValue(p.chart.y()+880)
    settle_picture(qtbot,p)
    assert window.grab().save(str(path/'analytics-gym.png'))
    window.navigation.setCurrentRow(0)
    panel=window.chart_controls
    panel.period.setCurrentIndex(panel.period.findData('custom'))
    panel.start.setDate(QDate(2026,10,1));panel.end.setDate(QDate(2026,10,14));panel.apply.click()
    qtbot.waitUntil(lambda:window.chart.bridge.state=='confirmed',timeout=20000)
    qtbot.waitUntil(lambda:'Медиана' in window.overview_summary.text())
    settle_picture(qtbot,window)
    assert window.overview_summary.isEnabled()
    assert window.grab().save(str(path/'overview.png'))


def test_native_view_rechecks_token_and_never_waits_for_coordinator(analytics_window,qtbot,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    window,db,_=analytics_window;p=open_page(qtbot,window);custom(qtbot,window)
    previous=p.sections
    publish=p._publish
    monkeypatch.setattr(p,'_publish',lambda:None)
    p.request();qtbot.waitUntil(lambda:p._pending is not None,timeout=15000)
    entered,release=Event(),Event()
    def commit():
        with db.write() as s:
            entered.set();assert release.wait(15)
            s.settings.set('compact_mode',True)
    with ThreadPoolExecutor(max_workers=1) as pool:
        task=pool.submit(commit)
        try:
            qtbot.waitUntil(entered.is_set)
            publish()  # try-lock занят, готовое дерево ещё не показано
            assert p._pending is not None and p.sections is previous
            marker=[];QTimer.singleShot(0,lambda:marker.append(True));qtbot.waitUntil(lambda:bool(marker))
        finally:release.set()
        task.result(timeout=10)
    publish()  # commit сменил поколение между построением виджетов и показом
    assert p.sections is previous and p._pending is None
    monkeypatch.setattr(p,'_publish',publish)
    p.request();wait_page(qtbot,window)
    assert p.sections is not previous


def test_invalid_factor_projection_does_not_replace_last_echarts_plot(analytics_window,qtbot):
    from dataclasses import replace
    import json
    window,_,_=analytics_window;p=open_page(qtbot,window);custom(qtbot,window)
    previous=picture(qtbot,p);actual=p.controller.requests.preparation
    class Invalid:
        analytics=actual.analytics
        def prepare(self,*args):
            result=actual.prepare(*args)
            projection=json.loads(result.projection_json)
            projection['factors']['sleep'][0]['value'][0]='invalid'
            return replace(result,projection_json=json.dumps(projection))
    p.controller.requests.preparation=Invalid();p.request()
    qtbot.waitUntil(lambda:p.chart.bridge.state=='error',timeout=15000)
    assert picture(qtbot,p)['rendered']==previous['rendered']
    assert picture(qtbot,p)['models']==previous['models']
    p.controller.requests.preparation=actual;p.retry.click();wait_page(qtbot,window)


def test_overview_ready_and_preferences_do_not_race_into_two_initial_queries(analytics_window,qtbot,monkeypatch):
    window,_,_=analytics_window
    qtbot.waitUntil(lambda:window.chart.bridge.is_ready,timeout=20000)
    c=window.chart_controller;ids=[];request=c.requests.request
    def counted(query):
        value=request(query);ids.append(value);return value
    monkeypatch.setattr(c.requests,'request',counted)
    window.start_chart=True
    window._ready()  # native ready поставил начальный запрос в event loop
    window._preferences_loaded(window.chart_controls.preferences(),'')
    qtbot.waitUntil(lambda:window.chart.bridge.state=='confirmed' and c.last_request_id==c.requests.latest_id,timeout=20000)
    assert len(ids)==1


def test_analytics_opens_original_record_with_64_bit_sqlite_id(analytics_window,qtbot):
    window,db,app=analytics_window
    record_id=app.observations.save_stress(score=0,observed_at=datetime(2026,10,5,12,tzinfo=UTC))
    large_id=1<<40
    with db.write() as session:
        session.connection.execute('UPDATE stress_entries SET id=? WHERE id=?',(large_id,record_id))
    p=open_page(qtbot,window);custom(qtbot,window)
    p.controls.series[SeriesKind.STRESS].setChecked(True);wait_page(qtbot,window)
    delivery=p.chart.bridge.pending
    p.chart.bridge.openSource(p.chart.bridge.pageId,delivery.request_id,delivery.delivery_id,'stress',str(large_id))
    dialog=window.active_dialog
    assert dialog.record_id==large_id and dialog.service.get('stress',large_id).value.score==0
    dialog.reject()


def test_preferences_error_and_retry_are_visible_on_active_analytics(analytics_window,qtbot,monkeypatch):
    from healthtracker.application.chart_preferences import PreferencesError
    window,_,app=analytics_window;p=open_page(qtbot,window);custom(qtbot,window)
    original=app.chart_preferences.save
    def fail(value):raise PreferencesError('private data')
    monkeypatch.setattr(app.chart_preferences,'save',fail)
    p.controls.series[SeriesKind.MOOD].setChecked(True)
    manager=window.preferences_controller;manager.debounce.stop();manager._save()
    qtbot.waitUntil(lambda:bool(manager.error))
    assert window.pages.currentIndex()==1 and window.preferences_status.isVisible() and window.preferences_retry.isVisible()
    assert p.controls.series[SeriesKind.MOOD].isChecked() and 'private' not in window.preferences_status.text()
    window.close();assert window.isVisible()
    monkeypatch.setattr(app.chart_preferences,'save',original)
    window.preferences_retry.click();wait_page(qtbot,window)
    assert SeriesKind.MOOD in app.chart_preferences.load().visible_series
