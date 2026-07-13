"""Manifest-driven orchestration for heterogeneous company segments and sidecars."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any


SUITE = Path(__file__).resolve().parents[2]
for path in (
    SUITE / "invest-core" / "scripts", SUITE / "invest-financials" / "scripts",
    SUITE / "invest-valuation" / "scripts", SUITE / "invest-sotp" / "scripts",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from bundle_validator import render_bundle_markdown, run_bundle, validate_module_semantics  # noqa: E402
from financial_model import run_financial_model, validate_financial_artifact  # noqa: E402
from invest_contracts import (  # noqa: E402
    InvestmentArtifactError, build_scenario_manifest, canonical_sha256,
    read_json, revenue_reference, validate_revenue_forecast, write_new_json,
)
from manifest_contract import ManifestContractError, scenario_manifest_from_policy, validate_manifest  # noqa: E402
from sotp_model import run_sotp, validate_sotp_artifact  # noqa: E402
from valuation_model import run_valuation, validate_valuation_artifact  # noqa: E402


def _require(condition: object, message: str) -> None:
    if not condition:
        raise InvestmentArtifactError(message)


def _inventory(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "module": artifact["module"], "scope": artifact["scope"],
            "artifact_id": artifact["artifact_id"], "artifact_sha256": artifact["artifact_sha256"],
        }
        for artifact in artifacts
    ]


def _scope_key(module: str, scope: dict[str, Any]) -> tuple[str, str, str]:
    return module, scope["type"], scope.get("name", "")


def _validate_supplementals(
    declarations: list[dict[str, Any]],
    supplied: list[dict[str, Any]],
    identity: dict[str, Any],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for artifact in supplied:
        validate_module_semantics(artifact)
        _require(artifact["module"] in {"management", "moat", "distribution"}, f"unsupported supplemental module: {artifact['module']}")
        _require(artifact["identity"] == identity, f"supplemental identity mismatch: {artifact['module']}")
        _require(artifact["artifact_id"] not in by_id, "duplicate supplied supplemental artifact")
        by_id[artifact["artifact_id"]] = artifact
    declared_ids = {item["artifact_id"] for item in declarations}
    _require(set(by_id) <= declared_ids, "supplied supplemental artifact is not declared in manifest")
    for declaration in declarations:
        selected_artifact = by_id.get(declaration["artifact_id"])
        if selected_artifact is None:
            _require(not declaration["required"], f"required supplemental artifact is missing: {declaration['module']}/{declaration['scope']}")
            continue
        _require(selected_artifact["artifact_sha256"] == declaration["artifact_sha256"], "supplemental artifact hash mismatch")
        _require(selected_artifact["module"] == declaration["module"] and selected_artifact["scope"] == declaration["scope"], "supplemental module/scope mismatch")
    return [by_id[item["artifact_id"]] for item in declarations if item["artifact_id"] in by_id]


def run_company(
    manifest: dict[str, Any],
    forecast: dict[str, Any],
    supplemental_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the full declared graph in memory and return validated frozen outputs."""
    frozen_forecast = copy.deepcopy(forecast)
    validate_revenue_forecast(frozen_forecast)
    revenue_ref = revenue_reference(frozen_forecast)
    try:
        normalized = validate_manifest(manifest, frozen_forecast)
    except ManifestContractError as exc:
        raise InvestmentArtifactError(str(exc)) from exc
    manifest_sha256 = canonical_sha256(normalized)
    scenario_manifest = build_scenario_manifest(
        ["low", "base", "high"], scenario_manifest_from_policy(normalized["scenario_policy"]),
    )
    assert scenario_manifest is not None

    financials: list[dict[str, Any]] = []
    valuations: list[dict[str, Any]] = []
    for config in normalized["segments"]:
        financial_model = copy.deepcopy(config["financial_model"])
        financial_model["scenario_manifest"] = scenario_manifest
        financial = run_financial_model(frozen_forecast, financial_model)
        validate_financial_artifact(financial)
        _require(financial["scope"] == {"type": "segment", "name": config["name"]}, f"financial scope drift: {config['name']}")
        valuation_model = copy.deepcopy(config["valuation_model"])
        valuation_model["scenario_manifest"] = scenario_manifest
        valuation = run_valuation(financial, valuation_model)
        validate_valuation_artifact(valuation)
        _require(valuation["scope"] == financial["scope"], f"valuation scope drift: {config['name']}")
        financials.append(financial)
        valuations.append(valuation)

    sotp_model = copy.deepcopy(normalized["sotp_model"])
    sotp = run_sotp(valuations, sotp_model)
    validate_sotp_artifact(sotp)
    supplementals = _validate_supplementals(
        normalized.get("supplemental_artifacts", []), list(supplemental_artifacts or []),
        financials[0]["identity"],
    )
    bundle_inputs = [*financials, *valuations, sotp, *supplementals]
    bundle_plan = copy.deepcopy(normalized["bundle_plan"])
    bundle_plan["manifest_sha256"] = manifest_sha256
    bundle_plan["scenario_manifest"] = scenario_manifest
    bundle = run_bundle(
        bundle_inputs, bundle_plan, manifest_snapshot=normalized,
        frozen_revenue_forecast=frozen_forecast,
        supplemental_artifact_ids=[item["artifact_id"] for item in supplementals],
    )
    _require(bundle["revenue_forecast_ref"] == revenue_ref, "bundle revenue lineage drift")

    all_artifacts = [*bundle_inputs, bundle]
    supplemental_files = [f"supplemental_{index:03d}_{artifact['module']}.json" for index, artifact in enumerate(supplementals, start=1)]
    output_files = [
        "manifest.snapshot.json", "revenue_forecast.snapshot.json",
        *[f"segment_{index:03d}_financials.json" for index in range(1, len(financials) + 1)],
        *[f"segment_{index:03d}_valuation.json" for index in range(1, len(valuations) + 1)],
        "sotp.json", *supplemental_files, "bundle.json", "report.md", "receipt.json",
    ]
    receipt = {
        "receipt_schema_version": "2.0", "status": "pass",
        "manifest_sha256": manifest_sha256,
        "revenue_input_sha256": frozen_forecast["input_sha256"],
        "revenue_result_sha256": frozen_forecast["result_sha256"],
        "revenue_forecast_ref": revenue_ref,
        "scenario_manifest_sha256": scenario_manifest["scenario_manifest_sha256"],
        "scenario_set": ["low", "base", "high"],
        "segment_count": len(financials), "supplemental_count": len(supplementals),
        "artifact_inventory": _inventory(all_artifacts), "output_files": output_files,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return {
        "normalized_manifest": normalized, "frozen_revenue_forecast": frozen_forecast,
        "financials": financials, "valuations": valuations, "sotp": sotp,
        "supplementals": supplementals, "bundle": bundle,
        "report_markdown": render_bundle_markdown(bundle), "receipt": receipt,
    }


def write_execution(output_directory: str | Path, execution: dict[str, Any]) -> None:
    """Publish a validated execution atomically without overwriting any path."""
    output = Path(output_directory).expanduser().resolve()
    _require(not output.exists(), f"output directory already exists: {output}")
    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = parent / f".{output.name}.{uuid.uuid4().hex}.tmp"
    _require(not temporary.exists(), f"temporary output path already exists: {temporary}")
    temporary.mkdir()
    try:
        write_new_json(temporary / "manifest.snapshot.json", execution["normalized_manifest"])
        write_new_json(temporary / "revenue_forecast.snapshot.json", execution["frozen_revenue_forecast"])
        for index, artifact in enumerate(execution["financials"], start=1):
            write_new_json(temporary / f"segment_{index:03d}_financials.json", artifact)
        for index, artifact in enumerate(execution["valuations"], start=1):
            write_new_json(temporary / f"segment_{index:03d}_valuation.json", artifact)
        write_new_json(temporary / "sotp.json", execution["sotp"])
        for index, artifact in enumerate(execution["supplementals"], start=1):
            write_new_json(temporary / f"supplemental_{index:03d}_{artifact['module']}.json", artifact)
        write_new_json(temporary / "bundle.json", execution["bundle"])
        (temporary / "report.md").write_text(execution["report_markdown"], encoding="utf-8")
        write_new_json(temporary / "receipt.json", execution["receipt"])
        actual_files = sorted(path.name for path in temporary.iterdir())
        _require(actual_files == sorted(execution["receipt"]["output_files"]), "execution output inventory mismatch")
        temporary.rename(output)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def write_failure_receipt(
    output_directory: str | Path,
    *,
    stage: str,
    error: Exception,
    manifest: dict[str, Any] | None = None,
    forecast: dict[str, Any] | None = None,
) -> Path:
    output = Path(output_directory).expanduser().resolve()
    failure_path = output.parent / f"{output.name}.failure.json"
    receipt = {
        "receipt_schema_version": "2.0", "status": "fail", "stage": stage,
        "error_type": type(error).__name__, "error_message": str(error),
        "manifest_sha256": canonical_sha256(manifest) if isinstance(manifest, dict) else None,
        "revenue_result_sha256": forecast.get("result_sha256") if isinstance(forecast, dict) else None,
        "success_output_created": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    failure_path.parent.mkdir(parents=True, exist_ok=True)
    write_new_json(failure_path, receipt)
    return failure_path


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run a declarative heterogeneous-segment investment analysis")
    parser.add_argument("manifest")
    parser.add_argument("forecast")
    parser.add_argument("--supplemental", action="append", default=[])
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    stage = "load_inputs"
    manifest: dict[str, Any] | None = None
    forecast: dict[str, Any] | None = None
    try:
        manifest = read_json(args.manifest)
        forecast = read_json(args.forecast)
        supplementals = [read_json(path) for path in args.supplemental]
        stage = "orchestrate"
        execution = run_company(manifest, forecast, supplementals)
        stage = "publish"
        write_execution(args.output_dir, execution)
        print(json.dumps(execution["receipt"], ensure_ascii=False, indent=2))
        return 0
    except (InvestmentArtifactError, OSError, json.JSONDecodeError) as exc:
        try:
            write_failure_receipt(args.output_dir, stage=stage, error=exc, manifest=manifest, forecast=forecast)
        except (InvestmentArtifactError, OSError):
            pass
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
