"""Воспроизводимый замер дневника: только самостоятельно созданные временные базы.

Запуск: .venv/bin/python tests/performance/diary_load.py
Не устанавливает нормативы производительности. JSON направляется в stdout.
"""
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from statistics import median
import json
import resource

from healthtracker.application.diary import Diary
from healthtracker.domain.answers import CognitiveAnswer
from healthtracker.domain.cognitive import CognitiveAssessment
from healthtracker.domain.measurement import CognitiveMeasurement
from healthtracker.domain.intervals import CognitiveInterval, SleepInterval
from healthtracker.domain.records import PhysicalRecord, StressRecord, MoodRecord, SleepRecord, MealRecord, MealItem, GymRecord
from healthtracker.domain.catalogs import SymptomStatus, MealCategory
from healthtracker.infrastructure.sqlite.database import Database

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


def populate(db, days):
    assessment = CognitiveAssessment(*(CognitiveAnswer.numeric(6) for _ in range(3)))
    meta = dict(created_at=NOW, updated_at=NOW)
    with db.write() as session:
        for index in range(days):
            moment = NOW - timedelta(days=days-index, hours=4)
            for hour in (0, 3, 6, 9):
                session.cognitive.create(CognitiveMeasurement(assessment, CognitiveInterval(moment+timedelta(hours=hour), now=NOW), NOW, NOW))
            session.physical.create(PhysicalRecord(observed_at=moment, score=7, symptom_status=SymptomStatus.UNKNOWN, **meta))
            session.stress.create(StressRecord(observed_at=moment, score=0, **meta))
            session.mood.create(MoodRecord(observed_at=moment, score=5, **meta))
            session.sleep.create(SleepRecord(interval=SleepInterval(moment-timedelta(hours=8), moment, now=NOW), **meta))
            for category in (MealCategory.BREAKFAST, MealCategory.LUNCH, MealCategory.DINNER):
                session.meals.create(MealRecord(entry_date=moment.date(), category=category, items=(MealItem(name='Искусственная позиция', **meta),), **meta))
            session.gym.create(GymRecord(entry_date=moment.date(), attended=False, **meta))


def measure(db, days):
    samples = []
    for offset in (days, days//2 or 1, 1, days, 1):
        day = (NOW-timedelta(days=offset)).date()
        start = perf_counter()
        result = Diary(db).day(day, UTC)
        samples.append((perf_counter()-start)*1000)
        assert len(result.timed) == 8 and len(result.untimed) == 4
    return dict(read_ms=[round(n, 2) for n in samples], median_ms=round(median(samples), 2), max_ms=round(max(samples), 2))


def main():
    for days in (30, 365, 1096):
        with TemporaryDirectory(prefix='healthtracker-load-') as directory:
            path = Path(directory)/'synthetic.sqlite3'
            with Database(path, clock=lambda: NOW) as db:
                start = perf_counter()
                populate(db, days)
                creation = perf_counter()-start
                measurements = measure(db, days)
                with db.read_snapshot() as session:
                    assert session.connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                    assert not session.connection.execute('PRAGMA foreign_key_check').fetchall()
            with Database(path, clock=lambda: NOW) as db:
                reopened = measure(db, days)
            print(json.dumps(dict(days=days, records=days*12, seed_seconds=round(creation, 2), bytes=path.stat().st_size,
                peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, **measurements, reopened=reopened), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
