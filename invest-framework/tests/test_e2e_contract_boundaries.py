"""Narrow real-owner tests for the offline CLI boundary; no model calls."""
from __future__ import annotations

import importlib.util
import copy
import json
import os
import subprocess
from types import SimpleNamespace
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
for scripts in (ROOT / "tests_support", ROOT / "invest-framework/scripts", ROOT / "e2e"):
    sys.path.insert(0, str(scripts))
import invest_contracts  # noqa: E402 - canonical checkout path setup
from revenue_fixtures import load_revenue_fixture  # noqa: E402 - canonical checkout path setup
import run_biren_invest_e2e as harness  # noqa: E402 - canonical checkout path setup
import company_orchestrator as company  # noqa: E402 - canonical checkout path setup
import bundle_validator as bundle  # noqa: E402 - canonical checkout path setup

_spec = importlib.util.spec_from_file_location("_company_fixture", ROOT / "invest-framework/tests/test_company_orchestrator.py")
assert _spec is not None and _spec.loader is not None
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)


@pytest.fixture
def forecast():
    return load_revenue_fixture("recognition")


def test_step_one_does_not_require_a_global_index(forecast):
    with patch("publication_registry.register_publication", side_effect=OSError("index offline")) as register:
        harness.collect_step_1_forecast_valid(forecast, Path("not-used.json"))
    register.assert_not_called()


class BoundaryReached(Exception):
    pass


def test_company_reference_owns_the_single_immediate_validation(forecast):
    calls = []
    original = invest_contracts.validate_revenue_forecast
    def checked(value):
        calls.append(value)
        return original(value)
    with patch.object(invest_contracts, "validate_revenue_forecast", checked), patch.object(company, "validate_revenue_forecast", checked, create=True), patch.object(company, "validate_manifest", side_effect=BoundaryReached):
        with pytest.raises(BoundaryReached):
            company.run_company({}, forecast)
    assert len(calls) == 1


def test_bundle_reference_owns_the_single_immediate_validation(forecast):
    reference = invest_contracts.revenue_reference(forecast)
    calls = []
    original = invest_contracts.validate_revenue_forecast
    def checked(value):
        calls.append(value)
        return original(value)
    plan = {"bundle_plan_schema_version": "2.0", "required_modules": [], "optional_modules": []}
    with patch.object(invest_contracts, "validate_revenue_forecast", checked), patch.object(bundle, "validate_revenue_forecast", checked), patch.object(bundle, "_validate_bundle_inputs", return_value=({}, [reference], [])), patch.object(bundle, "_summary", side_effect=BoundaryReached):
        with pytest.raises(BoundaryReached):
            bundle.run_bundle([], plan, frozen_revenue_forecast=forecast)
    assert calls == [forecast]


def test_current_bundle_public_read_validates_its_frozen_forecast_once(forecast):
    execution = company.run_company(_fixture.manifest_for(forecast), forecast)
    artifact = execution["bundle"]
    frozen = artifact["data"]["frozen_revenue_forecast"]
    calls = []
    original = invest_contracts.validate_revenue_forecast
    def checked(value):
        if value is frozen:
            calls.append(value)
        return original(value)
    with patch.object(invest_contracts, "validate_revenue_forecast", checked), patch.object(bundle, "validate_revenue_forecast", checked):
        bundle.validate_bundle_artifact(artifact)
    assert len(calls) == 1


