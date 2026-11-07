from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from healthtracker.domain.analytics import AnalysisContext, DailyStatistics
from healthtracker.domain.charts import (
    CalendarEvent, ChartMode, ChartPoint, ChartSample, ChartSegment, ChartSeries,
    DefinitionRef, PreparedChart, SeriesKind, SleepSpan, SourceRef, chart_mode, prepare_series,
)
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.periods import DateRange

NOW=datetime(2026,11,4,12,tzinfo=UTC)
CONTEXT=AnalysisContext(NOW,UTC)
DAY=date(2026,11,1)
START=datetime(2026,11,1,8,tzinfo=UTC)
PERIOD=DateRange(DAY,DAY)
REF=SourceRef('cognitive',1,(DefinitionRef('learning',1),DefinitionRef('cognitive_index',1)))


def sample(hours=0, value=7, record_id=1, kind='cognitive'):
    return ChartSample(replace(REF,kind=kind,record_id=record_id),START+timedelta(hours=hours),value)


def prepare(samples,mode=ChartMode.DAY,kind=SeriesKind.COGNITIVE,period=PERIOD,context=CONTEXT,gap=3,daily=()):
    return prepare_series(kind,tuple(samples),period,context,mode,gap,daily)


@pytest.mark.parametrize('days,compact,expected',[(1,True,ChartMode.DAY),(1,False,ChartMode.DAY),
    (2,True,ChartMode.COMPACT),(2,False,ChartMode.TIMELINE),(7,True,ChartMode.COMPACT),
    (7,False,ChartMode.TIMELINE),(8,True,ChartMode.DAILY),(8,False,ChartMode.DAILY)])
def test_chart01_mode_boundaries(days,compact,expected):
    assert chart_mode(DateRange(DAY,DAY+timedelta(days=days-1)),compact) is expected


@pytest.mark.parametrize('gap,threshold,connected',[(3,3,True),(3+1/3600,3,False),(2,2,True),(2.1,2,False)])
def test_chart02_elapsed_gap_boundary(gap,threshold,connected):
    result=prepare((sample(0,0,1),sample(gap,10,2)),gap=threshold)
    assert [p.value for p in result.points]==[0,10]
    assert tuple(s.indices for s in result.segments)==(((0,1),) if connected else ())


@pytest.mark.parametrize('values',[(1,None,9),(1,None,None,9),(None,),()])
def test_chart03_special_answers_break_without_filling_or_dropping_sources(values):
    result=prepare(tuple(sample(i,value,i+1) for i,value in enumerate(values)))
    assert result.segments==()
    assert tuple(p.value for p in result.points)==values
    assert tuple(p.sources[0].record_id for p in result.points)==tuple(range(1,len(values)+1))


def test_chart02_midnight_break_even_in_continuous_timeline():
    samples=(ChartSample(REF,datetime(2026,11,1,23,tzinfo=UTC),6),
             ChartSample(replace(REF,record_id=2),datetime(2026,11,2,0,tzinfo=UTC),7))
    result=prepare(samples,mode=ChartMode.TIMELINE,period=DateRange(DAY,DAY+timedelta(days=1)))
    assert result.segments==() and [p.day for p in result.points]==[DAY,DAY+timedelta(days=1)]


def test_chart04_duplicates_break_connections_to_both_neighbors_without_averaging():
    result=prepare((sample(0,1,1),sample(1,2,2),sample(1,8,3),sample(2,4,4),sample(3,5,5)))
    assert [p.value for p in result.points]==[1,2,8,4,5]
    assert result.points[1].utc_moment==result.points[2].utc_moment
    assert tuple(s.indices for s in result.segments)==((3,4),)
    assert result.points[1].sources[0].record_id==2 and result.points[2].sources[0].record_id==3


@pytest.mark.parametrize('mode,connect',[(ChartMode.COMPACT,False),(ChartMode.TIMELINE,True),(ChartMode.DAY,True)])
def test_chart05_rollback_breaks_compact_even_if_local_clock_increases(mode,connect):
    day=date(2026,10,25)
    moments=(datetime(2026,10,25,0,10,tzinfo=UTC),datetime(2026,10,25,1,50,tzinfo=UTC))
    result=prepare(tuple(ChartSample(replace(REF,record_id=i+1),m,v) for i,(m,v) in enumerate(zip(moments,(2,8)))),
        mode=mode,period=DateRange(day,day),context=AnalysisContext(NOW,ZoneInfo('Europe/Berlin')))
    assert [p.local_moment.strftime('%H:%M %z') for p in result.points]==['02:10 +0200','02:50 +0100']
    assert bool(result.segments)==connect
    assert tuple(p.utc_moment for p in result.points)==moments


def test_chart05_repeated_hour_points_have_distinct_utc_and_offsets():
    day=date(2026,10,25)
    moments=(datetime(2026,10,25,0,30,tzinfo=UTC),datetime(2026,10,25,1,30,tzinfo=UTC))
    result=prepare(tuple(ChartSample(replace(REF,record_id=i+1),m,7) for i,m in enumerate(reversed(moments))),
        mode=ChartMode.COMPACT,period=DateRange(day,day),context=AnalysisContext(NOW,ZoneInfo('Europe/Berlin')))
    assert tuple(p.utc_moment for p in result.points)==moments
    assert [p.local_moment.hour for p in result.points]==[2,2]
    assert [p.local_moment.fold for p in result.points]==[0,1]
    assert result.segments==()


