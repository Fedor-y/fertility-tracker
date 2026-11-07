"""Проверка настоящих моделей/графических элементов ECharts, не только JSON."""
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
import json
import os
from pathlib import Path

import pytest

from test_chart_channel import channel, js, snapshot
from healthtracker.application.charts import ChartQuery
from healthtracker.domain.analytics import AnalysisContext
from healthtracker.domain.answers import AnswerStatus, CognitiveAnswer
from healthtracker.domain.catalogs import MealCategory, SymptomStatus
from healthtracker.domain.charts import SeriesKind
from healthtracker.domain.cognitive import CognitiveAssessment
from healthtracker.domain.periods import DateRange

DAY = date(2026, 11, 1)
MOMENT = datetime(2026, 11, 1, 12, tzinfo=UTC)
CONTEXT = AnalysisContext(datetime(2026, 11, 4, 12, tzinfo=UTC), UTC)


def seed(window, day=DAY, *, moment=None):
    obs = window.application.observations
    moment = moment or datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=12)
    ids = {}
    for kind, values in [('cognitive', (0, 6, 9))]:
        ids[kind] = obs.save_cognitive(CognitiveAssessment(*(CognitiveAnswer.numeric(v) for v in values)), moment)
    ids['physical'] = obs.save_physical(score=0, observed_at=moment, symptom_status=SymptomStatus.UNKNOWN, symptoms=())
    ids['mood'] = obs.save_mood(score=4, observed_at=moment)
    ids['stress'] = obs.save_stress(score=0, observed_at=moment)
    ids['sleep'] = obs.save_sleep(start=moment - timedelta(hours=10), end=moment - timedelta(hours=2))
    ids['meals'] = obs.save_meal(entry_date=day, category=MealCategory.OTHER, items=({'name': '<script>synthetic</script>'},))
    ids['gym'] = obs.save_gym(entry_date=day, attended=False)
    return ids


def render(channel, qtbot, days=1, compact=True, kinds=None, zone=UTC, start=DAY):
    window, _, c, b, _ = channel
    c.zone_provider = lambda: zone
    query = ChartQuery(DateRange(start, start + timedelta(days=days - 1)),
                       replace(CONTEXT, zone=zone), visible_series=tuple(SeriesKind) if kinds is None else kinds,
                       compact=compact)
    c.request(query)
    qtbot.waitUntil(lambda: b.state == 'confirmed', timeout=15000)
    qtbot.waitUntil(lambda: picture(qtbot, window)['rendered'] == b.pending.delivery_id, timeout=15000)
    qtbot.waitUntil(lambda: (lambda r: r['width'] == r['domWidth'] and r['height'] == r['domHeight'])(picture(qtbot, window)))
    return picture(qtbot, window)


def picture(qtbot, window):
    return json.loads(js(qtbot, window, 'JSON.stringify(window.healthtrackerChannel.rendering())'))


@pytest.mark.parametrize('kind', list(SeriesKind))
def test_each_indicator_has_real_echarts_graphics(channel, qtbot, kind):
    window, _, _, b, _ = channel
    seed(window)
    result = render(channel, qtbot, kinds=(kind,))
    model = next(m for m in result['models'] if m['id'] == kind.value + '-points')
    assert model['count'] == 1 and model['graphics'] == 1
    series = next(s for s in result['series'] if s['id'] == kind.value + '-points')
    assert series['data'][0]['value'][1] == {'cognitive': 5, 'learning': 0, 'application': 6,
        'speed': 9, 'physical': 0, 'mood': 4, 'stress': 0}[kind.value]
    assert result['elements'] > 5 and result['paintCount'] > 0
    assert b.echarts_version == '6.0.0'


@pytest.mark.parametrize('days,compact,mode', [(1, True, 'day'), (3, True, 'compact'),
                                              (3, False, 'timeline'), (10, True, 'daily')])
