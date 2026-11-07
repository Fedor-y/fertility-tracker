"""Настоящие Qt/WebEngine, искусственная база и управляемые Event гонки."""
from dataclasses import replace
from datetime import UTC, date, datetime
from threading import Event, get_ident
from concurrent.futures import ThreadPoolExecutor

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication

from healthtracker.application.chart_preferences import PreferencesError, ChartPreferencesService
from healthtracker.application.chart_requests import ChartRequests
from healthtracker.application.session import ApplicationSession
from healthtracker.domain.chart_preferences import ChartPreferences
from healthtracker.domain.charts import SeriesKind, ChartMode
from healthtracker.domain.periods import QuickPeriod
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.infrastructure.sqlite.settings import SettingsRepository
from healthtracker.presentation.main_window import MainWindow
from test_chart_channel import js
from test_chart_controls import choose, wait
from test_chart_rendering import seed, picture


@pytest.fixture
def setup(qtbot, tmp_path):
    db = Database(tmp_path/'synthetic.sqlite3')
    app = ApplicationSession(db)
    assert app.open()
    windows = []
    def create(start_chart=True):
        window = MainWindow(app, start_chart=start_chart)
        window.chart_now = lambda: datetime(2026,11,4,12,tzinfo=UTC)
        window.chart_controller.zone_provider = lambda: UTC
        qtbot.addWidget(window)
        windows.append(window)
        window.show()
        return window
    yield db, app, create
    for window in windows:
        if not window.isVisible():
            continue
        p = window.preferences_controller
        if p is not None:
            p.error = ''
        window.close()
        qtbot.waitUntil(lambda: not window.isVisible(), timeout=20000)
    app.close()


def ready(qtbot, window):
    qtbot.waitUntil(lambda: window._preferences_ready, timeout=10000)
    wait(qtbot, window)


def saved(qtbot, window):
    p = window.preferences_controller
    qtbot.waitUntil(lambda: p.future is None and not p.dirty and not p.error, timeout=10000)


def test_saved_values_used_by_only_first_query(setup, qtbot, monkeypatch):
    db, app, create = setup
    value = ChartPreferences(visible_series=tuple(SeriesKind), compact_mode=False,
                            line_gap_hours=2.5, show_sleep=False, show_meals=False,
                            show_gym=False, show_events=False)
    app.chart_preferences.save(value)
    queries = []
    original = ChartRequests.request
    def request(self, query):
        queries.append(query)
        return original(self, query)
    monkeypatch.setattr(ChartRequests, 'request', request)
    window = create(); ready(qtbot, window)
    assert len(queries) == 1
    query = queries[0]
    assert query.visible_series == tuple(SeriesKind)
    assert not query.compact and query.line_gap_hours == 2.5
    assert not any((query.show_sleep, query.show_meals, query.show_gym, query.show_events))
    assert window.chart_controls.preferences() == value
    assert window.chart_controls.period.currentData() == QuickPeriod.DAY
    assert picture(qtbot,window)['models']


@pytest.mark.parametrize('kind', list(SeriesKind))
def test_each_series_saved_and_restored(setup, qtbot, kind):
    db, app, create = setup
    window = create(); ready(qtbot, window)
    check = window.chart_controls.series[kind]
    target = not check.isChecked()
    check.setChecked(target)
    saved(qtbot, window); wait(qtbot, window)
    assert (kind in app.chart_preferences.load().visible_series) == target
    assert window.chart_controls.preferences() == app.chart_preferences.load()


@pytest.mark.parametrize('layer', ['sleep', 'meals', 'gym', 'events'])
def test_each_layer_saved_with_rendering(setup, qtbot, layer):
    db, app, create = setup
    window = create(); ready(qtbot, window)
    seed(window,day=date(2026,11,1))
    choose(qtbot, window.chart_controls.period, QuickPeriod.SEVEN_DAYS)
    window.chart_controls.layers[layer].setChecked(False)
    saved(qtbot, window); wait(qtbot, window)
    assert getattr(app.chart_preferences.load(), 'show_'+layer) is False
    assert getattr(window.chart_controller.last_query, 'show_'+layer) is False
    assert picture(qtbot, window)['rendered'] == window.chart.bridge.pending.delivery_id


