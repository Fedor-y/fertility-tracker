"""Представление дня из существующих наблюдений. Без новой сущности хранения."""
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo

from healthtracker.application.errors import ConfirmationRequired, RecordNotFound
from healthtracker.domain.answers import AnswerStatus
from healthtracker.domain.catalogs import SYMPTOM_LABELS, SymptomCode, SymptomStatus
from healthtracker.domain.cognitive import cognitive_index
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.time import local_date


TITLES = {
    "cognitive": "Когнитивное состояние", "physical": "Физическое состояние",
    "stress": "Стресс", "mood": "Настроение", "sleep": "Сон",
    "meals": "Питание", "gym": "Спортзал",
}
KINDS = tuple(TITLES)
MEAL_LABELS = ("Завтрак", "Обед", "Ужин", "Перекус после завтрака",
               "Перекус после обеда", "Перекус после ужина", "Другое")


@dataclass(frozen=True, slots=True)
class DiaryEntry:
    """Неизменяемая строка представления; value — прежняя Domain-модель."""
    kind: str
    id: int
    value: object
    moment: datetime | None
    summary: str


@dataclass(frozen=True, slots=True)
class DiaryDay:
    entry_date: date
    timed: tuple[DiaryEntry, ...]
    untimed: tuple[DiaryEntry, ...]


def summary(kind, value):
    if kind == "cognitive":
        index = cognitive_index(value.assessment)
        label = f"Индекс: {index:.2f}" if index is not None else "Индекс не рассчитан"
        answers = []
        for name, answer in (("Новое", value.assessment.learning),
                             ("Применение", value.assessment.application),
                             ("Скорость", value.assessment.speed)):
            text = str(answer.value) if answer.status is AnswerStatus.NUMERIC else answer.status.label
            answers.append(f"{name}: {text}")
        return label + " · " + "; ".join(answers)
    if kind == "physical":
        state = {SymptomStatus.UNKNOWN: "Сведения о симптомах отсутствуют",
                 SymptomStatus.NONE_CONFIRMED: "Подтверждено: симптомов нет"}
        text = state.get(value.symptom_status)
        if text is None:
            labels = dict(zip(SymptomCode, SYMPTOM_LABELS))
            text = "Симптомы: " + ", ".join(labels[s.code] for s in value.symptoms[:2])
            if len(value.symptoms) > 2:
                text += " …"
        return f"Оценка: {value.score}/10 · {text}"
    if kind == "stress":
        if value.score == 0:
            return "Стресса нет (0)"
        causes = "Причины не указаны" if not value.causes else f"Причин отмечено: {len(value.causes)}"
        return f"Стресс: {value.score}/10 · {causes}" + (" · Есть комментарий" if value.comment else "")
    if kind == "mood":
        return f"Настроение: {value.score}/10"
    if kind == "sleep":
        return f"Длительность: {value.interval.duration}"
    if kind == "meals":
        from healthtracker.domain.catalogs import MealCategory
        label = dict(zip(MealCategory, MEAL_LABELS))[value.category]
        return label + " · " + ", ".join(item.name for item in value.items[:2]) + (" …" if len(value.items) > 2 else "")
    return (f"Был · Сложность: {value.difficulty}/10" if value.attended
            else "Подтверждено: не был · Сложность неприменима")


class Diary:
    def __init__(self, storage):
        self.storage = storage

    def day(self, entry_date: date, zone: tzinfo) -> DiaryDay:
        if type(entry_date) is not date or not isinstance(zone, tzinfo):
            raise DomainValidationError("Необходимы календарная дата и текущий часовой пояс.")
        timed, untimed = [], []
        # Смещение tzinfo строго меньше суток. Широкий UTC-диапазон включает
        # весь местный день, в том числе переходы DST и смену даты в поясе.
        # Точная принадлежность дню по-прежнему проверяется через local_date.
        midnight = datetime.combine(entry_date, datetime.min.time(), UTC)
        try:
            lower, upper = midnight - timedelta(days=1), midnight + timedelta(days=2)
            next_date = entry_date + timedelta(days=1)
        except OverflowError:
            lower = upper = next_date = None
        with self.storage.read_snapshot() as session:
            for kind in KINDS:
                repo = getattr(session, kind)
                if lower is None:
                    records = repo.all()
                elif kind in ("meals", "gym"):
                    records = repo.between(entry_date, next_date)
                else:
                    records = repo.between(lower, upper)
                for record in records:
                    value = record.value
                    moment = None
                    if kind in ("meals", "gym"):
                        event_date = value.entry_date
                    else:
                        moment = value.interval.end if kind in ("cognitive", "sleep") else value.observed_at
                        event_date = local_date(moment, zone)
                    if event_date == entry_date:
                        entry = DiaryEntry(kind, record.id, value, moment, summary(kind, value))
                        (timed if moment is not None else untimed).append(entry)
        timed.sort(key=lambda row: (row.moment, KINDS.index(row.kind), row.id))
        untimed.sort(key=lambda row: (KINDS.index(row.kind), row.id))
        return DiaryDay(entry_date, tuple(timed), tuple(untimed))

    def delete(self, kind, record_id, *, confirmed=False):
        if kind not in KINDS:
            raise DomainValidationError("Неизвестный тип записи.")
        if confirmed is not True:
            raise ConfirmationRequired("Удаление требует подтверждения.")
        with self.storage.write() as session:
            repo = getattr(session, kind)
            if repo.get(record_id) is None:
                raise RecordNotFound("Запись уже удалена или недоступна.")
            repo.delete(record_id)
