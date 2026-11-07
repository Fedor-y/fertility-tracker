"""Дневник выбранной даты: существующие записи, без отчётов и аналитики."""
from zoneinfo import ZoneInfo
from html import escape

from PySide6.QtCore import QDate, QTimeZone, QTimer, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QDateEdit, QHeaderView, QHBoxLayout, QLabel, QMenu,
    QMessageBox, QPushButton, QToolButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)
from healthtracker.application.diary import KINDS, TITLES
from healthtracker.presentation.theme import role
from healthtracker.application.errors import RecordNotFound, StorageError
from healthtracker.domain.errors import DomainValidationError


def system_zone():
    return ZoneInfo(bytes(QTimeZone.systemTimeZoneId()).decode())


class DiaryPage(QWidget):
    open_requested = Signal(str, int)
    add_requested = Signal(str, object)
    deleted = Signal(str, int)

    def __init__(self, service=None, *, zone_provider=system_zone, parent=None):
        super().__init__(parent)
        self.service = service
        self.zone_provider = zone_provider
        self.zone = zone_provider()
        self._deleting = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,6,0,0)
        layout.setSpacing(12)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Дата дневника"))
        self.entry_date = QDateEdit(QDate.currentDate())
        self.entry_date.setDateRange(QDate(1,1,1), QDate(9999,12,31))
        self.entry_date.setCalendarPopup(True)
        self.entry_date.setDisplayFormat("dd.MM.yyyy")
        self.entry_date.setAccessibleName("Дата дневника")
        toolbar.addWidget(self.entry_date)
        self.add_button = QToolButton()
        self.add_button.setText("Добавить за эту дату")
        self.add_menu = QMenu(self.add_button)
        self.add_actions = {}
        for kind in KINDS:
            action = self.add_menu.addAction(TITLES[kind])
            action.triggered.connect(lambda checked=False, k=kind: self.add_requested.emit(k, self.entry_date.date().toPython()))
            self.add_actions[kind] = action
        self.add_button.setMenu(self.add_menu)
        self.add_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        toolbar.addWidget(self.add_button)
        self.refresh_button = QPushButton("Обновить")
        toolbar.addWidget(self.refresh_button)
        layout.addLayout(toolbar)
        self.zone_notice = QLabel()
        self.zone_notice.setWordWrap(True)
        layout.addWidget(self.zone_notice)
        self.status = role(QLabel(),'secondary')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.records = QTreeWidget()
        self.records.setHeaderLabels(["Местное время", "Тип записи", "Краткое содержание"])
        self.records.setRootIsDecorated(False)
        self.records.setWordWrap(True)
        self.records.setAlternatingRowColors(True)
        self.records.setIndentation(12)
        self.records.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.records.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.records.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.records.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.records.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.records,1)
        actions = QHBoxLayout()
        self.open_button = QPushButton("Открыть / изменить")
        self.delete_button = QPushButton("Удалить")
        actions.addWidget(self.open_button)
        actions.addWidget(self.delete_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.records.itemSelectionChanged.connect(self._selection_changed)
        self.records.itemDoubleClicked.connect(lambda *_: self.open_selected())
        self.entry_date.dateChanged.connect(self.refresh)
        self.refresh_button.clicked.connect(self.refresh)
        self.open_button.clicked.connect(self.open_selected)
        self.delete_button.clicked.connect(self.delete_selected)
        for key, callback in (("Return",self.open_selected),("Delete",self.delete_selected)):
            shortcut = QShortcut(QKeySequence(key), self.records, activated=callback)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self._check_zone)
        self.timer.start()
        self.refresh()

    def selected(self):
        item = self.records.currentItem()
        return item.data(0,Qt.ItemDataRole.UserRole) if item else None

    def _selection_changed(self):
        available = self.selected() is not None and self.service is not None and not self._deleting
        self.open_button.setEnabled(available)
        self.delete_button.setEnabled(available)

    def _zone(self):
        current = self.zone_provider()
        if current != self.zone:
            self.zone_notice.setText("Часовой пояс изменился. Дневник перегруппирован; исходные UTC-моменты не изменены.")
        self.zone = current

    def refresh(self, *_):
        previous = self.selected()
        previous_key = (previous.kind, previous.id) if previous else None
        self.records.clear()
        self._selection_changed()
        self.add_button.setEnabled(self.service is not None)
        if self.service is None:
            self.status.setText("Хранилище недоступно. Дневник не загружен.")
            return False
        try:
            self._zone()
            day = self.service.day(self.entry_date.date().toPython(), self.zone)
        except (StorageError, DomainValidationError):
            self.status.setText("Не удалось загрузить дневник. Повторите попытку; отсутствие данных не подтверждено.")
            return False
        for title, entries in (("С точным временем",day.timed),("События без времени",day.untimed)):
            group = QTreeWidgetItem([title])
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            font=QFont(self.records.font());font.setBold(True)
            group.setFont(0,font)
            self.records.addTopLevelItem(group)
            group.setFirstColumnSpanned(True)
            group.setExpanded(True)
            if not entries:
                empty = QTreeWidgetItem(["Нет сведений"])
                empty.setFlags(Qt.ItemFlag.ItemIsEnabled)
                group.addChild(empty)
            for entry in entries:
                text = entry.moment.astimezone(self.zone).strftime("%H:%M:%S %z") if entry.moment is not None else "Без времени"
                item = QTreeWidgetItem([text,TITLES[entry.kind],entry.summary])
                item.setData(0,Qt.ItemDataRole.UserRole,entry)
                item.setToolTip(2,'<qt>'+escape(entry.summary).replace('\n','<br>')+'</qt>')
                if entry.moment is not None:
                    item.setToolTip(0,entry.moment.astimezone(self.zone).isoformat())
                group.addChild(item)
                if (entry.kind,entry.id)==previous_key:
                    self.records.setCurrentItem(item)
        self.status.setText("Записей за эту дату нет. Отсутствие сведений не означает нулевые оценки или отрицательные ответы."
                            if not day.timed and not day.untimed else "Выберите запись для просмотра, исправления или удаления.")
        self._selection_changed()
        return True

    def _check_zone(self):
        if self.isVisible() and self.zone_provider()!=self.zone:
            self.refresh()

    def showEvent(self,event):
        super().showEvent(event)
        self.refresh()

    def open_selected(self):
        entry = self.selected()
        if entry is not None and not self._deleting:
            self.open_requested.emit(entry.kind,entry.id)

    def confirm_delete(self,entry):
        box = QMessageBox(QMessageBox.Icon.Warning,"Удаление записи",
            f"Удалить запись «{TITLES[entry.kind]}» за {self.entry_date.date().toString('dd.MM.yyyy')}? Это действие необратимо.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,self)
        box.button(QMessageBox.StandardButton.Yes).setText("Удалить")
        box.button(QMessageBox.StandardButton.No).setText("Отмена")
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec()==QMessageBox.StandardButton.Yes

    def delete_selected(self):
        entry = self.selected()
        if entry is None or self._deleting or self.service is None:
            return
        self._deleting = True
        self._selection_changed()
        try:
            if not self.confirm_delete(entry):
                return
            self.service.delete(entry.kind,entry.id,confirmed=True)
        except RecordNotFound:
            self.refresh()
            self.status.setText("Запись уже удалена или недоступна. Список обновлён.")
        except (StorageError, DomainValidationError):
            self.status.setText("Не удалось удалить запись. Успешное удаление не подтверждено; повторите попытку.")
        else:
            loaded = self.refresh()
            self.status.setText("Запись удалена." if loaded else "Запись удалена, но дневник не удалось обновить. Повторите загрузку.")
            self.deleted.emit(entry.kind,entry.id)
        finally:
            self._deleting = False
            self._selection_changed()
