from healthtracker.domain.answers import AnswerStatus, CognitiveAnswer
from healthtracker.domain.cognitive import CognitiveAssessment
from healthtracker.domain.intervals import CognitiveInterval
from healthtracker.domain.measurement import CognitiveMeasurement
from healthtracker.domain.scales import CognitiveDifficulty
from healthtracker.infrastructure.sqlite.base import RecordRepository
from healthtracker.infrastructure.sqlite.codecs import decode_time, encode_time
from healthtracker.infrastructure.sqlite.errors import SchemaError


class CognitiveRepository(RecordRepository):
    table, model, range_column = "cognitive_entries", CognitiveMeasurement, "interval_end_utc"

    def _encode(self, value):
        assessment = value.assessment
        data = {**self._meta(value), "interval_start_utc": encode_time(value.interval.start), "interval_end_utc": encode_time(value.interval.end)}
        for code in ("learning", "application", "speed"):
            answer = getattr(assessment, code)
            data[code + "_status"] = answer.status.value
            data[code + "_value"] = answer.value
            data[code + "_scale_version_id"] = self.session.definitions.scale_id(code, getattr(assessment, code + "_scale_version"))
        data.update(formula_version_id=self.session.definitions.formula_id(assessment.formula_version),
                    activity_description=assessment.activity_description,
                    activity_difficulty=assessment.activity_difficulty.value if assessment.activity_difficulty else None)
        return data

    def _decode(self, row):
        answers = [CognitiveAnswer(AnswerStatus(row[code + "_status"]), row[code + "_value"]) for code in ("learning", "application", "speed")]
        versions = {code + "_scale_version": self.session.definitions.version(row[code + "_scale_version_id"], code) for code in ("learning", "application", "speed")}
        assessment = CognitiveAssessment(*answers, **versions,
            formula_version=self.session.definitions.version(row["formula_version_id"], "cognitive_index", formula=True),
            activity_description=row["activity_description"],
            activity_difficulty=CognitiveDifficulty(row["activity_difficulty"]) if row["activity_difficulty"] else None)
        interval = CognitiveInterval(decode_time(row["interval_end_utc"]), now=self.session.now)
        if interval.start != decode_time(row["interval_start_utc"]):
            raise SchemaError("Некорректная длина сохранённого когнитивного часа.")
        return CognitiveMeasurement(assessment, interval, decode_time(row["created_at_utc"]), decode_time(row["updated_at_utc"]))
