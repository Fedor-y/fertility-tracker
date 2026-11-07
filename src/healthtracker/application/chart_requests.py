"""Управляемые рабочие задачи и проверяемая доставка. Без Qt и SQL."""
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from dataclasses import dataclass
from queue import Empty, SimpleQueue
from threading import Event, RLock, get_ident
from uuid import uuid4

from healthtracker.application.charts import ChartPreparation, ChartQuery, ChartResult
from healthtracker.application.errors import StorageError
from healthtracker.application.storage import SnapshotToken
from healthtracker.domain.errors import DomainValidationError


@dataclass(frozen=True, slots=True)
class ChartFailure:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ChartOutcome:
    request_id: str
    token: SnapshotToken
    result: ChartResult | None = None
    failure: ChartFailure | None = None

    def __post_init__(self):
        if (self.result is None) == (self.failure is None):
            raise ValueError("Нужен ровно один результат: данные или ошибка.")


class ChartRequests:
    """request/dispatch/apply вызываются только потоком владельца.

    Готовые результаты не передаются UI из callback рабочего потока.
    При быстром вводе отменяются ожидающие задачи; выполняющиеся завершаются
    безопасно. Ни отмена, ни предварительная проверка не заменяют apply.
    """
    def __init__(self, preparation: ChartPreparation, *, max_workers=2):
        self.preparation = preparation
        self.storage = preparation.analytics.storage
        self._owner = get_ident()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='healthtracker-chart')
        self._lock = RLock()
        self._jobs: dict[Future, Event] = {}
        self._operations: set[Future] = set()
        self._queue = SimpleQueue()
        self._deferred: ChartOutcome | None = None
        self._latest: str | None = None
        self.query: ChartQuery | None = None
        self._closed = False

    def _assert_owner(self):
        if get_ident() != self._owner:
            raise RuntimeError("Запросами и состоянием управляет только поток владельца.")

    @property
    def latest_id(self):
        return self._latest

    @property
    def idle(self):
        with self._lock:
            return not self._jobs and not self._operations

    def submit_operation(self, operation) -> Future:
        """Операция Application в том же пуле, независимо от отмены графика.

        Future опрашивает владелец. Callback не обращается к GUI. Операции
        предпочтений не попадают в очередь результатов графика.
        """
        self._assert_owner()
        if self._closed:
            raise RuntimeError("Приём задач завершён.")
        with self._lock:
            future = self._pool.submit(operation)
            self._operations.add(future)
            future.add_done_callback(self._operation_completed)
        return future

    def _operation_completed(self, future):
        with self._lock:
            self._operations.discard(future)

    @property
    def closed(self):
        return self._closed

    def invalidate(self):
        self._assert_owner()
        self._latest = None
        self.query = None
        self._deferred = None
        with self._lock:
            for future, event in tuple(self._jobs.items()):
                event.set()
                future.cancel()

    def request(self, query: ChartQuery) -> str:
        self._assert_owner()
        if self._closed:
            raise RuntimeError("Приём запросов завершён.")
        if not isinstance(query, ChartQuery):
            raise DomainValidationError("Необходим неизменяемый запрос графика.")
        self.invalidate()
        self._latest = request_id = uuid4().hex
        self.query = query
        cancel = Event()
        with self._lock:
            future = self._pool.submit(self._work, request_id, query, cancel)
            self._jobs[future] = cancel
            future.add_done_callback(self._completed)
        return request_id

    def _work(self, request_id, query, cancel):
        def checkpoint():
            if cancel.is_set():
                raise CancelledError()
        checkpoint()
        token = self.storage.capture_token()
        try:
            def snapshot_ready(snapshot_token):
                nonlocal token
                token = snapshot_token
            result = self.preparation.prepare(query, checkpoint, snapshot_ready)
            # Даже завершившаяся вопреки отмене задача обязана пройти apply.
            return ChartOutcome(request_id, result.token, result=result)
        except CancelledError:
            raise
        except (StorageError, DomainValidationError) as error:
            code = 'storage' if isinstance(error, StorageError) else 'validation'
            return ChartOutcome(request_id, token, failure=ChartFailure(code,
                "Не удалось подготовить график. Текущее отображение сохранено; повторите запрос."))
        except Exception:
            # Исключения и их тексты не передаются в UI и не журналируются.
            return ChartOutcome(request_id, token, failure=ChartFailure('preparation',
                "Ошибка подготовки графика. Текущее отображение сохранено; повторите запрос."))

    def _completed(self, future):
        try:
            if not future.cancelled():
                try:
                    outcome = future.result()
                except CancelledError:
                    pass
                else:
                    self._queue.put(outcome)
        finally:
            with self._lock:
                self._jobs.pop(future, None)

    def take_completed(self) -> tuple[ChartOutcome, ...]:
        self._assert_owner()
        outcomes = []
        while True:
            try:
                outcomes.append(self._queue.get_nowait())
            except Empty:
                return tuple(outcomes)

    def apply(self, outcome: ChartOutcome, on_result, on_failure) -> bool | None:
        """Проверяет прямо перед коротким потребителем в потоке владельца."""
        self._assert_owner()
        if self._closed or outcome.request_id != self._latest:
            return False
        def consume():
            # Повторная проверка непосредственно в атомарном участке.
            if not self._closed and outcome.request_id == self._latest:
                (on_failure(outcome.failure) if outcome.failure is not None else on_result(outcome.result))
        return self.storage.apply_if_current(outcome.token, consume, require_ready=outcome.failure is None)

    def dispatch(self, on_result, on_failure):
        self._assert_owner()
        candidates = ((self._deferred,) if self._deferred is not None else ()) + self.take_completed()
        self._deferred = None
        for outcome in candidates:
            status = self.apply(outcome, on_result, on_failure)
            if status is None:
                self._deferred = outcome

    def shutdown(self, *, wait=False):
        self._assert_owner()
        if not self._closed:
            self._closed = True
            self.invalidate()
        # invalidate уже отменил ожидающие графики. Запись предпочтений
        # нельзя отменить вслед за графиком или при завершении приложения.
        self._pool.shutdown(wait=wait, cancel_futures=False)
