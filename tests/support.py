"""Shared test utilities."""

import tempfile

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def temporary_directory():
    """Create isolated test data under this checkout's ignored tmp folder."""
    temporary_root = PROJECT_ROOT / "tmp" / "tests"
    temporary_root.mkdir(parents=True, exist_ok=True)

    return tempfile.TemporaryDirectory(dir=temporary_root)
