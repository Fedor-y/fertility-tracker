from datetime import date
import pytest
from healthtracker.domain.periods import QuickPeriod, quick_period
from healthtracker.domain.errors import DomainValidationError

@pytest.mark.parametrize('today,start,end', [
    (date(2024,3,31),date(2024,2,1),date(2024,2,29)),
    (date(2026,3,1),date(2026,2,1),date(2026,2,28)),
    (date(2026,1,1),date(2025,12,1),date(2025,12,31)),
    (date(2026,12,31),date(2026,11,1),date(2026,11,30)),
])
def test_previous_month_is_full_calendar_month(today,start,end):
    result=quick_period(QuickPeriod.PREVIOUS_MONTH,today)
    assert (result.start,result.end)==(start,end)


def test_previous_month_at_minimum_year_is_explicit_error():
    with pytest.raises(DomainValidationError):
        quick_period(QuickPeriod.PREVIOUS_MONTH,date.min)
