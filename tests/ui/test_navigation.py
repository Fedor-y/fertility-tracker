from datetime import UTC, datetime
import os
from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import QSettings, Qt

from healthtracker.application.errors import StorageBusy
from healthtracker.application.session import ApplicationSession
from healthtracker.domain.records import MoodRecord
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.presentation.main_window import MainWindow


def create_window(qtbot, tmp_path):
    database = Database(tmp_path / "data/database.sqlite3")
    application = ApplicationSession(database)
    assert application.open()
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    window = MainWindow(application=application, settings=settings)
    qtbot.addWidget(window)
    window.show()
    return window, database, application, settings


def test_four_sections_navigation_keyboard_and_pending_forms(qtbot, tmp_path):
    window, _, application, _ = create_window(qtbot, tmp_path)
    assert [window.navigation.item(i).text() for i in range(4)] == ["Обзор", "Аналитика", "Дневник", "Настройки"]
    assert window.pages.count() == 4
    window.navigation.setFocus()
    qtbot.keyClick(window.navigation, Qt.Key.Key_Down)
    assert window.pages.currentIndex() == 1
    for index in range(4):
        window.navigation.setCurrentRow(index)
        assert window.pages.currentIndex() == index
    assert window.cognitive_button.isEnabled()
    assert window.physical_button.isEnabled()
    assert [a.text() for a in window.add_menu.actions()[:6]] == ["Настроение", "Стресс", "Стресса нет", "Сон", "Питание", "Спортзал"]
    assert [action.isEnabled() for action in window.add_menu.actions()[:6]] == [True, True, True, True, True, True]
    assert not window.last_saved_action.isEnabled()
    assert application.storage_available
    qtbot.waitUntil(lambda: window.chart.bridge.is_ready, timeout=20000)
    qtbot.waitUntil(lambda: window.chart.bridge.state == "confirmed", timeout=20000)
    assert "Снимок проверен" in window.status.text()
    assert window.close()
    assert not application.storage_available


def test_geometry_uses_only_qsettings_and_records_survive_window_restart(qtbot, tmp_path):
    window, database, _, settings = create_window(qtbot, tmp_path)
    now = datetime.now(UTC)
    with database.write() as session:
        record_id = session.mood.create(MoodRecord(observed_at=now, score=0, created_at=now, updated_at=now))
    available = window.screen().availableGeometry()
    # Оставить место рамке/заголовку: restoreGeometry вправе ужать окно у края экрана.
    expected_width = min(1080, available.width() - 40)
    expected_height = min(720, available.height() - 80)
    window.resize(expected_width, expected_height)
    window.close()
    # Загрузка предпочтений может ещё выполняться: закрытие теперь
    # завершается через event loop, без ожидания SQLite в GUI.
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=15000)
    assert set(settings.allKeys()) == {"window/geometry", "window/maximized"}
    assert not settings.value("window/geometry").isEmpty()
    reopened_database = Database(database.path)
    restarted = ApplicationSession(reopened_database)
    assert restarted.open()
    reopened = MainWindow(application=restarted, settings=settings)
    qtbot.addWidget(reopened)
    reopened.show()
    assert reopened.width() == expected_width
    assert reopened.height() == expected_height
    with reopened_database.read_snapshot() as session:
        assert session.mood.get(record_id).value.score == 0
        assert session.settings.get("visible_series") is None
    reopened.close()


def test_unavailable_storage_is_visible_and_actions_disabled(qtbot, tmp_path):
    path = tmp_path / "data.sqlite3"
    with Database(path):
        application = ApplicationSession(Database(path))
        assert not application.open()
        window = MainWindow(application=application)
        qtbot.addWidget(window)
        window.show()
        assert "другим экземпляром" in window.storage_status.text()
        assert not window.add_button.isEnabled()
        window.navigation.setCurrentRow(2)
        assert window.pages.currentIndex() == 2
        window.close()


def test_close_failure_keeps_window_open_and_reports_error(qtbot):
    from healthtracker.application.storage import AccessState, AccessStatus
    class BusyStorage:
        access_status = AccessStatus(AccessState.NORMAL, True)
        blocked = True
        def initialize(self):
            pass
        def read_snapshot(self):
            raise StorageBusy("injected read failure")
        def close(self):
            if self.blocked:
                raise StorageBusy("injected")
            self.access_status = AccessStatus(AccessState.NORMAL, False)
    storage = BusyStorage()
    application = ApplicationSession(storage)
    application.open()
    window = MainWindow(application=application)
    qtbot.addWidget(window)
    window.show()
    try:
        qtbot.waitUntil(lambda: window._preferences_ready)
        assert not window.close()
        assert window.isVisible()
        assert "отменено" in window.storage_status.text()
    finally:
        storage.blocked = False
        window.close()


def test_bootstrap_smoke_creates_only_test_xdg_database_and_reopens(qapp, tmp_path):
    env = {**os.environ, "XDG_DATA_HOME": str(tmp_path / "data"),
           "XDG_CONFIG_HOME": str(tmp_path / "config")}
    for _ in range(2):
        result = subprocess.run([sys.executable, "-m", "healthtracker", "--smoke-test"],
                                env=env, capture_output=True, text=True, timeout=35)
        assert result.returncode == 0, result.stderr
        assert '"status": "ok"' in result.stdout
    assert (Path(env["XDG_DATA_HOME"]) / "healthtracker/healthtracker.sqlite3").exists()
    assert not Path(env["XDG_CONFIG_HOME"]).exists()  # smoke не сохраняет геометрию.


def test_access_state_reaches_presentation_without_sql(qtbot, tmp_path):
    from healthtracker.application.errors import StorageRecoveryRequired
    import pytest
    window, database, application, _ = create_window(qtbot, tmp_path)
    qtbot.waitUntil(lambda: window._preferences_ready, timeout=10000)
    # Первоначальные читатели/предпочтения завершаются до эксклюзивной операции.
    qtbot.waitUntil(lambda: database.access_status.active_sessions == 0, timeout=10000)
    with database.exclusive() as access:
        window._check_chart_context()
        assert not window.cognitive_button.isEnabled()
        assert 'приостановлена' in window.storage_status.text()
        access.confirm_safe()
    window._check_chart_context()
    assert window.cognitive_button.isEnabled()
    with pytest.raises(StorageRecoveryRequired):
        with database.write():
            raise StorageRecoveryRequired('injected')
    qtbot.waitUntil(lambda: not window.physical_button.isEnabled(), timeout=5000)
    assert not application.storage_available
    assert not window.physical_button.isEnabled()
    assert 'проверка' in window.storage_status.text()
    database.verify_access()
    window._check_chart_context()
    assert window.physical_button.isEnabled()
    window.close()
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=15000)
