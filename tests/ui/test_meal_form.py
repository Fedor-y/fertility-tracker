from contextlib import contextmanager
from datetime import date, timedelta

import pytest
from PySide6.QtCore import QDate, QTimer, Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QMessageBox

from healthtracker.application.errors import StorageError
from healthtracker.application.observations import Observations
from healthtracker.domain.catalogs import CaffeineStatus, MealCategory
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.infrastructure.sqlite.meals import MealRepository
from healthtracker.presentation.forms.common import EntryDialog
from healthtracker.presentation.forms.meal import MealDialog

DAY=date(2026,11,1)


@pytest.fixture(autouse=True)
def discard_cleanup(monkeypatch):
    monkeypatch.setattr(EntryDialog,'confirm_discard',lambda self: True)


@pytest.fixture
def service(tmp_path):
    with Database(tmp_path/'meal.sqlite3') as db:
        yield Observations(db)


def make(qtbot,service,record_id=None):
    form=MealDialog(service,record_id=record_id)
    qtbot.addWidget(form)
    return form


def fill(form,category=MealCategory.LUNCH):
    form.entry_date.setDate(QDate(DAY))
    form.category.setCurrentIndex(form.category.findData(category.value))
    form.items[0].name.setText('Гречка с курицей')


def test_meal_required_fields_and_empty_rows(qtbot,service):
    form=make(qtbot,service)
    assert form.category.currentData() is None
    assert form.items[0].name.text()==''
    assert form.items[0].caffeine.currentData()==CaffeineStatus.UNSPECIFIED.value
    form.submit();assert not form._committed
    form.category.setCurrentIndex(1)
    form.submit();assert not form._committed
    form.items[0].name.setText('  ')
    form.submit();assert not form._committed
    form.items[0].remove_button.click()
    form.submit();assert not form._committed
    with service.storage.read_snapshot() as s:
        assert not s.meals.all()
    form.add_button.click();assert len(form.items)==1
    fill(form);form.submit();assert form._committed


@pytest.mark.parametrize('caffeine',list(CaffeineStatus))
def test_meal_fields_create_view_edit_add_remove(qtbot,service,caffeine):
    form=make(qtbot,service);fill(form)
    form.items[0].composition.setPlainText('Крупа, курица')
    form.items[0].quantity.setText('Большая тарелка')
    form.items[0].caffeine.setCurrentIndex(form.items[0].caffeine.findData(caffeine.value))
    form.add_button.click()
    form.items[1].name.setText('Вода')
    form.note.setPlainText('Субъективная заметка')
    form.submit();form.submit()
    old=service.get('meals',form.record_id).value
    assert len(old.items)==2 and old.items[0].caffeine_status is caffeine
    assert old.entry_date==DAY and old.created_at.date()>DAY
    reopened=make(qtbot,service,form.record_id)
    assert reopened.items[0].composition.toPlainText()=='Крупа, курица'
    assert reopened.items[0].quantity.text()=='Большая тарелка'
    assert reopened.note.toPlainText()==old.note
    reopened.items[0].remove_button.click()
    reopened.add_button.click();reopened.items[1].name.setText('Чай')
    reopened.entry_date.setDate(QDate(DAY+timedelta(days=1)))
    reopened.category.setCurrentIndex(reopened.category.findData(MealCategory.DINNER.value))
    reopened.submit()
    saved=service.get('meals',form.record_id).value
    assert saved.created_at==old.created_at
    assert saved.items[0]==old.items[1]
    assert [i.name for i in saved.items]==['Вода','Чай']
    with service.storage.read_snapshot() as s:
        assert len(s.meals.all())==1


@pytest.mark.parametrize('confirm',[False,True])
def test_meal_duplicate_confirm_or_cancel_retains_form(qtbot,service,monkeypatch,confirm):
    original=make(qtbot,service);fill(original);original.submit()
    form=make(qtbot,service);fill(form)
    seen=[]
    def answer(ids):
        seen.append(ids)
        with service.storage.read_snapshot() as s:
            assert len(s.meals.all())==1
        return 'confirm' if confirm else 'cancel'
    monkeypatch.setattr(form,'confirm_duplicate',answer)
    before=form.state();form.submit()
    assert seen==[(original.record_id,)] and form.state()==before
    assert form._committed is confirm
    with service.storage.read_snapshot() as s:
        assert len(s.meals.all())==(2 if confirm else 1)
    if confirm:
        edited=make(qtbot,service,form.record_id)
        monkeypatch.setattr(edited,'confirm_duplicate',lambda ids: pytest.fail('Unchanged pair must not warn'))
        edited.note.setPlainText('Правка заметки');edited.submit();assert edited._committed


