import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Must be set before any app module is imported — config.py reads SECRET_KEY
# at class-body time and raises if it is missing or the default value.
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")
