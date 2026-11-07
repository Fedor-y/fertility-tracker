"""GUI-состояние предпочтений; Application-задачи в существующем пуле."""
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from healthtracker.domain.chart_preferences import ChartPreferences


class PreferencesController(QObject):
    loaded = Signal(object, str)
    saved = Signal()
    changed = Signal()
    failed = Signal(str)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.requests = None
        self.future = None
        self.loading = True
        self.load_failed = False
        self.desired = None
        self.persisted = None
        self.inflight = None
        self.error = ''
        self.closing = False
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(200)
        self.debounce.timeout.connect(self._save)
        self.timer = QTimer(self)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self.poll)
        # Создаётся до ChartController: финальный flush ставится в пул раньше
        # его aboutToQuit shutdown. Штатное закрытие идёт через flush_for_close.
        QApplication.instance().aboutToQuit.connect(self.finish)

    def start(self, requests):
        self.requests = requests
        self.future = requests.submit_operation(self.service.load)
        self.timer.start()

    @property
    def dirty(self):
        return self.desired is not None and self.desired != self.persisted

    def set_preferences(self, preferences):
        if self.loading or preferences == self.desired:
            return
        self.desired = preferences
        self.load_failed = False
        self.error = ''
        self.debounce.start()
        self.changed.emit()

    def retry(self):
        self.error = ''
        self.debounce.stop()
        if self.load_failed:
            self.loading = True
            self.future = self.requests.submit_operation(self.service.load)
            return
        if self.loading:
            return
        self._save()

    def _save(self):
        if self.loading or self.future is not None or not self.dirty or self.error:
            return
        self.inflight = self.desired
        value = self.inflight
        self.future = self.requests.submit_operation(lambda: self.service.save(value))
        self.changed.emit()

    def poll(self):
        if self.future is None or not self.future.done():
            return
        future, self.future = self.future, None
        try:
            value = future.result()
        except Exception:
            # Не передавать в UI тексты неожиданных исключений/значения JSON.
            if self.loading:
                self.loading = False
                self.load_failed = True
                self.desired = ChartPreferences()
                self.error = 'Не удалось прочитать настройки графика. Используются значения по умолчанию; сохранённые настройки не изменены.'
                self.loaded.emit(self.desired, self.error)
            else:
                self.error = 'Не удалось сохранить настройки графика. Текущий выбор остаётся в окне; повторите сохранение.'
                self.failed.emit(self.error)
        else:
            if self.loading:
                self.loading = False
                self.load_failed = False
                self.desired = self.persisted = value
                self.loaded.emit(value, '')
            else:
                self.persisted = self.inflight
                self.error = ''
                self.saved.emit()
        if self.closing and not self.error:
            self._save()
        elif self.dirty and not self.error and not self.debounce.isActive():
            self._save()
        self.changed.emit()

    def flush_for_close(self):
        self.closing = True
        self.debounce.stop()
        if self.future is not None and self.future.done():
            self.poll()
        if self.future is not None:
            return None
        # Ошибка загрузки без изменений не должна создавать/переписывать строки.
        if self.persisted is None and self.inflight is None and self.error:
            return True
        if self.error and self.dirty:
            self.closing = False
            return False
        self._save()
        return True if self.future is None else None

    def finish(self):
        """Последний снимок при выходе event loop, без Qt из worker.

        Штатное закрытие уже дождалось записи через polling. При внешнем quit
        финальная операция идёт после предыдущей, в существующем пуле.
        """
        self.debounce.stop()
        if self.loading or self.error or self.requests.closed:
            return
        if not self.dirty and (self.future is None or self.inflight == self.desired):
            return
        if self.future is not None and self.inflight == self.desired:
            return
        previous, value, service = self.future, self.desired, self.service
        def flush():
            if previous is not None:
                try:
                    previous.result()
                except Exception:
                    pass
            service.save(value)
        self.inflight = value
        self.future = self.requests.submit_operation(flush)
