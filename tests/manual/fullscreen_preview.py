"""Fullscreen KDE/Wayland: искусственная БД, геометрия поверхности и снимки."""
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import timedelta
import json,os,runpy,subprocess
from PySide6.QtCore import QSettings,Qt,QDate,QSignalBlocker
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.application.session import ApplicationSession
from healthtracker.application.charts import ChartQuery
from healthtracker.domain.analytics import AnalysisContext
from healthtracker.domain.periods import DateRange
from healthtracker.domain.charts import SeriesKind
from healthtracker.presentation.main_window import MainWindow
h=runpy.run_path(str(Path(__file__).with_name('smooth_chart_preview.py')))
helpers=runpy.run_path(str(Path(__file__).resolve().parents[1]/'performance/analytics_load.py'))
spin,js=helpers['spin'],helpers['javascript']
qt=QApplication([]);assert qt.platformName()=='wayland'
out=Path('/tmp/healthtracker-fullscreen')/os.environ.get('QT_SCALE_FACTOR','1');out.mkdir(parents=True,exist_ok=True)
with TemporaryDirectory(prefix='ht-fullscreen-') as d:
 root=Path(d);db=Database(root/'synthetic.sqlite3',clock=lambda:h['NOW']);app=ApplicationSession(db);assert app.open();h['populate'](app)
 w=MainWindow(app,QSettings(str(root/'window.ini'),QSettings.Format.IniFormat),start_chart=False)
 w.setWindowTitle('HealthTracker — fullscreen, искусственные данные')
 w.chart_now=lambda:h['NOW'];w.chart_controller.zone_provider=lambda:h['UTC'];w.show()
 spin(lambda:w._preferences_ready and w.chart.bridge.is_ready)
 panel=w.chart_controls
 with QSignalBlocker(panel):
  panel.period.setCurrentIndex(panel.period.findData('custom'));panel.start.setDate(QDate(h['DAY']));panel.end.setDate(QDate(h['DAY']+timedelta(days=2)));panel.compact=False
  query=panel.query(AnalysisContext(h['NOW'],h['UTC']));panel.custom.show()
 w.chart_controller.request(query)
 spin(lambda:w.chart.bridge.state=='confirmed' and w.chart_controller.requests.idle)
 spin(lambda:js(w.chart.page(),'window.healthtrackerChannel.rendering().rendered')==w.chart.bridge.pending.delivery_id)
 def snap(name):
  QTest.qWait(220);assert w.grab().save(str(out/(name+'.png')))
 snap('normal')
 js(w.chart.page(),'window.healthtrackerChannel.zoom(10,80)');snap('normal-zoom')
 w.fullscreen_button.click();spin(w.isFullScreen)
 spin(lambda:w.size()==w.screen().size())
 snap('fullscreen-expanded')
 metrics={'platform':qt.platformName(),'desktop':os.environ.get('XDG_CURRENT_DESKTOP'),'window':[w.width(),w.height()],'screen':[w.screen().size().width(),w.screen().size().height()]}
 margins=w.windowHandle().frameMargins();metrics['frame_margins']=[margins.left(),margins.top(),margins.right(),margins.bottom()]
 w.sidebar_toggle.click();spin(lambda:w.sidebar.width()==56);snap('fullscreen-collapsed')
 # Снимок только активного окна compositor: не захватывает другие окна/мониторы.
 if os.environ.get('HT_CAPTURE_COMPOSITOR')=='1':
  if w.isActiveWindow():
   try:
    metrics['spectacle_returncode']=subprocess.run(['spectacle','--background','--activewindow','--nonotify','--output',str(out/'compositor-fullscreen.png')],timeout=15,capture_output=True).returncode
   except subprocess.TimeoutExpired:metrics['spectacle_error']='timeout'
  else:metrics['spectacle_error']='test window not active; capture skipped'
 QTest.keyClick(w,Qt.Key.Key_Escape);spin(lambda:not w.isFullScreen());snap('restored-normal')
 w.showMaximized();spin(w.isMaximized);snap('maximized-before')
 QTest.keyClick(w,Qt.Key.Key_F11);spin(w.isFullScreen);snap('fullscreen-from-maximized')
 QTest.keyClick(w,Qt.Key.Key_F11);spin(lambda:w.isMaximized() and not w.isFullScreen());snap('restored-maximized')
 (out/'geometry.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2))
 w.close();spin(lambda:not w.isVisible());w.chart_controller.shutdown();w.analytics_page.shutdown();app.close()
print(out,flush=True)
