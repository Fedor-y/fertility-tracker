from contextlib import contextmanager
from datetime import UTC,date,datetime,timedelta
from zoneinfo import ZoneInfo

import pytest
from PySide6.QtCore import QDate,QTimer,Qt
from PySide6.QtWidgets import QApplication,QDateTimeEdit,QMessageBox

from healthtracker.application.diary import Diary,KINDS
from healthtracker.application.errors import RecordNotFound,StorageError
from healthtracker.application.observations import Observations
from healthtracker.application.session import ApplicationSession
from healthtracker.domain.answers import CognitiveAnswer
from healthtracker.domain.catalogs import MealCategory,SymptomStatus
from healthtracker.domain.cognitive import CognitiveAssessment
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.presentation.diary import DiaryPage
from healthtracker.presentation.forms.common import EntryDialog
from healthtracker.presentation.main_window import MainWindow

DAY=date(2026,11,1)
MOMENT=datetime(2026,11,1,12,tzinfo=UTC)


@pytest.fixture(autouse=True)
def discard_cleanup(monkeypatch):
    monkeypatch.setattr(EntryDialog,'confirm_discard',lambda self:True)


@pytest.fixture
def services(tmp_path):
    with Database(tmp_path/'diary.sqlite3') as db:
        obs=Observations(db)
        yield db,obs,Diary(db)


def seed(obs):
    assessment=CognitiveAssessment(*(CognitiveAnswer.numeric(0) for _ in range(3)))
    return {
        'cognitive':obs.save_cognitive(assessment,MOMENT),
        'physical':obs.save_physical(score=0,observed_at=MOMENT,symptom_status=SymptomStatus.NONE_CONFIRMED,symptoms=()),
        'stress':obs.save_stress(score=0,observed_at=MOMENT),
        'mood':obs.save_mood(score=0,observed_at=MOMENT),
        'sleep':obs.save_sleep(start=MOMENT-timedelta(hours=8),end=MOMENT),
        'meals':obs.save_meal(entry_date=DAY,category=MealCategory.OTHER,items=({'name':'Чай'},)),
        'gym':obs.save_gym(entry_date=DAY,attended=False),
    }


def page(qtbot,service,zone_provider=lambda:ZoneInfo('UTC')):
    widget=DiaryPage(service,zone_provider=zone_provider)
    qtbot.addWidget(widget)
    widget.entry_date.setDate(QDate(DAY))
    widget.show()
    return widget


def rows(widget):
    return [widget.records.topLevelItem(g).child(i)
            for g in range(widget.records.topLevelItemCount())
            for i in range(widget.records.topLevelItem(g).childCount())
            if widget.records.topLevelItem(g).child(i).data(0,Qt.ItemDataRole.UserRole) is not None]


def select(widget,kind):
    item=next(i for i in rows(widget) if i.data(0,Qt.ItemDataRole.UserRole).kind==kind)
    widget.records.setCurrentItem(item)
    return item


def test_diary_empty_all_types_and_switch_day(qtbot,services):
    db,obs,diary=services
    widget=page(qtbot,diary)
    assert not rows(widget) and 'нет' in widget.status.text()
    assert not widget.open_button.isEnabled() and not widget.delete_button.isEnabled()
    seed(obs);widget.refresh()
    assert len(rows(widget))==7
    assert widget.records.topLevelItem(0).childCount()==5
    assert widget.records.topLevelItem(1).childCount()==2
    assert 'Индекс: 0.00' in select(widget,'cognitive').text(2)
    assert select(widget,'meals').text(0)=='Без времени'
    assert 'не был' in select(widget,'gym').text(2)
    widget.entry_date.setDate(QDate(DAY+timedelta(days=1)))
    assert not rows(widget)


@pytest.mark.parametrize('kind',KINDS)
def test_diary_delete_cancel_then_commit(qtbot,services,monkeypatch,kind):
    db,obs,diary=services;ids=seed(obs);widget=page(qtbot,diary)
    select(widget,kind)
    monkeypatch.setattr(widget,'confirm_delete',lambda entry:False)
    widget.delete_button.click();assert len(rows(widget))==7
    monkeypatch.setattr(widget,'confirm_delete',lambda entry:True)
    widget.delete_button.click()
    assert len(rows(widget))==6 and 'удалена' in widget.status.text()
    with pytest.raises(RecordNotFound):
        obs.get(kind,ids[kind])


