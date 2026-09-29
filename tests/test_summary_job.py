"""Tests for HA/standalone bucketing in summary_job._run_job()."""

import importlib
from contextlib import contextmanager
from unittest.mock import MagicMock, patch


def _make_client_mock(adom_names, devices_by_adom):
    """Return a context-manager mock for make_client producing controlled data."""
    client = MagicMock()
    client.get_adoms.return_value = [{"name": n} for n in adom_names]
    client.get_devices.side_effect = lambda adom: devices_by_adom.get(adom, [])
    client.get_policy_packages.return_value = []

    @contextmanager
    def _ctx():
        yield client

    return _ctx


def _reset_store():
    """Re-import summary_job to get a clean module-level _store."""
    import app.summary_job as sj
    importlib.reload(sj)
    return sj


def test_ha_active_passive_counted_as_cluster():
    sj = _reset_store()
    devices = [{"name": "fw1", "ha_mode": 1}]
    ctx = _make_client_mock(["ADOM1"], {"ADOM1": devices})
    with patch("app.fmg_helpers.make_client", ctx):
        sj._run_job(app=None)
    result = sj.get_summary()
    assert result["ha_clusters"] == 1
    assert result["standalones"] == 0


def test_ha_active_active_counted_as_cluster():
    sj = _reset_store()
    devices = [{"name": "fw1", "ha_mode": 2}]
    ctx = _make_client_mock(["ADOM1"], {"ADOM1": devices})
    with patch("app.fmg_helpers.make_client", ctx):
        sj._run_job(app=None)
    result = sj.get_summary()
    assert result["ha_clusters"] == 1
    assert result["standalones"] == 0


def test_ha_mode_zero_counted_as_standalone():
    sj = _reset_store()
    devices = [{"name": "fw1", "ha_mode": 0}]
    ctx = _make_client_mock(["ADOM1"], {"ADOM1": devices})
    with patch("app.fmg_helpers.make_client", ctx):
        sj._run_job(app=None)
    result = sj.get_summary()
    assert result["ha_clusters"] == 0
    assert result["standalones"] == 1


def test_ha_mode_null_counted_as_standalone():
    sj = _reset_store()
    devices = [{"name": "fw1", "ha_mode": None}]
    ctx = _make_client_mock(["ADOM1"], {"ADOM1": devices})
    with patch("app.fmg_helpers.make_client", ctx):
        sj._run_job(app=None)
    result = sj.get_summary()
    assert result["ha_clusters"] == 0
    assert result["standalones"] == 1


def test_ha_mode_missing_counted_as_standalone():
    sj = _reset_store()
    devices = [{"name": "fw1"}]  # no ha_mode key at all
    ctx = _make_client_mock(["ADOM1"], {"ADOM1": devices})
    with patch("app.fmg_helpers.make_client", ctx):
        sj._run_job(app=None)
    result = sj.get_summary()
    assert result["ha_clusters"] == 0
    assert result["standalones"] == 1


def test_mixed_devices_across_adoms():
    sj = _reset_store()
    # ADOM1: 2 HA clusters, ADOM2: 1 standalone
    ctx = _make_client_mock(
        ["ADOM1", "ADOM2"],
        {
            "ADOM1": [{"name": "fw1", "ha_mode": 1}, {"name": "fw2", "ha_mode": 2}],
            "ADOM2": [{"name": "fw3", "ha_mode": 0}],
        },
    )
    with patch("app.fmg_helpers.make_client", ctx):
        sj._run_job(app=None)
    result = sj.get_summary()
    assert result["ha_clusters"] == 2
    assert result["standalones"] == 1
    assert result["firewalls_total"] == 3


def test_ha_clusters_and_standalones_sum_equals_firewalls_total():
    sj = _reset_store()
    ctx = _make_client_mock(
        ["ADOM1"],
        {
            "ADOM1": [
                {"name": "fw1", "ha_mode": 1},
                {"name": "fw2", "ha_mode": 0},
                {"name": "fw3"},
            ]
        },
    )
    with patch("app.fmg_helpers.make_client", ctx):
        sj._run_job(app=None)
    result = sj.get_summary()
    assert result["ha_clusters"] + result["standalones"] == result["firewalls_total"]
