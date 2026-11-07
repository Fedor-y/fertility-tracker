"""Domain/Application аналитика запускаются без site-packages и SQLite."""
import ast
import os
from pathlib import Path
import subprocess
import sys


def test_analytics_runs_without_qt_sqlite_or_presentation():
    root=Path(__file__).resolve().parents[2]
    script='''
from datetime import UTC,date,datetime
from healthtracker.application.analytics import Analytics,calculate_snapshot
from healthtracker.application.charts import ChartQuery,ChartPreparation
from healthtracker.application.chart_requests import ChartRequests
from healthtracker.domain.analytics import AnalyticsData,AnalysisContext,Indicator,period_statistics
from healthtracker.domain.periods import DateRange
from healthtracker.domain.factors import sleep_comparison,gym_comparison
import sys
context=AnalysisContext(datetime(2026,11,4,12,tzinfo=UTC),UTC)
period=DateRange(date(2026,11,1),date(2026,11,4))
assert period_statistics(AnalyticsData(),Indicator.COGNITIVE,period,context).summary is None
assert sleep_comparison(AnalyticsData(),period,context).excluded_days==4
assert gym_comparison(AnalyticsData(),period,context).difference is None
assert not any(n.startswith(('PySide6','sqlite3','healthtracker.presentation','healthtracker.infrastructure')) for n in sys.modules)
print('pure-analytics')
'''
    result=subprocess.run([sys.executable,'-S','-c',script],env={**os.environ,'PYTHONPATH':str(root/'src')},
                          capture_output=True,text=True,timeout=10,check=True)
    assert result.stdout.strip()=='pure-analytics'
    for path in (root/'src/healthtracker/application').glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            names=([alias.name for alias in node.names] if isinstance(node,ast.Import) else
                   [node.module or ''] if isinstance(node,ast.ImportFrom) else [])
            assert not any(n.startswith(('PySide6','sqlite3','healthtracker.presentation','healthtracker.infrastructure')) for n in names),path
