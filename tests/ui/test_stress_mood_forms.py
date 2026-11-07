from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from healthtracker.application.errors import StorageError
from healthtracker.application.observations import Observations
from healthtracker.domain.catalogs import StressCause, STRESS_CAUSE_LABELS
from healthtracker.domain.scales import get_numeric_scale
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.infrastructure.sqlite.stress import StressRepository
from healthtracker.presentation.forms.common import EntryDialog
from healthtracker.presentation.forms.stress import StressDialog


@pytest.fixture(autouse=True)
def discard_cleanup(monkeypatch):
    monkeypatch.setattr(EntryDialog, "confirm_discard", lambda self: True)


@pytest.fixture
def service(tmp_path):
    with Database(tmp_path / "observations.sqlite3") as database:
        yield Observations(database)


def stress_form(qtbot, service, record_id=None):
    form = StressDialog(service, record_id=record_id)
    qtbot.addWidget(form)
    return form


@pytest.mark.parametrize("score", range(11))
def test_stress_every_score_and_description(qtbot, service, score):
    form = stress_form(qtbot, service)
    assert form.score.choice.currentData() is None
    form.score.set_value(score)
    assert form.score.description.text() == get_numeric_scale("stress", 1).describe(score)
    form.submit()
    form.submit()
    saved = service.get("stress", form.record_id).value
    assert saved.score == score and saved.scale_version == 1
    assert not saved.causes and saved.comment is None
    with service.storage.read_snapshot() as session:
        assert len(session.stress.all()) == 1


def test_stress_requires_score_and_is_not_auto_zero(qtbot, service):
    form = stress_form(qtbot, service)
    form.submit()
    assert form.error.text() and not form._committed
    with service.storage.read_snapshot() as session:
        assert not session.stress.all()


def test_stress_create_view_edit_backdate(qtbot, service):
    assert service.stress_causes() == tuple(zip(StressCause, STRESS_CAUSE_LABELS))
    form = stress_form(qtbot, service)
    past = datetime.now(UTC) - timedelta(days=4)
    form.moment.set_moment(past)
    form.score.set_value(7)
    form.causes[StressCause.WORK].setChecked(True)
    form.causes[StressCause.HEALTH].setChecked(True)
    form.comment.setPlainText("Субъективное наблюдение")
    form.submit()
    old = service.get("stress", form.record_id).value
    assert old.observed_at == past and old.created_at > past
    assert old.causes == (StressCause.WORK, StressCause.HEALTH)
    reopened = stress_form(qtbot, service, form.record_id)
    assert reopened.comment.toPlainText() == old.comment
    assert reopened.causes[StressCause.WORK].isChecked()
    reopened.score.set_value(0)
    reopened.submit()
    saved = service.get("stress", form.record_id).value
    assert saved.score == 0 and not saved.causes and saved.comment is None
    assert saved.created_at == old.created_at and saved.observed_at == past
    assert saved.scale_version == old.scale_version
    assert service.stress_causes() == tuple(zip(StressCause, STRESS_CAUSE_LABELS))


@pytest.mark.parametrize("existing", [False, True])
def test_stress_zero_always_clears(qtbot, service, existing):
    form = stress_form(qtbot, service)
    if existing:
        form.score.set_value(0)
        form.submit()
        form = stress_form(qtbot, service, form.record_id)
    form.score.set_value(0)
    form.causes[StressCause.STUDY].setChecked(True)
    form.comment.setPlainText("Не сохранять при нуле")
    form.submit()
    saved = service.get("stress", form.record_id).value
    assert not saved.causes and saved.comment is None


@pytest.mark.parametrize("existing", [False, True])
def test_stress_clear_failure_rolls_back_and_retains_input(qtbot, service, monkeypatch, existing):
    form = stress_form(qtbot, service)
    form.score.set_value(8)
    form.causes[StressCause.WORK].setChecked(True)
    form.comment.setPlainText("Сохранить ввод при ошибке")
    old = None
    if existing:
        form.submit()
        old = service.get("stress", form.record_id).value
        form = stress_form(qtbot, service, form.record_id)
    form.score.set_value(0)
    before = form.state()
    children = StressRepository._children
    def fail(self, record_id, value):
        children(self, record_id, value)
        raise StorageError("private content")
    monkeypatch.setattr(StressRepository, "_children", fail)
    form.submit()
    assert not form._committed and form.state() == before
    assert "private" not in form.error.text()
    if existing:
        assert service.get("stress", form.record_id).value == old
    else:
        with service.storage.read_snapshot() as session:
            assert not session.stress.all()
    monkeypatch.setattr(StressRepository, "_children", children)
    form.submit()
    assert form._committed
    saved = service.get("stress", form.record_id).value
    assert saved.score == 0 and not saved.causes and saved.comment is None


