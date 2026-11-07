from datetime import UTC, date, datetime

import pytest

from healthtracker.domain.catalogs import CaffeineStatus, MealCategory, StressCause, SymptomCode, SymptomStatus
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.records import GymRecord, MealItem, MealRecord, MoodRecord, PhysicalRecord, StressRecord, Symptom


NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)
META = {"created_at": NOW, "updated_at": NOW}


@pytest.mark.parametrize("factory", [
    lambda: MoodRecord(observed_at=NOW, score=True, **META),
    lambda: PhysicalRecord(observed_at=NOW, score=11, symptom_status=SymptomStatus.UNKNOWN, **META),
    lambda: PhysicalRecord(observed_at=NOW, score=5, symptom_status=SymptomStatus.LISTED,
                           symptoms=(Symptom(SymptomCode.HEADACHE), Symptom(SymptomCode.HEADACHE)), **META),
    lambda: StressRecord(observed_at=NOW, score=5, causes=(StressCause.WORK, StressCause.WORK), **META),
    lambda: StressRecord(observed_at=NOW, score=5, causes=[StressCause.WORK], **META),
    lambda: GymRecord(entry_date=date(2026, 11, 4), attended=0, **META),
    lambda: GymRecord(entry_date=date(2026, 11, 4), attended=True, **META),
    lambda: GymRecord(entry_date=date(2026, 11, 4), attended=False, difficulty=0, **META),
    lambda: MealItem(name=" ", **META),
    lambda: MealItem(name="Еда", caffeine_status=None, **META),
    lambda: MealRecord(entry_date=NOW, category=MealCategory.OTHER, items=(MealItem(name="Еда", **META),), **META),
    lambda: Symptom(SymptomCode.OTHER, intensity="unknown"),
])
def test_invalid_record_states_are_rejected(factory):
    with pytest.raises(DomainValidationError):
        factory()


def test_unknown_details_remain_unknown_and_optional_text_normalizes():
    assert Symptom(SymptomCode.HEADACHE).intensity is None
    item = MealItem(name="Еда", composition="   ", quantity_text=None, **META)
    assert item.composition is item.quantity_text is None
    assert item.caffeine_status is CaffeineStatus.UNSPECIFIED
