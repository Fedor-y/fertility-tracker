"""Управление графиком; типизированные предпочтения передаются Application."""
from dataclasses import replace
from PySide6.QtCore import QDate, QSignalBlocker, Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QToolButton, QVBoxLayout, QWidget,
)

from healthtracker.application.charts import ChartQuery
from healthtracker.domain.chart_preferences import ChartPreferences
from healthtracker.application.chart_projection import NAMES
from healthtracker.domain.charts import ChartMode, SeriesKind, chart_mode
from healthtracker.domain.periods import DateRange, QuickPeriod, quick_period

PERIODS = ((QuickPeriod.DAY, 'Сегодня'), (QuickPeriod.SEVEN_DAYS, 'Последние 7 дней'),
           (QuickPeriod.TEN_DAYS, 'Последние 10 дней'), (QuickPeriod.MONTH, 'Текущий месяц'),
           (QuickPeriod.PREVIOUS_MONTH, 'Предыдущий месяц'), (QuickPeriod.YEAR, 'Текущий год'),
           ('custom', 'Произвольный диапазон'))
MODES = {ChartMode.DAY: 'Наблюдения за день', ChartMode.COMPACT: 'Компактно по дням',
         ChartMode.TIMELINE: 'График по часам', ChartMode.DAILY: 'Дневные медианы'}


