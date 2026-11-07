from contextlib import contextmanager
from datetime import date,timedelta

import pytest
from PySide6.QtCore import Qt,QDate
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication,QDateEdit,QDateTimeEdit

from healthtracker.application.errors import StorageError
from healthtracker.application.observations import Observations
from healthtracker.domain.scales import get_numeric_scale
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.infrastructure.sqlite.gym import GymRepository
from healthtracker.presentation.forms.common import EntryDialog
from healthtracker.presentation.forms.gym import GymDialog

DAY=date(2026,11,1)


@pytest.fixture(autouse=True)
def discard_cleanup(monkeypatch):
    monkeypatch.setattr(EntryDialog,'confirm_discard',lambda self:True)


@pytest.fixture
def service(tmp_path):
    with Database(tmp_path/'gym.sqlite3') as database:
        yield Observations(database)


def make(qtbot,service,record_id=None):
    form=GymDialog(service,record_id=record_id)
    qtbot.addWidget(form)
    return form


def fill(form,score=5,day=DAY):
    form.set_date(day)
    form.attended.setCurrentIndex(form.attended.findData(True))
    form.difficulty.set_value(score)


def test_gym_blank_date_answer_score_and_unknown_not_zero(qtbot,service):
    form=make(qtbot,service)
    assert not form.date_selected
    assert form.attended.currentData() is None
    assert form.difficulty.choice.currentData() is None
    assert not form.difficulty.isEnabled()
    form.submit();assert not form._committed
    form.set_date(DAY);form.submit();assert not form._committed
    form.attended.setCurrentIndex(1)
    assert form.difficulty.isEnabled() and form.difficulty.choice.currentData() is None
    form.submit();assert not form._committed
    with service.storage.read_snapshot() as s:
        assert not s.gym.all()


@pytest.mark.parametrize('score',range(11))
def test_gym_all_scores_exact_descriptions_and_duplicate_submission(qtbot,service,score):
    form=make(qtbot,service);fill(form,score)
    assert form.difficulty.description.text()==get_numeric_scale('gym_difficulty',1).describe(score)
    form.submit();form.submit()
    saved=service.get('gym',form.record_id).value
    assert saved.difficulty==score and saved.difficulty_scale_version==1 and saved.entry_date==DAY
    assert saved.created_at.date()>DAY
    with service.storage.read_snapshot() as s:
        assert len(s.gym.all())==1


def test_gym_no_null_yes_requires_new_choice_and_view(qtbot,service):
    form=make(qtbot,service);fill(form,0)
    form.attended.setCurrentIndex(2)
    assert not form.difficulty.isEnabled() and form.difficulty.choice.currentData() is None
    form.submit()
    old=service.get('gym',form.record_id).value
    assert old.attended is False and old.difficulty is None
    reopened=make(qtbot,service,form.record_id)
    assert reopened.attended.currentData() is False and reopened.difficulty.choice.currentData() is None
    reopened.attended.setCurrentIndex(1)
    reopened.submit();assert not reopened._committed
    assert service.get('gym',form.record_id).value==old
    reopened.difficulty.set_value(8);reopened.submit()
    saved=service.get('gym',form.record_id).value
    assert saved.difficulty==8 and saved.created_at==old.created_at


def test_gym_edit_date_uniqueness_no_overwrite(qtbot,service):
    first=make(qtbot,service);fill(first);first.submit()
    form=make(qtbot,service);fill(form,9)
    before=form.state();form.submit()
    assert not form._committed and form.state()==before
    assert 'уже существует' in form.error.text()
    form.set_date(DAY+timedelta(days=1));form.submit();assert form._committed
    old=service.get('gym',first.record_id)
    edited=make(qtbot,service,first.record_id)
    assert edited.difficulty.choice.currentData()==5
    edited.set_date(DAY+timedelta(days=1));edited.difficulty.set_value(7)
    before=edited.state();edited.submit()
    assert not edited._committed and edited.state()==before
    assert service.get('gym',first.record_id)==old
    edited.set_date(DAY);edited.submit()
    saved=service.get('gym',first.record_id).value
    assert saved.created_at==old.value.created_at and saved.difficulty==7
    assert saved.difficulty_scale_version==old.value.difficulty_scale_version


