"""Определённый когнитивный ответ. Незаполненность представляется отдельно None."""

from dataclasses import dataclass
from enum import StrEnum

from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.scales import validate_score


class AnswerStatus(StrEnum):
    NUMERIC = "numeric"
    NOT_ENGAGED = "not_engaged"
    CANNOT_ASSESS = "cannot_assess"

    @property
    def label(self) -> str:
        return {
            AnswerStatus.NUMERIC: "Числовая оценка",
            AnswerStatus.NOT_ENGAGED: "Не занимался",
            AnswerStatus.CANNOT_ASSESS: "Не могу оценить",
        }[self]


@dataclass(frozen=True, slots=True)
class CognitiveAnswer:
    status: AnswerStatus
    value: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, AnswerStatus):
            raise DomainValidationError("Необходимо явно выбрать статус ответа.")
        if self.status is AnswerStatus.NUMERIC:
            validate_score(self.value)
        elif self.value is not None:
            raise DomainValidationError("Специальный ответ не содержит числовую оценку.")

    @classmethod
    def numeric(cls, value: int) -> CognitiveAnswer:
        return cls(AnswerStatus.NUMERIC, value)
