from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from healthtracker.domain.answers import AnswerStatus, CognitiveAnswer
from healthtracker.domain.cognitive import CognitiveAssessment, cognitive_index
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.intervals import CognitiveInterval, SleepInterval
from healthtracker.domain.measurement import CognitiveMeasurement
from healthtracker.domain.records import GymRecord, MoodRecord, SleepRecord
from healthtracker.infrastructure.sqlite.errors import ConfirmationRequired, ConstraintViolation, RecordNotFound, StorageError


NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)
META = {"created_at": NOW, "updated_at": NOW}


def cognitive():
    return CognitiveMeasurement(CognitiveAssessment(CognitiveAnswer.numeric(0),
        CognitiveAnswer(AnswerStatus.NOT_ENGAGED), CognitiveAnswer(AnswerStatus.CANNOT_ASSESS)),
        CognitiveInterval(NOW - timedelta(days=1), now=NOW), NOW, NOW)


@pytest.mark.parametrize("repo,value", [
    ("cognitive", cognitive()),
    ("mood", MoodRecord(observed_at=NOW, score=0, **META)),
    ("gym", GymRecord(entry_date=date(2026, 11, 3), attended=False, **META)),
    ("sleep", SleepRecord(interval=SleepInterval(NOW-timedelta(hours=8), NOW, now=NOW), **META)),
])
def test_create_read_update_delete_and_missing_are_distinct(db, repo, value):
    with db.write() as session:
        repository = getattr(session, repo)
        assert repository.get(999) is None
        record_id = repository.create(value)
    with db.read_snapshot() as session:
        assert getattr(session, repo).get(record_id).value == value
    with db.write() as session:
        repository = getattr(session, repo)
        repository.update(record_id, value)
        assert len(repository.all()) == 1
        repository.delete(record_id)
        assert repository.get(record_id) is None
    with pytest.raises(RecordNotFound):
        with db.write() as session:
            getattr(session, repo).update(record_id, value)


def test_cognitive_statuses_versions_and_duplicate_times_roundtrip(db):
    value = cognitive()
    with db.write() as session:
        first = session.cognitive.create(value)
        second = session.cognitive.create(value)
    with db.read_snapshot() as session:
        assert first != second
        result = session.cognitive.get(first).value
        assert result == value
        assert result.assessment.learning.value == 0
        assert cognitive_index(result.assessment) is None
        assert len(session.cognitive.between(value.interval.end, value.interval.end+timedelta(microseconds=1))) == 2


def test_gym_unique_and_no_automatic_negative(db):
    value = GymRecord(entry_date=date(2026, 11, 3), attended=True, difficulty=0, difficulty_scale_version=1, **META)
    with db.write() as session:
        record_id = session.gym.create(value)
        with pytest.raises(ConstraintViolation):
            session.gym.create(value)
        assert len(session.gym.all()) == 1
        session.gym.update(record_id, replace(value, attended=False, difficulty=None, difficulty_scale_version=None))
    with db.read_snapshot() as session:
        assert session.gym.get(record_id).value.attended is False
        assert len(session.gym.between(date(2026, 11, 2), date(2026, 11, 3))) == 0


def test_sleep_overlap_edit_and_long_sleep_confirmation(db):
    value = SleepRecord(interval=SleepInterval(NOW-timedelta(hours=8), NOW, now=NOW), **META)
    with db.write() as session:
        record_id = session.sleep.create(value)
        session.sleep.update(record_id, value)  # Исключает себя при проверке пересечений.
        with pytest.raises(DomainValidationError):
            session.sleep.create(value)
        session.sleep.delete(record_id)
        long = replace(value, interval=SleepInterval(NOW-timedelta(hours=17), NOW, now=NOW))
        with pytest.raises(ConfirmationRequired):
            session.sleep.create(long)
        session.sleep.create(long, long_sleep_confirmed=True)


def test_repository_rejects_readonly_write_and_changed_creation(db):
    value = MoodRecord(observed_at=NOW, score=5, **META)
    with db.write() as session:
        record_id = session.mood.create(value)
        with pytest.raises(DomainValidationError):
            session.mood.update(record_id, replace(value, created_at=NOW-timedelta(days=1)))
    with db.read_snapshot() as session:
        with pytest.raises(StorageError):
            session.mood.delete(record_id)


def test_outer_transaction_rolls_back_multiple_repositories(db):
    with pytest.raises(RuntimeError):
        with db.write() as session:
            session.cognitive.create(cognitive())
            session.mood.create(MoodRecord(observed_at=NOW, score=5, **META))
            raise RuntimeError("injected")
    with db.read_snapshot() as session:
        assert session.cognitive.all() == session.mood.all() == ()
