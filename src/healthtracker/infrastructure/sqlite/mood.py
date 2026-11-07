from healthtracker.domain.records import MoodRecord
from healthtracker.infrastructure.sqlite.base import RecordRepository
from healthtracker.infrastructure.sqlite.codecs import decode_time, encode_time


class MoodRepository(RecordRepository):
    table, model, range_column = "mood_entries", MoodRecord, "observed_at_utc"

    def _encode(self, value):
        return {**self._meta(value), "observed_at_utc": encode_time(value.observed_at), "score": value.score,
                "scale_version_id": self.session.definitions.scale_id("mood", value.scale_version)}

    def _decode(self, row):
        return MoodRecord(observed_at=decode_time(row["observed_at_utc"]), score=row["score"],
            scale_version=self.session.definitions.version(row["scale_version_id"], "mood"),
            created_at=decode_time(row["created_at_utc"]), updated_at=decode_time(row["updated_at_utc"]))
