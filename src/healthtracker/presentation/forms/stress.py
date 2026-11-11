"""Добровольное наблюдение стресса; сохранение только через Application."""
from PySide6.QtWidgets import QCheckBox, QLabel, QTextEdit

from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.scales import get_numeric_scale
from healthtracker.presentation.forms.common import EntryDialog, MomentInput, ScoreChoice


class StressDialog(EntryDialog):
    kind = "stress"

    def __init__(self, service, *, record_id=None, parent=None):
        super().__init__(service, record_id=record_id, parent=parent)
        self.setWindowTitle("Стресс")
        old = service.get(self.kind, record_id).value if record_id is not None else None
        self.form.addWidget(QLabel("Сила внутреннего переживания стресса"))
        self.score = ScoreChoice(get_numeric_scale("stress", old.scale_version if old else 1))
        self.score.choice.setAccessibleName("Оценка стресса")
        if old:
            self.score.set_value(old.score)
        self.form.addWidget(self.score)
        self.form.addWidget(QLabel("Предполагаемые причины (необязательно)"))
        self.causes = {}
        for code, label in service.stress_causes():
            check = QCheckBox(label)
            check.setChecked(old is not None and code in old.causes)
            self.causes[code] = check
            self.form.addWidget(check)
        self.form.addWidget(QLabel("Комментарий (необязательно)"))
        self.comment = QTextEdit()
        self.comment.setMaximumHeight(110)
        self.comment.setPlainText(old.comment or "" if old else "")
        self.form.addWidget(self.comment)
        note = QLabel("При сохранении оценки 0 причины и комментарий будут очищены.")
        note.setWordWrap(True)
        self.form.addWidget(note)
        self.form.addWidget(QLabel("Момент наблюдения"))
        self.moment = MomentInput(old.observed_at if old else None)
        self.form.addWidget(self.moment)
        self.causes_section=self.group_fields(2,self.form.indexOf(self.moment)-2,"Причины и комментарий",expanded=old is not None)
        self.finish_setup()

    def state(self):
        return (self.score.choice.currentIndex(),
                tuple(check.isChecked() for check in self.causes.values()),
                self.comment.toPlainText(), self.moment.state())

    def persist(self):
        score = self.score.choice.currentData()
        if score is None:
            raise DomainValidationError("Укажите оценку стресса.")
        return self.service.save_stress(score=score, observed_at=self.moment.moment(),
            causes=tuple(code for code, check in self.causes.items() if check.isChecked()),
            comment=self.comment.toPlainText(), record_id=self.record_id)