def test_restart_restores_all_preferences_but_not_period(setup, qtbot):
    db, app, create = setup
    first = create(); ready(qtbot, first)
    panel = first.chart_controls
    for check in panel.series.values(): check.setChecked(True)
    for check in panel.layers.values(): check.setChecked(False)
    choose(qtbot,panel.period,QuickPeriod.SEVEN_DAYS)
    choose(qtbot,panel.mode,ChartMode.TIMELINE)
    expected = panel.preferences()
    # Закрытие до таймера debounce обязано сохранить последнее изменение.
    first.close()
    qtbot.waitUntil(lambda: not first.isVisible(), timeout=15000)
    assert app.open()
    second = create(); ready(qtbot, second)
    assert second.chart_controls.preferences() == expected
    assert second.chart_controls.period.currentData() == QuickPeriod.DAY
    choose(qtbot,second.chart_controls.period,QuickPeriod.SEVEN_DAYS)
    wait(qtbot,second)
    assert second.chart_controller.last_result.chart.mode == ChartMode.TIMELINE


def test_no_sql_on_gui_and_no_extra_writes_for_period_or_zoom(setup, qtbot, monkeypatch):
    db, app, create = setup
    main = get_ident(); reads=[]; writes=[]
    get, put = SettingsRepository.get, SettingsRepository.set
    def read(self,key):
        reads.append(get_ident()); return get(self,key)
    def write(self,key,value):
        writes.append(get_ident()); return put(self,key,value)
    monkeypatch.setattr(SettingsRepository,'get',read)
    monkeypatch.setattr(SettingsRepository,'set',write)
    window=create(); ready(qtbot,window)
    assert reads and all(t != main for t in reads)
    assert not writes
    panel=window.chart_controls
    choose(qtbot,panel.period,QuickPeriod.SEVEN_DAYS)
    panel.reset_zoom.click()
    assert not window.preferences_controller.dirty
    panel.series[SeriesKind.MOOD].setChecked(True)
    saved(qtbot,window)
    assert len(writes)==8 and all(t != main for t in writes)
    with db.read_snapshot() as s:
        keys={r[0] for r in s.connection.execute('SELECT key FROM application_settings')}
    assert keys=={'visible_series','compact_mode','line_gap_hours','analytics_indicator',
                  'show_sleep','show_meals','show_gym','show_events'}


def test_rapid_changes_are_serial_and_last_change_flushed_on_close(setup, qtbot, monkeypatch):
    db, app, create = setup
    window=create(); ready(qtbot,window)
    service=app.chart_preferences; original=service.save
    entered,release=Event(),Event(); values=[]
    def save(value):
        values.append(value)
        if len(values)==1:
            entered.set()
            assert release.wait(15)
        original(value)
    monkeypatch.setattr(service,'save',save)
    p=window.preferences_controller; panel=window.chart_controls
    panel.series[SeriesKind.MOOD].setChecked(True)
    p.debounce.stop(); p._save()
    try:
        qtbot.waitUntil(entered.is_set)
        for _ in range(10): panel.layers['sleep'].setChecked(not panel.layers['sleep'].isChecked())
        panel.layers['gym'].setChecked(False)
        expected=panel.preferences()
        window.close()
        assert window.isVisible()
        marker=[]; QTimer.singleShot(0,lambda:marker.append(True))
        qtbot.waitUntil(lambda: bool(marker))
        assert len(values)==1
    finally:
        release.set()
    qtbot.waitUntil(lambda: not window.isVisible(),timeout=20000)
    assert values==[values[0],expected]
    with Database(db.path) as reopened:
        assert ChartPreferencesService(reopened).load()==expected


