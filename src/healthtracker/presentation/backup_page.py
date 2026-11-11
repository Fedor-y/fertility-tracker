"""Компактная страница копий: Qt и готовые результаты Application, без файлового I/O."""
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QProgressBar,
    QMessageBox, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from healthtracker.application.backups import BackupPhase, BackupRequest
from healthtracker.application.restoration import RestoreRequest
from healthtracker.presentation.theme import role, Disclosure, quiet_table, icon_button, action_icon, style_message_box

DIRECTORY_KEY = 'backup/directory'


def label(text=''):
    value = QLabel(text)
    value.setTextFormat(Qt.TextFormat.PlainText)
    value.setWordWrap(True)
    return value


def file_size(size):
    for unit in ('Б', 'КиБ', 'МиБ', 'ГиБ'):
        if size < 1024 or unit == 'ГиБ':
            return f'{size:.1f} {unit}' if unit != 'Б' else f'{size} Б'
        size /= 1024


class BackupPage(QWidget):
    restore_requested = Signal(object)
    restore_finished = Signal()
    close_requested = Signal()

    def __init__(self, application, settings=None, parent=None):
        super().__init__(parent)
        self.application = application
        self.service = application.backups if application is not None else None
        self.settings = settings
        self.future = None
        self.operation = None
        self.results = ()
        self._closing = False
        self._notice = ''
        self._activated = False
        self._restore_preparing = False
        self._restart_locked = False
        self.directory = self.service.default_directory if self.service is not None else None
        if settings is not None:
            saved = settings.value(DIRECTORY_KEY, '')
            if isinstance(saved, str) and saved and Path(saved).is_absolute() and '..' not in Path(saved).parts:
                self.directory = Path(saved)

        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        self.scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 6, 0, 8)
        layout.setSpacing(12)
        heading = label('Резервные копии')
        role(heading,'sectionTitle')
        layout.addWidget(heading)
        heading.setToolTip('Проверенные локальные копии и восстановление с защитной копией текущих данных.')
        self.directory_label = label()
        self.directory_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.directory_details=Disclosure("Каталог сохранения",self.directory_label)
        layout.addWidget(self.directory_details)
        controls = QHBoxLayout()
        self.create_button = QPushButton('Создать резервную копию')
        self.create_button.setObjectName('createBackup')
        self.create_button.setProperty('kind','primary')
        self.create_button.setIcon(action_icon('archive'))
        self.create_button.clicked.connect(self.create)
        controls.addWidget(self.create_button)
        self.refresh_button = QPushButton('Обновить список')
        icon_button(self.refresh_button,'refresh','Обновить список копий')
        self.refresh_button.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_button)
        controls.addStretch()
        layout.addLayout(controls)
        self.status = label('Откройте страницу, чтобы проверить доступные копии.')
        self.status.setAccessibleName('Состояние резервирования')
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setAccessibleName('Прогресс резервирования')
        self.progress.hide()
        layout.addWidget(self.progress)
        self.error = label()
        role(self.error,'notice')
        self.error.hide()
        layout.addWidget(self.error)
        self.settings_error = label()
        self.settings_error.hide()
        layout.addWidget(self.settings_error)
        self.summary = label('Проверенных копий: 0')
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 3)
        self.table.setObjectName('backupList')
        self.table.setAccessibleName('Доступные резервные копии')
        self.table.setHorizontalHeaderLabels(['Дата создания', 'Размер', 'Проверка'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        quiet_table(self.table)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(160)
        self.table.setMaximumHeight(320)
        self.table.itemSelectionChanged.connect(self._controls)
        layout.addWidget(self.table, 1)
        self.open_button = QPushButton('Открыть расположение копии')
        icon_button(self.open_button,'folder','Открыть расположение копии')
        self.open_button.clicked.connect(self.open_location)
        actions = QHBoxLayout()
        actions.addWidget(self.open_button)
        self.restore_button = QPushButton('Восстановить')
        self.restore_button.setObjectName('restoreBackup')
        self.restore_button.clicked.connect(self.restore)
        actions.addWidget(self.restore_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.restart_button = QPushButton('Закрыть для перезапуска')
        self.restart_button.clicked.connect(self.close_requested.emit)
        self.restart_button.hide()
        layout.insertWidget(layout.indexOf(self.status) + 1, self.restart_button, 0, Qt.AlignmentFlag.AlignLeft)
        note=role(label('При создании выберите папку. Старые копии остаются на своих местах.'),'secondary')
        layout.addWidget(note)
        layout.addStretch(1)
        scroll.setWidget(body)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self._directory_text()
        if self.service is None:
            self.status.setText('Резервирование недоступно в текущем запуске.')
        self._controls()

    def _directory_text(self):
        self.directory_details.toggle.setText("Каталог · "+self.directory.name if self.directory else "Каталог не задан")
        self.directory_label.setToolTip(str(self.directory) if self.directory else '')
        self.directory_label.setText(f'Каталог копий: {self.directory}' if self.directory is not None
                                     else 'Каталог копий не задан.')

    def _error(self, text):
        self.error.setText(text)
        self.error.setVisible(bool(text))

    def _controls(self):
        idle = not self._closing and not self._restore_preparing and not self._restart_locked and self.future is None and self.service is not None and not self.service.busy
        available = self.application is not None and self.application.storage_available
        self.create_button.setEnabled(idle and available)
        self.refresh_button.setEnabled(idle and self.directory is not None)
        selected = 0 <= self.table.currentRow() < len(self.results)
        self.open_button.setEnabled(not self._closing and selected)
        self.restore_button.setEnabled(idle and available and selected and self.service.can_restore)

    def activate(self):
        # Возврат на страницу не должен стирать ошибку прошлой попытки.
        if not self._activated:
            self._activated = True
            self.refresh()

    def refresh(self, checked=False, *, preserve_notice=False):
        if self._closing or self.future is not None or self.service is None or self.directory is None:
            return
        if not preserve_notice:
            self._notice = ''
        self._error('')
        try:
            self.future = self.service.scan(self.directory)
            self.operation = 'scan'
            self.progress.setRange(0, 0)
            self.progress.show()
            self.status.setText(self._notice + ' Проверяем список копий…' if self._notice else 'Проверяем список копий…')
        except Exception:
            self._error('Не удалось проверить список копий. Повторите попытку.')
        self._controls()

    def create(self):
        if not self.create_button.isEnabled():
            return
        selected = QFileDialog.getExistingDirectory(self, 'Куда сохранить резервную копию', str(self.directory))
        if not selected:
            return
        try:
            request = BackupRequest(Path(selected))
            future = self.service.create(request)
        except Exception:
            self._error('Не удалось начать создание копии. Проверьте выбранную папку и повторите попытку.')
            return
        if request.directory != self.directory:
            self.results = ()
            self._render()
        self.directory = request.directory
        self._directory_text()
        if self.settings is not None:
            self.settings.setValue(DIRECTORY_KEY, str(self.directory))
            self.settings.sync()
            message = '' if self.settings.status() is QSettings.Status.NoError else 'Не удалось запомнить каталог. При следующем запуске выберите его снова.'
            self.settings_error.setText(message)
            self.settings_error.setVisible(bool(message))
        self._notice = ''
        self._error('')
        self.future = future
        self.operation = 'create'
        self.progress.setRange(0, 0)
        self.progress.show()
        self.status.setText('Подготавливаем резервную копию…')
        self._controls()

    def restore(self):
        if not self.restore_button.isEnabled():
            return
        result = self.results[self.table.currentRow()]
        metadata = result.metadata
        box = QMessageBox(QMessageBox.Icon.Warning,'Восстановить резервную копию?',
            'Текущие данные будут полностью заменены выбранной копией.\n\n'
            f'Дата: {metadata.created_at_utc.astimezone().strftime("%d.%m.%Y %H:%M:%S")}\n'
            f'Размер: {file_size(metadata.size_bytes)}\nСтатус: {self.table.item(self.table.currentRow(), 2).text()}, перед заменой будет повторная проверка.\n\n'
            'Сначала будет сохранена копия текущего состояния. После операции потребуется перезапуск.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,self)
        box.button(QMessageBox.StandardButton.Yes).setText('Восстановить')
        box.button(QMessageBox.StandardButton.No).setText('Отмена')
        box.setDefaultButton(QMessageBox.StandardButton.No)
        style_message_box(box)
        answer=box.exec()
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._restore_preparing = True
        self._error('')
        self.status.setText('Завершаем текущие операции перед восстановлением…')
        self.progress.setRange(0, 0)
        self.progress.show()
        self._controls()
        self.scroll.ensureWidgetVisible(self.status)
        self.restore_requested.emit(RestoreRequest(result, self.directory))

    def start_restore(self, request):
        try:
            self.future = self.service.restore(request)
            self.operation = 'restore'
        except Exception:
            self.restore_preparation_failed()

    def restore_preparation_failed(self):
        self._restore_preparing = False
        self.progress.hide()
        self.status.setText('Восстановление не началось.')
        self._error('Не удалось завершить текущие операции. Проверьте сообщения и повторите попытку.')
        self._controls()
        self.restore_finished.emit()

    def _render(self, *, verified=True):
        self.table.setRowCount(len(self.results))
        self.table.setMinimumHeight(0)
        self.table.setFixedHeight(self.table.horizontalHeader().height()+max(1,min(6,len(self.results)))*38+8)
        for row, result in enumerate(self.results):
            value = result.metadata
            texts = (value.created_at_utc.astimezone().strftime('%d.%m.%Y %H:%M:%S'),
                     file_size(value.size_bytes), 'Проверена' if verified else 'Проверка не обновлена')
            for column, text in enumerate(texts):
                item = QTableWidgetItem(text)
                if column==0:item.setIcon(action_icon('archive'))
                item.setToolTip(str(result.directory))
                self.table.setItem(row, column, item)
        self.summary.setText(f'Проверенных копий: {len(self.results)}' if verified else 'Список не удалось проверить повторно.')
        if self.results:
            self.table.selectRow(0)
        self._controls()

    def poll(self):
        if self.future is not None and self.future.done():
            future, operation = self.future, self.operation
            self.future = None
            self.progress.hide()
            try:
                result = future.result()  # Только завершённый Future; GUI не ждёт worker.
            except Exception:
                if operation == 'restore':
                    self._restore_preparing = False
                    self._restart_locked = self.application.restart_required or self.application.recovery_required
                    self.restart_button.setVisible(self._restart_locked)
                    self.status.setText('Восстановление не завершено.')
                    self._error('Не удалось восстановить выбранную копию. Имеющиеся защитные файлы не удаляются. '
                                + ('Закройте приложение; перед продолжением требуется проверка и перезапуск.' if self._restart_locked
                                   else 'Текущая база остаётся доступной. Обновите список и повторите попытку.'))
                    self.restore_finished.emit()
                elif operation == 'create':
                    self.status.setText('Копия не подтверждена. Можно повторить попытку.')
                    self._error('Не удалось создать проверенную копию. Проверьте место на диске и доступ к папке. '
                                'Выберите отдельную папку, доступную только вам, и повторите попытку.')
                else:
                    self._render(verified=False)
                    self.status.setText(self._notice or 'Каталог копий недоступен.')
                    self._error('Не удалось проверить список копий. Проверьте доступ к каталогу и нажмите «Обновить список».')
            else:
                if operation == 'restore':
                    self._restore_preparing = False
                    self._restart_locked = True
                    self.restart_button.show()
                    self.status.setText('Данные восстановлены и проверены. Закройте и снова запустите HealthTracker.')
                    self._notice = 'Текущее состояние сохранено в: ' + str(result.safety.directory)
                    self.summary.setText(self._notice)
                    self.restore_finished.emit()
                elif operation == 'create':
                    self.results = (result,) + tuple(item for item in self.results if item.directory != result.directory)
                    self._notice = 'Копия создана и проверена.'
                    self._render()
                    self.status.setText(self._notice)
                    if not self._closing:
                        self.refresh(preserve_notice=True)
                else:
                    self.results = result.copies
                    self._render()
                    self.status.setText(self._notice or ('Доступные копии проверены.' if self.results else 'В этой папке пока нет проверенных копий.'))
                    if result.unverified_count:
                        self._error(f'Не удалось проверить пакеты: {result.unverified_count}. Они не включены в список.')
        elif self.future is not None and self.operation in ('create', 'restore'):
            progress = self.service.progress
            messages = {BackupPhase.WAITING: 'Ожидаем завершения текущих операций…',
                        BackupPhase.COPYING: 'Создаём резервную копию…',
                        BackupPhase.VERIFYING: 'Проверяем целостность копии…',
                        BackupPhase.PUBLISHING: 'Сохраняем проверенную копию…',
                        BackupPhase.COMPLETE: 'Проверяем опубликованную копию…',
                        BackupPhase.RESTORE_PREPARING: 'Проверяем выбранную копию и готовим восстановление…',
                        BackupPhase.RESTORE_REPLACING: 'Заменяем данные и проверяем базу…'}
            text = messages[progress.phase]
            if self.operation == 'restore' and progress.phase not in (BackupPhase.RESTORE_PREPARING, BackupPhase.RESTORE_REPLACING):
                text = 'Сохраняем и проверяем текущее состояние перед заменой…'
            self.status.setText(text)
            if progress.phase is BackupPhase.COPYING and progress.total_pages > 0:
                self.progress.setRange(0, progress.total_pages)
                self.progress.setValue(progress.total_pages - progress.remaining_pages)
            else:
                self.progress.setRange(0, 0)
        self._controls()

    def open_location(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.results):
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.results[row].directory))):
                self._error('Не удалось открыть файловый менеджер. Расположение копии: ' + str(self.results[row].directory))

    def begin_close(self):
        self._closing = True
        self._controls()

    def resume(self):
        self._closing = False
        self._controls()