def test_modes_render_actual_canvas_and_calendar_events(channel, qtbot, days, compact, mode):
    window, _, _, b, _ = channel
    seed(window)
    result = render(channel, qtbot, days=days, compact=compact)
    assert snapshot(qtbot, window)['candidate']['data']['mode'] == mode
    assert result['plotHeight'] >= 150
    assert next(m for m in result['models'] if m['id'] == 'cognitive-points')['graphics'] == 1
    assert next(m for m in result['models'] if m['id'] == 'sleep')['graphics'] >= 1
    text = js(qtbot, window, 'document.querySelector(".calendar-events").textContent')
    assert 'Питание' in text and 'Спортзал: Не был' in text and 'только дату' in text
    events = snapshot(qtbot, window)['candidate']['data']['calendar_events']
    assert all('utc_moment' not in e and 'time' not in e for e in events)
    assert events[1]['attended'] is False
    path = Path('/tmp/healthtracker-echarts-preview') / os.environ.get('QT_SCALE_FACTOR', '1')
    path.mkdir(parents=True, exist_ok=True)
    assert window.chart.grab().save(str(path / (mode + '.png')))
    image = window.chart.grab().toImage()
    point = json.loads(js(qtbot, window, """(() => {
        const c=echarts.getInstanceByDom(document.getElementById('chart'));
        const row=c.getOption().series.find(s=>s.id==='cognitive-points');
        return JSON.stringify(c.convertToPixel({xAxisIndex:0,yAxisIndex:0},row.data[0].value));
    })()"""))
    dpr=image.devicePixelRatio()
    x,y=int(point[0]*dpr),int(point[1]*dpr)
    radius=max(3,int(6*dpr))
    light = sum(1 for py in range(max(0,y-radius),min(image.height(),y+radius+1))
                for px in range(max(0,x-radius),min(image.width(),x+radius+1))
                if (lambda col: min(col.red(),col.green(),col.blue())>160
                    and max(col.red(),col.green(),col.blue())-min(col.red(),col.green(),col.blue())<10)(image.pixelColor(px,py)))
    assert light > 0  # Светлый маркер в реальных координатах, не подписи оси.
    assert next(s for s in result['series'] if s['id']=='cognitive-points')['itemStyle']['color']=='#f0f0f0'



def test_empty_has_no_fictitious_markers(channel, qtbot):
    window, _, _, _, _ = channel
    result = render(channel, qtbot)
    assert all(m['count'] == 0 for m in result['models'])
    assert result['option']['title'][0]['text'] == 'Нет числовых наблюдений'


def test_special_answers_remain_accessible_without_zero_markers(channel, qtbot):
    window, _, _, _, _ = channel
    obs = window.application.observations
    obs.save_cognitive(CognitiveAssessment(CognitiveAnswer.numeric(0),
        CognitiveAnswer(AnswerStatus.NOT_ENGAGED), CognitiveAnswer(AnswerStatus.CANNOT_ASSESS)), MOMENT)
    result = render(channel, qtbot)
    counts = {m['id']: m['count'] for m in result['models']}
    assert counts['cognitive-points'] == counts['application-points'] == counts['speed-points'] == 0
    assert counts['learning-points'] == 1
    text = js(qtbot, window, 'document.querySelector(".calendar-events").textContent')
    assert 'Не занимался' in text and 'Не могу оценить' in text


@pytest.mark.parametrize('kind', [SeriesKind.COGNITIVE, SeriesKind.STRESS])
def test_duplicate_utc_and_segments_survive_into_echarts(channel, qtbot, kind):
    window, _, _, _, _ = channel
    obs = window.application.observations
    ids = [(obs.save_stress(score=score, observed_at=MOMENT) if kind is SeriesKind.STRESS else
            obs.save_cognitive(CognitiveAssessment(*(CognitiveAnswer.numeric(score) for _ in range(3))), MOMENT))
           for score in (0, 9)]
    result = render(channel, qtbot, kinds=(kind,))
    model = next(m for m in result['models'] if m['id'] == kind.value + '-points')
    assert model['count'] == model['graphics'] == 2
    assert not any(m['type'] == 'line' for m in result['models'])
    points = result['series'][0]['data']
    assert points[0]['value'][0] == points[1]['value'][0]
    assert {s['record_id'] for s in points[0]['sources']} == set(ids)
    assert all('#' + str(record_id) in '\n'.join(points[0]['lines']) for record_id in ids)


def test_midnight_connects_display_but_domain_rules_are_separate(channel, qtbot):
    window, _, _, _, _ = channel
    obs = window.application.observations
    for moment in (MOMENT.replace(hour=23), MOMENT + timedelta(days=1, hours=-12)):
        obs.save_mood(score=3, observed_at=moment)
    result = render(channel, qtbot, days=3, kinds=(SeriesKind.MOOD,))
    assert len([m for m in result['models'] if m['type'] == 'line']) == 1
    result = render(channel, qtbot, days=10, kinds=(SeriesKind.MOOD,))
    assert any(m['type'] == 'line' for m in result['models'])


