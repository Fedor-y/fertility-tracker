"""Пользовательские сценарии резервирования в настоящем Qt/Wayland."""
import os
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog

from healthtracker.application.backups import BackupPhase, BackupProgress
from healthtracker.application.session import ApplicationSession
from healthtracker.infrastructure.sqlite.backup import SQLiteBackup, inspect_backup
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.presentation.backup_page import DIRECTORY_KEY, file_size
from healthtracker.presentation.main_window import MainWindow


@pytest.fixture
def ui(qtbot,tmp_path):
    db=Database(tmp_path/'data/source.sqlite3')
    adapter=SQLiteBackup(db)
    app=ApplicationSession(db,backup_port=adapter)
    assert app.open()
    settings=QSettings(str(tmp_path/'window.ini'),QSettings.Format.IniFormat)
    window=MainWindow(application=app,settings=settings,start_chart=False)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda:window._preferences_ready,timeout=10000)
    window.navigation.setCurrentRow(3)
    page=window.backup_page
    qtbot.waitUntil(lambda:page.future is None,timeout=10000)
    yield window,page,adapter,db,app,settings
    app.shutdown_backups()
    window.close()
    qtbot.waitUntil(lambda:not window.isVisible(),timeout=15000)


def choose(monkeypatch,directory):
    def dialog(parent,title,start):
        assert title=='Куда сохранить резервную копию'
        assert Path(start).is_absolute()
        return str(directory) if directory is not None else ''
    monkeypatch.setattr(QFileDialog,'getExistingDirectory',dialog)


def create(qtbot,page):
    assert page.create_button.isEnabled()
    qtbot.mouseClick(page.create_button,Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda:page.future is None,timeout=15000)


def test_open_backup_page_in_settings_prepares_default_and_empty_state(ui):
    window,page,adapter,db,app,settings=ui
    assert window.navigation.currentItem().text()=='Настройки'
    assert window.pages.currentWidget() is page
    assert page.directory==db.path.parent/'backups'
    assert page.directory.is_dir()
    assert page.directory.stat().st_mode&0o777==0o700
    assert not list(page.directory.iterdir())
    assert page.table.rowCount()==0
    assert 'пока нет' in page.status.text()
    assert page.create_button.isEnabled()
    assert not page.open_button.isEnabled()
    assert not settings.contains(DIRECTORY_KEY)


@pytest.mark.parametrize('open_success',[True,False])
def test_create_through_ui_lists_verified_copy_date_size_and_open_location(ui,qtbot,tmp_path,monkeypatch,open_success):
    window,page,adapter,db,app,settings=ui
    target=tmp_path/'chosen'
    target.mkdir(mode=0o700)
    token=db.capture_token()
    choose(monkeypatch,target)
    create(qtbot,page)
    assert 'Копия создана и проверена' in page.status.text()
    assert page.table.rowCount()==1
    result=inspect_backup(page.results[0].directory)
    assert page.table.item(0,0).text()==result.metadata.created_at_utc.astimezone().strftime('%d.%m.%Y %H:%M:%S')
    assert page.table.item(0,1).text()==file_size(result.metadata.size_bytes)
    assert page.table.item(0,2).text()=='Проверена'
    assert result.metadata.source==token==db.capture_token()
    assert settings.value(DIRECTORY_KEY)==str(target)
    assert page.directory==target
    assert page.table.visualItemRect(page.table.item(0,0)).height()>0
    assert app.storage_available
    opened=[]
    monkeypatch.setattr(QDesktopServices,'openUrl',lambda url:opened.append(url) or open_success)
    qtbot.mouseClick(page.open_button,Qt.MouseButton.LeftButton)
    assert len(opened)==1 and opened[0].isLocalFile()
    assert Path(opened[0].toLocalFile())==result.directory
    if open_success:
        assert not page.error.isVisible()
        preview=Path('/tmp/healthtracker-backup-preview')/os.environ.get('QT_SCALE_FACTOR','1')
        preview.mkdir(parents=True,exist_ok=True)
        assert window.grab().save(str(preview/'backups.png'))
    else:
        assert 'файловый менеджер' in page.error.text()
        assert page.error.isVisible()
        assert page.create_button.isEnabled()


def test_cancel_directory_dialog_does_not_create_or_change_settings(ui,qtbot,monkeypatch):
    _,page,_,db,app,settings=ui
    token=db.capture_token()
    choose(monkeypatch,None)
    create(qtbot,page)
    assert not list(page.directory.iterdir())
    assert not settings.contains(DIRECTORY_KEY)
    assert page.table.rowCount()==0
    assert page.create_button.isEnabled()
    assert db.capture_token()==token and app.storage_available


def test_creation_failure_is_visible_and_retry_succeeds(ui,qtbot,tmp_path,monkeypatch):
    window,page,adapter,db,app,_=ui
    original=adapter._copy
    calls=0
    def fail_once(source,target,progress):
        nonlocal calls
        calls+=1
        if calls==1:
            raise OSError('synthetic disk failure: must not reach UI')
        return original(source,target,progress)
    monkeypatch.setattr(adapter,'_copy',fail_once)
    target=tmp_path/'selected'
    choose(monkeypatch,target)
    create(qtbot,page)
    assert page.error.isVisible() and 'Не удалось' in page.error.text()
    assert 'synthetic' not in page.error.text()
    assert page.table.rowCount()==0 and app.storage_available
    assert not list(target.iterdir())
    window.navigation.setCurrentRow(0)
    window.navigation.setCurrentRow(3)
    assert page.error.isVisible() and 'Не удалось' in page.error.text()
    create(qtbot,page)
    assert not page.error.isVisible()
    assert page.table.rowCount()==1
    assert 'создана и проверена' in page.status.text()


