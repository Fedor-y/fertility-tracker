from datetime import UTC, date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.time import (
    AmbiguousLocalTimeError, NonexistentLocalTimeError, as_utc,
    local_date, local_time_candidates, resolve_local_time,
)


BERLIN = ZoneInfo("Europe/Berlin")


def test_naive_time_is_not_silently_assigned_a_zone():
    for value in (datetime(2026, 11, 4), None, "2026-11-04"):
        with pytest.raises(DomainValidationError):
            as_utc(value)


def test_fixed_offset_is_normalized_without_retaining_original_zone():
    moment = datetime(2026, 11, 4, 15, tzinfo=timezone(timedelta(hours=3)))
    utc = as_utc(moment)
    assert utc == datetime(2026, 11, 4, 12, tzinfo=UTC)
    assert utc.tzinfo is UTC


def test_nonexistent_local_time_rejected_in_both_entry_paths():
    local = datetime(2026, 3, 29, 2, 30)
    assert local_time_candidates(local, BERLIN) == ()
    with pytest.raises(NonexistentLocalTimeError):
        resolve_local_time(local, BERLIN)
    with pytest.raises(NonexistentLocalTimeError):
        as_utc(local.replace(tzinfo=BERLIN))


def test_repeated_hour_requires_explicit_offset_and_preserves_both_moments():
    local = datetime(2026, 10, 25, 2, 30)
    assert local_time_candidates(local, BERLIN) == (
        datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
        datetime(2026, 10, 25, 1, 30, tzinfo=UTC),
    )
    with pytest.raises(AmbiguousLocalTimeError):
        resolve_local_time(local, BERLIN)
    assert resolve_local_time(local, BERLIN, utc_offset=timedelta(hours=2)).hour == 0
    assert resolve_local_time(local, BERLIN, utc_offset=timedelta(hours=1)).hour == 1
    with pytest.raises(DomainValidationError):
        resolve_local_time(local, BERLIN, utc_offset=timedelta(hours=3))


def test_ordinary_local_time_has_one_candidate():
    local = datetime(2026, 11, 4, 15)
    expected = datetime(2026, 11, 4, 14, tzinfo=UTC)
    assert local_time_candidates(local, BERLIN) == (expected,)
    assert resolve_local_time(local, BERLIN) == expected


def test_calendar_grouping_changes_without_changing_utc():
    moment = datetime(2026, 11, 4, 23, 30, tzinfo=UTC)
    assert local_date(moment, UTC) == date(2026, 11, 4)
    assert local_date(moment, ZoneInfo("Europe/Moscow")) == date(2026, 11, 5)
    assert moment == datetime(2026, 11, 4, 23, 30, tzinfo=UTC)


@pytest.mark.parametrize("local, zone", [
    (datetime(2026, 11, 4, tzinfo=UTC), BERLIN),
    (None, BERLIN), (datetime(2026, 11, 4), "Europe/Berlin"),
])
def test_local_input_is_explicit(local, zone):
    with pytest.raises(DomainValidationError):
        local_time_candidates(local, zone)


@pytest.mark.parametrize("start, end, hours", [
    (datetime(2026, 3, 29), datetime(2026, 3, 30), 23),
    (datetime(2026, 10, 25), datetime(2026, 10, 26), 25),
])
def test_calendar_day_can_contain_23_or_25_real_hours(start, end, hours):
    assert resolve_local_time(end, BERLIN) - resolve_local_time(start, BERLIN) == timedelta(hours=hours)
