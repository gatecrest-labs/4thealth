import json
import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.fixture
def jobs_path(tmp_path, monkeypatch):
    p = tmp_path / "config_diff_jobs.json"
    monkeypatch.setattr("app.config_diff_scheduler._JOBS_PATH", p)
    return p


def test_get_all_jobs_empty(jobs_path):
    from app import config_diff_scheduler as sched
    assert sched.get_all_jobs() == []


def test_create_job_assigns_id(jobs_path):
    from app import config_diff_scheduler as sched
    job = sched.create_job({
        "adom": "TEST", "day_of_week": "MON", "time": "06:00",
        "format": "pdf", "email": "x@x.com", "enabled": True
    })
    assert "id" in job
    assert len(sched.get_all_jobs()) == 1


def test_update_job(jobs_path):
    from app import config_diff_scheduler as sched
    job = sched.create_job({"adom": "TEST", "day_of_week": "MON", "time": "06:00",
                             "format": "pdf", "email": "x@x.com", "enabled": True})
    updated = sched.update_job(job["id"], {**job, "email": "new@x.com"})
    assert updated["email"] == "new@x.com"
    assert sched.get_all_jobs()[0]["email"] == "new@x.com"


def test_delete_job(jobs_path):
    from app import config_diff_scheduler as sched
    job = sched.create_job({"adom": "TEST", "day_of_week": "MON", "time": "06:00",
                             "format": "pdf", "email": "x@x.com", "enabled": True})
    sched.delete_job(job["id"])
    assert sched.get_all_jobs() == []


def test_prune_old_runs(jobs_path):
    from app import config_diff_scheduler as sched
    import datetime
    old_ts = (datetime.datetime.utcnow() - datetime.timedelta(days=40)).isoformat() + "Z"
    recent_ts = datetime.datetime.utcnow().isoformat() + "Z"
    job = sched.create_job({"adom": "TEST", "day_of_week": "MON", "time": "06:00",
                             "format": "pdf", "email": "x@x.com", "enabled": True})
    # Manually inject run history with one old and one recent entry
    jobs = json.loads(jobs_path.read_text())
    jobs[0]["runs"] = [
        {"ran_at": old_ts, "status": "ok", "devices_total": 1, "devices_with_changes": 0},
        {"ran_at": recent_ts, "status": "ok", "devices_total": 1, "devices_with_changes": 1},
    ]
    jobs_path.write_text(json.dumps(jobs))
    sched._prune_runs(job["id"], retention_days=30)
    remaining = sched.get_all_jobs()[0]["runs"]
    assert len(remaining) == 1
    assert remaining[0]["ran_at"] == recent_ts