def test_dst_spring_gap_is_not_filled_and_elapsed_hour_can_connect():
    day=date(2026,3,29)
    moments=(datetime(2026,3,29,0,30,tzinfo=UTC),datetime(2026,3,29,1,30,tzinfo=UTC))
    result=prepare(tuple(ChartSample(replace(REF,record_id=i+1),m,7) for i,m in enumerate(moments)),
        mode=ChartMode.COMPACT,period=DateRange(day,day),context=AnalysisContext(NOW,ZoneInfo('Europe/Berlin')))
    assert [p.local_moment.hour for p in result.points]==[1,3]
    assert result.segments==(ChartSegment((0,1)),) and len(result.points)==2


def test_chart03_daily_points_connect_only_neighboring_calendar_dates_and_keep_all_ids():
    samples=(sample(0,2,1),sample(0,8,2),sample(24,6,3),sample(48,None,4),sample(72,8,5))
    daily=(DailyStatistics(DAY,5,2,8,2),DailyStatistics(DAY+timedelta(days=1),6,6,6,1),DailyStatistics(DAY+timedelta(days=3),8,8,8,1))
    result=prepare(samples,mode=ChartMode.DAILY,period=DateRange(DAY,DAY+timedelta(days=7)),daily=daily)
    assert [p.value for p in result.points]==[5,6,8]
    assert [s.indices for s in result.segments]==[(0,1)]
    assert [s.record_id for s in result.points[0].sources]==[1,2]
    assert result.points[0].measurements==2 and result.points[0].minimum==2 and result.points[0].maximum==8
    assert all(p.utc_moment is None and p.local_moment is None for p in result.points)


@pytest.mark.parametrize('mode',list(ChartMode))
def test_stress_always_has_individual_markers_including_zero_and_no_segments(mode):
    result=prepare((sample(0,0,1,'stress'),sample(1,7,2,'stress')),kind=SeriesKind.STRESS,mode=mode)
    assert [p.value for p in result.points]==[0,7] and result.segments==()
    assert all(p.utc_moment is not None and len(p.sources)==1 for p in result.points)


def test_out_of_range_and_future_points_are_not_manufactured():
    result=prepare((sample(-24),sample(96,record_id=2)))
    assert result.points==() and result.segments==()


@pytest.mark.parametrize('factory',[
    lambda:DefinitionRef('',1),lambda:DefinitionRef('learning',True),lambda:SourceRef('mood',0),
    lambda:SourceRef('mood',1,[]),lambda:ChartSample(REF,START,float('nan')),
    lambda:ChartSample(REF,START,True),lambda:ChartSegment((0,)),
    lambda:ChartSegment([0,1]),lambda:ChartSeries(SeriesKind.COGNITIVE,[],()),
    lambda:CalendarEvent(DAY,REF),lambda:SleepSpan(SourceRef('sleep',1),START,START,DAY),
    lambda:PreparedChart(PERIOD,CONTEXT,ChartMode.DAY,3,[],(),()),
])
def test_models_reject_invalid_or_mutable_data(factory):
    with pytest.raises(DomainValidationError): factory()


def test_all_chart_models_are_frozen_and_keep_definition_versions():
    point=prepare((sample(),)).points[0]
    models=(REF.definitions[0],REF,sample(),point,ChartSegment((0,1)),prepare((sample(),)),
        CalendarEvent(DAY,SourceRef('gym',1)),SleepSpan(SourceRef('sleep',1),START-timedelta(hours=8),START,DAY),
        PreparedChart(PERIOD,CONTEXT,ChartMode.DAY,3,(),(),()))
    for model in models:
        field=next(iter(model.__dataclass_fields__))
        with pytest.raises(FrozenInstanceError): setattr(model,field,None)
    assert point.sources[0].definitions==REF.definitions


@pytest.mark.parametrize('gap',[0,-1,True,float('inf'),float('nan')])
def test_invalid_line_thresholds_cannot_enter_prepared_data(gap):
    with pytest.raises(DomainValidationError): prepare((sample(),),gap=gap)
    with pytest.raises(DomainValidationError): PreparedChart(PERIOD,CONTEXT,ChartMode.DAY,gap,(),(),())


def test_series_cannot_forge_stress_lines_or_unbacked_daily_statistics():
    points=prepare((sample(0,0,1,'stress'),sample(1,7,2,'stress')),kind=SeriesKind.STRESS).points
    with pytest.raises(DomainValidationError): ChartSeries(SeriesKind.STRESS,points,(ChartSegment((0,1)),))
    with pytest.raises(DomainValidationError):
        prepare((),mode=ChartMode.DAILY,daily=(DailyStatistics(DAY,5,5,5,1),))
    with pytest.raises(DomainValidationError): ChartSegment((1,1))