def test_save_error_keeps_window_selection_and_can_retry(setup, qtbot, monkeypatch):
    db,app,create=setup
    window=create();ready(qtbot,window)
    service=app.chart_preferences;original=service.save
    def fail(value): raise PreferencesError('private information')
    monkeypatch.setattr(service,'save',fail)
    panel=window.chart_controls;p=window.preferences_controller
    panel.layers['sleep'].setChecked(False)
    p.debounce.stop();p._save()
    qtbot.waitUntil(lambda: bool(p.error))
    assert not panel.layers['sleep'].isChecked()
    assert window.preferences_retry.isVisible()
    assert 'private' not in window.preferences_status.text()
    window.close()
    assert window.isVisible() and app.storage_available
    monkeypatch.setattr(service,'save',original)
    window.preferences_retry.click();saved(qtbot,window)
    assert service.load().show_sleep is False


def test_invalid_read_uses_explicit_defaults_without_overwriting_and_retries_read(setup,qtbot):
    db,app,create=setup
    with db.write() as s:
        s.connection.execute('INSERT INTO application_settings VALUES(?,?,?)',
                             ('visible_series','["unknown"]','2026-11-04T12:00:00.000000Z'))
    window=create();ready(qtbot,window)
    assert window.preferences_controller.load_failed
    assert window.preferences_status.isVisible()
    assert window.chart_controls.preferences()==ChartPreferences()
    window.preferences_retry.click()
    qtbot.waitUntil(lambda: not window.preferences_controller.loading)
    with db.read_snapshot() as s:
        assert s.connection.execute("SELECT value FROM application_settings WHERE key='visible_series'").fetchone()[0]=='["unknown"]'
    assert window.preferences_controller.load_failed


def test_busy_coordinator_does_not_block_gui(setup,qtbot):
    db,app,create=setup
    window=create();ready(qtbot,window)
    entered,release=Event(),Event()
    def hold():
        with db.write() as s:
            entered.set()
            assert release.wait(15)
    with ThreadPoolExecutor(max_workers=1) as pool:
        held=pool.submit(hold)
        try:
            qtbot.waitUntil(entered.is_set)
            window.chart_controls.layers['events'].setChecked(False)
            p=window.preferences_controller;p.debounce.stop();p._save()
            marker=[];QTimer.singleShot(0,lambda:marker.append(True))
            qtbot.waitUntil(lambda:bool(marker))
            assert p.future is not None and not p.future.done()
        finally:
            release.set()
        held.result(timeout=10)
    saved(qtbot,window);wait(qtbot,window)
    assert app.chart_preferences.load().show_events is False


def test_load_gate_prevents_initial_query_and_close_during_load(setup,qtbot,monkeypatch):
    db,app,create=setup
    entered,release=Event(),Event();original=app.chart_preferences.load
    def load():
        entered.set();assert release.wait(15);return original()
    monkeypatch.setattr(app.chart_preferences,'load',load)
    window=create()
    try:
        qtbot.waitUntil(entered.is_set)
        assert not window._preferences_ready
        assert window.chart_controller.last_query is None
        assert not window.chart_controls.isEnabled()
        window.close()
        assert window.isVisible()
    finally:
        release.set()
    qtbot.waitUntil(lambda:not window.isVisible(),timeout=15000)


def test_layout_with_restored_preferences_and_real_canvas(setup,qtbot):
    import os
    from pathlib import Path
    from test_chart_controls import settle_picture
    db,app,create=setup
    value=ChartPreferences(visible_series=tuple(SeriesKind),show_sleep=False,show_gym=False)
    app.chart_preferences.save(value)
    window=create();ready(qtbot,window)
    seed(window,day=date(2026,11,1))
    panel=window.chart_controls
    choose(qtbot,panel.period,QuickPeriod.SEVEN_DAYS);wait(qtbot,window)
    panel.details_button.setChecked(True)
    window.resize(900,650)
    settle_picture(qtbot,window)
    assert panel.preferences()==value
    assert js(qtbot,window,'document.documentElement.scrollWidth <= document.documentElement.clientWidth')
    assert picture(qtbot,window)['domHeight']>=300
    assert picture(qtbot,window)['plotHeight']>=150
    panel.details.ensureWidgetVisible(panel.layers['events'])
    assert panel.details.verticalScrollBar().maximum()>0
    # Только QTest: compositor Wayland не обязан активировать новое окно.
    # Проверяем ожидаемое предупреждение устаревшего Qt test workaround.
    with pytest.warns(DeprecationWarning, match='setActiveWindow'):
        QApplication.setActiveWindow(window)
    panel.layers['events'].setFocus()
    qtbot.waitUntil(panel.layers['events'].hasFocus)
    assert 'QCheckBox:focus' in window.styleSheet()  # Общая тема наследуется панелью.
    path=Path('/tmp/healthtracker-preferences-preview')/os.environ.get('QT_SCALE_FACTOR','1')
    path.mkdir(parents=True,exist_ok=True)
    assert window.grab().save(str(path/'restored.png'))


