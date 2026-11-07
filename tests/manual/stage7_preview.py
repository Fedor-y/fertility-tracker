"""Визуальный осмотр на искусственных данных; before/after, Wayland 1/1.5/2.

.venv/bin/python tests/manual/stage7_preview.py --phase before
Данные и QSettings только во временном каталоге. Изображения — /tmp/healthtracker-stage7.
"""
import argparse
from datetime import UTC, timedelta
import os
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory

from PySide6.QtCore import QDate, QPoint, QSettings, QTimer, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QScrollArea
from PySide6.QtTest import QTest

from healthtracker.application.backups import BackupRequest
from healthtracker.application.session import ApplicationSession
from healthtracker.domain.chart_preferences import ChartPreferences
from healthtracker.domain.charts import SeriesKind
from healthtracker.domain.periods import QuickPeriod
from healthtracker.infrastructure.sqlite.backup import SQLiteBackup
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.infrastructure.sqlite.restore import SQLiteRestore
from healthtracker.presentation.main_window import MainWindow

helper = runpy.run_path(str(Path(__file__).resolve().parents[1]/'performance/analytics_load.py'))
spin, javascript, now = helper['spin'], helper['javascript'], helper['NOW']
parser=argparse.ArgumentParser()
parser.add_argument('--phase',choices=('before','after'),required=True)
args=parser.parse_args()
qt=QApplication([])
qt.setQuitOnLastWindowClosed(False)
assert qt.platformName()=='wayland'
scale=os.environ.get('QT_SCALE_FACTOR','1')
output=Path('/tmp/healthtracker-stage7')/args.phase/scale
output.mkdir(parents=True,exist_ok=True)


def capture(widget,name):
    # Небольшая выдержка только для кадра композитора после WebEngine setOption.
    # Согласованность запросов выше проверена по delivery_id, не по задержке.
    QTest.qWait(180)
    assert widget.grab().save(str(output/(name+'.png')))


def rendered(chart):
    return (chart.bridge.pending is not None and
            javascript(chart.page(), 'window.healthtrackerChannel ? window.healthtrackerChannel.rendering().rendered : null')
            == chart.bridge.pending.delivery_id)


with TemporaryDirectory(prefix='healthtracker-stage7-') as directory:
    root=Path(directory)
    db=Database(root/'synthetic.sqlite3',clock=lambda:now)
    app=ApplicationSession(db,backup_port=SQLiteBackup(db),restore_port=SQLiteRestore(db))
    assert app.open()
    helper['populate'](db,14)
    app.chart_preferences.save(ChartPreferences(visible_series=tuple(SeriesKind)))
    window=MainWindow(app,QSettings(str(root/'window.ini'),QSettings.Format.IniFormat),start_chart=False)
    window.chart_now=lambda:now
    window.chart_controller.zone_provider=lambda:UTC
    window.show()
    spin(lambda:window._preferences_ready and window.chart.bridge.is_ready)
    window.start_chart=True
    window.chart_controls.period.setCurrentIndex(window.chart_controls.period.findData(QuickPeriod.TEN_DAYS))
    window._request_controls()
    spin(lambda:window.chart.bridge.state=='confirmed' and window.chart_controller.requests.idle)
    spin(lambda:rendered(window.chart))
    window.navigation.setCurrentRow(0)
    assert window.pages.currentIndex()==0
    capture(window,'overview')
    if args.phase=='after':
        overview_scroll=window.pages.widget(0)
        overview_scroll.ensureWidgetVisible(window.chart)
        capture(window,'overview-chart')
        overview_scroll.verticalScrollBar().setValue(0)
    page=window.analytics_page
    page.controls.period.setCurrentIndex(page.controls.period.findData('custom'))
    page.controls.start.setDate(QDate((now-timedelta(days=14)).date()))
    page.controls.end.setDate(QDate((now-timedelta(days=1)).date()))
    window.navigation.setCurrentRow(1)
    spin(lambda:page.chart is not None and page.chart.bridge.state=='confirmed' and page.sections is not None)
    spin(lambda:rendered(page.chart))
    page.scroll.verticalScrollBar().setValue(0)
    capture(window,'analytics')
    if args.phase=='after':
        page.scroll.ensureWidgetVisible(page.sections.cards)
        capture(window,'analytics-cards')
    page.sections.tabs.setCurrentIndex(2)
    page.scroll.ensureWidgetVisible(page.sections.tabs)
    capture(window,'analytics-factors')
    if args.phase=='after':
        page.scroll.verticalScrollBar().setValue(page.chart.y()+450)
        capture(window,'analytics-sleep-chart')
        page.scroll.verticalScrollBar().setValue(page.chart.y()+820)
        capture(window,'analytics-gym-chart')
    window.navigation.setCurrentRow(2)
    window.diary.entry_date.setDate(QDate((now-timedelta(days=1)).date()))
    capture(window,'diary')
    window.open_cognitive()
    form=window.active_dialog
    for answer in form.answers:
        answer.set_value(7)
    form.context.setPlainText('Искусственный пример: чтение и работа над проектом. Длинный текст остаётся доступным для редактирования.')
    form.finish_setup()
    capture(form,'form')
    form.reject()
    if args.phase=='after':
        for kind in ('physical','stress','mood','sleep','meal','gym'):
            getattr(window,'open_'+kind)()
            extra=window.active_dialog
            capture(extra,'form-'+kind)
            extra.reject()
    window.navigation.setCurrentRow(3)
    backup=window.backup_page
    spin(lambda:backup.future is None)
    capture(window,'settings')
    task=app.backups.create(BackupRequest(backup.directory))
    spin(task.done)
    task.result()
    backup.refresh()
    spin(lambda:backup.future is None)
    scroll=backup.findChild(QScrollArea)
    scroll.verticalScrollBar().setValue(0)
    capture(window,'backups')
    if args.phase=='after':
        scroll.ensureWidgetVisible(backup.restore_button)
        capture(window,'backups-actions')
    if args.phase=='after':
        def dismiss_confirmation():
            modal=qt.activeModalWidget()
            if modal is None:
                QTimer.singleShot(20,dismiss_confirmation)
                return
            capture(modal,'confirmation')
            modal.done(QMessageBox.StandardButton.No)
        QTimer.singleShot(0,dismiss_confirmation)
        backup.restore_button.click()  # Реальный диалог; замена отменяется.
    # Реальные календарь, фокус и небольшая область дополняют основные снимки.
    window.navigation.setCurrentRow(2)
    window.resize(900,600)
    capture(window,'diary-small')
    if args.phase=='after':
        field=window.diary.entry_date
        QTest.mouseClick(field,Qt.MouseButton.LeftButton,pos=QPoint(field.width()-8,field.height()//2))
        spin(lambda:field.calendarWidget().isVisible(),timeout=5000)
        capture(field.calendarWidget(),'calendar')
        field.calendarWidget().hide()
    window.close()
    spin(lambda:not window.isVisible())
    app.shutdown_backups()
    window.chart_controller.shutdown()
    window.analytics_page.shutdown()
    app.close()
print(f'Wayland {scale}: {args.phase}, снимки {output}',flush=True)
