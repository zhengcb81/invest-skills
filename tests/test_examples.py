from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ExecutableExampleTests(unittest.TestCase):
    def test_examples_execute_without_private_test_imports(self) -> None:
        for name in ("run_financial_families.py", "run_holding_company.py"):
            with self.subTest(name=name):
                completed = subprocess.run(
                    [sys.executable, str(ROOT / "examples" / name)], capture_output=True,
                    text=True, encoding="utf-8", check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertNotIn("test_", completed.stderr)


if __name__ == "__main__":
    unittest.main()
