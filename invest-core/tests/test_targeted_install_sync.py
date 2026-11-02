"""Targeted deployment: select files, never replace component directories."""

from __future__ import annotations

from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def load_tool():
    path = Path(__file__).resolve().parents[2] / "tools" / "sync_installations.py"
    spec = spec_from_file_location("selective_install_owner", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def invoke(tool, monkeypatch, canonical, destinations, files, *flags):
    args = ["sync", "--canonical", str(canonical), *flags]
    for destination in destinations:
        args += ["--destination", str(destination)]
    for selected in files:
        args += ["--file", selected]
    monkeypatch.setattr(sys, "argv", args)
    try:
        return tool.main()
    except SystemExit as exc:
        return exc.code


def source_tree(tmp_path):
    source = tmp_path / "canonical"
    (source / "invest-core/scripts").mkdir(parents=True)
    (source / "invest-core/scripts/a.py").write_bytes(b"new_a = True\n")
    (source / "invest-core/scripts/b.py").write_bytes(b"new_b = True\n")
    return source


def alias_directory(target, alias):
    alias.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(alias), str(target)],
            capture_output=True,
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        alias.symlink_to(target, target_is_directory=True)


def unlink_alias(alias):
    if alias.is_symlink():
        alias.unlink()
    else:
        alias.rmdir()


def test_selected_check_does_not_scan_unrequested_or_create_installations(
    tmp_path, monkeypatch
):
    tool = load_tool()
    source = source_tree(tmp_path)
    target = tmp_path / "absent-install"

    def no_scan(*args):
        raise AssertionError("subset must not enumerate components")

    monkeypatch.setattr(tool, "suite_manifest", no_scan)
    monkeypatch.setattr(tool, "_files", no_scan)
    assert (
        invoke(tool, monkeypatch, source, [target], ["invest-core/scripts/a.py"]) == 1
    )
    assert not target.exists()


def test_three_roots_repeated_files_and_alias_update_once_preserve_unknowns(
    tmp_path, monkeypatch
):
    tool = load_tool()
    source = source_tree(tmp_path)
    agents, claude, codex = [tmp_path / name for name in ("agents", "claude", "codex")]
    for base in (agents, codex):
        (base / "invest-core/scripts").mkdir(parents=True)
        (base / "invest-core/scripts/a.py").write_bytes(b"old code")
        (base / "invest-core/config.json").write_bytes(b"foreign user config")
        (base / "invest-core/output").mkdir()
        (base / "invest-core/output/result.json").write_bytes(b"foreign result")
    alias_directory(agents / "invest-core", claude / "invest-core")
    link_id = (claude / "invest-core").lstat().st_ino
    real_replace, writes = tool.os.replace, []

    def replace(staged, destination):
        writes.append(Path(destination).resolve())
        return real_replace(staged, destination)

    monkeypatch.setattr(tool.os, "replace", replace)
    try:
        selected = ["invest-core/scripts/a.py", "invest-core/scripts/a.py"]
        assert (
            invoke(
                tool, monkeypatch, source, [agents, claude, codex], selected, "--apply"
            )
            == 0
        )
        assert len(writes) == 2 and len(set(writes)) == 2
        for base in (agents, claude, codex):
            assert (base / selected[0]).read_bytes() == b"new_a = True\n"
            assert (
                base / "invest-core/config.json"
            ).read_bytes() == b"foreign user config"
            assert (
                base / "invest-core/output/result.json"
            ).read_bytes() == b"foreign result"
            assert not (base / "invest-core/scripts/b.py").exists()
        assert (claude / "invest-core").lstat().st_ino == link_id
        assert (claude / "invest-core").resolve() == (agents / "invest-core").resolve()
        assert not list(tmp_path.rglob("*.stage-*"))
    finally:
        unlink_alias(claude / "invest-core")


def test_repeat_apply_has_zero_writes_and_no_staging(tmp_path, monkeypatch):
    tool = load_tool()
    source = source_tree(tmp_path)
    target = tmp_path / "install"
    selected = ["invest-core/scripts/a.py"]
    assert invoke(tool, monkeypatch, source, [target], selected, "--apply") == 0
    path = target / selected[0]
    before = path.stat()

    def no_write(*args, **kwargs):
        raise AssertionError("matching file must not be written or staged")

    monkeypatch.setattr(tool.os, "replace", no_write)
    monkeypatch.setattr(tool.tempfile, "NamedTemporaryFile", no_write)
    assert invoke(tool, monkeypatch, source, [target], selected, "--apply") == 0
    after = path.stat()
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)


def test_partial_file_failure_keeps_first_success_and_reports_partial(
    tmp_path, monkeypatch, capsys
):
    tool = load_tool()
    source = source_tree(tmp_path)
    target = tmp_path / "install"
    (target / "invest-core/scripts").mkdir(parents=True)
    (target / "invest-core/scripts/a.py").write_bytes(b"old-a")
    (target / "invest-core/scripts/b.py").write_bytes(b"old-b")
    real_replace = tool.os.replace

    def fail_second(staged, destination):
        if Path(destination).name == "b.py":
            raise OSError("synthetic second file failure")
        return real_replace(staged, destination)

    monkeypatch.setattr(tool.os, "replace", fail_second)
    assert (
        invoke(
            tool,
            monkeypatch,
            source,
            [target],
            ["invest-core/scripts/a.py", "invest-core/scripts/b.py"],
            "--apply",
        )
        == 1
    )
    assert (target / "invest-core/scripts/a.py").read_bytes() == b"new_a = True\n"
    assert (target / "invest-core/scripts/b.py").read_bytes() == b"old-b"
    assert not list(target.rglob("*.stage-*"))
    text = capsys.readouterr().out
    assert "PARTIAL" in text and "ERROR" in text
    resumed = []

    def resume(staged, destination):
        resumed.append(Path(destination).name)
        return real_replace(staged, destination)

    monkeypatch.setattr(tool.os, "replace", resume)
    assert (
        invoke(
            tool,
            monkeypatch,
            source,
            [target],
            ["invest-core/scripts/a.py", "invest-core/scripts/b.py"],
            "--apply",
        )
        == 0
    )
    assert resumed == ["b.py"]


