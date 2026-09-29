"""
4-thread stress test for SQLiteHandler to check for thread safety and race conditions.
"""
import logging
import threading

from app.utils.constants import MONITOR_TYPE_INSTANT
from app.utils.sqlite_handler import SQLiteHandler


def test_sqlite_handler_thread_safety():

    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger('test')
    h = SQLiteHandler(logger=logger, db_dir='testdb/dev')
    h.create_schema()

    # Insert a test monitor record so updates and reads are operating on an actual row
    monitor_id = h.add_monitor(
        name='thread_safety_monitor',
        monitor_path='/tmp/test',
        remote_path='remote:/test',
        monitor_type=MONITOR_TYPE_INSTANT,
        config={},
        status='stopped',
    )
    assert monitor_id is not None

    errs = []
    def work(n):
        try:
            for i in range(25):
                status_val = 'running' if i % 2 == 0 else 'stopped'
                h.update_monitor_status(monitor_id=monitor_id, status=status_val)
                mon = h.get_monitor(monitor_id=monitor_id)
                assert mon is not None and mon.get('id') == monitor_id
                _ = h.get_monitors()
        except Exception as e:  # noqa: BLE001
            errs.append((n, str(e)))

    threads = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print('errors:', errs if errs else 'NONE')
    final_status = h.get_monitor(monitor_id=monitor_id).get('status')
    print('monitor status:', final_status)
    assert errs == [], f"Expected no errors, got {errs}"
    assert final_status in ('running', 'stopped')

    # Cleanup test monitor
    h.delete_monitor(monitor_id)
    h.close()

if __name__ == "__main__":
    # Allows running directly with `python3 -m tests.thread_stress_test` too
    test_sqlite_handler_thread_safety()
