import json
import datetime
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def jobs_path(tmp_path, monkeypatch):
    p = tmp_path / "device_review_jobs.json"
    monkeypatch.setattr("app.device_review_scheduler._JOBS_PATH", p)
    return p


def test_get_all_jobs_empty(jobs_path):
    from app import device_review_scheduler as sched
    assert sched.get_all_jobs() == []


def test_create_job_assigns_id(jobs_path):
    from app import device_review_scheduler as sched
    job = sched.create_job({
        "name": "Test Job",
        "adom": "TEST",
        "days_of_week": ["MON"],
        "time": "06:00",
        "checks": [],
        "check_params": {},
        "format": "pdf",
        "email": "x@x.com",
        "enabled": True,
    })
    assert "id" in job
    assert len(sched.get_all_jobs()) == 1


def test_create_job_persists_all_fields(jobs_path):
    from app import device_review_scheduler as sched
    job = sched.create_job({
        "name": "CIS Audit",
        "adom": "Enterprise",
        "days_of_week": ["MON", "FRI"],
        "time": "02:00",
        "checks": ["ntp_config", "trusted_hosts"],
        "check_params": {"ntp_config": {"expected_servers": "10.1.1.1"}},
        "format": "csv",
        "email": "alice@corp.com, bob@corp.com",
        "enabled": True,
    })
    stored = sched.get_all_jobs()[0]
    assert stored["name"] == "CIS Audit"
    assert stored["checks"] == ["ntp_config", "trusted_hosts"]
    assert stored["check_params"] == {"ntp_config": {"expected_servers": "10.1.1.1"}}
    assert stored["email"] == "alice@corp.com, bob@corp.com"
    assert stored["days_of_week"] == ["MON", "FRI"]


def test_update_job(jobs_path):
    from app import device_review_scheduler as sched
    job = sched.create_job({
        "name": "Old Name", "adom": "TEST", "days_of_week": ["MON"],
        "time": "06:00", "checks": [], "check_params": {},
        "format": "pdf", "email": "x@x.com", "enabled": True,
    })
    updated = sched.update_job(job["id"], {**job, "email": "new@x.com", "name": "New Name"})
    assert updated["email"] == "new@x.com"
    assert updated["name"] == "New Name"
    assert sched.get_all_jobs()[0]["email"] == "new@x.com"


def test_delete_job(jobs_path):
    from app import device_review_scheduler as sched
    job = sched.create_job({
        "name": "Test", "adom": "TEST", "days_of_week": ["MON"],
        "time": "06:00", "checks": [], "check_params": {},
        "format": "pdf", "email": "x@x.com", "enabled": True,
    })
    sched.delete_job(job["id"])
    assert sched.get_all_jobs() == []


def test_delete_job_unknown_raises(jobs_path):
    from app import device_review_scheduler as sched
    with pytest.raises(KeyError):
        sched.delete_job("nonexistent-id")


def test_validate_empty_days(jobs_path):
    from app import device_review_scheduler as sched
    with pytest.raises(ValueError, match="days_of_week"):
        sched.create_job({
            "name": "T", "adom": "TEST", "days_of_week": [], "time": "06:00",
            "checks": [], "check_params": {}, "format": "pdf",
            "email": "x@x.com", "enabled": True,
        })


def test_validate_invalid_day_code(jobs_path):
    from app import device_review_scheduler as sched
    with pytest.raises(ValueError, match="days_of_week"):
        sched.create_job({
            "name": "T", "adom": "TEST", "days_of_week": ["MONDAY"], "time": "06:00",
            "checks": [], "check_params": {}, "format": "pdf",
            "email": "x@x.com", "enabled": True,
        })


def test_validate_bad_time_format(jobs_path):
    from app import device_review_scheduler as sched
    with pytest.raises(ValueError, match="time"):
        sched.create_job({
            "name": "T", "adom": "TEST", "days_of_week": ["MON"], "time": "6am",
            "checks": [], "check_params": {}, "format": "pdf",
            "email": "x@x.com", "enabled": True,
        })


def test_is_job_running_false_initially(jobs_path):
    from app import device_review_scheduler as sched
    assert sched.is_job_running("any-id") is False


def test_prune_old_runs(jobs_path):
    from app import device_review_scheduler as sched
    old_ts = (datetime.datetime.utcnow() - datetime.timedelta(days=40)).isoformat() + "Z"
    recent_ts = datetime.datetime.utcnow().isoformat() + "Z"
    job = sched.create_job({
        "name": "T", "adom": "TEST", "days_of_week": ["MON"], "time": "06:00",
        "checks": [], "check_params": {}, "format": "pdf",
        "email": "x@x.com", "enabled": True,
    })
    jobs = json.loads(jobs_path.read_text())
    jobs[0]["runs"] = [
        {"ran_at": old_ts, "status": "ok", "devices_total": 1, "devices_reviewed": 1,
         "total_findings": 5, "fail_count": 1},
        {"ran_at": recent_ts, "status": "ok", "devices_total": 2, "devices_reviewed": 2,
         "total_findings": 3, "fail_count": 0},
    ]
    jobs_path.write_text(json.dumps(jobs))
    sched._prune_runs(job["id"], retention_days=30)
    remaining = sched.get_all_jobs()[0]["runs"]
    assert len(remaining) == 1
    assert remaining[0]["ran_at"] == recent_ts


