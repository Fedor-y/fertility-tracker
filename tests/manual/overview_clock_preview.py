"""Часы Обзора: реальная съёмка Wayland на искусственной временной базе."""
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import timedelta
import os,runpy,subprocess,json
from PySide6.QtCore import QSettings,Qt,QDate,QSignalBlocker
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.application.session import ApplicationSession
from healthtracker.domain.analytics import AnalysisContext
from healthtracker.domain.periods import QuickPeriod
from healthtracker.presentation.main_window import MainWindow
h=runpy.run_path(str(Path(__file__).with_name('smooth_chart_preview.py')))
helpers=runpy.run_path(str(Path(__file__).resolve().parents[1]/'performance/analytics_load.py'))
spin,js=helpers['spin'],helpers['javascript']
qt=QApplication([]);assert qt.platformName()=='wayland'
out=Path('/tmp/healthtracker-overview-clock')/os.environ.get('QT_SCALE_FACTOR','1');out.mkdir(parents=True,exist_ok=True)
with TemporaryDirectory(prefix='ht-gear-') as d:
 root=Path(d);db=Database(root/'synthetic.sqlite3',clock=lambda:h['NOW']);app=ApplicationSession(db);assert app.open();h['populate'](app)
 w=MainWindow(app,QSettings(str(root/'window.ini'),QSettings.Format.IniFormat),start_chart=False)
 w.setWindowTitle('HealthTracker — тест панели графика');w.chart_now=lambda:h['NOW'];w.chart_controller.zone_provider=lambda:h['UTC'];w.show()
 spin(lambda:w._preferences_ready and w.chart.bridge.is_ready)
 p=w.chart_controls;popup=w.chart_settings_popup
 with QSignalBlocker(p):
  p.period.setCurrentIndex(p.period.findData('custom'));p.start.setDate(QDate(h['DAY']));p.end.setDate(QDate(h['DAY']+timedelta(days=2)));p.compact=False;p.custom.show()
  query=p.query(AnalysisContext(h['NOW'],h['UTC']))
 w.chart_controller.request(query)
 spin(lambda:w.chart.bridge.state=='confirmed' and w.chart_controller.requests.idle)
 spin(lambda:js(w.chart.page(),'window.healthtrackerChannel.rendering().rendered')==w.chart.bridge.pending.delivery_id)
 def center_check():
  a=w.overview_clock.mapTo(w,w.overview_clock.rect().center()).x()
  b=w.pages.mapTo(w,w.pages.rect().center()).x()
  assert abs(a-b)<=2,(a,b)
 w.toggle_fullscreen();spin(w.isFullScreen);QTest.qWait(800);center_check()
 assert w.isActiveWindow()
 subprocess.run(['spectacle','--background','--fullscreen','--nonotify','--output',str(out/'overview.png')],timeout=15,check=True,capture_output=True)
 w.sidebar_toggle.click();spin(lambda:w.sidebar.width()==56);QTest.qWait(400);center_check()
 subprocess.run(['spectacle','--background','--fullscreen','--nonotify','--output',str(out/'collapsed.png')],timeout=15,check=True,capture_output=True)
 w.leave_fullscreen();w.resize(680,600);QTest.qWait(800);center_check()
 subprocess.run(['spectacle','--background','--activewindow','--nonotify','--output',str(out/'narrow.png')],timeout=15,check=True,capture_output=True)
 print(w.overview_clock.date_label.text(),w.overview_clock.time_label.text(),out,flush=True)
 w.close();spin(lambda:not w.isVisible());w.chart_controller.shutdown();w.analytics_page.shutdown();app.close()
