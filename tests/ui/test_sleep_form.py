from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from PySide6.QtCore import QDate, QDateTime, QTime, QTimeZone, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QSignalSpy

from healthtracker.application.observations import Observations
from healthtracker.application.errors import StorageError
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.presentation.forms.common import EntryDialog
from healthtracker.presentation.forms.sleep import SleepDialog

BASE = datetime(2026, 11, 1, 22, tzinfo=UTC)


@pytest.fixture(autouse=True)
def discard_cleanup(monkeypatch):
    monkeypatch.setattr(EntryDialog,'confirm_discard',lambda self: True)


@pytest.fixture
def service(tmp_path):
    with Database(tmp_path/'sleep.sqlite3') as database:
        yield Observations(database)


def make(qtbot, service, record_id=None):
    form=SleepDialog(service,record_id=record_id)
    qtbot.addWidget(form)
    return form


def fill(form,start=BASE,hours=8):
    form.start.set_moment(start)
    form.end.set_moment(start+timedelta(hours=hours))


def set_local(widget, year,month,day,hour,minute=0):
    # Нейтральные компоненты; UTC здесь только режим Qt-редактора, не пояс события.
    widget.edit.setDateTime(QDateTime(QDate(year,month,day),QTime(hour,minute),QTimeZone.utc()))


def test_sleep_starts_empty_and_each_moment_required(qtbot,service):
    form=make(qtbot,service)
    assert not form.start.is_provided and not form.end.is_provided
    assert not form.start.editor.isVisible()
    assert form.state()==((False,),(False,))
    form.submit()
    assert not form._committed and 'дату' in form.error.text()
    form.start.set_moment(BASE)
    form.submit()
    assert not form._committed
    with service.storage.read_snapshot() as s:
        assert not s.sleep.all()


def test_sleep_placeholder_explicit_input_and_keyboard(qtbot,service,monkeypatch):
    form=make(qtbot,service)
    form.show()
    qtbot.waitExposed(form)
    # Wayland не обязан принимать программный запрос активации окна.
    # Для QTest явно назначаем активное окно внутри Qt.
    QApplication.setActiveWindow(form)
    qtbot.waitUntil(form.isActiveWindow,timeout=1000)
    form.start.placeholder.setFocus()
    qtbot.keyClick(form.start.placeholder,Qt.Key.Key_Space)
    assert form.start.is_provided and form.start.edit.isVisible()
    assert not form.end.is_provided
    fill(form)
    monkeypatch.setattr(form,'confirm_discard',lambda: False)
    qtbot.keyClick(form,Qt.Key.Key_Escape)
    assert form.isVisible()
    form.start.edit.setFocus()
    qtbot.keyClick(form.start.edit,Qt.Key.Key_Tab)
    qtbot.keyClick(form,Qt.Key.Key_Return,Qt.KeyboardModifier.ControlModifier)
    assert form._committed, (form.error.text(), form.isActiveWindow(), form.state())


def test_sleep_create_view_edit_precision_and_duplicate(qtbot,service):
    form=make(qtbot,service)
    past=BASE.replace(microsecond=654321)
    fill(form,start=past)
    assert '8:00:00' in form.preview.text()
    form.submit();form.submit()
    old=service.get('sleep',form.record_id).value
    assert old.interval.start==past and old.created_at>old.interval.end
    assert old.interval.date_in(ZoneInfo('UTC')).day==2
    reopened=make(qtbot,service,form.record_id)
    assert reopened.start.moment()==old.interval.start
    assert reopened.end.moment()==old.interval.end
    reopened.submit() # unchanged precise times; no self-conflict
    saved=service.get('sleep',form.record_id).value
    assert saved.created_at==old.created_at and saved.interval==old.interval
    with service.storage.read_snapshot() as s:
        assert len(s.sleep.all())==1


@pytest.mark.parametrize('hours',[15,16,17])
@pytest.mark.parametrize('confirmed',[False,True])
def test_sleep_confirmation_threshold_and_decline(qtbot,service,monkeypatch,hours,confirmed):
    form=make(qtbot,service);fill(form,hours=hours)
    calls=[]
    def confirm(interval):
        with service.storage.read_snapshot() as s:
            assert not s.sleep.all() # no transaction/write before confirmation
        calls.append(interval)
        return confirmed
    monkeypatch.setattr(form,'confirm_long_sleep',confirm)
    before=form.state()
    form.submit()
    assert len(calls)==(1 if hours>16 else 0)
    assert form._committed==(hours<=16 or confirmed)
    assert form.state()==before
    if not form._committed:
        assert form.isEnabled() and form.record_id is None


@pytest.mark.parametrize('existing',[False,True])
def test_sleep_failure_after_confirmation_rolls_back_keeps_input(qtbot,service,monkeypatch,existing):
    form=make(qtbot,service);fill(form)
    old=None
    if existing:
        form.submit();old=service.get('sleep',form.record_id)
        form=make(qtbot,service,form.record_id)
    fill(form,hours=17)
    monkeypatch.setattr(form,'confirm_long_sleep',lambda interval: True)
    write=service.storage.write
    @contextmanager
    def fail():
        with write() as s:
            yield s
            raise StorageError('private error')
    monkeypatch.setattr(service.storage,'write',fail)
    spy=QSignalSpy(form.saved)
    before=form.state();form.submit()
    assert form.state()==before and not form._committed
    assert spy.count()==0 and 'private' not in form.error.text()
    if existing:
        assert service.get('sleep',form.record_id)==old
    else:
        with service.storage.read_snapshot() as s:
            assert not s.sleep.all()
    monkeypatch.setattr(service.storage,'write',write)
    form.saved.connect(lambda kind,record_id: service.get(kind,record_id))
    form.submit()
    assert form._committed and spy.count()==1


