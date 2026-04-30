from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def main() -> int:
    test_file = Path(__file__).with_name("tests.py")
    cmd = [sys.executable, "-m", "pytest", str(test_file), "-q"]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
