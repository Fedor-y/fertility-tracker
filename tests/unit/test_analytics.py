from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from healthtracker.domain.analytics import (
    AnalyticsData, AnalysisContext, Indicator, daily_statistics, period_statistics, compare_periods,
)
from healthtracker.domain.answers import AnswerStatus, CognitiveAnswer
from healthtracker.domain.cognitive import CognitiveAssessment
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.intervals import CognitiveInterval
from healthtracker.domain.measurement import CognitiveMeasurement
from healthtracker.domain.periods import DateRange, QuickPeriod, quick_period
from healthtracker.domain.records import MoodRecord, PhysicalRecord
from healthtracker.domain.catalogs import SymptomStatus

NOW = datetime(2026,11,4,12,tzinfo=UTC)
DAY = date(2026,11,1)
PERIOD = DateRange(DAY,DAY)
CONTEXT = AnalysisContext(NOW,UTC)


def cognitive(values, moment=None):
    answers = tuple(CognitiveAnswer.numeric(v) if type(v) is int else CognitiveAnswer(v) for v in values)
    return CognitiveMeasurement(CognitiveAssessment(*answers),
        CognitiveInterval(moment or datetime(2026,11,1,12,tzinfo=UTC), now=NOW+timedelta(days=365)), NOW,NOW)


@pytest.mark.parametrize('values,expected', [
    ((),()), ((0,), (0,0,0,1)), ((10,), (10,10,10,1)),
    ((2,4,8,10),(6,2,10,4)), ((0,0,10),(0,0,10,3)), ((1,2),(1.5,1,2,2)),
])
def test_daily_numeric_medians_and_extrema(values,expected):
    data=AnalyticsData(cognitive=tuple(cognitive((v,v,v)) for v in values))
    result=daily_statistics(data,Indicator.COGNITIVE,PERIOD,CONTEXT)
    if not expected: assert result == ()
    else:
        day=result[0]
        assert (day.median,day.minimum,day.maximum,day.measurements)==expected
        assert day.day==DAY


@pytest.mark.parametrize('indicator',list(Indicator)[:4])
@pytest.mark.parametrize('status',[AnswerStatus.NOT_ENGAGED,AnswerStatus.CANNOT_ASSESS])
def test_components_independent_from_missing_index(indicator,status):
    rows=(cognitive((0,status,10)), cognitive((status,2,4)))
    result=daily_statistics(AnalyticsData(cognitive=rows),indicator,PERIOD,CONTEXT)
    expected={Indicator.COGNITIVE:None,Indicator.LEARNING:0,Indicator.APPLICATION:2,Indicator.SPEED:7}[indicator]
    assert (result[0].median if result else None)==expected
    if result: assert result[0].measurements==(2 if indicator is Indicator.SPEED else 1)


def test_index_precision_is_not_rounded_before_median():
    rows=(cognitive((0,0,1)),cognitive((0,0,2)),cognitive((0,0,2)))
    result=daily_statistics(AnalyticsData(cognitive=rows),Indicator.COGNITIVE,PERIOD,CONTEXT)[0]
    assert result.median==pytest.approx(2/3) and result.median!=0.67


@pytest.mark.parametrize('indicator,model',[ (Indicator.PHYSICAL,PhysicalRecord),(Indicator.MOOD,MoodRecord)])
@pytest.mark.parametrize('score',[0,10])
def test_physical_mood_independent_scores(indicator,model,score):
    kwargs=dict(observed_at=datetime(2026,11,1,1,tzinfo=UTC),score=score,created_at=NOW,updated_at=NOW)
    if model is PhysicalRecord: kwargs.update(symptom_status=SymptomStatus.UNKNOWN)
    data=AnalyticsData(**{indicator.value:(model(**kwargs),)})
    result=daily_statistics(data,indicator,PERIOD,CONTEXT)
    assert result[0].median==score and result[0].measurements==1
    other=Indicator.MOOD if indicator is Indicator.PHYSICAL else Indicator.PHYSICAL
    assert daily_statistics(data,other,PERIOD,CONTEXT)==()


def test_utc_midnight_timezone_grouping_and_future_values():
    rows=(cognitive((0,0,0),datetime(2026,11,1,0,30,tzinfo=UTC)),
          cognitive((10,10,10),NOW+timedelta(seconds=1)))
    data=AnalyticsData(cognitive=rows)
    result=daily_statistics(data,Indicator.COGNITIVE,DateRange(date(2026,10,31),date(2026,11,5)),
                            AnalysisContext(NOW,ZoneInfo('America/New_York')))
    assert [(d.day,d.median) for d in result]==[(date(2026,10,31),0)]


