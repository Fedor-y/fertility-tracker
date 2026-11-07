"""Локальный ECharts и минимальный двусторонний контракт WebChannel."""

import json
from pathlib import Path
from uuid import uuid4
from time import monotonic

from healthtracker.presentation.chart_payload import ChartPayload, PROTOCOL_VERSION

from PySide6.QtCore import QObject, QUrl, Signal, Slot, Property, QTimer
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEnginePage, QWebEngineProfile, QWebEngineSettings,
    QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication
from shiboken6 import delete


CHART_ROOT = Path(__file__).resolve().parents[1] / "resources" / "chart"
ECHARTS_VERSION = "6.0.0"


def resource_allowed(url: QUrl) -> bool:
    if url.scheme() == "qrc":
        return url.path() == "/qtwebchannel/qwebchannel.js"
    if url.scheme() != "file":
        return False
    return Path(url.toLocalFile()).resolve().is_relative_to(CHART_ROOT.resolve())


class LocalRequests(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info) -> None:
        info.block(not resource_allowed(info.requestUrl()))


class LocalPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, navigation_type, is_main_frame) -> bool:
        return url.isLocalFile() and Path(url.toLocalFile()).resolve() == (
            CHART_ROOT / "index.html"
        ).resolve()


class ChartBridge(QObject):
    """Предварительный приём в JS и проверяемое принятие в Python.

    confirmed означает актуальность в момент проверки, а не бессрочную гарантию.
    Ни один таймер/ответ renderer не удерживает координатор хранилища.
    """
    payload = Signal(str)
    ready = Signal()
    failed = Signal()
    page_changed = Signal()
    state_changed = Signal(str)
    open_requested = Signal(str, str)

    def __init__(self, parent=None, *, clock=monotonic, timeout=5.0):
        super().__init__(parent)
        self.clock, self.timeout = clock, timeout
        self.controller = None
        self.closed = False
        self.sequence = 0
        self.allowed_sources = frozenset()
        self.pending = None
        self.awaiting_ack = False
        self.ack_received = False
        self.deadline = None
        self.state = 'loading'
        self.echarts_version = ''
        self.is_ready = False
        self.library_loaded = False
        self.channel_ready = False
        self._page_id = uuid4().hex
        self.timer = QTimer(self)
        self.timer.setInterval(25)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    @Property(str, notify=page_changed)
    def pageId(self):
        return self._page_id

    def bind(self, controller):
        self.controller = controller
        controller.result_ready.connect(self.schedule_delivery)
        controller.invalidated.connect(self.invalidate)
        controller.failed.connect(self.preparation_failed)

    def _state(self, state):
        if self.state != state:
            self.state = state
            self.state_changed.emit(state)

    def _control(self, kind, pending=None):
        message = {'protocol': PROTOCOL_VERSION, 'kind': kind,
                   'page_id': self._page_id, 'sequence': self.sequence}
        if pending is not None:
            message.update(request_id=pending.request_id, delivery_id=pending.delivery_id)
        self.payload.emit(json.dumps(message))

    def invalidate(self):
        if self.closed:
            return
        self.sequence += 1
        self.allowed_sources = frozenset()
        self.pending = None
        self.deadline = None
        self.awaiting_ack = self.ack_received = False
        self._state('stale')
        if self.channel_ready and not self.closed:
            self._control('stale')

    def page_loading(self):
        if self.closed:
            return
        self.invalidate()
        self._page_id = uuid4().hex
        self.is_ready = self.library_loaded = self.channel_ready = False
        self.page_changed.emit()
        self._state('loading')

    @Slot(str, str)
    def requestInitialState(self, page_id, version):
        if self.closed or page_id != self._page_id:
            return
        if version != ECHARTS_VERSION:
            self.transport_failed()
            return
        if self.channel_ready:  # Повторный hello не отменяет текущую доставку.
            return
        self.library_loaded = True
        self.echarts_version = version
        self.channel_ready = self.is_ready = True
        self._state('ready')
        self.ready.emit()
        self.schedule_delivery()

    def schedule_delivery(self):
        # result_ready испускается внутри короткого guard: сериализация позже.
        QTimer.singleShot(0, self.send_latest)

    def send_latest(self):
        c = self.controller
        if self.closed or not self.channel_ready or c is None or c.closing or c.closed:
            return False
        result, request_id = c.last_result, c.last_request_id
        if result is None or request_id != c.requests.latest_id:
            return False
        self.invalidate()
        self.sequence += 1
        try:
            candidate = ChartPayload.prepare(self._page_id, request_id, uuid4().hex,
                                             self.sequence, result.chart, projection_json=result.projection_json,
                                             prepared_data=getattr(result,'prepared_data',None))
            encoded = candidate.encode()
        except (ValueError, TypeError, OverflowError):
            self.transport_failed()
            return False
        self.allowed_sources = frozenset(
            (source.kind, source.record_id)
            for sources in ([p.sources for row in result.chart.series for p in row.points]
                            + [(e.source,) for e in result.chart.calendar_events]
                            + [(s.source,) for s in result.chart.sleep])
            for source in sources)
        self.pending = candidate
        self.deadline = self.clock() + self.timeout
        self._encoded = encoded
        self._state('updating')
        self._send()
        return True

    def _guard(self, action):
        c, candidate = self.controller, self.pending
        if (self.closed or c is None or c.closing or c.closed or candidate is None
                or candidate.page_id != self._page_id
                or candidate.request_id != c.requests.latest_id
                or candidate.request_id != c.last_request_id):
            return False
        return c.deliver(action)

    def _send(self):
        candidate = self.pending
        def send(_):
            if self.pending is candidate:
                self.awaiting_ack = True
                self._state('sent')
                self.payload.emit(self._encoded)
        status = self._guard(send)
        if status is False:
            self.invalidate()
        return status

    def _matches(self, page_id, request_id, delivery_id):
        p = self.pending
        return (not self.closed and p is not None and p.page_id == page_id
                and p.request_id == request_id and p.delivery_id == delivery_id)

    @Slot(str, str, str)
    def received(self, page_id, request_id, delivery_id):
        if not self._matches(page_id, request_id, delivery_id) or not self.awaiting_ack:
            return
        if self.deadline is not None and self.clock() >= self.deadline:
            self._expire()
            return
        self.ack_received = True
        self._accept()

    def _accept(self):
        candidate = self.pending
        def accept(_):
            if self.pending is candidate:
                self.awaiting_ack = self.ack_received = False
                self.deadline = None
                self._state('confirmed')
                self._control('confirmed', candidate)
        status = self._guard(accept)
        if status is None:
            self._state('updating')
        elif status is False:
            self.invalidate()

    @Slot(str, str, str, str, str)
    def openSource(self, page_id, request_id, delivery_id, kind, record_id):
        if not self._matches(page_id, request_id, delivery_id) or self.state != 'confirmed':
            return
        if not record_id.isascii() or not record_id.isdecimal() or len(record_id) > 19:
            return
        source = (kind, int(record_id))
        if source not in self.allowed_sources:
            return
        # Открытие формы читает SQLite, поэтому сигнал испускается ПОСЛЕ guard.
        if self._guard(lambda _: None) is True:
            self.open_requested.emit(source[0], str(source[1]))

    def _expire(self):
        # Тайм-аут старого снимка не становится ошибкой текущего поколения.
        if self._guard(lambda _: None) is False:
            self.invalidate()
        else:
            self.transport_failed()

    def poll(self):
        if self.closed or self.pending is None:
            return
        if self.deadline is not None and self.clock() >= self.deadline:
            self._expire()
            return
        if not self.awaiting_ack and self.deadline is not None:
            self._send()
        elif self.ack_received:
            self._accept()
        else:
            status = self._guard(lambda _: None)
            if status is False:
                self.invalidate()
            elif status is None:
                # Даже ранее проверенный снимок не выдаётся за текущий.
                if self.state != 'updating':
                    self._state('updating')
                    self._control('checking', self.pending)
            elif self.deadline is None and self.state == 'updating':
                self._state('confirmed')
                self._control('confirmed', self.pending)

    @Slot(str, str, str)
    def reportFailure(self, page_id, request_id, delivery_id):
        if self._matches(page_id, request_id, delivery_id):
            # Ошибку устаревшего снимка нельзя превращать в текущую ошибку UI.
            status = self._guard(lambda _: self.transport_failed())
            if status is not True:
                self.invalidate()

    def preparation_failed(self, message):
        self.invalidate()
        if not self.closed:
            self._state('error')
            if self.channel_ready:
                self._control('error')

    def transport_failed(self):
        if self.closed:
            return
        self.invalidate()
        self._state('error')
        if self.channel_ready:
            self._control('error')
        self.failed.emit()

    def close(self):
        if self.closed:
            return
        self.invalidate()
        self.closed = True
        self.is_ready = self.channel_ready = False
        self.timer.stop()
        self._state('closed')

    def resume(self):
        self.closed = False
        self.is_ready = self.channel_ready = self.library_loaded
        self._state('stale')
        self.timer.start()