def test_stress_quick_uses_same_application(qtbot, service, monkeypatch):
    calls = []
    original = service.save_stress
    def save(**fields):
        calls.append(fields)
        return original(**fields)
    monkeypatch.setattr(service, "save_stress", save)
    record_id = service.no_stress()
    assert len(calls) == 1 and calls[0]["score"] == 0
    saved = service.get("stress", record_id).value
    assert saved.score == 0 and not saved.causes and saved.comment is None

from healthtracker.presentation.forms.mood import MoodDialog


def mood_form(qtbot, service, record_id=None):
    form = MoodDialog(service, record_id=record_id)
    qtbot.addWidget(form)
    return form


@pytest.mark.parametrize("score", range(11))
def test_mood_every_score_description_and_independence(qtbot, service, score):
    form = mood_form(qtbot, service)
    assert form.score.choice.currentData() is None
    form.score.set_value(score)
    assert form.score.description.text() == get_numeric_scale("mood", 1).describe(score)
    form.submit()
    form.submit()
    saved = service.get("mood", form.record_id).value
    assert saved.score == score and saved.scale_version == 1
    with service.storage.read_snapshot() as session:
        assert len(session.mood.all()) == 1
        assert not session.stress.all() and not session.physical.all()


def test_mood_requires_score(qtbot, service):
    form = mood_form(qtbot, service)
    form.submit()
    assert form.error.text() and not form._committed
    with service.storage.read_snapshot() as session:
        assert not session.mood.all()


def test_mood_backdate_view_edit(qtbot, service):
    form = mood_form(qtbot, service)
    past = datetime.now(UTC) - timedelta(days=5)
    form.moment.set_moment(past)
    form.score.set_value(6)
    form.submit()
    original = service.get("mood", form.record_id).value
    assert original.observed_at == past and original.created_at > past
    edited = mood_form(qtbot, service, form.record_id)
    assert edited.score.choice.currentData() == 6
    assert edited.moment.moment() == past
    edited.score.set_value(0)
    edited.submit()
    saved = service.get("mood", form.record_id).value
    assert saved.score == 0 and saved.created_at == original.created_at
    assert saved.scale_version == original.scale_version and saved.updated_at >= original.updated_at


@pytest.mark.parametrize("existing", [False, True])
def test_mood_failed_commit_preserves_input(qtbot, service, monkeypatch, existing):
    form = mood_form(qtbot, service)
    form.score.set_value(8)
    old = None
    if existing:
        form.submit()
        old = service.get("mood", form.record_id).value
        form = mood_form(qtbot, service, form.record_id)
    form.score.set_value(0)
    original_write = service.storage.write
    @contextmanager
    def fail():
        with original_write() as session:
            yield session
            raise StorageError("private error")
    monkeypatch.setattr(service.storage, "write", fail)
    before = form.state()
    form.submit()
    assert form.state() == before and not form._committed
    assert "private" not in form.error.text()
    if existing:
        assert service.get("mood", form.record_id).value == old
    else:
        with service.storage.read_snapshot() as session:
            assert not session.mood.all()
    monkeypatch.setattr(service.storage, "write", original_write)
    form.submit()
    assert form._committed

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QSignalSpy
from healthtracker.application.session import ApplicationSession
from healthtracker.presentation.main_window import MainWindow


