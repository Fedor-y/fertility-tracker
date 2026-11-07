"""Создание и правка наблюдений: транзакции, служебные времена и версии."""
from datetime import UTC, datetime
from dataclasses import replace

from healthtracker.application.errors import ConfirmationRequired, MealDuplicateConfirmationRequired, RecordNotFound
from healthtracker.application.storage import Storage
from healthtracker.domain.cognitive import CognitiveAssessment, cognitive_index
from healthtracker.domain.intervals import CognitiveInterval, SleepInterval, ensure_no_sleep_overlap
from healthtracker.domain.measurement import CognitiveMeasurement
from healthtracker.domain.records import (
    GymRecord, MealItem, MealRecord, MoodRecord, PhysicalRecord, SleepRecord, StressRecord,
    meal_duplicate_warning_needed, validate_record_time,
)
from healthtracker.domain.catalogs import CaffeineStatus
from healthtracker.domain.errors import DomainValidationError


class Observations:
    def __init__(self, storage: Storage, *, clock=lambda: datetime.now(UTC)):
        self.storage = storage
        self.clock = clock

    def get(self, kind, record_id):
        with self.storage.read_snapshot() as session:
            record = getattr(session, kind).get(record_id)
            if record is None:
                raise RecordNotFound("Запись не найдена.")
            return record

    def cognitive_interval(self, end):
        return CognitiveInterval(end, now=self.clock())

    def cognitive_preview(self, assessment, end):
        return self.cognitive_interval(end), cognitive_index(assessment)

    def save_cognitive(self, assessment: CognitiveAssessment, end, record_id=None):
        with self.storage.write() as session:
            repo = session.cognitive
            now = session.now
            created = now
            if record_id is not None:
                previous = repo.get(record_id)
                if previous is None:
                    raise RecordNotFound("Запись не найдена.")
                old = previous.value
                created = old.created_at
                assessment = replace(assessment,
                    learning_scale_version=old.assessment.learning_scale_version,
                    application_scale_version=old.assessment.application_scale_version,
                    speed_scale_version=old.assessment.speed_scale_version,
                    formula_version=old.assessment.formula_version)
            value = CognitiveMeasurement(assessment, CognitiveInterval(end, now=now), created, now)
            if record_id is None:
                record_id = repo.create(value)
            else:
                repo.update(record_id, value)
        return record_id

    def save_physical(self, *, score, observed_at, symptom_status, symptoms, record_id=None):
        with self.storage.write() as session:
            repo = session.physical
            now = session.now
            created, version = now, 1
            if record_id is not None:
                previous = repo.get(record_id)
                if previous is None:
                    raise RecordNotFound("Запись не найдена.")
                created, version = previous.value.created_at, previous.value.scale_version
            value = PhysicalRecord(score=score, observed_at=observed_at,
                symptom_status=symptom_status, symptoms=symptoms,
                created_at=created, updated_at=now, scale_version=version)
            if record_id is None:
                record_id = repo.create(value)
            else:
                repo.update(record_id, value)
        return record_id

    def stress_causes(self):
        with self.storage.read_snapshot() as session:
            return session.definitions.stress_causes()

    def save_stress(self, *, score, observed_at, causes=(), comment=None, record_id=None):
        # Ноль всегда означает отсутствие переживаемого стресса. Нормализация
        # входных данных здесь не изменяет форму до подтверждённого commit.
        if score == 0:
            causes, comment = (), None
        return self._save_moment("stress", StressRecord, record_id,
            score=score, observed_at=observed_at, causes=causes, comment=comment)

    def no_stress(self):
        """Быстрое действие использует тот же сценарий, что и обычная форма."""
        return self.save_stress(score=0, observed_at=self.clock())

    def save_mood(self, *, score, observed_at, record_id=None):
        return self._save_moment("mood", MoodRecord, record_id,
            score=score, observed_at=observed_at)

    def _save_moment(self, kind, model, record_id, **fields):
        with self.storage.write() as session:
            repo = getattr(session, kind)
            now = session.now
            created, version = now, 1
            if record_id is not None:
                previous = repo.get(record_id)
                if previous is None:
                    raise RecordNotFound("Запись не найдена.")
                created, version = previous.value.created_at, previous.value.scale_version
            value = model(**fields, created_at=created, updated_at=now, scale_version=version)
            if record_id is None:
                record_id = repo.create(value)
            else:
                repo.update(record_id, value)
        return record_id

    def sleep_interval(self, start, end):
        """Предварительная проверка и производная длительность без записи."""
        return SleepInterval(start, end, now=self.clock())

    def save_sleep(self, *, start, end, record_id=None, long_sleep_confirmed=False):
        with self.storage.write() as session:
            repo = session.sleep
            interval = SleepInterval(start, end, now=session.now)
            if interval.requires_confirmation and long_sleep_confirmed is not True:
                raise ConfirmationRequired("Подтвердите сон продолжительностью более 16 часов.")
            created = session.now
            if record_id is not None:
                previous = repo.get(record_id)
                if previous is None:
                    raise RecordNotFound("Запись не найдена.")
                created = previous.value.created_at
            # Проверка Application выполняется в той же пишущей транзакции.
            # Репозиторий и триггеры остаются дополнительной защитой.
            ensure_no_sleep_overlap(interval, (
                record.value.interval for record in repo.all() if record.id != record_id
            ))
            value = SleepRecord(interval=interval, created_at=created, updated_at=session.now)
            if record_id is None:
                record_id = repo.create(value, long_sleep_confirmed=long_sleep_confirmed)
            else:
                repo.update(record_id, value, long_sleep_confirmed=long_sleep_confirmed)
        return record_id

    def save_meal(self, *, entry_date, category, items, note=None,
                  record_id=None, duplicate_confirmed=False):
        """Поля позиций — команда формы, исходная позиция — только ключ правки.

        Источник служебных времён — текущая транзакция и прежний агрегат,
        а не поля пользовательского интерфейса. Время еды не создаётся.
        """
        with self.storage.write() as session:
            repo = session.meals
            previous = None
            if record_id is not None:
                stored = repo.get(record_id)
                if stored is None:
                    raise RecordNotFound("Запись не найдена.")
                previous = stored.value
            values, used = [], set()
            for fields in items:
                source = fields.get("source_position")
                old = None
                if source is not None:
                    if (type(source) is not int or previous is None
                            or not 0 <= source < len(previous.items) or source in used):
                        raise DomainValidationError("Не удалось определить исходную позицию питания.")
                    old = previous.items[source]
                    used.add(source)
                item = MealItem(name=fields.get("name", ""),
                    composition=fields.get("composition"), quantity_text=fields.get("quantity_text"),
                    caffeine_status=fields.get("caffeine_status", CaffeineStatus.UNSPECIFIED),
                    created_at=old.created_at if old else session.now, updated_at=session.now)
                if old and replace(item, updated_at=old.updated_at) == old:
                    item = old
                values.append(item)
            value = MealRecord(entry_date=entry_date, category=category, items=tuple(values), note=note,
                created_at=previous.created_at if previous else session.now, updated_at=session.now)
            validate_record_time(value, now=session.now, today=session.today)
            duplicates = repo.duplicates(entry_date, category, exclude_id=record_id)
            if (meal_duplicate_warning_needed(value, previous, has_duplicates=bool(duplicates))
                    and duplicate_confirmed is not True):
                raise MealDuplicateConfirmationRequired(duplicates)
            if record_id is None:
                record_id = repo.create(value, duplicate_confirmed=duplicate_confirmed)
            else:
                repo.update(record_id, value, duplicate_confirmed=duplicate_confirmed)
        return record_id

    def save_gym(self, *, entry_date, attended, difficulty=None, record_id=None):
        with self.storage.write() as session:
            repo = session.gym
            previous = None
            if record_id is not None:
                stored = repo.get(record_id)
                if stored is None:
                    raise RecordNotFound("Запись не найдена.")
                previous = stored.value
            version = None
            if attended is True:
                version = (previous.difficulty_scale_version
                    if previous is not None and previous.attended else 1)
            value = GymRecord(entry_date=entry_date, attended=attended, difficulty=difficulty,
                difficulty_scale_version=version,
                created_at=previous.created_at if previous else session.now, updated_at=session.now)
            validate_record_time(value, now=session.now, today=session.today)
            if any(record.id != record_id and record.value.entry_date == entry_date
                   for record in repo.all()):
                raise DomainValidationError(
                    "За эту дату отметка спортзала уже существует. Откройте её для исправления.")
            if record_id is None:
                record_id = repo.create(value)
            else:
                repo.update(record_id, value)
        return record_id
