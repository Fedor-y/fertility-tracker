from PySide6.QtWidgets import QComboBox, QLabel, QTextEdit
from healthtracker.domain.answers import AnswerStatus, CognitiveAnswer
from healthtracker.domain.cognitive import CognitiveAssessment
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.scales import CognitiveDifficulty, get_numeric_scale
from healthtracker.presentation.forms.common import EntryDialog, MomentInput, ScoreChoice


class CognitiveDialog(EntryDialog):
    kind = "cognitive"

    def __init__(self, service, *, record_id=None, parent=None):
        super().__init__(service, record_id=record_id, parent=parent)
        self.setWindowTitle("Когнитивное состояние")
        old = service.get(self.kind, record_id).value if record_id is not None else None
        self.answers = []
        for code, title in (("learning", "Запоминание нового"), ("application", "Воспроизведение и применение знаний"), ("speed", "Скорость мышления")):
            version = getattr(old.assessment, code + "_scale_version") if old else 1
            field = ScoreChoice(get_numeric_scale(code, version), special=True)
            field.choice.setAccessibleName(title)
            self.form.addWidget(QLabel(title))
            self.form.addWidget(field)
            self.answers.append(field)
            if old:
                answer = getattr(old.assessment, code)
                field.set_value(answer.value if answer.status is AnswerStatus.NUMERIC else answer.status)
        self.form.addWidget(QLabel("Описание занятия (необязательно)"))
        self.context = QTextEdit()
        self.context.setMaximumHeight(85)
        self.context.setPlainText(old.assessment.activity_description or "" if old else "")
        self.form.addWidget(self.context)
        self.difficulty = QComboBox()
        self.difficulty.addItem("Сложность не указана", None)
        for difficulty in CognitiveDifficulty:
            self.difficulty.addItem(difficulty.value, difficulty)
        if old:
            self.difficulty.setCurrentIndex(self.difficulty.findData(old.assessment.activity_difficulty))
        self.form.addWidget(self.difficulty)
        self.form.addWidget(QLabel("Конец оцениваемого часа"))
        self.moment = MomentInput(old.interval.end if old else None)
        self.form.addWidget(self.moment)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.form.addWidget(self.preview)
        for field in self.answers:
            field.choice.currentIndexChanged.connect(self.update_preview)
        self.moment.changed.connect(self.update_preview)
        self.moment.offset.currentIndexChanged.connect(self.update_preview)
        self.update_preview()
        self.finish_setup()

    def assessment(self):
        answers = []
        for field in self.answers:
            value = field.choice.currentData()
            if value is None:
                raise DomainValidationError("Определите все три когнитивных ответа.")
            answers.append(CognitiveAnswer.numeric(value) if type(value) is int else CognitiveAnswer(AnswerStatus(value)))
        return CognitiveAssessment(*answers, activity_description=self.context.toPlainText(),
                                   activity_difficulty=CognitiveDifficulty(self.difficulty.currentData()) if self.difficulty.currentData() is not None else None)

    def update_preview(self):
        try:
            interval = self.service.cognitive_interval(self.moment.moment())
            start = interval.start.astimezone(self.moment.zone).strftime("%d.%m.%Y %H:%M:%S %z")
        except DomainValidationError as error:
            self.preview.setText(str(error))
            return
        try:
            _, index = self.service.cognitive_preview(self.assessment(), self.moment.moment())
            detail = f"Индекс: {index:.2f}" if index is not None else "Индекс не рассчитывается."
        except DomainValidationError:
            detail = "Определите все три ответа."
        self.preview.setText(f"Начало часа: {start}. {detail}")

    def state(self):
        return (tuple(f.choice.currentIndex() for f in self.answers), self.context.toPlainText(),
                self.difficulty.currentIndex(), self.moment.state())

    def persist(self):
        return self.service.save_cognitive(self.assessment(), self.moment.moment(), self.record_id)
