from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


SUITE = Path(__file__).resolve().parents[1]
CLIS = sorted((SUITE / skill / "scripts" / script) for skill, script in (
    ("invest-compare", "compare_artifacts.py"),
    ("invest-core", "invest_contracts.py"),
    ("invest-distribution", "capital_allocation.py"),
    ("invest-financials", "financial_model.py"),
    ("invest-framework", "bundle_validator.py"),
    ("invest-framework", "company_orchestrator.py"),
    ("invest-psychology", "psychology_check.py"),
    ("invest-sotp", "sotp_model.py"),
    ("invest-valuation", "valuation_model.py"),
))


class CliSmokeTests(unittest.TestCase):
    def test_every_cli_help_path_succeeds(self) -> None:
        for cli in CLIS:
            with self.subTest(cli=cli.name):
                completed = subprocess.run(
                    [sys.executable, str(cli), "--help"], capture_output=True,
                    text=True, encoding="utf-8", check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("usage:", completed.stdout.lower())

    def test_every_cli_missing_input_path_fails_without_traceback(self) -> None:
        for cli in CLIS:
            with self.subTest(cli=cli.name):
                completed = subprocess.run(
                    [sys.executable, str(cli)], capture_output=True,
                    text=True, encoding="utf-8", check=False,
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
