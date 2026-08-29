"""
4-thread stress test for SQLiteHandler to check for thread safety and race conditions.
"""
import logging
import threading

from scripts.sqlite_handler import SQLiteHandler

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger('test')
h = SQLiteHandler(logger=logger, db_dir='testdata/db/dev')
h.create_schema()

errs = []
def work(n):
    try:
        for i in range(20):
            h.update_monitor_status(monitor_id=5, status='running')
            m = h.get_monitor(monitor_id=5)
            _ = h.get_monitors()
    except Exception as e:
        errs.append((n, str(e)))

threads = [threading.Thread(target=work, args=(i,)) for i in range(4)]
for t in threads: t.start()
for t in threads: t.join()

print('errors:', errs if errs else 'NONE')
print('monitor status:', h.get_monitor(monitor_id=5).get('status'))
h.close()

