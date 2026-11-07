from datetime import date

from healthtracker.domain.catalogs import CaffeineStatus, MealCategory
from healthtracker.domain.records import MealItem, MealRecord, meal_duplicate_warning_needed
from healthtracker.infrastructure.sqlite.base import RecordRepository
from healthtracker.infrastructure.sqlite.codecs import decode_time, encode_date, encode_time
from healthtracker.infrastructure.sqlite.errors import ConfirmationRequired


class MealRepository(RecordRepository):
    table, model, range_column, date_only = "meals", MealRecord, "meal_date", True

    def duplicates(self, entry_date, category, *, exclude_id=None):
        if not isinstance(category, MealCategory):
            from healthtracker.domain.errors import DomainValidationError
            raise DomainValidationError("Неизвестная категория питания.")
        if category is MealCategory.OTHER:
            return ()
        return tuple(row[0] for row in self.connection.execute(
            "SELECT id FROM meals WHERE meal_date=? AND category=? AND (? IS NULL OR id<>?) ORDER BY id",
            (encode_date(entry_date), category.value, exclude_id, exclude_id),
        ))

    def _prepare(self, value, previous, record_id, *, duplicate_confirmed=False):
        duplicates = bool(self.duplicates(value.entry_date, value.category, exclude_id=record_id))
        if meal_duplicate_warning_needed(value, previous, has_duplicates=duplicates) and duplicate_confirmed is not True:
            raise ConfirmationRequired("Категория уже использована за эту дату. Подтвердите новую запись.")
        return value

    def _encode(self, value):
        return {**self._meta(value), "meal_date": encode_date(value.entry_date), "category": value.category.value, "note": value.note}

    def _children(self, record_id, value):
        # Позиции — внутренние части агрегата, не самостоятельные наблюдения.
        self.connection.execute("DELETE FROM meal_items WHERE meal_id=?", (record_id,))
        for position, item in enumerate(value.items):
            self.connection.execute(
                "INSERT INTO meal_items(meal_id,position,name,composition,quantity_text,caffeine_status,created_at_utc,updated_at_utc) VALUES(?,?,?,?,?,?,?,?)",
                (record_id, position, item.name, item.composition, item.quantity_text, item.caffeine_status.value,
                 encode_time(item.created_at), encode_time(item.updated_at)),
            )

    def _decode(self, row):
        items = self.connection.execute("SELECT * FROM meal_items WHERE meal_id=? ORDER BY position", (row["id"],)).fetchall()
        return MealRecord(entry_date=date.fromisoformat(row["meal_date"]), category=MealCategory(row["category"]), note=row["note"],
            items=tuple(MealItem(name=i["name"], composition=i["composition"], quantity_text=i["quantity_text"], caffeine_status=CaffeineStatus(i["caffeine_status"]),
                created_at=decode_time(i["created_at_utc"]), updated_at=decode_time(i["updated_at_utc"])) for i in items),
            created_at=decode_time(row["created_at_utc"]), updated_at=decode_time(row["updated_at_utc"]))