def test_actual_delete_confirmation(qtbot,services):
    db,obs,diary=services;seed(obs);widget=page(qtbot,diary);select(widget,'mood')
    def answer():
        box=widget.findChild(QMessageBox)
        assert box and 'Настроение' in box.text() and '01.11.2026' in box.text()
        box.button(QMessageBox.StandardButton.No).click()
    QTimer.singleShot(30,answer)
    widget.delete_selected();assert len(rows(widget))==7


def test_diary_delete_failure_and_stale_record(qtbot,services,monkeypatch):
    db,obs,diary=services;ids=seed(obs);widget=page(qtbot,diary);select(widget,'meals')
    monkeypatch.setattr(widget,'confirm_delete',lambda entry:True)
    write=db.write
    @contextmanager
    def fail():
        with write() as s:
            yield s
            raise StorageError('private')
    monkeypatch.setattr(db,'write',fail)
    widget.delete_selected()
    assert len(rows(widget))==7 and 'не подтверждено' in widget.status.text()
    assert 'private' not in widget.status.text()
    monkeypatch.setattr(db,'write',write)
    diary.delete('meals',ids['meals'],confirmed=True)
    widget.delete_selected()
    assert len(rows(widget))==6 and 'уже удалена' in widget.status.text()


def test_diary_zone_change_regroups_without_changing_source(qtbot,services):
    db,obs,diary=services
    moment=datetime(2026,11,1,0,15,tzinfo=UTC)
    record_id=obs.save_mood(score=0,observed_at=moment)
    current=[ZoneInfo('UTC')]
    widget=page(qtbot,diary,lambda:current[0])
    assert len(rows(widget))==1
    current[0]=ZoneInfo('America/New_York')
    widget._check_zone()
    assert not rows(widget) and 'пояс изменился' in widget.zone_notice.text()
    assert obs.get('mood',record_id).value.observed_at==moment
    widget.entry_date.setDate(QDate(DAY-timedelta(days=1)))
    assert len(rows(widget))==1


@pytest.mark.parametrize('kind',KINDS)
def test_open_edit_each_kind_same_id_and_refresh(qtbot,services,kind):
    db,obs,diary=services;ids=seed(obs)
    app=ApplicationSession(db);assert app.open()
    window=MainWindow(app);qtbot.addWidget(window);window.show()
    qtbot.waitUntil(lambda:window.chart.bridge.is_ready,timeout=20000)
    window.diary.zone_provider=lambda:ZoneInfo('UTC')
    window.navigation.setCurrentRow(2)
    window.diary.entry_date.setDate(QDate(DAY))
    old=obs.get(kind,ids[kind])
    select(window.diary,kind);window.diary.open_button.click()
    form=window.active_dialog
    assert form.record_id==ids[kind]
    if kind=='cognitive': form.context.setPlainText('Исправленный контекст')
    elif kind=='physical': form.score.set_value(7)
    elif kind=='stress': form.score.set_value(7)
    elif kind=='mood': form.score.set_value(7)
    elif kind=='sleep': form.end.set_moment(old.value.interval.end+timedelta(minutes=1))
    elif kind=='meals': form.note.setPlainText('Исправленная заметка')
    else:
        form.attended.setCurrentIndex(1);form.difficulty.set_value(0)
    form.submit();assert form._committed
    updated=obs.get(kind,ids[kind])
    assert updated.id==old.id and updated.value.created_at==old.value.created_at
    assert updated.value.updated_at>=old.value.updated_at
    if kind in ('physical','stress','mood'):
        assert updated.value.observed_at==old.value.observed_at
        assert updated.value.scale_version==old.value.scale_version
    if kind=='cognitive':
        assert updated.value.interval==old.value.interval
        assert updated.value.assessment.formula_version==old.value.assessment.formula_version
    assert len(rows(window.diary))==7
    if kind=='mood': assert '7/10' in select(window.diary,kind).text(2)
    window.close()


