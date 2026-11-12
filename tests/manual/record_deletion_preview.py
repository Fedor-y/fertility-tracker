"""Проверка кнопки и настоящего подтверждения на искусственной записи.

Запускать через virtual_wayland.py: окна останутся на отдельном виртуальном экране.
"""
from datetime import UTC,datetime
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
from PySide6.QtCore import QDate,QSettings,QTimer
from PySide6.QtWidgets import QApplication,QMessageBox
from healthtracker.application.errors import RecordNotFound
from healthtracker.application.session import ApplicationSession
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.presentation.main_window import MainWindow

helpers=runpy.run_path(str(Path(__file__).resolve().parents[1]/'performance/analytics_load.py'))
spin=helpers['spin']
qt=QApplication([]);assert qt.platformName()=='wayland'
out=Path('/tmp/healthtracker-record-deletion');out.mkdir(exist_ok=True)
with TemporaryDirectory(prefix='healthtracker-delete-preview-') as directory:
    root=Path(directory)
    db=Database(root/'synthetic.sqlite3');app=ApplicationSession(db);assert app.open()
    moment=datetime(2026,11,12,12,tzinfo=UTC)
    record=app.observations.save_mood(score=6,observed_at=moment)
    window=MainWindow(app,QSettings(str(root/'window.ini'),QSettings.Format.IniFormat),start_chart=False)
    window.show();spin(lambda:window._preferences_ready)
    window.navigation.setCurrentRow(2);window.diary.entry_date.setDate(QDate(moment.date()))
    window._diary_open('mood',record);form=window.active_dialog
    spin(lambda:form.delete_button.isVisible() and form.height()<600)
    assert form.grab().save(str(out/'edit-record.png'))
    def cancel():
        box=QApplication.activeModalWidget()
        assert isinstance(box,QMessageBox)
        assert box.standardButton(box.defaultButton())==QMessageBox.StandardButton.No
        assert box.grab().save(str(out/'confirmation.png'))
        box.button(QMessageBox.StandardButton.No).click()
    QTimer.singleShot(0,cancel);form.delete_button.click()
    assert form.isVisible() and app.observations.get('mood',record).id==record
    def confirm():
        box=QApplication.activeModalWidget();assert isinstance(box,QMessageBox)
        box.button(QMessageBox.StandardButton.Yes).click()
    QTimer.singleShot(0,confirm);form.delete_button.click()
    try:app.observations.get('mood',record)
    except RecordNotFound:pass
    else:raise AssertionError('Удаление не выполнено')
    assert window.diary.grab().save(str(out/'deleted.png'))
    window.close();spin(lambda:not window.isVisible())
    window.chart_controller.shutdown();window.analytics_page.shutdown();app.close()
print(out,flush=True)
