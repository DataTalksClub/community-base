"""The importer must use a consumer-owned events app without package model imports."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("mode", ["empty", "instructors"])
def test_import_uses_the_installed_events_model(mode):
    result = subprocess.run(
        [sys.executable, "-m", "tests.curriculum.host_adapter.probe", mode],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "site-events-import-passed"
