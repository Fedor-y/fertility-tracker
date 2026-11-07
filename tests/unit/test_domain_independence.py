"""Предметные модули должны загружаться без site-packages и графического сеанса."""

import os
from pathlib import Path
import subprocess
import sys


def test_domain_imports_without_qt_or_sqlite():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-S", "-c", """
import importlib
import pkgutil
import sys
import healthtracker.domain
for module in pkgutil.walk_packages(healthtracker.domain.__path__, 'healthtracker.domain.'):
    importlib.import_module(module.name)
assert not any(name.startswith(('PySide6', 'sqlite3', 'healthtracker.presentation',
                                'healthtracker.infrastructure')) for name in sys.modules)
print('domain-only')
"""],
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        capture_output=True, text=True, timeout=10, check=True,
    )
    assert result.stdout.strip() == "domain-only"
