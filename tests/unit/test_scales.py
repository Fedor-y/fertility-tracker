"""DOM-03: исходный текст ТЗ — независимый эталон всех описаний."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.scales import (
    APPLICATION_V1, COGNITIVE_DIFFICULTY_V1, GYM_DIFFICULTY_V1,
    LEARNING_V1, MOOD_V1, NUMERIC_SCALES_V1, PHYSICAL_V1,
    SPEED_V1, STRESS_V1, SYMPTOM_INTENSITY_V1,
)


def specification_tables():
    text = (Path(__file__).resolve().parents[2] / "docs/requirements.md").read_text()
    tables = []
    rows = []
    for line in text.splitlines() + [""]:
        if line.startswith("|"):
            cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
            if cells[0].isdigit():
                rows.append(cells)
        elif rows:
            tables.append(tuple(rows))
            rows = []
    return tables


def test_all_77_numeric_descriptions_match_requirements_verbatim():
    tables = specification_tables()
    assert len(tables) == 5
    expected = [
        (LEARNING_V1, tables[0], 1), (APPLICATION_V1, tables[0], 2),
        (SPEED_V1, tables[0], 3), (PHYSICAL_V1, tables[1], 1),
        (STRESS_V1, tables[2], 1), (MOOD_V1, tables[3], 1),
        (GYM_DIFFICULTY_V1, tables[4], 1),
    ]
    for scale, rows, column in expected:
        assert scale.version == 1
        assert tuple(int(row[0]) for row in rows) == tuple(range(11))
        assert tuple(scale.describe(int(row[0])) for row in rows) == tuple(
            row[column] for row in rows
        )


@pytest.mark.parametrize("scale", NUMERIC_SCALES_V1, ids=lambda scale: scale.code)
@pytest.mark.parametrize("invalid", [-1, 11, True, False, 5.0, "5", None])
def test_scales_reject_invalid_scores(scale, invalid):
    with pytest.raises(DomainValidationError):
        scale.describe(invalid)


def test_definitions_are_immutable_and_categories_are_exact():
    for scale in (*NUMERIC_SCALES_V1, COGNITIVE_DIFFICULTY_V1, SYMPTOM_INTENSITY_V1):
        with pytest.raises(FrozenInstanceError):
            scale.version = 2
    assert COGNITIVE_DIFFICULTY_V1.labels == ("Лёгкая", "Обычная", "Сложная")
    assert SYMPTOM_INTENSITY_V1.labels == ("Слабая", "Умеренная", "Сильная")
    assert COGNITIVE_DIFFICULTY_V1.version == SYMPTOM_INTENSITY_V1.version == 1
