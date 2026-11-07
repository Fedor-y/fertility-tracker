import pytest

from healthtracker.domain.answers import AnswerStatus, CognitiveAnswer
from healthtracker.domain.errors import DomainValidationError


@pytest.mark.parametrize("score", range(11))
def test_numeric_values_include_real_zero(score):
    assert CognitiveAnswer.numeric(score).value == score


def test_unanswered_and_special_answers_are_distinct():
    unanswered = None
    not_engaged = CognitiveAnswer(AnswerStatus.NOT_ENGAGED)
    cannot_assess = CognitiveAnswer(AnswerStatus.CANNOT_ASSESS)
    assert not_engaged != cannot_assess
    assert not_engaged is not unanswered
    assert cannot_assess is not unanswered
    assert not_engaged.value is cannot_assess.value is None
    assert CognitiveAnswer.numeric(0) not in (unanswered, not_engaged, cannot_assess)
    assert not_engaged.status.label == "Не занимался"
    assert cannot_assess.status.label == "Не могу оценить"


@pytest.mark.parametrize("value", [-1, 11, True, False, 4.5, "5", None])
def test_numeric_answer_rejects_invalid_value(value):
    with pytest.raises(DomainValidationError):
        CognitiveAnswer.numeric(value)


@pytest.mark.parametrize("status", [AnswerStatus.NOT_ENGAGED, AnswerStatus.CANNOT_ASSESS])
@pytest.mark.parametrize("value", [0, 5, "", False])
def test_special_answers_cannot_carry_numbers(status, value):
    with pytest.raises(DomainValidationError):
        CognitiveAnswer(status, value)


@pytest.mark.parametrize("status", [None, "numeric", "not_engaged", "", 0])
def test_status_must_be_explicit_enum_not_an_implicit_conversion(status):
    with pytest.raises(DomainValidationError):
        CognitiveAnswer(status, 0)
