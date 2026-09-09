import sqlite3
import time
import pytest


@pytest.fixture
def db(tmp_path):
    from app.login_metrics import init_db
    path = str(tmp_path / 'test.db')
    init_db(path)
    return path


def test_init_db_creates_table(db):
    conn = sqlite3.connect(db)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    conn.close()
    assert 'login_events' in tables


def test_init_db_creates_index(db):
    conn = sqlite3.connect(db)
    indexes = [r[1] for r in conn.execute(
        "SELECT * FROM sqlite_master WHERE type='index'"
    ).fetchall()]
    conn.close()
    assert 'idx_login_ts' in indexes


def test_record_event_success_stores_1(db):
    from app.login_metrics import record_event
    record_event(True, db)
    conn = sqlite3.connect(db)
    rows = conn.execute('SELECT ts, success FROM login_events').fetchall()
    conn.close()
    assert len(rows) == 1
    ts, success = rows[0]
    assert isinstance(ts, int) and ts > 0
    assert success == 1


def test_record_event_failure_stores_0(db):
    from app.login_metrics import record_event
    record_event(False, db)
    conn = sqlite3.connect(db)
    rows = conn.execute('SELECT success FROM login_events').fetchall()
    conn.close()
    assert rows[0][0] == 0


def test_record_event_bad_db_path_does_not_raise():
    from app.login_metrics import record_event
    # Must silently swallow the error
    record_event(True, '/no/such/directory/login.db')


def test_get_metrics_returns_success_and_failed_keys(db):
    from app.login_metrics import get_metrics
    result = get_metrics('1h', db)
    assert set(result.keys()) == {'success', 'failed'}


def test_get_metrics_counts_correctly(db):
    from app.login_metrics import get_metrics
    # Place all events in the same 60-second bucket
    bucket_start = (int(time.time()) // 60) * 60
    conn = sqlite3.connect(db)
    conn.execute('INSERT INTO login_events VALUES (?, 1)', (bucket_start + 10,))
    conn.execute('INSERT INTO login_events VALUES (?, 1)', (bucket_start + 20,))
    conn.execute('INSERT INTO login_events VALUES (?, 0)', (bucket_start + 30,))
    conn.commit()
    conn.close()

    result = get_metrics('1h', db)
    assert len(result['success']) > 0
    assert result['success'][0]['v'] == 2
    assert result['failed'][0]['v'] == 1


def test_get_metrics_each_point_has_ts_and_v(db):
    from app.login_metrics import get_metrics
    now = int(time.time())
    conn = sqlite3.connect(db)
    conn.execute('INSERT INTO login_events VALUES (?, 1)', (now - 60,))
    conn.commit()
    conn.close()
    result = get_metrics('1h', db)
    for point in result['success']:
        assert 'ts' in point and 'v' in point


def test_get_metrics_unknown_range_defaults_to_1h(db):
    from app.login_metrics import get_metrics
    now = int(time.time())
    conn = sqlite3.connect(db)
    conn.execute('INSERT INTO login_events VALUES (?, 1)', (now - 60,))
    conn.commit()
    conn.close()
    result = get_metrics('bogus', db)
    assert 'success' in result and 'failed' in result


def test_get_metrics_excludes_data_outside_lookback(db):
    from app.login_metrics import get_metrics
    old = int(time.time()) - 7201  # older than 1h lookback (3600s)
    conn = sqlite3.connect(db)
    conn.execute('INSERT INTO login_events VALUES (?, 1)', (old,))
    conn.commit()
    conn.close()
    result = get_metrics('1h', db)
    assert result['success'] == []


def test_prune_removes_rows_older_than_90_days(db):
    from app.login_metrics import prune_old_data
    now = int(time.time())
    old = now - (91 * 86400)
    conn = sqlite3.connect(db)
    conn.execute('INSERT INTO login_events VALUES (?, 1)', (old,))
    conn.execute('INSERT INTO login_events VALUES (?, 1)', (now - 60,))
    conn.commit()
    conn.close()

    prune_old_data(db)

    conn = sqlite3.connect(db)
    rows = conn.execute('SELECT ts FROM login_events').fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == now - 60
