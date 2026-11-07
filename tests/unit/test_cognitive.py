from dataclasses import FrozenInstanceError, replace

import pytest

from healthtracker.domain.answers import AnswerStatus, CognitiveAnswer
from healthtracker.domain.cognitive import CognitiveAssessment, cognitive_index
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.scales import CognitiveDifficulty, get_numeric_scale


def assessment(*values, **kwargs):
    return CognitiveAssessment(*(CognitiveAnswer.numeric(value) for value in values), **kwargs)


@pytest.mark.parametrize("values, expected", [
    ((6, 8, 7), 7), ((0, 0, 0), 0), ((10, 10, 10), 10),
    ((0, 5, 10), 5), ((0, 0, 1), 1 / 3),
])
def test_dom01_equal_mean_without_rounding(values, expected):
    result = cognitive_index(assessment(*values))
    assert result == expected
    assert result is not None


@pytest.mark.parametrize("position", range(3))
@pytest.mark.parametrize("status", [AnswerStatus.NOT_ENGAGED, AnswerStatus.CANNOT_ASSESS])
def test_dom02_special_in_any_position_removes_only_index(position, status):
    answers = [CognitiveAnswer.numeric(6), CognitiveAnswer.numeric(8), CognitiveAnswer.numeric(7)]
    answers[position] = CognitiveAnswer(status)
    record = CognitiveAssessment(*answers)
    assert cognitive_index(record) is None
    for index, answer in enumerate((record.learning, record.application, record.speed)):
        if index != position:
            assert answer == answers[index]
            assert answer.value is not None


@pytest.mark.parametrize("position", range(3))
@pytest.mark.parametrize("invalid", [None, 0, "Не занимался"])
def test_dom02_unanswered_is_rejected_and_not_converted(position, invalid):
    answers = [CognitiveAnswer.numeric(5)] * 3
    answers[position] = invalid
    with pytest.raises(DomainValidationError):
        CognitiveAssessment(*answers)
    assert answers[position] is invalid


def test_three_special_answers_still_form_a_defined_assessment():
    record = CognitiveAssessment(
        CognitiveAnswer(AnswerStatus.NOT_ENGAGED),
        CognitiveAnswer(AnswerStatus.CANNOT_ASSESS),
        CognitiveAnswer(AnswerStatus.NOT_ENGAGED),
    )
    assert cognitive_index(record) is None


@pytest.mark.parametrize("difficulty", [None, *CognitiveDifficulty])
def test_optional_context_does_not_adjust_index(difficulty):
    record = assessment(6, 8, 7, activity_description="Изучение материала", activity_difficulty=difficulty)
    assert cognitive_index(record) == 7


def test_blank_context_is_absent_and_versions_are_preserved_on_edit():
    original = assessment(6, 8, 7, activity_description="   ")
    assert original.activity_description is None
    edited = replace(original, speed=CognitiveAnswer.numeric(4))
    assert edited.formula_version == original.formula_version == 1
    assert (edited.learning_scale_version, edited.application_scale_version,
            edited.speed_scale_version) == (1, 1, 1)
    with pytest.raises(FrozenInstanceError):
        original.formula_version = 2


@pytest.mark.parametrize("kwargs", [
    {"formula_version": 2}, {"formula_version": True},
    {"learning_scale_version": 0}, {"application_scale_version": 2},
    {"speed_scale_version": "1"}, {"activity_difficulty": "обычная"},
    {"activity_description": 123},
])
def test_invalid_versions_and_context_are_not_silently_reinterpreted(kwargs):
    with pytest.raises(DomainValidationError):
        assessment(6, 8, 7, **kwargs)


def test_unknown_scale_is_not_replaced_with_another():
    with pytest.raises(DomainValidationError):
        get_numeric_scale("unknown", 1)


def test_index_rejects_an_unfinished_assessment():
    with pytest.raises(DomainValidationError):
        cognitive_index(None)
