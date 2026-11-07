from datetime import UTC,date,datetime,timedelta
from zoneinfo import ZoneInfo

import pytest

from healthtracker.domain.analytics import AnalyticsData,AnalysisContext,Indicator,daily_statistics
from healthtracker.domain.answers import AnswerStatus,CognitiveAnswer
from healthtracker.domain.cognitive import CognitiveAssessment
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.factors import SleepExclusion,sleep_comparison,gym_comparison
from healthtracker.domain.intervals import CognitiveInterval,SleepInterval
from healthtracker.domain.measurement import CognitiveMeasurement
from healthtracker.domain.periods import DateRange
from healthtracker.domain.records import GymRecord,SleepRecord

NOW=datetime(2026,11,4,12,tzinfo=UTC)
CONTEXT=AnalysisContext(NOW,UTC)
DAY=date(2026,11,1)
WAKE=datetime(2026,11,1,8,tzinfo=UTC)
PERIOD=DateRange(DAY,DAY)
META=dict(created_at=NOW,updated_at=NOW)


def cog(value=6,end=WAKE+timedelta(hours=1),special=False):
    answers=[CognitiveAnswer.numeric(value)]*3
    if special: answers[0]=CognitiveAnswer(AnswerStatus.CANNOT_ASSESS)
    return CognitiveMeasurement(CognitiveAssessment(*answers),CognitiveInterval(end,now=NOW),NOW,NOW)


def sleep(start=WAKE-timedelta(hours=8),end=WAKE):
    return SleepRecord(interval=SleepInterval(start,end,now=NOW),**META)


def mark(day=DAY,attended=True,difficulty=5):
    return GymRecord(entry_date=day,attended=attended,difficulty=difficulty if attended else None,
                     difficulty_scale_version=1 if attended else None,**META)


@pytest.mark.parametrize('seconds,used',[(0,True),(-1,False),(1,True)])
def test_sleep_cognitive_hour_start_boundary(seconds,used):
    data=AnalyticsData(cognitive=(cog(end=WAKE+timedelta(hours=1,seconds=seconds)),),sleep=(sleep(),))
    result=sleep_comparison(data,PERIOD,CONTEXT)
    assert result.used_days==int(used) and result.excluded_days==int(not used)
    if used:
        assert result.points[0].sleep_hours==8 and result.points[0].cognitive_median==6
    else: assert result.excluded[0].reasons==(SleepExclusion.COGNITIVE_HOUR_BEFORE_WAKE,)


def test_sleep_one_early_full_hour_excludes_whole_day_without_changing_median():
    data=AnalyticsData(cognitive=(cog(0,WAKE),cog(10,WAKE+timedelta(hours=2))),sleep=(sleep(),))
    before=daily_statistics(data,Indicator.COGNITIVE,PERIOD,CONTEXT)
    result=sleep_comparison(data,PERIOD,CONTEXT)
    assert not result.points and result.excluded_days==1
    assert before[0].median==5
    assert daily_statistics(data,Indicator.COGNITIVE,PERIOD,CONTEXT)==before


def test_sleep_partial_cognitive_record_before_wake_does_not_exclude_valid_day():
    data=AnalyticsData(cognitive=(cog(0,WAKE,special=True),cog(0)),sleep=(sleep(),))
    result=sleep_comparison(data,PERIOD,CONTEXT)
    assert result.used_days==1 and result.points[0].cognitive_median==0


@pytest.mark.parametrize('data,reasons',[
    (AnalyticsData(),(SleepExclusion.NO_SLEEP,SleepExclusion.NO_COGNITIVE_MEDIAN)),
    (AnalyticsData(cognitive=(cog(),)),(SleepExclusion.NO_SLEEP,)),
    (AnalyticsData(sleep=(sleep(),)),(SleepExclusion.NO_COGNITIVE_MEDIAN,)),
    (AnalyticsData(cognitive=(cog(special=True),),sleep=(sleep(),)),(SleepExclusion.NO_COGNITIVE_MEDIAN,)),
    (AnalyticsData(cognitive=(cog(),),sleep=(sleep(end=WAKE-timedelta(hours=1)),sleep(start=WAKE-timedelta(hours=1)))),
        (SleepExclusion.MULTIPLE_SLEEP_INTERVALS,)),
    (AnalyticsData(sleep=(sleep(end=WAKE-timedelta(hours=1)),sleep(start=WAKE-timedelta(hours=1)))),
        (SleepExclusion.NO_COGNITIVE_MEDIAN,SleepExclusion.MULTIPLE_SLEEP_INTERVALS)),
])
def test_sleep_exclusions_and_overlapping_reasons_count_date_once(data,reasons):
    result=sleep_comparison(data,PERIOD,CONTEXT)
    assert result.used_days==0 and result.excluded_days==1
    assert result.excluded[0].reasons==reasons