def test_final_flush_restores_selection_reverted_during_older_write(setup,qtbot,monkeypatch):
    db,app,create=setup
    window=create();ready(qtbot,window)
    app.chart_preferences.save(ChartPreferences())
    original=app.chart_preferences.save;entered,release=Event(),Event();values=[]
    def save(value):
        values.append(value)
        if len(values)==1:
            entered.set();assert release.wait(15)
        original(value)
    monkeypatch.setattr(app.chart_preferences,'save',save)
    p=window.preferences_controller;panel=window.chart_controls
    panel.layers['sleep'].setChecked(False);p.debounce.stop();p._save()
    try:
        qtbot.waitUntil(entered.is_set)
        panel.layers['sleep'].setChecked(True)
        assert not p.dirty  # совпадает с прежним persisted, но не с записью в работе
        p.finish()
    finally:
        release.set()
    saved(qtbot,window)
    assert len(values)==2
    assert app.chart_preferences.load()==ChartPreferences()


def test_close_during_failed_initial_read_does_not_wait_forever(setup,qtbot,monkeypatch):
    db,app,create=setup
    entered,release=Event(),Event()
    def fail():
        entered.set();assert release.wait(15)
        raise PreferencesError('private')
    monkeypatch.setattr(app.chart_preferences,'load',fail)
    window=create()
    try:
        qtbot.waitUntil(entered.is_set)
        window.close();assert window.isVisible()
    finally:
        release.set()
    qtbot.waitUntil(lambda:not window.isVisible(),timeout=15000)


def test_failure_of_inflight_save_cancels_close_and_allows_retry(setup,qtbot,monkeypatch):
    db,app,create=setup
    window=create();ready(qtbot,window)
    original=app.chart_preferences.save;entered,release=Event(),Event()
    def fail(value):
        entered.set();assert release.wait(15)
        raise PreferencesError('private')
    monkeypatch.setattr(app.chart_preferences,'save',fail)
    panel=window.chart_controls;p=window.preferences_controller
    panel.layers['gym'].setChecked(False);p.debounce.stop();p._save()
    try:
        qtbot.waitUntil(entered.is_set)
        window.close();assert window.isVisible()
    finally:
        release.set()
    qtbot.waitUntil(lambda:bool(p.error))
    assert window.isVisible() and not window._preferences_close_pending
    assert window.preferences_retry.isVisible() and app.storage_available
    assert not panel.layers['gym'].isChecked()
    monkeypatch.setattr(app.chart_preferences,'save',original)
    window.preferences_retry.click();saved(qtbot,window)
    assert app.chart_preferences.load().show_gym is False


def test_initial_read_while_coordinator_busy_leaves_gui_responsive(setup,qtbot,monkeypatch):
    db,app,create=setup
    entered,release,begin_read=Event(),Event(),Event()
    original=app.chart_preferences.load
    def load():
        assert begin_read.wait(15)
        return original()
    monkeypatch.setattr(app.chart_preferences,'load',load)
    # Окно создаётся до занятости: прежняя инициализация дневника не относится
    # к асинхронной загрузке предпочтений и здесь не тестируется.
    window=create()
    def hold():
        with db.write():
            entered.set();assert release.wait(15)
    with ThreadPoolExecutor(max_workers=1) as pool:
        task=pool.submit(hold)
        try:
            qtbot.waitUntil(entered.is_set)
            begin_read.set()
            marker=[];QTimer.singleShot(0,lambda:marker.append(True))
            qtbot.waitUntil(lambda:bool(marker))
            assert not window._preferences_ready
            assert window.chart_controller.last_query is None
        finally:
            begin_read.set();release.set()
        task.result(timeout=10)
    ready(qtbot,window)
