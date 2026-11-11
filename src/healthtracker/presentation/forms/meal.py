"""Ручной журнал питания: дата, категория и позиции без времени еды."""
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDialogButtonBox, QGroupBox, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from healthtracker.application.errors import MealDuplicateConfirmationRequired
from healthtracker.domain.catalogs import CaffeineStatus, MealCategory
from healthtracker.domain.errors import DomainValidationError
from healthtracker.presentation.theme import compact_combo, style_message_box
from healthtracker.presentation.forms.common import EntryDialog, SaveCancelled


MEAL_LABELS = (
    "Завтрак", "Обед", "Ужин", "Перекус после завтрака",
    "Перекус после обеда", "Перекус после ужина", "Другое",
)
CAFFEINE_LABELS = (
    (CaffeineStatus.UNSPECIFIED, "Не указано"),
    (CaffeineStatus.CONTAINS, "Содержит"),
    (CaffeineStatus.DOES_NOT_CONTAIN, "Не содержит"),
)


class MealItemEditor(QGroupBox):
    """Редактор полей существующего MealItem, не новая предметная модель."""

    def __init__(self, *, item=None, source_position=None):
        super().__init__()
        self.source_position = source_position
        layout = QVBoxLayout(self)
        self.name = QLineEdit(item.name if item else "")
        self.name.setAccessibleName("Название еды или напитка")
        self.name.setPlaceholderText("Название еды или напитка (обязательно)")
        layout.addWidget(self.name)
        layout.addWidget(QLabel("Состав (необязательно)"))
        self.composition = QTextEdit()
        self.composition.setTabChangesFocus(True)
        self.composition.setMaximumHeight(75)
        self.composition.setPlainText(item.composition or "" if item else "")
        layout.addWidget(self.composition)
        self.quantity = QLineEdit(item.quantity_text or "" if item else "")
        self.quantity.setPlaceholderText("Количество свободным текстом (необязательно)")
        self.quantity.setAccessibleName("Количество")
        layout.addWidget(self.quantity)
        layout.addWidget(QLabel("Кофеин"))
        self.caffeine = QComboBox()
        compact_combo(self.caffeine)
        self.caffeine.setProperty("floatingStyled",True)
        for value, label in CAFFEINE_LABELS:
            self.caffeine.addItem(label, value.value)
        if item:
            self.caffeine.setCurrentIndex(self.caffeine.findData(item.caffeine_status.value))
        layout.addWidget(self.caffeine)
        self.remove_button = QPushButton("Удалить позицию")
        self.remove_button.setAutoDefault(False)
        layout.addWidget(self.remove_button)

    def fields(self):
        return dict(name=self.name.text(), composition=self.composition.toPlainText(),
            quantity_text=self.quantity.text(), caffeine_status=CaffeineStatus(self.caffeine.currentData()),
            source_position=self.source_position)


