import os
import time
import pytest
from unittest.mock import patch


@pytest.fixture
def app():
    os.environ.setdefault("SECRET_KEY", "test-secret")
    os.environ.setdefault("FMG_PRIMARY_HOST", "127.0.0.1")
    from app import create_app
    return create_app({'TESTING': True})


@pytest.fixture
def admin_client(app):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user'] = 'testadmin'
        sess['role'] = 'admin'
        sess['allowed_tabs'] = ['admin']
        sess['login_at'] = int(time.time())
    return client


def test_login_metrics_endpoint_returns_200(admin_client):
    with patch('app.login_metrics.get_metrics',
               return_value={'success': [], 'failed': []}):
        resp = admin_client.get('/admin/api/login-metrics?range=1h')
    assert resp.status_code == 200


def test_login_metrics_endpoint_returns_success_and_failed_keys(admin_client):
    mock_data = {
        'success': [{'ts': 1000000, 'v': 3}],
        'failed':  [{'ts': 1000000, 'v': 1}],
    }
    with patch('app.login_metrics.get_metrics', return_value=mock_data):
        resp = admin_client.get('/admin/api/login-metrics?range=4h')
    data = resp.get_json()
    assert 'success' in data
    assert 'failed' in data
    assert data['success'] == [{'ts': 1000000, 'v': 3}]
    assert data['failed']  == [{'ts': 1000000, 'v': 1}]


def test_login_metrics_endpoint_includes_range_and_generated_at(admin_client):
    with patch('app.login_metrics.get_metrics',
               return_value={'success': [], 'failed': []}):
        resp = admin_client.get('/admin/api/login-metrics?range=7d')
    data = resp.get_json()
    assert data['range'] == '7d'
    assert isinstance(data['generated_at'], int)


def test_login_metrics_endpoint_requires_admin(app):
    client = app.test_client()  # no session — unauthenticated
    resp = client.get('/admin/api/login-metrics?range=1h')
    assert resp.status_code in (302, 401, 403)