@pytest.mark.parametrize('hours',[0,-1])
def test_sleep_invalid_order(qtbot,service,hours):
    form=make(qtbot,service);fill(form,hours=hours);form.submit()
    assert not form._committed and form.error.text()


def test_sleep_future_rejected(qtbot,service):
    form=make(qtbot,service);fill(form,start=datetime.now(UTC),hours=1);form.submit()
    assert not form._committed and 'будущ' in form.error.text()


def test_sleep_overlap_keeps_old_and_input(qtbot,service):
    first=service.save_sleep(start=BASE,end=BASE+timedelta(hours=4))
    second=service.save_sleep(start=BASE+timedelta(hours=4),end=BASE+timedelta(hours=8))
    old=service.get('sleep',first)
    form=make(qtbot,service,first)
    form.end.set_moment(BASE+timedelta(hours=5));before=form.state();form.submit()
    assert not form._committed and 'пересек' in form.error.text()
    assert form.state()==before and service.get('sleep',first)==old
    assert service.get('sleep',second).value.interval.start==BASE+timedelta(hours=4)


@pytest.mark.parametrize('month,day,start_hour,end_hour,expected',[(3,29,1,3,1),(10,25,1,3,3)])
def test_sleep_dst_real_duration(qtbot,service,month,day,start_hour,end_hour,expected):
    form=make(qtbot,service)
    zone=ZoneInfo('Europe/Berlin')
    form.start.zone=form.end.zone=zone
    fill(form)
    set_local(form.start,2026,month,day,start_hour,30)
    set_local(form.end,2026,month,day,end_hour,30)
    form.submit()
    assert form._committed
    assert service.get('sleep',form.record_id).value.interval.duration==timedelta(hours=expected)


def test_sleep_dst_nonexistent_and_repeated_choice(qtbot,service):
    form=make(qtbot,service)
    form.start.zone=form.end.zone=ZoneInfo('Europe/Berlin')
    fill(form)
    set_local(form.start,2026,3,29,2,30)
    set_local(form.end,2026,3,29,3,30)
    form.submit()
    assert not form._committed and 'не существует' in form.error.text()
    set_local(form.start,2026,10,25,2,15)
    set_local(form.end,2026,10,25,2,45)
    assert form.start.offset.currentData() is None and form.end.offset.currentData() is None
    form.submit()
    assert not form._committed and 'смещение' in form.error.text()
    form.start.offset.setCurrentIndex(1)
    form.submit() # end still ambiguous
    assert not form._committed
    form.end.offset.setCurrentIndex(2)
    form.submit()
    assert form._committed
    assert service.get('sleep',form.record_id).value.interval.duration==timedelta(hours=1,minutes=30)


def test_sleep_timezone_change_preserves_utc_and_reopening(qtbot,service,monkeypatch):
    form=make(qtbot,service);fill(form,start=BASE.replace(microsecond=123456));form.submit()
    old=service.get('sleep',form.record_id)
    import healthtracker.presentation.forms.common as common
    monkeypatch.setattr(common,'ZoneInfo',lambda _: ZoneInfo('America/Los_Angeles'))
    reopened=make(qtbot,service,form.record_id)
    assert reopened.start.moment()==old.value.interval.start
    assert reopened.end.moment()==old.value.interval.end
    assert '01.11.2026' in reopened.preview.text() # UTC wake date is 2 November
    reopened.submit()
    assert service.get('sleep',form.record_id).value.interval==old.value.interval
    path=service.storage.path
    service.storage.close()
    with Database(path) as db:
        assert Observations(db).get('sleep',form.record_id).value.interval==old.value.interval


@pytest.mark.parametrize('accept',[False,True])
def test_actual_long_sleep_warning(qtbot,service,accept):
    form=make(qtbot,service);fill(form,hours=17)
    seen=[]
    def answer():
        box=form.findChild(QMessageBox)
        assert box is not None
        seen.append(box.text())
        with service.storage.read_snapshot() as s:
            assert not s.sleep.all()
        box.button(QMessageBox.StandardButton.Yes if accept else QMessageBox.StandardButton.No).click()
    QTimer.singleShot(30,answer)
    form.submit()
    assert len(seen)==1 and '16' in seen[0]
    assert form._committed is accept


def test_sleep_write_error_keeps_input(qtbot,service,monkeypatch):
    from healthtracker.infrastructure.sqlite.sleep import SleepRepository
    form=make(qtbot,service);fill(form)
    def fail(*args,**kwargs):
        raise StorageError('private')
    monkeypatch.setattr(SleepRepository,'create',fail)
    before=form.state();form.submit()
    assert not form._committed and form.state()==before
    with service.storage.read_snapshot() as s:
        assert not s.sleep.all()


def test_sleep_main_menu_and_open_saved(qtbot,service):
    from healthtracker.application.session import ApplicationSession
    from healthtracker.presentation.main_window import MainWindow
    application=ApplicationSession(service.storage)
    assert application.open()
    window=MainWindow(application)
    qtbot.addWidget(window);window.show()
    qtbot.waitUntil(lambda: window.chart.bridge.is_ready,timeout=20000)
    window.add_actions['Сон'].trigger()
    form=window.active_dialog
    assert isinstance(form,SleepDialog)
    assert not form.start.is_provided and not form.end.is_provided
    fill(form);form.submit()
    assert 'Открыть запись' in window.storage_status.text()
    window._open_saved(f'sleep:{form.record_id}')
    assert window.active_dialog.record_id==form.record_id
    assert window.active_dialog.start.moment()==BASE
    window.active_dialog.reject()
    assert window.add_actions['Питание'].isEnabled()
    assert window.add_actions['Спортзал'].isEnabled()
    assert window.close()
