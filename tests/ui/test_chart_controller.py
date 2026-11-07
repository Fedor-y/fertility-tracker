from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC,date,datetime,timedelta
from threading import Event,get_ident

import pytest
from PySide6.QtCore import QTimer

from healthtracker.application.charts import ChartPreparation,ChartQuery
from healthtracker.application.session import ApplicationSession
from healthtracker.domain.analytics import AnalysisContext,Indicator
from healthtracker.domain.charts import SeriesKind
from healthtracker.domain.periods import DateRange
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.presentation.chart_controller import ChartController
import healthtracker.presentation.main_window as window_module

QUERY=ChartQuery(DateRange(date(2026,11,1),date(2026,11,1)),AnalysisContext(datetime(2026,11,4,12,tzinfo=UTC),UTC))


class GatedPreparation:
    def __init__(self,preparation):
        self.actual=preparation
        self.analytics=preparation.analytics
        self.started={}
        self.allow={}
        self.fail=set()
    def add(self,query):
        self.started[query]=Event();self.allow[query]=Event()
    def prepare(self,query,checkpoint,snapshot_ready):
        # Данные действительно читаются и рассчитываются рабочим потоком.
        # После этого имитируется непрерываемая фаза, заканчивающаяся позднее.
        result=self.actual.prepare(query)
        snapshot_ready(result.token)
        self.started[query].set()
        assert self.allow[query].wait(5)
        if query in self.fail: raise RuntimeError('private synthetic details')
        return result


@pytest.fixture
def running_window(qtbot,tmp_path,monkeypatch):
    db=Database(tmp_path/'chart.sqlite3')
    application=ApplicationSession(db);assert application.open()
    gate=GatedPreparation(ChartPreparation(application.analytics))
    monkeypatch.setattr(window_module,'ChartController',lambda preparation,parent:ChartController(gate,parent,zone_provider=lambda:UTC))
    window=window_module.MainWindow(application, start_chart=False)
    qtbot.addWidget(window);window.show()
    qtbot.waitUntil(lambda:window.chart.bridge.is_ready,timeout=20000)
    try: yield window,db,gate
    finally:
        for event in gate.allow.values(): event.set()
        window.chart_controller.shutdown()
        window.close()


def test_real_worker_does_not_read_sqlite_in_gui_and_closes_before_calculations(running_window,qtbot,monkeypatch):
    window,db,gate=running_window
    import healthtracker.infrastructure.sqlite.database as module
    import healthtracker.application.charts as charts
    original_connect=module.connect
    original_calculate=charts.calculate_snapshot
    gui=get_ident();connections=[];closed=[];calculations=[]
    @contextmanager
    def connect(*args,**kwargs):
        assert get_ident()!=gui
        with original_connect(*args,**kwargs) as connection:
            connections.append(get_ident())
            yield connection
        import sqlite3
        with pytest.raises(sqlite3.ProgrammingError): connection.execute('SELECT 1')
        closed.append(get_ident())
    def calculate(*args):
        assert db._active==0 and get_ident()!=gui
        assert connections==closed
        calculations.append(get_ident())
        return original_calculate(*args)
    monkeypatch.setattr(module,'connect',connect)
    monkeypatch.setattr(charts,'calculate_snapshot',calculate)
    gate.add(QUERY)
    window.chart_controller.request(QUERY)
    assert gate.started[QUERY].wait(2)
    alive=Event();QTimer.singleShot(0,alive.set)
    qtbot.waitUntil(alive.is_set)
    assert not gate.allow[QUERY].is_set() # GUI обрабатывает события при занятой задаче.
    gate.allow[QUERY].set()
    qtbot.waitUntil(lambda:window.chart_controller.last_result is not None)
    assert calculations and connections and all(thread!=gui for thread in connections)
    # Полноценные данные по-прежнему не передаются прежнему WebChannel.
    assert window.chart.bridge.is_ready


@pytest.mark.parametrize('old_failure',[False,True])
def test_reverse_order_is_preserved_in_presentation(running_window,qtbot,old_failure):
    window,db,gate=running_window;controller=window.chart_controller
    b=replace(QUERY,compact=False)
    for q in (QUERY,b): gate.add(q)
    if old_failure: gate.fail.add(QUERY)
    a_id=controller.request(QUERY);assert gate.started[QUERY].wait(2)
    b_id=controller.request(b);assert gate.started[b].wait(2)
    gate.allow[b].set()
    qtbot.waitUntil(lambda:controller.last_request_id==b_id)
    good=controller.last_result
    gate.allow[QUERY].set()
    qtbot.waitUntil(lambda:controller.requests.idle)
    controller.poll()
    assert controller.last_result is good and controller.last_result.query==b
    assert controller.error is None and a_id!=b_id


def test_delayed_consumer_checks_request_and_token_again(running_window,qtbot):
    window,db,gate=running_window;controller=window.chart_controller
    gate.add(QUERY);gate.allow[QUERY].set()
    controller.request(QUERY)
    qtbot.waitUntil(lambda:controller.last_result is not None)
    delivered=[]
    assert controller.deliver(delivered.append) is True and len(delivered)==1
    with db.write() as session: session.settings.set('compact_mode',False)
    assert controller.deliver(delivered.append) is False and len(delivered)==1
    b=replace(QUERY,indicator=Indicator.LEARNING)
    gate.add(b);controller.request(b)
    assert controller.deliver(delivered.append) is False
    assert len(delivered)==1


