"""Tests to ensure codebase quality and compliance with Ruff linter & formatter."""

from __future__ import annotations

import shutil
import subprocess
import sys
import unittest


class TestCodeQuality(unittest.TestCase):
    """Verify that python files pass ruff check and ruff format --check."""

    def setUp(self) -> None:
        """Skip tests if ruff is not available in the environment."""
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "--version"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 and not shutil.which("ruff"):
            raise unittest.SkipTest("Ruff is not installed in this environment.")

    def test_ruff_lint(self) -> None:
        """Ensure ruff check passes without any violations."""
        cmd = [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "custom_components",
            "tests",
        ]
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        self.assertEqual(
            result.returncode,
            0,
            f"Ruff linter found violations:\n{result.stdout}\n{result.stderr}",
        )

    def test_ruff_format(self) -> None:
        """Ensure all python files adhere to ruff formatting standards."""
        cmd = [
            sys.executable,
            "-m",
            "ruff",
            "format",
            "--check",
            "custom_components",
            "tests",
        ]
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        self.assertEqual(
            result.returncode,
            0,
            (
                "Ruff formatter found unformatted files. "
                "Run 'python -m ruff format custom_components tests' to auto-fix:\n"
                f"{result.stdout}\n{result.stderr}"
            ),
        )


if __name__ == "__main__":
    unittest.main()
