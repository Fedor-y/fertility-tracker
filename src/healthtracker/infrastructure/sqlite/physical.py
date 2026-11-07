from healthtracker.domain.catalogs import SymptomCode, SymptomStatus
from healthtracker.domain.records import PhysicalRecord, Symptom
from healthtracker.domain.scales import SymptomIntensity
from healthtracker.infrastructure.sqlite.base import RecordRepository
from healthtracker.infrastructure.sqlite.codecs import decode_time, encode_time


class PhysicalRepository(RecordRepository):
    table, model, range_column = "physical_entries", PhysicalRecord, "observed_at_utc"

    def _encode(self, value):
        return {**self._meta(value), "observed_at_utc": encode_time(value.observed_at), "score": value.score,
                "scale_version_id": self.session.definitions.scale_id("physical", value.scale_version),
                "symptom_status": value.symptom_status.value}

    def _children(self, record_id, value):
        self.connection.execute("DELETE FROM physical_symptoms WHERE physical_entry_id=?", (record_id,))
        for symptom in value.symptoms:
            self.connection.execute(
                "INSERT INTO physical_symptoms VALUES(?,(SELECT id FROM symptom_catalog WHERE code=?),?,?)",
                (record_id, symptom.code.value, symptom.intensity.value if symptom.intensity else None, symptom.detail),
            )

    def _decode(self, row):
        symptoms = self.connection.execute(
            "SELECT c.code,s.intensity,s.detail FROM physical_symptoms s JOIN symptom_catalog c ON c.id=s.symptom_id "
            "WHERE s.physical_entry_id=? ORDER BY c.display_order", (row["id"],),
        ).fetchall()
        return PhysicalRecord(observed_at=decode_time(row["observed_at_utc"]), score=row["score"],
            scale_version=self.session.definitions.version(row["scale_version_id"], "physical"),
            symptom_status=SymptomStatus(row["symptom_status"]),
            symptoms=tuple(Symptom(SymptomCode(s["code"]), SymptomIntensity(s["intensity"]) if s["intensity"] else None, s["detail"]) for s in symptoms),
            created_at=decode_time(row["created_at_utc"]), updated_at=decode_time(row["updated_at_utc"]))
