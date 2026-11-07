from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError,replace
from datetime import UTC,date,datetime,timedelta
from threading import Event,RLock,get_ident
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from healthtracker.application.analytics import AnalyticsResult
from healthtracker.application.chart_requests import ChartFailure,ChartOutcome,ChartRequests
from healthtracker.application.charts import ChartQuery,ChartResult
from healthtracker.application.storage import SnapshotToken
from healthtracker.domain.analytics import AnalyticsData,AnalysisContext,Indicator,period_statistics
from healthtracker.domain.charts import PreparedChart,SeriesKind,chart_mode
from healthtracker.domain.factors import sleep_comparison,gym_comparison
from healthtracker.domain.periods import DateRange

CONTEXT=AnalysisContext(datetime(2026,11,4,12,tzinfo=UTC),UTC)
QUERY=ChartQuery(DateRange(date(2026,11,1),date(2026,11,1)),CONTEXT)


class MemoryStorage:
    def __init__(self):
        self.token=SnapshotToken('synthetic',0)
        self.lock=RLock()
    def capture_token(self):
        with self.lock: return self.token
    def apply_if_current(self,token,action,*,require_ready=True):
        if not self.lock.acquire(blocking=False): return None
        try:
            if token!=self.token: return False
            action()
            return True
        finally: self.lock.release()


def result(query,token):
    data=AnalyticsData()
    statistics=period_statistics(data,query.indicator,query.period,query.context)
    analytics=AnalyticsResult(token,statistics,sleep_comparison(data,query.period,query.context),gym_comparison(data,query.period,query.context))
    return ChartResult(query,token,PreparedChart(query.period,query.context,chart_mode(query.period,query.compact),query.line_gap_hours,(),(),()),analytics)


class ControlledPreparation:
    """Имитирует непрерываемую фазу: отмена не препятствует доставке исхода."""
    def __init__(self,queries):
        self.storage=MemoryStorage()
        self.analytics=SimpleNamespace(storage=self.storage)
        self.started={q:Event() for q in queries}
        self.allow={q:Event() for q in queries}
        self.fail={}
        self.threads={}
    def prepare(self,query,checkpoint,snapshot_ready):
        token=self.storage.capture_token()
        snapshot_ready(token)
        self.threads[query]=get_ident()
        self.started[query].set()
        assert self.allow[query].wait(5)
        if query in self.fail: raise self.fail[query]
        return result(query,token)


def job_finished(requests):
    # Регистрируется, пока задача удерживается Event. Callback идёт после
    # callback контроллера и тем самым доказывает завершение доставки в очередь.
    with requests._lock: future=tuple(requests._jobs)[-1]
    event=Event()
    future.add_done_callback(lambda _:event.set())
    return future,event


def release_all(preparation,requests):
    for event in preparation.allow.values(): event.set()
    requests.shutdown(wait=True)


@pytest.mark.parametrize('change',[
    dict(compact=False),dict(indicator=Indicator.LEARNING),dict(line_gap_hours=2),
    dict(visible_series=(SeriesKind.MOOD,)),dict(context=AnalysisContext(CONTEXT.now,ZoneInfo('Europe/Berlin'))),
    dict(period=DateRange(date(2026,10,31),date(2026,11,1))),
])
def test_async01_a_finishes_after_b_and_cannot_replace_b(change):
    b=replace(QUERY,**change)
    preparation=ControlledPreparation((QUERY,b))
    requests=ChartRequests(preparation)
    applied,errors=[],[]
    try:
        a_id=requests.request(QUERY)
        assert preparation.started[QUERY].wait(2)
        _,a_done=job_finished(requests)
        b_id=requests.request(b)
        assert preparation.started[b].wait(2)
        _,b_done=job_finished(requests)
        assert a_id!=b_id
        preparation.allow[b].set()
        assert b_done.wait(2)
        requests.dispatch(applied.append,errors.append)
        assert len(applied)==1 and applied[0].query==b
        preparation.allow[QUERY].set()
        assert a_done.wait(2)
        stale=requests.take_completed()
        assert len(stale)==1 and stale[0].request_id==a_id and stale[0].result is not None
        assert requests.apply(stale[0],applied.append,errors.append) is False
        assert len(applied)==1 and applied[0].query==b and errors==[]
        assert set(preparation.threads.values())!={get_ident()}
    finally: release_all(preparation,requests)


def test_late_failure_of_a_does_not_replace_success_of_b():
    b=replace(QUERY,compact=False)
    preparation=ControlledPreparation((QUERY,b));preparation.fail[QUERY]=RuntimeError('private synthetic text')
    requests=ChartRequests(preparation);applied,errors=[],[]
    try:
        requests.request(QUERY);assert preparation.started[QUERY].wait(2)
        _,a_done=job_finished(requests)
        requests.request(b);assert preparation.started[b].wait(2)
        _,b_done=job_finished(requests)
        preparation.allow[b].set();assert b_done.wait(2)
        requests.dispatch(applied.append,errors.append)
        preparation.allow[QUERY].set();assert a_done.wait(2)
        requests.dispatch(applied.append,errors.append)
        assert len(applied)==1 and applied[0].query==b and errors==[]
    finally: release_all(preparation,requests)


