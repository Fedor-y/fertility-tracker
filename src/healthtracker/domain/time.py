"""Однозначные UTC-моменты и явное разрешение локального времени.

Часовой пояс передаётся вызывающим слоем. Domain не читает настройки системы
и не сохраняет исходный пояс события.
"""

from datetime import UTC, date, datetime, timedelta, tzinfo

from healthtracker.domain.errors import DomainValidationError


class NonexistentLocalTimeError(DomainValidationError):
    """Местное время отсутствует при переводе часов."""


class AmbiguousLocalTimeError(DomainValidationError):
    """Повторяющийся час требует явного выбора UTC-смещения."""


def as_utc(moment: datetime) -> datetime:
    """Принять только определённый реальный момент; не угадывать пояс naive."""
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise DomainValidationError("Необходим момент времени с часовым поясом.")
    try:
        if moment.utcoffset() is None:
            raise DomainValidationError("Необходим определённый часовой пояс.")
        utc = moment.astimezone(UTC)
        restored = utc.astimezone(moment.tzinfo)
        if (
            restored.replace(tzinfo=None) != moment.replace(tzinfo=None)
            or restored.utcoffset() != moment.utcoffset()
        ):
            raise NonexistentLocalTimeError("Выбранное местное время не существует.")
        return utc
    except (OverflowError, OSError) as error:
        raise DomainValidationError("Момент времени вне допустимого диапазона.") from error


def local_time_candidates(local: datetime, zone: tzinfo) -> tuple[datetime, ...]:
    """Вернуть 0/1/2 реальных UTC-момента без автоматического выбора fold."""
    if not isinstance(local, datetime) or local.tzinfo is not None:
        raise DomainValidationError("Ожидаются местные дата и время без часового пояса.")
    if not isinstance(zone, tzinfo):
        raise DomainValidationError("Необходимо указать часовой пояс.")
    candidates = set()
    for fold in (0, 1):
        attached = local.replace(tzinfo=zone, fold=fold)
        try:
            candidates.add(as_utc(attached))
        except NonexistentLocalTimeError:
            continue
    return tuple(sorted(candidates))


def resolve_local_time(
    local: datetime, zone: tzinfo, *, utc_offset: timedelta | None = None,
) -> datetime:
    """При повторе часа вызывающий интерфейс обязан получить выбор пользователя."""
    candidates = local_time_candidates(local, zone)
    if not candidates:
        raise NonexistentLocalTimeError("Выбранное местное время не существует.")
    if utc_offset is not None:
        if not isinstance(utc_offset, timedelta):
            raise DomainValidationError("Некорректное UTC-смещение.")
        for candidate in candidates:
            if candidate.astimezone(zone).utcoffset() == utc_offset:
                return candidate
        raise DomainValidationError("UTC-смещение не соответствует выбранному времени.")
    if len(candidates) > 1:
        raise AmbiguousLocalTimeError("Выберите UTC-смещение повторяющегося часа.")
    return candidates[0]


def local_date(moment: datetime, zone: tzinfo) -> date:
    """Календарная дата наблюдения в переданном текущем поясе."""
    if not isinstance(zone, tzinfo):
        raise DomainValidationError("Необходимо указать часовой пояс.")
    return as_utc(moment).astimezone(zone).date()
