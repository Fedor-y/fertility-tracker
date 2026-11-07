from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton
from healthtracker.domain.catalogs import SYMPTOM_LABELS, SymptomCode, SymptomStatus
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.records import Symptom
from healthtracker.domain.scales import SymptomIntensity, get_numeric_scale
from healthtracker.presentation.forms.common import EntryDialog, MomentInput, ScoreChoice


class PhysicalDialog(EntryDialog):
    kind = "physical"

    def __init__(self, service, *, record_id=None, parent=None):
        super().__init__(service, record_id=record_id, parent=parent)
        self.setWindowTitle("Физическое состояние")
        old = service.get(self.kind, record_id).value if record_id is not None else None
        self.form.addWidget(QLabel("Общее физическое состояние"))
        self.score = ScoreChoice(get_numeric_scale('physical', old.scale_version if old else 1))
        self.score.choice.setAccessibleName("Общее физическое состояние")
        if old:
            self.score.set_value(old.score)
        self.form.addWidget(self.score)
        self.form.addWidget(QLabel("Симптомы (необязательно)"))
        self.symptom_state = SymptomStatus.UNKNOWN
        self.symptom_label = QLabel()
        self.form.addWidget(self.symptom_label)
        actions = QHBoxLayout()
        self.no_symptoms = QPushButton("Симптомов нет")
        self.unknown = QPushButton("Сведения не указаны")
        for button in (self.no_symptoms, self.unknown):
            button.setAutoDefault(False)
            actions.addWidget(button)
        self.form.addLayout(actions)
        self.symptoms = {}
        for code, label in zip(SymptomCode, SYMPTOM_LABELS):
            row = QHBoxLayout()
            check = QCheckBox(label)
            intensity = QComboBox()
            intensity.setAccessibleName(f"Интенсивность: {label}")
            intensity.addItem("Интенсивность не указана", None)
            for value in SymptomIntensity:
                intensity.addItem(value.value, value.value)
            intensity.setEnabled(False)
            row.addWidget(check, 1)
            row.addWidget(intensity, 1)
            self.form.addLayout(row)
            self.symptoms[code] = (check, intensity)
            check.toggled.connect(self._selection_changed)
        self.detail = QLineEdit()
        self.detail.setPlaceholderText("Уточнение симптома «Другое» (необязательно)")
        self.detail.setEnabled(False)
        self.form.addWidget(self.detail)
        self.no_symptoms.clicked.connect(lambda: self._clear(SymptomStatus.NONE_CONFIRMED))
        self.unknown.clicked.connect(lambda: self._clear(SymptomStatus.UNKNOWN))
        self.form.addWidget(QLabel("Момент наблюдения"))
        self.moment = MomentInput(old.observed_at if old else None)
        self.form.addWidget(self.moment)
        if old:
            for symptom in old.symptoms:
                check, intensity = self.symptoms[symptom.code]
                check.setChecked(True)
                intensity.setCurrentIndex(intensity.findData(symptom.intensity.value if symptom.intensity else None))
                if symptom.code is SymptomCode.OTHER:
                    self.detail.setText(symptom.detail or "")
            self.symptom_state = old.symptom_status
        self._state_label()
        self.finish_setup()

    def _state_label(self):
        self.symptom_label.setText({SymptomStatus.LISTED: 'Выбранные симптомы',
            SymptomStatus.NONE_CONFIRMED: 'Подтверждено: симптомов нет',
            SymptomStatus.UNKNOWN: 'Сведения о симптомах отсутствуют'}[self.symptom_state])

    def _selection_changed(self):
        selected = False
        for code, (check, intensity) in self.symptoms.items():
            intensity.setEnabled(check.isChecked())
            if not check.isChecked():
                intensity.setCurrentIndex(0)
            selected |= check.isChecked()
        other = self.symptoms[SymptomCode.OTHER][0].isChecked()
        self.detail.setEnabled(other)
        if not other:
            self.detail.clear()
        self.symptom_state = SymptomStatus.LISTED if selected else SymptomStatus.UNKNOWN
        self._state_label()

    def _clear(self, status):
        for check, _ in self.symptoms.values():
            check.setChecked(False)
        self.symptom_state = status
        self._state_label()

    def state(self):
        return (self.score.choice.currentIndex(), self.symptom_state,
            tuple((check.isChecked(), intensity.currentIndex()) for check, intensity in self.symptoms.values()),
            self.detail.text(), self.moment.state())

    def persist(self):
        score = self.score.choice.currentData()
        if score is None:
            raise DomainValidationError("Укажите общую оценку физического состояния.")
        symptoms = tuple(Symptom(code,
            SymptomIntensity(intensity.currentData()) if intensity.currentData() is not None else None,
            self.detail.text() if code is SymptomCode.OTHER else None)
            for code, (check, intensity) in self.symptoms.items() if check.isChecked())
        return self.service.save_physical(score=score, observed_at=self.moment.moment(),
            symptom_status=self.symptom_state, symptoms=symptoms, record_id=self.record_id)
