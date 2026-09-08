"""Hash-check or atomically synchronize canonical invest skills to installations.

Owner requirement (2026-09-08): every installed skill must equal its Projects
git repo, in all three agent roots (``~/.agents``, ``~/.claude``,
``~/.codex``).  A component missing inside an existing root is drift, which is
how the 补齐 requirement is enforced; junction installs are verified through
the link and never replaced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path


COMPONENTS = (
    "invest-core", "invest-financials", "invest-valuation", "invest-sotp",
    "invest-management", "invest-moat", "invest-distribution", "invest-compare",
    "invest-psychology", "invest-framework", "tests_support",
)
IGNORED_PARTS = {"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".codegraph"}


def _files(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("*")
        if path.is_file() and not (set(path.parts) & IGNORED_PARTS) and path.suffix not in {".pyc", ".pyo"}
    )


def _is_alias(path: Path) -> bool:
    """True for junctions/symlinks (``Path.is_symlink`` misses junctions).

    ``~/.claude/skills/<component>`` are junctions into ``~/.agents/skills``;
    an atomic replace must never delete the link's target (that is how the
    stale ``.invest-core-backup-8400`` leftover was created).
    """
    try:
        return os.path.normcase(str(path.resolve())) != os.path.normcase(str(path.absolute()))
    except OSError:
        return False


def _remove_path(path: Path) -> None:
    """Remove a file, a real directory, or a junction/symlink itself."""
    if _is_alias(path):
        os.rmdir(path)
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def component_manifest(root: Path, component: str) -> dict[str, str]:
    base = root / component
    if not base.is_dir():
        raise FileNotFoundError(f"missing canonical component: {base}")
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in _files(base)
    }


def suite_manifest(root: Path) -> dict[str, str]:
    combined: dict[str, str] = {}
    for component in COMPONENTS:
        combined.update(component_manifest(root, component))
    return dict(sorted(combined.items()))


def installation_diff(canonical: Path, destination: Path) -> list[str]:
    expected = suite_manifest(canonical)
    actual: dict[str, str] = {}
    for component in COMPONENTS:
        base = destination / component
        if not base.is_dir():
            actual[f"{component}/<missing>"] = "missing"
            continue
        actual.update({
            path.relative_to(destination).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in _files(base)
        })
    keys = sorted(set(expected) | set(actual))
    return [key for key in keys if expected.get(key) != actual.get(key)]


def _sync_component(canonical: Path, destination: Path, component: str) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / component
    if target.exists() and _is_alias(target):
        print(f"  ALIAS {target} -> {target.resolve()} (verified via link, not replaced)")
        return
    with tempfile.TemporaryDirectory(prefix=f".{component}-stage-", dir=destination) as directory:
        staged = Path(directory) / component
        shutil.copytree(
            canonical / component, staged,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".codegraph"),
        )
        backup = destination / f".{component}-backup-{os.getpid()}"
        if backup.exists():
            _remove_path(backup)
        if target.exists():
            os.replace(target, backup)
        try:
            os.replace(staged, target)
        except Exception:
            if backup.exists() and not target.exists():
                os.replace(backup, target)
            raise
        if backup.exists():
            _remove_path(backup)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check or synchronize installed invest skills")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="apply an atomic component-by-component sync")
    mode.add_argument("--print-manifest", action="store_true", help="print the canonical SHA-256 manifest")
    parser.add_argument("--canonical", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--destination", type=Path, action="append")
    args = parser.parse_args()
    canonical = args.canonical.resolve()
    if args.print_manifest:
        print(json.dumps(suite_manifest(canonical), indent=2, sort_keys=True))
        return 0
    destinations = args.destination or [
        Path.home() / ".agents" / "skills",
        Path.home() / ".claude" / "skills",
        Path.home() / ".codex" / "skills",
    ]
    if args.apply:
        for destination in destinations:
            for component in COMPONENTS:
                _sync_component(canonical, destination.resolve(), component)
    failed = False
    for destination in destinations:
        differences = installation_diff(canonical, destination.resolve())
        if differences:
            failed = True
            print(f"DIFF {destination}: {len(differences)} files")
            for path in differences[:50]:
                print(f"  {path}")
        else:
            print(f"MATCH {destination}: {len(suite_manifest(canonical))} files")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