@pytest.mark.parametrize('kind',KINDS)
def test_add_selected_date_without_fabricated_time(qtbot,services,kind):
    db,obs,diary=services
    app=ApplicationSession(db);assert app.open()
    window=MainWindow(app);qtbot.addWidget(window);window.show()
    qtbot.waitUntil(lambda:window.chart.bridge.is_ready,timeout=20000)
    window.diary.zone_provider=lambda:ZoneInfo('UTC')
    window.navigation.setCurrentRow(2);window.diary.entry_date.setDate(QDate(DAY))
    window.diary.add_actions[kind].trigger();form=window.active_dialog
    if kind in ('cognitive','physical','stress','mood'):
        assert form.moment.requested_date==DAY and form.moment.requested_time.text()==''
        if kind=='cognitive':
            for answer in form.answers: answer.set_value(0)
        else: form.score.set_value(0)
        form.submit();assert not form._committed
        form.moment.requested_time.setText('12:00')
    elif kind=='sleep':
        assert form.end.requested_date==DAY and not form.start.is_provided
        form.start.set_moment(MOMENT-timedelta(hours=8));form.end.requested_time.setText('12:00')
    elif kind=='meals':
        assert form.entry_date.date().toPython()==DAY
        form.category.setCurrentIndex(1);form.items[0].name.setText('Еда')
    else:
        assert form.entry_date.date().toPython()==DAY and form.date_selected
        form.attended.setCurrentIndex(2)
    form.submit();assert form._committed
    assert len(rows(window.diary))==1
    window.close()


def test_diary_load_error_is_not_empty_data(qtbot,services,monkeypatch):
    db,obs,diary=services;seed(obs);widget=page(qtbot,diary)
    assert len(rows(widget))==7
    @contextmanager
    def fail():
        raise StorageError('private')
        yield
    monkeypatch.setattr(db,'read_snapshot',fail)
    assert not widget.refresh() and not rows(widget)
    assert 'не подтверждено' in widget.status.text() and 'private' not in widget.status.text()


def test_long_diary_scroll_keyboard_and_reopen(qtbot,services,monkeypatch):
    db,obs,diary=services
    for minute in range(80):
        obs.save_mood(score=minute%11,observed_at=MOMENT+timedelta(minutes=minute))
    widget=page(qtbot,diary);widget.resize(760,450)
    qtbot.waitExposed(widget)
    QApplication.setActiveWindow(widget)
    item=rows(widget)[-1];widget.records.setCurrentItem(item)
    widget.records.scrollToItem(item)
    qtbot.waitUntil(lambda:widget.records.verticalScrollBar().maximum()>0)
    seen=[];widget.open_requested.connect(lambda kind,record_id:seen.append((kind,record_id)))
    widget.records.setFocus();qtbot.keyClick(widget.records,Qt.Key.Key_Return)
    assert seen==[('mood',80)]
    monkeypatch.setattr(widget,'confirm_delete',lambda entry:True)
    qtbot.keyClick(widget.records,Qt.Key.Key_Delete)
    assert len(rows(widget))==79
    path=db.path;db.close()
    with Database(path) as restarted:
        widget.service=Diary(restarted);widget.refresh()
        assert len(rows(widget))==79
    widget.service=None


def test_retro_time_input_dst_and_no_guessed_hour(qtbot):
    from healthtracker.presentation.forms.common import MomentInput
    from healthtracker.domain.errors import DomainValidationError
    widget=MomentInput(zone=ZoneInfo('Europe/Berlin'));qtbot.addWidget(widget)
    widget.request_date(date(2026,3,29))
    assert widget.requested_time.text()==''
    with pytest.raises(DomainValidationError): widget.moment()
    widget.requested_time.setText('02:30')
    with pytest.raises(DomainValidationError,match='не существует'): widget.moment()
    widget.request_date(date(2026,10,25));widget.requested_time.setText('02:30')
    assert widget.offset.currentData() is None
    with pytest.raises(DomainValidationError,match='смещение'): widget.moment()
    widget.show();qtbot.waitExposed(widget)
    widget.requested_day.setFocus()
    # Tab сначала проходит секции даты; из последней секции выходит к времени.
    widget.requested_day.setCurrentSection(QDateTimeEdit.Section.YearSection)
    qtbot.keyClick(widget.requested_day,Qt.Key.Key_Tab)
    assert widget.focusWidget() is widget.requested_time
    qtbot.keyClick(widget.requested_time,Qt.Key.Key_Tab)
    assert widget.focusWidget() is widget.offset
    widget.offset.setCurrentIndex(1);first=widget.moment()
    widget.offset.setCurrentIndex(2);assert widget.moment()-first==timedelta(hours=1)


