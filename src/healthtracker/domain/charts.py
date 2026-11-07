"""Неизменяемые данные графиков и сегментация. Без Qt, SQL и ECharts."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from itertools import groupby
import math

from healthtracker.domain.analytics import AnalysisContext, DailyStatistics
from healthtracker.domain.answers import CognitiveAnswer
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.periods import DateRange
from healthtracker.domain.time import as_utc, local_date


class SeriesKind(StrEnum):
    COGNITIVE = "cognitive"
    LEARNING = "learning"
    APPLICATION = "application"
    SPEED = "speed"
    PHYSICAL = "physical"
    MOOD = "mood"
    STRESS = "stress"


    @property
    def source_kind(self):
        return 'cognitive' if self in (self.LEARNING, self.APPLICATION, self.SPEED) else self.value


class ChartMode(StrEnum):
    DAY = "day"
    COMPACT = "compact"
    TIMELINE = "timeline"
    DAILY = "daily"


def chart_mode(period: DateRange, compact: bool) -> ChartMode:
    if not isinstance(period, DateRange) or type(compact) is not bool:
        raise DomainValidationError("Необходимы календарный диапазон и выбранный режим.")
    if period.calendar_days == 1:
        return ChartMode.DAY
    if period.calendar_days > 7:
        return ChartMode.DAILY
    return ChartMode.COMPACT if compact else ChartMode.TIMELINE


def _tuple(values, model):
    if type(values) is not tuple or any(not isinstance(value, model) for value in values):
        raise DomainValidationError("Необходим неизменяемый типизированный набор графика.")


def validate_line_gap(hours):
    if type(hours) not in (int, float) or not math.isfinite(hours) or hours <= 0:
        raise DomainValidationError("Порог линий должен быть положительным конечным числом.")


@dataclass(frozen=True, slots=True)
class DefinitionRef:
    code: str
    version: int

    def __post_init__(self):
        if type(self.code) is not str or not self.code or type(self.version) is not int or self.version < 1:
            raise DomainValidationError("Необходима определённая версия шкалы/формулы.")


@dataclass(frozen=True, slots=True)
class SourceRef:
    kind: str
    record_id: int
    definitions: tuple[DefinitionRef, ...] = ()
    cognitive_answers: tuple[CognitiveAnswer, ...] = ()

    def __post_init__(self):
        if self.kind not in ("cognitive", "physical", "mood", "stress", "sleep", "meals", "gym") or type(self.record_id) is not int or self.record_id < 1:
            raise DomainValidationError("Необходимы тип и ID исходной записи.")
        _tuple(self.definitions, DefinitionRef)
        _tuple(self.cognitive_answers, CognitiveAnswer)
        if self.cognitive_answers and (self.kind != 'cognitive' or len(self.cognitive_answers) != 3):
            raise DomainValidationError("Исходная когнитивная оценка содержит три ответа.")


@dataclass(frozen=True, slots=True)
class ChartSample:
    source: SourceRef
    moment: datetime
    value: float | None
    interval_start: datetime | None = None

    def __post_init__(self):
        if not isinstance(self.source, SourceRef):
            raise DomainValidationError("Необходима ссылка на исходную запись.")
        object.__setattr__(self, "moment", as_utc(self.moment))
        if self.value is not None and (type(self.value) not in (int, float) or not math.isfinite(self.value) or not 0 <= self.value <= 10):
            raise DomainValidationError("Значение графика должно быть числом 0–10 либо отсутствовать.")
        if self.interval_start is not None:
            object.__setattr__(self, "interval_start", as_utc(self.interval_start))
            if self.interval_start > self.moment:
                raise DomainValidationError("Начало интервала не может быть позже окончания.")


@dataclass(frozen=True, slots=True)
class ChartPoint:
    day: date
    value: float | None
    sources: tuple[SourceRef, ...]
    utc_moment: datetime | None
    local_moment: datetime | None
    interval_start: datetime | None
    minimum: float | None
    maximum: float | None
    measurements: int

    def __post_init__(self):
        _tuple(self.sources, SourceRef)
        if not self.sources:
            raise DomainValidationError("Точка должна ссылаться на реальные наблюдения.")
        if type(self.day) is not date or type(self.measurements) is not int or self.measurements < 0:
            raise DomainValidationError("Необходимы календарная дата и число измерений.")
        if self.value is None:
            if self.minimum is not None or self.maximum is not None or self.measurements != 0 or self.utc_moment is None:
                raise DomainValidationError("Отсутствующая оценка не является числовой сводкой.")
        elif (any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 10
                  for v in (self.minimum, self.value, self.maximum))
              or not self.minimum <= self.value <= self.maximum or self.measurements != len(self.sources)):
            raise DomainValidationError("Значения и источники точки должны соответствовать её статистике.")
        if self.utc_moment is not None:
            object.__setattr__(self, 'utc_moment', as_utc(self.utc_moment))
            if self.local_moment is None or as_utc(self.local_moment) != self.utc_moment:
                raise DomainValidationError("Местный и UTC-момент должны обозначать одно наблюдение.")
        elif self.local_moment is not None:
            raise DomainValidationError("У дневной сводки нет выдуманного времени наблюдения.")


@dataclass(frozen=True, slots=True)
class ChartSegment:
    # Индексы реальных точек в ChartSeries.points; никаких вставленных наблюдений.
    indices: tuple[int, ...]

    def __post_init__(self):
        if (type(self.indices) is not tuple or len(self.indices) < 2
                or any(type(i) is not int or i < 0 for i in self.indices)
                or any(a >= b for a,b in zip(self.indices,self.indices[1:]))):
            raise DomainValidationError("Сегмент содержит как минимум два индекса точек.")


@dataclass(frozen=True, slots=True)
class ChartSeries:
    kind: SeriesKind
    points: tuple[ChartPoint, ...]
    segments: tuple[ChartSegment, ...]

    def __post_init__(self):
        if not isinstance(self.kind, SeriesKind):
            raise DomainValidationError("Неизвестный временной ряд.")
        _tuple(self.points, ChartPoint)
        _tuple(self.segments, ChartSegment)
        if self.kind is SeriesKind.STRESS and self.segments:
            raise DomainValidationError("Стресс не соединяется линиями.")
        if any(source.kind != self.kind.source_kind for point in self.points for source in point.sources):
            raise DomainValidationError("Источники точки должны соответствовать ряду.")
        if any(i >= len(self.points) for segment in self.segments for i in segment.indices):
            raise DomainValidationError("Индекс сегмента выходит за границы ряда.")


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    day: date
    source: SourceRef  # Еда/зал: намеренно без поля момента времени.
    attended: bool | None = None
    difficulty: int | None = None

    def __post_init__(self):
        if type(self.day) is not date or not isinstance(self.source, SourceRef) or self.source.kind not in ('meals','gym'):
            raise DomainValidationError("Событие без времени должно быть датой питания/зала.")
        if self.attended is not None and (self.source.kind != 'gym' or type(self.attended) is not bool):
            raise DomainValidationError("Явный ответ относится только к спортзалу.")
        if self.difficulty is not None and (self.attended is not True or type(self.difficulty) is not int or not 0 <= self.difficulty <= 10):
            raise DomainValidationError("Сложность относится к посещению спортзала.")


@dataclass(frozen=True, slots=True)
class SleepSpan:
    source: SourceRef
    start: datetime
    end: datetime
    wake_day: date

    def __post_init__(self):
        if not isinstance(self.source, SourceRef) or self.source.kind != 'sleep' or type(self.wake_day) is not date:
            raise DomainValidationError("Необходима ссылка на сон и дата пробуждения.")
        object.__setattr__(self, 'start', as_utc(self.start))
        object.__setattr__(self, 'end', as_utc(self.end))
        if self.end <= self.start:
            raise DomainValidationError("Пробуждение должно быть позже засыпания.")


@dataclass(frozen=True, slots=True)
class PreparedChart:
    period: DateRange
    context: AnalysisContext
    mode: ChartMode
    line_gap_hours: float
    series: tuple[ChartSeries, ...]
    calendar_events: tuple[CalendarEvent, ...]
    sleep: tuple[SleepSpan, ...]

    def __post_init__(self):
        if not isinstance(self.period, DateRange) or not isinstance(self.context, AnalysisContext) or not isinstance(self.mode, ChartMode):
            raise DomainValidationError("Необходимы период, контекст и режим графика.")
        validate_line_gap(self.line_gap_hours)
        _tuple(self.series, ChartSeries)
        _tuple(self.calendar_events, CalendarEvent)
        _tuple(self.sleep, SleepSpan)


def _segments(points, eligible, connected):
    segments, run = [], []
    for i, point in enumerate(points):
        if not eligible(i, point):
            if len(run) >= 2:
                segments.append(ChartSegment(tuple(run)))
            run = []
            continue
        if run and not connected(points[run[-1]], point):
            if len(run) >= 2:
                segments.append(ChartSegment(tuple(run)))
            run = []
        run.append(i)
    if len(run) >= 2:
        segments.append(ChartSegment(tuple(run)))
    return tuple(segments)


def prepare_series(kind: SeriesKind, samples: tuple[ChartSample, ...], period: DateRange,
                   context: AnalysisContext, mode: ChartMode, line_gap_hours: float,
                   daily: tuple[DailyStatistics, ...] = ()) -> ChartSeries:
    _tuple(samples, ChartSample)
    _tuple(daily, DailyStatistics)
    if not isinstance(kind, SeriesKind) or not isinstance(mode, ChartMode) or any(s.source.kind != kind.source_kind for s in samples):
        raise DomainValidationError("Исходные наблюдения должны соответствовать ряду.")
    validate_line_gap(line_gap_hours)
    ordered = sorted((s for s in samples if s.moment <= context.now and period.contains(local_date(s.moment, context.zone))),
                     key=lambda s: (s.moment, s.source.record_id))
    if mode is ChartMode.DAILY and kind is not SeriesKind.STRESS:
        by_day = {}
        for sample in ordered:
            if sample.value is not None:
                by_day.setdefault(local_date(sample.moment, context.zone), []).append(sample.source)
        if any(d.day not in by_day for d in daily):
            raise DomainValidationError("Дневная сводка должна ссылаться на реальные числовые наблюдения.")
        points = tuple(ChartPoint(d.day, d.median, tuple(by_day[d.day]), None, None, None,
                                  d.minimum, d.maximum, d.measurements) for d in daily)
        segments = _segments(points, lambda i,p: True,
                             lambda a,b: b.day-a.day == timedelta(days=1))
    else:
        points = tuple(ChartPoint(local_date(s.moment,context.zone), s.value, (s.source,), s.moment,
                                  s.moment.astimezone(context.zone), s.interval_start,
                                  s.value, s.value, int(s.value is not None)) for s in ordered)
        duplicates = {moment for moment, group in groupby(ordered, key=lambda s:s.moment) if len(tuple(group)) > 1}
        def connected(a,b):
            if a.day != b.day or (b.utc_moment-a.utc_moment).total_seconds()/3600 > line_gap_hours:
                return False
            if mode is ChartMode.COMPACT and b.local_moment.utcoffset() < a.local_moment.utcoffset():
                return False
            return True
        segments = () if kind is SeriesKind.STRESS else _segments(points,
            lambda i,p: p.value is not None and p.utc_moment not in duplicates, connected)
    return ChartSeries(kind, points, segments)