def test_execute_job_sends_email(jobs_path, monkeypatch):
    from app import device_review_scheduler as sched

    job = sched.create_job({
        "name": "T", "adom": "CorpADOM", "days_of_week": ["MON"], "time": "06:00",
        "checks": ["trusted_hosts"], "check_params": {},
        "format": "pdf", "email": "test@corp.com", "enabled": True,
    })

    fake_results = [
        {"device": "fw-01", "ip": "10.0.0.1",
         "rows": [{"device": "fw-01", "check": "Trusted Hosts on Admin Accounts (CIS)",
                   "result": "PASS", "interface": "system", "vdom": "root",
                   "ip": "", "detail": "All admins have trusted hosts",
                   "protocols": [], "has_insecure": False, "has_secure": False}],
         "error": None},
    ]

    sent = {}

    def fake_bulk(adom, checks, check_params, max_workers=4):
        return fake_results

    def fake_send(to, subject, body_html, attachments):
        sent["to"] = to
        sent["subject"] = subject
        sent["attachments"] = attachments

    monkeypatch.setattr(
        "app.device_review_scheduler._bulk_device_review_adom", fake_bulk
    )
    monkeypatch.setattr("app.device_review_scheduler._send_email", fake_send)

    sched._execute_job(job["id"])

    assert sent["to"] == "test@corp.com"
    assert "CorpADOM" in sent["subject"]
    assert len(sent["attachments"]) == 1


def test_execute_job_appends_run_record(jobs_path, monkeypatch):
    from app import device_review_scheduler as sched

    job = sched.create_job({
        "name": "T", "adom": "CorpADOM", "days_of_week": ["MON"], "time": "06:00",
        "checks": [], "check_params": {}, "format": "pdf",
        "email": "test@corp.com", "enabled": True,
    })

    monkeypatch.setattr(
        "app.device_review_scheduler._bulk_device_review_adom",
        lambda *a, **kw: [],
    )
    monkeypatch.setattr(
        "app.device_review_scheduler._send_email",
        lambda *a, **kw: None,
    )

    sched._execute_job(job["id"])

    runs = sched.get_all_jobs()[0]["runs"]
    assert len(runs) == 1
    assert runs[0]["status"] == "ok"
    assert "ran_at" in runs[0]


def test_build_attachment_json(jobs_path):
    from app import device_review_scheduler as sched
    rows = [{"device": "fw-01", "check": "NTP", "result": "PASS",
             "interface": "system", "vdom": "root", "ip": "", "detail": "ok",
             "protocols": [], "has_insecure": False, "has_secure": False}]
    results = [{"device": "fw-01", "ip": "10.0.0.1", "rows": rows, "error": None}]
    att = sched._build_attachment_dr("Corp", "json", results, "2026-08-01T00:00:00Z")
    data = json.loads(att["data"])
    assert data["adom"] == "Corp"
    assert data["exported_at"] == "2026-08-01T00:00:00Z"
    assert len(data["rows"]) == 1


def test_build_attachment_csv(jobs_path):
    from app import device_review_scheduler as sched
    rows = [{"device": "fw-01", "check": "NTP", "result": "PASS",
             "interface": "system", "vdom": "root", "ip": "", "detail": "ok",
             "protocols": [], "has_insecure": False, "has_secure": False}]
    results = [{"device": "fw-01", "ip": "10.0.0.1", "rows": rows, "error": None}]
    att = sched._build_attachment_dr("Corp", "csv", results, "2026-08-01T00:00:00Z")
    text = att["data"].decode()
    assert "Corp" in text
    assert "fw-01" in text
    assert "PASS" in text


def test_build_attachment_pdf_html(jobs_path):
    from app import device_review_scheduler as sched
    rows = [{"device": "fw-01", "check": "NTP", "result": "FAIL",
             "interface": "system", "vdom": "root", "ip": "", "detail": "No NTP",
             "protocols": [], "has_insecure": False, "has_secure": False}]
    results = [{"device": "fw-01", "ip": "10.0.0.1", "rows": rows, "error": None}]
    att = sched._build_attachment_dr("Corp", "pdf", results, "2026-08-01T00:00:00Z")
    html = att["data"].decode()
    assert "Corp" in html
    assert "4THealth" in html
    assert "fw-01" in html
