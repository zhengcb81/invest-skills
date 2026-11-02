"""Git checks must be fast, read-only and separate from deployment."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def load_tool():
    path = Path(__file__).resolve().parents[2] / "tools/pre_push_gate.py"
    spec = spec_from_file_location("invest_fast_checks", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_document_commit_runs_no_tests_or_deployment(monkeypatch):
    tool = load_tool()
    monkeypatch.setattr(tool, "_staged_python", lambda: [])
    calls = []
    monkeypatch.setattr(tool, "_run", lambda *args, **kwargs: calls.append(args) or 0)
    assert tool.main(["--commit"]) == 0
    assert calls == []


def test_bad_staged_python_is_rejected_without_running_it(tmp_path, monkeypatch):
    tool = load_tool()
    bad = tmp_path / "bad.py"
    bad.write_text("def invalid(:", encoding="utf-8")
    monkeypatch.setattr(tool, "_staged_python", lambda: [bad])
    monkeypatch.setattr(tool, "_staged_bytes", lambda path: path.read_bytes())
    assert tool.main(["--commit"]) != 0
    assert not list(tmp_path.rglob("*.pyc"))


def test_push_has_no_implicit_deployment_or_whole_suite(monkeypatch):
    tool = load_tool()
    calls, smoke_environments = [], []
    def record(cmd, *_args, **kwargs):
        calls.append(cmd)
        if "pytest" in cmd:
            isolated = Path(kwargs["env_overrides"]["REVENUE_PUBLICATION_REGISTRY"])
            assert isolated.parent.is_dir()
            smoke_environments.append(isolated)
        return 0
    monkeypatch.setattr(tool, "_run", record)
    assert tool.main([]) == 0
    flattened = " ".join(str(arg) for cmd in calls for arg in cmd)
    assert "sync_installations" not in flattened
    assert "compileall" not in flattened
    assert "run_biren_invest_e2e" not in flattened
    assert "test_revenue_adapter" in flattened
    assert "test_forged_cross_repo_chain" in flattened
    assert len(calls) <= 2
    assert len(smoke_environments) == 1
    assert not smoke_environments[0].parent.exists()


def test_commit_syntax_uses_actual_index_bytes_without_changing_worktree(tmp_path, monkeypatch):
    import subprocess
    tool = load_tool()
    monkeypatch.setattr(tool, "PROJECT_ROOT", tmp_path)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "example.py"
    source.write_text("def invalid(:", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "example.py"], check=True)
    source.write_text("valid_worktree = True\n", encoding="utf-8")
    monkeypatch.setattr(tool, "_run", lambda *_args, **_kwargs: 0)
    assert tool.main(["--commit"]) == 1
    assert source.read_text() == "valid_worktree = True\n"
    assert tool._staged_bytes(source) == b"def invalid(:"


def test_ruff_reads_index_in_an_owned_temporary_tree(tmp_path, monkeypatch):
    import subprocess
    tool = load_tool()
    monkeypatch.setattr(tool, "PROJECT_ROOT", tmp_path)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "example.py"
    staged = b"valid_staged = True\n"
    source.write_bytes(staged)
    subprocess.run(["git", "-C", str(tmp_path), "add", "example.py"], check=True)
    source.write_text("def broken_worktree(:", encoding="utf-8")
    observed = []
    def inspect(cmd, *_args, **_kwargs):
        candidate = Path(cmd[-1])
        assert candidate != source
        assert candidate.read_bytes() == staged
        observed.append(candidate)
        return 0
    monkeypatch.setattr(tool, "_run", inspect)
    assert tool.main(["--commit"]) == 0
    assert len(observed) == 1 and not observed[0].exists()
    assert tool._staged_bytes(source) == staged
    assert source.read_text() == "def broken_worktree(:"


def test_real_ruff_rejects_staged_name_error_hidden_by_good_worktree(tmp_path, monkeypatch):
    import subprocess
    tool = load_tool()
    monkeypatch.setattr(tool, "PROJECT_ROOT", tmp_path)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "example.py"
    source.write_text("answer = missing_name\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "example.py"], check=True)
    source.write_text("answer = 42\n", encoding="utf-8")
    assert tool.main(["--commit"]) == 1
    assert source.read_text() == "answer = 42\n"
