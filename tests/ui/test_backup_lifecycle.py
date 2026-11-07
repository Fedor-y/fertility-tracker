"""Worker копирования не блокирует Qt; штатный close ждёт всю операцию."""
from threading import Event

from PySide6.QtCore import QSettings, QTimer

from healthtracker.application.backups import BackupRequest
from healthtracker.application.session import ApplicationSession
from healthtracker.infrastructure.sqlite.backup import SQLiteBackup, inspect_backup
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.presentation.main_window import MainWindow


def test_close_waits_for_snapshot_without_blocking_gui(qtbot,tmp_path,monkeypatch):
    db=Database(tmp_path/'data/source.sqlite3')
    adapter=SQLiteBackup(db)
    app=ApplicationSession(db,backup_port=adapter)
    assert app.open()
    window=MainWindow(application=app,settings=QSettings(str(tmp_path/'window.ini'),QSettings.Format.IniFormat),start_chart=False)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda:window._preferences_ready,timeout=10000)
    entered,release,tick=Event(),Event(),Event()
    original=adapter._copy
    def copy(source,target,progress):
        entered.set()
        assert release.wait(10)
        original(source,target,progress)
    monkeypatch.setattr(adapter,'_copy',copy)
    task=app.backups.create(BackupRequest(tmp_path/'backups'))
    try:
        qtbot.waitUntil(entered.is_set,timeout=5000)
        assert not window.close()
        assert window.isVisible()
        assert db.access_status.opened
        QTimer.singleShot(0,tick.set)
        qtbot.waitUntil(tick.is_set,timeout=3000)
        release.set()
        qtbot.waitUntil(lambda:not window.isVisible(),timeout=15000)
        assert task.done()
        result=task.result()
        assert inspect_backup(result.directory)==result
        assert not db.access_status.opened
    finally:
        release.set()
        app.shutdown_backups()
        window.close()
