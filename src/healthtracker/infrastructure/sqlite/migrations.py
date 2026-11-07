"""Атомарная начальная миграция; обновления требуют защитного резервирования этапа 6."""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
import sqlite3

from healthtracker.infrastructure.sqlite.codecs import encode_time
from healthtracker.infrastructure.sqlite.connections import transaction
from healthtracker.infrastructure.sqlite.errors import MigrationBackupRequired, SchemaError
from healthtracker.infrastructure.sqlite.schema import TABLES, initial_statements


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        return hashlib.sha256(json.dumps(
            (self.version, self.name, self.statements), ensure_ascii=False,
        ).encode()).hexdigest()


MIGRATIONS = (Migration(1, "0001_initial", initial_statements()),)


def validate_integrity(connection: sqlite3.Connection) -> None:
    if [row[0] for row in connection.execute("PRAGMA integrity_check")] != ["ok"]:
        raise SchemaError("Нарушена целостность SQLite.")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise SchemaError("Нарушены внешние ключи.")


def validate_schema(connection: sqlite3.Connection, migrations=MIGRATIONS) -> None:
    validate_integrity(connection)
    rows = connection.execute("SELECT version,migration_id,checksum FROM schema_migrations ORDER BY version").fetchall()
    if len(rows) != len(migrations):
        raise SchemaError("Неожиданная версия схемы.")
    for row, expected in zip(rows, migrations, strict=True):
        if tuple(row) != (expected.version, expected.name, expected.checksum):
            raise SchemaError("Версия или контрольная сумма схемы не соответствует приложению.")
    actual = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if actual != TABLES:
        raise SchemaError("Набор таблиц не соответствует схеме.")
    expected_objects = {}
    for migration in migrations:
        for statement in migration.statements:
            match = re.match(r"\s*CREATE\s+(TABLE|INDEX|TRIGGER)\s+(\w+)\b", statement, re.I)
            if match:
                expected_objects[(match[1].lower(), match[2])] = " ".join(statement.split())
    actual_objects = {
        (row["type"], row["name"]): " ".join(row["sql"].split())
        for row in connection.execute(
            "SELECT type,name,sql FROM sqlite_schema WHERE type IN ('table','index','trigger') AND name NOT LIKE 'sqlite_%'"
        )
    }
    if actual_objects != expected_objects:
        raise SchemaError("Структура таблиц, индексов или защитных триггеров не соответствует схеме.")


def inspect_existing_schema(connection: sqlite3.Connection, migrations=MIGRATIONS) -> bool:
    """Предварительная проверка, допустимая на mode=ro до открытия на запись."""
    if not migrations or tuple(m.version for m in migrations) != tuple(range(1, len(migrations) + 1)):
        raise SchemaError("Миграции должны быть последовательными и нумерованными.")
    existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'")}
    if existing:
        if "schema_migrations" not in existing:
            raise SchemaError("Неизвестная база без журнала миграций; файл не изменён.")
        rows = connection.execute("SELECT version,migration_id,checksum FROM schema_migrations ORDER BY version").fetchall()
        if not rows or any(row[0] > len(migrations) for row in rows):
            raise SchemaError("Неизвестная версия схемы; запись запрещена.")
        for index, row in enumerate(rows):
            if index >= len(migrations) or tuple(row) != (index + 1, migrations[index].name, migrations[index].checksum):
                raise SchemaError("История миграций не соответствует приложению.")
        if len(rows) < len(migrations):
            raise MigrationBackupRequired("Обновление существующей схемы заблокировано до защитного резервирования этапа 6.")
        with transaction(connection):
            validate_schema(connection, migrations)
        return True
    return False


def initialize_schema(connection: sqlite3.Connection, *, now: datetime, migrations=MIGRATIONS) -> None:
    if inspect_existing_schema(connection, migrations):
        return
    # Новая база: только начальная миграция. Никакого обхода защиты будущих обновлений.
    if len(migrations) != 1:
        raise MigrationBackupRequired("Последующие миграции требуют защитного резервирования.")
    migration = migrations[0]
    for statement in migration.statements:
        if re.match(r"\s*(BEGIN|COMMIT|END|ROLLBACK|SAVEPOINT|RELEASE|VACUUM|ATTACH|DETACH|PRAGMA)\b", statement, re.I):
            raise SchemaError("Миграция содержит операцию вне атомарной транзакции.")
    with transaction(connection, write=True):
        for statement in migration.statements:
            connection.execute(statement, {"now": encode_time(now)})
        connection.execute("INSERT INTO schema_migrations VALUES(?,?,?,?)", (
            migration.version, migration.name, migration.checksum, encode_time(now),
        ))
        validate_schema(connection, migrations)  # До commit, в той же транзакции.
