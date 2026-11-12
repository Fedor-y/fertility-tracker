"""Общие элементы диалогов; без SQL и вычисления показателей."""
from datetime import UTC, date, datetime, time
import re
from zoneinfo import ZoneInfo

from PySide6.QtCore import QDate, QDateTime, QTime, QTimeZone, QTimer, Qt, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QDateTimeEdit, QDialog, QDialogButtonBox, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)
from healthtracker.presentation.theme import apply_theme, role, compact_combo, style_calendar, Disclosure, style_message_box
from healthtracker.application.errors import StorageError, RecordNotFound
from healthtracker.presentation.record_actions import confirm_record_delete
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.time import local_time_candidates, resolve_local_time


class ScoreChoice(QWidget):
    def __init__(self, scale, *, special=False):
        super().__init__()
        self.choice = QComboBox()
        self.choice.addItem("Выберите ответ", None)
        for value in range(11):
            self.choice.addItem(str(value), value)
            self.choice.setItemData(value + 1, scale.describe(value), Qt.ItemDataRole.ToolTipRole)
        if special:
            from healthtracker.domain.answers import AnswerStatus
            for status in (AnswerStatus.NOT_ENGAGED, AnswerStatus.CANNOT_ASSESS):
                self.choice.addItem(status.label, status)
        self.description = role(QLabel(),'secondary')
        self.description.setWordWrap(True)
        self.description.hide()
        self.scale = scale
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.choice)
        layout.addWidget(self.description)
        self.choice.currentIndexChanged.connect(self._description)

    def _description(self):
        value = self.choice.currentData()
        self.description.setText(self.scale.describe(value) if type(value) is int else "")
        self.description.setVisible(bool(self.description.text()))

    def set_value(self, value):
        self.choice.setCurrentIndex(self.choice.findData(value))


