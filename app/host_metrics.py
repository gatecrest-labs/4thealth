import os
import sqlite3
import threading
import time
from contextlib import closing

import psutil
from apscheduler.schedulers.background import BackgroundScheduler

psutil.cpu_percent(interval=None)  # prime baseline; result discarded

_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "host_metrics.db")
_RETENTION_DAYS = 90

_BUCKETS = {
    "1h": {"window": 3_600, "bucket": 60},
    "4h": {"window": 14_400, "bucket": 300},
    "12h": {"window": 43_200, "bucket": 600},
    "1d": {"window": 86_400, "bucket": 900},
    "7d": {"window": 604_800, "bucket": 3_600},
    "14d": {"window": 1_209_600, "bucket": 7_200},
}


def init_db(db_path=None):
    path = db_path or _DB_PATH
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS host_metrics (
                ts    INTEGER NOT NULL,
                cpu   REAL,
                mem   REAL,
                disk  REAL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON host_metrics(ts)")
        conn.commit()


def record_sample(db_path=None):
    path = db_path or _DB_PATH
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage("/").percent
    ts = int(time.time())
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "INSERT INTO host_metrics (ts, cpu, mem, disk) VALUES (?, ?, ?, ?)",
            (ts, cpu, mem, disk),
        )
        conn.commit()


def get_metrics(range_key, db_path=None):
    path = db_path or _DB_PATH
    cfg = _BUCKETS.get(range_key, _BUCKETS["1h"])
    window = cfg["window"]
    bucket = cfg["bucket"]
    cutoff = int(time.time()) - window
    with closing(sqlite3.connect(path)) as conn:
        rows = conn.execute(
            "SELECT (ts / :bucket) * :bucket AS t, "
            "COALESCE(AVG(cpu), 0.0), COALESCE(AVG(mem), 0.0), COALESCE(AVG(disk), 0.0) "
            "FROM host_metrics WHERE ts >= :cutoff GROUP BY t ORDER BY t",
            {"bucket": bucket, "cutoff": cutoff},
        ).fetchall()
    return {
        "cpu": [{"ts": int(r[0]), "v": round(r[1], 1)} for r in rows],
        "mem": [{"ts": int(r[0]), "v": round(r[2], 1)} for r in rows],
        "disk": [{"ts": int(r[0]), "v": round(r[3], 1)} for r in rows],
    }


def prune_old_data(db_path=None):
    path = db_path or _DB_PATH
    cutoff = int(time.time()) - (_RETENTION_DAYS * 86400)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("DELETE FROM host_metrics WHERE ts < ?", (cutoff,))
        conn.commit()


def init_scheduler(app):
    init_db()
    threading.Thread(target=record_sample, daemon=True).start()
    scheduler = BackgroundScheduler()
    scheduler.add_job(record_sample, "interval", seconds=60, id="host_metrics_sample")
    scheduler.add_job(prune_old_data, "cron", hour=3, minute=0, id="host_metrics_prune")
    scheduler.start()
