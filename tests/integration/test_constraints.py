"""DB-01–04: защиты SQLite проверяются напрямую, независимо от моделей."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from healthtracker.domain.answers import CognitiveAnswer
from healthtracker.domain.catalogs import CaffeineStatus, MealCategory, StressCause, SymptomCode, SymptomStatus
from healthtracker.domain.cognitive import CognitiveAssessment
from healthtracker.domain.intervals import CognitiveInterval, SleepInterval
from healthtracker.domain.measurement import CognitiveMeasurement
from healthtracker.domain.records import GymRecord, MealItem, MealRecord, MoodRecord, PhysicalRecord, SleepRecord, StressRecord, Symptom
from healthtracker.infrastructure.sqlite.errors import ConstraintViolation
from healthtracker.infrastructure.sqlite.schema import TABLES


NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)
META = {"created_at": NOW, "updated_at": NOW}


@pytest.fixture
def filled(db):
    with db.write() as session:
        session.cognitive.create(CognitiveMeasurement(
            CognitiveAssessment(*(CognitiveAnswer.numeric(5) for _ in range(3))),
            CognitiveInterval(NOW, now=NOW), NOW, NOW))
        session.physical.create(PhysicalRecord(observed_at=NOW, score=5, symptom_status=SymptomStatus.LISTED,
                                               symptoms=(Symptom(SymptomCode.HEADACHE),), **META))
        session.stress.create(StressRecord(observed_at=NOW, score=5, causes=(StressCause.WORK,), **META))
        session.mood.create(MoodRecord(observed_at=NOW, score=5, **META))
        session.sleep.create(SleepRecord(interval=SleepInterval(NOW-timedelta(hours=8), NOW, now=NOW), **META))
        session.meals.create(MealRecord(entry_date=date(2026, 11, 3), category=MealCategory.OTHER,
                                        items=(MealItem(name="Еда", **META),), **META))
        session.gym.create(GymRecord(entry_date=date(2026, 11, 3), attended=True, difficulty=5, difficulty_scale_version=1, **META))
        session.settings.set("compact_mode", False)
    return db


@pytest.mark.parametrize("table", sorted(TABLES))
def test_explicit_not_null_for_all_required_columns(filled, table):
    optional = {
        "cognitive_entries": {"learning_value", "application_value", "speed_value", "activity_description", "activity_difficulty"},
        "stress_entries": {"comment"}, "meals": {"note"}, "meal_items": {"composition", "quantity_text"},
        "gym_entries": {"difficulty", "difficulty_scale_version_id"}, "physical_symptoms": {"intensity", "detail"},
    }.get(table, set())
    with filled.write() as session:
        columns = session.connection.execute(f"PRAGMA table_info({table})").fetchall()
        assert columns
        for column in columns:
            if column["name"] not in optional and not (column["pk"] and column["type"] == "INTEGER"):
                assert column["notnull"] == 1, (table, column["name"])
                with pytest.raises(ConstraintViolation):
                    with session.operation():
                        session.connection.execute(f"UPDATE {table} SET {column['name']}=NULL")


@pytest.mark.parametrize("table, column, invalid", [
    ("cognitive_entries", "learning_value", None),
    ("cognitive_entries", "learning_value", 11),
    ("cognitive_entries", "learning_value", 2.5),
    ("cognitive_entries", "learning_status", "not_engaged"),
    ("cognitive_entries", "activity_difficulty", "Средняя"),
    ("cognitive_entries", "interval_start_utc", "2026-11-04T10:59:59.999999Z"),
    ("physical_entries", "score", -1), ("mood_entries", "score", 11),
    ("stress_entries", "score", "personal text"),
    ("mood_entries", "observed_at_utc", "2026-02-30T12:00:00.000000Z"),
    ("mood_entries", "observed_at_utc", "2026-11-04T24:00:00.000000Z"),
    ("mood_entries", "observed_at_utc", "2026-11-04T12:00:00+03:00"),
    ("meals", "meal_date", "2026-02-30"), ("meals", "category", "unknown"),
    ("meal_items", "name", "   "), ("meal_items", "caffeine_status", "unknown"),
    ("physical_symptoms", "intensity", "unknown"),
    ("physical_symptoms", "symptom_id", 9999),
    ("stress_causes", "cause_id", 9999), ("meal_items", "meal_id", 9999),
    ("gym_entries", "difficulty", None), ("gym_entries", "attended", 0),
])
def test_sql_constraints_do_not_depend_on_python_validation(filled, table, column, invalid):
    with filled.write() as session:
        with pytest.raises(ConstraintViolation):
            with session.operation():
                session.connection.execute(f"UPDATE {table} SET {column}=?", (invalid,))


def test_wrong_scale_reference_and_catalog_deletion_rejected(filled):
    with filled.write() as session:
        wrong = session.definitions.scale_id("mood")
        for statement, params in (
            ("UPDATE physical_entries SET scale_version_id=?", (wrong,)),
            ("DELETE FROM symptom_catalog WHERE code=?", ("headache",)),
            ("DELETE FROM stress_cause_catalog WHERE code=?", ("work",)),
        ):
            with pytest.raises(ConstraintViolation):
                with session.operation():
                    session.connection.execute(statement, params)


def test_raw_sleep_overlap_rejected_and_no_cognitive_unique_time(filled):
    with filled.write() as session:
        with pytest.raises(ConstraintViolation):
            with session.operation():
                session.connection.execute("INSERT INTO sleep_entries(sleep_start_utc,wake_at_utc,created_at_utc,updated_at_utc) SELECT sleep_start_utc,wake_at_utc,created_at_utc,updated_at_utc FROM sleep_entries")
        value = session.cognitive.all()[0].value
        session.cognitive.create(value)
        assert len(session.cognitive.all()) == 2


def test_utc_microseconds_and_text_survive_roundtrip(db):
    time = datetime(2026, 11, 3, 23, 30, 0, 999999, tzinfo=timezone(timedelta(hours=3)))
    value = CognitiveMeasurement(CognitiveAssessment(*(CognitiveAnswer.numeric(0) for _ in range(3))),
                                 CognitiveInterval(time, now=NOW), NOW, NOW)
    malicious = "Еда '); DROP TABLE meals; --"
    meal = MealRecord(entry_date=date(2026, 11, 3), category=MealCategory.OTHER,
                      items=(MealItem(name=malicious, quantity_text="Большая тарелка", **META),), **META)
    with db.write() as session:
        identifier = session.cognitive.create(value)
        meal_id = session.meals.create(meal)
    with db.read_snapshot() as session:
        assert session.cognitive.get(identifier).value == value
        assert session.cognitive.get(identifier).value.interval.end.tzinfo is UTC
        assert session.meals.get(meal_id).value.items[0].name == malicious
        assert session.meals.get(meal_id).value.items[0].caffeine_status is CaffeineStatus.UNSPECIFIED
