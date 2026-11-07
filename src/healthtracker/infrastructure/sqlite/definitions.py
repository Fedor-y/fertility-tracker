"""Только чтение неизменяемых версий, без подстановки последней версии."""

import json

from healthtracker.domain.scales import get_numeric_scale, COGNITIVE_DIFFICULTY_V1, SYMPTOM_INTENSITY_V1
from healthtracker.infrastructure.sqlite.errors import SchemaError


class DefinitionsRepository:
    def __init__(self, session):
        self.session = session

    def _row(self, table, code_field, code, version):
        self.session.ensure_active()
        if type(version) is not int:
            raise SchemaError("Неопределённая версия определения.")
        row = self.session.connection.execute(f"SELECT * FROM {table} WHERE {code_field}=? AND version=?", (code, version)).fetchone()
        if row is None:
            raise SchemaError("Нужная версия определения отсутствует.")
        return row

    def scale(self, code, version=1):
        row = self._row("scale_versions", "scale_code", code, version)
        categorical = {s.code: s for s in (COGNITIVE_DIFFICULTY_V1, SYMPTOM_INTENSITY_V1)}
        scale = categorical.get(code) if version == 1 else None
        if scale is None:
            scale = get_numeric_scale(code, version)
        expected = scale.descriptions if hasattr(scale, "descriptions") else scale.labels
        if json.loads(row["definition"]) != {"labels": list(expected)}:
            raise SchemaError("Сохранённая шкала отличается от исполняемой версии.")
        return scale

    def scale_id(self, code, version=1):
        self.scale(code, version)
        return self._row("scale_versions", "scale_code", code, version)["id"]

    def formula_id(self, version=1):
        row = self._row("formula_versions", "formula_code", "cognitive_index", version)
        if version != 1 or json.loads(row["definition"]) != {
            "formula": "(A + B + C) / 3", "requires": "three_numeric_answers",
        }:
            raise SchemaError("Формула не поддерживается.")
        return row["id"]

    def version(self, record_id, code, *, formula=False):
        self.session.ensure_active()
        table, field = ("formula_versions", "formula_code") if formula else ("scale_versions", "scale_code")
        row = self.session.connection.execute(f"SELECT version FROM {table} WHERE id=? AND {field}=?", (record_id, code)).fetchone()
        if row is None:
            raise SchemaError("Запись ссылается на неподходящее определение.")
        if formula:
            self.formula_id(row[0])
        else:
            self.scale(code, row[0])
        return row[0]

    def stress_causes(self):
        """Существующий справочник причин в порядке отображения."""
        from healthtracker.domain.catalogs import StressCause
        self.session.ensure_active()
        rows = self.session.connection.execute(
            "SELECT code,name FROM stress_cause_catalog ORDER BY display_order"
        ).fetchall()
        return tuple((StressCause(row["code"]), row["name"]) for row in rows)
