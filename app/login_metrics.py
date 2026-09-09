import sqlite3
import time
from pathlib import Path

_DEFAULT_DB_PATH = str(Path(__file__).parent.parent / 'login_events.db')

_RANGES = {
    '1h':  {'bucket': 60,    'lookback': 3_600},
    '4h':  {'bucket': 300,   'lookback': 14_400},
    '12h': {'bucket': 600,   'lookback': 43_200},
    '1d':  {'bucket': 900,   'lookback': 86_400},
    '7d':  {'bucket': 3_600, 'lookback': 604_800},
    '14d': {'bucket': 7_200, 'lookback': 1_209_600},
}


def init_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS login_events (
            ts      INTEGER NOT NULL,
            success INTEGER NOT NULL
        )
    ''')
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_login_ts ON login_events(ts)'
    )
    conn.commit()
    conn.close()


def record_event(success: bool, db_path: str = None) -> None:
    path = db_path or _DEFAULT_DB_PATH
    try:
        conn = sqlite3.connect(path)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute(
            'INSERT INTO login_events (ts, success) VALUES (?, ?)',
            (int(time.time()), int(bool(success)))
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_metrics(range_key: str, db_path: str = None) -> dict:
    path = db_path or _DEFAULT_DB_PATH
    if not Path(path).exists():
        return {'success': [], 'failed': []}
    cfg = _RANGES.get(range_key) or _RANGES['1h']
    bucket = cfg['bucket']
    since = int(time.time()) - cfg['lookback']
    try:
        conn = sqlite3.connect(path)
        conn.execute('PRAGMA journal_mode=WAL')
        rows = conn.execute(
            '''
            SELECT
                (ts / :bucket) * :bucket AS bucket_ts,
                SUM(success)             AS ok_count,
                SUM(1 - success)         AS fail_count
            FROM login_events
            WHERE ts >= :since
            GROUP BY bucket_ts
            ORDER BY bucket_ts
            ''',
            {'bucket': bucket, 'since': since}
        ).fetchall()
        conn.close()
        return {
            'success': [{'ts': r[0], 'v': r[1]} for r in rows],
            'failed':  [{'ts': r[0], 'v': r[2]} for r in rows],
        }
    except Exception:
        return {'success': [], 'failed': []}


def prune_old_data(db_path: str = None) -> None:
    path = db_path or _DEFAULT_DB_PATH
    cutoff = int(time.time()) - 90 * 86_400
    try:
        conn = sqlite3.connect(path)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('DELETE FROM login_events WHERE ts < ?', (cutoff,))
        conn.commit()
        conn.close()
    except Exception:
        pass


def init_scheduler(app) -> None:
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(prune_old_data, 'cron', hour=3, minute=30)
    scheduler.start()
    init_db(_DEFAULT_DB_PATH)