def test_latest_error_keeps_previous_good_result(running_window,qtbot):
    window,db,gate=running_window;controller=window.chart_controller
    gate.add(QUERY);gate.allow[QUERY].set();controller.request(QUERY)
    qtbot.waitUntil(lambda:controller.last_result is not None)
    old=controller.last_result
    b=replace(QUERY,visible_series=(SeriesKind.MOOD,))
    gate.add(b);gate.fail.add(b);gate.allow[b].set();controller.request(b)
    qtbot.waitUntil(lambda:controller.error is not None)
    assert controller.last_result is old and 'private' not in controller.error.message
    assert controller.deliver(lambda _:pytest.fail('old result')) is False


def test_timezone_change_invalidates_before_poll_and_delayed_delivery(running_window,qtbot):
    window,db,gate=running_window;controller=window.chart_controller
    gate.add(QUERY);gate.allow[QUERY].set();controller.request(QUERY)
    qtbot.waitUntil(lambda:controller.last_result is not None)
    from zoneinfo import ZoneInfo
    controller.zone_provider=lambda:ZoneInfo('Europe/Berlin')
    assert controller.deliver(lambda _:pytest.fail('old timezone')) is False
    assert controller.requests.latest_id is None


def test_window_close_waits_safely_without_blocking_gui_or_leaving_threads(running_window,qtbot):
    window,db,gate=running_window;controller=window.chart_controller
    gate.add(QUERY);controller.request(QUERY)
    assert gate.started[QUERY].wait(2)
    assert not window.close()
    assert window.isVisible() and controller.closing and not controller.closed
    assert window.application.storage_available
    alive=Event();QTimer.singleShot(0,alive.set);qtbot.waitUntil(alive.is_set)
    assert not gate.allow[QUERY].is_set()
    gate.allow[QUERY].set()
    qtbot.waitUntil(lambda:not window.isVisible())
    assert controller.closed and controller.requests.idle
    assert not any(thread.is_alive() for thread in controller.requests._pool._threads)
    assert not window.application.storage_available


def test_about_to_quit_shutdown_slot_joins_inflight_work(running_window):
    window,db,gate=running_window;controller=window.chart_controller
    gate.add(QUERY);controller.request(QUERY)
    assert gate.started[QUERY].wait(2)
    with controller.requests._lock: cancellation=next(iter(controller.requests._jobs.values()))
    def release_after_shutdown_started():
        assert cancellation.wait(2)
        gate.allow[QUERY].set()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(release_after_shutdown_started)
        controller.shutdown() # Этот Slot подключён к QApplication.aboutToQuit.
        future.result(timeout=3)
    assert controller.closed and controller.requests.idle
    assert not any(thread.is_alive() for thread in controller.requests._pool._threads)


def test_failed_storage_close_restores_ability_to_request_data(running_window,monkeypatch,qtbot):
    window,db,gate=running_window;controller=window.chart_controller
    from healthtracker.application.errors import StorageError
    original=db.close
    def fail(): raise StorageError('synthetic')
    monkeypatch.setattr(db,'close',fail)
    assert not window.close() and window.isVisible()
    assert not controller.closed and not controller.requests.closed
    monkeypatch.setattr(db,'close',original)
    gate.add(QUERY);gate.allow[QUERY].set();controller.request(QUERY)
    qtbot.waitUntil(lambda:controller.last_result is not None)
    assert window.close()


def test_close_during_actual_sqlite_read_keeps_window_responsive_until_session_ends(running_window,qtbot,monkeypatch):
    window,db,gate=running_window;controller=window.chart_controller
    from healthtracker.infrastructure.sqlite.base import RecordRepository
    original=RecordRepository.between
    reading,release=Event(),Event()
    def between(repo,start,end):
        if repo.table=='cognitive_entries':
            reading.set()
            assert release.wait(5)
        return original(repo,start,end)
    monkeypatch.setattr(RecordRepository,'between',between)
    gate.add(QUERY);gate.allow[QUERY].set()
    try:
        controller.request(QUERY);assert reading.wait(2)
        assert db._active==1
        assert not window.close() and window.application.storage_available
        alive=Event();QTimer.singleShot(0,alive.set);qtbot.waitUntil(alive.is_set)
        assert db._active==1 and not release.is_set()
        release.set()
        qtbot.waitUntil(lambda:not window.isVisible())
        assert db._active==0 and controller.closed and controller.requests.idle
    finally: release.set()


def test_timezone_is_rechecked_inside_the_final_consumer(running_window,qtbot,monkeypatch):
    window,db,gate=running_window;controller=window.chart_controller
    gate.add(QUERY);gate.allow[QUERY].set();controller.request(QUERY)
    qtbot.waitUntil(lambda:controller.last_result is not None)
    original=db.apply_if_current
    def changed_between_check_and_consumer(token,action,**kwargs):
        from zoneinfo import ZoneInfo
        controller.zone_provider=lambda:ZoneInfo('Europe/Berlin')
        return original(token,action,**kwargs)
    monkeypatch.setattr(db,'apply_if_current',changed_between_check_and_consumer)
    delivered=[]
    assert controller.deliver(delivered.append) is False
    assert delivered==[]
