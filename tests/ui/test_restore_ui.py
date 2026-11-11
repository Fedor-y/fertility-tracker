"""Подтверждение, worker, защитная копия и новое открытие приложения в Wayland."""
from datetime import UTC, datetime
from threading import Event

import pytest
from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtWidgets import QMessageBox, QScrollArea

from healthtracker.application.backups import BackupRequest
from healthtracker.application.session import ApplicationSession
from healthtracker.domain.records import MoodRecord
from healthtracker.infrastructure.sqlite.backup import SQLiteBackup
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.infrastructure.sqlite.restore import SQLiteRestore
from healthtracker.presentation.backup_page import file_size
from healthtracker.presentation.main_window import MainWindow

NOW=datetime(2026,11,4,12,tzinfo=UTC)


@pytest.fixture
def ui(qtbot,tmp_path):
    db=Database(tmp_path/'data/source.sqlite3',clock=lambda:NOW)
    backup=SQLiteBackup(db)
    installer=SQLiteRestore(db)
    app=ApplicationSession(db,backup_port=backup,restore_port=installer)
    assert app.open()
    with db.write() as session:
        session.settings.set('compact_mode',False)
        session.mood.create(MoodRecord(observed_at=NOW,score=4,created_at=NOW,updated_at=NOW))
    selected=app.backups.create(BackupRequest(backup.default_directory)).result(5)
    with db.write() as session:
        session.settings.set('compact_mode',True)
        session.mood.create(MoodRecord(observed_at=NOW,score=9,created_at=NOW,updated_at=NOW))
    settings=QSettings(str(tmp_path/'window.ini'),QSettings.Format.IniFormat)
    window=MainWindow(application=app,settings=settings,start_chart=False)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda:window._preferences_ready,timeout=10000)
    window.navigation.setCurrentRow(3)
    page=window.backup_page
    qtbot.waitUntil(lambda:page.future is None,timeout=10000)
    assert page.results==(selected,)
    yield window,page,db,app,backup,installer,selected,settings
    app.shutdown_backups()
    window.close()
    qtbot.waitUntil(lambda:not window.isVisible(),timeout=15000)


def confirm(monkeypatch,selected,yes=True):
    def dialog(box):
        text=box.text()
        assert 'полностью заменены' in text
        assert selected.metadata.created_at_utc.astimezone().strftime('%d.%m.%Y %H:%M:%S') in text
        assert file_size(selected.metadata.size_bytes) in text
        assert 'Статус:' in text
        assert box.standardButton(box.defaultButton())==QMessageBox.StandardButton.No
        return QMessageBox.StandardButton.Yes if yes else QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox,'exec',dialog)


def click_restore(qtbot,page):
    assert page.restore_button.isEnabled()
    page.findChild(QScrollArea).ensureWidgetVisible(page.restore_button)
    qtbot.mouseClick(page.restore_button,Qt.MouseButton.LeftButton)


def test_user_restore_and_new_window_preserve_restored_preferences(ui,qtbot,monkeypatch):
    window,page,db,app,_,_,selected,settings=ui
    assert window.chart_controls.preferences().compact_mode is True
    confirm(monkeypatch,selected)
    click_restore(qtbot,page)
    qtbot.waitUntil(lambda:app.restart_required and page.future is None,timeout=15000)
    assert 'Данные восстановлены и проверены' in page.status.text()
    assert page.restart_button.isVisible()
    assert not window.navigation.isEnabled()
    assert not window.cognitive_button.isEnabled()
    assert not page.restore_button.isEnabled()
    assert 'Текущее состояние сохранено' in page.summary.text()
    qtbot.mouseClick(page.restart_button,Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda:not window.isVisible(),timeout=15000)
    assert not db.access_status.opened
    reopened_db=Database(db.path,clock=lambda:NOW)
    reopened=ApplicationSession(reopened_db,backup_port=SQLiteBackup(reopened_db),restore_port=SQLiteRestore(reopened_db))
    assert reopened.open()
    other=MainWindow(application=reopened,settings=settings,start_chart=False)
    qtbot.addWidget(other)
    other.show()
    try:
        qtbot.waitUntil(lambda:other._preferences_ready,timeout=10000)
        assert other.chart_controls.preferences().compact_mode is False
        with reopened_db.read_snapshot() as session:
            assert [item.value.score for item in session.mood.all()]==[4]
            assert session.settings.get('compact_mode') is False
    finally:
        reopened.shutdown_backups()
        other.close()
        qtbot.waitUntil(lambda:not other.isVisible(),timeout=15000)


