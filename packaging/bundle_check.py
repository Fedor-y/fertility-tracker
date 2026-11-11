"""Приёмка onedir на искусственных данных; запускается только явным --check-bundle.

Не импортирует pytest и тесты проекта. Обычный запуск этот модуль не выполняет.
"""
import json
import os
from pathlib import Path
import sys
import subprocess
from tempfile import TemporaryDirectory
from datetime import UTC, datetime, timedelta


def main():
    if not getattr(sys, 'frozen', False):
        raise RuntimeError('Эта проверка предназначена для собранной onedir')
    # Дочерний процесс проверяет повторный запуск на том же искусственном состоянии.
    reopening = os.environ.get('HEALTHTRACKER_CHECK_REOPEN')
    if reopening:
        root = Path(reopening)
        assert root.parent == Path('/tmp') and root.name.startswith('healthtracker-bundle-check-')
        assert (root / '.synthetic-check').is_file()
        for name, child in (('XDG_DATA_HOME', 'data'), ('XDG_CONFIG_HOME', 'config'), ('XDG_CACHE_HOME', 'cache')):
            os.environ[name] = str(root / child)
        return check(root, reopen_only=True)
    # До QApplication и расчёта любых пользовательских путей.
    with TemporaryDirectory(prefix='healthtracker-bundle-check-', dir='/tmp') as directory:
        root = Path(directory)
        (root / '.synthetic-check').touch()
        os.environ['XDG_DATA_HOME'] = str(root / 'data')
        os.environ['XDG_CONFIG_HOME'] = str(root / 'config')
        os.environ['XDG_CACHE_HOME'] = str(root / 'cache')
        return check(root)


