"""Локальный замер, не норматив: временная база, WebChannel и реальный ECharts.

Запуск без сети в Wayland:
 bwrap --unshare-net --dev-bind / / -- .venv/bin/python tests/performance/analytics_load.py
Выводит только размеры/время, без наблюдений и сообщений WebChannel.
"""
from contextlib import ExitStack
from datetime import UTC,datetime,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch
import json,resource

from PySide6.QtCore import QDate,QEventLoop,QSignalBlocker,QTimer
from PySide6.QtWidgets import QApplication

from healthtracker.application.analytics import Analytics
from healthtracker.application.analytics_page import AnalyticsPagePreparation
from healthtracker.application.session import ApplicationSession
from healthtracker.domain.answers import CognitiveAnswer
from healthtracker.domain.cognitive import CognitiveAssessment
from healthtracker.domain.charts import SeriesKind
from healthtracker.domain.chart_preferences import ChartPreferences
from healthtracker.domain.measurement import CognitiveMeasurement
from healthtracker.domain.intervals import CognitiveInterval,SleepInterval
from healthtracker.domain.records import PhysicalRecord,StressRecord,MoodRecord,SleepRecord,MealRecord,MealItem,GymRecord
from healthtracker.domain.catalogs import SymptomStatus,MealCategory
from healthtracker.infrastructure.sqlite.database import Database
from healthtracker.presentation.main_window import MainWindow

NOW=datetime(2026,11,4,12,tzinfo=UTC)


def populate(db,days):
    assessment=CognitiveAssessment(*(CognitiveAnswer.numeric(6) for _ in range(3)))
    meta=dict(created_at=NOW,updated_at=NOW)
    with db.write() as s:
        for index in range(days):
            day=NOW-timedelta(days=days-index,hours=4)  # 08:00 UTC
            for hours in (1,4,7,10):
                s.cognitive.create(CognitiveMeasurement(assessment,CognitiveInterval(day+timedelta(hours=hours),now=NOW),NOW,NOW))
            s.physical.create(PhysicalRecord(observed_at=day,score=7,symptom_status=SymptomStatus.UNKNOWN,**meta))
            s.stress.create(StressRecord(observed_at=day,score=0,**meta))
            s.mood.create(MoodRecord(observed_at=day,score=5,**meta))
            s.sleep.create(SleepRecord(interval=SleepInterval(day-timedelta(hours=8),day,now=NOW),**meta))
            for category in (MealCategory.BREAKFAST,MealCategory.LUNCH,MealCategory.DINNER):
                s.meals.create(MealRecord(entry_date=day.date(),category=category,items=(MealItem(name='Искусственная позиция',**meta),),**meta))
            attended=index%2==0
            s.gym.create(GymRecord(entry_date=day.date(),attended=attended,difficulty=5 if attended else None,
                                  difficulty_scale_version=1 if attended else None,**meta))


def spin(predicate,timeout=120000):
    if predicate():return
    loop=QEventLoop();poll=QTimer();deadline=QTimer();deadline.setSingleShot(True)
    poll.timeout.connect(lambda:loop.quit() if predicate() else None)
    deadline.timeout.connect(loop.quit);poll.start(10);deadline.start(timeout);loop.exec()
    poll.stop();deadline.stop()
    if not predicate():raise RuntimeError('Время ожидания тестового результата истекло')


def javascript(page,code):
    value=[];page.runJavaScript(code,value.append);spin(lambda:bool(value))
    return value[0]


def run(days):
    with TemporaryDirectory(prefix='healthtracker-analytics-bench-') as directory:
        db=Database(Path(directory)/'synthetic.sqlite3',clock=lambda:NOW)
        application=ApplicationSession(db);assert application.open()
        populate(db,days)
        application.chart_preferences.save(ChartPreferences(visible_series=tuple(SeriesKind)))
        metrics={'snapshot_ms':0.,'calculation_ms':0.,'worker_ms':0.}
        class TimedAnalytics(Analytics):
            def load(self,*args):
                start=perf_counter();value=super().load(*args)
                metrics['snapshot_ms']+=(perf_counter()-start)*1000;return value
        class Preparation(AnalyticsPagePreparation):
            def prepare(self,*args):
                start=perf_counter();value=super().prepare(*args)
                metrics['worker_ms']+=(perf_counter()-start)*1000;return value
        def timer(function):
            def measure(*args,**kwargs):
                start=perf_counter()
                try:return function(*args,**kwargs)
                finally:metrics['calculation_ms']+=(perf_counter()-start)*1000
            return measure
        import healthtracker.application.charts as charts
        import healthtracker.application.analytics_page as analytics_page
        with ExitStack() as stack:
            for module,name in ((charts,'calculate_snapshot'),(charts,'daily_statistics'),
                                (analytics_page,'period_statistics'),(analytics_page,'compare_periods')):
                stack.enter_context(patch.object(module,name,timer(getattr(module,name))))
            window=MainWindow(application,start_chart=False)
            window.chart_now=lambda:NOW;window.chart_controller.zone_provider=lambda:UTC
            window.show();spin(lambda:window._preferences_ready)
            page=window.analytics_page
            with QSignalBlocker(page.controls.period):
                page.controls.period.setCurrentIndex(page.controls.period.findData('custom'))
            page.controls.start.setDate(QDate((NOW-timedelta(days=days)).date()))
            page.controls.end.setDate(QDate((NOW-timedelta(days=1)).date()))
            window.navigation.setCurrentRow(1)
            page.controller.requests.preparation=Preparation(TimedAnalytics(db))
            sent=[];confirmed=[]
            def payload(message):
                if '"kind": "data"' in message[:80]:sent.append((perf_counter(),len(message.encode('utf-8'))))
            page.chart.bridge.payload.connect(payload)
            page.chart.bridge.state_changed.connect(lambda state:confirmed.append(perf_counter()) if state=='confirmed' else None)
            started=perf_counter()
            spin(lambda:page.chart.bridge.state=='confirmed' and page.sections is not None)
            delivery=page.chart.bridge.pending.delivery_id
            def rendering():
                return json.loads(javascript(page.chart.page(),'''JSON.stringify((()=>{let r=window.healthtrackerChannel.rendering();return {rendered:r.rendered,renderMs:r.renderMs,paintCount:r.paintCount,graphics:r.models.map(m=>({id:m.id,count:m.count,graphics:m.graphics})),width:r.width,domWidth:r.domWidth};})())'''))
            result=rendering()
            spin(lambda:rendering()['rendered']==delivery)
            result=rendering()
            assert result['paintCount']>0 and result['width']==result['domWidth']
            assert next(m for m in result['graphics'] if m['id']=='sleep-analysis')['graphics']==days
            metrics['presentation_ms']=metrics['worker_ms']-metrics['snapshot_ms']-metrics['calculation_ms']
            metrics['channel_roundtrip_ms']=(confirmed[0]-sent[0][0])*1000
            metrics['javascript_render_ms']=result['renderMs']
            metrics['end_to_checked_render_ms']=(perf_counter()-started)*1000
            metrics['payload_bytes']=sent[0][1]
            metrics['days']=days;metrics['records']=days*12
            metrics['peak_process_rss_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            window.close();spin(lambda:not window.isVisible());application.close()
            print(json.dumps({key:round(value,2) if isinstance(value,float) else value for key,value in metrics.items()},ensure_ascii=False),flush=True)


def main():
    qt=QApplication([]);qt.setQuitOnLastWindowClosed(False)
    for days in (31,1096):run(days)


if __name__=='__main__':main()
