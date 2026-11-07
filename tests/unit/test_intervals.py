from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from healthtracker.domain.answers import CognitiveAnswer
from healthtracker.domain.cognitive import CognitiveAssessment
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.intervals import (
    CognitiveInterval, SleepInterval, ensure_no_sleep_overlap,
)
from healthtracker.domain.measurement import CognitiveMeasurement


NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)


def test_time01_cognitive_hour_is_exact_and_crosses_midnight():
    interval = CognitiveInterval(datetime(2026, 11, 4, 0, 30, tzinfo=UTC), now=NOW)
    assert interval.start == datetime(2026, 11, 3, 23, 30, tzinfo=UTC)
    assert interval.end - interval.start == timedelta(minutes=60)
    assert interval.date_in(UTC) == date(2026, 11, 4)


def test_time01_future_is_rejected_but_current_and_retrospective_allowed():
    assert CognitiveInterval(NOW, now=NOW).end == NOW
    assert CognitiveInterval(NOW - timedelta(days=100), now=NOW).end < NOW
    with pytest.raises(DomainValidationError):
        CognitiveInterval(NOW + timedelta(microseconds=1), now=NOW)


def test_time01_cognitive_intersections_and_duplicate_times_are_allowed():
    first = CognitiveInterval(NOW - timedelta(minutes=30), now=NOW)
    second = CognitiveInterval(NOW, now=NOW)
    assert second.start < first.end
    assert CognitiveInterval(NOW, now=NOW) == second


@pytest.mark.parametrize("end, expected_start", [
    (datetime(2026, 3, 29, 3, 30, tzinfo=ZoneInfo("Europe/Berlin")),
     datetime(2026, 3, 29, 0, 30, tzinfo=UTC)),
    (datetime(2026, 10, 25, 2, 30, fold=1, tzinfo=ZoneInfo("Europe/Berlin")),
     datetime(2026, 10, 25, 0, 30, tzinfo=UTC)),
])
def test_real_cognitive_hour_does_not_use_wall_clock_subtraction(end, expected_start):
    interval = CognitiveInterval(end, now=NOW)
    assert interval.start == expected_start
    assert interval.end.tzinfo is UTC
    assert interval.end - interval.start == timedelta(hours=1)


def test_measurement_time_is_independent_from_creation_and_edit_time():
    assessment = CognitiveAssessment(*(CognitiveAnswer.numeric(7) for _ in range(3)))
    interval = CognitiveInterval(NOW - timedelta(days=2), now=NOW)
    measurement = CognitiveMeasurement(assessment, interval, NOW, NOW)
    assert measurement.interval.end != measurement.created_at
    edited = replace(measurement, updated_at=NOW + timedelta(minutes=1))
    assert edited.created_at == measurement.created_at
    assert edited.interval == measurement.interval
    with pytest.raises(FrozenInstanceError):
        measurement.created_at = interval.end
    with pytest.raises(DomainValidationError):
        replace(measurement, updated_at=NOW - timedelta(seconds=1))


@pytest.mark.parametrize("duration, warning", [
    (timedelta(hours=8), False), (timedelta(hours=16), False),
    (timedelta(hours=16, microseconds=1), True), (timedelta(hours=24), True),
])
def test_sleep_longer_than_16_hours_warns_but_model_is_valid(duration, warning):
    sleep = SleepInterval(NOW - duration, NOW, now=NOW)
    assert sleep.duration == duration
    assert sleep.requires_confirmation is warning


@pytest.mark.parametrize("start, end", [
    (NOW, NOW), (NOW, NOW - timedelta(seconds=1)),
    (NOW - timedelta(hours=1), NOW + timedelta(microseconds=1)),
])
def test_sleep_zero_negative_and_future_intervals_rejected(start, end):
    with pytest.raises(DomainValidationError):
        SleepInterval(start, end, now=NOW)


