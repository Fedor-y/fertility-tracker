from datetime import UTC, datetime

from PySide6.QtCore import QEvent, QByteArray, QDate, QSettings, QTimer, Qt, QSize, Property, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget, QMainWindow, QMenu,
    QPushButton, QScrollArea, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from healthtracker.application.session import ApplicationSession
from healthtracker.application.errors import StorageError
from healthtracker.presentation.forms.cognitive import CognitiveDialog
from healthtracker.presentation.forms.physical import PhysicalDialog
from healthtracker.presentation.forms.stress import StressDialog
from healthtracker.presentation.forms.mood import MoodDialog
from healthtracker.presentation.forms.sleep import SleepDialog
from healthtracker.presentation.forms.meal import MealDialog
from healthtracker.presentation.forms.gym import GymDialog
from healthtracker.domain.errors import DomainValidationError
from healthtracker.presentation.chart import ChartView
from healthtracker.presentation.diary import DiaryPage, system_zone
from healthtracker.presentation.chart_controls import ChartControls
from healthtracker.presentation.chart_settings_popup import ChartSettingsPopup
from healthtracker.presentation.overview_clock import OverviewClock
from healthtracker.domain.analytics import AnalysisContext
from healthtracker.application.charts import ChartPreparation
from healthtracker.presentation.chart_controller import ChartController
from healthtracker.presentation.chart_preferences import PreferencesController
from healthtracker.presentation.analytics_page import AnalyticsPage
from healthtracker.presentation.backup_page import BackupPage
from healthtracker.presentation.theme import apply_theme, navigation_icon, action_icon, role, show_warning


