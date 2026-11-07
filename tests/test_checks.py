"""pytest entry point: every check_*.py script runs in its own interpreter.

The scripts print one line per check (OK / FAIL) and exit non-zero on a
failure; they also run by hand: python tests/check_louvers.py

With CHECKS_REPORT set, one JSON line per script is appended to that file:
how many of its checks passed and failed. scripts/ci_results.py turns the
reports of a CI run into its summary and the README badges.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = sorted(p.name for p in HERE.glob("check_*.py"))
REPORT = os.environ.get("CHECKS_REPORT")


def _report(**record) -> None:
    if REPORT:
        with open(REPORT, "a", encoding="utf-8") as file:
            file.write(json.dumps(record) + "\n")


@pytest.fixture(scope="session", autouse=True)
def _report_homeassistant():
    try:
        from homeassistant.const import __version__
    except ImportError:
        __version__ = None
    _report(homeassistant=__version__)


@pytest.mark.parametrize("script", SCRIPTS)
def test_check_script(script: str) -> None:
    try:
        proc = subprocess.run(
            [sys.executable, str(HERE / script)],
            cwd=HERE.parent, capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        _report(script=script, passed=0, failed=1, ok=False)
        raise
    output = proc.stdout + proc.stderr
    lines = proc.stdout.splitlines()
    passed = sum(line.startswith("OK ") for line in lines)
    failed = [line for line in lines if line.startswith("FAIL ")]
    ok = proc.returncode == 0 and "FAILS: 0" in output
    # a script that broke before printing a FAIL line counts as one failed check
    _report(script=script, passed=passed, failed=len(failed) or (0 if ok else 1), ok=ok)
    assert ok, "\n".join(failed) or output[-4000:]
