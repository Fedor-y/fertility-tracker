from contextlib import contextmanager
from datetime import date, timedelta

import pytest

from healthtracker.application.errors import MealDuplicateConfirmationRequired, RecordNotFound, StorageError
from healthtracker.application.observations import Observations
from healthtracker.domain.catalogs import CaffeineStatus, MealCategory
from healthtracker.domain.errors import DomainValidationError
from healthtracker.infrastructure.sqlite.database import Database

DAY = date(2026, 11, 1)


@pytest.fixture
def service(db):
    return Observations(db, clock=db.clock)


def fields(name='Еда', source=None, **kwargs):
    return dict(name=name, source_position=source, **kwargs)


def save(service, *, day=DAY, category=MealCategory.LUNCH, items=None, **kwargs):
    return service.save_meal(entry_date=day, category=category,
        items=items if items is not None else (fields(),), **kwargs)


def test_meal_all_fields_reopen_and_schema(service):
    record_id=save(service,items=(
        fields('Омлет',composition='Яйца, сыр',quantity_text='Большая тарелка'),
        fields('Чай',quantity_text='Две чашки',caffeine_status=CaffeineStatus.CONTAINS)),note='Наблюдение')
    old=service.get('meals',record_id)
    assert old.value.entry_date == DAY and len(old.value.items)==2
    assert old.value.created_at.date()>DAY
    assert old.value.items[0].composition=='Яйца, сыр'
    assert old.value.items[0].quantity_text=='Большая тарелка'
    assert old.value.items[0].caffeine_status is CaffeineStatus.UNSPECIFIED
    assert old.value.items[1].caffeine_status is CaffeineStatus.CONTAINS
    assert not hasattr(old.value,'observed_at')
    path=service.storage.path
    service.storage.close()
    with Database(path,clock=service.clock) as reopened:
        assert Observations(reopened).get('meals',record_id)==old


def test_meal_edit_add_remove_and_metadata(service):
    record_id=save(service,items=(fields('Первая'),fields('Вторая')))
    old=service.get('meals',record_id).value
    save(service,record_id=record_id,day=DAY+timedelta(days=1),category=MealCategory.DINNER,
         items=(fields('Вторая',1),fields('Новая')))
    edited=service.get('meals',record_id).value
    assert edited.created_at==old.created_at
    assert edited.items[0]==old.items[1]
    assert edited.category is MealCategory.DINNER and edited.entry_date==DAY+timedelta(days=1)
    assert [i.name for i in edited.items]==['Вторая','Новая']


def test_meal_duplicate_confirm_and_no_self_conflict(service):
    first=save(service)
    with pytest.raises(MealDuplicateConfirmationRequired) as error:
        save(service)
    assert error.value.record_ids==(first,)
    second=save(service,duplicate_confirmed=True)
    save(service,record_id=second,items=(fields('Исправлено',0),))
    assert service.get('meals',first).value.items[0].name=='Еда'
    assert service.get('meals',second).value.items[0].name=='Исправлено'
    with service.storage.read_snapshot() as s:
        assert len(s.meals.all())==2


@pytest.mark.parametrize('change',['date','category'])
def test_meal_edit_changed_pair_requires_confirmation(service,change):
    other=save(service)
    initial=dict(day=DAY+timedelta(days=1)) if change=='date' else dict(category=MealCategory.DINNER)
    record_id=save(service,**initial)
    old=service.get('meals',record_id)
    with pytest.raises(MealDuplicateConfirmationRequired) as error:
        save(service,record_id=record_id,items=(fields('Правка',0),))
    assert error.value.record_ids==(other,)
    assert service.get('meals',record_id)==old
    save(service,record_id=record_id,items=(fields('Правка',0),),duplicate_confirmed=True)


def test_meal_other_repeats_without_confirmation(service):
    for _ in range(3):
        save(service,category=MealCategory.OTHER)
    with service.storage.read_snapshot() as s:
        assert len(s.meals.all())==3


@pytest.mark.parametrize('items',[(),(fields(''),),(fields('   '),)])
def test_meal_required_items_and_names(service,items):
    with pytest.raises(DomainValidationError):
        save(service,items=items)


def test_meal_required_category_date_and_future(service):
    for kwargs in [dict(category=None),dict(day=None),dict(day=date(2030,1,1))]:
        with pytest.raises(DomainValidationError):
            save(service,**kwargs)


@pytest.mark.parametrize('existing',[False,True])
def test_meal_failed_commit_rolls_back(service,monkeypatch,existing):
    record_id=save(service) if existing else None
    old=service.get('meals',record_id) if existing else None
    write=service.storage.write
    @contextmanager
    def fail():
        with write() as s:
            yield s
            raise StorageError('before commit')
    monkeypatch.setattr(service.storage,'write',fail)
    with pytest.raises(StorageError):
        save(service,record_id=record_id,items=(fields('Новая'),fields('Ещё одна')))
    if existing:
        assert service.get('meals',record_id)==old
    else:
        with service.storage.read_snapshot() as s:
            assert not s.meals.all()


def test_meal_unknown_id_and_invalid_item_source(service):
    with pytest.raises(RecordNotFound):
        save(service,record_id=999)
    with pytest.raises(DomainValidationError):
        save(service,items=(fields('Имя',0),))