@pytest.mark.parametrize("damage", ["invalid_pair", "unsigned_claims_signed", "currency", "unit", "revenue"])
def test_real_cli_rejects_invalid_frozen_artifact(tmp_path, damage):
    frozen = json.loads(harness.DEFAULT_FORECAST.read_text(encoding="utf-8"))
    if damage == "invalid_pair":
        frozen["engine_version"] = "0.0.0-invalid"
    elif damage == "unsigned_claims_signed":
        frozen["publication_receipt"]["attestation_status"] = "host_signed"
    elif damage == "currency":
        frozen["currency"] = "USD"
    elif damage == "unit":
        frozen["unit"] = "billion"
    else:
        frozen["segments"][0]["scenarios"]["base"]["effective_revenue"]["2030"] *= 1.1
    forecast_path = tmp_path / "damaged.json"
    forecast_path.write_text(json.dumps(frozen), encoding="utf-8")
    parent = tmp_path / "runs-parent"
    parent.mkdir()
    environment = dict(os.environ, PYTHON_DOTENV_DISABLED="1")
    environment.pop("REVENUE_ATTESTATION_PROVIDER", None)
    result = subprocess.run([
        sys.executable, "-B", "-X", "utf8", str(ROOT / "e2e/run_biren_invest_e2e.py"),
        "--forecast", str(forecast_path), "--runs-dir", str(parent),
    ], capture_output=True, text=True, encoding="utf-8", timeout=30, env=environment)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "strong forecast validation rejected" in result.stderr
    assert list(parent.iterdir()) == []


@pytest.fixture
def biren_execution():
    frozen = json.loads(harness.DEFAULT_FORECAST.read_text(encoding="utf-8"))
    manifest = json.loads(harness.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    return company.run_company(manifest, frozen)


def test_intermediate_financial_mutation_is_detected_at_its_public_read(tmp_path, biren_execution):
    output = tmp_path / "run"
    company.write_execution(output, biren_execution)
    expected = json.loads((harness.EXPECTED_DIR / "expected-0e1cc8d4c73d.json").read_text(encoding="utf-8"))
    harness.collect_steps_3_to_8(output, expected)
    path = output / "segment_001_financials.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["data"]["annual_financials"]["base"]["2030"]["net_income"] += 1
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(AssertionError, match="STEP 3.*public validation"):
        harness.collect_steps_3_to_8(output, expected)


def test_live_harness_actually_invokes_phase_checks(tmp_path, biren_execution, monkeypatch):
    frozen = biren_execution["frozen_revenue_forecast"]
    manifest = tmp_path / "unused-manifest.json"
    forecast = tmp_path / "unused-forecast.json"
    def actual_writer(_manifest, _forecast, output):
        company.write_execution(output, biren_execution)
    calls = []
    def rejected_phase(output, _expected):
        calls.append(output)
        raise AssertionError("live phase sentinel")
    monkeypatch.setattr(harness, "run_orchestrator", actual_writer)
    monkeypatch.setattr(harness, "collect_steps_3_to_8", rejected_phase)
    golden = harness.EXPECTED_DIR / f"expected-{frozen['input_sha256'][:12]}.json"
    with pytest.raises(AssertionError, match="live phase sentinel"):
        harness.check_runs(SimpleNamespace(update_golden=False), frozen, forecast, manifest, golden, tmp_path)
    assert calls == [tmp_path / "run-1"]


def test_even_explicit_metadata_refresh_cannot_absorb_economic_drift():
    current = json.loads((harness.EXPECTED_DIR / "expected-0e1cc8d4c73d.json").read_text(encoding="utf-8"))
    changed = copy.deepcopy(current)
    changed["valuation_equity"]["base"] *= 1.1
    assert harness.economic_differences(changed, current)
    assert not harness.economic_differences(copy.deepcopy(current), current)


def test_frozen_fixture_is_a_real_documented_unsigned_emission():
    from schema_compatibility import SCHEMA_EMIT_ENGINES
    frozen = json.loads(harness.DEFAULT_FORECAST.read_text(encoding="utf-8"))
    assert frozen["engine_version"] in SCHEMA_EMIT_ENGINES[frozen["schema_version"]]
    assert frozen["publication_receipt"]["attestation_status"] == "unattested"
    harness.collect_step_1_forecast_valid(frozen, harness.DEFAULT_FORECAST)


def test_offline_bootstrap_blocks_actual_socket_attempt(tmp_path):
    script = tmp_path / "socket_attempt.py"
    script.write_text("import socket; socket.create_connection(('127.0.0.1', 9))", encoding="utf-8")
    result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(ROOT / "e2e/offline_cli.py"), str(script)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "Network is disabled in the offline E2E process" in result.stderr