@pytest.mark.parametrize('fail',[False,True])
@pytest.mark.parametrize('replacement',[SnapshotToken('synthetic',1),SnapshotToken('another',0)])
def test_stale_snapshot_or_database_drops_result_and_error(fail,replacement):
    preparation=ControlledPreparation((QUERY,))
    if fail: preparation.fail[QUERY]=RuntimeError('private synthetic text')
    requests=ChartRequests(preparation);applied,errors=[],[]
    try:
        requests.request(QUERY);assert preparation.started[QUERY].wait(2)
        _,done=job_finished(requests)
        preparation.storage.token=replacement
        preparation.allow[QUERY].set();assert done.wait(2)
        requests.dispatch(applied.append,errors.append)
        assert applied==errors==[]
    finally: release_all(preparation,requests)


def test_queued_outcome_is_checked_again_after_generation_changes():
    preparation=ControlledPreparation((QUERY,));requests=ChartRequests(preparation)
    try:
        requests.request(QUERY);assert preparation.started[QUERY].wait(2)
        _,done=job_finished(requests)
        preparation.allow[QUERY].set();assert done.wait(2)
        outcome=requests.take_completed()[0]
        preparation.storage.token=SnapshotToken('synthetic',1)
        assert requests.apply(outcome,lambda _:pytest.fail('stale'),lambda _:pytest.fail('stale')) is False
    finally: release_all(preparation,requests)


def test_latest_preparation_error_is_sanitized_and_returned():
    preparation=ControlledPreparation((QUERY,));preparation.fail[QUERY]=ValueError('private synthetic text')
    requests=ChartRequests(preparation);errors=[]
    try:
        requests.request(QUERY);assert preparation.started[QUERY].wait(2)
        _,done=job_finished(requests)
        preparation.allow[QUERY].set();assert done.wait(2)
        requests.dispatch(lambda _:pytest.fail('success'),errors.append)
        assert len(errors)==1 and errors[0].code=='preparation'
        assert 'private' not in errors[0].message
    finally: release_all(preparation,requests)


def test_waiting_superseded_request_is_cancelled_while_running_task_is_joined():
    b=replace(QUERY,line_gap_hours=2);c=replace(QUERY,line_gap_hours=1)
    preparation=ControlledPreparation((QUERY,b,c));requests=ChartRequests(preparation,max_workers=1)
    try:
        requests.request(QUERY);assert preparation.started[QUERY].wait(2)
        _,a_done=job_finished(requests)
        requests.request(b)
        future_b,_=job_finished(requests)
        requests.request(c)
        assert future_b.cancelled() and not preparation.started[b].is_set()
        requests.shutdown(wait=False)
        assert requests.closed and not requests.idle
        with pytest.raises(RuntimeError): requests.request(QUERY)
        preparation.allow[QUERY].set();assert a_done.wait(2)
        requests.shutdown(wait=True)
        assert requests.idle and not any(t.is_alive() for t in requests._pool._threads)
    finally: release_all(preparation,requests)


def test_controller_rejects_calls_from_non_owner_thread():
    preparation=ControlledPreparation((QUERY,));requests=ChartRequests(preparation)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with pytest.raises(RuntimeError): pool.submit(requests.request,QUERY).result(timeout=2)
    finally: requests.shutdown(wait=True)


def test_request_and_result_models_are_immutable_and_outcome_is_unambiguous():
    token=SnapshotToken('synthetic',0)
    data=result(QUERY,token)
    models=(QUERY,data,ChartFailure('error','safe'),ChartOutcome('one',token,result=data))
    for model in models:
        field=next(iter(model.__dataclass_fields__))
        with pytest.raises(FrozenInstanceError): setattr(model,field,None)
    with pytest.raises(ValueError): ChartOutcome('one',token)
    with pytest.raises(ValueError): ChartOutcome('one',token,result=data,failure=ChartFailure('error','safe'))


def test_busy_guard_defers_and_retries_without_waiting_or_losing_current_result():
    preparation=ControlledPreparation((QUERY,));requests=ChartRequests(preparation)
    locked,release=Event(),Event();applied=[]
    def busy():
        with preparation.storage.lock:
            locked.set()
            assert release.wait(3)
    try:
        requests.request(QUERY);assert preparation.started[QUERY].wait(2)
        _,done=job_finished(requests)
        preparation.allow[QUERY].set();assert done.wait(2)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(busy)
            try:
                assert locked.wait(2)
                requests.dispatch(applied.append,lambda _:pytest.fail('error'))
                assert applied==[] and not future.done()
            finally: release.set()
            future.result(timeout=3)
        requests.dispatch(applied.append,lambda _:pytest.fail('error'))
        assert len(applied)==1 and applied[0].query==QUERY
    finally: release_all(preparation,requests)
