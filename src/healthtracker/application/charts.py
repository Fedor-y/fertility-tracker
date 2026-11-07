"""Подготовка типизированного графика по одному прежнему снимку аналитики."""
from dataclasses import dataclass
import json

from healthtracker.application.chart_projection import project_chart
from healthtracker.application.chart_serialization import PreparedChartData

from healthtracker.application.analytics import Analytics, AnalyticsResult, calculate_snapshot
from healthtracker.application.storage import SnapshotToken
from healthtracker.domain.analytics import AnalysisContext, Indicator, daily_statistics
from healthtracker.domain.charts import (
    CalendarEvent, ChartSample, DefinitionRef, PreparedChart, SeriesKind,
    SleepSpan, SourceRef, chart_mode, prepare_series, validate_line_gap,
)
from healthtracker.domain.cognitive import cognitive_index
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.periods import DateRange
from healthtracker.domain.time import local_date


@dataclass(frozen=True, slots=True)
class ChartQuery:
    period: DateRange
    context: AnalysisContext
    indicator: Indicator = Indicator.COGNITIVE
    visible_series: tuple[SeriesKind, ...] = (SeriesKind.COGNITIVE, SeriesKind.PHYSICAL)
    compact: bool = True
    line_gap_hours: float = 3
    show_sleep: bool = True
    show_meals: bool = True
    show_gym: bool = True
    show_events: bool = True

    def __post_init__(self):
        if not isinstance(self.period, DateRange) or not isinstance(self.context, AnalysisContext) or not isinstance(self.indicator, Indicator):
            raise DomainValidationError("Нужны диапазон, контекст и известный показатель.")
        if type(self.visible_series) is not tuple or any(not isinstance(s, SeriesKind) for s in self.visible_series) or len(set(self.visible_series)) != len(self.visible_series):
            raise DomainValidationError("Нужен неизменяемый набор уникальных рядов.")
        if type(self.compact) is not bool:
            raise DomainValidationError("Недопустимы режим или порог соединения точек.")
        validate_line_gap(self.line_gap_hours)
        if any(type(v) is not bool for v in (self.show_sleep, self.show_meals, self.show_gym, self.show_events)):
            raise DomainValidationError("Слои графика задаются явными переключателями.")


@dataclass(frozen=True, slots=True)
class ChartResult:
    query: ChartQuery
    token: SnapshotToken
    chart: PreparedChart
    analytics: AnalyticsResult
    projection_json: str | None = None
    summary_text: str = ''
    prepared_data: PreparedChartData | None = None


def source_ref(kind, record):
    value = record.value
    answers = ()
    if kind == 'cognitive':
        assessment = value.assessment
        definitions = tuple(DefinitionRef(code, getattr(assessment, code+'_scale_version'))
                            for code in ('learning','application','speed'))
        definitions += (DefinitionRef('cognitive_index', assessment.formula_version),)
        answers = (assessment.learning, assessment.application, assessment.speed)
    elif kind in ('physical','mood','stress'):
        definitions = (DefinitionRef(kind, value.scale_version),)
    elif kind == 'gym' and value.attended:
        definitions = (DefinitionRef('gym_difficulty', value.difficulty_scale_version),)
    else:
        definitions = ()
    return SourceRef(kind, record.id, definitions, answers)


class ChartPreparation:
    def __init__(self, analytics: Analytics):
        self.analytics = analytics

    def prepare(self, query: ChartQuery, checkpoint=lambda:None, snapshot_ready=lambda token:None) -> ChartResult:
        """Весь метод вызывается рабочим потоком; checkpoint только отменяет задачу."""
        checkpoint()
        snapshot = self.analytics.load(query.period, query.context)
        snapshot_ready(snapshot.token)
        checkpoint()  # Читающая сессия и соединение уже закрыты.
        return self.prepare_snapshot(query, snapshot, checkpoint)

    def prepare_snapshot(self, query, snapshot, checkpoint=lambda:None, *, mode=None, serialize=True):
        """То же представление из уже закрытого снимка, без повторного SQL."""
        from healthtracker.application.analytics_view import brief_statistics
        analytics = calculate_snapshot(snapshot, query.indicator)
        checkpoint()
        data = snapshot.data
        mode = mode or chart_mode(query.period, query.compact)
        series = []
        for kind in query.visible_series:
            samples = []
            for record in getattr(snapshot, kind.source_kind):
                value = record.value
                if kind.source_kind == 'cognitive':
                    number = (cognitive_index(value.assessment) if kind is SeriesKind.COGNITIVE
                              else getattr(value.assessment, kind.value).value)
                    moment, start = value.interval.end, value.interval.start
                else:
                    moment, number, start = value.observed_at, value.score, None
                samples.append(ChartSample(source_ref(kind.source_kind, record), moment, number, start))
            daily = (() if kind is SeriesKind.STRESS else
                     daily_statistics(data, Indicator(kind.value), query.period, query.context))
            series.append(prepare_series(kind, tuple(samples), query.period, query.context, mode, query.line_gap_hours, daily))
            checkpoint()
        events = tuple(sorted((CalendarEvent(record.value.entry_date, source_ref(kind, record),
                       record.value.attended if kind == 'gym' else None,
                       record.value.difficulty if kind == 'gym' else None)
                       for kind in ('meals','gym') if getattr(query, 'show_'+kind) for record in getattr(snapshot, kind)),
                       key=lambda e:(e.day, e.source.kind == 'gym', e.source.record_id)))
        sleep = tuple(SleepSpan(source_ref('sleep', record), record.value.interval.start, record.value.interval.end,
                                local_date(record.value.interval.end, query.context.zone)) for record in snapshot.sleep if query.show_sleep)
        chart = PreparedChart(query.period, query.context, mode, query.line_gap_hours, tuple(series), events, sleep)
        checkpoint()
        projection_json = json.dumps(project_chart(chart, show_events=query.show_events), ensure_ascii=False, allow_nan=False)
        checkpoint()
        prepared_data=PreparedChartData.prepare(chart,projection_json) if serialize else None
        checkpoint()
        return ChartResult(query, snapshot.token, chart, analytics, projection_json,
                           brief_statistics(analytics.statistics),prepared_data)