def test_edit_failed_save_retains_form_then_moves_date(qtbot,services,monkeypatch):
    db,obs,diary=services;ids=seed(obs)
    app=ApplicationSession(db);assert app.open()
    window=MainWindow(app);qtbot.addWidget(window);window.show()
    qtbot.waitUntil(lambda:window.chart.bridge.is_ready,timeout=20000)
    window.diary.zone_provider=lambda:ZoneInfo('UTC')
    window.navigation.setCurrentRow(2);window.diary.entry_date.setDate(QDate(DAY))
    select(window.diary,'mood');window.diary.open_selected();form=window.active_dialog
    form.score.set_value(9);old=obs.get('mood',ids['mood'])
    write=db.write
    @contextmanager
    def fail():
        with write() as s:
            yield s
            raise StorageError('private')
    monkeypatch.setattr(db,'write',fail)
    form.submit()
    assert not form._committed and form.score.choice.currentData()==9
    assert obs.get('mood',ids['mood'])==old
    assert '0/10' in select(window.diary,'mood').text(2)
    monkeypatch.setattr(db,'write',write)
    form.moment.set_moment(MOMENT+timedelta(days=1));form.submit()
    assert form._committed and len(rows(window.diary))==6
    window.diary.entry_date.setDate(QDate(DAY+timedelta(days=1)))
    assert len(rows(window.diary))==1 and '9/10' in rows(window.diary)[0].text(2)
    window.close()


def test_missing_record_open_and_graph_failure_not_diary_failure(qtbot,services,monkeypatch):
    db,obs,diary=services;ids=seed(obs)
    app=ApplicationSession(db);assert app.open()
    window=MainWindow(app);qtbot.addWidget(window);window.show()
    qtbot.waitUntil(lambda:window.chart.bridge.is_ready,timeout=20000)
    window.diary.zone_provider=lambda:ZoneInfo('UTC')
    window.navigation.setCurrentRow(2);window.diary.entry_date.setDate(QDate(DAY))
    select(window.diary,'mood');diary.delete('mood',ids['mood'],confirmed=True)
    messages=[]
    monkeypatch.setattr('healthtracker.presentation.main_window.show_warning',lambda *args:messages.append(args[1]))
    window.diary.open_selected()
    assert messages
    window.chart.failed.emit();window.diary.refresh()
    assert len(rows(window.diary))==6
    window.close()


@pytest.mark.parametrize('kind',KINDS)
def test_cancel_edit_each_type_preserves_record(qtbot,services,monkeypatch,kind):
    db,obs,diary=services
    ids=seed(obs)
    old=obs.get(kind,ids[kind])
    application=ApplicationSession(db)
    assert application.open()
    window=MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window._diary_open(kind,ids[kind])
    form=window.active_dialog
    if kind=='cognitive': form.context.setPlainText('Отменённая правка')
    elif kind in ('physical','stress','mood'): form.score.set_value(9)
    elif kind=='sleep': form.end.set_moment(MOMENT+timedelta(minutes=1))
    elif kind=='meals': form.note.setPlainText('Отменённая правка')
    else:
        form.attended.setCurrentIndex(1)
        form.difficulty.set_value(9)
    monkeypatch.setattr(form,'confirm_discard',lambda:False)
    form.reject()
    assert form.isVisible() and obs.get(kind,ids[kind])==old
    monkeypatch.setattr(form,'confirm_discard',lambda:True)
    form.reject()
    assert not form.isVisible() and obs.get(kind,ids[kind])==old
    window.close()
    with Database(db.path) as reopened:
        assert Observations(reopened).get(kind,ids[kind])==old
