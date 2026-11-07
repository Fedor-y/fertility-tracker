from datetime import date

from healthtracker.domain.records import GymRecord
from healthtracker.infrastructure.sqlite.base import RecordRepository
from healthtracker.infrastructure.sqlite.codecs import decode_time


class GymRepository(RecordRepository):
    table, model, range_column, date_only = "gym_entries", GymRecord, "entry_date", True

    def _encode(self, value):
        return {**self._meta(value), "entry_date": value.entry_date.isoformat(), "attended": int(value.attended),
                "difficulty": value.difficulty,
                "difficulty_scale_version_id": self.session.definitions.scale_id("gym_difficulty", value.difficulty_scale_version) if value.attended else None}

    def _decode(self, row):
        return GymRecord(entry_date=date.fromisoformat(row["entry_date"]), attended=bool(row["attended"]),
            difficulty=row["difficulty"],
            difficulty_scale_version=self.session.definitions.version(row["difficulty_scale_version_id"], "gym_difficulty") if row["attended"] else None,
            created_at=decode_time(row["created_at_utc"]), updated_at=decode_time(row["updated_at_utc"]))