def test_meal_other_no_warning(qtbot,service,monkeypatch):
    for _ in range(2):
        form=make(qtbot,service);fill(form,MealCategory.OTHER)
        monkeypatch.setattr(form,'confirm_duplicate',lambda ids: pytest.fail('Other must not warn'))
        form.submit();assert form._committed


def test_actual_duplicate_dialog_decline(qtbot,service):
    original=make(qtbot,service);fill(original);original.submit()
    form=make(qtbot,service);fill(form)
    def answer():
        box=form.findChild(QMessageBox)
        assert box is not None
        next(b for b in box.buttons() if b.text()=='Вернуться к форме').click()
    QTimer.singleShot(30,answer)
    before=form.state();form.submit()
    assert form.state()==before and not form._committed


@pytest.mark.parametrize('existing',[False,True])
@pytest.mark.parametrize('stage',['parent','item','commit'])
def test_meal_failure_rollback_and_preserved_input(qtbot,service,monkeypatch,existing,stage):
    form=make(qtbot,service);fill(form)
    old=None
    if existing:
        form.submit();old=service.get('meals',form.record_id)
        form=make(qtbot,service,form.record_id)
    form.add_button.click();form.items[1].name.setText('Салат')
    before=form.state();spy=QSignalSpy(form.saved)
    write=service.storage.write
    children=MealRepository._children
    if stage=='commit':
        @contextmanager
        def fail():
            with write() as s:
                yield s
                raise StorageError('private')
        monkeypatch.setattr(service.storage,'write',fail)
    else:
        def fail(self,record_id,value):
            if stage=='item':
                from dataclasses import replace
                children(self,record_id,replace(value,items=value.items[:1]))
            raise StorageError('private')
        monkeypatch.setattr(MealRepository,'_children',fail)
    form.submit()
    assert form.state()==before and not form._committed and spy.count()==0
    assert 'private' not in form.error.text()
    if existing:
        assert service.get('meals',form.record_id)==old
    else:
        with service.storage.read_snapshot() as s:
            assert not s.meals.all()
            assert s.connection.execute('SELECT count(*) FROM meal_items').fetchone()[0]==0
    monkeypatch.setattr(service.storage,'write',write)
    monkeypatch.setattr(MealRepository,'_children',children)
    form.saved.connect(lambda kind,record_id: service.get(kind,record_id))
    form.submit()
    assert form._committed and spy.count()==1


@pytest.mark.parametrize('change',['date','category'])
def test_edit_changed_category_or_date_prompts(qtbot,service,monkeypatch,change):
    original=make(qtbot,service);fill(original);original.submit()
    form=make(qtbot,service);fill(form)
    if change=='date':
        form.entry_date.setDate(QDate(DAY+timedelta(days=1)))
    else:
        form.category.setCurrentIndex(form.category.findData(MealCategory.DINNER.value))
    form.submit()
    old=service.get('meals',form.record_id)
    edit=make(qtbot,service,form.record_id)
    edit.entry_date.setDate(QDate(DAY))
    edit.category.setCurrentIndex(edit.category.findData(MealCategory.LUNCH.value))
    monkeypatch.setattr(edit,'confirm_duplicate',lambda ids: 'cancel')
    edit.submit()
    assert not edit._committed and service.get('meals',form.record_id)==old
    monkeypatch.setattr(edit,'confirm_duplicate',lambda ids: 'confirm')
    edit.submit();assert edit._committed


def test_duplicate_open_existing_keeps_draft(qtbot,service,monkeypatch):
    original=make(qtbot,service);fill(original);original.submit()
    form=make(qtbot,service);fill(form)
    form.note.setPlainText('Не терять текущий ввод')
    monkeypatch.setattr(form,'confirm_duplicate',lambda ids:'open')
    def edit_existing():
        child=form.findChild(MealDialog)
        assert child is not None and child.record_id==original.record_id
        child.note.setPlainText('Правка существующей записи')
        child.submit()
    QTimer.singleShot(40,edit_existing)
    before=form.state();form.submit()
    assert form.state()==before and not form._committed and form.record_id is None
    assert service.get('meals',original.record_id).value.note=='Правка существующей записи'
    with service.storage.read_snapshot() as s:
        assert len(s.meals.all())==1


