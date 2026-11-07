"""Граничные точки/сегменты: только временная искусственная SQLite, настоящий Wayland."""
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
import argparse
import json
import os
import runpy
from tempfile import TemporaryDirectory

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
NOW=datetime(2026,11,7,23,59,tzinfo=UTC)


def populate(app):
    obs=app.observations
    profile={0:10,1:10,2:10,3:8,4:6,5:3,6:0,7:0,8:0,9:3,10:6,11:9,12:10,13:10,14:None,15:7,16:4,21:0,22:0,23:10}
    for index in range(10):
        day=DAY-timedelta(days=index)
        for hour,base in profile.items():
            value=base if index%3==0 else 0 if index%3==1 else 10
            moment=datetime.combine(day,datetime.min.time(),UTC)+timedelta(hours=hour)
            answer=CognitiveAnswer(AnswerStatus.NOT_ENGAGED) if value is None else CognitiveAnswer.numeric(value)
            obs.save_cognitive(CognitiveAssessment(answer,answer,answer),moment)
            obs.save_physical(score=4 if value is None else 10-value,observed_at=moment,symptom_status=SymptomStatus.UNKNOWN,symptoms=())
            obs.save_mood(score=(hour*3)%11,observed_at=moment)
            obs.save_stress(score=(hour%3)*5,observed_at=moment)
    moment=datetime(2026,11,7,12,tzinfo=UTC)
    obs.save_cognitive(CognitiveAssessment(*(CognitiveAnswer.numeric(0) for _ in range(3))),moment)


GEOMETRY="""(() => {
    const c=echarts.getInstanceByDom(document.getElementById('chart'));
    const r=c.getModel().getComponent('grid',0).coordinateSystem.getRect();
    const rows=c.getOption().series.filter(s=>s.type==='line').map(s=>{
        const model=c.getModel().getSeries().find(m=>m.id===s.id);
        const group=c.getViewOfSeriesModel(model).group;
        const clips=[];
        group.traverse(el=>{const p=el.getClipPath && el.getClipPath();if(p) clips.push(p.shape);});
        return {id:s.id,clip:s.clip,clips,modelCount:model.getData().count(),points:s.data.map(p=>p.value)};
    });
    return JSON.stringify({grid:{x:r.x,y:r.y,width:r.width,height:r.height},
        zero:c.convertToPixel({xAxisIndex:0,yAxisIndex:0},[0,0]),
        ten:c.convertToPixel({xAxisIndex:0,yAxisIndex:0},[0,10]),rows});
})()"""


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--phase',choices=('before','after'),required=True)
    args=parser.parse_args()
    qt=QApplication([])
    qt.setQuitOnLastWindowClosed(False)
    assert qt.platformName()=='wayland'
    helpers=runpy.run_path(str(Path(__file__).resolve().parents[1]/'performance/analytics_load.py'))
    spin,js=helpers['spin'],helpers['javascript']
    output=Path('/tmp/healthtracker-chart-edges')/args.phase/os.environ.get('QT_SCALE_FACTOR','1')
    output.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix='healthtracker-edges-') as directory:
        root=Path(directory)
        db=Database(root/'synthetic.sqlite3',clock=lambda:NOW)
        app=ApplicationSession(db)
        assert app.open()
        populate(app)
        window=MainWindow(app,QSettings(str(root/'window.ini'),QSettings.Format.IniFormat),start_chart=False)
        window.chart_now=lambda:NOW
        window.chart_controller.zone_provider=lambda:UTC
        window.show()
        spin(lambda:window._preferences_ready and window.chart.bridge.is_ready)
        def capture(name,query):
            window.chart_controller.request(query)
            spin(lambda:window.chart.bridge.state=='confirmed' and window.chart_controller.requests.idle)
            spin(lambda:window.chart.bridge.pending is not None and js(window.chart.page(),'window.healthtrackerChannel.rendering().rendered')==window.chart.bridge.pending.delivery_id)
            QTest.qWait(200)  # Кадр композитора, не синхронизация worker.
            assert window.grab().save(str(output/(name+'.png')))
            (output/(name+'.json')).write_text(js(window.chart.page(),GEOMETRY))
        context=AnalysisContext(NOW,UTC)
        for name,period,compact in (
            ('day',DateRange(DAY,DAY),True),('compact',DateRange(DAY-timedelta(days=2),DAY),True),
            ('timeline',DateRange(DAY-timedelta(days=2),DAY),False),('daily',DateRange(DAY-timedelta(days=9),DAY),True),
            ('single',DateRange(NOW.date(),NOW.date()),True)):
            kinds=(SeriesKind.COGNITIVE,) if name=='single' else tuple(SeriesKind)
            query=ChartQuery(period,context,visible_series=kinds,compact=compact,show_sleep=False,show_events=False)
            capture(name,query)
            if name=='day':
                for label,start,end in (('zoom',20,45),('pan',40,65),('between',13.333333,15.833333)):
                    js(window.chart.page(),f'window.healthtrackerChannel.zoom({start},{end})')
                    QTest.qWait(200)
                    assert window.grab().save(str(output/(label+'.png')))
                    (output/(label+'.json')).write_text(js(window.chart.page(),GEOMETRY))
                # Один выбранный ряд при тех же неизменных измерениях.
                capture('physical',ChartQuery(period,context,visible_series=(SeriesKind.PHYSICAL,),show_sleep=False,show_events=False))
        window.close()
        spin(lambda:not window.isVisible())
        window.chart_controller.shutdown()
        window.analytics_page.shutdown()
        app.close()
    print(f'Wayland: {args.phase}, {output}',flush=True)


if __name__=='__main__':
    main()
