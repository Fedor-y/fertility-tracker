"""Подготовка полной страницы из одного снимка, включая сравниваемые периоды."""
from dataclasses import dataclass, replace
import json

from healthtracker.application.analytics import JOURNALS
from healthtracker.application.analytics_view import AnalyticsView, factor_projection, make_view
from healthtracker.application.charts import ChartPreparation, ChartQuery, ChartResult
from healthtracker.application.chart_serialization import PreparedChartData
from healthtracker.domain.analytics import Indicator, PeriodComparison, PeriodStatistics, compare_periods, period_statistics
from healthtracker.domain.charts import ChartMode
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.periods import ComparisonPeriod, DateRange, PeriodPair, comparison_periods
from healthtracker.domain.time import local_date


@dataclass(frozen=True, slots=True)
class AnalyticsQuery(ChartQuery):
    comparison_kind: ComparisonPeriod | None = None
    comparison_ranges: PeriodPair | None = None

    def __post_init__(self):
        ChartQuery.__post_init__(self)
        if (self.comparison_kind is not None and not isinstance(self.comparison_kind,ComparisonPeriod)
                or self.comparison_ranges is not None and not isinstance(self.comparison_ranges,PeriodPair)
                or self.comparison_kind is not None and self.comparison_ranges is not None):
            raise DomainValidationError('Недопустимое сравнение периодов.')
        if self.comparison_ranges is not None and any(not isinstance(p,DateRange)
                for p in (self.comparison_ranges.first,self.comparison_ranges.second)):
            raise DomainValidationError('Нужны два календарных диапазона.')


@dataclass(frozen=True, slots=True)
class AnalyticsPageResult(ChartResult):
    statistics: tuple[PeriodStatistics, ...] = ()
    comparison: PeriodComparison | None = None
    page_view: AnalyticsView | None = None


def select_period(snapshot, period):
    def day(kind,record):
        value=record.value
        if kind in ('meals','gym'):
            return value.entry_date
        return local_date(value.interval.end if kind in ('cognitive','sleep') else value.observed_at,snapshot.context.zone)
    return replace(snapshot,period=period,**{kind:tuple(r for r in getattr(snapshot,kind) if period.contains(day(kind,r)))
                                             for kind in JOURNALS})


class AnalyticsPagePreparation(ChartPreparation):
    def prepare(self, query, checkpoint=lambda:None, snapshot_ready=lambda token:None):
        if not isinstance(query,AnalyticsQuery):
            raise DomainValidationError('Нужен запрос страницы аналитики.')
        checkpoint()
        pair = (comparison_periods(query.comparison_kind,query.context.today)
                if query.comparison_kind is not None else query.comparison_ranges)
        periods=(query.period,) if pair is None else (query.period,pair.first,pair.second)
        bounds=DateRange(min(p.start for p in periods),max(p.end for p in periods))
        snapshot=self.analytics.load(bounds,query.context)
        snapshot_ready(snapshot.token)
        checkpoint()  # Соединение закрыто до всех расчётов и подготовки представления.
        selected=select_period(snapshot,query.period)
        chart=self.prepare_snapshot(query,selected,checkpoint,mode=ChartMode.DAILY,serialize=False)
        data=selected.data
        statistics=tuple(chart.analytics.statistics if indicator is query.indicator
                         else period_statistics(data,indicator,query.period,query.context) for indicator in Indicator)
        checkpoint()
        comparison=(compare_periods(snapshot.data,query.indicator,pair.first,pair.second,query.context) if pair else None)
        view=make_view(selected,chart.analytics,statistics,comparison,checkpoint)
        projection=json.loads(chart.projection_json)
        projection['factors']=factor_projection(chart.analytics)
        checkpoint()
        projection_json=json.dumps(projection,ensure_ascii=False,allow_nan=False)
        prepared_data=PreparedChartData.prepare(chart.chart,projection_json)
        checkpoint()
        return AnalyticsPageResult(query,chart.token,chart.chart,chart.analytics,projection_json,
            chart.summary_text,prepared_data,statistics,comparison,view)
