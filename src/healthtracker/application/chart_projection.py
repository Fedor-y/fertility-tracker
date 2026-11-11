"""Python-проекция готовых точек для ECharts. Не рассчитывает статистику; последовательности отрисовки отделены от моделей."""
from collections import Counter, defaultdict
from datetime import UTC, datetime, time, timedelta, timezone
from math import ceil

from healthtracker.domain.charts import ChartMode, SeriesKind

NAMES = {'cognitive': 'Когнитивный индекс', 'learning': 'Запоминание нового',
         'application': 'Воспроизведение и применение', 'speed': 'Скорость мышления',
         'physical': 'Физическое состояние', 'mood': 'Настроение', 'stress': 'Стресс'}
SOURCE_NAMES = {'cognitive': 'Когнитивная запись', 'physical': 'Физическое состояние',
                'mood': 'Настроение', 'stress': 'Стресс', 'sleep': 'Сон',
                'meals': 'Питание', 'gym': 'Спортзал'}
COLORS = {'cognitive': '#ff9b54', 'learning': '#e5e5e5', 'application': '#b8c9d8',
          'speed': '#c8b8d8', 'physical': '#aaaaaa', 'mood': '#d0cf9d', 'stress': '#deab9e'}


def day_start(day, zone):
    """Граница календаря: ранний fold; при пропуске полуночи — начало доступной даты.

    Это границы оси, не подстановка момента наблюдения или выбор времени формы.
    Пропущенная целиком дата имеет нулевую реальную ширину.
    """
    candidates = [datetime.combine(day, time.min, zone).replace(fold=fold).astimezone(UTC)
                  for fold in (0, 1)]
    return min(moment for moment in candidates if moment.astimezone(zone).date() >= day)


def definitions(sources):
    return '; '.join(f"{SOURCE_NAMES[s.kind]} #{s.record_id}" +
                     (' · ' + ', '.join(f'{NAMES.get(d.code, NAMES["cognitive"] if d.code == "cognitive_index" else d.code)} · версия {d.version}' for d in s.definitions) if s.definitions else '')
                     for s in sources)


def moment_text(moment, zone):
    return moment.astimezone(zone).isoformat(sep=' ', timespec='seconds')


def offset_parts(start, end, zone):
    """Разделить геометрию сна на участки постоянного UTC-смещения."""
    left, scan = start, start
    while scan < end:
        right = min(scan + timedelta(hours=1), end)
        offset = scan.astimezone(zone).utcoffset()
        if right.astimezone(zone).utcoffset() != offset:
            lo, hi = scan, right
            while hi - lo > timedelta(microseconds=1):
                middle = lo + (hi - lo) // 2
                if middle.astimezone(zone).utcoffset() == offset:
                    lo = middle
                else:
                    hi = middle
            yield left, hi, offset
            left = scan = hi
        else:
            scan = right
    if left < end:
        yield left, end, left.astimezone(zone).utcoffset()


def display_segments(chart, series):
    """Проекция для линии: прежние связи плюс допустимые переходы даты.

    Исходные ChartSeries/ChartSegment не изменяются. Решение выполняется в worker
    вместе с прежней проекцией, без разбора JSON или вычислений в GUI/JavaScript.
    """
    original = [list(segment.indices) for segment in series.segments]
    if chart.mode not in (ChartMode.COMPACT, ChartMode.TIMELINE) or series.kind is SeriesKind.STRESS:
        return original
    points = series.points
    links = {(a, b) for segment in original for a, b in zip(segment, segment[1:])}
    counts = Counter(p.utc_moment for p in points)
    for i in range(1, len(points)):
        a, b = points[i-1], points[i]
        if (a.day == b.day or a.value is None or b.value is None
                or a.utc_moment is None or b.utc_moment is None
                or counts[a.utc_moment] > 1 or counts[b.utc_moment] > 1):
            continue
        gap = (b.utc_moment-a.utc_moment).total_seconds()/3600
        if not 0 < gap <= chart.line_gap_hours:
            continue
        if chart.mode is ChartMode.COMPACT and b.local_moment.utcoffset() < a.local_moment.utcoffset():
            continue
        links.add((i-1, i))
    runs, run = [], []
    for i in range(len(points)):
        if run and (run[-1], i) not in links:
            if len(run) >= 2:
                runs.append(run)
            run = []
        run.append(i)
    if len(run) >= 2:
        runs.append(run)
    return runs