@pytest.mark.parametrize('existing',[False,True])
@pytest.mark.parametrize('stage',['write','commit'])
def test_gym_failure_rollback_keeps_input_retry(qtbot,service,monkeypatch,existing,stage):
    form=make(qtbot,service);fill(form)
    old=None
    if existing:
        form.submit();old=service.get('gym',form.record_id)
        form=make(qtbot,service,form.record_id)
    form.difficulty.set_value(0)
    write=service.storage.write
    method=GymRepository.update if existing else GymRepository.create
    if stage=='commit':
        @contextmanager
        def fail():
            with write() as s:
                yield s
                raise StorageError('private')
        monkeypatch.setattr(service.storage,'write',fail)
    else:
        def fail(*args,**kwargs):
            raise StorageError('private')
        monkeypatch.setattr(GymRepository,'update' if existing else 'create',fail)
    spy=QSignalSpy(form.saved);before=form.state();form.submit()
    assert not form._committed and form.state()==before and spy.count()==0
    assert 'private' not in form.error.text()
    if existing:
        assert service.get('gym',form.record_id)==old
    else:
        with service.storage.read_snapshot() as s:
            assert not s.gym.all()
    monkeypatch.setattr(service.storage,'write',write)
    monkeypatch.setattr(GymRepository,'update' if existing else 'create',method)
    form.saved.connect(lambda kind,record_id: service.get(kind,record_id))
    form.submit();assert form._committed and spy.count()==1


def test_gym_future_no_time_and_reopen(qtbot,service):
    form=make(qtbot,service);fill(form)
    assert all(isinstance(w,QDateEdit) for w in form.findChildren(QDateTimeEdit))
    form.set_date(date.today()+timedelta(days=1));form.submit();assert not form._committed
    form.set_date(DAY);form.submit()
    old=service.get('gym',form.record_id)
    path=service.storage.path;service.storage.close()
    with Database(path) as database:
        reopened=make(qtbot,Observations(database),form.record_id)
        assert reopened.entry_date.date().toPython()==DAY
        assert reopened.difficulty.choice.currentData()==old.value.difficulty


def test_gym_main_menu_keyboard_and_open_saved(qtbot,service,monkeypatch):
    from healthtracker.application.session import ApplicationSession
    from healthtracker.presentation.main_window import MainWindow
    app=ApplicationSession(service.storage);assert app.open()
    window=MainWindow(app);qtbot.addWidget(window);window.show()
    qtbot.waitUntil(lambda:window.chart.bridge.is_ready,timeout=20000)
    assert all(action.isEnabled() for action in window.add_actions.values())
    window.add_actions['Спортзал'].trigger()
    form=window.active_dialog
    assert isinstance(form,GymDialog)
    qtbot.waitExposed(form)
    QApplication.setActiveWindow(form) # test-only activation for Wayland QTest
    form.date_button.setFocus();qtbot.keyClick(form.date_button,Qt.Key.Key_Space)
    assert form.date_selected and form.entry_date.isVisible()
    assert form.attended.currentData() is None
    form.set_date(DAY)
    form.attended.setCurrentIndex(1)
    form.difficulty.choice.setFocus()
    qtbot.keyClick(form.difficulty.choice,Qt.Key.Key_Down)
    assert form.difficulty.choice.currentData()==0
    qtbot.keyClick(form.difficulty.choice,Qt.Key.Key_Tab)
    assert form.focusWidget() is not form.difficulty.choice
    monkeypatch.setattr(form,'confirm_discard',lambda:False)
    qtbot.keyClick(form,Qt.Key.Key_Escape);assert form.isVisible()
    qtbot.keyClick(form,Qt.Key.Key_Return,Qt.KeyboardModifier.ControlModifier)
    assert form._committed and 'Открыть запись' in window.storage_status.text()
    window._open_saved(f'gym:{form.record_id}')
    assert window.active_dialog.record_id==form.record_id
    assert window.active_dialog.difficulty.choice.currentData()==0
    window.active_dialog.reject()
    window.close()
