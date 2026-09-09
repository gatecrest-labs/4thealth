import os
import pytest
from unittest.mock import patch


@pytest.fixture
def app():
    os.environ.setdefault("SECRET_KEY", "test-secret")
    os.environ.setdefault("FMG_PRIMARY_HOST", "127.0.0.1")
    from app import create_app
    return create_app({'TESTING': True})


@pytest.fixture
def client(app):
    return app.test_client()


def test_successful_login_calls_record_event_true(client):
    with client.session_transaction() as sess:
        sess["_csrf_token"] = "test-token"
    with patch('app.routes.auth_routes.authenticate', return_value=('admin', [])), \
         patch('app.routes.auth_routes.get_allowed_tabs', return_value=['admin']), \
         patch('app.login_metrics.record_event') as mock_record:
        client.post('/login', data={
            'username': 'testuser',
            'password': 'pass',
            'csrf_token': 'test-token',
        })
    mock_record.assert_called_once_with(True)


def test_failed_login_calls_record_event_false(client):
    with client.session_transaction() as sess:
        sess["_csrf_token"] = "test-token"
    with patch('app.routes.auth_routes.authenticate', return_value=None), \
         patch('app.login_metrics.record_event') as mock_record:
        client.post('/login', data={
            'username': 'testuser',
            'password': 'wrong',
            'csrf_token': 'test-token',
        })
    mock_record.assert_called_once_with(False)
