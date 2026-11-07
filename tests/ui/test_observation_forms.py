from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from PySide6.QtCore import QDate, QDateTime, QTime, QTimeZone, Qt
from PySide6.QtWidgets import QApplication

from healthtracker.application.errors import StorageError
from healthtracker.application.observations import Observations
from healthtracker.domain.answers import AnswerStatus
from healthtracker.domain.cognitive import cognitive_index
from healthtracker.domain.scales import CognitiveDifficulty, get_numeric_scale
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.presentation.forms.cognitive import CognitiveDialog
from healthtracker.presentation.forms.common import MomentInput


@pytest.fixture(autouse=True)
def discard_on_cleanup(monkeypatch):
    from healthtracker.presentation.forms.common import EntryDialog
    monkeypatch.setattr(EntryDialog, "confirm_discard", lambda self: True)


@pytest.fixture
def service(tmp_path):
    with Database(tmp_path / 'test.sqlite3') as db:
        yield Observations(db)


def dialog(qtbot, service, record_id=None):
    form = CognitiveDialog(service, record_id=record_id)
    qtbot.addWidget(form)
    return form


def fill(form, values=(0, 6, 9)):
    for field, value in zip(form.answers, values):
        field.set_value(value)


def test_empty_and_each_missing_answer(qtbot, service):
    form = dialog(qtbot, service)
    assert all(f.choice.currentData() is None for f in form.answers)
    for index in range(3):
        fill(form)
        form.answers[index].set_value(None)
        form.submit()
        assert not form._committed
        assert 'три' in form.error.text()
    with service.storage.read_snapshot() as s:
        assert not s.cognitive.all()
    form._initial = form.state()


@pytest.mark.parametrize('status', [AnswerStatus.NOT_ENGAGED, AnswerStatus.CANNOT_ASSESS])
@pytest.mark.parametrize('position', range(3))
def test_specials_not_zeros(qtbot, service, status, position):
    form = dialog(qtbot, service)
    fill(form, (0, 0, 0))
    form.answers[position].set_value(status)
    form.submit()
    saved = service.get('cognitive', form.record_id).value
    assert cognitive_index(saved.assessment) is None
    assert getattr(saved.assessment, ('learning','application','speed')[position]).status is status


def test_cognitive_create_view_edit_and_no_duplicate(qtbot, service):
    form = dialog(qtbot, service)
    fill(form)
    past = datetime.now(UTC) - timedelta(days=3)
    form.moment.set_moment(past)
    form.context.setPlainText('Чтение')
    form.difficulty.setCurrentIndex(2)
    form.submit()
    form.submit()
    old = service.get('cognitive', form.record_id).value
    assert cognitive_index(old.assessment) == 5
    assert old.interval.end == past
    assert old.interval.end - old.interval.start == timedelta(hours=1)
    assert old.created_at > past
    assert old.assessment.activity_difficulty is CognitiveDifficulty.ORDINARY
    reopened = dialog(qtbot, service, form.record_id)
    assert reopened.context.toPlainText() == 'Чтение'
    fill(reopened, (0,0,0))
    reopened.submit()
    updated = service.get('cognitive', form.record_id).value
    assert cognitive_index(updated.assessment) == 0
    assert updated.created_at == old.created_at
    assert updated.interval.end == past
    assert updated.assessment.formula_version == old.assessment.formula_version
    with service.storage.read_snapshot() as s:
        assert len(s.cognitive.all()) == 1


def test_exact_descriptions(qtbot, service):
    form = dialog(qtbot, service)
    for field, code in zip(form.answers, ('learning','application','speed')):
        for score in range(11):
            field.set_value(score)
            assert field.description.text() == get_numeric_scale(code).describe(score)
    form._initial = form.state()


def test_cognitive_failed_transaction_keeps_form(qtbot, service, monkeypatch):
    original = service.storage.write
    @contextmanager
    def failing():
        with original() as session:
            yield session
            raise StorageError('private details')
    monkeypatch.setattr(service.storage, 'write', failing)
    form = dialog(qtbot, service)
    fill(form)
    form.context.setPlainText('Сохранить ввод')
    form.submit()
    assert not form._committed and form.record_id is None
    assert form.context.toPlainText() == 'Сохранить ввод'
    assert 'private' not in form.error.text()
    with service.storage.read_snapshot() as s:
        assert not s.cognitive.all()
    monkeypatch.setattr(service.storage, 'write', original)
    form.submit()
    assert form._committed