def test_cancel_confirmation_keeps_current_data_and_creates_no_safety_copy(ui,qtbot,monkeypatch):
    window,page,db,app,_,_,selected,_=ui
    before=db.capture_token()
    confirm(monkeypatch,selected,yes=False)
    click_restore(qtbot,page)
    assert page.future is None
    assert db.capture_token()==before
    assert len(list(selected.directory.parent.iterdir()))==1
    assert app.storage_available and window.navigation.isEnabled()
    with db.read_snapshot() as session:
        assert len(session.mood.all())==2


def test_damaged_selection_is_rejected_and_window_can_continue(ui,qtbot,monkeypatch):
    window,page,db,app,_,_,selected,_=ui
    selected.database_path.write_bytes(b'synthetic broken snapshot')
    confirm(monkeypatch,selected)
    click_restore(qtbot,page)
    qtbot.waitUntil(lambda:page.error.isVisible() and not page._restore_preparing,timeout=15000)
    assert app.storage_available
    assert window.navigation.isEnabled()
    assert 'Не удалось восстановить' in page.error.text()
    assert len(list(selected.directory.parent.iterdir()))==1
    with db.read_snapshot() as session:
        assert len(session.mood.all())==2


def test_safety_backup_error_is_visible_and_retry_can_restore(ui,qtbot,monkeypatch):
    window,page,db,app,backup,_,selected,_=ui
    original=backup._copy
    def fail(*args):
        raise OSError('synthetic disk problem')
    monkeypatch.setattr(backup,'_copy',fail)
    confirm(monkeypatch,selected)
    click_restore(qtbot,page)
    qtbot.waitUntil(lambda:page.error.isVisible() and not page._restore_preparing,timeout=15000)
    assert app.storage_available and window.navigation.isEnabled()
    monkeypatch.setattr(backup,'_copy',original)
    qtbot.waitUntil(page.restore_button.isEnabled,timeout=5000)
    click_restore(qtbot,page)
    qtbot.waitUntil(lambda:app.restart_required and page.future is None,timeout=15000)
    assert 'Данные восстановлены' in page.status.text()


def test_close_during_replace_waits_for_worker_without_blocking_qt(ui,qtbot,monkeypatch):
    window,page,db,app,_,installer,selected,_=ui
    entered,release,tick=Event(),Event(),Event()
    original=installer._replace
    def blocked(*args):
        assert db.access_status.active_sessions==0
        entered.set()
        assert release.wait(10)
        original(*args)
    monkeypatch.setattr(installer,'_replace',blocked)
    confirm(monkeypatch,selected)
    click_restore(qtbot,page)
    try:
        qtbot.waitUntil(entered.is_set,timeout=10000)
        assert not window.close()
        assert window.isVisible()
        QTimer.singleShot(0,tick.set)
        qtbot.waitUntil(tick.is_set,timeout=3000)
    finally:
        release.set()
    qtbot.waitUntil(lambda:not window.isVisible(),timeout=15000)
    with Database(db.path,clock=lambda:NOW) as reopened:
        with reopened.read_snapshot() as session:
            assert [item.value.score for item in session.mood.all()]==[4]


def test_close_during_preparation_waits_for_confirmed_restore(ui,qtbot,monkeypatch):
    window,page,db,app,_,_,selected,_=ui
    release=Event()
    original=window.preferences_controller.flush_for_close
    monkeypatch.setattr(window.preferences_controller,'flush_for_close',lambda:original() if release.is_set() else None)
    confirm(monkeypatch,selected)
    click_restore(qtbot,page)
    assert window._restore_pending is not None and page.future is None
    assert not window.close()
    assert window.isVisible()
    release.set()
    qtbot.waitUntil(lambda:not window.isVisible(),timeout=15000)
    with Database(db.path,clock=lambda:NOW) as reopened:
        with reopened.read_snapshot() as session:
            assert [item.value.score for item in session.mood.all()]==[4]
