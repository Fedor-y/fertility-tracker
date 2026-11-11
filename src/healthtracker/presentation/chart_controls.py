"""Управление графиком; типизированные предпочтения передаются Application."""
from dataclasses import replace
from PySide6.QtCore import QDate, QSize, QSignalBlocker, Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QFrame, QGridLayout, QHBoxLayout, QLayout,
    QLabel, QPushButton, QScrollArea, QSizePolicy, QStyle, QStyleOptionComboBox, QToolButton, QVBoxLayout, QWidget,
)

from healthtracker.presentation.theme import compact_combo, navigation_icon, style_calendar
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

    def __init__(self, today, parent=None, *, floating=False):
        super().__init__(parent)
        self.floating = floating
        self.setObjectName('chartControls')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
        self._preferences = ChartPreferences()
        self.compact = self._preferences.compact_mode
        self.line_gap_hours = self._preferences.line_gap_hours
        self.last_query = None
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setSpacing(6)
        self.top_grid = QGridLayout()
        self.top_grid.setHorizontalSpacing(7)
        self.top_grid.setVerticalSpacing(6)
        self.top_grid.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.period = QComboBox()
        self.period.setAccessibleName('Период графика')
        for key, text in PERIODS:
            self.period.addItem(text, key)
        self.mode = QComboBox()
        for combo in (self.period, self.mode):
            compact_combo(combo)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(6)
            combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.mode.setAccessibleName('Режим графика')
        self.mode.addItem(MODES[ChartMode.DAY], ChartMode.DAY)
        self.details_button = QToolButton()
        self.details_button.setProperty('kind', 'icon')
        self.details_button.setIcon(navigation_icon(3))
        self.details_button.setIconSize(QSize(20,20))
        self.details_button.setFixedSize(36,36)
        self.details_button.setToolTip('Ряды и слои')
        self.details_button.setAccessibleName('Ряды и слои')
        self.details_button.setCheckable(True)
        self.mode_group = QWidget()
        self.mode_group.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Fixed)
        mode_row = QHBoxLayout(self.mode_group)
        mode_row.setContentsMargins(0,0,0,0)
        mode_row.setSpacing(7)
        mode_row.addWidget(self.mode)
        if not floating:
            mode_row.addWidget(self.details_button)
        else:
            self.details_button.setProperty('kind','secondary')
            self.details_button.setMinimumSize(0,0)
            self.details_button.setMaximumSize(16777215,16777215)
            self.details_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self.details_button.setText('Ряды и слои')
            self.period_label = QLabel('Период')
            self.mode_label = QLabel('Режим графика')
            for label in (self.period_label,self.mode_label):label.setProperty('role','secondary')
        layout.addLayout(self.top_grid)
        self.custom = QWidget()
        self.custom_grid = QGridLayout(self.custom)
        self.custom_grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.custom_grid.setContentsMargins(0,0,0,0)
        self.custom_grid.setHorizontalSpacing(7)
        self.custom_grid.setVerticalSpacing(6)
        self.custom_grid.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.start = QDateEdit(QDate(today))
        self.end = QDateEdit(QDate(today))
        for field, name in ((self.start, 'Начальная дата'), (self.end, 'Конечная дата')):
            field.setCalendarPopup(True)
            style_calendar(field)
            field.setDisplayFormat('dd.MM.yyyy')
            field.setDateRange(QDate(1, 1, 1), QDate(9999, 12, 31))
            field.setAccessibleName(name)
        self.apply = QPushButton('Применить')
        self.date_groups = []
        for label, field in (('От',self.start),('До',self.end)):
            group = QWidget()
            group.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Fixed)
            pair = QHBoxLayout(group)
            pair.setContentsMargins(0,0,0,0)
            pair.setSpacing(7)
            pair.addWidget(QLabel(label))
            pair.addWidget(field)
            self.date_groups.append(group)
        self._size_controls()
        layout.addWidget(self.custom)
        self.custom.hide()
        if floating:layout.addWidget(self.details_button,0,Qt.AlignmentFlag.AlignLeft)
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
        footer.addWidget(self.reset_zoom)
        footer.addStretch(1)
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

    def _size_controls(self):
        metrics = self.fontMetrics()
        for combo, texts, preferred in ((self.period,[text for _,text in PERIODS],205),
                                         (self.mode,list(MODES.values()),175)):
            combo.ensurePolished()
            option = QStyleOptionComboBox()
            combo.initStyleOption(option)
            edit = combo.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                                                QStyle.SubControl.SC_ComboBoxEditField, combo)
            inset = combo.width() - edit.width()
            text_width = max(combo.fontMetrics().horizontalAdvance(text) for text in texts)
            combo.setFixedWidth(max(preferred,text_width+inset+4))
        for field in (self.start,self.end):
            field.setFixedWidth(max(135,metrics.horizontalAdvance('00.00.0000')+43))
        self.apply.setFixedWidth(max(100,metrics.horizontalAdvance('Применить')+22))

    def minimumSizeHint(self):
        result = super().minimumSizeHint()
        if hasattr(self,'mode_group'):
            result.setWidth(max(self.period.width(),self.mode_group.sizeHint().width()))
        return result

    @staticmethod
    def _place_groups(grid, groups, available):
        while grid.count():
            grid.takeAt(0)
        row, column, used = 0, 0, 0
        for group in groups:
            width = max(group.minimumWidth(),group.sizeHint().width())
            if column and used + 7 + width > available:
                row, column, used = row+1, 0, 0
            grid.addWidget(group,row,column,Qt.AlignmentFlag.AlignLeft)
            used += width + (7 if column else 0)
            column += 1

    def _reflow(self):
        if self.floating:
            while self.top_grid.count():self.top_grid.takeAt(0)
            for row,widget in enumerate((self.period_label,self.period,self.mode_label,self.mode_group)):
                self.top_grid.addWidget(widget,row,0,Qt.AlignmentFlag.AlignLeft)
            while self.custom_grid.count():self.custom_grid.takeAt(0)
            for row,widget in enumerate((*self.date_groups,self.apply)):
                self.custom_grid.addWidget(widget,row,0,Qt.AlignmentFlag.AlignLeft)
        else:
            self._place_groups(self.top_grid,(self.period,self.mode_group),self.width())
            self._place_groups(self.custom_grid,(*self.date_groups,self.apply),self.width())
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

    def showEvent(self, event):
        super().showEvent(event)
        self._size_controls()
        self._reflow()

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
