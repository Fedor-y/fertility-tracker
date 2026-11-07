"""Только SQL начальной миграции. Значения пользователя здесь не интерполируются."""

import json

from healthtracker.domain.catalogs import (
    MealCategory, STRESS_CAUSE_LABELS, StressCause, SYMPTOM_LABELS, SymptomCode,
)
from healthtracker.domain.scales import (
    COGNITIVE_DIFFICULTY_V1, NUMERIC_SCALES_V1, SYMPTOM_INTENSITY_V1,
)


TABLES = frozenset({
    "schema_migrations", "scale_versions", "formula_versions", "application_settings",
    "cognitive_entries", "physical_entries", "stress_entries", "mood_entries",
    "sleep_entries", "meals", "meal_items", "gym_entries", "symptom_catalog",
    "physical_symptoms", "stress_cause_catalog", "stress_causes",
})


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _date_check(name: str) -> str:
    pattern = "[0-9]" * 4 + "-" + "[0-9]" * 2 + "-" + "[0-9]" * 2
    return (f"length({name})=10 AND {name} GLOB '{pattern}' "
            f"AND substr({name},1,4)>='0001' AND date({name},'+0 days') IS {name}")


def _timestamp(name: str) -> str:
    return (f"{name} TEXT NOT NULL CHECK(length({name})=27 "
            f"AND ({_date_check('substr(' + name + ',1,10)')}) "
            f"AND substr({name},11,1)='T' AND substr({name},14,1)=':' "
            f"AND substr({name},17,1)=':' AND substr({name},20,1)='.' "
            f"AND substr({name},27,1)='Z' "
            f"AND substr({name},12,2) GLOB '[0-9][0-9]' AND substr({name},12,2) BETWEEN '00' AND '23' "
            f"AND substr({name},15,2) GLOB '[0-9][0-9]' AND substr({name},15,2) BETWEEN '00' AND '59' "
            f"AND substr({name},18,2) GLOB '[0-9][0-9]' AND substr({name},18,2) BETWEEN '00' AND '59' "
            f"AND substr({name},21,6) GLOB '{'[0-9]' * 6}')")


META = _timestamp("created_at_utc") + "," + _timestamp("updated_at_utc") + ",CHECK(updated_at_utc>=created_at_utc)"
SCORE = "score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 10)"
SCALE = "scale_version_id INTEGER NOT NULL REFERENCES scale_versions(id) ON DELETE RESTRICT"


def _cognitive_fields(code: str) -> str:
    return f"""{code}_status TEXT NOT NULL CHECK({code}_status IN ('numeric','not_engaged','cannot_assess')),
        {code}_value INTEGER,
        {code}_scale_version_id INTEGER NOT NULL REFERENCES scale_versions(id) ON DELETE RESTRICT,
        CHECK(({code}_status='numeric' AND {code}_value IS NOT NULL AND {code}_value BETWEEN 0 AND 10)
           OR ({code}_status<>'numeric' AND {code}_value IS NULL))"""


