"""Ночной сон: два момента, производная длительность, подтверждение >16 ч."""
from PySide6.QtWidgets import QLabel, QMessageBox

from healthtracker.presentation.theme import style_message_box
from healthtracker.domain.errors import DomainValidationError
from healthtracker.presentation.forms.common import EntryDialog, MomentInput, SaveCancelled


class SleepDialog(EntryDialog):
    kind = "sleep"

    def __init__(self, service, *, record_id=None, parent=None):
        super().__init__(service, record_id=record_id, parent=parent)
        self.setWindowTitle("Ночной сон")
        old = service.get(self.kind, record_id).value if record_id is not None else None
        self.form.addWidget(QLabel("Начало сна"))
        self.start = MomentInput(old.interval.start if old else None, initially_empty=True)
        self.start.placeholder.setAccessibleName("Указать начало сна")
        self.start.edit.setAccessibleName("Начало сна")
        self.form.addWidget(self.start)
        self.form.addWidget(QLabel("Окончание сна / пробуждение"))
        self.end = MomentInput(old.interval.end if old else None,
                               zone=self.start.zone, initially_empty=True)
        self.end.placeholder.setAccessibleName("Указать пробуждение")
        self.end.edit.setAccessibleName("Окончание сна / пробуждение")
        self.form.addWidget(self.end)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.form.addWidget(self.preview)
        self.form.addStretch()
        self.start.changed.connect(self.update_preview)
        self.end.changed.connect(self.update_preview)
        self.update_preview()
        self.finish_setup()

    def state(self):
        return self.start.state(), self.end.state()

    def update_preview(self):
        try:
            interval = self.service.sleep_interval(self.start.moment(), self.end.moment())
            self.preview.setText(f"Длительность: {interval.duration}. "
                f"Дата пробуждения: {interval.date_in(self.end.zone):%d.%m.%Y}.")
        except DomainValidationError as error:
            self.preview.setText(str(error))

    def confirm_long_sleep(self, interval):
        box = QMessageBox(QMessageBox.Icon.Warning, "Необычно длинный сон",
            f"Длительность {interval.duration} превышает 16 часов. Сохранить этот интервал?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        box.button(QMessageBox.StandardButton.Yes).setText("Сохранить")
        box.button(QMessageBox.StandardButton.No).setText("Вернуться к форме")
        box.setDefaultButton(QMessageBox.StandardButton.No)
        style_message_box(box)
        return box.exec() == QMessageBox.StandardButton.Yes

    def persist(self):
        start, end = self.start.moment(), self.end.moment()
        interval = self.service.sleep_interval(start, end)
        confirmed = False
        if interval.requires_confirmation:
            confirmed = self.confirm_long_sleep(interval)
            if not confirmed:
                raise SaveCancelled()
        return self.service.save_sleep(start=start, end=end, record_id=self.record_id,
                                       long_sleep_confirmed=confirmed)
