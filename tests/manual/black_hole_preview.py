"""Реальные Wayland-снимки: только временные искусственные данные, без личной базы."""
import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import runpy

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from healthtracker.application.session import ApplicationSession
from healthtracker.domain.answers import CognitiveAnswer
from healthtracker.domain.cognitive import CognitiveAssessment
from healthtracker.domain.chart_preferences import ChartPreferences
from healthtracker.domain.charts import SeriesKind
from healthtracker.domain.periods import QuickPeriod
from healthtracker.domain.catalogs import SymptomStatus
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.presentation.main_window import MainWindow

helper = runpy.run_path(str(Path(__file__).resolve().parents[1]/'performance/analytics_load.py'))
spin, js = helper['spin'], helper['javascript']
parser=argparse.ArgumentParser()
parser.add_argument('--phase', choices=('before','after'), required=True)
args=parser.parse_args()
qt=QApplication([])
qt.setQuitOnLastWindowClosed(False)
assert qt.platformName()=='wayland'
scale=os.environ.get('QT_SCALE_FACTOR','1')
out=Path('/tmp/healthtracker-black-hole')/args.phase/scale
out.mkdir(parents=True,exist_ok=True)
now=datetime(2026,11,4,21,tzinfo=UTC)
for case in ('one','day','multiple','empty'):
    with TemporaryDirectory(prefix='healthtracker-black-hole-') as directory:
        root=Path(directory)
        db=Database(root/'synthetic.sqlite3',clock=lambda:now)
        app=ApplicationSession(db)
        assert app.open()
        obs=app.observations
        days=range(10) if case=='multiple' else range(1)
        if case!='empty':
            for day in days:
                scores=(3,5,4,7,6,8) if case!='one' else (7,)
                for index,value in enumerate(scores):
                    moment=(now-timedelta(days=day)).replace(hour=8+index,minute=0)
                    assessment=CognitiveAssessment(*(CognitiveAnswer.numeric(v) for v in (value,max(0,value-1),min(10,value+1))))
                    obs.save_cognitive(assessment,moment)
                if case=='multiple':
                    obs.save_physical(score=4+day%4,observed_at=moment,symptom_status=SymptomStatus.UNKNOWN,symptoms=())
                    obs.save_mood(score=3+day%5,observed_at=moment)
                    obs.save_stress(score=day%3,observed_at=moment)
                    obs.save_sleep(start=moment-timedelta(hours=12),end=moment-timedelta(hours=4))
        app.chart_preferences.save(ChartPreferences(visible_series=tuple(SeriesKind) if case=='multiple' else (SeriesKind.COGNITIVE,),show_sleep=case=='multiple'))
        window=MainWindow(app,QSettings(str(root/'window.ini'),QSettings.Format.IniFormat),start_chart=False)
        window.chart_now=lambda:now
        window.chart_controller.zone_provider=lambda:UTC
        window.show()
        spin(lambda:window._preferences_ready and window.chart.bridge.is_ready)
        window.start_chart=True
        if case=='multiple':
            panel=window.chart_controls
            panel.period.setCurrentIndex(panel.period.findData(QuickPeriod.TEN_DAYS))
        window._request_controls()
        spin(lambda:window.chart.bridge.state=='confirmed' and window.chart_controller.requests.idle)
        spin(lambda:window.chart.bridge.pending is not None and js(window.chart.page(),'window.healthtrackerChannel.rendering().rendered')==window.chart.bridge.pending.delivery_id)
        window.navigation.setCurrentRow(0)
        QTest.qWait(250)  # Только кадр композитора, не синхронизация worker.
        assert window.grab().save(str(out/(case+'.png')))
        if args.phase=='after' and case=='day':
            js(window.chart.page(),'window.healthtrackerChannel.showTip(0,2)')
            spin(lambda:js(window.chart.page(),'Boolean(document.querySelector(".observation-tooltip"))'))
            QTest.qWait(200)
            assert window.grab().save(str(out/'tooltip.png'))
            js(window.chart.page(),"echarts.getInstanceByDom(document.getElementById('chart')).dispatchAction({type:'hideTip'})")
            js(window.chart.page(),'window.healthtrackerChannel.zoom(20,70)')
            if hasattr(window,'_poll_chart_zoom'):
                window._poll_chart_zoom()
                spin(lambda:window.chart_controls.reset_zoom.isVisible())
            QTest.qWait(200)
            assert window.grab().save(str(out/'zoom.png'))
            window.chart_controls.reset_zoom.click()
        if args.phase=='after' and case=='multiple':
            window.resize(min(900,window.screen().availableGeometry().width()),min(600,window.screen().availableGeometry().height()))
            QTest.qWait(200)
            assert window.grab().save(str(out/'small.png'))
        window.close()
        spin(lambda:not window.isVisible())
        window.chart_controller.shutdown()
        window.analytics_page.shutdown()
        app.close()
print(f'Wayland {scale}: {args.phase}: {out}',flush=True)
