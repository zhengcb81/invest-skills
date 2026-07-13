"""Cross-company comparison over validated module artifacts."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


CORE_SCRIPTS = Path(__file__).resolve().parents[2] / "invest-core" / "scripts"
if str(CORE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CORE_SCRIPTS))

from invest_contracts import (  # noqa: E402
    InvestmentArtifactError,
    create_artifact,
    read_json,
    validate_artifact,
    write_new_json,
)


def _require(condition: bool, message: str) -> None:
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


def _parameter_index(model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index = {}
    for parameter in model.get("parameters", []):
        _require(isinstance(parameter, dict), "comparison parameter must be an object")
        parameter_id = parameter.get("parameter_id")
        _require(isinstance(parameter_id, str) and parameter_id.strip() and parameter_id not in index, "comparison parameter_id must be unique")
        index[parameter_id] = parameter
    return index


def _normalization_factor(company: str, artifact: dict[str, Any], model: dict[str, Any], parameters: dict[str, dict[str, Any]]) -> float:
    target_currency = model["target_currency"]
    target_unit = model["target_unit"]
    if artifact["identity"]["currency"] == target_currency and artifact["identity"]["unit"] == target_unit:
        return 1.0
    mapping = model.get("normalization_parameter_ids", {})
    _require(company in mapping, f"missing normalization parameter for {company}")
    parameter_id = mapping[company]
    _require(parameter_id in parameters, f"unknown normalization parameter: {parameter_id}")
    parameter = parameters[parameter_id]
    _require(parameter.get("dimension") == "currency_rate", f"normalization parameter must use currency_rate: {parameter_id}")
    value = parameter.get("value")
    _require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and float(value) > 0, f"invalid normalization factor: {parameter_id}")
    return float(value)


def run_comparison(artifacts: list[dict[str, Any]], model: dict[str, Any]) -> dict[str, Any]:
    _require(isinstance(artifacts, list) and len(artifacts) >= 2, "comparison requires at least two artifacts")
    for artifact in artifacts:
        validate_artifact(artifact)
    modules = {artifact["module"] for artifact in artifacts}
    _require(len(modules) == 1, "comparison artifacts must use the same module")
    companies = [artifact["identity"]["company_name"] for artifact in artifacts]
    _require(len(companies) == len(set(companies)), "comparison companies must be unique")
    scenario_sets = {tuple(artifact["scenario_set"]) for artifact in artifacts}
    _require(len(scenario_sets) == 1, "comparison scenario sets mismatch")
    forecast_years = {tuple(artifact["identity"]["forecast_years"]) for artifact in artifacts}
    _require(len(forecast_years) == 1, "comparison forecast years mismatch")
    if model.get("require_same_as_of", True):
        _require(len({artifact["identity"]["as_of_date"] for artifact in artifacts}) == 1, "comparison as_of_date mismatch")
    target_currency = model.get("target_currency")
    target_unit = model.get("target_unit")
    _require(isinstance(target_currency, str) and target_currency.strip(), "target_currency is required")
    _require(isinstance(target_unit, str) and target_unit.strip(), "target_unit is required")
    metrics = model.get("metrics")
    _require(isinstance(metrics, list) and metrics, "comparison metrics must be a non-empty list")
    metric_names = set()
    for metric in metrics:
        _require(isinstance(metric, dict), "comparison metric must be an object")
        name = metric.get("name")
        _require(isinstance(name, str) and name.strip() and name not in metric_names, "comparison metric name must be unique")
        metric_names.add(name)
        _require(isinstance(metric.get("path"), str) and metric["path"].strip(), f"metric path required: {name}")
        _require(isinstance(metric.get("monetary"), bool), f"metric monetary flag required: {name}")
    parameters = _parameter_index(model)
    rows = []
    terminal_year = str(next(iter(forecast_years))[-1])
    scenario = model.get("scenario")
    if next(iter(scenario_sets)):
        _require(scenario in next(iter(scenario_sets)), "comparison scenario is required and must match artifacts")
    for artifact in artifacts:
        company = artifact["identity"]["company_name"]
        factor = _normalization_factor(company, artifact, model, parameters)
        values = {}
        for metric in metrics:
            path = metric["path"].format(scenario=scenario or "", terminal_year=terminal_year)
            value = _extract(artifact, path)
            _require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)), f"comparison metric must be numeric: {metric['name']}/{company}")
            values[metric["name"]] = float(value) * factor if metric["monetary"] else float(value)
        rows.append({"company_name": company, "source_artifact_id": artifact["artifact_id"], "normalization_factor": factor, "values": values})
    identity = {
        "company_name": "Comparison: " + " | ".join(sorted(companies)),
        "as_of_date": model.get("comparison_as_of_date", max(artifact["identity"]["as_of_date"] for artifact in artifacts)),
        "currency": target_currency,
        "unit": target_unit,
        "fiscal_year_end": "mixed",
        "base_year": artifacts[0]["identity"]["base_year"],
        "forecast_years": list(next(iter(forecast_years))),
    }
    data = {"source_module": next(iter(modules)), "scenario": scenario, "metrics": metrics, "rows": rows}
    return create_artifact(
        "compare", identity, {"type": "comparison", "names": sorted(companies)}, data,
        scenario_set=list(next(iter(scenario_sets))), upstream_artifacts=artifacts,
        sources=model.get("sources", []), parameters=model.get("parameters", []),
        evidence_claims=model.get("evidence_claims", []), limitations=model.get("limitations", []),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare validated investment artifacts")
    parser.add_argument("model")
    parser.add_argument("artifacts", nargs="+")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = run_comparison([read_json(path) for path in args.artifacts], read_json(args.model))
        write_new_json(args.output, result)
        return 0
    except (InvestmentArtifactError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