def test_unsaved_escape_and_shortcut(qtbot, service, monkeypatch):
    form = dialog(qtbot, service)
    form.show()
    qtbot.waitExposed(form)
    QApplication.setActiveWindow(form) # deterministic QTest activation in Wayland
    fill(form)
    monkeypatch.setattr(form, 'confirm_discard', lambda: False)
    qtbot.keyClick(form, Qt.Key.Key_Escape)
    assert form.isVisible()
    qtbot.keyClick(form, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert form._committed


def test_time_dst_requires_explicit_offset(qtbot):
    widget = MomentInput(zone=ZoneInfo('Europe/Berlin'))
    qtbot.addWidget(widget)
    widget.edit.setDateTime(QDateTime(QDate(2026,10,25), QTime(2,30), QTimeZone.utc()))
    assert widget.offset.currentData() is None
    with pytest.raises(ValueError):
        widget.moment()
    widget.offset.setCurrentIndex(1)
    first = widget.moment()
    widget.offset.setCurrentIndex(2)
    assert widget.moment() - first == timedelta(hours=1)
    widget.edit.setDateTime(QDateTime(QDate(2026,3,29), QTime(2,30), QTimeZone.utc()))
    with pytest.raises(ValueError):
        widget.moment()

from healthtracker.domain.catalogs import SymptomCode, SymptomStatus
from healthtracker.domain.scales import SymptomIntensity
from healthtracker.presentation.forms.physical import PhysicalDialog


def physical(qtbot, service, record_id=None):
    form = PhysicalDialog(service, record_id=record_id)
    qtbot.addWidget(form)
    return form


@pytest.mark.parametrize('status', list(SymptomStatus))
def test_physical_statuses_and_zero(qtbot, service, status):
    form = physical(qtbot, service)
    assert form.score.choice.currentData() is None
    assert form.symptom_state is SymptomStatus.UNKNOWN
    form.submit()
    assert not form._committed
    form.score.set_value(0)
    if status is SymptomStatus.NONE_CONFIRMED:
        form.no_symptoms.click()
    elif status is SymptomStatus.LISTED:
        form.symptoms[SymptomCode.HEADACHE][0].setChecked(True)
    form.submit()
    saved = service.get('physical', form.record_id).value
    assert saved.score == 0 and saved.symptom_status is status
    form.submit()
    with service.storage.read_snapshot() as s:
        assert len(s.physical.all()) == 1


def test_physical_symptoms_view_edit_and_backdate(qtbot, service):
    form = physical(qtbot, service)
    form.score.set_value(10)
    past = datetime.now(UTC) - timedelta(days=2)
    form.moment.set_moment(past)
    for code in SymptomCode:
        form.symptoms[code][0].setChecked(True)
    form.symptoms[SymptomCode.MUSCLE_PAIN][1].setCurrentIndex(3)
    form.detail.setText('Уточнение')
    form.submit()
    old = service.get('physical', form.record_id).value
    assert len(old.symptoms) == 7
    assert old.observed_at == past and old.created_at > past
    reopened = physical(qtbot, service, form.record_id)
    assert reopened.symptoms[SymptomCode.MUSCLE_PAIN][1].currentData() == SymptomIntensity.SEVERE.value
    assert reopened.detail.text() == 'Уточнение'
    reopened.no_symptoms.click()
    reopened.submit()
    saved = service.get('physical', form.record_id).value
    assert not saved.symptoms and saved.symptom_status is SymptomStatus.NONE_CONFIRMED
    assert saved.created_at == old.created_at and saved.scale_version == old.scale_version
    assert saved.observed_at == past


def test_physical_unknown_and_none_exclusive(qtbot, service):
    form = physical(qtbot, service)
    form.no_symptoms.click()
    form.symptoms[SymptomCode.BODY_ACHES][0].setChecked(True)
    assert form.symptom_state is SymptomStatus.LISTED
    form.unknown.click()
    assert form.symptom_state is SymptomStatus.UNKNOWN
    assert not any(check.isChecked() for check, _ in form.symptoms.values())
    form._initial = form.state()


def test_physical_exact_scale(qtbot, service):
    form = physical(qtbot, service)
    for score in range(11):
        form.score.set_value(score)
        assert form.score.description.text() == get_numeric_scale('physical').describe(score)
    form._initial = form.state()


def test_physical_failure_rolls_back_children_keeps_input(qtbot, service, monkeypatch):
    from healthtracker.infrastructure.sqlite.physical import PhysicalRepository
    form = physical(qtbot, service)
    form.score.set_value(7)
    form.symptoms[SymptomCode.OTHER][0].setChecked(True)
    form.detail.setText('Не терять')
    children = PhysicalRepository._children
    def fail(self, record_id, value):
        children(self, record_id, value)
        raise StorageError('private')
    monkeypatch.setattr(PhysicalRepository, '_children', fail)
    form.submit()
    assert not form._committed
    assert form.detail.text() == 'Не терять'
    with service.storage.read_snapshot() as s:
        assert not s.physical.all()
    monkeypatch.setattr(PhysicalRepository, '_children', children)
    form.submit()
    assert form._committed


@pytest.mark.parametrize('kind', ['cognitive', 'physical'])
def test_future_rejected(qtbot, service, kind):
    form = dialog(qtbot, service) if kind == 'cognitive' else physical(qtbot, service)
    if kind == 'cognitive':
        fill(form)
    else:
        form.score.set_value(5)
    form.moment.set_moment(datetime.now(UTC) + timedelta(days=1))
    form.submit()
    assert not form._committed and form.error.text()
    form._initial = form.state()


@pytest.mark.parametrize('intensity', [None, *SymptomIntensity])
def test_each_symptom_intensity_roundtrip(qtbot, service, intensity):
    form = physical(qtbot, service)
    form.score.set_value(5)
    check, choice = form.symptoms[SymptomCode.NAUSEA]
    check.setChecked(True)
    choice.setCurrentIndex(choice.findData(intensity.value if intensity else None))
    form.submit()
    saved = service.get('physical', form.record_id).value
    assert saved.symptoms[0].intensity is intensity


@pytest.mark.parametrize('kind', ['cognitive','physical'])
def test_edit_failure_preserves_database_and_form(qtbot, service, monkeypatch, kind):
    form = dialog(qtbot, service) if kind == 'cognitive' else physical(qtbot, service)
    if kind == 'cognitive':
        fill(form)
    else:
        form.score.set_value(4)
    form.submit()
    original_value = service.get(kind, form.record_id).value
    edited = dialog(qtbot, service, form.record_id) if kind == 'cognitive' else physical(qtbot, service, form.record_id)
    if kind == 'cognitive':
        fill(edited, (9,9,9))
    else:
        edited.score.set_value(0)
        edited.symptoms[SymptomCode.HEADACHE][0].setChecked(True)
    expected_input = edited.state()
    original_write = service.storage.write
    @contextmanager
    def failing():
        with original_write() as session:
            yield session
            raise StorageError('failure before commit')
    monkeypatch.setattr(service.storage, 'write', failing)
    edited.submit()
    assert edited.state() == expected_input
    assert not edited._committed
    assert service.get(kind, form.record_id).value == original_value
    edited._initial = edited.state()


def test_saved_forms_survive_database_reopening(qtbot, service):
    first = dialog(qtbot, service)
    fill(first, (0,0,0))
    first.submit()
    second = physical(qtbot, service)
    second.score.set_value(10)
    second.no_symptoms.click()
    second.submit()
    path = service.storage.path
    service.storage.close()
    with Database(path) as reopened:
        new_service = Observations(reopened)
        c = dialog(qtbot, new_service, first.record_id)
        p = physical(qtbot, new_service, second.record_id)
        assert [f.choice.currentData() for f in c.answers] == [0,0,0]
        assert p.score.choice.currentData() == 10
        assert p.symptom_state is SymptomStatus.NONE_CONFIRMED


def test_main_window_opens_both_forms_and_saved_edit(qtbot, service, monkeypatch):
    from healthtracker.application.session import ApplicationSession
    from healthtracker.presentation.main_window import MainWindow
    app = ApplicationSession(service.storage)
    assert app.open()
    window = MainWindow(app)
    qtbot.addWidget(window)
    window.show()
    window.cognitive_button.click()
    cognitive = window.active_dialog
    fill(cognitive)
    cognitive.submit()
    assert 'Открыть запись' in window.storage_status.text()
    assert window.physical_suggestion.isVisible()
    window._open_saved(f'cognitive:{cognitive.record_id}')
    assert window.active_dialog.record_id == cognitive.record_id
    window.active_dialog.reject()
    window.physical_button.click()
    physical_form = window.active_dialog
    assert isinstance(physical_form, PhysicalDialog)
    physical_form.score.set_value(6)
    monkeypatch.setattr(physical_form, 'confirm_discard', lambda: False)
    assert not window.close()
    assert app.storage_available
    monkeypatch.setattr(physical_form, 'confirm_discard', lambda: True)
    assert window.close()


@pytest.mark.parametrize('kind', ['cognitive','physical'])
def test_arrow_choice_and_tab(qtbot, service, kind):
    form = dialog(qtbot, service) if kind == 'cognitive' else physical(qtbot, service)
    form.show()
    form.activateWindow()
    qtbot.wait(30)
    choice = form.answers[0].choice if kind == 'cognitive' else form.score.choice
    choice.setFocus()
    qtbot.keyClick(choice, Qt.Key.Key_Down)
    assert choice.currentData() == 0
    qtbot.keyClick(choice, Qt.Key.Key_Tab)
    assert not choice.hasFocus()
    form._initial = form.state()
