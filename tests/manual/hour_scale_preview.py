"""До/после: непрерывные три дня, реальные пропуски и одна точка. Только временные базы."""
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo
import argparse
import json
import os
import runpy
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from healthtracker.application.session import ApplicationSession
from healthtracker.application.charts import ChartQuery
from healthtracker.domain.analytics import AnalysisContext
from healthtracker.domain.answers import CognitiveAnswer, AnswerStatus
from healthtracker.domain.cognitive import CognitiveAssessment
from healthtracker.domain.catalogs import SymptomStatus
from healthtracker.domain.charts import SeriesKind
from healthtracker.domain.periods import DateRange
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.presentation.main_window import MainWindow

DAY=date(2026,11,5)
NOW=datetime(2026,11,9,23,59,tzinfo=UTC)
PROFILE=(7,6,5,4,4,5,6,7,6,5,4,5,7,7,6,4,0,0,2,9,10,10,7,6)


def populate(app,broken=False,single=False):
    obs=app.observations
    if single:
        obs.save_cognitive(CognitiveAssessment(*(CognitiveAnswer.numeric(0) for _ in range(3))),datetime(2026,11,8,12,tzinfo=UTC))
        return
    for offset in range(-7,3):
        if broken and offset==-3:continue
        day=DAY+timedelta(days=offset)
        for hour in (range(24) if offset>=0 else (12,)):
            if broken and offset==1 and 7<=hour<=12:continue
            moment=datetime.combine(day,datetime.min.time(),UTC)+timedelta(hours=hour)
            value=PROFILE[(hour+offset*2)%24]
            answer=CognitiveAnswer(AnswerStatus.NOT_ENGAGED) if broken and offset==1 and hour==23 else CognitiveAnswer.numeric(value)
            obs.save_cognitive(CognitiveAssessment(answer,answer,answer),moment)
            obs.save_physical(score=PROFILE[(hour+offset+5)%24],observed_at=moment,symptom_status=SymptomStatus.UNKNOWN,symptoms=())
            if broken and offset==1 and hour==3:
                obs.save_cognitive(CognitiveAssessment(*(CognitiveAnswer.numeric(4) for _ in range(3))),moment)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=('before','after'),required=True)
    args=parser.parse_args()
    qt=QApplication([]);qt.setQuitOnLastWindowClosed(False)
    assert qt.platformName()=='wayland'
    helpers=runpy.run_path(str(Path(__file__).resolve().parents[1]/'performance/analytics_load.py'))
    spin,js=helpers['spin'],helpers['javascript']
    output=Path('/tmp/healthtracker-hour-scale')/args.phase/os.environ.get('QT_SCALE_FACTOR','1')
    output.mkdir(parents=True,exist_ok=True)
    for dataset in ('continuous','breaks','single'):
        with TemporaryDirectory(prefix='healthtracker-hour-scale-') as directory:
            root=Path(directory);db=Database(root/'synthetic.sqlite3',clock=lambda:NOW)
            app=ApplicationSession(db);assert app.open()
            populate(app,broken=dataset=='breaks',single=dataset=='single')
            window=MainWindow(app,QSettings(str(root/'window.ini'),QSettings.Format.IniFormat),start_chart=False)
            window.chart_now=lambda:NOW;window.chart_controller.zone_provider=lambda:UTC
            window.show();spin(lambda:window._preferences_ready and window.chart.bridge.is_ready)
            cases=[('single',DateRange(DAY+timedelta(days=3),DAY+timedelta(days=3)),True)] if dataset=='single' else [
                ('day',DateRange(DAY,DAY),True),('compact',DateRange(DAY,DAY+timedelta(days=2)),True),
                ('timeline',DateRange(DAY,DAY+timedelta(days=2)),False),
                ('dst',DateRange(date(2026,10,31),date(2026,11,2)),False),
                ('daily',DateRange(DAY-timedelta(days=7),DAY+timedelta(days=2)),True)]
            for name,period,compact in cases:
                kinds=(SeriesKind.COGNITIVE,) if dataset=='single' else (SeriesKind.COGNITIVE,SeriesKind.PHYSICAL)
                zone=ZoneInfo('America/New_York') if name=='dst' else UTC
                window.chart_controller.zone_provider=lambda:zone
                query=ChartQuery(period,AnalysisContext(NOW,zone),visible_series=kinds,compact=compact,show_sleep=False,show_events=False)
                window.chart_controller.request(query)
                spin(lambda:window.chart.bridge.state=='confirmed' and window.chart_controller.requests.idle)
                spin(lambda:window.chart.bridge.pending is not None and js(window.chart.page(),'window.healthtrackerChannel.rendering().rendered')==window.chart.bridge.pending.delivery_id)
                QTest.qWait(220)
                label=dataset+'-'+name
                assert window.grab().save(str(output/(label+'.png')))
                data=js(window.chart.page(),"JSON.stringify(window.healthtrackerChannel.rendering().series.filter(s=>s.type==='line').map(s=>({id:s.id,smooth:s.smooth,points:s.data.map(p=>p.value)})))")
                (output/(label+'.json')).write_text(data)
                if dataset=='continuous' and name=='timeline':
                    js(window.chart.page(),'window.healthtrackerChannel.zoom(30,36)')
                    QTest.qWait(220)
                    assert window.grab().save(str(output/'midnight-zoom.png'))
            window.close();spin(lambda:not window.isVisible())
            window.chart_controller.shutdown();window.analytics_page.shutdown();app.close()
    print(f'Wayland: {args.phase}, {output}',flush=True)


if __name__=='__main__':main()
