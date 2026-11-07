"""Неизменяемые определения утверждённых шкал. Источник: requirements.md."""

from dataclasses import dataclass
from enum import StrEnum

from healthtracker.domain.errors import DomainValidationError


def validate_score(value: int) -> int:
    """Только целые 0–10: bool, дроби и строки не являются оценками."""
    if type(value) is not int or not 0 <= value <= 10:
        raise DomainValidationError("Оценка должна быть целым числом от 0 до 10.")
    return value


@dataclass(frozen=True, slots=True)
class NumericScale:
    code: str
    version: int
    descriptions: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.code, str) or not self.code.strip()
            or type(self.version) is not int or self.version < 1
            or type(self.descriptions) is not tuple
            or len(self.descriptions) != 11
            or any(not isinstance(text, str) or not text.strip()
                   for text in self.descriptions)
        ):
            raise DomainValidationError("Некорректное определение шкалы.")

    def describe(self, score: int) -> str:
        return self.descriptions[validate_score(score)]


LEARNING_V1 = NumericScale("learning", 1, (
    "Почти ничего не удавалось усвоить, несмотря на попытки",
    "Усвоить удавалось лишь отдельные фрагменты",
    "Новое усваивалось очень трудно",
    "Новое усваивалось с большим усилием",
    "Усвоение требовало заметного усилия",
    "Усваивать удавалось с умеренным усилием",
    "Новое усваивалось достаточно легко",
    "Новое усваивалось легко",
    "Новое усваивалось очень легко",
    "Новое усваивалось исключительно легко",
    "Максимальная субъективная лёгкость усвоения",
))

APPLICATION_V1 = NumericScale("application", 1, (
    "Почти ничего нужного не удавалось вспомнить или применить",
    "Удавалось вспомнить лишь отдельные фрагменты, применить — почти нет",
    "Вспоминать и применять знакомое было очень трудно",
    "Для воспроизведения и применения требовалось большое усилие",
    "Вспоминать и применять было ощутимо трудно",
    "Вспоминать и применять удавалось с умеренным усилием",
    "Вспоминать и применять было достаточно легко",
    "Нужные знания вспоминались и применялись легко",
    "Вспоминать и применять было очень легко",
    "Нужные знания были доступны почти без усилий",
    "Максимальная субъективная лёгкость воспроизведения и применения",
))

SPEED_V1 = NumericScale("speed", 1, (
    "Мысли продвигались с чрезвычайно большим трудом",
    "Мысли продвигались крайне медленно",
    "Мышление ощущалось очень медленным",
    "Мышление было заметно замедленным",
    "Мысли продвигались несколько медленно",
    "Темп мышления ощущался умеренным",
    "Мысли продвигались достаточно быстро",
    "Мышление ощущалось быстрым",
    "Мышление ощущалось очень быстрым",
    "Мышление ощущалось исключительно быстрым",
    "Максимальная субъективная скорость обработки информации",
))

PHYSICAL_V1 = NumericScale("physical", 1, (
    "Крайне плохое физическое самочувствие",
    "Очень плохое самочувствие",
    "Плохое самочувствие",
    "Выраженно неудовлетворительное самочувствие",
    "Скорее плохое, чем хорошее самочувствие",
    "Среднее: ни хорошее, ни плохое самочувствие",
    "Скорее хорошее, чем плохое самочувствие",
    "Хорошее самочувствие",
    "Очень хорошее самочувствие",
    "Отличное самочувствие",
    "Максимально хорошее физическое самочувствие по моим ощущениям",
))

STRESS_V1 = NumericScale("stress", 1, (
    "Стресса не ощущаю",
    "Едва заметное напряжение",
    "Слабый стресс",
    "Лёгкий, отчётливо заметный стресс",
    "Умеренный стресс",
    "Довольно ощутимый стресс",
    "Выраженный стресс",
    "Сильный стресс",
    "Очень сильный стресс",
    "Крайне сильный стресс, близкий к моему максимуму",
    "Максимально сильный стресс, который могу представить для себя",
))

MOOD_V1 = NumericScale("mood", 1, (
    "Крайне плохое настроение",
    "Очень плохое настроение",
    "Плохое настроение",
    "Заметно сниженное настроение",
    "Скорее плохое настроение",
    "Нейтральное настроение",
    "Скорее хорошее настроение",
    "Хорошее настроение",
    "Очень хорошее настроение",
    "Отличное настроение",
    "Крайне хорошее настроение",
))

GYM_DIFFICULTY_V1 = NumericScale("gym_difficulty", 1, (
    "Практически без усилий",
    "Минимальное усилие",
    "Очень лёгкая тренировка",
    "Лёгкая тренировка",
    "Умеренно лёгкая тренировка",
    "Умеренно тяжёлая тренировка",
    "Ощутимо тяжёлая тренировка",
    "Тяжёлая тренировка",
    "Очень тяжёлая тренировка",
    "Исключительно тяжёлая тренировка",
    "Максимально тяжёлая тренировка",
))

NUMERIC_SCALES_V1 = (
    LEARNING_V1, APPLICATION_V1, SPEED_V1, PHYSICAL_V1,
    STRESS_V1, MOOD_V1, GYM_DIFFICULTY_V1,
)


def get_numeric_scale(code: str, version: int = 1) -> NumericScale:
    """Не подменять неизвестную/старую версию последней доступной."""
    if type(version) is not int:
        raise DomainValidationError("Некорректная версия шкалы.")
    for scale in NUMERIC_SCALES_V1:
        if scale.code == code and scale.version == version:
            return scale
    raise DomainValidationError("Версия шкалы не поддерживается.")


class CognitiveDifficulty(StrEnum):
    LIGHT = "Лёгкая"
    ORDINARY = "Обычная"
    HARD = "Сложная"


class SymptomIntensity(StrEnum):
    MILD = "Слабая"
    MODERATE = "Умеренная"
    SEVERE = "Сильная"


@dataclass(frozen=True, slots=True)
class CategoricalScale:
    code: str
    version: int
    labels: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.code, str) or not self.code.strip()
            or type(self.version) is not int or self.version < 1
            or type(self.labels) is not tuple or not self.labels
            or any(not isinstance(label, str) or not label.strip() for label in self.labels)
            or len(set(self.labels)) != len(self.labels)
        ):
            raise DomainValidationError("Некорректное определение категориальной шкалы.")


COGNITIVE_DIFFICULTY_V1 = CategoricalScale(
    "cognitive_difficulty", 1, tuple(item.value for item in CognitiveDifficulty),
)
SYMPTOM_INTENSITY_V1 = CategoricalScale(
    "symptom_intensity", 1, tuple(item.value for item in SymptomIntensity),
)