class MealDialog(EntryDialog):
    kind = "meals"

    def __init__(self, service, *, record_id=None, parent=None):
        super().__init__(service, record_id=record_id, parent=parent)
        self.setWindowTitle("Питание")
        old = service.get(self.kind, record_id).value if record_id is not None else None
        self.form.addWidget(QLabel("Дата приёма пищи (без времени)"))
        self.entry_date = QDateEdit()
        self.entry_date.setDateRange(QDate(1, 1, 1), QDate(9999, 12, 31))
        self.entry_date.setCalendarPopup(True)
        self.entry_date.setDisplayFormat("dd.MM.yyyy")
        self.entry_date.setDate(QDate(old.entry_date) if old else QDate.currentDate())
        self.form.addWidget(self.entry_date)
        self.form.addWidget(QLabel("Категория приёма пищи"))
        self.category = QComboBox()
        self.category.addItem("Выберите категорию", None)
        for value, label in zip(MealCategory, MEAL_LABELS):
            self.category.addItem(label, value.value)
        if old:
            self.category.setCurrentIndex(self.category.findData(old.category.value))
        self.form.addWidget(self.category)
        self.existing_dialog = None
        self.items = []
        self.items_layout = QVBoxLayout()
        self.form.addLayout(self.items_layout)
        if old:
            for position, item in enumerate(old.items):
                self.add_item(item=item, source_position=position)
        else:
            self.add_item()
        self.add_button = QPushButton("Добавить позицию")
        self.add_button.setAutoDefault(False)
        self.add_button.clicked.connect(lambda: self.add_item())
        self.form.addWidget(self.add_button)
        self.form.addWidget(QLabel("Общая заметка (необязательно)"))
        self.note = QTextEdit()
        self.note.setTabChangesFocus(True)
        self.note.setMaximumHeight(90)
        self.note.setPlainText(old.note or "" if old else "")
        self.form.addWidget(self.note)
        self._tab_order()
        self.finish_setup()

    def add_item(self, *, item=None, source_position=None):
        editor = MealItemEditor(item=item, source_position=source_position)
        self.items.append(editor)
        self.items_layout.addWidget(editor)
        editor.show()
        editor.remove_button.clicked.connect(lambda: self.remove_item(editor))
        self._number_items()
        return editor

    def remove_item(self, editor):
        self.items.remove(editor)
        self.items_layout.removeWidget(editor)
        editor.hide()
        editor.deleteLater()
        self._number_items()

    def _number_items(self):
        for position, editor in enumerate(self.items, 1):
            editor.setTitle(f"Позиция {position}")
        if hasattr(self, "note"):
            self._tab_order()

    def _tab_order(self):
        widgets = [self.entry_date, self.category]
        for row in self.items:
            widgets.extend([row.name, row.composition, row.quantity, row.caffeine, row.remove_button])
        widgets.extend([self.add_button, self.note,
            self.buttons.button(QDialogButtonBox.StandardButton.Save),
            self.buttons.button(QDialogButtonBox.StandardButton.Cancel)])
        for first, second in zip(widgets, widgets[1:]):
            QWidget.setTabOrder(first, second)

    def state(self):
        return (self.entry_date.date().toString("yyyy-MM-dd"), self.category.currentIndex(),
                tuple(tuple(row.fields().items()) for row in self.items), self.note.toPlainText())

    def confirm_duplicate(self, record_ids):
        box = QMessageBox(QMessageBox.Icon.Warning, "Повтор категории питания",
            "Эта категория уже записана за выбранную дату. Сохранить ещё одну запись?",
            parent=self)
        save = box.addButton("Сохранить ещё одну запись", QMessageBox.ButtonRole.AcceptRole)
        existing = box.addButton("Открыть существующую", QMessageBox.ButtonRole.ActionRole)
        cancel = box.addButton("Вернуться к форме", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        style_message_box(box)
        box.exec()
        if box.clickedButton() is save:
            return "confirm"
        if box.clickedButton() is existing:
            return "open"
        return "cancel"

    def open_existing(self, record_ids):
        record_id = record_ids[0]
        if len(record_ids) > 1:
            labels = [f"Запись №{value}" for value in record_ids]
            selected, accepted = QInputDialog.getItem(self, "Существующие приёмы пищи",
                "Выберите запись", labels, 0, False)
            if not accepted:
                return
            record_id = record_ids[labels.index(selected)]
        # Исходная заполненная форма остаётся на месте; автоматической замены нет.
        dialog = MealDialog(self.service, record_id=record_id, parent=self)
        dialog.saved.connect(self.saved.emit)
        self.existing_dialog = dialog
        try:
            dialog.exec()
        finally:
            self.existing_dialog = None
            dialog.deleteLater()

    def _close_existing(self):
        dialog = self.existing_dialog
        if dialog is not None and dialog.isVisible():
            dialog.reject()
            return not dialog.isVisible()
        return True

    def reject(self):
        if self._close_existing():
            super().reject()

    def closeEvent(self, event):
        if self._close_existing():
            super().closeEvent(event)
        else:
            event.ignore()

    def persist(self):
        category = self.category.currentData()
        if category is None:
            raise DomainValidationError("Выберите категорию приёма пищи.")
        fields = dict(entry_date=self.entry_date.date().toPython(), category=MealCategory(category),
            items=tuple(row.fields() for row in self.items), note=self.note.toPlainText(),
            record_id=self.record_id)
        try:
            return self.service.save_meal(**fields)
        except MealDuplicateConfirmationRequired as error:
            action = self.confirm_duplicate(error.record_ids)
            if action == "confirm":
                return self.service.save_meal(**fields, duplicate_confirmed=True)
            if action == "open":
                self.open_existing(error.record_ids)
            raise SaveCancelled()