def project_chart(chart, *, show_events=True):
    period, zone, mode = chart.period, chart.context.zone, chart.mode
    days = period.calendar_days
    origin = day_start(period.start, zone)
    end = day_start(period.end + timedelta(days=1), zone)
    real = mode in (ChartMode.DAY, ChartMode.TIMELINE)
    daily = mode is ChartMode.DAILY

    def coordinate(moment):
        if real:
            return (moment - origin).total_seconds()
        local = moment.astimezone(zone)
        fraction = (local.hour * 3600 + local.minute * 60 + local.second + local.microsecond / 1e6) / 86400
        return ((local.date() - period.start).days + fraction) * (1 if daily else 86400)

    maximum = (end - origin).total_seconds() if real else days * (1 if daily else 86400)
    step = (10800 if mode is ChartMode.DAY else 43200) if real else (max(1, ceil(days / 10)) if daily else 21600)
    ticks = []
    # Только представление оси: локальные целые часы из реальных UTC-моментов.
    # Четверть часа покрывает и получасовые DST-сдвиги без выдуманных часов.
    tick_step = 900 if real else step
    for i in range(int(maximum // tick_step) + 1):
        x = i * tick_step
        if real:
            local = (origin + timedelta(seconds=x)).astimezone(zone)
            if local.minute or local.second:
                continue
            label = local.strftime('%d.%m\n%H:%M %z')
        elif daily:
            label = (period.start + timedelta(days=int(x))).strftime('%d.%m.%Y') if x < maximum else ''
        else:
            day_index, seconds = divmod(x, 86400)
            day = period.start + timedelta(days=day_index)
            label = day.strftime('%d.%m') + '\n' + f'{seconds // 3600:02d}:00'
            if seconds == 0 and (day_start(day + timedelta(days=1), zone) - day_start(day, zone)).total_seconds() != 86400:
                label += ' · DST'
        ticks.append({'x': x, 'text': label})

    rows, nonnumeric = [], []
    by_x = defaultdict(list)
    sources_by_x = defaultdict(dict)
    for series in chart.series:
        points = []
        for i, point in enumerate(series.points):
            x = coordinate(point.utc_moment) if point.utc_moment else (point.day - period.start).days + .5
            value_text = 'Нет числовой оценки' if point.value is None else f'{point.value:.2f}'
            lines = [NAMES[series.kind.value], point.day.isoformat(), value_text]
            if point.utc_moment:
                lines.append(moment_text(point.utc_moment, zone))
                lines.append('UTC ' + point.utc_moment.isoformat())
                if point.interval_start:
                    lines.append('Начало часа: ' + moment_text(point.interval_start, zone))
            else:
                lines.append(f'Дневная медиана · min {point.minimum:.2f} · max {point.maximum:.2f} · измерений {point.measurements}')
            for source in point.sources:
                if source.cognitive_answers:
                    lines.extend(f'{name}: {answer.value if answer.value is not None else answer.status.label}'
                                 for name, answer in zip(('Запоминание нового', 'Воспроизведение и применение', 'Скорость мышления'), source.cognitive_answers))
            lines.append(definitions(point.sources))
            projected = {'value': [x, point.value], 'point_index': i, 'lines': lines,
                         'sources': [{'kind': s.kind, 'record_id': s.record_id, 'label': SOURCE_NAMES[s.kind]} for s in point.sources]}
            points.append(projected)
            if point.value is None:
                nonnumeric.append(projected)
            by_x[x].extend(lines + [''])
            for source in projected['sources']:
                sources_by_x[x][(source['kind'], source['record_id'])] = source
        rows.append({'kind': series.kind.value, 'name': NAMES[series.kind.value],
                     'color': COLORS[series.kind.value], 'points': points,
                     'segments': display_segments(chart, series)})
    # Общая подсказка сохраняет все записи совпавшей временной координаты.
    for row in rows:
        for point in row['points']:
            point['lines'] = by_x[point['value'][0]]
            point['sources'] = list(sources_by_x[point['value'][0]].values())

    events = []
    for event in chart.calendar_events:
        label = 'Питание' if event.source.kind == 'meals' else ('Спортзал: Был' if event.attended is True else 'Спортзал: Не был' if event.attended is False else 'Запись спортзала')
        if event.difficulty is not None:
            label += f' · сложность {event.difficulty}'
        events.append({'day': event.day.isoformat(), 'text': label,
                       'lines': [event.day.isoformat(), label, 'Время не указано: событие имеет только дату', definitions((event.source,))],
                       'sources': [{'kind': event.source.kind, 'record_id': event.source.record_id, 'label': SOURCE_NAMES[event.source.kind]}]})

    sleep = []
    for span in chart.sleep:
        lines = ['Сон', 'Засыпание: ' + moment_text(span.start, zone),
                 'Пробуждение: ' + moment_text(span.end, zone),
                 f'Длительность по UTC: {(span.end - span.start).total_seconds() / 3600:.2f} ч', definitions((span.source,))]
        # Деление интервала только по границам календарных полос; не новые наблюдения.
        visible_start = max(period.start, span.start.astimezone(zone).date())
        visible_end = min(period.end, span.end.astimezone(zone).date())
        count = max(0, (visible_end - visible_start).days + 1)
        for day in (visible_start + timedelta(days=i) for i in range(count)):
            start = max(span.start, day_start(day, zone))
            finish = min(span.end, day_start(day + timedelta(days=1), zone))
            if start >= finish:
                continue
            parts = ((start, finish, None),) if real else offset_parts(start, finish, zone)
            for piece_start, piece_end, offset in parts:
                if real:
                    a, b = coordinate(piece_start), coordinate(piece_end)
                else:
                    def wall_coordinate(moment):
                        wall = moment.astimezone(timezone(offset))
                        fraction = (wall.hour * 3600 + wall.minute * 60 + wall.second + wall.microsecond / 1e6) / 86400
                        return ((wall.date() - period.start).days + fraction) * (1 if daily else 86400)
                    a, b = wall_coordinate(piece_start), wall_coordinate(piece_end)
                sleep.append({'value': [0, a, b], 'lines': lines,
                              'sources': [{'kind': 'sleep', 'record_id': span.source.record_id, 'label': 'Сон'}]})
    return {'mode': mode.value, 'axis': {'min': 0, 'max': maximum, 'step': step, 'ticks': ticks,
                'boundaries': [(day_start(day, zone) - origin).total_seconds() if real
                               else i * (1 if daily else 86400)
                               for i, day in enumerate(period.dates())]},
            'series': rows, 'sleep': sleep, 'events': events if show_events else [],
            'nonnumeric': nonnumeric if show_events else [],
            'caption': f'{period.start.isoformat()} — {period.end.isoformat()} · {zone}',
            'empty_text': 'Показатели отключены' if not chart.series else 'Нет числовых наблюдений',
            'empty': not any(p['value'][1] is not None for row in rows for p in row['points'])}
