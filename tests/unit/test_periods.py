from datetime import date,datetime,timedelta

import pytest

from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.periods import DateRange, QuickPeriod, ComparisonPeriod, quick_period, comparison_periods


@pytest.mark.parametrize('today,kind,start,end',[
    (date(2026,1,1),QuickPeriod.DAY,date(2026,1,1),date(2026,1,1)),
    (date(2026,1,1),QuickPeriod.SEVEN_DAYS,date(2025,12,26),date(2026,1,1)),
    (date(2026,3,3),QuickPeriod.TEN_DAYS,date(2026,2,22),date(2026,3,3)),
    (date(2024,3,3),QuickPeriod.TEN_DAYS,date(2024,2,23),date(2024,3,3)),
    (date(2024,2,1),QuickPeriod.MONTH,date(2024,2,1),date(2024,2,29)),
    (date(2026,2,28),QuickPeriod.MONTH,date(2026,2,1),date(2026,2,28)),
    (date(2026,12,31),QuickPeriod.MONTH,date(2026,12,1),date(2026,12,31)),
    (date(2024,2,29),QuickPeriod.YEAR,date(2024,1,1),date(2024,12,31)),
    (date(2026,11,4),QuickPeriod.YEAR,date(2026,1,1),date(2026,12,31)),
    (date.max,QuickPeriod.YEAR,date(9999,1,1),date.max),
])
def test_quick_calendar_boundaries(today,kind,start,end):
    result=quick_period(kind,today)
    assert (result.start,result.end)==(start,end)


@pytest.mark.parametrize('today,kind,left,right',[
    (date(2026,11,2),ComparisonPeriod.WEEK,(date(2026,11,2),date(2026,11,2)),(date(2026,10,26),date(2026,10,26))),
    (date(2026,11,4),ComparisonPeriod.WEEK,(date(2026,11,2),date(2026,11,4)),(date(2026,10,26),date(2026,10,28))),
    (date(2026,11,8),ComparisonPeriod.WEEK,(date(2026,11,2),date(2026,11,8)),(date(2026,10,26),date(2026,11,1))),
    (date(2026,1,1),ComparisonPeriod.MONTH,(date(2026,1,1),date(2026,1,1)),(date(2025,12,1),date(2025,12,1))),
    (date(2026,3,31),ComparisonPeriod.MONTH,(date(2026,3,1),date(2026,3,31)),(date(2026,2,1),date(2026,2,28))),
    (date(2024,3,31),ComparisonPeriod.MONTH,(date(2024,3,1),date(2024,3,31)),(date(2024,2,1),date(2024,2,29))),
    (date(2026,11,4),ComparisonPeriod.MONTH,(date(2026,11,1),date(2026,11,4)),(date(2026,10,1),date(2026,10,4))),
])
def test_same_elapsed_part_of_previous_period(today,kind,left,right):
    result=comparison_periods(kind,today)
    assert result.first==DateRange(*left) and result.second==DateRange(*right)


@pytest.mark.parametrize('start,end,days',[(date(2024,1,1),date(2024,12,31),366),
    (date(2026,3,29),date(2026,3,29),1),(date.min,date.max,3652059)])
def test_calendar_size_does_not_depend_on_hours_or_dst(start,end,days):
    assert DateRange(start,end).calendar_days==days


def test_date_iterator_handles_last_python_date():
    assert tuple(DateRange(date.max-timedelta(days=1),date.max).dates())==(date(9999,12,30),date.max)


@pytest.mark.parametrize('factory',[
    lambda:DateRange(date(2026,2,1),date(2026,1,1)),lambda:DateRange(datetime(2026,1,1),date(2026,1,2)),
    lambda:quick_period('week',date(2026,1,1)),lambda:quick_period(QuickPeriod.TEN_DAYS,date.min),
    lambda:comparison_periods(ComparisonPeriod.MONTH,date.min),lambda:comparison_periods('year',date(2026,1,1)),
])
def test_invalid_or_unrepresentable_periods_are_explicit_errors(factory):
    with pytest.raises(DomainValidationError): factory()
