import pytest

from healthtracker.domain.errors import DomainValidationError


def test_settings_are_explicit_and_preserve_false_not_missing(db):
    with db.write() as session:
        assert session.settings.get("compact_mode") is None
        session.settings.set("compact_mode", False)
        session.settings.set("line_gap_hours", 3)
        session.settings.set("visible_series", ["cognitive", "physical"])
        session.settings.set("analytics_indicator", "learning")
    with db.read_snapshot() as session:
        assert session.settings.get("compact_mode") is False
        assert session.settings.get("line_gap_hours") == 3
    with db.write() as session:
        session.settings.set("line_gap_hours", 2.5)
        session.settings.delete("compact_mode")
        assert session.settings.get("compact_mode") is None


@pytest.mark.parametrize("key,value", [
    ("backup_path", "/tmp"), ("window_geometry", "private"), ("unknown", 1),
    ("line_gap_hours", True), ("line_gap_hours", 0), ("line_gap_hours", float("inf")),
    ("visible_series", ["unknown"]), ("visible_series", ["mood", "mood"]),
    ("compact_mode", None), ("analytics_indicator", "stress"),
])
def test_invalid_or_qsettings_parameters_rejected(db, key, value):
    with pytest.raises(DomainValidationError):
        with db.write() as session:
            session.settings.set(key, value)
