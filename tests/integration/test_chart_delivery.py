from concurrent.futures import ThreadPoolExecutor
from threading import Event

from healthtracker.infrastructure.sqlite.database import Database


def test_atomic_delivery_cannot_interleave_with_commit(db):
    token=db.capture_token()
    attempt=Event();committed=Event();start=Event()
    def writer():
        assert start.wait(2)
        attempt.set()
        with db.write() as session: session.settings.set('compact_mode',False)
        committed.set()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(writer)
        def apply():
            start.set()
            assert attempt.wait(2)
            assert not committed.is_set()
        assert db.apply_if_current(token,apply) is True
        future.result(timeout=3)
    assert db.apply_if_current(token,lambda:None) is False


def test_delivery_does_not_wait_for_busy_database_coordinator(db):
    locked=Event();release=Event();called=[]
    token=db.capture_token()
    def writer():
        with db.write() as session:
            locked.set()
            assert release.wait(3)
            session.settings.set('compact_mode',False)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(writer)
        try:
            assert locked.wait(2)
            assert db.apply_if_current(token,lambda:called.append(1)) is None
            assert called==[] and not future.done()
        finally: release.set()
        future.result(timeout=3)
    assert db.apply_if_current(token,lambda:called.append(1)) is False


def test_closed_or_reopened_database_is_not_treated_as_current_data(db):
    token=db.capture_token();called=[]
    db.close()
    assert db.apply_if_current(token,lambda:called.append('data')) is False
    # Ошибка текущего запроса может сообщить о неисправной/недоступной базе.
    assert db.apply_if_current(token,lambda:called.append('error'),require_ready=False) is True
    db.initialize()
    assert db.apply_if_current(token,lambda:called.append('old'),require_ready=False) is False
    assert called==['error']