@pytest.mark.parametrize("hours", [(0, 2), (3, 5), (-1, 5), (1, 3), (2, 4)])
def test_sleep_overlaps_in_all_directions_are_rejected(hours):
    base = NOW - timedelta(days=1)
    existing = SleepInterval(base + timedelta(hours=1), base + timedelta(hours=4), now=NOW)
    candidate = SleepInterval(base + timedelta(hours=hours[0]),
                              base + timedelta(hours=hours[1]), now=NOW)
    with pytest.raises(DomainValidationError):
        ensure_no_sleep_overlap(candidate, [existing])


def test_sleep_touching_boundaries_and_multiple_records_on_same_date_allowed():
    base = datetime(2026, 11, 4, tzinfo=UTC)
    first = SleepInterval(base, base + timedelta(hours=4), now=NOW)
    second = SleepInterval(base + timedelta(hours=4), base + timedelta(hours=8), now=NOW)
    ensure_no_sleep_overlap(second, [first])
    ensure_no_sleep_overlap(first, [second])
    assert first.date_in(UTC) == second.date_in(UTC)


@pytest.mark.parametrize("start, end, expected", [
    (datetime(2026, 3, 29, 0, tzinfo=ZoneInfo("Europe/Berlin")),
     datetime(2026, 3, 29, 8, tzinfo=ZoneInfo("Europe/Berlin")), 7),
    (datetime(2026, 10, 25, 0, tzinfo=ZoneInfo("Europe/Berlin")),
     datetime(2026, 10, 25, 8, tzinfo=ZoneInfo("Europe/Berlin")), 9),
])
def test_sleep_duration_uses_actual_utc_elapsed_time(start, end, expected):
    sleep = SleepInterval(start, end, now=NOW)
    assert sleep.duration == timedelta(hours=expected)


def test_sleep_crosses_midnight_and_is_grouped_by_waking_date_in_current_zone():
    sleep = SleepInterval(datetime(2026, 11, 3, 23, tzinfo=UTC),
                          datetime(2026, 11, 4, 7, tzinfo=UTC), now=NOW)
    assert sleep.duration == timedelta(hours=8)
    assert sleep.date_in(UTC) == date(2026, 11, 4)
    assert sleep.date_in(ZoneInfo("America/Los_Angeles")) == date(2026, 11, 3)
    assert sleep.end == datetime(2026, 11, 4, 7, tzinfo=UTC)


@pytest.mark.parametrize("factory", [
    lambda: CognitiveInterval(datetime(2026, 11, 4), now=NOW),
    lambda: CognitiveInterval(NOW, now=datetime(2026, 11, 5)),
    lambda: SleepInterval(datetime(2026, 11, 3), NOW, now=NOW),
    lambda: SleepInterval(NOW - timedelta(hours=8), NOW, now=None),
])
def test_interval_inputs_cannot_hide_naive_or_missing_time(factory):
    with pytest.raises(DomainValidationError):
        factory()


def test_sleep_overlap_uses_utc_not_repeated_local_clock_values():
    zone = ZoneInfo("Europe/Berlin")
    first = SleepInterval(
        datetime(2026, 10, 25, 2, 15, tzinfo=zone, fold=0),
        datetime(2026, 10, 25, 2, 45, tzinfo=zone, fold=0), now=NOW,
    )
    second = SleepInterval(
        datetime(2026, 10, 25, 2, 15, tzinfo=zone, fold=1),
        datetime(2026, 10, 25, 2, 45, tzinfo=zone, fold=1), now=NOW,
    )
    ensure_no_sleep_overlap(second, [first])
    crossing = SleepInterval(
        datetime(2026, 10, 25, 2, 30, tzinfo=zone, fold=0),
        datetime(2026, 10, 25, 2, 30, tzinfo=zone, fold=1), now=NOW,
    )
    with pytest.raises(DomainValidationError):
        ensure_no_sleep_overlap(crossing, [first, second])