def test_canonical_alias_never_writes_source_or_replaces_link(tmp_path, monkeypatch):
    tool = load_tool()
    source = source_tree(tmp_path)
    target = tmp_path / "install"
    alias_directory(source / "invest-core", target / "invest-core")
    before = (target / "invest-core").lstat().st_ino

    def no_replace(*args):
        raise AssertionError("canonical alias is already current")

    monkeypatch.setattr(tool.os, "replace", no_replace)
    try:
        assert (
            invoke(
                tool,
                monkeypatch,
                source,
                [target],
                ["invest-core/scripts/a.py"],
                "--apply",
            )
            == 0
        )
        assert (target / "invest-core").lstat().st_ino == before
        assert (source / "invest-core/scripts/a.py").read_bytes() == b"new_a = True\n"
    finally:
        unlink_alias(target / "invest-core")


@pytest.mark.parametrize(
    "selected",
    ["../outside.py", "invest-core/../../outside.py", "C:/outside.py", "invest-core"],
)
def test_path_escape_or_component_directory_never_writes(
    tmp_path, monkeypatch, selected
):
    tool = load_tool()
    source = source_tree(tmp_path)
    target = tmp_path / "absent-install"
    assert invoke(tool, monkeypatch, source, [target], [selected], "--apply") == 1
    assert not target.exists()


def test_subset_manifest_contains_only_requested_bytes(tmp_path, monkeypatch, capsys):
    tool = load_tool()
    source = source_tree(tmp_path)
    assert (
        invoke(
            tool,
            monkeypatch,
            source,
            [],
            ["invest-core/scripts/a.py"],
            "--print-manifest",
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {
        "invest-core/scripts/a.py": sha256(b"new_a = True\n").hexdigest()
    }


def test_legacy_explicit_full_and_check_modes_remain_available(tmp_path, monkeypatch):
    tool = load_tool()
    source = tmp_path / "all"
    target = tmp_path / "install"
    for component in tool.COMPONENTS:
        (source / component).mkdir(parents=True)
        (source / component / "SKILL.md").write_text(component, encoding="utf-8")
    assert invoke(tool, monkeypatch, source, [target], [], "--apply") == 0
    assert invoke(tool, monkeypatch, source, [target], []) == 0


def test_conflicting_aliases_fail_before_overwriting_any_file(tmp_path, monkeypatch):
    tool = load_tool()
    source = source_tree(tmp_path)
    target = tmp_path / "install"
    (source / "invest-financials/scripts").mkdir(parents=True)
    (source / "invest-financials/scripts/a.py").write_bytes(
        b"different_canonical = True\n"
    )
    (target / "invest-core/scripts").mkdir(parents=True)
    selected = target / "invest-core/scripts/a.py"
    selected.write_bytes(b"old")
    alias_directory(target / "invest-core", target / "invest-financials")
    try:
        assert (
            invoke(
                tool,
                monkeypatch,
                source,
                [target],
                ["invest-core/scripts/a.py", "invest-financials/scripts/a.py"],
                "--apply",
            )
            == 1
        )
        assert selected.read_bytes() == b"old"
    finally:
        unlink_alias(target / "invest-financials")


def test_fresh_cli_only_updates_requested_file(tmp_path):
    source = source_tree(tmp_path)
    target = tmp_path / "install"
    script = Path(__file__).resolve().parents[2] / "tools/sync_installations.py"
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(script),
            "--canonical",
            str(source),
            "--destination",
            str(target),
            "--file",
            "invest-core/scripts/a.py",
            "--apply",
        ],
        env=env,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert (target / "invest-core/scripts/a.py").read_bytes() == b"new_a = True\n"
    assert not (target / "invest-core/scripts/b.py").exists()


def test_changed_canonical_alias_never_restores_stale_snapshot(
    tmp_path, monkeypatch, capsys
):
    tool = load_tool()
    source = source_tree(tmp_path)
    target = tmp_path / "install"
    alias_directory(source / "invest-core", target / "invest-core")
    canonical = source / "invest-core/scripts/a.py"
    newer = b"canonical_writer_advanced = True\n"
    real_select = tool._selected_sources
    real_stage = tool.tempfile.NamedTemporaryFile
    stages = []

    def select_then_writer_advances(*args):
        selected = real_select(*args)
        canonical.write_bytes(newer)
        return selected

    def staged(*args, **kwargs):
        stages.append(1)
        return real_stage(*args, **kwargs)

    monkeypatch.setattr(tool, "_selected_sources", select_then_writer_advances)
    monkeypatch.setattr(tool.tempfile, "NamedTemporaryFile", staged)
    before = (target / "invest-core").lstat().st_ino
    try:
        code = invoke(
            tool, monkeypatch, source, [target], ["invest-core/scripts/a.py"], "--apply"
        )
        assert canonical.read_bytes() == newer
        assert code == 1 and stages == []
        assert (target / "invest-core").lstat().st_ino == before
        text = capsys.readouterr().out
        assert "source_changed" in text and "PARTIAL" in text
    finally:
        unlink_alias(target / "invest-core")
