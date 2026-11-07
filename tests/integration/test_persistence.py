from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from healthtracker.domain.answers import AnswerStatus, CognitiveAnswer
from healthtracker.domain.catalogs import MealCategory, StressCause, SymptomStatus
from healthtracker.domain.cognitive import CognitiveAssessment
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.intervals import CognitiveInterval, SleepInterval
from healthtracker.domain.measurement import CognitiveMeasurement
from healthtracker.domain.records import GymRecord, MealItem, MealRecord, MoodRecord, PhysicalRecord, SleepRecord, StressRecord
from healthtracker.infrastructure.sqlite.connections import connect, transaction
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.infrastructure.sqlite.errors import SchemaError, StorageError, StorageRecoveryRequired


NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)
META = {"created_at": NOW, "updated_at": NOW}


def test_every_repository_survives_complete_manager_close_and_reopen(tmp_path):
    path = tmp_path / "persist.sqlite3"
    values = {
        "cognitive": CognitiveMeasurement(CognitiveAssessment(CognitiveAnswer.numeric(0), CognitiveAnswer.numeric(10),
            CognitiveAnswer(AnswerStatus.CANNOT_ASSESS)), CognitiveInterval(NOW, now=NOW), NOW, NOW),
        "physical": PhysicalRecord(observed_at=NOW, score=0, symptom_status=SymptomStatus.UNKNOWN, **META),
        "stress": StressRecord(observed_at=NOW, score=0, **META),
        "mood": MoodRecord(observed_at=NOW, score=0, **META),
        "sleep": SleepRecord(interval=SleepInterval(NOW-timedelta(hours=8), NOW, now=NOW), **META),
        "meals": MealRecord(entry_date=date(2026, 11, 3), category=MealCategory.OTHER,
                            items=(MealItem(name="Еда", **META),), **META),
        "gym": GymRecord(entry_date=date(2026, 11, 3), attended=False, **META),
    }
    with Database(path, clock=lambda: NOW) as db:
        with db.write() as session:
            identifiers = {name: getattr(session, name).create(value) for name, value in values.items()}
            session.settings.set("compact_mode", False)
    with Database(path, clock=lambda: NOW) as db:
        with db.read_snapshot() as session:
            for name, value in values.items():
                assert getattr(session, name).get(identifiers[name]).value == value
            assert session.settings.get("compact_mode") is False
            assert session.definitions.scale("stress").version == 1


def test_reusing_same_manager_after_close_creates_new_identity(tmp_path):
    db = Database(tmp_path / "persist.sqlite3", clock=lambda: NOW)
    with db:
        with db.read_snapshot() as session:
            token = session.token
    with db:
        assert not db.is_current(token)


@pytest.mark.parametrize("sql", [
    "DROP TRIGGER sleep_overlap_insert", "DROP INDEX ix_mood_entries_observed_at_utc",
    "ALTER TABLE mood_entries ADD COLUMN unexpected INTEGER",
    "UPDATE schema_migrations SET checksum=printf('%064d',0)",
])
def test_altered_schema_or_history_rejected_without_overwrite(tmp_path, sql):
    path = tmp_path / "persist.sqlite3"
    with Database(path, clock=lambda: NOW):
        pass
    with connect(path) as connection:
        with transaction(connection, write=True):
            connection.execute(sql)
    before = path.read_bytes()
    with pytest.raises(SchemaError):
        Database(path).initialize()
    assert path.read_bytes() == before


def test_unknown_legacy_scale_is_not_automatically_replaced(db):
    value = MoodRecord(observed_at=NOW, score=5, **META)
    with db.write() as session:
        record_id = session.mood.create(value)
        session.connection.execute("INSERT INTO scale_versions(scale_code,version,definition,created_at_utc) SELECT scale_code,2,definition,created_at_utc FROM scale_versions WHERE scale_code='mood'")
        new_id = session.connection.execute("SELECT id FROM scale_versions WHERE scale_code='mood' AND version=2").fetchone()[0]
        session.connection.execute("UPDATE mood_entries SET scale_version_id=? WHERE id=?", (new_id, record_id))
        with pytest.raises(DomainValidationError):
            session.mood.update(record_id, value)
        assert session.connection.execute("SELECT scale_version_id FROM mood_entries WHERE id=?", (record_id,)).fetchone()[0] == new_id


def test_recovery_required_disables_manager_writes(db):
    with pytest.raises(StorageRecoveryRequired):
        with db.write():
            raise StorageRecoveryRequired("injected uncertain transaction")
    with pytest.raises(StorageError):
        with db.write():
            pass
    with pytest.raises(StorageRecoveryRequired):
        db.initialize()
    db.close()
    with Database(db.path, clock=lambda: NOW) as reopened:
        with reopened.read_snapshot() as reader:
            assert reader.mood.all() == ()


@pytest.mark.parametrize("repo,value", [
    ("mood", MoodRecord(observed_at=NOW+timedelta(seconds=1), score=5, **META)),
    ("gym", GymRecord(entry_date=date(2026, 11, 5), attended=False, **META)),
])
def test_future_record_values_do_not_enter_storage(db, repo, value):
    with pytest.raises(DomainValidationError):
        with db.write() as session:
            getattr(session, repo).create(value)


def test_corrupted_file_blocks_new_writes_and_is_not_replaced(db):
    # Только искусственная база: имитация повреждения между короткими сессиями.
    with db.path.open("r+b") as file:
        file.write(b"NOT A SQLITE DB!")
    corrupted = db.path.read_bytes()
    with pytest.raises(StorageRecoveryRequired):
        with db.read_snapshot():
            pass
    with pytest.raises(StorageError):
        with db.write():
            pass
    assert db.path.read_bytes() == corrupted


def test_existing_schema_is_inspected_readonly_before_any_writable_open(tmp_path, monkeypatch):
    from contextlib import contextmanager
    import healthtracker.infrastructure.sqlite.database as module
    path = tmp_path / "persist.sqlite3"
    with Database(path):
        pass
    modes = []
    original = module.connect
    @contextmanager
    def tracked(path, *, readonly=False):
        modes.append(readonly)
        with original(path, readonly=readonly) as connection:
            yield connection
    monkeypatch.setattr(module, "connect", tracked)
    with Database(path):
        pass
    assert modes == [True]