@pytest.mark.parametrize('start,end,hours',[
    (datetime(2026,3,28,22,tzinfo=UTC),datetime(2026,3,29,6,tzinfo=UTC),8),
    (datetime(2026,10,24,22,tzinfo=UTC),datetime(2026,10,25,6,tzinfo=UTC),8),
])
def test_sleep_duration_uses_utc_through_dst_and_waking_date(start,end,hours):
    context=AnalysisContext(NOW,ZoneInfo('Europe/Berlin'))
    day=end.astimezone(context.zone).date()
    result=sleep_comparison(AnalyticsData(cognitive=(cog(end=end+timedelta(hours=1)),),sleep=(sleep(start,end),)),
        DateRange(day,day),context)
    assert result.points[0].day==day and result.points[0].sleep_hours==hours


def test_sleep_current_zone_can_change_waking_date_without_mutating_input():
    end=datetime(2026,11,1,0,30,tzinfo=UTC)
    data=AnalyticsData(cognitive=(cog(end=end+timedelta(hours=1)),),sleep=(sleep(end-timedelta(hours=8),end),))
    result=sleep_comparison(data,DateRange(date(2026,10,31),date(2026,10,31)),
                            AnalysisContext(NOW,ZoneInfo('America/New_York')))
    assert result.used_days==1 and result.points[0].day==date(2026,10,31)
    assert data.sleep[0].interval.end==end


@pytest.mark.parametrize('yes_count,no_count,warning',[(4,5,True),(5,4,True),(5,5,False),(1,1,True),(0,5,True),(5,0,True),(0,0,True)])
def test_gym_thresholds_groups_and_empty_difference(yes_count,no_count,warning):
    start=date(2026,10,1)
    rows,marks=[],[]
    for i in range(yes_count+no_count):
        day=start+timedelta(days=i)
        attended=i<yes_count
        rows.append(cog(0 if attended else 8,datetime.combine(day,datetime.min.time(),UTC)+timedelta(hours=12)))
        marks.append(mark(day,attended))
    result=gym_comparison(AnalyticsData(cognitive=tuple(rows),gym=tuple(marks)),
                           DateRange(start,date(2026,10,31)),CONTEXT)
    assert result.attended.days==yes_count and result.absent.days==no_count
    assert (result.warning is not None)==warning
    assert result.attended.median==(0 if yes_count else None)
    assert result.absent.median==(8 if no_count else None)
    assert result.difference==(-8 if yes_count and no_count else None)


def test_gym_unknown_is_not_no_and_difficulty_does_not_define_group():
    rows=(cog(2),cog(8,WAKE+timedelta(days=1,hours=1)))
    period=DateRange(DAY,DAY+timedelta(days=1))
    result=gym_comparison(AnalyticsData(cognitive=rows,gym=(mark(difficulty=0),)),period,CONTEXT)
    assert result.attended.days==1 and result.absent.days==0 and result.difference is None
    assert result.attended.points[0].difficulty==0
    assert result.excluded_dates==(DAY+timedelta(days=1),)


def test_gym_group_uses_daily_medians_and_equal_day_weight_without_seven_day_gate():
    next_day=DAY+timedelta(days=1)
    rows=(cog(0),)*20+(cog(10,WAKE+timedelta(days=1,hours=1)),cog(6,WAKE+timedelta(days=2,hours=1)))
    result=gym_comparison(AnalyticsData(cognitive=rows,gym=(mark(),mark(next_day),mark(next_day+timedelta(days=1),False))),
        DateRange(DAY,DAY+timedelta(days=2)),CONTEXT)
    assert result.attended.median==5 and result.absent.median==6 and result.difference==-1
    assert result.warning=='Мало наблюдений для сравнения'


def test_gym_no_cognitive_median_and_duplicate_marks_are_not_silently_used():
    result=gym_comparison(AnalyticsData(gym=(mark(attended=False),)),PERIOD,CONTEXT)
    assert result.attended.days==result.absent.days==0
    with pytest.raises(DomainValidationError):
        gym_comparison(AnalyticsData(gym=(mark(),mark(attended=False))),PERIOD,CONTEXT)


def test_future_factor_values_not_used_as_historical_data():
    context=AnalysisContext(WAKE-timedelta(hours=1),UTC)
    data=AnalyticsData(cognitive=(cog(),),sleep=(sleep(),),gym=(mark(DAY+timedelta(days=1)),))
    assert sleep_comparison(data,PERIOD,context).points==()
    assert gym_comparison(data,PERIOD,context).attended.days==0


def test_sleep_fractional_hours_are_not_rounded():
    result=sleep_comparison(AnalyticsData(cognitive=(cog(),),sleep=(sleep(WAKE-timedelta(seconds=25644)),)),PERIOD,CONTEXT)
    assert result.points[0].sleep_hours==pytest.approx(7.123333333333333)
    assert result.points[0].sleep_hours!=7.12


def test_gym_mark_date_does_not_move_when_timezone_moves_cognitive_record():
    data=AnalyticsData(cognitive=(cog(end=datetime(2026,11,1,12,tzinfo=UTC)),),gym=(mark(),))
    assert gym_comparison(data,PERIOD,CONTEXT).attended.days==1
    moved=gym_comparison(data,DateRange(DAY,DAY+timedelta(days=1)),AnalysisContext(NOW,ZoneInfo('Pacific/Kiritimati')))
    assert moved.attended.days==moved.absent.days==0
    assert data.gym[0].entry_date==DAY
