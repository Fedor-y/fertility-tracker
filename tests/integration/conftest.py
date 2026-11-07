from datetime import UTC, datetime

import pytest

from healthtracker.infrastructure.sqlite.database import Database


NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


@pytest.fixture
def db(tmp_path):
    with Database(tmp_path / "records.sqlite3", clock=lambda: NOW) as database:
        yield database
