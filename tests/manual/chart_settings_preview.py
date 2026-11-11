"""Шестерёнка и вложенные popup: только искусственная временная база."""
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
out=Path('/tmp/healthtracker-chart-settings/after')/os.environ.get('QT_SCALE_FACTOR','1');out.mkdir(parents=True,exist_ok=True)
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
 def snap(name,widget=w):
  QTest.qWait(180);assert widget.grab().save(str(out/(name+'.png')))
 def opened():
  if not popup.isVisible():w.chart_settings_button.click()
  spin(popup.isVisible)
 snap('closed');opened();snap('custom-dates',popup)
 p.period.setCurrentIndex(p.period.findData(QuickPeriod.SEVEN_DAYS));snap('opened',popup)
 for name,combo in (('period',p.period),('mode',p.mode)):
  combo.showPopup();spin(combo.view().isVisible);snap(name+'-popup',combo.view().window());combo.hidePopup();assert popup.isVisible()
 p.period.setCurrentIndex(p.period.findData('custom'));snap('custom-again',popup)
 p.details_button.click();snap('layers',popup)
 bounds=popup.screen().availableGeometry();assert w.rect().contains(popup.geometry()), (bounds,popup.geometry(),popup.minimumSize(),popup.sizeHint())
 popup.hide();w.sidebar_toggle.click();spin(lambda:w.sidebar.width()==56);opened();snap('collapsed-panel',popup);popup.hide();snap('collapsed-main')
 w.resize(680,650);opened();snap('narrow-panel',popup);popup.hide();snap('narrow-main')
 w.toggle_fullscreen();spin(w.isFullScreen);snap('fullscreen-main');opened();snap('fullscreen-panel',popup)
 if len(qt.screens())==1 and w.isActiveWindow():
  try:subprocess.run(['spectacle','--background','--fullscreen','--nonotify','--output',str(out/'fullscreen-compositor.png')],timeout=15,capture_output=True)
  except subprocess.TimeoutExpired:pass
 (out/'geometry.json').write_text(json.dumps({'panel':[popup.x(),popup.y(),popup.width(),popup.height()],'screen':[popup.screen().geometry().width(),popup.screen().geometry().height()]}))
 popup.hide();w.leave_fullscreen();w.close();spin(lambda:not w.isVisible());w.chart_controller.shutdown();w.analytics_page.shutdown();app.close()
print(out,flush=True)