@pytest.mark.parametrize("form_class,kind", [(StressDialog,"stress"), (MoodDialog,"mood")])
def test_new_forms_keyboard_unsaved_cancel_and_future(qtbot, service, monkeypatch, form_class, kind):
    form = form_class(service)
    qtbot.addWidget(form)
    form.show()
    qtbot.waitExposed(form)
    QApplication.setActiveWindow(form) # deterministic QTest activation in Wayland
    form.score.choice.setFocus()
    qtbot.keyClick(form.score.choice, Qt.Key.Key_Down)
    assert form.score.choice.currentData() == 0
    qtbot.keyClick(form.score.choice, Qt.Key.Key_Tab)
    assert not form.score.choice.hasFocus()
    monkeypatch.setattr(form, "confirm_discard", lambda: False)
    qtbot.keyClick(form, Qt.Key.Key_Escape)
    assert form.isVisible()
    form.moment.set_moment(datetime.now(UTC) + timedelta(days=1))
    form.submit()
    assert not form._committed and form.error.text()
    form.moment.set_moment(datetime.now(UTC) - timedelta(days=1))
    qtbot.keyClick(form, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert form._committed
    assert service.get(kind, form.record_id).value.score == 0


def test_forms_reopen_database_without_losing_records(qtbot, service):
    stress = stress_form(qtbot, service)
    stress.score.set_value(9)
    stress.causes[StressCause.FINANCES].setChecked(True)
    stress.comment.setPlainText("Комментарий")
    stress.submit()
    mood = mood_form(qtbot, service)
    mood.score.set_value(0)
    mood.submit()
    path = service.storage.path
    service.storage.close()
    with Database(path) as database:
        restarted = Observations(database)
        reopened_stress = stress_form(qtbot, restarted, stress.record_id)
        assert reopened_stress.causes[StressCause.FINANCES].isChecked()
        assert reopened_stress.comment.toPlainText() == "Комментарий"
        assert reopened_stress.score.choice.currentData() == 9
        reopened_mood = mood_form(qtbot, restarted, mood.record_id)
        assert reopened_mood.score.choice.currentData() == 0


def test_stress_positive_child_failure_and_success_signal_after_commit(qtbot, service, monkeypatch):
    form = stress_form(qtbot, service)
    form.score.set_value(6)
    for check in form.causes.values():
        check.setChecked(True)
    form.comment.setPlainText("Не очищать форму")
    spy = QSignalSpy(form.saved)
    children = StressRepository._children
    def fail(self, record_id, value):
        children(self, record_id, value)
        raise StorageError("private")
    monkeypatch.setattr(StressRepository, "_children", fail)
    before = form.state()
    form.submit()
    assert spy.count() == 0 and form.state() == before
    with service.storage.read_snapshot() as session:
        assert not session.stress.all()
    monkeypatch.setattr(StressRepository, "_children", children)
    observed = []
    form.saved.connect(lambda kind, record_id: observed.append(service.get(kind, record_id)))
    form.submit()
    assert spy.count() == 1 and len(observed[0].value.causes) == 6


def test_main_menu_forms_quick_no_stress_and_reopen(qtbot, service):
    session = ApplicationSession(service.storage)
    assert session.open()
    window = MainWindow(session)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.chart.bridge.is_ready, timeout=20000)
    for name, cls, kind in [("Стресс", StressDialog, "stress"), ("Настроение", MoodDialog, "mood")]:
        window.add_actions[name].trigger()
        form = window.active_dialog
        assert isinstance(form, cls)
        form.score.set_value(5)
        form.submit()
        assert not window.physical_suggestion.isVisible()
        window._open_saved(f"{kind}:{form.record_id}")
        assert window.active_dialog.score.choice.currentData() == 5
        window.active_dialog.reject()
    window.add_actions["Стресса нет"].trigger()
    window.add_actions["Стресса нет"].trigger()
    window.mark_no_stress()  # защита и на границе обработчика
    with service.storage.read_snapshot() as s:
        assert len(s.stress.all()) == 2
        assert len(s.mood.all()) == 1
        assert not s.physical.all()
        zero = [r for r in s.stress.all() if r.value.score == 0][0]
        assert not zero.value.causes and zero.value.comment is None
    window._prepare_add_menu()  # новое осознанное действие
    window.add_actions["Стресса нет"].trigger()
    with service.storage.read_snapshot() as s:
        assert len(s.stress.all()) == 3
    assert window.close()


def test_quick_failure_no_false_success_allows_retry(qtbot, service, monkeypatch):
    app = ApplicationSession(service.storage)
    assert app.open()
    window = MainWindow(app)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.chart.bridge.is_ready, timeout=20000)
    original = app.observations.no_stress
    def fail():
        raise StorageError("secret")
    monkeypatch.setattr(app.observations, "no_stress", fail)
    window.mark_no_stress()
    assert "не подтверждена" in window.storage_status.text()
    assert "secret" not in window.storage_status.text()
    assert window.add_actions["Стресса нет"].isEnabled()
    monkeypatch.setattr(app.observations, "no_stress", original)
    window.mark_no_stress()
    with service.storage.read_snapshot() as s:
        assert len(s.stress.all()) == 1
    window.close()


def test_new_forms_cancel_does_not_change_existing(qtbot, service):
    for kind, make in [("stress", stress_form), ("mood", mood_form)]:
        form = make(qtbot, service)
        form.score.set_value(7)
        form.submit()
        original = service.get(kind, form.record_id)
        edited = make(qtbot, service, form.record_id)
        edited.score.set_value(0)
        edited.reject()
        assert service.get(kind, form.record_id) == original
