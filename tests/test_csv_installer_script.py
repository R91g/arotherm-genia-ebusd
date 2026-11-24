"""Unit tests validating the eBUSd CSV installer/updater shell script."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "install_ebusd_csvs.sh"
CSV_ROOT = REPO_ROOT / "ebusd-configuration"


class TestCsvInstallerScript(unittest.TestCase):
    """Verify scripts/install_ebusd_csvs.sh stays in sync with ebusd-configuration/."""

    def test_script_exists_with_lf_line_endings_and_posix_shebang(self) -> None:
        self.assertTrue(SCRIPT_PATH.is_file(), "scripts/install_ebusd_csvs.sh missing")
        raw = SCRIPT_PATH.read_bytes()
        self.assertNotIn(
            b"\r\n",
            raw,
            "Shell script must use Unix LF line endings (not CRLF)",
        )
        first_line = raw.splitlines()[0].decode("utf-8")
        self.assertEqual(first_line, "#!/usr/bin/env sh")

    def test_csv_file_list_matches_repository_exactly(self) -> None:
        content = SCRIPT_PATH.read_text(encoding="utf-8")
        match = re.search(r'^CSV_FILES="\n(.*?)\n"$', content, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(match, "Could not locate CSV_FILES block in script")
        assert match is not None

        script_files = sorted(
            line.strip() for line in match.group(1).splitlines() if line.strip()
        )
        repo_files = sorted(
            p.relative_to(CSV_ROOT).as_posix() for p in CSV_ROOT.rglob("*.csv")
        )
        self.assertEqual(
            script_files,
            repo_files,
            "CSV_FILES in scripts/install_ebusd_csvs.sh is out of sync with ebusd-configuration/",
        )

    def test_all_listed_csvs_pass_script_header_validation(self) -> None:
        for csv_file in sorted(CSV_ROOT.rglob("*.csv")):
            text = csv_file.read_text(encoding="utf-8")
            self.assertTrue(
                re.search(r"^type,circuit,", text, re.MULTILINE),
                f"{csv_file.name} does not contain the 'type,circuit,' header expected by validate_csv()",
            )


if __name__ == "__main__":
    unittest.main()
