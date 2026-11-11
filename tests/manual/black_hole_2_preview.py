"""Реальные popup и график в Wayland; только временные искусственные данные."""
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import timedelta
from zoneinfo import ZoneInfo
import os,runpy,sys
from PySide6.QtCore import QSettings,Qt,QSignalBlocker
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.application.session import ApplicationSession
from healthtracker.presentation.main_window import MainWindow
from healthtracker.application.charts import ChartQuery
from healthtracker.domain.analytics import AnalysisContext
from healthtracker.domain.periods import DateRange
from healthtracker.domain.charts import SeriesKind,ChartMode
from healthtracker.presentation.chart_controls import MODES
h=runpy.run_path(str(Path(__file__).with_name('smooth_chart_preview.py')))
helpers=runpy.run_path(str(Path(__file__).resolve().parents[1]/'performance/analytics_load.py'))
spin,js=helpers['spin'],helpers['javascript']
qt=QApplication([]);assert qt.platformName()=='wayland'
out=Path('/tmp/healthtracker-black-hole-2')/sys.argv[1]/os.environ.get('QT_SCALE_FACTOR','1');out.mkdir(parents=True,exist_ok=True)
with TemporaryDirectory(prefix='ht-bh2-') as d:
    db=Database(Path(d)/'test.sqlite3',clock=lambda:h['NOW']);app=ApplicationSession(db);assert app.open();h['populate'](app)
    w=MainWindow(app,QSettings(str(Path(d)/'window.ini'),QSettings.Format.IniFormat),start_chart=False)
    w.chart_now=lambda:h['NOW'];w.chart_controller.zone_provider=lambda:ZoneInfo('UTC');w.show()
    spin(lambda:w._preferences_ready and w.chart.bridge.is_ready)
    def draw(period,zone):
        w.chart_controller.zone_provider=lambda:zone
        w.chart_controller.request(ChartQuery(period,AnalysisContext(h['NOW'],zone),compact=False,visible_series=(SeriesKind.COGNITIVE,SeriesKind.PHYSICAL),show_sleep=False,show_events=False))
        spin(lambda:w.chart.bridge.state=='confirmed' and w.chart_controller.requests.idle)
        spin(lambda:js(w.chart.page(),'window.healthtrackerChannel.rendering().rendered')==w.chart.bridge.pending.delivery_id)
        QTest.qWait(180)
    def snap(name,widget=w):
        QTest.qWait(120);assert widget.grab().save(str(out/(name+'.png')))
    draw(DateRange(h['DAY'],h['DAY']+timedelta(days=2)),ZoneInfo('UTC'));snap('overview');snap('three-days')
    button=w.add_button;QTest.mouseMove(button,button.rect().center());snap('hover')
    for name,combo in [('period',w.chart_controls.period),('mode',w.chart_controls.mode)]:
        if name=='mode':
            with QSignalBlocker(combo):
                combo.clear()
                for mode in (ChartMode.COMPACT,ChartMode.TIMELINE):combo.addItem(MODES[mode],mode)
                combo.setCurrentIndex(1)
        combo.showPopup();QTest.qWait(120);snap(name,w);snap(name+'-popup',combo.view().window());combo.hidePopup()
    w.add_menu.popup(w.add_button.mapToGlobal(w.add_button.rect().bottomLeft()));snap('add-menu',w.add_menu);w.add_menu.hide()
    js(w.chart.page(),'window.healthtrackerChannel.zoom(25,65)');snap('zoom')
    draw(DateRange(h['DAY']-timedelta(days=5),h['DAY']-timedelta(days=3)),ZoneInfo('America/New_York'));snap('dst')
    print('Font:',w.font().family(),w.font().weight(),'available:',[x for x in ('Inter','Noto Sans','DejaVu Sans') if x in QFontDatabase.families()],flush=True)
    w.close();spin(lambda:not w.isVisible());w.chart_controller.shutdown();w.analytics_page.shutdown();app.close()
print(out,flush=True)
