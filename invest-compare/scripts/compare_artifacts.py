"""Cross-company comparison over validated, explicitly aligned artifacts."""

from __future__ import annotations

import argparse
import copy
import json
import re
import string
import sys
from pathlib import Path
from typing import Any


SUITE = Path(__file__).resolve().parents[2]
for scripts in (SUITE / "invest-core" / "scripts", SUITE / "invest-framework" / "scripts"):
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))

from invest_contracts import (  # noqa: E402
    ARTIFACT_SCHEMA_VERSION,
    CURRENT_SEMANTIC_SUITE_VERSIONS,
    MONETARY_DIMENSIONS,
    PARAMETER_DIMENSIONS,
    InvestmentArtifactError,
    artifact_reference,
    create_artifact,
    finite_number,
    parameter_by_id,
    parse_iso_date,
    read_json,
    validate_artifact,
    write_new_json,
)
from bundle_validator import validate_bundle_artifact  # noqa: E402


COMPARISON_MODEL_SCHEMA_VERSION = "2.1"
LEGACY_COMPARISON_MODEL_SCHEMA_VERSION = "2.0"


def _require(condition: object, message: str) -> None:
    if not condition:
        raise InvestmentArtifactError(message)


def _extract(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise InvestmentArtifactError(f"comparison path not found: {path}")
    return current


def _render_path(template: str, scenario: str | None, source_period: str) -> str:
    try:
        fields = {field for _, field, _, _ in string.Formatter().parse(template) if field is not None}
    except ValueError as exc:
        raise InvestmentArtifactError(f"invalid comparison path template: {template}") from exc
    _require(fields <= {"scenario", "source_period", "source_year"}, f"unsupported comparison path placeholder: {template}")
    source_year = source_period[2:] if source_period.startswith("FY") else source_period[:4]
    try:
        return template.format(scenario=scenario or "", source_period=source_period, source_year=source_year)
    except (KeyError, ValueError) as exc:
        raise InvestmentArtifactError(f"invalid comparison path template: {template}") from exc


def _validate_metric(metric: dict[str, Any], artifacts: list[dict[str, Any]], companies: list[str]) -> None:
    metric_id = metric.get("metric_id")
    _require(isinstance(metric_id, str) and metric_id.strip(), "comparison metric_id is required")
    for field in ("label", "path_template", "target_definition", "comparison_period"):
        _require(isinstance(metric.get(field), str) and metric[field].strip(), f"{metric_id}.{field} is required")
    _require(metric.get("dimension") in PARAMETER_DIMENSIONS, f"unsupported comparison metric dimension: {metric_id}")
    time_basis = metric.get("time_basis")
    _require(time_basis in {"annual", "point_in_time"}, f"invalid comparison time_basis: {metric_id}")
    _require(metric.get("value_basis") in {"enterprise", "equity", "not_applicable"}, f"invalid comparison value_basis: {metric_id}")
    expected_normalization = "currency_scale" if metric["dimension"] in MONETARY_DIMENSIONS | {"per_share"} else "none"
    _require(metric.get("normalization") == expected_normalization, f"comparison normalization does not match metric dimension: {metric_id}")
    source_periods = metric.get("source_periods")
    definitions = metric.get("source_definitions")
    alignments = metric.get("definition_alignments")
    notes = metric.get("reconciliation_notes", {})
    _require(isinstance(source_periods, dict) and set(source_periods) == set(companies), f"source_periods must cover companies: {metric_id}")
    _require(isinstance(definitions, dict) and set(definitions) == set(companies), f"source_definitions must cover companies: {metric_id}")
    assert isinstance(source_periods, dict) and isinstance(definitions, dict)
    _require(all(isinstance(value, str) and value.strip() for value in definitions.values()), f"source definitions must be non-empty: {metric_id}")
    _require(isinstance(alignments, dict) and set(alignments) == set(companies), f"definition_alignments must cover companies: {metric_id}")
    assert isinstance(alignments, dict)
    _require(all(value in {"exact", "reconciled"} for value in alignments.values()), f"invalid definition alignment: {metric_id}")
    _require(isinstance(notes, dict), f"reconciliation_notes must be an object: {metric_id}")
    for artifact in artifacts:
        company = artifact["identity"]["company_name"]
        period = source_periods[company]
        _require(isinstance(period, str), f"source period must be a string: {metric_id}/{company}")
        assert isinstance(period, str)
        if time_basis == "annual":
            _require(isinstance(period, str) and re.fullmatch(r"FY\d{4}", period) is not None, f"annual source period must use FYyyyy: {metric_id}/{company}")
            year = int(period[2:])
            _require(year in {artifact["identity"]["base_year"], *artifact["identity"]["forecast_years"]}, f"source period outside artifact horizon: {metric_id}/{company}")
        else:
            _require(parse_iso_date(period, f"{metric_id}.{company}.source_period") <= parse_iso_date(artifact["identity"]["as_of_date"], "as_of_date"), f"point-in-time metric leaks future information: {metric_id}/{company}")
        if alignments[company] == "reconciled":
            _require(isinstance(notes.get(company), str) and notes[company].strip(), f"reconciled definition requires notes: {metric_id}/{company}")


def _normalization_factor(
    company: str,
    artifact: dict[str, Any],
    metric: dict[str, Any],
    model: dict[str, Any],
    parameters: list[dict[str, Any]],
    comparison_as_of: str,
) -> tuple[float, dict[str, Any]]:
    if metric["normalization"] == "none":
        return 1.0, {"currency_rate": 1.0, "scale_factor": 1.0}
    mappings = model.get("normalizations", {})
    config = mappings.get(company, {})
    _require(isinstance(config, dict), f"normalization config must be an object: {company}")
    currency_rate = 1.0
    if artifact["identity"]["currency"] != model["target_currency"]:
        parameter_id = config.get("currency_rate_parameter_id")
        _require(isinstance(parameter_id, str) and parameter_id, f"missing currency normalization parameter for {company}")
        parameter = parameter_by_id(
            parameters, parameter_id, expected_dimensions={"currency_rate"},
            expected_time_bases={"point_in_time"},
        )
        _require(parameter.get("period") == comparison_as_of, f"currency normalization must use comparison date: {company}")
        currency_rate = finite_number(parameter["value"], f"{parameter_id}.value")
        _require(currency_rate > 0, f"currency normalization must be positive: {company}")
    else:
        _require(config.get("currency_rate_parameter_id") in (None, ""), f"same-currency company must not carry FX normalization: {company}")
    scale_factor = 1.0
    if metric["dimension"] != "per_share" and artifact["identity"]["unit"] != model["target_unit"]:
        scale_factor = finite_number(config.get("scale_factor"), f"normalizations.{company}.scale_factor")
        _require(scale_factor > 0, f"scale normalization must be positive: {company}")
    elif metric["dimension"] != "per_share":
        _require(config.get("scale_factor") in (None, 1, 1.0), f"same-scale company must not carry scale normalization: {company}")
    return currency_rate * scale_factor, {"currency_rate": currency_rate, "scale_factor": scale_factor}


def _validate_model(artifacts: list[dict[str, Any]], model: dict[str, Any]) -> tuple[list[str], str | None, str, str]:
    model_version = model.get("comparison_model_schema_version")
    _require(model_version in {LEGACY_COMPARISON_MODEL_SCHEMA_VERSION, COMPARISON_MODEL_SCHEMA_VERSION}, "comparison_model_schema_version must be 2.0 or 2.1")
    comparison_kind = model.get("comparison_kind", "metrics" if model_version == LEGACY_COMPARISON_MODEL_SCHEMA_VERSION else None)
    _require(comparison_kind in {"metrics", "growth_drivers"}, "comparison_kind must be metrics or growth_drivers")
    assert isinstance(comparison_kind, str)
    if comparison_kind == "growth_drivers":
        _require(model_version == COMPARISON_MODEL_SCHEMA_VERSION, "growth driver comparison requires model schema 2.1")
    _require(isinstance(artifacts, list) and len(artifacts) >= 2, "comparison requires at least two artifacts")
    for artifact in artifacts:
        validate_artifact(artifact)
    modules = {artifact["module"] for artifact in artifacts}
    _require(len(modules) == 1 and "psychology" not in modules, "comparison artifacts must use the same fundamental module")
    if comparison_kind == "growth_drivers":
        _require(modules == {"framework"}, "growth driver comparison requires validated framework bundles")
        for artifact in artifacts:
            validate_bundle_artifact(artifact)
    companies: list[str] = [artifact["identity"]["company_name"] for artifact in artifacts]
    _require(len(companies) == len(set(companies)), "comparison companies must be unique")
    scenario = model.get("scenario")
    if comparison_kind == "growth_drivers":
        _require(scenario in (None, ""), "growth driver comparison is base-path attribution and cannot receive a scenario")
        scenario = None
    else:
        scenario_sets = {tuple(artifact["scenario_set"]) for artifact in artifacts}
        _require(len(scenario_sets) == 1, "comparison scenario sets mismatch")
        scenario_set = next(iter(scenario_sets))
        if scenario_set:
            _require(scenario in scenario_set, "comparison scenario is required and must match artifacts")
        else:
            _require(scenario in (None, ""), "non-scenario artifacts cannot receive a comparison scenario")
            scenario = None
    if model.get("require_same_as_of", True):
        _require(len({artifact["identity"]["as_of_date"] for artifact in artifacts}) == 1, "comparison as_of_date mismatch")
    comparison_as_of = model.get("comparison_as_of_date", max(artifact["identity"]["as_of_date"] for artifact in artifacts))
    _require(isinstance(comparison_as_of, str), "comparison_as_of_date must be a string")
    assert isinstance(comparison_as_of, str)
    parse_iso_date(comparison_as_of, "comparison_as_of_date")
    for field in ("target_currency", "target_unit"):
        _require(isinstance(model.get(field), str) and model[field].strip(), f"{field} is required")
    if comparison_kind == "growth_drivers":
        _require(model.get("require_same_horizon", True) is True, "growth driver comparison requires the same forecast horizon")
        _require(len({tuple(artifact["identity"]["forecast_years"]) for artifact in artifacts}) == 1, "growth driver comparison horizon mismatch")
        _require(all(artifact["identity"]["currency"] == model["target_currency"] for artifact in artifacts), "growth driver comparison currency mismatch")
        _require(all(artifact["identity"]["unit"] == model["target_unit"] for artifact in artifacts), "growth driver comparison unit mismatch")
        for artifact in artifacts:
            summary = artifact["data"]["summary"]
            _require(isinstance(summary.get("growth_driver_summary"), dict), "framework bundle lacks growth driver summary")
            _require(summary.get("growth_driver_summary_sha256") is not None, "framework bundle lacks growth driver summary hash")
            _require(summary.get("growth_driver_analysis_status") in {"validated", "data_gap"}, "framework bundle lacks current growth driver analysis")
        assert scenario is None
        return companies, scenario, comparison_as_of, comparison_kind
    metrics = model.get("metrics")
    _require(isinstance(metrics, list) and metrics, "comparison metrics must be a non-empty list")
    assert isinstance(metrics, list)
    metric_ids: set[str] = set()
    for metric in metrics:
        _require(isinstance(metric, dict), "comparison metric must be an object")
        assert isinstance(metric, dict)
        _require(metric.get("metric_id") not in metric_ids, "comparison metric_id must be unique")
        _validate_metric(metric, artifacts, companies)
        metric_ids.add(metric["metric_id"])
    assert scenario is None or isinstance(scenario, str)
    return companies, scenario, comparison_as_of, comparison_kind


def _calculate_rows(artifacts: list[dict[str, Any]], model: dict[str, Any], scenario: str | None, comparison_as_of: str) -> list[dict[str, Any]]:
    parameters = model.get("parameters", [])
    rows: list[dict[str, Any]] = []
    for artifact in artifacts:
        company = artifact["identity"]["company_name"]
        values: dict[str, Any] = {}
        for metric in model["metrics"]:
            source_period = metric["source_periods"][company]
            path = _render_path(metric["path_template"], scenario, source_period)
            raw_value = finite_number(_extract(artifact, path), f"comparison metric {metric['metric_id']}/{company}")
            factor, components = _normalization_factor(company, artifact, metric, model, parameters, comparison_as_of)
            values[metric["metric_id"]] = {
                "raw_value": raw_value, "normalized_value": raw_value * factor,
                "normalization_factor": factor, "normalization_components": components,
                "source_period": source_period,
                "source_definition": metric["source_definitions"][company],
                "definition_alignment": metric["definition_alignments"][company],
            }
        rows.append({"company_name": company, "source_artifact_id": artifact["artifact_id"], "values": values})
    return rows


def _calculate_growth_driver_rows(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for artifact in artifacts:
        summary = artifact["data"]["summary"]
        rows.append({
            "company_name": artifact["identity"]["company_name"],
            "source_artifact_id": artifact["artifact_id"],
            "growth_driver_analysis_status": summary["growth_driver_analysis_status"],
            "growth_driver_analysis_sha256": summary["growth_driver_analysis_sha256"],
            "growth_driver_summary_sha256": summary["growth_driver_summary_sha256"],
            "growth_driver_summary": copy.deepcopy(summary["growth_driver_summary"]),
        })
    return rows


def validate_comparison_artifact(artifact: dict[str, Any]) -> None:
    validate_artifact(artifact)
    _require(artifact["module"] == "compare", "expected comparison artifact")
    if artifact["artifact_schema_version"] != ARTIFACT_SCHEMA_VERSION:
        return
    data = artifact["data"]
    expected_version = COMPARISON_MODEL_SCHEMA_VERSION if artifact["invest_suite_version"] in CURRENT_SEMANTIC_SUITE_VERSIONS else LEGACY_COMPARISON_MODEL_SCHEMA_VERSION
    _require(data.get("comparison_model_schema_version") == expected_version, "invalid comparison model schema")
    comparison_kind = data.get("comparison_kind", "metrics" if expected_version == LEGACY_COMPARISON_MODEL_SCHEMA_VERSION else None)
    _require(comparison_kind in {"metrics", "growth_drivers"}, "invalid comparison kind")
    snapshots = data.get("source_artifact_snapshots")
    _require(isinstance(snapshots, list) and len(snapshots) >= 2, "comparison artifact must freeze source artifacts")
    model = {
        "comparison_model_schema_version": data["comparison_model_schema_version"],
        "comparison_kind": comparison_kind,
        "target_currency": artifact["identity"]["currency"], "target_unit": artifact["identity"]["unit"],
        "require_same_as_of": data["require_same_as_of"], "comparison_as_of_date": artifact["identity"]["as_of_date"],
        "require_same_horizon": data.get("require_same_horizon", True),
        "scenario": data.get("scenario"), "metrics": data.get("metrics", []),
        "normalizations": data.get("normalizations", {}), "parameters": artifact["parameters"],
    }
    _, scenario, comparison_as_of, _ = _validate_model(snapshots, model)
    _require(artifact["upstream_artifacts"] == [artifact_reference(item) for item in snapshots], "comparison upstream snapshots mismatch")
    expected = (
        _calculate_growth_driver_rows(snapshots)
        if comparison_kind == "growth_drivers"
        else _calculate_rows(snapshots, model, scenario, comparison_as_of)
    )
    _require(data.get("rows") == expected, "comparison semantic recomputation mismatch")


def run_comparison(artifacts: list[dict[str, Any]], model: dict[str, Any]) -> dict[str, Any]:
    companies, scenario, comparison_as_of, comparison_kind = _validate_model(artifacts, model)
    rows = (
        _calculate_growth_driver_rows(artifacts)
        if comparison_kind == "growth_drivers"
        else _calculate_rows(artifacts, model, scenario, comparison_as_of)
    )
    all_forecast_years = sorted({year for artifact in artifacts for year in artifact["identity"]["forecast_years"]})
    base_year = min(artifact["identity"]["base_year"] for artifact in artifacts)
    forecast_years = [year for year in all_forecast_years if year > base_year]
    _require(bool(forecast_years), "comparison requires at least one forward year in source identities")
    identity: dict[str, Any] = {
        "company_name": "Comparison: " + " | ".join(sorted(companies)),
        "as_of_date": comparison_as_of, "currency": model["target_currency"], "unit": model["target_unit"],
        "fiscal_year_end": "mixed", "base_year": base_year, "forecast_years": forecast_years,
    }
    data = {
        "comparison_model_schema_version": COMPARISON_MODEL_SCHEMA_VERSION,
        "comparison_kind": comparison_kind,
        "source_module": artifacts[0]["module"], "scenario": scenario,
        "require_same_as_of": model.get("require_same_as_of", True),
        "require_same_horizon": model.get("require_same_horizon", True),
        "metrics": model.get("metrics", []), "normalizations": model.get("normalizations", {}),
        "source_artifact_snapshots": artifacts, "rows": rows,
    }
    scenario_set = [] if comparison_kind == "growth_drivers" else list(artifacts[0]["scenario_set"])
    artifact = create_artifact(
        "compare", identity, {"type": "comparison", "names": sorted(companies)}, data,
        scenario_set=scenario_set, upstream_artifacts=artifacts,
        sources=model.get("sources", []), parameters=model.get("parameters", []),
        evidence_claims=model.get("evidence_claims", []), limitations=model.get("limitations", []),
    )
    validate_comparison_artifact(artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare explicitly aligned investment artifacts")
    parser.add_argument("model", nargs="?")
    parser.add_argument("artifacts", nargs="*")
    parser.add_argument("--output")
    parser.add_argument("--validate-artifact")
    args = parser.parse_args()
    try:
        if args.validate_artifact:
            validate_comparison_artifact(read_json(args.validate_artifact))
            print("comparison artifact valid")
            return 0
        _require(bool(args.model and len(args.artifacts) >= 2 and args.output), "model, at least two artifacts, and --output are required")
        result = run_comparison([read_json(path) for path in args.artifacts], read_json(args.model))
        write_new_json(args.output, result)
        return 0
    except (InvestmentArtifactError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