def check(root, *, reopen_only=False):
    from PySide6.QtCore import QDate, QEventLoop, QLibraryInfo, QSettings, QTimer
    from PySide6.QtWidgets import QApplication, QDialogButtonBox, QFileDialog, QMessageBox
    from healthtracker.application.session import ApplicationSession
    from healthtracker.domain.periods import QuickPeriod
    from healthtracker.domain.charts import SeriesKind
    from healthtracker.domain.chart_preferences import ChartPreferences
    from healthtracker.domain.answers import CognitiveAnswer
    from healthtracker.domain.cognitive import CognitiveAssessment
    from healthtracker.domain.intervals import CognitiveInterval, SleepInterval
    from healthtracker.domain.measurement import CognitiveMeasurement
    from healthtracker.domain.records import PhysicalRecord, StressRecord, MoodRecord, SleepRecord, MealRecord, MealItem, GymRecord
    from healthtracker.domain.catalogs import SymptomStatus, MealCategory
    from healthtracker.infrastructure.sqlite.database import Database, default_database_path
    from healthtracker.infrastructure.sqlite.backup import SQLiteBackup, inspect_backup
    from healthtracker.infrastructure.sqlite.restore import SQLiteRestore
    from healthtracker.presentation.chart import CHART_ROOT
    from healthtracker.presentation.main_window import MainWindow
    from healthtracker.presentation.theme import CHART_ASSETS

    qt = QApplication([])
    qt.setQuitOnLastWindowClosed(False)
    qt.setApplicationName('HealthTracker')
    qt.setOrganizationName('HealthTracker')
    assert qt.platformName() == 'wayland', qt.platformName()
    assert not os.environ.get('QTWEBENGINE_DISABLE_SANDBOX')
    assert '--no-sandbox' not in os.environ.get('QTWEBENGINE_CHROMIUM_FLAGS', '')
    bundle = Path(sys._MEIPASS).resolve()
    assert CHART_ROOT.is_relative_to(bundle)
    assert CHART_ASSETS.is_relative_to(bundle)
    for name in ('index.html', 'chart.css', 'chart.js', 'chart_render.js', 'ui-check.svg', 'ui-down.svg', 'ui-up.svg', 'vendor/echarts.min.js'):
        assert (CHART_ROOT / name).is_file(), name
    assert not any('.venv/' in line for line in Path('/proc/self/maps').read_text().splitlines())

    def spin(predicate, timeout=25000):
        if predicate():
            return
        loop, poll, deadline = QEventLoop(), QTimer(), QTimer()
        deadline.setSingleShot(True)
        poll.timeout.connect(lambda: loop.quit() if predicate() else None)
        deadline.timeout.connect(loop.quit)
        poll.start(10)
        deadline.start(timeout)
        loop.exec()
        poll.stop()
        deadline.stop()
        assert predicate(), 'Превышено время ожидания приёмки onedir'

    def js(chart, code):
        values = []
        chart.page().runJavaScript(code, values.append)
        spin(lambda: bool(values))
        return values[0]

    def rendered(chart):
        return chart.bridge.pending is not None and js(chart,
            'window.healthtrackerChannel ? window.healthtrackerChannel.rendering().rendered : null') == chart.bridge.pending.delivery_id

    def open_storage():
        db = Database(default_database_path())
        app = ApplicationSession(db, backup_port=SQLiteBackup(db), restore_port=SQLiteRestore(db))
        assert app.open()
        return db, app

    def close(window, app):
        window.close()
        spin(lambda: not window.isVisible())
        app.shutdown_backups()
        window.chart_controller.shutdown()
        window.analytics_page.shutdown()
        app.close()

    if reopen_only:
        db, app = open_storage()
        with db.read_snapshot() as session:
            counts = tuple(len(getattr(session, name).all()) for name in ('cognitive','physical','stress','mood','sleep','meals','gym'))
            assert counts == (15,) * 7
            assert session.settings.get('compact_mode') is False
        settings = QSettings()
        assert settings.value('backup/directory') == str(root / 'chosen-backups')
        assert settings.contains('window/geometry')
        window = MainWindow(app, settings)
        window.show()
        spin(lambda: window._preferences_ready and window.chart.bridge.state == 'confirmed')
        spin(lambda: rendered(window.chart))
        assert window.chart_controls.preferences().compact_mode is False
        window.navigation.setCurrentRow(3)
        spin(lambda: window.backup_page.future is None)
        assert len(window.backup_page.results) == 2
        close(window, app)
        print(json.dumps(dict(status='ok', fresh_process=True, restored_counts=counts, settings=True)), flush=True)
        return 0

    now = datetime.now(UTC) - timedelta(minutes=5)
    db, app = open_storage()
    assert db.path.is_relative_to(root) and not db.path.is_relative_to(bundle)
    meta = dict(created_at=now, updated_at=now)
    assessment = CognitiveAssessment(*(CognitiveAnswer.numeric(6) for _ in range(3)))
    with db.write() as s:
        s.settings.set('compact_mode', False)
        for offset in range(1, 15):
            day = now - timedelta(days=offset)
            s.cognitive.create(CognitiveMeasurement(assessment, CognitiveInterval(day, now=now), now, now))
            s.physical.create(PhysicalRecord(observed_at=day, score=7, symptom_status=SymptomStatus.UNKNOWN, **meta))
            s.stress.create(StressRecord(observed_at=day, score=0, **meta))
            s.mood.create(MoodRecord(observed_at=day, score=5, **meta))
            s.sleep.create(SleepRecord(interval=SleepInterval(day-timedelta(hours=8), day, now=now), **meta))
            s.meals.create(MealRecord(entry_date=day.date(), category=MealCategory.LUNCH, items=(MealItem(name='Искусственная запись', **meta),), **meta))
            s.gym.create(GymRecord(entry_date=day.date(), attended=False, **meta))
    app.chart_preferences.save(ChartPreferences(visible_series=tuple(SeriesKind), compact_mode=False))
    python_maps = [line.split(None, 5)[5] for line in Path('/proc/self/maps').read_text().splitlines() if 'libpython' in line]
    assert python_maps and all(Path(p).is_relative_to(bundle) for p in python_maps)
    settings = QSettings()
    assert Path(settings.fileName()).is_relative_to(root)
    window = MainWindow(app, settings)
    window.show()
    spin(lambda: window._preferences_ready)
    window.chart_controls.period.setCurrentIndex(window.chart_controls.period.findData(QuickPeriod.TEN_DAYS))
    spin(lambda: window.chart.bridge.state == 'confirmed' and window.chart_controller.requests.idle)
    spin(lambda: rendered(window.chart))
    assert js(window.chart, 'window.echarts.version') == '6.0.0'
    assert 'QCheckBox:focus' in window.styleSheet()
    evidence = os.environ.get('HEALTHTRACKER_CHECK_SCREENSHOTS')
    def capture(name):
        if evidence:
            output = Path(evidence)
            output.mkdir(parents=True, exist_ok=True)
            ready = []
            QTimer.singleShot(200, lambda: ready.append(True))
            spin(lambda: bool(ready))
            assert window.grab().save(str(output / (name + '.png')))
    capture('frozen-overview')
    assert not window.chart_controls.isVisible()
    window.chart_settings_button.click()
    assert window.chart_settings_popup.isVisible() and window.chart_controls.isVisible()
    assert not window.chart_settings_button.icon().isNull()
    capture('frozen-chart-settings')
    window.chart_settings_button.click()
    assert not window.chart_settings_popup.isVisible()
    renderer_sandbox = []
    children = [os.getpid()]
    while children:
        pid = children.pop()
        try:
            children.extend(map(int, Path(f'/proc/{pid}/task/{pid}/children').read_text().split()))
            command = Path(f'/proc/{pid}/cmdline').read_bytes()
            if b'--type=renderer' in command:
                assert b'--no-sandbox' not in command
                status = Path(f'/proc/{pid}/status').read_text()
                seccomp = next(line.split(':')[1].strip() for line in status.splitlines() if line.startswith('Seccomp:'))
                renderer_sandbox.append(seccomp)
        except (FileNotFoundError, ProcessLookupError):
            continue
    assert renderer_sandbox and all(value == '2' for value in renderer_sandbox), renderer_sandbox

    for kind in ('cognitive', 'physical', 'stress', 'mood', 'sleep', 'meal', 'gym'):
        getattr(window, 'open_' + kind)()
        form = window.active_dialog
        assert form.isVisible()
        if kind == 'cognitive':
            for field in form.answers:
                field.set_value(7)
            form.moment.set_moment(now)
        elif kind in ('physical', 'stress', 'mood'):
            form.score.set_value(0 if kind == 'stress' else 7)
            form.moment.set_moment(now)
        elif kind == 'sleep':
            form.start.set_moment(now-timedelta(hours=8))
            form.end.set_moment(now)
        elif kind == 'meal':
            form.category.setCurrentIndex(form.category.findData(MealCategory.LUNCH.value))
            form.items[0].name.setText('Искусственная запись из формы')
        else:
            form.set_date(now.astimezone().date())
            form.attended.setCurrentIndex(form.attended.findData(False))
        form.buttons.button(QDialogButtonBox.StandardButton.Save).click()
        assert form._committed, (kind, form.error.text())
        assert not form.isVisible()

    page = window.analytics_page
    page.controls.period.setCurrentIndex(page.controls.period.findData(QuickPeriod.TEN_DAYS))
    window.navigation.setCurrentRow(1)
    spin(lambda: page.chart is not None and page.sections is not None and page.chart.bridge.state == 'confirmed')
    spin(lambda: rendered(page.chart))
    assert page.sections.summary_table.model().rowCount() == 6
    assert page.sections.summary_table.model().rows[0][1] not in ('—', '')
    capture('frozen-analytics')
    window.navigation.setCurrentRow(2)
    window.diary.entry_date.setDate(QDate(now.astimezone().date()))
    assert window.diary.records.topLevelItemCount() > 0
    capture('frozen-diary')
    window.navigation.setCurrentRow(3)
    backup = window.backup_page
    spin(lambda: backup.future is None)
    target = root / 'chosen-backups'
    target.mkdir(mode=0o700)
    original_dialog = QFileDialog.getExistingDirectory
    QFileDialog.getExistingDirectory = lambda *args: str(target)
    try:
        backup.create_button.click()
    finally:
        QFileDialog.getExistingDirectory = original_dialog
    spin(lambda: backup.future is None)
    assert len(backup.results) == 1, backup.error.text()
    selected = inspect_backup(backup.results[0].directory)
    assert backup.table.item(0, 2).text() == 'Проверена'
    capture('frozen-backups')
    with db.read_snapshot() as s:
        counts = tuple(len(getattr(s, name).all()) for name in ('cognitive','physical','stress','mood','sleep','meals','gym'))
    assert counts == (15,) * 7, counts
    with db.write() as s:
        s.mood.create(MoodRecord(observed_at=now, score=9, **meta))
        s.settings.set('compact_mode', True)

    # Настоящее QMessageBox; подтверждаем только искусственную временную базу.
    def confirm():
        modal = qt.activeModalWidget()
        if not isinstance(modal, QMessageBox):
            QTimer.singleShot(10, confirm)
        else:
            modal.button(QMessageBox.StandardButton.Yes).click()
    QTimer.singleShot(0, confirm)
    backup.restore_button.click()
    spin(lambda: app.restart_required and backup.future is None)
    assert 'Данные восстановлены и проверены' in backup.status.text(), backup.error.text()
    assert len(list(target.iterdir())) == 2  # Выбранная и защитная PRE_RESTORE.
    assert inspect_backup(selected.directory).metadata == selected.metadata
    backup.restart_button.click()
    spin(lambda: not window.isVisible())
    close(window, app)

    # Настоящий повторный запуск бинарника, а не только новое окно в этом процессе.
    restarted = subprocess.run([sys.executable, '--check-bundle'], capture_output=True, text=True,
        env={**os.environ, 'HEALTHTRACKER_CHECK_REOPEN': str(root), 'PYINSTALLER_RESET_ENVIRONMENT': '1'}, timeout=60)
    assert restarted.returncode == 0, (restarted.stdout, restarted.stderr)
    fresh = json.loads(restarted.stdout.strip().splitlines()[-1])
    assert fresh['fresh_process'] and fresh['settings']
    restored = fresh['restored_counts']
    print(json.dumps(dict(status='ok', frozen=True, platform=qt.platformName(),
        bundled_python=sys.version.split()[0], qt_plugins=QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath),
        chart_resources=str(CHART_ROOT), forms_saved=7, restored_counts=restored,
        echarts='6.0.0', backup_restore=True, reopen_settings=True,
        database_outside_bundle=True, loaded_from_venv=False,
        renderer_seccomp=renderer_sandbox, python_library=python_maps[0]), ensure_ascii=False), flush=True)
    return 0