def test_meal_future_and_no_time_input(qtbot,service):
    from PySide6.QtWidgets import QDateEdit,QDateTimeEdit
    form=make(qtbot,service);fill(form)
    assert all(isinstance(w,QDateEdit) for w in form.findChildren(QDateTimeEdit))
    form.entry_date.setDate(QDate.currentDate().addDays(1));form.submit()
    assert not form._committed and form.error.text()


def test_meal_reopen_database(qtbot,service):
    form=make(qtbot,service);fill(form)
    form.items[0].quantity.setText('Половина порции')
    form.submit()
    old=service.get('meals',form.record_id)
    path=service.storage.path;service.storage.close()
    with Database(path) as db:
        restarted=Observations(db)
        reopened=make(qtbot,restarted,form.record_id)
        assert reopened.items[0].quantity.text()=='Половина порции'
        assert restarted.get('meals',form.record_id)==old


def test_meal_menu_saved_action_and_keyboard(qtbot,service,monkeypatch):
    from healthtracker.application.session import ApplicationSession
    from healthtracker.presentation.main_window import MainWindow
    app=ApplicationSession(service.storage);assert app.open()
    window=MainWindow(app);qtbot.addWidget(window);window.show()
    qtbot.waitUntil(lambda:window.chart.bridge.is_ready,timeout=20000)
    window.add_actions['Питание'].trigger()
    form=window.active_dialog
    assert isinstance(form,MealDialog)
    qtbot.waitExposed(form)
    QApplication.setActiveWindow(form) # QTest activation; Wayland may reject activateWindow
    fill(form)
    form.items[0].name.setFocus()
    qtbot.keyClick(form.items[0].name,Qt.Key.Key_Tab)
    monkeypatch.setattr(form,'confirm_discard',lambda:False)
    qtbot.keyClick(form,Qt.Key.Key_Escape);assert form.isVisible()
    qtbot.keyClick(form,Qt.Key.Key_Return,Qt.KeyboardModifier.ControlModifier)
    assert form._committed and 'Открыть запись' in window.storage_status.text()
    window._open_saved(f'meals:{form.record_id}')
    assert window.active_dialog.record_id==form.record_id
    assert window.active_dialog.items[0].name.text()=='Гречка с курицей'
    window.active_dialog.reject()
    assert window.add_actions['Спортзал'].isEnabled()
    window.close()


def test_meal_historical_date_not_silently_clamped(qtbot,service):
    form=make(qtbot,service);fill(form)
    form.entry_date.setDate(QDate(1700,1,1))
    form.submit()
    reopened=make(qtbot,service,form.record_id)
    assert reopened.entry_date.date().toPython()==date(1700,1,1)


def test_duplicate_confirmed_then_failed_commit(qtbot,service,monkeypatch):
    original=make(qtbot,service);fill(original);original.submit()
    form=make(qtbot,service);fill(form)
    monkeypatch.setattr(form,'confirm_duplicate',lambda ids:'confirm')
    write=service.storage.write
    @contextmanager
    def fail():
        with write() as s:
            yield s
            raise StorageError('before commit')
    monkeypatch.setattr(service.storage,'write',fail)
    before=form.state();spy=QSignalSpy(form.saved);form.submit()
    assert not form._committed and form.state()==before and spy.count()==0
    with service.storage.read_snapshot() as s:
        assert len(s.meals.all())==1


def test_dynamic_positions_tab_follows_visual_order(qtbot,service):
    form=make(qtbot,service);form.show();qtbot.waitExposed(form)
    form.add_button.click()
    first,second=form.items
    first.composition.setFocus()
    qtbot.keyClick(first.composition,Qt.Key.Key_Tab)
    assert form.focusWidget() is first.quantity
    first.remove_button.setFocus()
    qtbot.keyClick(first.remove_button,Qt.Key.Key_Tab)
    assert form.focusWidget() is second.name
    second.remove_button.click()
    first.remove_button.setFocus()
    qtbot.keyClick(first.remove_button,Qt.Key.Key_Tab)
    assert form.focusWidget() is form.add_button
