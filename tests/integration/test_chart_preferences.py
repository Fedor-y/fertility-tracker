from contextlib import contextmanager
from dataclasses import replace
import json

import pytest

from healthtracker.application.chart_preferences import ChartPreferencesService, PreferencesError
from healthtracker.application.errors import StorageError
from healthtracker.domain.chart_preferences import ChartPreferences
from healthtracker.domain.charts import SeriesKind
from healthtracker.domain.errors import DomainValidationError
from healthtracker.infrastructure.sqlite.settings import SettingsRepository


def test_missing_and_legacy_preferences(db):
    service = ChartPreferencesService(db)
    assert service.load() == ChartPreferences()
    with db.read_snapshot() as s:
        assert s.settings.get('visible_series') is None
    with db.write() as s:
        s.settings.set('visible_series', [])
        s.settings.set('compact_mode', False)
        s.settings.set('line_gap_hours', 2.5)
        s.settings.set('analytics_indicator', 'learning')
    value = service.load()
    assert value.visible_series == () and value.compact_mode is False
    assert value.line_gap_hours == 2.5 and value.analytics_indicator.value == 'learning'
    assert value.show_sleep and value.show_meals and value.show_gym and value.show_events


@pytest.mark.parametrize('kind', list(SeriesKind))
def test_each_series_roundtrip(db, kind):
    service = ChartPreferencesService(db)
    value = ChartPreferences(visible_series=(kind,))
    service.save(value)
    assert service.load() == value


@pytest.mark.parametrize('key', ['compact_mode', 'show_sleep', 'show_meals', 'show_gym', 'show_events'])
def test_each_boolean_roundtrip(db, key):
    service = ChartPreferencesService(db)
    value = replace(ChartPreferences(), **{key: False})
    service.save(value)
    assert service.load() == value
    with db.read_snapshot() as s:
        raw = s.connection.execute('SELECT value FROM application_settings WHERE key=?', (key,)).fetchone()[0]
        assert raw == 'false'


@pytest.mark.parametrize('changes', [dict(visible_series=['mood']), dict(visible_series=('mood',)),
    dict(visible_series=(SeriesKind.MOOD, SeriesKind.MOOD)), dict(compact_mode=0),
    dict(show_sleep=None), dict(show_meals=1), dict(show_gym='false'), dict(show_events=[]),
    dict(line_gap_hours=True), dict(line_gap_hours=0), dict(line_gap_hours=float('nan')),
    dict(analytics_indicator='learning')])
def test_typed_validation(changes):
    with pytest.raises(DomainValidationError):
        ChartPreferences(**changes)


@pytest.mark.parametrize('key,value', [('visible_series', ['unknown']), ('show_sleep', 'false'),
    ('compact_mode', None), ('analytics_indicator', 'unknown')])
def test_bad_saved_value_is_not_destroyed(db, key, value):
    raw = json.dumps(value)
    with db.write() as s:
        s.connection.execute('INSERT INTO application_settings VALUES(?,?,?)',
                             (key, raw, '2026-11-04T12:00:00.000000Z'))
    with pytest.raises(PreferencesError):
        ChartPreferencesService(db).load()
    with pytest.raises(PreferencesError):
        ChartPreferencesService(db).save(ChartPreferences())
    with db.read_snapshot() as s:
        assert s.connection.execute('SELECT value FROM application_settings WHERE key=?', (key,)).fetchone()[0] == raw


def test_save_rolls_back_all_keys(db, monkeypatch):
    service = ChartPreferencesService(db)
    service.save(ChartPreferences())
    original = SettingsRepository.set
    def fail(self, key, value):
        if key == 'show_gym':
            raise StorageError('private contents')
        original(self, key, value)
    monkeypatch.setattr(SettingsRepository, 'set', fail)
    with pytest.raises(PreferencesError) as error:
        service.save(ChartPreferences(visible_series=(), compact_mode=False))
    assert 'private' not in str(error.value)
    assert service.load() == ChartPreferences()


def test_read_failure_and_bad_json_are_safe(db, monkeypatch):
    def fail(*args):
        raise json.JSONDecodeError('private', 'private', 0)
    monkeypatch.setattr(SettingsRepository, 'get', fail)
    with pytest.raises(PreferencesError) as error:
        ChartPreferencesService(db).load()
    assert 'private' not in str(error.value)


def test_reopen_combination_and_unchanged_observations(db):
    from healthtracker.infrastructure.sqlite.database import Database
    from healthtracker.application.observations import Observations
    from datetime import UTC, datetime
    observations = Observations(db)
    observations.save_stress(score=0, observed_at=datetime(2026,11,1,12,tzinfo=UTC))
    observations.save_mood(score=7, observed_at=datetime(2026,11,1,12,tzinfo=UTC))
    service = ChartPreferencesService(db)
    with db.read_snapshot() as s:
        original = {key: getattr(s,key).all() for key in ('cognitive','physical','stress','mood','sleep','meals','gym')}
    value = ChartPreferences(visible_series=tuple(SeriesKind), compact_mode=False,
                            show_sleep=False, show_meals=False, show_gym=False, show_events=False)
    service.save(value)
    path = db.path
    db.close()
    with Database(path) as reopened:
        assert ChartPreferencesService(reopened).load() == value
        with reopened.read_snapshot() as s:
            assert {key: getattr(s,key).all() for key in original} == original
    db.initialize()


def test_unknown_key_is_preserved(db):
    with db.write() as s:
        s.connection.execute('INSERT INTO application_settings VALUES(?,?,?)',
                             ('future_preference', '{"version":2}', '2026-11-04T12:00:00.000000Z'))
    service = ChartPreferencesService(db)
    service.save(service.load())
    with db.read_snapshot() as s:
        assert s.connection.execute("SELECT value FROM application_settings WHERE key='future_preference'").fetchone()[0] == '{"version":2}'


def test_legacy_series_order_does_not_become_an_unsaved_change(db):
    with db.write() as s:
        s.settings.set('visible_series', ['physical', 'cognitive'])
    value = ChartPreferencesService(db).load()
    assert value == ChartPreferences()
    # Нормализация только модели, без исправления/перезаписи прежнего JSON.
    with db.read_snapshot() as s:
        assert s.settings.get('visible_series') == ['physical', 'cognitive']


def test_read_storage_error_is_safe_and_unknown_model_field_is_rejected(db, monkeypatch):
    def fail():
        raise StorageError('private details')
    monkeypatch.setattr(db,'read_snapshot',fail)
    with pytest.raises(PreferencesError) as error:
        ChartPreferencesService(db).load()
    assert 'private' not in str(error.value)
    with pytest.raises(TypeError):
        ChartPreferences(unknown_field=True)