def test_progress_gui_responsiveness_and_close_during_creation(ui,qtbot,monkeypatch):
    window,page,adapter,db,app,_=ui
    entered,release,tick=Event(),Event(),Event()
    original=adapter._copy
    def blocked(source,target,progress):
        progress(BackupProgress(BackupPhase.COPYING,5,10))
        entered.set()
        assert release.wait(10)
        original(source,target,progress)
    monkeypatch.setattr(adapter,'_copy',blocked)
    choose(monkeypatch,page.directory)
    qtbot.mouseClick(page.create_button,Qt.MouseButton.LeftButton)
    try:
        qtbot.waitUntil(entered.is_set,timeout=5000)
        qtbot.waitUntil(lambda:page.progress.value()==5,timeout=3000)
        assert page.progress.isVisible() and page.progress.maximum()==10
        assert not page.create_button.isEnabled()
        assert not window.close()
        assert window.isVisible() and db.access_status.opened
        QTimer.singleShot(0,tick.set)
        qtbot.waitUntil(tick.is_set,timeout=3000)
    finally:
        release.set()
    qtbot.waitUntil(lambda:not window.isVisible(),timeout=15000)
    assert not db.access_status.opened
    directories=[entry for entry in page.directory.iterdir() if entry.is_dir()]
    assert len(directories)==1
    inspect_backup(directories[0])


def test_success_waits_for_post_publication_inspect(ui,qtbot,monkeypatch):
    _,page,adapter,db,app,_=ui
    entered,release=Event(),Event()
    original=adapter.inspect
    def blocked(directory):
        entered.set()
        assert release.wait(10)
        return original(directory)
    monkeypatch.setattr(adapter,'inspect',blocked)
    choose(monkeypatch,page.directory)
    qtbot.mouseClick(page.create_button,Qt.MouseButton.LeftButton)
    try:
        qtbot.waitUntil(entered.is_set,timeout=5000)
        assert page.table.rowCount()==0
        assert 'создана и проверена' not in page.status.text()
        assert not page.create_button.isEnabled()
        assert app.storage_available  # Снимок уже получен, проверка ещё в worker.
    finally:
        release.set()
    qtbot.waitUntil(lambda:page.future is None,timeout=15000)
    assert page.table.rowCount()==1
    assert 'создана и проверена' in page.status.text()


def test_changing_directory_keeps_old_copy_and_updates_only_current_list(ui,qtbot,tmp_path,monkeypatch):
    _,page,_,db,app,settings=ui
    first_dir=tmp_path/'first'
    choose(monkeypatch,first_dir)
    create(qtbot,page)
    first=page.results[0]
    second_dir=tmp_path/'second'
    choose(monkeypatch,second_dir)
    create(qtbot,page)
    assert page.table.rowCount()==1
    assert page.results[0].directory.parent==second_dir
    assert inspect_backup(first.directory)==first
    assert settings.value(DIRECTORY_KEY)==str(second_dir)
    assert app.storage_available


def test_remembered_directory_reopens_and_invalid_copy_is_reported(ui,qtbot,monkeypatch):
    window,page,_,db,app,settings=ui
    target=page.directory
    choose(monkeypatch,target)
    create(qtbot,page)
    result=page.results[0]
    source_path=db.path
    window.close()
    qtbot.waitUntil(lambda:not window.isVisible(),timeout=15000)
    reopened_db=Database(source_path)
    reopened=ApplicationSession(reopened_db,backup_port=SQLiteBackup(reopened_db))
    assert reopened.open()
    other=MainWindow(application=reopened,settings=settings,start_chart=False)
    qtbot.addWidget(other)
    other.show()
    try:
        other.navigation.setCurrentRow(3)
        next_page=other.backup_page
        qtbot.waitUntil(lambda:next_page.future is None,timeout=15000)
        assert next_page.directory==target and next_page.table.rowCount()==1
        (result.directory/'metadata.json').write_bytes(b'corrupted synthetic metadata')
        qtbot.mouseClick(next_page.refresh_button,Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda:next_page.future is None,timeout=15000)
        assert next_page.table.rowCount()==0
        assert next_page.error.isVisible() and 'пакеты: 1' in next_page.error.text()
        assert reopened.storage_available
    finally:
        reopened.shutdown_backups()
        other.close()
        qtbot.waitUntil(lambda:not other.isVisible(),timeout=15000)


def test_unavailable_directory_error_does_not_switch_path_or_block_database(ui,qtbot,monkeypatch):
    _,page,adapter,db,app,settings=ui
    choose(monkeypatch,page.directory)
    create(qtbot,page)
    result=page.results[0]
    original=adapter.scan
    def fail(directory):
        raise OSError('synthetic disconnected drive')
    monkeypatch.setattr(adapter,'scan',fail)
    qtbot.mouseClick(page.refresh_button,Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda:page.future is None,timeout=10000)
    assert page.error.isVisible() and 'каталогу' in page.error.text()
    assert page.table.item(0,2).text()=='Проверка не обновлена'
    assert settings.value(DIRECTORY_KEY)==str(page.directory)
    assert app.storage_available
    monkeypatch.setattr(adapter,'scan',original)
    qtbot.mouseClick(page.refresh_button,Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda:page.future is None,timeout=10000)
    assert not page.error.isVisible() and page.results==(result,)