class ChartView(QWebEngineView):
    failed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._released = False
        self.needs_reload = False
        # Профиль живёт до завершения приложения, дольше любой страницы.
        self.profile = QWebEngineProfile(QApplication.instance())
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies
        )
        self.interceptor = LocalRequests(self.profile)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        page = LocalPage(self.profile, self)
        settings = page.settings()
        for attribute in (
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            QWebEngineSettings.WebAttribute.LocalStorageEnabled,
            QWebEngineSettings.WebAttribute.PluginsEnabled,
        ):
            settings.setAttribute(attribute, False)
        self.setPage(page)
        self.channel = QWebChannel(page)
        self.bridge = ChartBridge(self.channel)
        self.channel.registerObject("bridge", self.bridge)
        page.setWebChannel(self.channel)
        self.bridge.failed.connect(self.failed)
        self.loadStarted.connect(self.bridge.page_loading)
        self.loadFinished.connect(self._loaded)
        self.renderProcessTerminated.connect(self._renderer_terminated)
        self.load(QUrl.fromLocalFile(str(CHART_ROOT / "index.html")))

    def _renderer_terminated(self, status, code):
        self.needs_reload = True
        self.bridge.transport_failed()

    def _loaded(self, ok: bool) -> None:
        self.needs_reload = not ok
        if not ok:
            self.bridge.transport_failed()

    def release(self) -> None:
        """Страница должна уничтожаться раньше своего off-the-record профиля."""
        if not self._released:
            self._released = True
            self.bridge.close()
            delete(self.page())
