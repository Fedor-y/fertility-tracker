"""Удаление из сохранённой формы через существующий Diary, только искусственные базы."""
from contextlib import contextmanager
import pytest
from PySide6.QtCore import QDate,QTimer,Qt
from PySide6.QtWidgets import QApplication,QMessageBox
from healthtracker.application.errors import RecordNotFound,StorageError
from healthtracker.application.session import ApplicationSession
from healthtracker.presentation.main_window import MainWindow
from healthtracker.presentation.forms.common import EntryDialog
from test_diary import services,seed,DAY,rows


@pytest.fixture
def edit_window(services,qtbot,monkeypatch):
    monkeypatch.setattr(EntryDialog,'confirm_discard',lambda self:True)
    db,obs,_=services;ids=seed(obs)
    app=ApplicationSession(db);assert app.open()
    window=MainWindow(app,start_chart=False);qtbot.addWidget(window);window.show()
    qtbot.waitUntil(lambda:window._preferences_ready)
    window.diary.entry_date.setDate(QDate(DAY))
    yield window,db,obs,ids
    window.close();qtbot.waitUntil(lambda:not window.isVisible(),timeout=15000)


@pytest.mark.parametrize('kind',('cognitive','physical','stress','mood','sleep','meals','gym'))
def test_delete_saved_form_updates_diary_and_leaves_other_records(edit_window,qtbot,monkeypatch,kind):
    w,_,obs,ids=edit_window
    w._diary_open(kind,ids[kind]);form=w.active_dialog
    assert form.delete_button.isVisible() and form.delete_button.isEnabled()
    monkeypatch.setattr(form,'confirm_delete',lambda:True)
    with qtbot.waitSignal(form.deleted) as signal:form.delete_button.click()
    assert signal.args==[kind,ids[kind]] and form._committed and not form.isVisible()
    with pytest.raises(RecordNotFound):obs.get(kind,ids[kind])
    for other,id_ in ids.items():
        if other!=kind:assert obs.get(other,id_).id==id_
    assert len(rows(w.diary))==6


def test_real_confirmation_cancel_keeps_unsaved_input_then_delete(edit_window,qtbot):
    w,_,obs,ids=edit_window;w._diary_open('mood',ids['mood']);form=w.active_dialog
    form.score.set_value(7);state=form.state()
    def answer(button):
        box=QApplication.activeModalWidget()
        assert not form.buttons.isEnabled()
        assert box and 'Настроение' in box.text() and 'Несохранённые' in box.text()
        assert box.standardButton(box.defaultButton())==QMessageBox.StandardButton.No
        assert obs.get('mood',ids['mood']).value.score==0
        box.button(button).click()
    QTimer.singleShot(0,lambda:answer(QMessageBox.StandardButton.No))
    form.delete_button.click()
    assert form.isVisible() and form.state()==state and not form._committed and form.buttons.isEnabled()
    QTimer.singleShot(0,lambda:answer(QMessageBox.StandardButton.Yes))
    form.delete_button.click()
    with pytest.raises(RecordNotFound):obs.get('mood',ids['mood'])


def test_delete_failure_rolls_back_and_preserves_input_for_retry(edit_window,qtbot,monkeypatch):
    w,db,obs,ids=edit_window;w._diary_open('mood',ids['mood']);form=w.active_dialog
    form.score.set_value(8);state=form.state();write=db.write
    monkeypatch.setattr(form,'confirm_delete',lambda:True)
    @contextmanager
    def fail():
        with write() as session:
            yield session
            raise StorageError('private details')
    monkeypatch.setattr(db,'write',fail)
    form.delete_button.click()
    assert form.isVisible() and form.state()==state and form.delete_button.isEnabled()
    assert form.error.isVisible() and 'private' not in form.error.text() and not form._committed
    assert obs.get('mood',ids['mood']).value.score==0
    monkeypatch.setattr(db,'write',write)
    form.delete_button.click()
    with pytest.raises(RecordNotFound):obs.get('mood',ids['mood'])


def test_delete_large_id_clears_last_saved_action(edit_window,qtbot,monkeypatch):
    w,db,obs,ids=edit_window;large=1<<40
    with db.write() as s:s.connection.execute('UPDATE mood_entries SET id=? WHERE id=?',(large,ids['mood']))
    w.last_saved_action.setData(f'mood:{large}');w.last_saved_action.setEnabled(True)
    w._diary_open('mood',large);form=w.active_dialog
    monkeypatch.setattr(form,'confirm_delete',lambda:True)
    with qtbot.waitSignal(form.deleted) as signal:form.delete_button.click()
    assert signal.args==['mood',large]
    assert w.last_saved_action.data() is None and not w.last_saved_action.isEnabled()
    with pytest.raises(RecordNotFound):obs.get('mood',large)


def test_new_forms_have_no_delete_action(edit_window):
    w,_,_,_=edit_window
    for kind in ('cognitive','physical','stress','mood','sleep','meals','gym'):
        w._diary_open(kind,None);form=w.active_dialog
        assert not form.delete_button.isVisible() and not form.delete_button.isEnabled()
        form.reject()
