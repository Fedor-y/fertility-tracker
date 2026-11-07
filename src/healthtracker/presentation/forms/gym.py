"""Дневная отметка спортзала без времени и иных видов активности."""
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDialogButtonBox, QLabel, QPushButton, QWidget,
)

from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.scales import get_numeric_scale
from healthtracker.presentation.forms.common import EntryDialog, ScoreChoice


class GymDialog(EntryDialog):
    kind = "gym"

    def __init__(self, service, *, record_id=None, parent=None):
        super().__init__(service, record_id=record_id, parent=parent)
        self.setWindowTitle("Спортзал")
        old = service.get(self.kind, record_id).value if record_id is not None else None
        self.form.addWidget(QLabel("Дата отметки (без времени тренировки)"))
        self.date_selected = False
        self.date_button = QPushButton("Указать дату")
        self.date_button.setAutoDefault(False)
        self.date_button.clicked.connect(lambda: self.set_date(QDate.currentDate().toPython()))
        self.form.addWidget(self.date_button)
        self.entry_date = QDateEdit()
        self.entry_date.setDateRange(QDate(1, 1, 1), QDate(9999, 12, 31))
        self.entry_date.setCalendarPopup(True)
        self.entry_date.setDisplayFormat("dd.MM.yyyy")
        self.entry_date.setAccessibleName("Дата отметки спортзала")
        self.entry_date.hide()
        self.form.addWidget(self.entry_date)
        self.form.addWidget(QLabel("Посещение спортзала"))
        self.attended = QComboBox()
        self.attended.setAccessibleName("Посещение спортзала")
        self.attended.addItem("Выберите ответ", None)
        self.attended.addItem("Был", True)
        self.attended.addItem("Не был", False)
        self.form.addWidget(self.attended)
        self.form.addWidget(QLabel("Сложность тренировки (обязательна, если был)"))
        version = old.difficulty_scale_version if old and old.attended else 1
        self.difficulty = ScoreChoice(get_numeric_scale("gym_difficulty", version))
        self.difficulty.choice.setAccessibleName("Сложность тренировки")
        self.form.addWidget(self.difficulty)
        hint = QLabel("При ответе «Не был» сложность отсутствует. День без записи — нет сведений.")
        hint.setWordWrap(True)
        self.form.addWidget(hint)
        self.form.addStretch()
        self.attended.currentIndexChanged.connect(self._attendance_changed)
        if old:
            self.set_date(old.entry_date)
            self.attended.setCurrentIndex(self.attended.findData(old.attended))
            if old.attended:
                self.difficulty.set_value(old.difficulty)
        self._attendance_changed()
        controls = [self.date_button, self.entry_date, self.attended, self.difficulty.choice,
            self.buttons.button(QDialogButtonBox.StandardButton.Save),
            self.buttons.button(QDialogButtonBox.StandardButton.Cancel)]
        for first, second in zip(controls, controls[1:]):
            QWidget.setTabOrder(first, second)
        self.finish_setup()

    def set_date(self, value):
        self.entry_date.setDate(QDate(value))
        self.date_selected = True
        self.date_button.hide()
        self.entry_date.show()
        self.entry_date.setFocus()

    def _attendance_changed(self):
        enabled = self.attended.currentData() is True
        self.difficulty.setEnabled(enabled)
        if not enabled:
            self.difficulty.set_value(None)

    def state(self):
        return (self.entry_date.date().toString("yyyy-MM-dd") if self.date_selected else None,
                self.attended.currentIndex(), self.difficulty.choice.currentIndex())

    def persist(self):
        if not self.date_selected:
            raise DomainValidationError("Укажите дату отметки спортзала.")
        attended = self.attended.currentData()
        if attended is None:
            raise DomainValidationError("Выберите «Был» или «Не был».")
        difficulty = self.difficulty.choice.currentData() if attended else None
        if attended and difficulty is None:
            raise DomainValidationError("Укажите сложность тренировки.")
        return self.service.save_gym(entry_date=self.entry_date.date().toPython(),
            attended=attended, difficulty=difficulty, record_id=self.record_id)
