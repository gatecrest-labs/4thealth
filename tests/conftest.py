import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def app_ctx():
    from app import create_app

    app = create_app(test_config={"TESTING": True})
    with app.app_context():
        yield app


@pytest.fixture(autouse=True)
def _isolated_fmg_staging_lock(tmp_path, monkeypatch):
    """Point the FMG staging lock at a per-test temp file.

    The real lock lives in the shared system temp dir and persists between
    runs; on a CI runner it can be owned by another user (-> Errno 13) or be
    held by a concurrent job.  Tests must never touch it.
    """
    import app.fmg_client as fc

    monkeypatch.setattr(fc, "STAGING_LOCK_PATH", str(tmp_path / "fmg_staging.lock"))
