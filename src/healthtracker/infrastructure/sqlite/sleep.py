from healthtracker.domain.intervals import SleepInterval, ensure_no_sleep_overlap
from healthtracker.domain.records import SleepRecord
from healthtracker.infrastructure.sqlite.base import RecordRepository
from healthtracker.infrastructure.sqlite.codecs import decode_time, encode_time
from healthtracker.infrastructure.sqlite.errors import ConfirmationRequired


class SleepRepository(RecordRepository):
    table, model, range_column = "sleep_entries", SleepRecord, "wake_at_utc"

    def _prepare(self, value, previous, record_id, *, long_sleep_confirmed=False):
        if value.interval.requires_confirmation and long_sleep_confirmed is not True:
            raise ConfirmationRequired("Подтвердите сон продолжительностью более 16 часов.")
        rows = self.connection.execute(
            "SELECT * FROM sleep_entries WHERE sleep_start_utc<? AND wake_at_utc>? AND (? IS NULL OR id<>?)",
            (encode_time(value.interval.end), encode_time(value.interval.start), record_id, record_id),
        ).fetchall()
        ensure_no_sleep_overlap(value.interval, (self._decode(row).interval for row in rows))
        return value

    def _encode(self, value):
        return {**self._meta(value), "sleep_start_utc": encode_time(value.interval.start), "wake_at_utc": encode_time(value.interval.end)}

    def _decode(self, row):
        return SleepRecord(interval=SleepInterval(decode_time(row["sleep_start_utc"]), decode_time(row["wake_at_utc"]), now=self.session.now),
            created_at=decode_time(row["created_at_utc"]), updated_at=decode_time(row["updated_at_utc"]))
