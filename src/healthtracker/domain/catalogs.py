"""Фиксированные категории MVP; не пользовательские справочники."""

from enum import StrEnum


class SymptomCode(StrEnum):
    HEADACHE = "headache"
    DIZZINESS = "dizziness"
    ABDOMINAL_DISCOMFORT = "abdominal_discomfort"
    NAUSEA = "nausea"
    MUSCLE_PAIN = "muscle_pain"
    BODY_ACHES = "body_aches"
    OTHER = "other"


SYMPTOM_LABELS = (
    "Головная боль", "Головокружение", "Дискомфорт в животе", "Тошнота",
    "Боль в мышцах", "Ломота в теле", "Другое",
)


class StressCause(StrEnum):
    WORK = "work"
    STUDY = "study"
    RELATIONSHIPS = "relationships"
    FINANCES = "finances"
    HEALTH = "health"
    OTHER = "other"


STRESS_CAUSE_LABELS = ("Работа", "Учёба", "Отношения", "Финансы", "Здоровье", "Другое")


class MealCategory(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    AFTER_BREAKFAST = "after_breakfast"
    AFTER_LUNCH = "after_lunch"
    AFTER_DINNER = "after_dinner"
    OTHER = "other"


class CaffeineStatus(StrEnum):
    CONTAINS = "contains"
    DOES_NOT_CONTAIN = "does_not_contain"
    UNSPECIFIED = "unspecified"


class SymptomStatus(StrEnum):
    LISTED = "listed"
    NONE_CONFIRMED = "none_confirmed"
    UNKNOWN = "unknown"
