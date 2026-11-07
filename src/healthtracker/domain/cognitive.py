"""Три определённых ответа и вычисление индекса известной версии."""

from dataclasses import dataclass

from healthtracker.domain.answers import AnswerStatus, CognitiveAnswer
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.scales import CognitiveDifficulty, get_numeric_scale


COGNITIVE_INDEX_FORMULA_VERSION = 1
COGNITIVE_INDEX_FORMULA_CODE = "cognitive_index"


@dataclass(frozen=True, slots=True)
class CognitiveAssessment:
    learning: CognitiveAnswer
    application: CognitiveAnswer
    speed: CognitiveAnswer
    activity_description: str | None = None
    activity_difficulty: CognitiveDifficulty | None = None
    learning_scale_version: int = 1
    application_scale_version: int = 1
    speed_scale_version: int = 1
    formula_version: int = COGNITIVE_INDEX_FORMULA_VERSION

    def __post_init__(self) -> None:
        for answer in (self.learning, self.application, self.speed):
            if not isinstance(answer, CognitiveAnswer):
                raise DomainValidationError("Необходимо определить все три когнитивных ответа.")
        if self.activity_description is not None:
            if not isinstance(self.activity_description, str):
                raise DomainValidationError("Описание занятия должно быть текстом.")
            if not self.activity_description.strip():
                object.__setattr__(self, "activity_description", None)
        if self.activity_difficulty is not None and not isinstance(
            self.activity_difficulty, CognitiveDifficulty
        ):
            raise DomainValidationError("Неизвестная категория сложности занятия.")
        for code, version in (
            ("learning", self.learning_scale_version),
            ("application", self.application_scale_version),
            ("speed", self.speed_scale_version),
        ):
            get_numeric_scale(code, version)
        if (
            type(self.formula_version) is not int
            or self.formula_version != COGNITIVE_INDEX_FORMULA_VERSION
        ):
            raise DomainValidationError("Версия формулы индекса не поддерживается.")


def cognitive_index(assessment: CognitiveAssessment) -> float | None:
    """Равное среднее трёх чисел, без округления и без поправки на контекст."""
    if not isinstance(assessment, CognitiveAssessment):
        raise DomainValidationError("Ожидается определённая когнитивная оценка.")
    answers = (assessment.learning, assessment.application, assessment.speed)
    if any(answer.status is not AnswerStatus.NUMERIC for answer in answers):
        return None
    return (assessment.learning.value + assessment.application.value
            + assessment.speed.value) / 3
