"""Fast local Git checks; full tests/E2E live in CI, deployment is explicit.

Commit: staged Python syntax + Ruff only. Push: Ruff and one fixed adapter /
three-hop integrity smoke. Neither operation modifies installed skills.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SMOKE = (
    "invest-core/tests/test_revenue_adapter.py",
    "invest-core/tests/test_revenue_adapter_gate_simplification.py",
    "invest-framework/tests/test_forged_cross_repo_chain.py",
)


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env.pop("REVENUE_ATTESTATION_PROVIDER", None)
    sibling = PROJECT_ROOT.parent / "revenue-forecast"
    if sibling.is_dir():
        env.setdefault("REVENUE_FORECAST_DIR", str(sibling))
    return env


def _run(cmd: list[str], label: str, *, env_overrides: dict[str, str] | None = None) -> int:
    print(label, flush=True)
    env = _env()
    env.update(env_overrides or {})
    # Disk-backed logs avoid unbounded memory. Log volume is not a veto.
    with tempfile.TemporaryFile() as log:
        try:
            result = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=120, check=False)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
        log.seek(0, 2)
        log.seek(max(0, log.tell() - 16000))
        print(log.read().decode("utf-8", "replace"))
    return code


def _staged_python() -> list[Path]:
    result = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
                            cwd=PROJECT_ROOT, capture_output=True, check=True)
    return [PROJECT_ROOT / os.fsdecode(name) for name in result.stdout.split(b"\0")
            if name.endswith(b".py")]


def _staged_bytes(path: Path) -> bytes:
    relative = path.relative_to(PROJECT_ROOT).as_posix()
    return subprocess.run(["git", "show", "--no-textconv", f":0:{relative}"],
                          cwd=PROJECT_ROOT, capture_output=True, check=True).stdout


def _check_commit() -> int:
    files = _staged_python()
    if not files:
        return 0
    # Validate exactly the index, without stashing or changing the worktree.
    with tempfile.TemporaryDirectory(prefix="invest-staged-") as directory:
        staged = []
        for path in files:
            try:
                source = _staged_bytes(path)
                compile(source, str(path), "exec")
                destination = Path(directory) / path.relative_to(PROJECT_ROOT)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source)
                staged.append(str(destination))
            except (SyntaxError, UnicodeError, OSError, ValueError, subprocess.CalledProcessError) as error:
                print(f"Staged Python syntax/read failure: {path}: {type(error).__name__}")
                return 1
        config = PROJECT_ROOT / "pyproject.toml"
        options = ["--config", str(config)] if config.is_file() else []
        return _run([sys.executable, "-m", "ruff", "check", "--no-cache", *options, *staged],
                    "Staged Python static checks")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args(argv)
    if args.commit:
        return _check_commit()
    code = _run([sys.executable, "-m", "ruff", "check", "--no-cache", "."], "Ruff")
    if code:
        return code
    with tempfile.TemporaryDirectory(prefix="invest-git-smoke-") as directory:
        return _run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", *SMOKE],
                    "Fixed revenue adapter / cross-repository integrity smoke; full validation remains in CI",
                    env_overrides={"REVENUE_PUBLICATION_REGISTRY": str(Path(directory) / "index")})


if __name__ == "__main__":
    raise SystemExit(main())