def initial_statements() -> tuple[str, ...]:
    # Ограничения таблицы следуют после всех колонок (включая META).
    cognitive_parts = [_cognitive_fields(code) for code in ("learning", "application", "speed")]
    cognitive_columns = ",".join(part.rsplit(",\n        CHECK", 1)[0] for part in cognitive_parts)
    cognitive_checks = ",".join("CHECK" + part.rsplit(",\n        CHECK", 1)[1] for part in cognitive_parts)
    statements = [
        """CREATE TABLE schema_migrations(
            version INTEGER PRIMARY KEY CHECK(version>0), migration_id TEXT NOT NULL UNIQUE CHECK(length(migration_id)>0),
            checksum TEXT NOT NULL CHECK(length(checksum)=64), """ + _timestamp("applied_at_utc") + ") STRICT",
        """CREATE TABLE scale_versions(id INTEGER PRIMARY KEY, scale_code TEXT NOT NULL CHECK(length(trim(scale_code))>0),
            version INTEGER NOT NULL CHECK(version>0), definition TEXT NOT NULL CHECK(json_valid(definition)), """
            + _timestamp("created_at_utc") + ", UNIQUE(scale_code,version)) STRICT",
        """CREATE TABLE formula_versions(id INTEGER PRIMARY KEY, formula_code TEXT NOT NULL CHECK(length(trim(formula_code))>0),
            version INTEGER NOT NULL CHECK(version>0), definition TEXT NOT NULL CHECK(json_valid(definition)), """
            + _timestamp("created_at_utc") + ", UNIQUE(formula_code,version)) STRICT",
        "CREATE TABLE application_settings(key TEXT PRIMARY KEY NOT NULL CHECK(length(trim(key))>0), value TEXT NOT NULL CHECK(json_valid(value)), "
            + _timestamp("updated_at_utc") + ") STRICT",
        f"""CREATE TABLE cognitive_entries(id INTEGER PRIMARY KEY,
            {_timestamp('interval_start_utc')}, {_timestamp('interval_end_utc')},
            {cognitive_columns},
            formula_version_id INTEGER NOT NULL REFERENCES formula_versions(id) ON DELETE RESTRICT,
            activity_description TEXT CHECK(activity_description IS NULL OR length(trim(activity_description))>0),
            activity_difficulty TEXT CHECK(activity_difficulty IN ('Лёгкая','Обычная','Сложная')),
            {META}, {cognitive_checks},
            CHECK(strftime('%Y-%m-%dT%H:%M:%S',interval_end_utc,'-1 hour')=substr(interval_start_utc,1,19)
                  AND substr(interval_start_utc,21,6)=substr(interval_end_utc,21,6))) STRICT""",
        f"""CREATE TABLE physical_entries(id INTEGER PRIMARY KEY, {_timestamp('observed_at_utc')},
            {SCORE}, {SCALE}, symptom_status TEXT NOT NULL CHECK(symptom_status IN ('listed','none_confirmed','unknown')),
            {META}) STRICT""",
        f"""CREATE TABLE stress_entries(id INTEGER PRIMARY KEY, {_timestamp('observed_at_utc')},
            {SCORE}, {SCALE}, comment TEXT CHECK(comment IS NULL OR length(trim(comment))>0), {META}) STRICT""",
        f"""CREATE TABLE mood_entries(id INTEGER PRIMARY KEY, {_timestamp('observed_at_utc')},
            {SCORE}, {SCALE}, {META}) STRICT""",
        f"""CREATE TABLE sleep_entries(id INTEGER PRIMARY KEY, {_timestamp('sleep_start_utc')},
            {_timestamp('wake_at_utc')}, {META}, CHECK(wake_at_utc>sleep_start_utc)) STRICT""",
        f"""CREATE TABLE meals(id INTEGER PRIMARY KEY, meal_date TEXT NOT NULL CHECK({_date_check('meal_date')}),
            category TEXT NOT NULL CHECK(category IN ({','.join(_literal(c.value) for c in MealCategory)})),
            note TEXT CHECK(note IS NULL OR length(trim(note))>0), {META}) STRICT""",
        f"""CREATE TABLE meal_items(id INTEGER PRIMARY KEY, meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
            position INTEGER NOT NULL CHECK(position>=0), name TEXT NOT NULL CHECK(length(trim(name))>0),
            composition TEXT CHECK(composition IS NULL OR length(trim(composition))>0),
            quantity_text TEXT CHECK(quantity_text IS NULL OR length(trim(quantity_text))>0),
            caffeine_status TEXT NOT NULL DEFAULT 'unspecified' CHECK(caffeine_status IN ('contains','does_not_contain','unspecified')),
            {META}, UNIQUE(meal_id,position)) STRICT""",
        f"""CREATE TABLE gym_entries(id INTEGER PRIMARY KEY, entry_date TEXT NOT NULL UNIQUE CHECK({_date_check('entry_date')}),
            attended INTEGER NOT NULL CHECK(attended IN (0,1)), difficulty INTEGER,
            difficulty_scale_version_id INTEGER REFERENCES scale_versions(id) ON DELETE RESTRICT,
            {META}, CHECK((attended=1 AND difficulty IS NOT NULL AND difficulty BETWEEN 0 AND 10 AND difficulty_scale_version_id IS NOT NULL)
                      OR (attended=0 AND difficulty IS NULL AND difficulty_scale_version_id IS NULL))) STRICT""",
        """CREATE TABLE symptom_catalog(id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK(length(trim(code))>0),
            name TEXT NOT NULL CHECK(length(trim(name))>0), display_order INTEGER NOT NULL CHECK(display_order>=0)) STRICT""",
        """CREATE TABLE physical_symptoms(physical_entry_id INTEGER NOT NULL REFERENCES physical_entries(id) ON DELETE CASCADE,
            symptom_id INTEGER NOT NULL REFERENCES symptom_catalog(id) ON DELETE RESTRICT,
            intensity TEXT CHECK(intensity IN ('Слабая','Умеренная','Сильная')),
            detail TEXT CHECK(detail IS NULL OR length(trim(detail))>0), PRIMARY KEY(physical_entry_id,symptom_id)) STRICT""",
        """CREATE TABLE stress_cause_catalog(id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE CHECK(length(trim(code))>0),
            name TEXT NOT NULL CHECK(length(trim(name))>0), display_order INTEGER NOT NULL CHECK(display_order>=0)) STRICT""",
        """CREATE TABLE stress_causes(stress_entry_id INTEGER NOT NULL REFERENCES stress_entries(id) ON DELETE CASCADE,
            cause_id INTEGER NOT NULL REFERENCES stress_cause_catalog(id) ON DELETE RESTRICT,
            PRIMARY KEY(stress_entry_id,cause_id)) STRICT""",
    ]
    for table in ("scale_versions", "formula_versions"):
        for operation in ("UPDATE", "DELETE"):
            statements.append(f"CREATE TRIGGER {table}_immutable_{operation.lower()} BEFORE {operation} ON {table} "
                              "BEGIN SELECT RAISE(ABORT,'immutable_definition'); END")
    for table, field, code in (
        ("cognitive_entries", "learning_scale_version_id", "learning"),
        ("cognitive_entries", "application_scale_version_id", "application"),
        ("cognitive_entries", "speed_scale_version_id", "speed"),
        ("physical_entries", "scale_version_id", "physical"),
        ("stress_entries", "scale_version_id", "stress"),
        ("mood_entries", "scale_version_id", "mood"),
        ("gym_entries", "difficulty_scale_version_id", "gym_difficulty"),
        ("cognitive_entries", "formula_version_id", "cognitive_index"),
    ):
        definition_table, code_field = ("formula_versions", "formula_code") if field == "formula_version_id" else ("scale_versions", "scale_code")
        for operation in ("INSERT", "UPDATE"):
            statements.append(f"CREATE TRIGGER {table}_{field}_{operation.lower()} BEFORE {operation} ON {table} "
                f"WHEN NEW.{field} IS NOT NULL AND NOT EXISTS(SELECT 1 FROM {definition_table} WHERE id=NEW.{field} AND {code_field}='{code}') "
                "BEGIN SELECT RAISE(ABORT,'wrong_definition'); END")
    for operation in ("INSERT", "UPDATE"):
        exclusion = "AND id<>OLD.id" if operation == "UPDATE" else ""
        statements.append(f"CREATE TRIGGER sleep_overlap_{operation.lower()} BEFORE {operation} ON sleep_entries "
            f"WHEN EXISTS(SELECT 1 FROM sleep_entries WHERE sleep_start_utc<NEW.wake_at_utc AND wake_at_utc>NEW.sleep_start_utc {exclusion}) "
            "BEGIN SELECT RAISE(ABORT,'sleep_overlap'); END")
    for table, column in (
        ("cognitive_entries", "interval_end_utc"), ("physical_entries", "observed_at_utc"),
        ("stress_entries", "observed_at_utc"), ("mood_entries", "observed_at_utc"),
        ("sleep_entries", "sleep_start_utc"), ("sleep_entries", "wake_at_utc"),
        ("meals", "meal_date,category"), ("physical_symptoms", "symptom_id"),
        ("stress_causes", "cause_id"),
    ):
        statements.append(f"CREATE INDEX ix_{table}_{column.split(',')[0]} ON {table}({column})")
    for scale in (*NUMERIC_SCALES_V1, COGNITIVE_DIFFICULTY_V1, SYMPTOM_INTENSITY_V1):
        definition = {"labels": scale.descriptions if hasattr(scale, "descriptions") else scale.labels}
        data = json.dumps(definition, ensure_ascii=False, separators=(",", ":"))
        statements.append("INSERT INTO scale_versions(scale_code,version,definition,created_at_utc) VALUES("
                          f"{_literal(scale.code)},1,{_literal(data)},:now)")
    definition = json.dumps({"formula": "(A + B + C) / 3", "requires": "three_numeric_answers"}, separators=(",", ":"))
    statements.append("INSERT INTO formula_versions(formula_code,version,definition,created_at_utc) VALUES("
                      f"'cognitive_index',1,{_literal(definition)},:now)")
    for table, codes, labels in (
        ("symptom_catalog", SymptomCode, SYMPTOM_LABELS),
        ("stress_cause_catalog", StressCause, STRESS_CAUSE_LABELS),
    ):
        for index, (code, label) in enumerate(zip(codes, labels, strict=True)):
            statements.append(f"INSERT INTO {table}(code,name,display_order) VALUES({_literal(code.value)},{_literal(label)},{index})")
    return tuple(statements)