class MomentInput(QWidget):
    changed = Signal()

    def __init__(self, moment=None, *, zone=None, initially_empty=False):
        super().__init__()
        self.requested_date = None
        self.zone = zone or ZoneInfo(bytes(QTimeZone.systemTimeZoneId()).decode())
        self.edit = QDateTimeEdit()
        self.edit.setTimeZone(QTimeZone.utc())
        self.edit.setDisplayFormat("dd.MM.yyyy HH:mm:ss")
        self.edit.setCalendarPopup(True)
        self.offset = QComboBox()
        self.offset.setAccessibleName("UTC-смещение повторяющегося часа")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.placeholder = QPushButton("Указать дату и время")
        self.placeholder.setAutoDefault(False)
        self.editor = QWidget()
        editor_layout = QVBoxLayout(self.editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.addWidget(self.edit)
        self.date_prompt = QWidget()
        prompt_layout = QVBoxLayout(self.date_prompt)
        prompt_layout.setContentsMargins(0, 0, 0, 0)
        self.date_label = QLabel()
        self.requested_day = QDateEdit()
        self.requested_day.setDateRange(QDate(1,1,1),QDate(9999,12,31))
        self.requested_day.setCalendarPopup(True)
        self.requested_day.setDisplayFormat("dd.MM.yyyy")
        self.requested_day.setAccessibleName("Дата наблюдения")
        self.requested_time = QLineEdit()
        self.requested_time.setPlaceholderText("Время ЧЧ:ММ или ЧЧ:ММ:СС — введите явно")
        self.requested_time.setAccessibleName("Время наблюдения выбранной даты")
        prompt_layout.addWidget(self.date_label)
        prompt_layout.addWidget(self.requested_day)
        prompt_layout.addWidget(self.requested_time)
        self.date_prompt.hide()
        layout.addWidget(self.date_prompt)
        layout.addWidget(self.placeholder)
        layout.addWidget(self.editor)
        layout.addWidget(self.offset)
        self.requested_time.textChanged.connect(self._requested_changed)
        self.requested_day.dateChanged.connect(self._requested_day_changed)
        self.placeholder.clicked.connect(self._begin_input)
        self.edit.dateTimeChanged.connect(self._candidates)
        self.edit.dateTimeChanged.connect(lambda: self.changed.emit())
        self.offset.currentIndexChanged.connect(lambda: self.changed.emit())
        self._original = moment
        self.set_moment(moment or datetime.now(UTC))
        if initially_empty and moment is None:
            self.is_provided = False
            self.editor.hide()
            self.offset.hide()
            self.placeholder.show()

    def _begin_input(self):
        self.set_moment(datetime.now(UTC))
        # Даже если открыли ввод в повторяющийся час, выбор смещения явный.
        self._candidates()
        self.changed.emit()
        self.edit.setFocus()

    def request_date(self, day):
        if type(day) is not date:
            raise DomainValidationError("Необходима календарная дата.")
        self.requested_date = day
        self._original = None
        self.is_provided = False
        self.date_label.setText("Дата наблюдения; местное время введите явно.")
        self.requested_day.setDate(QDate(day))
        self.requested_time.clear()
        self.editor.hide()
        self.placeholder.hide()
        self.date_prompt.show()
        QWidget.setTabOrder(self.requested_day, self.requested_time)
        QWidget.setTabOrder(self.requested_time, self.offset)
        self._candidates()
        self.changed.emit()

    def _requested_local(self):
        text = self.requested_time.text().strip()
        if not re.fullmatch(r"[0-9]{2}:[0-9]{2}(:[0-9]{2})?", text):
            raise DomainValidationError("Введите время в формате ЧЧ:ММ или ЧЧ:ММ:СС.")
        try:
            return datetime.combine(self.requested_date, time.fromisoformat(text))
        except ValueError:
            raise DomainValidationError("Некорректное местное время.") from None

    def _requested_day_changed(self, value):
        if self.requested_date is not None:
            self.requested_date = value.toPython()
            self._requested_changed()

    def _requested_changed(self):
        if self.requested_date is None:
            return
        try:
            self._requested_local()
            self.is_provided = True
        except DomainValidationError:
            self.is_provided = False
        self._candidates()
        self.changed.emit()

    def state(self):
        if self.requested_date is not None:
            return ("requested", self.requested_date, self.requested_time.text(), self.offset.currentIndex())
        if not self.is_provided:
            return (False,)
        return (True, self.edit.dateTime().toString(), self.offset.currentIndex())

    def local(self):
        if self.requested_date is not None:
            return self._requested_local()
        # Qt не должен разрешать DST автоматически: извлекаем только компоненты.
        value = self.edit.dateTime()
        d, t = value.date(), value.time()
        return datetime(d.year(), d.month(), d.day(), t.hour(), t.minute(), t.second())

    def _candidates(self):
        self.offset.clear()
        try:
            candidates = local_time_candidates(self.local(), self.zone)
        except DomainValidationError:
            candidates = ()
        self.offset.setVisible(len(candidates) > 1)
        self.offset.addItem("Выберите UTC-смещение", None)
        for candidate in candidates:
            offset = candidate.astimezone(self.zone).utcoffset()
            self.offset.addItem(f"UTC{offset.total_seconds()/3600:+g}", offset)

    def set_moment(self, moment):
        self.requested_date = None
        self.date_prompt.hide()
        self.is_provided = True
        self.placeholder.hide()
        self.editor.show()
        local = moment.astimezone(self.zone)
        self.edit.setDateTime(QDateTime(QDate(local.year, local.month, local.day),
            QTime(local.hour, local.minute, local.second), QTimeZone.utc()))
        self._candidates()
        self.offset.setCurrentIndex(self.offset.findData(local.utcoffset()))
        self._initial_local = self.local()
        self._original = moment
        self.changed.emit()

    def moment(self):
        if self.requested_date is not None:
            return resolve_local_time(self._requested_local(), self.zone, utc_offset=self.offset.currentData())
        if not self.is_provided:
            raise DomainValidationError("Укажите дату и время.")
        resolved = resolve_local_time(self.local(), self.zone, utc_offset=self.offset.currentData())
        # Не обрезать микросекунды сохранённого наблюдения при правке иных полей.
        if self._original is not None and self.local() == self._initial_local:
            if resolved.replace(microsecond=0) == self._original.replace(microsecond=0):
                return self._original
        return resolved


class SaveCancelled(Exception):
    """Пользователь отказался от подтверждения; ввод остаётся в форме."""


class EntryDialog(QDialog):
    saved = Signal(str, int)
    deleted = Signal(str, object)

    def __init__(self, service, *, record_id=None, parent=None):
        super().__init__(parent)
        apply_theme(self)
        self.service, self.record_id = service, record_id
        self._saving = False
        self._committed = False
        self.delete_service = None
        self.setModal(True)
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(700, max(300,available.width()-24)), min(680, max(200, available.height() - 40)))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18,16,18,16)
        outer.setSpacing(12)
        self.title_label = role(QLabel(self.windowTitle()),'pageTitle')
        self.windowTitleChanged.connect(self.title_label.setText)
        outer.addWidget(self.title_label)
        scroll = QScrollArea()
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll=scroll
        scroll.setWidgetResizable(True)
        self.body = QWidget()
        self.form = QVBoxLayout(self.body)
        self.form.setContentsMargins(4,4,12,10)
        self.form.setSpacing(8)
        self.form.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.body)
        outer.addWidget(scroll)
        self.error = role(QLabel(),"notice")
        self.error.hide()
        self.error.setWordWrap(True)
        outer.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setProperty('kind','primary')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Закрыть")
        for button in self.buttons.buttons():
            button.setIcon(QIcon())
        self.delete_button = QPushButton('Удалить запись')
        self.delete_button.setToolTip('Удалить эту сохранённую запись после подтверждения')
        self.delete_button.setAutoDefault(False)
        self.buttons.addButton(self.delete_button,QDialogButtonBox.ButtonRole.ActionRole)
        self.delete_button.setVisible(record_id is not None)
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self.delete_record)
        self.buttons.accepted.connect(self.submit)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.submit)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self.submit)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setAutoDefault(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setAutoDefault(False)

    def group_fields(self, start, stop, title, *, expanded=False):
        """Только перенос существующих полей в раскрываемую секцию."""
        content=QWidget()
        layout=QVBoxLayout(content)
        layout.setContentsMargins(0,2,0,4)
        layout.setSpacing(8)
        for _ in range(stop-start):
            item=self.form.takeAt(start)
            widget=item.widget()
            if widget is not None:
                layout.addWidget(widget)
            elif item.layout() is not None:
                layout.addLayout(item.layout())
        section=Disclosure(title,content)
        self.form.insertWidget(start,section)
        section.toggle.setChecked(expanded)
        section.toggle.toggled.connect(lambda:QTimer.singleShot(0,self._fit_content_height))
        return section

    def _fit_content_height(self):
        limit=max(240,self.screen().availableGeometry().height()-40)
        self.resize(self.width(),min(limit,max(320,self.body.sizeHint().height()+130)))

    def finish_setup(self):
        # Одна настройка оформления для добавления и правки всех семи типов.
        for combo in self.body.findChildren(QComboBox):
            if not combo.property('floatingStyled'):
                compact_combo(combo)
                combo.setProperty('floatingStyled',True)
        for i in range(self.form.count()):
            label=self.form.itemAt(i).widget()
            if isinstance(label,QLabel) and not label.property('role'):
                role(label,'fieldTitle')
                label.setWordWrap(True)
        for field in self.body.findChildren(QDateTimeEdit):style_calendar(field)
        self._initial = self.state()
        QTimer.singleShot(0,self._fit_content_height)

    def submit(self):
        if self._saving or self._committed:
            return
        self._saving = True
        self.buttons.setEnabled(False)
        try:
            record_id = self.persist()
        except SaveCancelled:
            pass
        except DomainValidationError as error:
            self.error.setText(str(error))
            self.error.show()
        except StorageError:
            self.error.show()
            self.error.setText("Не удалось сохранить запись. Данные остались в форме. Проверьте доступ к хранилищу и повторите попытку.")
        else:
            self.record_id = record_id
            self._committed = True
            self.saved.emit(self.kind, record_id)
            self.accept()
        finally:
            self._saving = False
            self.buttons.setEnabled(True)

    def enable_deletion(self, service):
        self.delete_service = service
        self.delete_button.setEnabled(service is not None and self.record_id is not None)

    def confirm_delete(self):
        return confirm_record_delete(self,self.kind,unsaved=self.state()!=self._initial)

    def delete_record(self):
        if self._saving or self._committed or self.record_id is None or self.delete_service is None:
            return
        self._saving = True
        self.buttons.setEnabled(False)
        try:
            if not self.confirm_delete():
                return
            self.delete_service.delete(self.kind,self.record_id,confirmed=True)
        except RecordNotFound:
            self.error.setText('Запись уже удалена или недоступна. Закройте окно и обновите дневник.')
            self.error.show()
        except (StorageError,DomainValidationError):
            self.error.setText('Не удалось удалить запись. Данные остались в форме. Повторите попытку.')
            self.error.show()
        else:
            self._committed = True
            self.deleted.emit(self.kind,self.record_id)
            self.accept()
        finally:
            self._saving = False
            self.buttons.setEnabled(True)

    def confirm_discard(self):
        box=QMessageBox(QMessageBox.Icon.Warning,"Несохранённые изменения","Закрыть форму без сохранения?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,self)
        box.button(QMessageBox.StandardButton.Discard).setText("Закрыть без сохранения")
        box.button(QMessageBox.StandardButton.Cancel).setText("Продолжить ввод")
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        style_message_box(box)
        return box.exec()==QMessageBox.StandardButton.Discard

    def reject(self):
        if self._committed or self.state() == self._initial or self.confirm_discard():
            super().reject()

    def closeEvent(self, event):
        if self._committed or self.state() == self._initial or self.confirm_discard():
            QDialog.reject(self)
            event.accept()
        else:
            event.ignore()