@pytest.mark.parametrize('month,day,hours',[(3,29,(0,1)),(10,25,(0,1))])
def test_dst_uses_real_moments_for_daily_grouping(month,day,hours):
    rows=tuple(cognitive((v,v,v),datetime(2026,month,day,h,tzinfo=UTC)) for v,h in zip((2,8),hours))
    result=daily_statistics(AnalyticsData(cognitive=rows),Indicator.COGNITIVE,
        DateRange(date(2026,month,day),date(2026,month,day)),AnalysisContext(NOW,ZoneInfo('Europe/Berlin')))
    assert result[0].median==5 and result[0].measurements==2


def test_immutable_typed_inputs_and_invalid_indicator():
    with pytest.raises(DomainValidationError): AnalyticsData(cognitive=[])
    with pytest.raises(DomainValidationError): AnalyticsData(cognitive=(object(),))
    with pytest.raises(FrozenInstanceError): CONTEXT.now=NOW
    with pytest.raises(DomainValidationError): daily_statistics(AnalyticsData(),'stress',PERIOD,CONTEXT)
    with pytest.raises(DomainValidationError): AnalysisContext(datetime(2026,1,1),UTC)


def across_days(values, start=date(2026,10,1)):
    return AnalyticsData(cognitive=tuple(cognitive((v,v,v),datetime.combine(start+timedelta(days=i),
        datetime.min.time(),UTC)+timedelta(hours=12)) for i,v in enumerate(values)))


@pytest.mark.parametrize('count',[0,1,6,7,8])
def test_summary_threshold_coverage_and_counts(count):
    period=DateRange(date(2026,10,1),date(2026,10,14))
    result=period_statistics(across_days([0]*count),Indicator.COGNITIVE,period,CONTEXT)
    assert result.observed_days==count and result.measurements==count
    assert result.calendar_days==14
    assert result.coverage_percent==pytest.approx(count*100/14)
    assert (result.summary is not None)==(count>=7)
    if count>=7: assert result.summary.median==result.summary.mean==0


def test_days_have_equal_weight_and_extrema_keep_all_dates():
    # 100 нулевых измерений первого дня имеют вес одного дня.
    data=across_days([2,4,6,6,8,8,8])
    zeros=tuple(cognitive((0,0,0),datetime(2026,10,1,13,tzinfo=UTC)) for _ in range(100))
    data=AnalyticsData(cognitive=data.cognitive+zeros)
    result=period_statistics(data,Indicator.COGNITIVE,DateRange(date(2026,10,1),date(2026,10,7)),CONTEXT)
    assert result.summary.median==6
    assert result.summary.mean==pytest.approx(40/7)
    assert result.summary.minimum==0 and result.summary.maximum==8
    assert result.summary.minimum_dates==(date(2026,10,1),)
    assert result.summary.maximum_dates==(date(2026,10,5),date(2026,10,6),date(2026,10,7))
    assert result.measurements==107 and result.observed_days==7


def test_normative_seven_days_example_and_no_summary_for_six():
    data=across_days([2,4,6,6,8,8,8])
    result=period_statistics(data,Indicator.COGNITIVE,DateRange(date(2026,10,1),date(2026,10,7)),CONTEXT)
    assert result.summary.median==6 and result.summary.mean==6
    assert result.summary.minimum==2 and result.summary.maximum==8
    assert period_statistics(data,Indicator.COGNITIVE,DateRange(date(2026,10,1),date(2026,10,6)),CONTEXT).summary is None


def test_sparse_component_coverage_differs_from_index_without_synthetic_days():
    data=AnalyticsData(cognitive=(cognitive((0,AnswerStatus.NOT_ENGAGED,10)),))
    period=DateRange(date(2026,11,1),date(2026,11,30))
    index=period_statistics(data,Indicator.COGNITIVE,period,CONTEXT)
    component=period_statistics(data,Indicator.LEARNING,period,CONTEXT)
    assert index.daily==() and index.coverage_percent==0
    assert component.observed_days==1 and component.measurements==1
    assert component.coverage_percent==pytest.approx(100/30)
    assert component.calendar_days==30 and component.incomplete
    assert len(component.daily)==1 and component.daily[0].median==0


@pytest.mark.parametrize('indicator',list(Indicator))
def test_completely_empty_period_has_no_extrema_or_fabricated_summary(indicator):
    result=period_statistics(AnalyticsData(),indicator,DateRange(date(2026,1,1),date(2026,12,31)),CONTEXT)
    assert result.summary is None and result.daily==()
    assert result.coverage_percent==0 and result.observed_days==result.measurements==0
    assert result.calendar_days==365 and result.incomplete


def test_future_only_and_current_day_are_incomplete_without_future_observations():
    data=AnalyticsData(cognitive=(cognitive((10,10,10),NOW+timedelta(seconds=1)),))
    for period in (DateRange(NOW.date(),NOW.date()), DateRange(date(2026,12,1),date(2026,12,31))):
        result=period_statistics(data,Indicator.COGNITIVE,period,CONTEXT)
        assert result.incomplete and result.daily==() and result.summary is None
    assert not period_statistics(data,Indicator.COGNITIVE,PERIOD,CONTEXT).incomplete


