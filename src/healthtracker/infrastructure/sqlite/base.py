"""Общая механика CRUD. Таблицы/колонки заданы кодом, значения параметризованы."""

from healthtracker.application.storage import StoredRecord
from healthtracker.domain.errors import DomainValidationError
from healthtracker.domain.records import validate_record_time
from healthtracker.infrastructure.sqlite.codecs import encode_date, encode_time
from healthtracker.infrastructure.sqlite.errors import RecordNotFound


class RecordRepository:
    table: str
    model: type
    range_column: str
    date_only = False

    def __init__(self, session):
        self.session = session

    @property
    def connection(self):
        self.session.ensure_active()
        return self.session.connection

    def get(self, record_id):
        row = self.connection.execute(f"SELECT * FROM {self.table} WHERE id=?", (record_id,)).fetchone()
        return None if row is None else StoredRecord(row["id"], self._decode(row))

    def all(self):
        rows = self.connection.execute(f"SELECT * FROM {self.table} ORDER BY {self.range_column},id").fetchall()
        return tuple(StoredRecord(row["id"], self._decode(row)) for row in rows)

    def between(self, start, end):
        encode = encode_date if self.date_only else encode_time
        lower, upper = encode(start), encode(end)
        if lower >= upper:
            raise DomainValidationError("Конец диапазона должен быть позже начала.")
        rows = self.connection.execute(
            f"SELECT * FROM {self.table} WHERE {self.range_column}>=? AND {self.range_column}<? ORDER BY {self.range_column},id",
            (lower, upper),
        ).fetchall()
        return tuple(StoredRecord(row["id"], self._decode(row)) for row in rows)

    def _validate(self, value):
        if not isinstance(value, self.model):
            raise DomainValidationError("Данные не соответствуют виду записи.")
        validate_record_time(value, now=self.session.now, today=self.session.today)

    def _meta(self, value):
        return {"created_at_utc": encode_time(value.created_at), "updated_at_utc": encode_time(value.updated_at)}

    def _prepare(self, value, previous, record_id, **options):
        return value

    def _children(self, record_id, value):
        pass

    def create(self, value, **options):
        with self.session.operation():
            self._validate(value)
            value = self._prepare(value, None, None, **options)
            data = self._encode(value)
            cursor = self.connection.execute(
                f"INSERT INTO {self.table}({','.join(data)}) VALUES({','.join('?' for _ in data)})", tuple(data.values()),
            )
            record_id = cursor.lastrowid
            self._children(record_id, value)
            return record_id

    def update(self, record_id, value, **options):
        with self.session.operation():
            self._validate(value)
            previous = self.get(record_id)
            if previous is None:
                raise RecordNotFound("Запись не найдена.")
            if value.created_at != previous.value.created_at or value.updated_at < previous.value.updated_at:
                raise DomainValidationError("Нельзя менять время создания или возвращать время изменения назад.")
            value = self._prepare(value, previous.value, record_id, **options)
            data, old = self._encode(value), self._encode(previous.value)
            for key in data:
                if key.endswith("version_id") and data[key] is not None and old[key] is not None and data[key] != old[key]:
                    raise DomainValidationError("Историческую версию нельзя менять автоматически.")
            self.connection.execute(
                f"UPDATE {self.table} SET {','.join(key+'=?' for key in data)} WHERE id=?", (*data.values(), record_id),
            )
            self._children(record_id, value)

    def delete(self, record_id):
        with self.session.operation():
            if self.connection.execute(f"DELETE FROM {self.table} WHERE id=?", (record_id,)).rowcount != 1:
                raise RecordNotFound("Запись не найдена.")
