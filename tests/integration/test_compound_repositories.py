from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from healthtracker.domain.catalogs import CaffeineStatus, MealCategory, StressCause, SymptomCode, SymptomStatus
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.records import MealItem, MealRecord, PhysicalRecord, StressRecord, Symptom
from healthtracker.domain.scales import SymptomIntensity
from healthtracker.infrastructure.sqlite.errors import ConfirmationRequired, ConstraintViolation


NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)
META = {"created_at": NOW-timedelta(days=1), "updated_at": NOW-timedelta(days=1)}


def meal(category=MealCategory.BREAKFAST):
    return MealRecord(entry_date=date(2026, 11, 3), category=category,
        items=(MealItem(name="Омлет", composition="Яйца, молоко", quantity_text="Две штуки", **META),
               MealItem(name="Чай", caffeine_status=CaffeineStatus.CONTAINS, **META)), **META)


def physical():
    return PhysicalRecord(observed_at=NOW, score=10, symptom_status=SymptomStatus.LISTED,
        symptoms=(Symptom(SymptomCode.HEADACHE), Symptom(SymptomCode.MUSCLE_PAIN, SymptomIntensity.MILD)), **META)


def stress():
    return StressRecord(observed_at=NOW, score=7, causes=(StressCause.WORK, StressCause.STUDY), comment="Личный комментарий", **META)


@pytest.mark.parametrize("repo,value,child_table,catalog", [
    ("physical", physical(), "physical_symptoms", "symptom_catalog"),
    ("stress", stress(), "stress_causes", "stress_cause_catalog"),
    ("meals", meal(), "meal_items", None),
])
def test_compound_crud_cascade_and_catalog_preservation(db, repo, value, child_table, catalog):
    with db.write() as session:
        repository = getattr(session, repo)
        record_id = repository.create(value)
        assert repository.get(record_id).value == value
        assert session.connection.execute(f"SELECT count(*) FROM {child_table}").fetchone()[0] == 2
        repository.update(record_id, replace(value, updated_at=NOW))
        repository.delete(record_id)
        assert session.connection.execute(f"SELECT count(*) FROM {child_table}").fetchone()[0] == 0
        if catalog:
            assert session.connection.execute(f"SELECT count(*) FROM {catalog}").fetchone()[0] > 0


def test_physical_absent_symptom_info_does_not_become_absence_or_zero(db):
    value = PhysicalRecord(observed_at=NOW, score=10, symptom_status=SymptomStatus.UNKNOWN, **META)
    with db.write() as session:
        first = session.physical.create(value)
        second = session.physical.create(replace(value, symptom_status=SymptomStatus.NONE_CONFIRMED))
    with db.read_snapshot() as session:
        assert session.physical.get(first).value.symptom_status is SymptomStatus.UNKNOWN
        assert session.physical.get(second).value.symptom_status is SymptomStatus.NONE_CONFIRMED
        assert session.physical.get(first).value.score == 10


def test_meal_duplicate_warning_confirmation_other_and_edit_self(db):
    with db.write() as session:
        first = session.meals.create(meal())
        with pytest.raises(ConfirmationRequired):
            session.meals.create(meal())
        assert session.meals.duplicates(date(2026, 11, 3), MealCategory.BREAKFAST) == (first,)
        second = session.meals.create(meal(), duplicate_confirmed=True)
        session.meals.update(second, replace(meal(), note="Изменено", updated_at=NOW))
        for _ in range(2):
            session.meals.create(meal(MealCategory.OTHER))
        assert len(session.meals.all()) == 4
        session.meals.delete(first)
        assert session.meals.duplicates(date(2026, 11, 3), MealCategory.BREAKFAST) == (second,)
    with db.read_snapshot() as session:
        value = session.meals.get(second).value
        assert value.items[0].quantity_text == "Две штуки"
        assert value.items[0].caffeine_status is CaffeineStatus.UNSPECIFIED


def test_stress_positive_to_zero_clears_only_this_record_atomically(db):
    with db.write() as session:
        first = session.stress.create(stress())
        second = session.stress.create(stress())
        session.stress.update(first, replace(stress(), score=0, updated_at=NOW))
    with db.read_snapshot() as session:
        zero = session.stress.get(first).value
        assert zero.score == 0 and zero.causes == () and zero.comment is None
        assert zero.created_at == stress().created_at and zero.updated_at == NOW
        assert zero.scale_version == stress().scale_version
        assert session.stress.get(second).value == stress()
        assert session.stress.get(999) is None
        assert session.connection.execute("SELECT count(*) FROM stress_cause_catalog").fetchone()[0] == 6


@pytest.mark.parametrize("repo,value,child_table", [
    ("physical", physical(), "physical_symptoms"),
    ("stress", stress(), "stress_causes"),
    ("meals", meal(), "meal_items"),
])
def test_child_failure_rolls_back_parent_even_when_caught_inside_session(db, repo, value, child_table):
    with db.write() as session:
        session.connection.execute(f"CREATE TRIGGER fail_child BEFORE INSERT ON {child_table} BEGIN SELECT RAISE(ABORT,'injected'); END")
        with pytest.raises(ConstraintViolation):
            getattr(session, repo).create(value)
        assert getattr(session, repo).all() == ()


def test_stress_failed_cleanup_preserves_score_causes_and_comment(db):
    with db.write() as session:
        record_id = session.stress.create(stress())
        session.connection.execute("CREATE TRIGGER fail_cleanup BEFORE DELETE ON stress_causes BEGIN SELECT RAISE(ABORT,'injected'); END")
        with pytest.raises(ConstraintViolation):
            session.stress.update(record_id, replace(stress(), score=0, updated_at=NOW))
        assert session.stress.get(record_id).value == stress()
    with db.read_snapshot() as session:
        assert session.stress.get(record_id).value == stress()


def test_meal_failed_edit_preserves_previous_positions(db):
    with db.write() as session:
        record_id = session.meals.create(meal())
        session.connection.execute("CREATE TRIGGER fail_item BEFORE INSERT ON meal_items WHEN NEW.position=1 BEGIN SELECT RAISE(ABORT,'injected'); END")
        with pytest.raises(ConstraintViolation):
            session.meals.update(record_id, replace(meal(), note="Не сохранять", updated_at=NOW))
        assert session.meals.get(record_id).value == meal()


@pytest.mark.parametrize("factory", [
    lambda: PhysicalRecord(observed_at=NOW, score=10, symptom_status=SymptomStatus.LISTED, **META),
    lambda: PhysicalRecord(observed_at=NOW, score=10, symptom_status=SymptomStatus.NONE_CONFIRMED, symptoms=(Symptom(SymptomCode.HEADACHE),), **META),
    lambda: MealRecord(entry_date=date(2026, 11, 3), category=MealCategory.OTHER, items=(), **META),
])
def test_cross_row_states_rejected_before_sql(factory):
    with pytest.raises(DomainValidationError):
        factory()
