"""Qt-доставка готовых данных. Без отрисовки, WebChannel и SQL."""
from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication

from healthtracker.application.chart_requests import ChartOutcome, ChartRequests
from healthtracker.presentation.diary import system_zone


class ChartController(QObject):
    result_ready = Signal()
    failed = Signal(str)
    stopped = Signal()
    invalidated = Signal()
    before_shutdown = Signal()

    def __init__(self, preparation, parent=None, *, zone_provider=system_zone):
        super().__init__(parent)
        self.requests = ChartRequests(preparation)
        self.zone_provider = zone_provider
        self.last_query = None
        self.last_result = None
        self.last_request_id = None
        self.error = None
        self.closing = False
        self.closed = False
        self.timer = QTimer(self)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        # Даже уничтожение QObject в обход closeEvent управляемо завершает пул.
        requests = self.requests
        self.destroyed.connect(lambda: requests.shutdown(wait=True))

    def request(self, query):
        request_id = self.requests.request(query)
        self.last_query = query
        self.invalidated.emit()
        self.error = None
        return request_id

    def invalidate(self):
        self.requests.invalidate()
        self.invalidated.emit()

    def _result(self, result):
        if result.query.context.zone != self.zone_provider():
            self.invalidate()
            return
        self.last_request_id = self.requests.latest_id
        self.last_result = result
        self.error = None
        self.result_ready.emit()

    def _failure(self, failure):
        query = self.requests.query
        if query is not None and query.context.zone != self.zone_provider():
            self.invalidate()
            return
        self.error = failure
        self.failed.emit(failure.message)

    @Slot()
    def poll(self):
        if self.closed:
            return
        if self.closing:
            if self.requests.idle:
                self._finish_close()
                self.stopped.emit()
            return
        query = self.requests.query
        if query is not None and query.context.zone != self.zone_provider():
            self.invalidate()
        self.requests.dispatch(self._result, self._failure)

    def deliver(self, consumer):
        """Повторная проверка при отложенном применении, включая будущий график."""
        if self.last_result is None or self.last_request_id is None:
            return False
        if self.last_result.query.context.zone != self.zone_provider():
            self.invalidate()
            return False
        outcome = ChartOutcome(self.last_request_id, self.last_result.token, result=self.last_result)
        delivered = False
        def consume(result):
            nonlocal delivered
            if result.query.context.zone != self.zone_provider():
                self.invalidate()
                return
            consumer(result)
            delivered = True
        status = self.requests.apply(outcome, consume, lambda failure:None)
        return None if status is None else delivered

    def begin_close(self):
        if not self.closing:
            self.closing = True
            self.invalidated.emit()
            self.requests.shutdown(wait=False)
        if self.requests.idle:
            self._finish_close()
        return self.closed

    def _finish_close(self):
        self.requests.shutdown(wait=True)
        self.timer.stop()
        self.closed = True

    def resume_after_close_failure(self):
        if not self.closed:
            return
        self.requests = ChartRequests(self.requests.preparation)
        requests = self.requests
        self.destroyed.connect(lambda: requests.shutdown(wait=True))
        self.last_request_id = None
        self.closing = self.closed = False
        self.timer.start()

    @Slot()
    def shutdown(self):
        # aboutToQuit/аварийное уничтожение: ждать безопасного окончания,
        # а не оставлять SQLite в неконтролируемом рабочем потоке.
        self.before_shutdown.emit()
        self.closing = True
        self.invalidated.emit()
        self._finish_close()
