"""Полная аналитика: только Qt-представление результатов Application."""
from dataclasses import fields, replace

from PySide6.QtCore import QAbstractTableModel, QDate, QModelIndex, QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QGridLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QScrollArea, QTabWidget, QToolButton, QTableView, QVBoxLayout, QWidget,
)

from healthtracker.application.analytics_page import AnalyticsPagePreparation, AnalyticsQuery
from healthtracker.application.analytics_view import DAILY_HEADERS, STAT_HEADERS
from healthtracker.application.chart_projection import NAMES
from healthtracker.application.charts import ChartQuery
from healthtracker.domain.analytics import AnalysisContext, Indicator
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.periods import ComparisonPeriod, DateRange, PeriodPair, QuickPeriod, comparison_periods
from healthtracker.presentation.chart import ChartView
from healthtracker.presentation.chart_controller import ChartController
from healthtracker.presentation.chart_controls import ChartControls
from healthtracker.presentation.theme import SummaryCards, role, Disclosure, quiet_table, compact_combo, icon_button, style_calendar
from healthtracker.presentation.chart_settings_popup import ChartSettingsPopup


def text_label(text):
    label=QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByKeyboard | Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class TextTable(QAbstractTableModel):
    def __init__(self, headers, rows, parent=None):
        super().__init__(parent)
        self.headers,self.rows=headers,rows

    def rowCount(self,parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self,parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role in (Qt.ItemDataRole.DisplayRole,Qt.ItemDataRole.ToolTipRole):
            return self.rows[index.row()][index.column()]

    def headerData(self,section,orientation,role=Qt.ItemDataRole.DisplayRole):
        if role in (Qt.ItemDataRole.DisplayRole,Qt.ItemDataRole.ToolTipRole) and orientation==Qt.Orientation.Horizontal:
            return self.headers[section]


def table(headers, rows, name, parent):
    view=QTableView(parent)
    view.setAccessibleName(name)
    view.setModel(TextTable(headers,rows,view))
    view.setMinimumWidth(0)
    view.setMinimumHeight(160)
    quiet_table(view)
    view.horizontalHeader().setStretchLastSection(True)
    view.setColumnWidth(0,180)
    return view


class AnalyticsControls(ChartControls):
    def __init__(self,today,parent=None):
        super().__init__(today,parent,floating=True)
        with QSignalBlocker(self.period):
            self.period.addItem('Текущая неделя до сегодня','week')
            self.period.setCurrentIndex(self.period.findData(QuickPeriod.MONTH))
        # Аналитическая динамика всегда дневная; почасовые режимы — в Обзоре.
        self.mode.hide()
        self.mode_label.hide()
        self.reset_zoom.hide()

    def period_for(self,context):
        if self.period.currentData()=='week':
            return comparison_periods(ComparisonPeriod.WEEK,context.today).first
        return super().period_for(context)


class AnalyticsSections(QWidget):
    def __init__(self,view,parent=None):
        super().__init__(parent)
        layout=QVBoxLayout(self)
        self.caption=text_label(view.caption)
        self.caption.setProperty("role","secondary")
        layout.addWidget(Disclosure("О показателях и периоде",self.caption))
        self.tabs=QTabWidget()
        self.tabs.setMinimumHeight(280)
        layout.addWidget(self.tabs)
        self.summary_table=table(STAT_HEADERS,view.summary_rows,'Сводки шести показателей',self)
        self.daily_table=table(DAILY_HEADERS,view.daily_rows,'Дневные значения выбранного показателя',self)
        summary=QWidget();summary_layout=QVBoxLayout(summary)
        self.cards=SummaryCards(view.summary_rows,summary)
        self.cards.setToolTip(view.caption)
        summary_layout.addWidget(self.cards)
        summary_layout.addWidget(Disclosure("Статистика и даты экстремумов",self.summary_table))
        self.extrema=QPlainTextEdit()
        self.extrema.setReadOnly(True)
        self.extrema.setAccessibleName('Полные даты экстремумов выбранной строки')
        self.extrema.setMinimumHeight(100)
        summary_layout.addWidget(Disclosure("Даты выбранного показателя",self.extrema))
        self.summary_table.selectionModel().currentRowChanged.connect(
            lambda current,previous:self.extrema.setPlainText(view.extrema[current.row()]) if current.isValid() else None)
        self.summary_table.selectRow(view.selected_row)
        self.tabs.addTab(summary,'Сводки')
        self.tabs.addTab(self.daily_table,'Дневные значения')
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        inner=QWidget();body=QVBoxLayout(inner)
        self.comparison=text_label(view.comparison_text)
        self.sleep=text_label(view.sleep_text)
        self.gym=text_label(view.gym_text)
        for title,label in (('Сравнение периодов',self.comparison),('Сон',self.sleep)):
            heading=role(text_label(title),'sectionTitle')
            body.addWidget(heading);body.addWidget(label)
        self.exclusions_table=table(('Исключённая дата','Причины'),view.exclusions,'Причины исключения дат сна',inner)
        body.addWidget(Disclosure("Исключённые даты сна",self.exclusions_table))
        body.addWidget(text_label('Спортзал'));body.addWidget(self.gym)
        scroll.setWidget(inner)
        self.tabs.addTab(scroll,'Сравнения и факторы')


class AnalyticsPage(QWidget):
    preferences_changed=Signal(object)
    close_ready=Signal()
    # SQLite ID — 64-битный; Qt int обрезал бы допустимые большие ID.
    open_requested=Signal(str,object)

    def __init__(self,application,context_provider,parent=None):
        super().__init__(parent)
        self.application=application
        self.context_provider=context_provider
        self.active=False
        self.closing=False
        self.preferences=None
        self.controller=None
        self.chart=None
        self.sections=None
        self._pending=None
        self._observed=None
        self._shown_request=None
        self._session_indicator=None
        outer=QVBoxLayout(self)
        self.scroll=QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll)
        self.inner=QWidget();self.layout=QVBoxLayout(self.inner)
        self.layout.setContentsMargins(0,6,0,0)
        self.controls=AnalyticsControls(context_provider().today,self.inner)
        self.controls.setEnabled(False)

        row=QHBoxLayout()
        self.indicator=QComboBox()
        self.indicator.setAccessibleName('Показатель аналитики')
        for kind in Indicator:
            self.indicator.addItem(NAMES[kind.value],kind.value)
        self.indicator.setToolTip('Индекс и компоненты запоминаются. Физическое состояние и настроение выбираются на текущий сеанс.')
        self.comparison=QComboBox()
        self.comparison.setAccessibleName('Сравнение периодов')
        for key,title in (('none','Без сравнения'),('week','Текущая неделя с предыдущей'),('month','Текущий месяц с предыдущим'),('custom','Два диапазона')):
            self.comparison.addItem(title,key)
        compact_combo(self.indicator)
        compact_combo(self.comparison)
        self.indicator.setMaximumWidth(290)
        self.indicator.setMinimumWidth(180)
        self.period_button=QPushButton(self.controls.period.currentText())
        self.period_button.setToolTip('Выбрать период и параметры аналитики')
        self.settings_button=icon_button(QToolButton(),'gear','Параметры аналитики')
        self.settings_button.setCheckable(True)
        row.addWidget(self.period_button);row.addWidget(self.settings_button);row.addStretch()
        self.layout.addLayout(row)
        self.custom_comparison=QWidget()
        dates=QGridLayout(self.custom_comparison)
        self.ranges=[]
        for i,title in enumerate(('Первый период','Второй период')):
            dates.addWidget(text_label(title),i*2,0,1,2)
            pair=[]
            for j,label in enumerate(('Начало','Конец')):
                field=QDateEdit(QDate(context_provider().today))
                field.setCalendarPopup(True);field.setDisplayFormat('dd.MM.yyyy')
                field.setDateRange(QDate(1,1,1),QDate(9999,12,31))
                field.setAccessibleName(title+' · '+label)
                dates.addWidget(field,i*2+1,j);pair.append(field)
            self.ranges.append(tuple(pair))
        self.apply_comparison=QPushButton('Применить сравнение')
        dates.addWidget(self.apply_comparison,4,0,1,2)
        params=self.controls.layout()
        params.addWidget(text_label('Сравнение периодов'))
        params.addWidget(self.comparison)
        params.addWidget(self.custom_comparison)
        self.custom_comparison.hide()
        self.settings_popup=ChartSettingsPopup(self.controls,self.settings_button,self.window())
        self.settings_popup.findChild(QLabel).setText('Параметры аналитики')
        def toggle_settings():
            if self.settings_popup.isVisible():self.settings_popup.hide()
            else:self.settings_popup.show_for_anchor()
        self.settings_button.clicked.connect(toggle_settings)
        self.period_button.clicked.connect(toggle_settings)
        self.controls.period.currentIndexChanged.connect(
            lambda:self.period_button.setText(self.controls.period.currentText()))
        self.range_label=role(text_label(""),"secondary")
        self.layout.addWidget(self.range_label)
        self.layout.addWidget(self.indicator,0,Qt.AlignmentFlag.AlignLeft)
        for pair in self.ranges:
            for field in pair:style_calendar(field)
        self.status=role(text_label('Откройте страницу для загрузки аналитики.'),'secondary')
        self.layout.addWidget(self.status)
        self.retry=QPushButton('Повторить запрос аналитики')
        self.retry.clicked.connect(self.request)
        self.layout.addWidget(self.retry,0,Qt.AlignmentFlag.AlignLeft)
        self.retry.hide()
        self.placeholder=text_label('Сводки и дневные значения появятся после получения снимка.')
        self.layout.addWidget(self.placeholder)
        self.chart_heading=role(text_label('Динамика и факторы'),'sectionTitle')
        self.layout.addWidget(self.chart_heading)
        self.scroll.setWidget(self.inner)
        self.controls.changed.connect(self._changed)
        self.indicator.currentIndexChanged.connect(self._changed)
        self.comparison.currentIndexChanged.connect(self._comparison_changed)
        self.apply_comparison.clicked.connect(self._changed)
        self.context_timer=QTimer(self)
        self.context_timer.setInterval(1000)
        self.context_timer.timeout.connect(self._check_context)
        self.context_timer.start()

    def apply_preferences(self,preferences):
        self.preferences=preferences
        self.controls.apply_preferences(preferences)
        with QSignalBlocker(self.indicator):
            selected=self._session_indicator or preferences.analytics_indicator
            self.indicator.setCurrentIndex(self.indicator.findData(selected.value))
        self.controls.setEnabled(True)

    def _changed(self):
        if self.preferences is not None:
            selected=Indicator(self.indicator.currentData())
            self._session_indicator=selected if selected in (Indicator.PHYSICAL,Indicator.MOOD) else None
            value=replace(self.controls.preferences(),analytics_indicator=(selected if self._session_indicator is None
                          else self.preferences.analytics_indicator))
            self.preferences_changed.emit(value)
        self.request()

    def _comparison_changed(self):
        self.custom_comparison.setVisible(self.comparison.currentData()=='custom')
        self._changed()

    def activate(self,preferences=None):
        self.active=True
        if preferences is not None:self.apply_preferences(preferences)
        if self.preferences is None or not self.application or not self.application.storage_available:
            self.status.setText('Аналитика ожидает доступного хранилища и настроек.')
            return
        if self.chart is None:
            self._ensure_chart()
        elif self.chart.bridge.is_ready:
            self.request()

    def deactivate(self):
        self.active=False
        self.settings_popup.hide()
        if self.controller:self.controller.invalidate()

    def _ensure_chart(self):
        self.chart=ChartView(self.inner)
        self.chart.setFixedHeight(1450)
        self.layout.addWidget(self.chart)
        self.controller=ChartController(AnalyticsPagePreparation(self.application.analytics),self,
                                        zone_provider=lambda:self.context_provider().zone)
        self.chart.bridge.bind(self.controller)
        self.chart.bridge.ready.connect(self.request)
        self.chart.bridge.state_changed.connect(self._state)
        self.chart.bridge.open_requested.connect(lambda kind,record_id:self.open_requested.emit(kind,int(record_id)))
        self.chart.failed.connect(lambda:self._state('error'))
        self.controller.result_ready.connect(lambda:QTimer.singleShot(0,self._build_sections))
        self.controller.invalidated.connect(self._invalidated)
        self.controller.stopped.connect(self.close_ready)

    def query(self,context):
        base=self.controls.query(context)
        values={f.name:getattr(base,f.name) for f in fields(ChartQuery)}
        values['indicator']=Indicator(self.indicator.currentData())
        key=self.comparison.currentData()
        if key in ('week','month'):values['comparison_kind']=ComparisonPeriod(key)
        elif key=='custom':
            values['comparison_ranges']=PeriodPair(*(DateRange(a.date().toPython(),b.date().toPython()) for a,b in self.ranges))
        return AnalyticsQuery(**values)

    def request(self):
        if (not self.active or not self.isEnabled() or self.closing or self.preferences is None or self.controller is None
                or self.controller.closing or self.controller.closed):return
        if self.chart.needs_reload:
            self.chart.reload();return
        if not self.chart.bridge.is_ready:return
        try:
            context=self.context_provider()
            query=self.query(context)
        except DomainValidationError:
            self.controller.invalidate()
            self.status.setText('Проверьте границы периодов. Прежние данные устарели.')
            return
        self._observed=(context.zone,context.today)
        self.controller.request(query)

    def _invalidated(self):
        if self.sections:self.sections.setEnabled(False)
        if self._pending:
            self._pending[1].deleteLater();self._pending=None
        self.status.setText('Обновляем данные…')

    def _state(self,state):
        self.retry.setVisible(state in ('error','stale','closed'))
        if state=='confirmed':
            if self.sections and self._shown_request==self.controller.requests.latest_id:
                self.sections.setEnabled(True)
            self.status.setText('')
            self.status.setToolTip('Снимок проверен на момент подтверждения. Каждый день имеет одинаковый вес.')
        elif state in ('error','stale','checking','closed','updating','sent'):
            if self.sections:self.sections.setEnabled(False)
            self.status.setText('Данные устарели. Повторите запрос.' if state!='error' else 'Ошибка графика или загрузки. Прежнее отображение сохранено; повторите запрос.')

    def _build_sections(self):
        if not self.active or self.closing or self.controller.last_result is None:return
        result=self.controller.last_result
        if self.controller.last_request_id!=self.controller.requests.latest_id:return
        # Создание виджетов — вне guard/блокировки базы. Только короткая замена
        # готового дерева повторно проверяется непосредственно перед показом.
        built=AnalyticsSections(result.page_view)
        if self.sections:
            built.tabs.setCurrentIndex(self.sections.tabs.currentIndex())
        if self._pending:self._pending[1].deleteLater()
        self._pending=(result,built)
        self._publish()

    def _publish(self):
        if self._pending is None or not self.active or self.closing:return
        result,built=self._pending
        def apply(current):
            if current is not result:return
            old=self.sections or self.placeholder
            self.layout.replaceWidget(old,built)
            old.hide()
            if self.sections:old.deleteLater()
            period=self.controller.last_query.period
            self.range_label.setText(period.start.strftime("%d.%m.%Y")+" — "+period.end.strftime("%d.%m.%Y"))
            self.sections=built
            self._shown_request=self.controller.last_request_id
            built.setEnabled(True);built.show()
        status=self.controller.deliver(apply)
        if status is None:
            QTimer.singleShot(25,self._publish)
            return
        self._pending=None
        if self.sections is not built:built.deleteLater()

    def _check_context(self):
        if not self.active or self.closing or self.controller is None:return
        context=self.context_provider()
        if (context.zone,context.today)!=self._observed:self.request()

    def close_bridge(self):
        self.closing=True
        self.settings_popup.hide()
        if self.chart:self.chart.bridge.close()

    def begin_close(self):
        self.close_bridge()
        return self.controller is None or self.controller.begin_close()

    def resume(self):
        self.closing=False
        if self.controller:self.controller.resume_after_close_failure()
        if self.chart:self.chart.bridge.resume()
        if self.active:self.request()

    def release(self):
        if self.chart:self.chart.release()

    def shutdown(self):
        self.close_bridge()
        if self.controller:self.controller.shutdown()
