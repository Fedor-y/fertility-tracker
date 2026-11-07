"""Настоящий WebEngine/WebChannel, искусственная база, управляемый порядок."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime
import json
from threading import Event

import pytest
from PySide6.QtCore import QSignalBlocker, QTimer

from healthtracker.application.charts import ChartQuery
from healthtracker.application.session import ApplicationSession
from healthtracker.domain.analytics import AnalysisContext
from healthtracker.domain.charts import SeriesKind
from healthtracker.domain.periods import DateRange
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.presentation.main_window import MainWindow

QUERY = ChartQuery(DateRange(date(2026, 11, 1), date(2026, 11, 1)),
                   AnalysisContext(datetime(2026, 11, 4, 12, tzinfo=UTC), UTC),
                   visible_series=(SeriesKind.STRESS,))


@pytest.fixture
def channel(qtbot, tmp_path):
    db = Database(tmp_path / 'synthetic.sqlite3')
    application = ApplicationSession(db)
    assert application.open()
    window = MainWindow(application, start_chart=False)
    qtbot.addWidget(window)
    window.show()
    c, b = window.chart_controller, window.chart.bridge
    c.zone_provider = lambda: UTC
    now = [0.0]
    b.clock = lambda: now[0]
    qtbot.waitUntil(lambda: b.is_ready, timeout=20000)
    yield window, db, c, b, now
    c.shutdown()
    window.close()


def js(qtbot, window, expression):
    result = []
    window.chart.page().runJavaScript(expression, result.append)
    qtbot.waitUntil(lambda: bool(result), timeout=10000)
    return result[0]


def snapshot(qtbot, window):
    return json.loads(js(qtbot, window, 'JSON.stringify(window.healthtrackerChannel.snapshot())'))


def request(qtbot, c, b):
    c.request(QUERY)
    qtbot.waitUntil(lambda: b.state == 'confirmed', timeout=10000)


def held_delivery(qtbot, c, b):
    # Сигналы моста удержаны, подготовка и Qt event loop продолжают работать.
    blocker = QSignalBlocker(b)
    c.request(QUERY)
    qtbot.waitUntil(lambda: b.state == 'sent')
    return blocker, b.pending


def acknowledge(b, p):
    b.received(p.page_id, p.request_id, p.delivery_id)


def write(db):
    with db.write() as session:
        session.settings.set('compact_mode', False)


@pytest.mark.parametrize('nonempty', [False, True])
def test_real_roundtrip_empty_and_nonempty(channel, qtbot, nonempty):
    window, db, c, b, _ = channel
    if nonempty:
        application = window.application
        # Прежний Application-сценарий, реальная запись с числовым нулём.
        application.observations.save_stress(
            score=0, observed_at=datetime(2026, 11, 1, 12, tzinfo=UTC))
    request(qtbot, c, b)
    qtbot.waitUntil(lambda: snapshot(qtbot, window)['state'] == 'confirmed')
    state = snapshot(qtbot, window)
    points = state['candidate']['data']['series'][0]['points']
    assert len(points) == int(nonempty)
    if nonempty:
        assert points[0]['value'] == 0
        assert points[0]['sources'][0]['record_id'] > 0
    assert b.library_loaded and b.channel_ready
    assert db._active == 0
    write(db)  # Никакого ресурса SQLite не удержано до ответа renderer.
    b.poll()
    assert b.state == 'stale'
    qtbot.waitUntil(lambda: snapshot(qtbot, window)['state'] == 'stale')


@pytest.mark.parametrize('field', ['page_id', 'request_id', 'delivery_id'])
def test_old_ack_is_ignored(channel, qtbot, field):
    _, db, c, b, _ = channel
    blocker, p = held_delivery(qtbot, c, b)
    ids = dict(page_id=p.page_id, request_id=p.request_id, delivery_id=p.delivery_id)
    ids[field] = 'f' * 32
    b.received(**ids)
    assert b.state == 'sent'
    acknowledge(b, p)
    assert b.state == 'confirmed'
    del blocker
    write(db)


@pytest.mark.parametrize('change', ['commit', 'database', 'timezone', 'request', 'cancel'])
def test_changes_reject_pending_confirmation(channel, qtbot, change):
    _, db, c, b, _ = channel
    blocker, p = held_delivery(qtbot, c, b)
    if change == 'commit':
        write(db)
    elif change == 'database':
        db.close(); db.initialize()
    elif change == 'timezone':
        from zoneinfo import ZoneInfo
        c.zone_provider = lambda: ZoneInfo('Europe/Berlin')
    elif change == 'request':
        c.request(replace(QUERY, compact=False))
    else:
        c.invalidate()
    acknowledge(b, p)
    assert b.state != 'confirmed'
    assert b.pending is None
    del blocker
    write(db)


@pytest.mark.parametrize('change', ['commit', 'database', 'timezone', 'request'])
def test_changes_invalidate_previously_confirmed_snapshot(channel, qtbot, change):
    _, db, c, b, _ = channel
    request(qtbot, c, b)
    if change == 'commit':
        write(db)
    elif change == 'database':
        db.close(); db.initialize()
    elif change == 'timezone':
        from zoneinfo import ZoneInfo
        c.zone_provider = lambda: ZoneInfo('Europe/Berlin')
    else:
        c.request(replace(QUERY, compact=False))
    b.poll()
    assert b.state == 'stale'
    write(db)


def test_busy_coordinator_defers_ack_without_blocking_gui(channel, qtbot):
    _, db, c, b, _ = channel
    blocker, p = held_delivery(qtbot, c, b)
    entered, release = Event(), Event()
    def hold():
        with db._lock:
            entered.set()
            assert release.wait(5)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(hold)
        assert entered.wait(2)
        try:
            acknowledge(b, p)
            assert b.state == 'updating' and b.ack_received
            alive = Event(); QTimer.singleShot(0, alive.set)
            qtbot.waitUntil(alive.is_set)
            assert not release.is_set()
        finally:
            release.set()
        future.result(timeout=2)
    b.poll()
    assert b.state == 'confirmed'
    del blocker
    write(db)


def test_busy_coordinator_defers_send(channel, qtbot):
    _, db, c, b, _ = channel
    request(qtbot, c, b)
    entered, release = Event(), Event()
    def hold():
        with db._lock:
            entered.set(); assert release.wait(5)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(hold); assert entered.wait(2)
        try:
            assert b.send_latest()
            assert b.state == 'updating' and not b.awaiting_ack
        finally:
            release.set()
        future.result(timeout=2)
    b.poll()
    qtbot.waitUntil(lambda: b.state == 'confirmed')
    write(db)


@pytest.mark.parametrize('failure', ['timeout', 'js', 'renderer'])
def test_errors_never_hold_database(channel, qtbot, failure):
    _, db, c, b, now = channel
    blocker, p = held_delivery(qtbot, c, b)
    if failure == 'timeout':
        now[0] = 6; b.poll()
    elif failure == 'js':
        b.reportFailure(p.page_id, p.request_id, p.delivery_id)
    else:
        # Тот же обработчик, который подключён к renderProcessTerminated.
        from PySide6.QtWebEngineCore import QWebEnginePage
        channel[0].chart.renderProcessTerminated.emit(QWebEnginePage.RenderProcessTerminationStatus.CrashedTerminationStatus, 1)
    assert b.state == 'error' and b.pending is None
    acknowledge(b, p)
    assert b.state == 'error'
    del blocker
    write(db)


def test_late_error_does_not_replace_new_delivery(channel, qtbot):
    _, _, c, b, _ = channel
    blocker, old = held_delivery(qtbot, c, b)
    assert b.send_latest()
    current = b.pending
    b.reportFailure(old.page_id, old.request_id, old.delivery_id)
    assert b.pending is current and b.state == 'sent'
    acknowledge(b, old)
    assert b.state == 'sent'
    acknowledge(b, current)
    assert b.state == 'confirmed'
    del blocker


def test_reload_old_page_and_repeat_handshake(channel, qtbot):
    window, db, c, b, _ = channel
    request(qtbot, c, b)
    old = b.pending
    old_page = b.pageId
    window.chart.reload()
    qtbot.waitUntil(lambda: b.pageId != old_page and b.is_ready, timeout=20000)
    qtbot.waitUntil(lambda: b.state == 'confirmed')
    assert b.pending.page_id != old_page
    current = b.pending
    acknowledge(b, old)
    b.requestInitialState(old_page, '6.0.0')
    b.reportFailure(old_page, old.request_id, old.delivery_id)
    assert b.pending is current and b.state == 'confirmed'
    write(db)


def test_close_rejects_delivery_and_late_answers(channel, qtbot):
    window, _, c, b, _ = channel
    blocker, p = held_delivery(qtbot, c, b)
    del blocker
    assert window.close()
    assert b.closed
    from shiboken6 import isValid
    assert not isValid(b.timer)
    acknowledge(b, p)
    b.reportFailure(p.page_id, p.request_id, p.delivery_id)
    b.requestInitialState(p.page_id, '6.0.0')
    assert not b.send_latest() and b.state == 'closed'


def test_delayed_data_and_confirmation_rejected_by_javascript(channel, qtbot):
    window, _, c, b, _ = channel
    request(qtbot, c, b)
    old = b.pending.encode()
    confirm = json.dumps({'protocol': 1, 'kind': 'confirmed', 'page_id': b.pageId,
                          'sequence': b.pending.sequence, 'request_id': b.pending.request_id,
                          'delivery_id': b.pending.delivery_id})
    c.invalidate()
    qtbot.waitUntil(lambda: snapshot(qtbot, window)['state'] == 'stale')
    for message in (old, confirm):
        js(qtbot, window, 'window.healthtrackerChannel.receive(' + json.dumps(message) + ')')
    assert snapshot(qtbot, window)['state'] == 'stale'
    assert snapshot(qtbot, window)['candidate'] is None


def test_commit_between_send_and_js_receipt_is_rejected(channel, qtbot):
    window, db, c, b, _ = channel
    messages = []
    def commit_on_send(raw):
        if json.loads(raw)['kind'] == 'data':
            messages.append(raw)
            write(db)
    b.payload.connect(commit_on_send)
    c.request(QUERY)
    qtbot.waitUntil(lambda: bool(messages))
    qtbot.waitUntil(lambda: b.state == 'stale')
    assert b.pending is None
    write(db)


def test_expired_ack_cannot_overtake_timeout_timer(channel, qtbot):
    _, db, c, b, now = channel
    blocker, p = held_delivery(qtbot, c, b)
    now[0] = 6
    acknowledge(b, p)  # poll ещё не вызван.
    assert b.state == 'error' and b.pending is None
    del blocker
    write(db)


def test_real_javascript_validation_error_roundtrip(channel, qtbot):
    window, db, c, b, _ = channel
    blocker, p = held_delivery(qtbot, c, b)
    del blocker
    message = json.loads(p.encode())
    message['data']['series'][0]['points'] = [{'value': '<script>'}]
    b.payload.emit(json.dumps(message))
    qtbot.waitUntil(lambda: b.state == 'error')
    qtbot.waitUntil(lambda: snapshot(qtbot, window)['state'] == 'error')
    write(db)


def test_page_identifier_checked_in_javascript(channel, qtbot):
    window, _, c, b, _ = channel
    request(qtbot, c, b)
    qtbot.waitUntil(lambda: snapshot(qtbot, window)['state'] == 'confirmed')
    before = snapshot(qtbot, window)
    bad = json.loads(b.pending.encode())
    bad.update(page_id='f' * 32, sequence=100000)
    js(qtbot, window, 'window.healthtrackerChannel.receive(' + json.dumps(json.dumps(bad)) + ')')
    assert snapshot(qtbot, window) == before


def test_new_delivery_invalidates_previous_in_javascript(channel, qtbot):
    window, _, c, b, _ = channel
    request(qtbot, c, b)
    old = b.pending
    assert b.send_latest()
    current = b.pending
    qtbot.waitUntil(lambda: b.state == 'confirmed')
    qtbot.waitUntil(lambda: snapshot(qtbot, window)['state'] == 'confirmed')
    assert snapshot(qtbot, window)['candidate']['delivery_id'] == current.delivery_id
    js(qtbot, window, 'window.healthtrackerChannel.receive(' + json.dumps(old.encode()) + ')')
    assert snapshot(qtbot, window)['candidate']['delivery_id'] == current.delivery_id


def test_close_during_worker_stops_channel_without_waiting_for_renderer(channel, qtbot):
    window, db, c, b, _ = channel
    started, release = Event(), Event()
    actual = c.requests.preparation
    class Gated:
        analytics = actual.analytics
        def prepare(self, query, checkpoint, snapshot_ready):
            result = actual.prepare(query, checkpoint, snapshot_ready)
            started.set()
            assert release.wait(5)
            return result
    c.requests.preparation = Gated()
    c.request(QUERY)
    assert started.wait(2)
    try:
        assert not window.close()
        assert b.closed and b.pending is None and c.closing
        assert window.application.storage_available
        write(db)
        alive = Event(); QTimer.singleShot(0, alive.set)
        qtbot.waitUntil(alive.is_set)
        assert not release.is_set()
    finally:
        release.set()
    qtbot.waitUntil(lambda: not window.isVisible())
    assert c.closed and c.requests.idle and b.state == 'closed'


def test_retry_after_timeout_gets_new_request_and_delivery(channel, qtbot):
    window, db, c, b, now = channel
    blocker, old = held_delivery(qtbot, c, b)
    now[0] = 6; b.poll()
    del blocker
    assert b.state == 'error'
    window._retry_chart()
    qtbot.waitUntil(lambda: b.state == 'confirmed')
    assert b.pending.request_id != old.request_id and b.pending.delivery_id != old.delivery_id
    write(db)


def test_worker_commit_before_real_webchannel_receipt(channel, qtbot):
    window, db, c, b, _ = channel
    blocker, p = held_delivery(qtbot, c, b)
    # Завершённый commit отдельного потока предшествует отпусканию сообщения.
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(write, db).result(timeout=2)
    del blocker
    b.payload.emit(p.encode())
    qtbot.waitUntil(lambda: b.state == 'stale')
    qtbot.waitUntil(lambda: snapshot(qtbot, window)['state'] == 'stale')
    assert b.pending is None
    write(db)


def test_timeout_of_old_generation_is_staleness_not_current_error(channel, qtbot):
    _, db, c, b, now = channel
    blocker, old = held_delivery(qtbot, c, b)
    write(db)
    now[0] = 6
    b.poll()
    assert b.state == 'stale' and b.pending is None
    acknowledge(b, old)
    assert b.state == 'stale'
    del blocker