def test_real_line_uses_prepared_segment_only(channel, qtbot):
    window, _, _, _, _ = channel
    obs = window.application.observations
    for hours, score in [(0, 0), (3, 10), (7, 5)]:
        obs.save_mood(score=score, observed_at=MOMENT + timedelta(hours=hours))
    result = render(channel, qtbot, kinds=(SeriesKind.MOOD,))
    lines = [s for s in result['series'] if s['type'] == 'line']
    assert len(lines) == 1 and len(lines[0]['data']) == 2
    assert lines[0]['smooth'] == 0.3 and lines[0]['connectNulls'] is False


def test_tooltip_dom_is_text_and_source_opens_existing_form(channel, qtbot):
    window, _, _, b, _ = channel
    ids = seed(window)
    result = render(channel, qtbot)
    series_index = next(i for i, s in enumerate(result['series']) if s['id'] == 'cognitive-points')
    js(qtbot, window, f'window.healthtrackerChannel.showTip({series_index}, 0)')
    text = js(qtbot, window, 'document.body.textContent')
    assert 'Когнитивный индекс' in text and 'Когнитивная запись #' + str(ids['cognitive']) in text
    assert 'Когнитивный индекс · версия 1' in text
    assert js(qtbot, window, 'window.healthtrackerChannel.tooltip({lines:["<img src=x onerror=alert(1)>"],sources:[]}).querySelectorAll("img").length') == 0
    # Кнопка из общей подсказки использует проверенные page/request/delivery ID.
    js(qtbot, window, 'document.querySelector(".observation-tooltip button").click()')
    qtbot.waitUntil(lambda: getattr(window, 'active_dialog', None) is not None)
    assert window.active_dialog.isVisible()
    window.active_dialog.reject()
    b.openSource(b.pageId, b.pending.request_id, b.pending.delivery_id, 'cognitive', '999999')
    assert not window.active_dialog.isVisible()


def test_reload_restores_real_rendering_and_resize(channel, qtbot):
    window, _, _, b, _ = channel
    seed(window)
    result = render(channel, qtbot)
    old_page = b.pageId
    window.chart.reload()
    qtbot.waitUntil(lambda: b.pageId != old_page and b.state == 'confirmed', timeout=20000)
    qtbot.waitUntil(lambda: picture(qtbot, window)['rendered'] == b.pending.delivery_id)
    window.resize(850, 600)
    # Wayland может ограничить окно минимальным размером layout.
    # Дополнительно гарантируем реальное изменение контейнера, не подменяя resize-событие.
    current = window.chart.width()
    window.chart.setMaximumWidth(max(250, current - 80))
    qtbot.waitUntil(lambda: picture(qtbot, window)['width'] < current)
    assert picture(qtbot, window)['width'] > 200


def test_stale_and_renderer_failure_preserve_last_plot_with_warning(channel, qtbot):
    window, db, c, b, _ = channel
    seed(window)
    before = render(channel, qtbot)
    from PySide6.QtCore import QSignalBlocker
    blocker = QSignalBlocker(b)
    assert b.send_latest()
    old = b.pending
    del blocker
    c.invalidate()
    qtbot.waitUntil(lambda: snapshot(qtbot, window)['state'] == 'stale')
    b.received(old.page_id, old.request_id, old.delivery_id)
    assert picture(qtbot, window)['rendered'] == before['rendered']
    assert js(qtbot, window, 'document.getElementById("chart").classList.contains("outdated")')
    b.transport_failed()
    assert picture(qtbot, window)['rendered'] == before['rendered']
    with db.write() as session:
        session.settings.set('compact_mode', False)


@pytest.mark.parametrize('compact', [True, False])
def test_real_dst_fold_uses_python_coordinates_and_segments(channel, qtbot, compact):
    from zoneinfo import ZoneInfo
    window, _, _, _, _ = channel
    obs = window.application.observations
    a = datetime(2026,10,25,0,30,tzinfo=UTC)
    for moment,score in [(a,2),(a+timedelta(hours=1),8)]:
        obs.save_mood(score=score,observed_at=moment)
    result = render(channel,qtbot,days=2,compact=compact,kinds=(SeriesKind.MOOD,),
                    start=date(2026,10,25),zone=ZoneInfo('Europe/Berlin'))
    points = next(s for s in result['series'] if s['id']=='mood-points')['data']
    assert len(points)==2
    assert points[1]['value'][0]-points[0]['value'][0] == (0 if compact else 3600)
    assert len([m for m in result['models'] if m['type']=='line']) == (0 if compact else 1)
    assert '+02:00' in '\n'.join(points[0]['lines'])
    if compact: assert '+01:00' in '\n'.join(points[0]['lines'])


