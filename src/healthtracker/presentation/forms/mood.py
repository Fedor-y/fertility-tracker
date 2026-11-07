"""Самостоятельная оценка настроения без связи с другими наблюдениями."""
from PySide6.QtWidgets import QLabel

from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.scales import get_numeric_scale
from healthtracker.presentation.forms.common import EntryDialog, MomentInput, ScoreChoice


class MoodDialog(EntryDialog):
    kind = "mood"

    def __init__(self, service, *, record_id=None, parent=None):
        super().__init__(service, record_id=record_id, parent=parent)
        self.setWindowTitle("Настроение")
        old = service.get(self.kind, record_id).value if record_id is not None else None
        self.form.addWidget(QLabel("Настроение в момент наблюдения"))
        self.score = ScoreChoice(get_numeric_scale("mood", old.scale_version if old else 1))
        self.score.choice.setAccessibleName("Оценка настроения")
        if old:
            self.score.set_value(old.score)
        self.form.addWidget(self.score)
        self.form.addWidget(QLabel("Момент наблюдения"))
        self.moment = MomentInput(old.observed_at if old else None)
        self.form.addWidget(self.moment)
        self.form.addStretch()
        self.finish_setup()

    def state(self):
        return (self.score.choice.currentIndex(), self.moment.state())

    def persist(self):
        score = self.score.choice.currentData()
        if score is None:
            raise DomainValidationError("Укажите оценку настроения.")
        return self.service.save_mood(score=score, observed_at=self.moment.moment(),
                                      record_id=self.record_id)