class ChartControls(QWidget):
    changed = Signal()

    def __init__(self, today, parent=None):
        super().__init__(parent)
        self.setObjectName('chartControls')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
        self._preferences = ChartPreferences()
        self.compact = self._preferences.compact_mode
        self.line_gap_hours = self._preferences.line_gap_hours
        self.last_query = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setSpacing(6)
        row = QHBoxLayout()
        self.period = QComboBox()
        self.period.setAccessibleName('Период графика')
        for key, text in PERIODS:
            self.period.addItem(text, key)
        self.mode = QComboBox()
        self.mode.setAccessibleName('Режим графика')
        self.mode.addItem(MODES[ChartMode.DAY], ChartMode.DAY)
        self.details_button = QToolButton()
        self.details_button.setText('Ряды и слои')
        self.details_button.setCheckable(True)
        row.addWidget(self.period, 1)
        row.addWidget(self.mode, 1)
        row.addWidget(self.details_button)
        layout.addLayout(row)
        self.custom = QWidget()
        custom_row = QHBoxLayout(self.custom)
        custom_row.setContentsMargins(0, 0, 0, 0)
        self.start = QDateEdit(QDate(today))
        self.end = QDateEdit(QDate(today))
        for field, name in ((self.start, 'Начальная дата'), (self.end, 'Конечная дата')):
            field.setCalendarPopup(True)
            field.setDisplayFormat('dd.MM.yyyy')
            field.setDateRange(QDate(1, 1, 1), QDate(9999, 12, 31))
            field.setAccessibleName(name)
        self.apply = QPushButton('Применить')
        custom_row.addWidget(QLabel('От'))
        custom_row.addWidget(self.start)
        custom_row.addWidget(QLabel('до'))
        custom_row.addWidget(self.end)
        custom_row.addWidget(self.apply)
        layout.addWidget(self.custom)
        self.custom.hide()
        self.details = QScrollArea()
        self.details.setFrameShape(QFrame.Shape.NoFrame)
        self.details.setWidgetResizable(True)
        self.details.setMaximumHeight(185)
        inner = QWidget()
        self.grid = QGridLayout(inner)
        self.grid.setContentsMargins(2, 2, 2, 2)
        self.series = {}
        for kind in SeriesKind:
            check = QCheckBox(NAMES[kind.value])
            check.setChecked(kind in self._preferences.visible_series)
            check.toggled.connect(self.changed)
            self.series[kind] = check
        self.layers = {}
        for name, title in (('sleep', 'Сон'), ('meals', 'Питание'), ('gym', 'Спортзал'),
                            ('events', 'События и специальные ответы')):
            check = QCheckBox(title)
            check.setChecked(getattr(self._preferences, 'show_'+name))
            check.toggled.connect(self.changed)
            self.layers[name] = check
        self.layers['events'].setToolTip('Карточки событий дат и специальных ответов. Питание и зал не имеют времени.')
        self.heading_series = QLabel('Показатели')
        self.heading_layers = QLabel('Дополнительные слои')
        self.details.setWidget(inner)
        layout.addWidget(self.details)
        self.details.hide()
        self.details_button.toggled.connect(self.details.setVisible)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setProperty('role','notice')
        self.error.hide()
        layout.addWidget(self.error)
        footer = QHBoxLayout()
        self.info = QLabel()
        self.info.setProperty('role','secondary')
        self.info.setWordWrap(True)
        self.reset_zoom = QToolButton()
        self.reset_zoom.setText('Сбросить масштаб')
        self.reset_zoom.setToolTip('Вернуть полный выбранный диапазон и обновить данные')
        self.info.hide()
        footer.addStretch(1)
        footer.addWidget(self.reset_zoom)
        layout.addLayout(footer)
        self.reset_zoom.clicked.connect(self.changed)
        self.period.currentIndexChanged.connect(self._period_changed)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.apply.clicked.connect(self.changed)
        self._reflow()

    def apply_preferences(self, preferences):
        self._preferences = preferences
        self.compact = preferences.compact_mode
        self.line_gap_hours = preferences.line_gap_hours
        for kind, check in self.series.items():
            with QSignalBlocker(check):
                check.setChecked(kind in preferences.visible_series)
        for name, check in self.layers.items():
            with QSignalBlocker(check):
                check.setChecked(getattr(preferences, 'show_'+name))

    def preferences(self):
        return replace(self._preferences,
                       visible_series=tuple(k for k, check in self.series.items() if check.isChecked()),
                       compact_mode=self.compact, line_gap_hours=self.line_gap_hours,
                       **{'show_'+k: check.isChecked() for k, check in self.layers.items()})

    def _reflow(self):
        while self.grid.count():
            self.grid.takeAt(0)
        columns = 2 if self.width() >= 630 else 1
        self.grid.addWidget(self.heading_series, 0, 0, 1, columns)
        for i, widget in enumerate(self.series.values()):
            self.grid.addWidget(widget, 1+i//columns, i % columns)
        row = 1+(len(self.series)+columns-1)//columns
        self.grid.addWidget(self.heading_layers, row, 0, 1, columns)
        for i, widget in enumerate(self.layers.values()):
            self.grid.addWidget(widget, row+1+i//columns, i % columns)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def _period_changed(self):
        self.custom.setVisible(self.period.currentData() == 'custom')
        self.changed.emit()

    def _mode_changed(self):
        value = self.mode.currentData()
        if value is None:
            return
        mode = ChartMode(value)
        if mode in (ChartMode.COMPACT, ChartMode.TIMELINE):
            self.compact = mode is ChartMode.COMPACT
            self.changed.emit()

    def period_for(self, context):
        key = self.period.currentData()
        return (DateRange(self.start.date().toPython(), self.end.date().toPython()) if key == 'custom'
                else quick_period(QuickPeriod(key), context.today))

    def query(self, context):
        key = self.period.currentData()
        period = self.period_for(context)
        if key != 'custom':
            with QSignalBlocker(self.start), QSignalBlocker(self.end):
                self.start.setDate(QDate(period.start)); self.end.setDate(QDate(period.end))
        modes = tuple(dict.fromkeys((chart_mode(period, True), chart_mode(period, False))))
        with QSignalBlocker(self.mode):
            self.mode.clear()
            for mode in modes:
                self.mode.addItem(MODES[mode], mode)
            self.mode.setCurrentIndex(self.mode.findData(chart_mode(period, self.compact)))
            self.mode.setEnabled(len(modes) > 1)
        query = ChartQuery(period, context, indicator=self._preferences.analytics_indicator,
                           visible_series=tuple(k for k, check in self.series.items() if check.isChecked()),
                           compact=self.compact, line_gap_hours=self.line_gap_hours,
                           **{'show_'+k: check.isChecked() for k, check in self.layers.items()})
        self.last_query = query
        self.error.hide()
        self.info.setText(f'{period.start:%d.%m.%Y} — {period.end:%d.%m.%Y} · {period.calendar_days} календарных дат')
        self.period.setToolTip(self.info.text())
        return query

    def show_result(self, result):
        if self.last_query == result.query:
            period = result.query.period
            suffix = ' · Период не завершён' if result.analytics.statistics.incomplete else ''
            self.info.setText(f'{period.start:%d.%m.%Y} — {period.end:%d.%m.%Y} · {period.calendar_days} календарных дат'+suffix)
            self.period.setToolTip(self.info.text())
