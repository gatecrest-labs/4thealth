import os
import sys
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")
sys.path.insert(0, str(Path(__file__).parent.parent))
