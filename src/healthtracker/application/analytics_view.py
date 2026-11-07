"""Тексты и геометрия по готовым Domain-результатам; без Qt/SQL и новых формул."""
from dataclasses import dataclass

from healthtracker.application.chart_projection import NAMES
from healthtracker.domain.analytics import Indicator
from healthtracker.domain.factors import SleepExclusion
from healthtracker.domain.time import local_date

REASONS = {
    SleepExclusion.NO_SLEEP: 'Нет записи сна',
    SleepExclusion.NO_COGNITIVE_MEDIAN: 'Нет подходящей дневной медианы индекса',
    SleepExclusion.MULTIPLE_SLEEP_INTERVALS: 'Несколько интервалов сна',
    SleepExclusion.COGNITIVE_HOUR_BEFORE_WAKE: 'Оцениваемый час начался до пробуждения',
}
STAT_HEADERS = ('Показатель', 'Медиана', 'Среднее', 'Минимум\n(даты)', 'Максимум\n(даты)',
                'Измерений', 'Дат с\nданными', 'Покрытие')
DAILY_HEADERS = ('Дата', 'Дневная\nмедиана', 'Минимум', 'Максимум', 'Измерений', 'Состояние')


def number(value):
    return '—' if value is None else f'{value:.2f}'


def coverage(stats):
    return f'{stats.observed_days} из {stats.calendar_days} — {stats.coverage_percent:.1f}%'


def brief_statistics(stats):
    prefix = f'{NAMES[stats.indicator.value]} · {coverage(stats)} · измерений {stats.measurements}'
    if stats.summary is None:
        detail = 'Нет числовых данных' if not stats.observed_days else 'Для сводки нужно 7 дат с данными'
    else:
        s = stats.summary
        detail = f'Медиана {number(s.median)} · среднее {number(s.mean)} · min {number(s.minimum)} · max {number(s.maximum)} (пункты)'
    return prefix + '\n' + detail + (' · Период не завершён' if stats.incomplete else '')


@dataclass(frozen=True, slots=True)
class AnalyticsView:
    summary_rows: tuple[tuple[str, ...], ...]
    daily_rows: tuple[tuple[str, ...], ...]
    comparison_text: str
    sleep_text: str
    exclusions: tuple[tuple[str, ...], ...]
    gym_text: str
    caption: str
    extrema: tuple[str, ...]
    selected_row: int


def make_view(snapshot, result, statistics, comparison, checkpoint=lambda:None):
    rows,extrema = [],[]
    for stats in statistics:
        s = stats.summary
        rows.append((NAMES[stats.indicator.value], number(s.median if s else None),
            number(s.mean if s else None),
            (number(s.minimum)+' · '+', '.join(map(str,s.minimum_dates))) if s else '—',
            (number(s.maximum)+' · '+', '.join(map(str,s.maximum_dates))) if s else '—',
            str(stats.measurements), str(stats.observed_days), coverage(stats)))
        extrema.append(NAMES[stats.indicator.value]+'\n'+
            ('Минимум: '+number(s.minimum)+'\nДаты минимума:\n'+'\n'.join(map(str,s.minimum_dates))+
             '\nМаксимум: '+number(s.maximum)+'\nДаты максимума:\n'+'\n'.join(map(str,s.maximum_dates))
             if s else 'Экстремумы сводки недоступны: нужно ≥ 7 дат с данными.'))
    selected = result.statistics
    by_day = {d.day:d for d in selected.daily}
    specials = {}
    if selected.indicator not in (Indicator.PHYSICAL, Indicator.MOOD):
        for record in snapshot.cognitive:
            assessment = record.value.assessment
            answers = (tuple(getattr(assessment,k) for k in ('learning','application','speed'))
                       if selected.indicator is Indicator.COGNITIVE else (getattr(assessment,selected.indicator.value),))
            for answer in answers:
                if answer.value is None:
                    specials.setdefault(local_date(record.value.interval.end,snapshot.context.zone),set()).add(answer.status.label)
    daily = []
    for day in selected.period.dates():
        checkpoint()
        row = by_day.get(day)
        state = ('Дневная медиана' if row else 'Нет числовых измерений')
        if day > snapshot.context.today:
            state = 'Будущая часть периода'
        if day in specials:
            state += ' · '+', '.join(sorted(specials[day]))
        daily.append((str(day),number(row.median if row else None),number(row.minimum if row else None),
                      number(row.maximum if row else None),str(row.measurements) if row else '—',state))
    comparison_text = 'Выберите сравнение недель, месяцев или два произвольных диапазона.'
    if comparison is not None:
        parts = []
        for name, stats in (('Первый',comparison.first),('Второй',comparison.second)):
            parts.append(f'{name}: {stats.period.start} — {stats.period.end}\n'+brief_statistics(stats))
        parts.append('Разница: '+(number(comparison.difference)+' пункта (первый минус второй)'
                     if comparison.difference is not None else 'недоступна — нужны ≥ 7 дат с данными в каждом периоде'))
        comparison_text = '\n\n'.join(parts)
    sleep, gym = result.sleep, result.gym
    sleep_text = (f'Использовано дат: {sleep.used_days}; исключено: {sleep.excluded_days}. '
                  'Каждая исключённая дата учитывается один раз; причин может быть несколько.\n'
                  'X — часы сна по UTC, Y — обычная дневная медиана индекса. Без прогнозов и причинных выводов.')
    if not sleep.points:
        sleep_text += '\nНет подходящих дат для сравнения сна.'
    gym_text = (f'Когнитивный индекс: дневные медианы\nБыл: {gym.attended.days} дат · медиана {number(gym.attended.median)}\n'
                f'Не был: {gym.absent.days} дат · медиана {number(gym.absent.median)}\n'
                f'Разница: {number(gym.difference)} пункта (Был минус Не был)\n'
                f'Исключено дат без подходящей медианы или явной отметки: {len(gym.excluded_dates)}. '
                'Неизвестные даты не считаются «Не был».')
    if gym.warning:
        gym_text += '\n'+gym.warning+' (нужно ≥ 5 дат в каждой группе; расчёты не скрыты).'
    caption = brief_statistics(selected)+'\nКаждая календарная дата имеет одинаковый вес. При < 7 дат сводка скрыта, дневные данные доступны.'
    return AnalyticsView(tuple(rows),tuple(daily),comparison_text,sleep_text,
        tuple((str(d.day),'; '.join(REASONS[r] for r in d.reasons)) for d in sleep.excluded),gym_text,caption,
        tuple(extrema),tuple(s.indicator for s in statistics).index(selected.indicator))


def factor_projection(result):
    sleep = [{'value':[p.sleep_hours,p.cognitive_median],
              'lines':[str(p.day),'Сон: '+number(p.sleep_hours)+' ч по UTC',
                       'Дневная медиана индекса: '+number(p.cognitive_median)],'sources':[]}
             for p in result.sleep.points]
    gym = [{'value':[category,p.cognitive_median],
            'lines':[str(p.day),label,'Дневная медиана индекса: '+number(p.cognitive_median),
                     'Сложность: '+number(p.difficulty) if p.difficulty is not None else 'Сложность не применяется («Не был»)'],
            'sources':[]}
           for category,label,group in ((0,'Был',result.gym.attended),(1,'Не был',result.gym.absent)) for p in group.points]
    return {'sleep':sleep,'gym':gym}
