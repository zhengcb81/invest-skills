"""One command for the complete revenue/invest release gate."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from jsonschema.validators import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, env: dict[str, str], cwd: Path = ROOT) -> str:
    print("RUN", " ".join(command))
    completed = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", check=False)
    output = completed.stdout + completed.stderr
    if completed.returncode:
        print(output)
        raise SystemExit(completed.returncode)
    return output


def test_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("test_*.py") if not set(path.parts) & {"__pycache__", ".codegraph"})


def run_tests(files: list[Path], *, env: dict[str, str], coverage: bool) -> int:
    if not files:
        raise SystemExit("zero test files discovered")
    count = 0
    for test in files:
        command = [sys.executable, str(test)]
        if coverage:
            command = [sys.executable, "-m", "coverage", "run", "--parallel-mode", str(test)]
        output = run(command, env=env)
        match = re.search(r"Ran (\d+) tests?", output)
        if not match:
            raise SystemExit(f"test count missing from {test}")
        count += int(match.group(1))
    if count == 0:
        raise SystemExit("zero tests executed")
    return count


def validate_schemas() -> None:
    import json

    schemas = sorted((ROOT / "schemas").glob("*.schema.json"))
    if not schemas:
        raise SystemExit("zero JSON schemas discovered")
    for path in schemas:
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))
    print(f"validated {len(schemas)} JSON schemas")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the complete invest-suite release gate")
    parser.add_argument("--revenue-dir", type=Path, required=True)
    parser.add_argument("--skip-install-check", action="store_true")
    parser.add_argument("--no-coverage", action="store_true")
    args = parser.parse_args()
    revenue = args.revenue_dir.resolve()
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["REVENUE_FORECAST_DIR"] = str(revenue)

    revenue_count = run_tests(test_files(revenue / "tests"), env=env, coverage=False)
    if not args.no_coverage:
        run([sys.executable, "-m", "coverage", "erase"], env=env)
    invest_count = run_tests(test_files(ROOT / "tests") + [
        path for skill in ROOT.glob("invest-*") for path in test_files(skill / "tests")
    ], env=env, coverage=not args.no_coverage)
    if not args.no_coverage:
        run([sys.executable, "-m", "coverage", "combine"], env=env)
        print(run([sys.executable, "-m", "coverage", "report", "--include=*/invest-*/scripts/*.py"], env=env))

    run(["ruff", "check", "."], env=env)
    scripts = sorted(str(path) for skill in ROOT.glob("invest-*") for path in (skill / "scripts").glob("*.py"))
    run(["mypy", "--ignore-missing-imports", *scripts], env=env)
    run([sys.executable, "-m", "compileall", "-q", *[str(ROOT / name) for name in (
        "invest-core", "invest-financials", "invest-valuation", "invest-sotp", "invest-management",
        "invest-moat", "invest-distribution", "invest-compare", "invest-psychology", "invest-framework", "tests_support",
    )]], env=env)
    validate_schemas()
    run([sys.executable, str(ROOT / "tools" / "validate_skills.py")], env=env)
    if not args.skip_install_check:
        run([sys.executable, str(ROOT / "tools" / "sync_installations.py")], env=env)
    print(f"PASS revenue_tests={revenue_count} invest_tests={invest_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
