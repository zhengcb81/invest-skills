"""Hash-check or atomically synchronize canonical invest skills to installations.

Owner requirement (2026-09-08): every installed skill must equal its Projects
git repo, in all three agent roots (``~/.agents``, ``~/.claude``,
``~/.codex``).  A component missing inside an existing root is drift, which is
how the 补齐 requirement is enforced; junction installs are verified through
the link and never replaced.

Repeat --file component/relative to check or atomically update only selected
files. This mode never replaces components or removes unknown config/output;
aliases resolve to one physical file and already matching files incur zero writes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath


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


def _selected_sources(canonical: Path, names: list[str]) -> dict[str, tuple[Path, bytes, str]]:
    """Read only explicitly selected canonical files; never enumerate a suite."""
    selected = {}
    for name in names:
        portable = name.replace("\\", "/")
        relative = PurePosixPath(portable)
        if (relative.is_absolute() or PureWindowsPath(portable).drive
                or len(relative.parts) < 2 or relative.parts[0] not in COMPONENTS
                or ".." in relative.parts or any(":" in part for part in relative.parts)):
            raise ValueError(f"expected component/relative file: {name}")
        key = relative.as_posix()
        if key in selected:
            continue
        base = (canonical / relative.parts[0]).resolve()
        source = canonical.joinpath(*relative.parts).resolve(strict=True)
        if not source.is_relative_to(base) or not source.is_file():
            raise ValueError(f"selected canonical path is not a component file: {name}")
        data = source.read_bytes()
        selected[key] = (source, data, hashlib.sha256(data).hexdigest())
    return selected


def _selected_plan(canonical: Path, destinations: list[Path], selected):
    """Resolve aliases once and reject conflicting writes before touching files."""
    roots = [destination.resolve() for destination in destinations]
    bases = {}
    for key in selected:
        component = PurePosixPath(key).parts[0]
        bases[component] = [(canonical / component).resolve(),
                            *((root / component).resolve() for root in roots)]
    plan = {}
    for root in roots:
        for key, entry in selected.items():
            logical = root / key
            target = logical.resolve()
            component = PurePosixPath(key).parts[0]
            if not any(target.is_relative_to(base) for base in bases[component]):
                raise ValueError(f"selected alias escapes the requested component: {logical}")
            identity = os.path.normcase(str(target))
            if identity in plan:
                if plan[identity][2][2] != entry[2]:
                    raise ValueError(f"different canonical files resolve to one target: {logical}")
                print(f"ALIAS {logical} -> {target} (one physical file)")
                continue
            plan[identity] = (logical, target, entry)
    return list(plan.values())


def _replace_selected_file(source: Path, target: Path, data: bytes) -> None:
    """Stage beside one physical target and replace only that selected file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".stage-",
                                         suffix=".tmp", delete=False) as stream:
            pending = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        shutil.copymode(source, pending)
        os.replace(pending, target)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


def _sync_selected(canonical: Path, destinations: list[Path], selected, *, apply: bool) -> int:
    plan = _selected_plan(canonical, destinations, selected)
    changed, matched, errors = 0, 0, 0
    for logical, target, (source, data, expected) in plan:
        try:
            if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
                matched += 1
                print(f"MATCH {logical}")
                continue
            if target == source or (target.is_file() and source.is_file()
                                    and os.path.samefile(target, source)):
                errors += 1
                print(f"ERROR {logical}: source_changed; canonical bytes retained")
                continue
            if not apply:
                errors += 1
                print(f"DIFF {logical}")
                continue
            _replace_selected_file(source, target, data)
            if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                raise OSError("selected file readback differs from canonical bytes")
            changed += 1
            print(f"UPDATED {logical}")
        except OSError as error:
            errors += 1
            print(f"ERROR {logical}: {type(error).__name__}; earlier file updates remain")
    state = "PARTIAL" if apply and errors else "DIFF" if errors else "MATCH"
    print(f"{state} selected files: updated={changed}, unchanged={matched}, errors={errors}")
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Check or synchronize installed invest skills")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="apply an atomic component-by-component sync")
    mode.add_argument("--print-manifest", action="store_true", help="print the canonical SHA-256 manifest")
    parser.add_argument("--canonical", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--destination", type=Path, action="append")
    parser.add_argument("--file", action="append", dest="selected_files",
                        help="only check/sync component/relative file; repeat for more files")
    args = parser.parse_args()
    canonical = args.canonical.resolve()
    try:
        selected = _selected_sources(canonical, args.selected_files) if args.selected_files else None
    except (OSError, ValueError) as error:
        print(f"ERROR selected files: {type(error).__name__}: {error}")
        return 1
    if args.print_manifest:
        manifest = {key: entry[2] for key, entry in selected.items()} if selected is not None else suite_manifest(canonical)
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0
    destinations = args.destination or [
        Path.home() / ".agents" / "skills",
        Path.home() / ".claude" / "skills",
        Path.home() / ".codex" / "skills",
    ]
    if selected is not None:
        try:
            return _sync_selected(canonical, destinations, selected, apply=args.apply)
        except (OSError, ValueError) as error:
            print(f"ERROR selected files: {type(error).__name__}: {error}")
            return 1
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
