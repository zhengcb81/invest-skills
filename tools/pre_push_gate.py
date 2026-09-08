"""Pre-push gate for invest-skills (owner requirement 2026-09-08).

The repo had a CI workflow but no local surface, and its `.githooks/pre-commit`
was never wired (``core.hooksPath`` was unset).  This gate mirrors the CI
`quality` workflow locally and adds the installed-skill consistency check that
CI cannot cover (GitHub runners have no install roots):

  1. ruff check .                          (CI "Lint")
  2. compileall over the ten components
  3. tools/validate_skills.py              (frontmatter + relative links)
  4. pytest over the ten components        (CI "Run test suite")
  5. e2e/run_biren_invest_e2e.py           (CI, when the revenue sibling exists)
  6. installed-skill consistency: ~/.agents, ~/.claude and ~/.codex must equal
     this repo; stale/missing copies are auto-synced and re-checked
  7. UTF-8 BOM scan

Exit non-zero on the first red check.  Push protocol: run this gate, push,
then self-monitor the GitHub Actions run until green.

Usage: python tools/pre_push_gate.py [--skip-tests] [--skip-e2e]
       [--skip-install-sync]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = (
    "invest-core",
    "invest-framework",
    "invest-financials",
    "invest-valuation",
    "invest-sotp",
    "invest-moat",
    "invest-management",
    "invest-distribution",
    "invest-compare",
    "invest-psychology",
)


def _safe_console() -> None:
    """Windows consoles default to GBK; never let reporting crash the gate."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _env() -> dict[str, str]:
    env = dict(os.environ)
    sibling = PROJECT_ROOT.parent / "revenue-forecast"
    if sibling.is_dir():
        env.setdefault("REVENUE_FORECAST_DIR", str(sibling))
    return env


def _run(
    cmd: list[str], label: str, timeout: int = 1800, *, blocking: bool = True
) -> int:
    print(f"\n=== {label} ===")
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    tail = (proc.stdout or "")[-2500:] + (proc.stderr or "")[-1200:]
    if proc.returncode != 0:
        print(tail)
        if blocking:
            print(f"FAILED: {label}")
    else:
        print("ok")
    return proc.returncode


def _no_bom_check() -> int:
    bad = [
        str(path.relative_to(PROJECT_ROOT))
        for path in sorted(PROJECT_ROOT.rglob("*.py"))
        if path.read_bytes().startswith(b"\xef\xbb\xbf")
    ]
    if bad:
        print("FAILED: UTF-8 BOM python files must be zero:")
        for name in bad:
            print(f"  {name}")
        return 1
    print("ok")
    return 0


def _install_sync() -> int:
    tool = PROJECT_ROOT / "tools" / "sync_installations.py"
    rc = _run(
        [sys.executable, str(tool)],
        "installed-skill consistency (check)",
        blocking=False,
    )
    if rc == 0:
        return 0
    print("installed copies were stale/incomplete: applying repo -> install sync ...")
    rc = _run(
        [sys.executable, str(tool), "--apply"],
        "installed-skill sync (repo -> install)",
        blocking=False,
    )
    if rc != 0:
        return rc
    return _run(
        [sys.executable, str(tool)],
        "installed-skill consistency (re-check)",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-e2e", action="store_true")
    parser.add_argument("--skip-install-sync", action="store_true")
    args = parser.parse_args(argv)
    _safe_console()

    gates: list[tuple[list[str], str]] = [
        ([sys.executable, "-m", "ruff", "check", "."], "ruff check (CI Lint)"),
        (
            [sys.executable, "-m", "compileall", "-q", *COMPONENTS],
            "compileall (all components)",
        ),
        (
            [sys.executable, str(PROJECT_ROOT / "tools" / "validate_skills.py")],
            "validate_skills (frontmatter + links)",
        ),
    ]
    if not args.skip_tests:
        gates.append(
            (
                [sys.executable, "-m", "pytest", *COMPONENTS, "-q"],
                "invest test suite (CI Run test suite)",
            )
        )

    for cmd, label in gates:
        rc = _run(cmd, label)
        if rc != 0:
            print(f"\nGATE RED at: {label}\nFix the root cause; do not bypass.")
            return rc

    if not args.skip_e2e:
        e2e = PROJECT_ROOT / "e2e" / "run_biren_invest_e2e.py"
        if (PROJECT_ROOT.parent / "revenue-forecast").is_dir():
            rc = _run(
                [sys.executable, str(e2e)], "Biren invest E2E (CI)"
            )
            if rc != 0:
                print("\nGATE RED at: Biren invest E2E\nFix the root cause.")
                return rc
        else:
            print(
                "\n=== Biren invest E2E (CI) ===\n"
                "SKIP: no revenue-forecast sibling; CI clones it."
            )

    if not args.skip_install_sync:
        rc = _install_sync()
        if rc != 0:
            print(
                "\nGATE RED at: installed-skill consistency\n"
                "Fix: python tools/sync_installations.py --apply"
            )
            return rc

    print("\n=== UTF-8 BOM scan ===")
    if _no_bom_check() != 0:
        return 1

    print("\npre-push gate GREEN — safe to push (then self-monitor CI).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
