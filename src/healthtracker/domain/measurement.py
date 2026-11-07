"""Когнитивное наблюдение: ответы, оцениваемый час и отдельные служебные моменты."""

from dataclasses import dataclass
from datetime import datetime

from healthtracker.domain.cognitive import CognitiveAssessment
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.intervals import CognitiveInterval
from healthtracker.domain.time import as_utc


@dataclass(frozen=True, slots=True)
class CognitiveMeasurement:
    assessment: CognitiveAssessment
    interval: CognitiveInterval
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.assessment, CognitiveAssessment):
            raise DomainValidationError("Необходимы три определённых ответа.")
        if not isinstance(self.interval, CognitiveInterval):
            raise DomainValidationError("Необходим определённый оцениваемый час.")
        created, updated = as_utc(self.created_at), as_utc(self.updated_at)
        if updated < created:
            raise DomainValidationError("Изменение записи не может предшествовать её созданию.")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "updated_at", updated)