class MainWindow(QMainWindow):
    """Навигация, дневник выбранного дня и существующие диалоги наблюдений."""

    def __init__(self, application: ApplicationSession | None = None,
                 settings: QSettings | None = None, *, start_chart: bool = True) -> None:
        super().__init__()
        self.start_chart = start_chart
        self.chart_now = lambda: datetime.now(UTC)
        self._chart_controls_used = False
        self._observed_chart_context = None
        self.chart_controller = None
        self._chart_ready = False
        self._overview_requested_page = None
        self._preferences_ready = application is None or not application.storage_available
        self._preferences_close_pending = False
        self.preferences_controller = (PreferencesController(application.chart_preferences, self)
                                       if application is not None and application.storage_available else None)
        self.application = application
        self._restore_pending = None
        self._restart_locked = False
        self.settings = settings
        self.setWindowTitle("HealthTracker")
        apply_theme(self)
        body = QWidget(self)
        body.setObjectName('appBody')
        layout = self._main_layout = QHBoxLayout(body)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(0)
        sidebar = self.sidebar = QFrame()
        sidebar.setObjectName('sideBar')
        sidebar.setFixedWidth(176)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(8,16,8,16)
        side.setSpacing(18)
        brand = QLabel('HealthTracker')
        brand.setObjectName('brand')
        brand.setStyleSheet('font-size: 13px; font-weight: 600;')
        self.brand = brand
        brand_row = self.sidebar_header_grid = QGridLayout()
        brand_row.setSpacing(4)
        brand_row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        brand_row.addWidget(brand, 0, 0, 1, 2)
        self.sidebar_toggle = QToolButton()
        self.sidebar_toggle.setProperty('kind', 'icon')
        self.sidebar_toggle.setIcon(action_icon('sidebar'))
        self.sidebar_toggle.setIconSize(QSize(20,20))
        self.sidebar_toggle.setFixedSize(36,36)
        self.sidebar_toggle.setAccessibleName('Свернуть меню')
        self.sidebar_toggle.clicked.connect(lambda: self._set_sidebar_collapsed(not self.sidebar_collapsed))
        brand_row.addWidget(self.sidebar_toggle, 1, 0)
        self.fullscreen_button = QToolButton()
        self.fullscreen_button.setProperty('kind', 'icon')
        self.fullscreen_button.setIconSize(QSize(20,20))
        self.fullscreen_button.setFixedSize(36,36)
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)
        brand_row.addWidget(self.fullscreen_button, 1, 1)
        self._fullscreen_geometry = QByteArray()
        self._fullscreen_state = Qt.WindowState.WindowNoState
        self.fullscreen_shortcut = QShortcut(QKeySequence('F11'), self)
        self.fullscreen_shortcut.setAutoRepeat(False)
        self.fullscreen_shortcut.activated.connect(self.toggle_fullscreen)
        self.fullscreen_escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.fullscreen_escape.setAutoRepeat(False)
        self.fullscreen_escape.activated.connect(self.leave_fullscreen)
        self._sync_fullscreen_button()
        side.addLayout(brand_row)
        caption = QLabel('ЛИЧНЫЙ ДНЕВНИК')
        caption.setObjectName('brandCaption')
        caption.hide()
        side.addWidget(caption)
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setAccessibleName("Разделы приложения")
        self.navigation.addItems(["Обзор", "Аналитика", "Дневник", "Настройки"])
        self.navigation.setIconSize(QSize(18,18))
        self.navigation.setSpacing(2)
        for index in range(self.navigation.count()):
            item = self.navigation.item(index)
            item.setIcon(navigation_icon(index))
            item.setData(Qt.ItemDataRole.UserRole, item.text())
            item.setData(Qt.ItemDataRole.AccessibleTextRole, item.text())
            item.setToolTip(item.text())
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side.addWidget(self.navigation,1)
        self.sidebar_animation = QPropertyAnimation(self, b'sidebarWidth', self)
        self.sidebar_animation.setDuration(250)
        self.sidebar_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.sidebar_animation.finished.connect(self._finish_sidebar_animation)
        self.sidebar_collapsed = False
        self._set_sidebar_collapsed(self.settings.value('window/sidebar_collapsed', False, type=bool) if self.settings is not None else False, persist=False)
        footer = role(QLabel('Локально на устройстве'),'secondary')
        footer.setWordWrap(True)
        footer.hide()
        side.addWidget(footer)
        layout.addWidget(sidebar)
        content = QVBoxLayout()
        content.setContentsMargins(22,18,22,16)
        content.setSpacing(9)
        layout.addLayout(content, 1)
        header = QVBoxLayout()
        header.setSpacing(3)
        self.page_title = role(QLabel('Обзор'),'pageTitle')
        self.page_subtitle = role(QLabel('Наблюдения и динамика состояния'),'secondary')
        self.page_subtitle.hide()
        header.addWidget(self.page_title)
        header.addWidget(self.page_subtitle)
        header_grid = QGridLayout()
        header_grid.setContentsMargins(0,0,0,0)
        header_grid.addLayout(header,0,0)
        self.overview_clock = OverviewClock()
        header_grid.addWidget(self.overview_clock,0,0,Qt.AlignmentFlag.AlignHCenter)
        content.addLayout(header_grid)
        self.storage_status = QLabel()
        self.storage_status.setObjectName("storageStatus")
        role(self.storage_status,'status')
        self.storage_status.setWordWrap(True)
        self.storage_status.linkActivated.connect(self._open_saved)
        content.addWidget(self.storage_status)
        self.pages = QStackedWidget()
        content.addWidget(self.pages, 1)
        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        overview_layout.setContentsMargins(0,6,0,0)
        overview_layout.setSpacing(9)
        toolbar = QHBoxLayout()
        self.cognitive_button = QPushButton()
        self.cognitive_button.setAccessibleName("Оценить когнитивное состояние")

        self.physical_button = QPushButton()
        self.add_button = QToolButton()
        self.chart_settings_button = QToolButton()
        self.chart_settings_button.setCheckable(True)
        for button, icon, label in (
                (self.cognitive_button, 'brain', 'Оценить когнитивное состояние'),
                (self.physical_button, 'biceps', 'Оценить физическое состояние'),
                (self.add_button, 'plus', 'Добавить запись'),
                (self.chart_settings_button, 'gear', 'Настройки графика')):
            button.setProperty('kind', 'icon')
            button.setIcon(action_icon(icon))
            button.setIconSize(QSize(23,23))
            button.setFixedSize(36,36)
            button.setAccessibleName(label)
            button.setToolTip(label)
        toolbar.setSpacing(7)
        self.add_menu = QMenu(self.add_button)
        self.add_menu.setObjectName("addMenu")
        self.add_actions = {}
        self._quick_stress_pending = False
        for name in ("Настроение", "Стресс", "Стресса нет", "Сон", "Питание", "Спортзал"):
            action = self.add_menu.addAction(name)
            action.setEnabled(False)
            self.add_actions[name] = action
        self.add_actions["Настроение"].triggered.connect(lambda: self.open_mood())
        self.add_actions["Спортзал"].triggered.connect(lambda: self.open_gym())
        self.add_actions["Питание"].triggered.connect(lambda: self.open_meal())
        self.add_actions["Сон"].triggered.connect(lambda: self.open_sleep())
        self.add_actions["Стресс"].triggered.connect(lambda: self.open_stress())
        self.add_actions["Стресса нет"].triggered.connect(self.mark_no_stress)
        self.last_saved_action = self.add_menu.addAction("Открыть последнюю запись")
        self.last_saved_action.setEnabled(False)
        self.last_saved_action.triggered.connect(lambda: self._open_saved(self.last_saved_action.data()))
        self.add_menu.aboutToShow.connect(self._prepare_add_menu)
        self.add_button.setMenu(self.add_menu)
        self.add_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        for button in (self.cognitive_button, self.physical_button):
            button.setEnabled(False)
            button.setToolTip("Форма пока недоступна.")
            toolbar.addWidget(button)
        toolbar.addWidget(self.add_button)
        toolbar.addWidget(self.chart_settings_button)
        overview_layout.addLayout(toolbar)
        self.physical_suggestion = QPushButton("Дополнить оценку")
        self.physical_suggestion.setToolTip("Дополнительно оценить физическое состояние")
        self.physical_suggestion.setVisible(False)
        self.physical_suggestion.clicked.connect(lambda: self.open_physical())
        toolbar.addWidget(self.physical_suggestion)
        toolbar.addStretch()
        self.chart_controls = ChartControls(AnalysisContext(self.chart_now(), system_zone()).today, overview, floating=True)
        self.chart_controls.setEnabled(False)
        self.chart_controls.reset_zoom.hide()
        self.chart_controls.changed.connect(self._controls_changed)
        self.chart_settings_popup = ChartSettingsPopup(self.chart_controls,self.chart_settings_button,self)
        self.chart_settings_button.clicked.connect(self._toggle_chart_settings)
        self.preferences_status = QLabel()
        self.preferences_status.setWordWrap(True)
        self.preferences_status.hide()
        role(self.preferences_status,'notice')
        content.insertWidget(2, self.preferences_status)
        self.preferences_retry = QPushButton('Повторить операцию с настройками')
        self.preferences_retry.hide()
        self.preferences_retry.clicked.connect(self._retry_preferences)
        content.insertWidget(3, self.preferences_retry)
        self.chart = ChartView(overview)
        self.chart.setMinimumHeight(300)
        overview_layout.addWidget(self.chart, 1)
        self.status = role(QLabel("Загрузка графика…"),'secondary')
        self.status.setWordWrap(True)
        overview_layout.addWidget(self.status)
        self.chart_retry = QPushButton("Повторить запрос данных")
        self.chart_retry.hide()
        self.chart_retry.clicked.connect(self._retry_chart)
        overview_layout.addWidget(self.chart_retry)
        self.overview_summary = QLabel('Сводка появится после получения данных.')
        self.overview_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.overview_summary.setWordWrap(True)
        summary_panel = QFrame()
        summary_panel.setObjectName('overviewSummary')
        role(self.overview_summary,'secondary')
        summary_layout = QVBoxLayout(summary_panel)
        summary_layout.setContentsMargins(0,6,0,0)
        summary_layout.setSpacing(5)
        summary_layout.addWidget(self.overview_summary)
        overview_layout.addWidget(summary_panel)
        overview_scroll = QScrollArea()
        overview_scroll.setWidgetResizable(True)
        overview_scroll.setFrameShape(QFrame.Shape.NoFrame)
        overview_scroll.setWidget(overview)
        self.pages.addWidget(overview_scroll)
        for title, message in (
            ("Аналитика", "Аналитика пока недоступна."),
            ("Дневник", "Просмотр дневника пока недоступен."),
            ("Настройки", "Настройки отображения пока недоступны."),
        ):
            if title == 'Аналитика':
                self.analytics_page = AnalyticsPage(application,
                    lambda: AnalysisContext(self.chart_now(), self.chart_controller.zone_provider()
                        if self.chart_controller is not None else system_zone()), self)
                self.analytics_page.setEnabled(self._preferences_ready and application is not None and application.storage_available)
                self.analytics_page.open_requested.connect(self._diary_open)
                self.analytics_page.preferences_changed.connect(self._analytics_preferences_changed)
                self.analytics_page.close_ready.connect(self._controllers_stopped)
                self.pages.addWidget(self.analytics_page)
                continue
            if title == "Дневник":
                service = application.diary if application is not None and application.storage_available else None
                self.diary = DiaryPage(service, parent=self)
                self.diary.open_requested.connect(self._diary_open)
                self.diary.add_requested.connect(self._diary_add)
                self.diary.deleted.connect(self._diary_deleted)
                self.pages.addWidget(self.diary)
                continue
            self.backup_page = BackupPage(application, settings, self)
            self.backup_page.restore_requested.connect(self._begin_restore)
            self.backup_page.restore_finished.connect(self._restore_finished)
            self.backup_page.close_requested.connect(self.close)
            self.pages.addWidget(self.backup_page)
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.setCurrentRow(0)
        self.setCentralWidget(body)
        self.chart.bridge.ready.connect(self._ready)
        self.chart.failed.connect(self._failed)
        self.cognitive_button.clicked.connect(lambda: self.open_cognitive())
        self.physical_button.clicked.connect(lambda: self.open_physical())
        self._storage_state()
        self._restore_window()
        # Контроллер запросов и управление используют один существующий Storage.
        self.chart_controller = (ChartController(ChartPreparation(application.analytics), self)
                                 if application is not None else None)
        if self.chart_controller is not None:
            self.chart_controller.stopped.connect(self._controllers_stopped)
            self.chart.bridge.bind(self.chart_controller)
            self.chart.bridge.open_requested.connect(lambda kind, record_id: self._diary_open(kind, int(record_id)))
            self.chart.bridge.state_changed.connect(self._chart_state)
            QApplication.instance().aboutToQuit.connect(self.chart.bridge.close)
            self.chart_controller.result_ready.connect(self._chart_result_ready)
        if self.preferences_controller is not None:
            p = self.preferences_controller
            p.loaded.connect(self._preferences_loaded)
            p.saved.connect(self._preferences_saved)
            p.changed.connect(self._preferences_changed)
            p.failed.connect(self._preferences_failed)
            self.chart_controller.before_shutdown.connect(p.finish)
            p.start(self.chart_controller.requests)
        self.chart_context_timer = QTimer(self)
        self.chart_context_timer.setInterval(1000)
        self.chart_context_timer.timeout.connect(self._check_chart_context)
        self.chart_context_timer.timeout.connect(self._poll_chart_zoom)
        self.saved_notice_timer = QTimer(self)
        self.saved_notice_timer.setSingleShot(True)
        self.saved_notice_timer.setInterval(5000)
        self.saved_notice_timer.timeout.connect(lambda: self.storage_status.setVisible(
            self.application is None or not self.application.storage_available or bool(self.application.error_message)))
        self.chart_context_timer.start()
        self.navigation.currentRowChanged.connect(self._navigation_changed)

    def _controllers_stopped(self):
        if self._restore_pending is not None:
            QTimer.singleShot(0, self._prepare_restore)
        elif not self._restart_locked:
            QTimer.singleShot(0, self.close)

    def _begin_restore(self, request):
        self._restore_pending = request
        self.navigation.setEnabled(False)
        self.chart.bridge.close()
        self.analytics_page.close_bridge()
        self._storage_state()
        self._prepare_restore()

    def _prepare_restore(self):
        if self._restore_pending is None or self.backup_page.future is not None:
            return
        if self.preferences_controller is not None:
            status = self.preferences_controller.flush_for_close()
            if status is None:
                QTimer.singleShot(25, self._prepare_restore)
                return
            if status is False:
                self.backup_page.restore_preparation_failed()
                return
        chart_done = self.chart_controller is None or self.chart_controller.begin_close()
        analytics_done = self.analytics_page.begin_close()
        if not chart_done or not analytics_done:
            QTimer.singleShot(25, self._prepare_restore)
            return
        self.backup_page.start_restore(self._restore_pending)

    def _restore_finished(self):
        self._restore_pending = None
        self._restart_locked = self.application.restart_required or self.application.recovery_required
        if not self._restart_locked and not self.backup_page._closing:
            if self.chart_controller is not None:
                self.chart_controller.resume_after_close_failure()
                if self.preferences_controller is not None:
                    self.preferences_controller.requests = self.chart_controller.requests
                    self.preferences_controller.closing = False
            self.chart.bridge.resume()
            self.analytics_page.resume()
            self.navigation.setEnabled(True)
        self._storage_state()

    def _toggle_chart_settings(self):
        if self.chart_settings_popup.isVisible():
            self.chart_settings_popup.hide()
        else:
            self.chart_settings_popup.show_for_anchor()

    def _sync_fullscreen_button(self):
        active = self.isFullScreen()
        label = 'Выйти из полного экрана (F11)' if active else 'Полный экран (F11)'
        self.fullscreen_button.setIcon(action_icon('fullscreen-exit' if active else 'fullscreen'))
        self.fullscreen_button.setToolTip(label)
        self.fullscreen_button.setAccessibleName(label)
        self.fullscreen_escape.setEnabled(active)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.leave_fullscreen()
            return
        self._fullscreen_geometry = self.saveGeometry()
        self._fullscreen_state = self.windowState() & ~Qt.WindowState.WindowMinimized
        self.showFullScreen()
        self._sync_fullscreen_button()

    def leave_fullscreen(self):
        if not self.isFullScreen():
            return
        self.showNormal()
        if not self._fullscreen_geometry.isEmpty():
            self.restoreGeometry(self._fullscreen_geometry)
        if self._fullscreen_state & Qt.WindowState.WindowMaximized:
            self.showMaximized()
        self._sync_fullscreen_button()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, 'chart_settings_popup'):
            self.chart_settings_popup.hide()
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, 'fullscreen_escape'):
            self._sync_fullscreen_button()

    @Property(int)
    def sidebarWidth(self):
        return self.sidebar.width()

    @sidebarWidth.setter
    def sidebarWidth(self, width):
        self.sidebar.setFixedWidth(width)
        self._main_layout.activate()

    def _sidebar_labels(self, collapsed):
        # Во время движения подписи целиком скрыты, поэтому не обрезаются.
        self.brand.setVisible(not collapsed)
        self.sidebar_header_grid.removeWidget(self.sidebar_toggle)
        self.sidebar_header_grid.removeWidget(self.fullscreen_button)
        self.sidebar_header_grid.addWidget(self.sidebar_toggle, 0 if collapsed else 1, 0)
        self.sidebar_header_grid.addWidget(self.fullscreen_button, 1, 0 if collapsed else 1)
        self.navigation.setProperty('collapsed', bool(collapsed))
        for index in range(self.navigation.count()):
            item = self.navigation.item(index)
            item.setText('' if collapsed else item.data(Qt.ItemDataRole.UserRole))
        self.navigation.style().unpolish(self.navigation)
        self.navigation.style().polish(self.navigation)

    def _finish_sidebar_animation(self):
        self._sidebar_labels(self.sidebar_collapsed)
        margin = 6 if self.sidebar_collapsed else 8
        self.sidebar.layout().setContentsMargins(margin, 16, margin, 16)

    def _set_sidebar_collapsed(self, collapsed, *, persist=True):
        self.sidebar_animation.stop()
        self.sidebar_collapsed = bool(collapsed)
        target = 56 if collapsed else 176
        label = 'Развернуть меню' if collapsed else 'Свернуть меню'
        self.sidebar_toggle.setToolTip(label)
        self.sidebar_toggle.setAccessibleName(label)
        if persist and self.isVisible() and self.sidebar.width() != target:
            self._sidebar_labels(True)
            self.sidebar_animation.setStartValue(self.sidebar.width())
            self.sidebar_animation.setEndValue(target)
            self.sidebar_animation.start()
        else:
            self.sidebar.setFixedWidth(target)
            self._finish_sidebar_animation()
        if persist and self.settings is not None:
            self.settings.setValue('window/sidebar_collapsed', bool(collapsed))

    def _navigation_changed(self, index):
        titles = (('Обзор','Наблюдения и динамика состояния'),
                  ('Аналитика','Сводки, сравнения и дневные значения'),
                  ('Дневник','Записи и события выбранного дня'),
                  ('Настройки','Резервные копии и сохранность данных'))
        self.page_title.setText(titles[index][0])
        self.overview_clock.setVisible(index == 0)
        self.page_subtitle.setText(titles[index][1])
        self.page_subtitle.hide()
        if index == 3:
            self.backup_page.activate()
        if index == 1:
            self.analytics_page.activate(self.chart_controls.preferences() if self._preferences_ready else None)
        else:
            self.analytics_page.deactivate()

    def _analytics_preferences_changed(self, preferences):
        changed = preferences != self.chart_controls.preferences()
        self.chart_controls.apply_preferences(preferences)
        self.analytics_page.apply_preferences(preferences)
        if self.preferences_controller is not None:
            self.preferences_controller.set_preferences(preferences)
        if changed and self._chart_controls_used:
            self._request_controls()

    def _chart_state(self, state):
        labels = {
            'updating': 'Данные обновляются.',
            'sent': 'Данные обновляются.',
            'confirmed': 'Снимок проверен на момент подтверждения.',
            'stale': 'Данные устарели. Можно повторить запрос.',
            'error': 'Ошибка доставки данных. Можно повторить запрос.',
            'closed': 'Канал данных закрыт.',
        }
        if state in labels:
            self.status.setText(labels[state])
        self.status.setVisible(state != 'confirmed')
        if state in ('updating', 'sent', 'stale', 'error', 'closed', 'checking'):
            self.overview_summary.setEnabled(False)
        elif state == 'confirmed':
            self.overview_summary.setEnabled(True)
        self.chart_retry.setVisible(state in ('stale', 'error')
                                    and self.chart_controller.last_query is not None)

    def _request_controls(self):
        c = self.chart_controller
        if (not self._preferences_ready or self._preferences_close_pending
                or c is None or c.closing or c.closed or not self.application.storage_available):
            return
        self._chart_controls_used = True
        context = AnalysisContext(self.chart_now(), c.zone_provider())
        self._observed_chart_context = (context.zone, context.today)
        try:
            query = self.chart_controls.query(context)
        except DomainValidationError:
            c.invalidate()
            self.chart_controls.mode.setEnabled(False)
            self.chart_controls.error.setText('Проверьте диапазон: начальная дата должна быть не позже конечной.')
            self.chart_controls.error.show()
            self.status.setText('Диапазон не применён. Данные графика устарели.')
            return False
        self._overview_requested_page = self.chart.bridge.pageId
        c.request(query)
        return True

    def _controls_changed(self):
        if self.preferences_controller is not None and self._preferences_ready:
            preferences = self.chart_controls.preferences()
            self.preferences_controller.set_preferences(preferences)
            self.analytics_page.apply_preferences(preferences)
            if self.analytics_page.active:
                self.analytics_page.request()
        self._request_controls()

    def _preferences_loaded(self, preferences, error):
        self.chart_controls.apply_preferences(preferences)
        self._preferences_ready = True
        self.chart_controls.setEnabled(True)
        self.analytics_page.setEnabled(True)
        self.analytics_page.apply_preferences(preferences)
        if self.analytics_page.active:
            self.analytics_page.activate()
        self.preferences_status.setText(error)
        self.preferences_status.setVisible(bool(error))
        self.preferences_retry.setVisible(bool(error))
        if self._chart_ready and self.start_chart:
            if self._chart_controls_used:
                self._request_controls()
            else:
                self._start_overview()

    def _start_overview(self):
        if (self.start_chart and self._chart_ready and self._preferences_ready
                and self._overview_requested_page != self.chart.bridge.pageId):
            self._request_controls()

    def _preferences_saved(self):
        self.preferences_status.hide()
        self.preferences_retry.hide()
        # Commit настроек повышает поколение. Нужен новый снимок, но запись
        # не запускается ни по result_ready, ни при этом обновлении.
        if not self._preferences_close_pending and self._chart_controls_used:
            self._request_controls()
        if not self._preferences_close_pending and self.analytics_page.active:
            self.analytics_page.request()

    def _preferences_failed(self, message):
        self.preferences_status.setText(message)
        self.preferences_status.show()
        self.preferences_retry.show()
        if self._preferences_close_pending:
            self._preferences_close_pending = False
            self.preferences_controller.closing = False
            self.chart.bridge.resume()
            self.analytics_page.resume()
            self._refresh_chart()

    def _preferences_changed(self):
        p = self.preferences_controller
        if self._preferences_close_pending and p.future is None and (not p.error or p.load_failed):
            QTimer.singleShot(0, self.close)

    def _retry_preferences(self):
        if self.preferences_controller is not None:
            if self.preferences_controller.load_failed:
                self._preferences_ready = False
                self.chart_controls.setEnabled(False)
                self.analytics_page.setEnabled(False)
            self.preferences_controller.retry()

    def _chart_result_ready(self):
        if self._chart_controls_used:
            self.chart_controls.show_result(self.chart_controller.last_result)
        QTimer.singleShot(0, self._overview_statistics)

    def _overview_statistics(self):
        c = self.chart_controller
        if c is None or c.closing or c.closed:
            return
        status = c.deliver(lambda result: self.overview_summary.setText(result.summary_text))
        if status is None:
            QTimer.singleShot(25, self._overview_statistics)

    def _check_chart_context(self):
        if self.application is not None:
            state = (self.application.storage_available, self.application.error_message)
            if state != getattr(self, "_last_storage_access", None):
                self._last_storage_access = state
                self._storage_state()
        c = self.chart_controller
        if not self._chart_controls_used or c is None or c.closing or c.closed:
            return
        context = AnalysisContext(self.chart_now(), c.zone_provider())
        key = (context.zone, context.today)
        if key != self._observed_chart_context:
            if self._request_controls():
                self.status.setText('Дата или часовой пояс изменились. Данные обновляются.')

    def _refresh_chart(self):
        if self.start_chart:
            self._request_controls()
        if self.analytics_page.active:
            self.analytics_page.request()

    def _retry_chart(self):
        from dataclasses import replace
        c = self.chart_controller
        if c is not None and not c.closing and not c.closed and c.last_query is not None:
            if self.chart.needs_reload:
                self.chart.reload()
            if self._chart_controls_used:
                self._request_controls()
            else:
                c.request(replace(c.last_query, context=AnalysisContext(self.chart_now(), c.zone_provider())))

    def open_cognitive(self, record_id=None):
        self._open_observation(CognitiveDialog, record_id)

    def open_physical(self, record_id=None):
        self._open_observation(PhysicalDialog, record_id)

    def open_stress(self, record_id=None):
        self._open_observation(StressDialog, record_id)

    def open_mood(self, record_id=None):
        self._open_observation(MoodDialog, record_id)

    def open_sleep(self, record_id=None):
        self._open_observation(SleepDialog, record_id)

    def open_meal(self, record_id=None):
        self._open_observation(MealDialog, record_id)

    def open_gym(self, record_id=None):
        self._open_observation(GymDialog, record_id)

    def _prepare_add_menu(self):
        # Новое открытие меню означает новое самостоятельное действие.
        # Повторные сигналы одной отправки не создают ещё одну запись.
        self._quick_stress_pending = False
        self.add_actions["Стресса нет"].setEnabled(
            self.application is not None and self.application.storage_available
            and not self.application.error_message)

    def mark_no_stress(self):
        if (self._quick_stress_pending or self.application is None
                or not self.application.storage_available or self.application.error_message):
            return
        self._quick_stress_pending = True
        action = self.add_actions["Стресса нет"]
        action.setEnabled(False)
        try:
            record_id = self.application.observations.no_stress()
        except (StorageError, DomainValidationError):
            self.storage_status.setText("Не удалось сохранить отсутствие стресса. Запись не подтверждена; повторите попытку.")
            self.storage_status.show()
            self._quick_stress_pending = False
            action.setEnabled(True)
        else:
            self._observation_saved("stress", record_id)

    def _diary_open(self, kind, record_id):
        classes = dict(cognitive=CognitiveDialog, physical=PhysicalDialog, stress=StressDialog,
                       mood=MoodDialog, sleep=SleepDialog, meals=MealDialog, gym=GymDialog)
        self._open_observation(classes[kind], record_id)

    def _diary_add(self, kind, day):
        classes = dict(cognitive=CognitiveDialog, physical=PhysicalDialog, stress=StressDialog,
                       mood=MoodDialog, sleep=SleepDialog, meals=MealDialog, gym=GymDialog)
        self._open_observation(classes[kind], None, entry_date=day)

    def _form_deleted(self, kind, record_id):
        self.diary.refresh()
        self._diary_deleted(kind, record_id)

    def _diary_deleted(self, kind, record_id):
        if self.last_saved_action.data() == f'{kind}:{record_id}':
            self.last_saved_action.setData(None)
            self.last_saved_action.setEnabled(False)
        if self.chart_controller is not None:
            self.chart_controller.invalidate()
        self._refresh_chart()
        self.storage_status.setText("Запись удалена из локального хранилища.")
        self.storage_status.show()
        self.saved_notice_timer.start()

    def _prefill_diary_date(self, dialog, day):
        zone = self.diary.zone
        if isinstance(dialog, MealDialog):
            dialog.entry_date.setDate(QDate(day))
        elif isinstance(dialog, GymDialog):
            dialog.set_date(day)
        elif isinstance(dialog, SleepDialog):
            dialog.start.zone = dialog.end.zone = zone
            dialog.end.request_date(day)
        else:
            moment = dialog.moment
            original = moment.moment()
            moment.zone = zone
            if day != datetime.now(UTC).astimezone(zone).date():
                moment.request_date(day)
            else:
                moment.set_moment(original)
        dialog.finish_setup()

    def _open_observation(self, dialog_type, record_id, *, entry_date=None):
        if self.application is None or not self.application.storage_available:
            return
        try:
            dialog = dialog_type(self.application.observations, record_id=record_id, parent=self)
        except StorageError:
            show_warning(self, "Не удалось открыть запись", "Запись недоступна. Проверьте хранилище.")
            return
        if record_id is None and entry_date is not None:
            self._prefill_diary_date(dialog, entry_date)
        self.active_dialog = dialog
        dialog.saved.connect(self._observation_saved)
        dialog.enable_deletion(self.application.diary)
        dialog.deleted.connect(self._form_deleted)
        dialog.finished.connect(lambda: dialog.deleteLater())
        dialog.open()

    def _open_saved(self, link):
        kind, record_id = link.split(":")
        if kind == "cognitive":
            self.open_cognitive(int(record_id))
        elif kind == "physical":
            self.open_physical(int(record_id))
        elif kind == "stress":
            self.open_stress(int(record_id))
        elif kind == "mood":
            self.open_mood(int(record_id))
        elif kind == "sleep":
            self.open_sleep(int(record_id))
        elif kind == "meals":
            self.open_meal(int(record_id))
        elif kind == "gym":
            self.open_gym(int(record_id))

    def _observation_saved(self, kind, record_id):
        if self.chart_controller is not None:
            self.chart_controller.invalidate()
        self._refresh_chart()
        self.diary.refresh()
        self.last_saved_action.setData(f'{kind}:{record_id}')
        self.last_saved_action.setEnabled(True)
        self.storage_status.show()
        self.saved_notice_timer.start()
        self.storage_status.setText(f'Запись сохранена в локальном хранилище. <a href="{kind}:{record_id}" style="color: white">Открыть запись</a>')
        if kind == "cognitive":
            self.physical_suggestion.show()

    def _poll_chart_zoom(self):
        # Только визуальное состояние локального ECharts; протокол данных прежний.
        if self.pages.currentIndex() != 0 or self.chart.bridge.state != 'confirmed':
            return
        def received(value):
            from shiboken6 import isValid
            if isValid(self.chart_controls):
                self.chart_controls.reset_zoom.setVisible(value is True)
        self.chart.page().runJavaScript("""(() => {
            const chart = echarts.getInstanceByDom(document.getElementById('chart'));
            const zoom = chart && chart.getOption().dataZoom[0];
            return Boolean(zoom && (zoom.start > 0 || zoom.end < 100));
        })()""", received)

    def _storage_state(self) -> None:
        role(self.storage_status,'notice' if self.application is not None and self.application.error_message else 'status')
        self.storage_status.style().unpolish(self.storage_status)
        self.storage_status.style().polish(self.storage_status)
        available = (self.application is not None and self.application.storage_available and not self.application.error_message
                     and self._restore_pending is None and not self._restart_locked)
        self.storage_status.setVisible(not available)
        self.last_saved_action.setEnabled(available and bool(self.last_saved_action.data()))
        for button in (self.cognitive_button, self.physical_button):
            button.setEnabled(available)
            button.setToolTip(button.accessibleName() if available else "Хранилище недоступно.")
        for name in ("Настроение", "Стресс", "Стресса нет", "Сон", "Питание", "Спортзал"):
            self.add_actions[name].setEnabled(available and (name != "Стресса нет" or not self._quick_stress_pending))
        if self.application is None:
            self.storage_status.setText("Хранилище не подключено.")
            self.add_button.setEnabled(False)
        elif self.application.error_message:
            self.storage_status.setText(self.application.error_message)
            self.add_button.setEnabled(False)
        elif self.application.storage_available:
            self.storage_status.setText("Локальное хранилище подключено.")
            self.add_button.setEnabled(True)
        else:
            self.storage_status.setText("Хранилище закрыто.")
            self.add_button.setEnabled(False)

    def _restore_window(self) -> None:
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry()
        self.resize(min(1280, available.width()), min(800, available.height()))
        if self.settings is not None:
            geometry = self.settings.value("window/geometry", QByteArray())
            if isinstance(geometry, QByteArray) and not geometry.isEmpty():
                self.restoreGeometry(geometry)
                self.setWindowState(self.windowState() & ~Qt.WindowState.WindowFullScreen)
        # Не оставлять окно за отключённым монитором или за краями экрана.
        screens = QApplication.screens()
        target = next((s.availableGeometry() for s in screens
                       if s.availableGeometry().intersects(self.frameGeometry())), available)
        self.resize(min(self.width(), target.width()), min(self.height(), target.height()))
        self.move(max(target.left(), min(self.x(), target.right() - self.width() + 1)),
                  max(target.top(), min(self.y(), target.bottom() - self.height() + 1)))
        if self.settings is not None and self.settings.value("window/maximized", False, type=bool):
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

    def _ready(self) -> None:
        self._chart_ready = True
        if self.application is None:
            self.status.setText("Записей пока нет. Формы появятся на следующих этапах.")
        else:
            self.status.setText("Загрузка наблюдений за выбранный период…")
            if self.start_chart:
                QTimer.singleShot(0, self._start_overview)

    def _failed(self) -> None:
        self.status.setText("Не удалось загрузить график. Проверьте файлы приложения.")

    def closeEvent(self, event) -> None:
        self.chart_settings_popup.hide()
        self.sidebar_animation.stop()
        dialog = getattr(self, "active_dialog", None)
        if dialog is not None:
            try:
                if dialog.isVisible():
                    dialog.reject()
                    if dialog.isVisible():
                        event.ignore()
                        return
            except RuntimeError:
                pass  # Qt уже удалил закрытый диалог.
        if self._restore_pending is not None and self.backup_page.future is None:
            # Подтверждённая операция ещё дописывает предпочтения/завершает
            # контроллеры. Не закрывать очередь раньше отправки restore worker.
            event.ignore()
            QTimer.singleShot(25, self.close)
            return
        self.backup_page.begin_close()
        self.chart.bridge.close()
        self.analytics_page.close_bridge()
        # Не отправлять финальную запись предпочтений навстречу активному snapshot.
        # Ожидание через event loop: никаких join/result под замками или в GUI.
        if self.application is not None and not self.application.prepare_close():
            event.ignore()
            QTimer.singleShot(25, self.close)
            return
        if self.preferences_controller is not None:
            status = self.preferences_controller.flush_for_close()
            if status is not True:
                self._preferences_close_pending = status is None
                if status is False:
                    if self.application is not None:
                        self.application.cancel_close()
                    self.backup_page.resume()
                    self.chart.bridge.resume()
                    self.analytics_page.resume()
                    self._preferences_failed(self.preferences_controller.error)
                event.ignore()
                return
            self._preferences_close_pending = False
        chart_done = self.chart_controller is None or self.chart_controller.begin_close()
        analytics_done = self.analytics_page.begin_close()
        if not chart_done or not analytics_done:
            event.ignore()
            return
        if self.application is not None and not self.application.close():
            self.backup_page.resume()
            if self.chart_controller is not None:
                self.chart_controller.resume_after_close_failure()
                if self.preferences_controller is not None:
                    self.preferences_controller.requests = self.chart_controller.requests
                    self.preferences_controller.closing = False
            self.chart.bridge.resume()
            self.analytics_page.resume()
            self._storage_state()
            event.ignore()
            return
        if self.settings is not None:
            fullscreen = self.isFullScreen() and not self._fullscreen_geometry.isEmpty()
            self.settings.setValue("window/geometry", self._fullscreen_geometry if fullscreen else self.saveGeometry())
            self.settings.setValue("window/maximized", bool(self._fullscreen_state & Qt.WindowState.WindowMaximized) if fullscreen else self.isMaximized())
            self.settings.sync()
        self.chart.release()
        self.analytics_page.release()
        super().closeEvent(event)
