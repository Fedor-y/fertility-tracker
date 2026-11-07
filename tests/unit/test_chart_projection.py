from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from healthtracker.domain.analytics import AnalysisContext
from healthtracker.domain.charts import (CalendarEvent, ChartMode, ChartSample, PreparedChart,
    SeriesKind, SleepSpan, SourceRef, chart_mode, prepare_series)
from healthtracker.domain.periods import DateRange
from healthtracker.application.chart_projection import day_start, project_chart


def chart(samples=(), *, start=date(2026,11,1), days=1, zone=UTC, compact=True, sleep=(), events=(), kind=SeriesKind.COGNITIVE):
    period = DateRange(start, start + timedelta(days=days-1))
    context = AnalysisContext(datetime(2026,12,1,tzinfo=UTC), zone)
    mode = chart_mode(period, compact)
    row = prepare_series(kind, tuple(samples), period, context, mode, 3)
    return PreparedChart(period, context, mode, 3, (row,), tuple(events), tuple(sleep))


def sample(moment, value, record_id=1):
    return ChartSample(SourceRef('cognitive',record_id),moment,value)


@pytest.mark.parametrize('day,hours', [(date(2026,3,29),23),(date(2026,10,25),25)])
def test_real_axis_uses_actual_dst_day_length(day,hours):
    result=project_chart(chart(start=day,zone=ZoneInfo('Europe/Berlin')))
    assert result['axis']['max']==hours*3600


def test_compact_repeat_hour_preserves_both_utc_and_breaks_connection():
    zone=ZoneInfo('Europe/Berlin');day=date(2026,10,25)
    a=datetime(2026,10,25,0,30,tzinfo=UTC);b=a+timedelta(hours=1)
    data=chart([sample(a,2,1),sample(b,8,2)],start=day,days=2,zone=zone)
    result=project_chart(data);row=result['series'][0]
    assert [p['value'][0] for p in row['points']]==[9000,9000]
    assert row['segments']==[]
    assert '+02:00' in '\n'.join(row['points'][0]['lines'])
    assert '+01:00' in '\n'.join(row['points'][0]['lines'])
    assert [s['record_id'] for s in row['points'][0]['sources']]==[1,2]
    assert any('DST' in tick['text'] for tick in result['axis']['ticks'])


def test_timeline_repeat_hour_preserves_elapsed_hour():
    zone=ZoneInfo('Europe/Berlin');a=datetime(2026,10,25,0,30,tzinfo=UTC)
    result=project_chart(chart([sample(a,2),sample(a+timedelta(hours=1),8,2)],
        start=date(2026,10,25),days=2,zone=zone,compact=False))
    points=result['series'][0]['points']
    assert points[1]['value'][0]-points[0]['value'][0]==3600
    assert result['series'][0]['segments']==[[0,1]]


def test_spring_gap_is_not_filled():
    zone=ZoneInfo('Europe/Berlin');a=datetime(2026,3,29,0,30,tzinfo=UTC)
    result=project_chart(chart([sample(a,2),sample(a+timedelta(hours=1),8,2)],
        start=date(2026,3,29),days=2,zone=zone))
    assert [p['value'][0] for p in result['series'][0]['points']]==[5400,12600]


def test_sleep_split_at_midnight_and_dst_without_reversing_time():
    zone=ZoneInfo('Europe/Berlin');start=datetime(2026,10,25,0,45,tzinfo=UTC)
    span=SleepSpan(SourceRef('sleep',7),start,start+timedelta(minutes=30),date(2026,10,25))
    result=project_chart(chart(start=date(2026,10,25),days=2,zone=zone,sleep=(span,)))
    assert [p['value'] for p in result['sleep']]==[[0,9900,10800],[0,7200,8100]]
    assert all('0.50 ч' in '\n'.join(p['lines']) for p in result['sleep'])


def test_sleep_clips_to_visible_day_but_tooltip_retains_original_bounds():
    start=datetime(2026,10,31,22,tzinfo=UTC);end=start+timedelta(hours=8)
    result=project_chart(chart(sleep=(SleepSpan(SourceRef('sleep',1),start,end,end.date()),)))
    assert result['sleep'][0]['value']==[0,0,6*3600]
    assert '2026-10-31 22:00:00' in '\n'.join(result['sleep'][0]['lines'])
    assert '8.00 ч' in '\n'.join(result['sleep'][0]['lines'])


def test_calendar_events_have_no_time_or_coordinate_and_preserve_explicit_no():
    events=(CalendarEvent(date(2026,11,1),SourceRef('meals',1)),
            CalendarEvent(date(2026,11,1),SourceRef('gym',2),False))
    result=project_chart(chart(events=events))
    assert len(result['events'])==2
    assert result['events'][1]['text']=='Спортзал: Не был'
    assert all(not any(key in event for key in ('time','value','x','utc_moment')) for event in result['events'])


def test_null_is_not_given_a_numeric_y_and_zero_is_retained():
    a=datetime(2026,11,1,12,tzinfo=UTC)
    result=project_chart(chart([sample(a,0),sample(a+timedelta(hours=1),None,2)]))
    assert [p['value'][1] for p in result['series'][0]['points']]==[0,None]
    assert len(result['nonnumeric'])==1 and not result['empty']
    assert result['series'][0]['segments']==[]


def test_skipped_calendar_date_has_no_real_duration():
    zone=ZoneInfo('Pacific/Apia')
    assert day_start(date(2011,12,30),zone)==day_start(date(2011,12,31),zone)


def test_javascript_contains_no_time_statistics_or_special_answer_interpretation():
    from pathlib import Path
    import re
    root = Path(__file__).resolve().parents[2] / 'src/healthtracker/resources/chart'
    for name in ('chart.js','chart_render.js'):
        code=(root/name).read_text()
        assert not re.search(r'\bmedian\b|\bmean\b|\bnew\s+Date\b|Date\.parse|\.reduce\s*\(|\.sort\s*\(', code)
        assert 'innerHTML' not in code and 'not_engaged' not in code and 'cannot_assess' not in code