def test_default_window_loads_real_current_day_and_refreshes_after_save(channel,qtbot):
    window, _, c, b, _ = channel
    window.start_chart=True
    today = datetime.now(UTC).date()
    ids=seed(window,today,moment=datetime.combine(today,datetime.min.time(),UTC))
    window._refresh_chart()
    qtbot.waitUntil(lambda:b.state=='confirmed',timeout=15000)
    qtbot.waitUntil(lambda:picture(qtbot,window)['rendered']==b.pending.delivery_id)
    before=b.pending.delivery_id
    series=picture(qtbot,window)['series']
    assert {s['id'] for s in series if s['type']=='scatter'}=={'cognitive-points','physical-points'}
    assert series[0]['data'][0]['sources'][0]['record_id']==ids['cognitive']
    window._observation_saved('cognitive',ids['cognitive'])
    qtbot.waitUntil(lambda:b.state=='confirmed' and b.pending.delivery_id!=before,timeout=15000)


def test_invalid_view_js_error_keeps_last_successful_echarts_model(channel,qtbot):
    window,db,c,b,_=channel
    seed(window)
    before=render(channel,qtbot)
    from PySide6.QtCore import QSignalBlocker
    blocker=QSignalBlocker(b)
    b.send_latest();pending=b.pending
    del blocker
    bad=json.loads(pending.encode())
    bad['data']['view'].pop('axis')
    b.payload.emit(json.dumps(bad))
    qtbot.waitUntil(lambda:b.state=='error')
    assert picture(qtbot,window)['rendered']==before['rendered']
    assert picture(qtbot,window)['models']==before['models']
    with db.write() as session: session.settings.set('compact_mode',False)


def test_daily_missing_date_breaks_line_and_stress_is_not_aggregated(channel,qtbot):
    window,_,_,_,_=channel
    obs=window.application.observations
    for delta in (0,2):
        obs.save_mood(score=5,observed_at=MOMENT+timedelta(days=delta))
    for score in (0,8): obs.save_stress(score=score,observed_at=MOMENT)
    result=render(channel,qtbot,days=10,kinds=(SeriesKind.MOOD,SeriesKind.STRESS))
    assert [m['count'] for m in result['models']]==[2,2]
    assert all(m['type']=='scatter' for m in result['models'])


def test_source_action_rechecks_generation_before_opening_form(channel,qtbot):
    window,db,_,b,_=channel
    ids=seed(window)
    render(channel,qtbot)
    current=b.pending
    with db.write() as session: session.settings.set('compact_mode',False)
    b.openSource(b.pageId,current.request_id,current.delivery_id,'cognitive',str(ids['cognitive']))
    assert getattr(window,'active_dialog',None) is None


def test_actual_renderer_loss_does_not_block_sqlite_and_reload_recovers(channel,qtbot):
    import signal
    window,db,_,b,_=channel
    seed(window)
    before=render(channel,qtbot)
    pid=window.chart.page().renderProcessPid()
    assert pid>0 and pid!=os.getpid()
    os.kill(pid,signal.SIGKILL)  # Только дочерний renderer искусственного тестового окна.
    qtbot.waitUntil(lambda:b.state=='error',timeout=15000)
    assert window.isVisible() and window.application.storage_available
    with db.write() as session: session.settings.set('compact_mode',False)
    old_page=b.pageId
    assert window.chart.needs_reload
    window.chart_retry.click()
    qtbot.waitUntil(lambda:b.pageId!=old_page and b.is_ready and b.state=='confirmed',timeout=20000)
    qtbot.waitUntil(lambda:picture(qtbot,window)['rendered']==b.pending.delivery_id,timeout=15000)
    after=picture(qtbot,window)
    assert not window.chart.needs_reload
    assert after['rendered']!=before['rendered']
    assert next(m for m in after['models'] if m['id']=='cognitive-points')['graphics']==1
