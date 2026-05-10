# Root conftest.py — ensures the project root is on sys.path for all test runs.
import sys
from pathlib import Path

# Make ``import src.*`` and ``import protocol.*`` work from any pytest invocation
# directory without requiring an editable install.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
