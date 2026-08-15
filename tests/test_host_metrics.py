import sqlite3
import time
import pytest


@pytest.fixture
def db(tmp_path):
    from app.host_metrics import init_db
    path = str(tmp_path / 'test.db')
    init_db(path)
    return path


def test_init_db_creates_table(db):
    conn = sqlite3.connect(db)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    conn.close()
    assert 'host_metrics' in tables


def test_init_db_creates_index(db):
    conn = sqlite3.connect(db)
    indexes = [r[1] for r in conn.execute(
        "SELECT * FROM sqlite_master WHERE type='index'"
    ).fetchall()]
    conn.close()
    assert 'idx_ts' in indexes


def test_record_sample_inserts_row(db):
    from app.host_metrics import record_sample
    record_sample(db)
    conn = sqlite3.connect(db)
    rows = conn.execute('SELECT ts, cpu, mem, disk FROM host_metrics').fetchall()
    conn.close()
    assert len(rows) == 1
    ts, cpu, mem, disk = rows[0]
    assert isinstance(ts, int) and ts > 0
    assert 0.0 <= cpu <= 100.0
    assert 0.0 <= mem <= 100.0
    assert 0.0 <= disk <= 100.0


def test_get_metrics_returns_structure(db):
    from app.host_metrics import get_metrics
    now = int(time.time())
    conn = sqlite3.connect(db)
    for i in range(5):
        conn.execute('INSERT INTO host_metrics VALUES (?,?,?,?)',
                     (now - i * 60, 20.0, 50.0, 30.0))
    conn.commit()
    conn.close()

    result = get_metrics('1h', db)
    assert set(result.keys()) == {'cpu', 'mem', 'disk'}
    assert len(result['cpu']) > 0
    for point in result['cpu']:
        assert 'ts' in point and 'v' in point


def test_get_metrics_unknown_range_defaults_to_1h(db):
    from app.host_metrics import get_metrics
    now = int(time.time())
    conn = sqlite3.connect(db)
    conn.execute('INSERT INTO host_metrics VALUES (?,?,?,?)', (now - 60, 10.0, 40.0, 20.0))
    conn.commit()
    conn.close()
    result = get_metrics('bogus', db)
    assert 'cpu' in result


def test_get_metrics_7d_buckets_by_hour(db):
    from app.host_metrics import get_metrics
    now = int(time.time())
    conn = sqlite3.connect(db)
    # 4 rows within the same 1-hour bucket
    for i in range(4):
        conn.execute('INSERT INTO host_metrics VALUES (?,?,?,?)',
                     (now - i * 300, 40.0, 60.0, 50.0))
    conn.commit()
    conn.close()

    result = get_metrics('7d', db)
    assert len(result['cpu']) == 1
    assert result['cpu'][0]['v'] == pytest.approx(40.0, abs=0.1)


def test_prune_removes_old_rows(db):
    from app.host_metrics import prune_old_data
    now = int(time.time())
    old = now - (91 * 86400)  # 91 days ago, beyond 90-day retention
    conn = sqlite3.connect(db)
    conn.execute('INSERT INTO host_metrics VALUES (?,?,?,?)', (old, 10.0, 40.0, 20.0))
    conn.execute('INSERT INTO host_metrics VALUES (?,?,?,?)', (now - 60, 10.0, 40.0, 20.0))
    conn.commit()
    conn.close()

    prune_old_data(db)

    conn = sqlite3.connect(db)
    rows = conn.execute('SELECT ts FROM host_metrics').fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == now - 60