@pytest.mark.parametrize('left_count,right_count,expected',[(6,7,None),(7,6,None),(7,7,-6),(8,7,-6),(0,0,None)])
def test_comparison_requires_both_seven_day_thresholds(left_count,right_count,expected):
    left=across_days([2]*left_count,date(2026,10,1))
    right=across_days([8]*right_count,date(2026,9,1))
    result=compare_periods(AnalyticsData(cognitive=left.cognitive+right.cognitive),Indicator.COGNITIVE,
        DateRange(date(2026,10,1),date(2026,10,14)),DateRange(date(2026,9,1),date(2026,9,7)),CONTEXT)
    assert result.difference==expected
    assert result.first.calendar_days==14 and result.second.calendar_days==7
    assert result.first.observed_days==left_count and result.second.observed_days==right_count


@pytest.mark.parametrize('kind,total',[(QuickPeriod.MONTH,30),(QuickPeriod.YEAR,365)])
def test_full_current_calendar_period_keeps_future_dates_in_denominator(kind,total):
    period=quick_period(kind,CONTEXT.today)
    result=period_statistics(across_days([0,2,4],date(2026,11,1)),Indicator.COGNITIVE,period,CONTEXT)
    assert result.calendar_days==total and result.coverage_percent==pytest.approx(300/total)
    assert result.incomplete and result.observed_days==3


def test_zero_difference_is_a_value_not_missing():
    data=across_days([0]*14)
    result=compare_periods(data,Indicator.COGNITIVE,DateRange(date(2026,10,1),date(2026,10,7)),
                          DateRange(date(2026,10,8),date(2026,10,14)),CONTEXT)
    assert result.difference==0 and result.first.summary is not None


@pytest.mark.parametrize('indicator',list(Indicator))
@pytest.mark.parametrize('values,expected_median,expected_mean',[
    ([0]*7,0,0),([10]*7,10,10),([2,4,6,6,8,8,8],6,6),
])
def test_each_indicator_summary_normal_and_scale_boundaries(indicator,values,expected_median,expected_mean):
    cognitive_rows=across_days(values).cognitive
    kwargs={}
    for name,model in (('physical',PhysicalRecord),('mood',MoodRecord)):
        kwargs[name]=tuple(model(observed_at=row.interval.end,score=value,created_at=NOW,updated_at=NOW,
            **({'symptom_status':SymptomStatus.UNKNOWN} if name=='physical' else {}))
            for row,value in zip(cognitive_rows,values))
    result=period_statistics(AnalyticsData(cognitive=cognitive_rows,**kwargs),indicator,
        DateRange(date(2026,10,1),date(2026,10,7)),CONTEXT)
    assert result.summary.median==expected_median and result.summary.mean==expected_mean
    assert result.summary.minimum==min(values) and result.summary.maximum==max(values)
    assert result.observed_days==result.measurements==7 and result.coverage_percent==100
    if values==[0]*7:
        dates=tuple(date(2026,10,n) for n in range(1,8))
        assert result.summary.minimum_dates==result.summary.maximum_dates==dates


def test_period_extrema_are_daily_medians_not_raw_measurement_extrema():
    rest=across_days([6]*6,date(2026,10,2))
    first=datetime(2026,10,1,12,tzinfo=UTC)
    data=AnalyticsData(cognitive=(cognitive((0,0,0),first),cognitive((10,10,10),first))+rest.cognitive)
    result=period_statistics(data,Indicator.COGNITIVE,DateRange(date(2026,10,1),date(2026,10,7)),CONTEXT)
    assert (result.daily[0].median,result.daily[0].minimum,result.daily[0].maximum)==(5,0,10)
    assert (result.summary.minimum,result.summary.maximum,result.summary.median)==(5,6,6)
    assert result.summary.mean==pytest.approx(41/7)


def test_leap_year_future_dates_remain_in_full_year_coverage():
    context=AnalysisContext(datetime(2024,2,29,12,tzinfo=UTC),UTC)
    data=AnalyticsData(cognitive=(cognitive((0,0,0),context.now),))
    result=period_statistics(data,Indicator.COGNITIVE,quick_period(QuickPeriod.YEAR,context.today),context)
    assert result.calendar_days==366 and result.observed_days==1
    assert result.coverage_percent==pytest.approx(100/366) and result.incomplete


def test_quick_today_uses_the_same_timezone_as_aggregation():
    context=AnalysisContext(datetime(2026,11,4,0,30,tzinfo=UTC),ZoneInfo('America/New_York'))
    assert quick_period(QuickPeriod.DAY,context.today)==DateRange(date(2026,11,3),date(2026,11,3))
