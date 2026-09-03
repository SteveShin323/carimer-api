"""Regression coverage for safe pytest defaults."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]


def _collect(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", *args],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )


def test_live_tests_are_deselected_by_default_and_explicit_marker_overrides() -> None:
    default = _collect("tests/live")
    explicit = _collect("-m", "live", "tests/live")

    assert default.returncode == 5
    assert "deselected" in default.stdout
    assert explicit.returncode == 0
    assert "tests collected" in explicit.stdout
