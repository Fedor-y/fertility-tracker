"""Связывание Application/SQLite и окна. Миграционная защита не обходится."""

import argparse
import json
import sys

from PySide6.QtCore import QSettings, QTimer, qVersion
from PySide6.QtWidgets import QApplication

from healthtracker.presentation.main_window import MainWindow
from healthtracker.application.session import ApplicationSession
from healthtracker.infrastructure.sqlite.database import Database, default_database_path
from healthtracker.infrastructure.sqlite.backup import SQLiteBackup
from healthtracker.infrastructure.sqlite.restore import SQLiteRestore


def main() -> int:
    parser = argparse.ArgumentParser(description="HealthTracker")
    parser.add_argument(
        "--smoke-test", action="store_true",
        help="Проверить локальный график и WebChannel, затем закрыть окно",
    )
    args = parser.parse_args()
    app = QApplication([sys.argv[0]])
    app.setApplicationName("HealthTracker")
    app.setOrganizationName("HealthTracker")
    database = Database(default_database_path())
    application = ApplicationSession(database, backup_port=SQLiteBackup(database), restore_port=SQLiteRestore(database))
    application.open()
    # Самопроверка не меняет интерфейсные предпочтения обычного запуска.
    settings = None if args.smoke_test else QSettings()
    try:
        window = MainWindow(application=application, settings=settings)
    except BaseException:
        application.close()
        raise
    timer = QTimer()
    timer.setSingleShot(True)

    if args.smoke_test:
        def success() -> None:
            if not application.storage_available:
                failure()
                return
            timer.stop()
            print(json.dumps({
                "status": "ok", "qt": qVersion(),
                "echarts": window.chart.bridge.echarts_version,
                "webchannel": "python-js-python", "observations": 0,
            }), flush=True)
            app.exit(0)

        def failure() -> None:
            timer.stop()
            print("Самопроверка: хранилище, локальный график или WebChannel недоступен.",
                  file=sys.stderr, flush=True)
            app.exit(1)

        window.chart.bridge.ready.connect(success)
        window.chart.failed.connect(failure)
        timer.timeout.connect(failure)
        timer.start(20000)

    try:
        window.show()
        result = app.exec()
        window.close()
        return result
    finally:
        # В том числе исключение из event loop: сначала завершить читателей,
        # затем закрывать хранилище. Обычный closeEvent ждёт их без блокировки UI.
        controller = getattr(window, "chart_controller", None)
        if controller is not None:
            controller.shutdown()
        window.analytics_page.shutdown()
        application.shutdown_backups()
        application.close()
