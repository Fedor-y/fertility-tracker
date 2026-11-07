from healthtracker.domain.catalogs import StressCause
from healthtracker.domain.records import StressRecord, prepare_stress_edit
from healthtracker.infrastructure.sqlite.base import RecordRepository
from healthtracker.infrastructure.sqlite.codecs import decode_time, encode_time


class StressRepository(RecordRepository):
    table, model, range_column = "stress_entries", StressRecord, "observed_at_utc"

    def _prepare(self, value, previous, record_id):
        return prepare_stress_edit(previous, value)

    def _encode(self, value):
        return {**self._meta(value), "observed_at_utc": encode_time(value.observed_at), "score": value.score,
                "scale_version_id": self.session.definitions.scale_id("stress", value.scale_version), "comment": value.comment}

    def _children(self, record_id, value):
        self.connection.execute("DELETE FROM stress_causes WHERE stress_entry_id=?", (record_id,))
        for cause in value.causes:
            self.connection.execute("INSERT INTO stress_causes VALUES(?,(SELECT id FROM stress_cause_catalog WHERE code=?))",
                                    (record_id, cause.value))

    def _decode(self, row):
        causes = self.connection.execute(
            "SELECT c.code FROM stress_causes s JOIN stress_cause_catalog c ON s.cause_id=c.id "
            "WHERE s.stress_entry_id=? ORDER BY c.display_order", (row["id"],),
        ).fetchall()
        return StressRecord(observed_at=decode_time(row["observed_at_utc"]), score=row["score"],
            scale_version=self.session.definitions.version(row["scale_version_id"], "stress"),
            causes=tuple(StressCause(c[0]) for c in causes), comment=row["comment"],
            created_at=decode_time(row["created_at_utc"]), updated_at=decode_time(row["updated_at_utc"]))
