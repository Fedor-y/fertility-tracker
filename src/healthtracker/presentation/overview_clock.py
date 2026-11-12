"""Текущие местные дата и время; не связаны с периодом или данными графика."""
from datetime import datetime

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from healthtracker.presentation.theme import role

MONTHS = ('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
          'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC')


class OverviewClock(QWidget):
    def __init__(self, parent=None, *, now_provider=None):
        super().__init__(parent)
        self.now_provider = now_provider or (lambda: datetime.now().astimezone())
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        self.date_label = role(QLabel(), 'clockDate')
        self.time_label = role(QLabel(), 'clockTime')
        for label, name in ((self.date_label, 'Текущая дата'), (self.time_label, 'Текущее местное время')):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setAccessibleName(name)
            layout.addWidget(label)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.refresh()

    def refresh(self):
        now = self.now_provider()
        values = ((self.date_label, f'{now.day:02d} {MONTHS[now.month-1]} {now.year:04d}'),
                  (self.time_label, f'{now.hour:02d}:{now.minute:02d}'))
        for label, text in values:
            if label.text() != text:
                label.setText(text)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)
