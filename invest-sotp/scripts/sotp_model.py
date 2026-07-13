"""Pure SOTP composition over validated segment valuation artifacts."""

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
    SCENARIOS,
    create_artifact,
    read_json,
    validate_artifact,
    write_new_json,
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InvestmentArtifactError(message)


def _parameter_index(model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values = model.get("parameters", [])
    _require(isinstance(values, list), "parameters must be a list")
    index = {}
    for parameter in values:
        _require(isinstance(parameter, dict), "SOTP parameter must be an object")
        parameter_id = parameter.get("parameter_id")
        _require(isinstance(parameter_id, str) and parameter_id.strip() and parameter_id not in index, "SOTP parameter_id must be unique")
        index[parameter_id] = parameter
    return index


def _parameter_value(index: dict[str, dict[str, Any]], template: str, scenario: str, dimension: str | None = None) -> float:
    parameter_id = template.format(scenario=scenario)
    _require(parameter_id in index, f"missing SOTP parameter: {parameter_id}")
    parameter = index[parameter_id]
    _require(parameter.get("scenario", "shared") in {"shared", scenario}, f"SOTP parameter scenario mismatch: {parameter_id}")
    if dimension:
        _require(parameter.get("dimension") == dimension, f"SOTP parameter dimension mismatch: {parameter_id}")
    value = parameter.get("value")
    _require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)), f"invalid SOTP parameter: {parameter_id}")
    return float(value)


def _selected_value(artifact: dict[str, Any], selection: str, scenario: str) -> float:
    scenario_data = artifact["data"]["scenario_valuations"][scenario]
    if selection == "weighted":
        _require("weighted_equity_value" in scenario_data, f"weighted valuation not available: {artifact['scope']['name']}")
        return float(scenario_data["weighted_equity_value"])
    methods = scenario_data["methods"]
    _require(selection in methods, f"unknown selected method {selection} for {artifact['scope']['name']}")
    return float(methods[selection]["equity_value"])


def run_sotp(valuations: list[dict[str, Any]], model: dict[str, Any]) -> dict[str, Any]:
    _require(isinstance(valuations, list) and valuations, "SOTP requires valuation artifacts")
    for artifact in valuations:
        validate_artifact(artifact)
        _require(artifact["module"] == "valuation", "SOTP accepts valuation artifacts only")
        _require(artifact["scope"]["type"] == "segment", "SOTP parts must be segment scoped")
        _require(artifact["scenario_set"] == list(SCENARIOS), "SOTP scenario set mismatch")
    first = valuations[0]
    identity = first["identity"]
    revenue_ref = first["revenue_forecast_ref"]
    names = set()
    for artifact in valuations:
        name = artifact["scope"]["name"]
        _require(name not in names, f"duplicate SOTP segment: {name}")
        names.add(name)
        _require(artifact["identity"] == identity, f"SOTP identity mismatch: {name}")
        _require(artifact["revenue_forecast_ref"] == revenue_ref, f"SOTP revenue lineage mismatch: {name}")
    selections = model.get("segment_selections")
    _require(isinstance(selections, dict) and set(selections) == names, "segment_selections must cover each segment exactly")
    ownership = model.get("ownership_parameter_templates")
    _require(isinstance(ownership, dict) and set(ownership) == names, "ownership parameters must cover each segment exactly")
    parameters = _parameter_index(model)
    adjustments = model.get("company_adjustments", [])
    _require(isinstance(adjustments, list), "company_adjustments must be a list")
    adjustment_names = set()
    for item in adjustments:
        _require(isinstance(item, dict), "company adjustment must be an object")
        name = item.get("name")
        _require(isinstance(name, str) and name.strip() and name not in adjustment_names, "company adjustment name must be unique")
        adjustment_names.add(name)
        _require(item.get("sign") in (-1, 1), f"company adjustment sign must be -1 or 1: {name}")
    scenario_values = {}
    for scenario in SCENARIOS:
        parts = []
        parts_total = 0.0
        for artifact in valuations:
            name = artifact["scope"]["name"]
            raw_value = _selected_value(artifact, selections[name], scenario)
            owned = _parameter_value(parameters, ownership[name], scenario, "ratio")
            _require(0 <= owned <= 1, f"ownership outside 0..1: {name}/{scenario}")
            owned_value = raw_value * owned
            parts_total += owned_value
            parts.append({
                "segment": name, "selection": selections[name], "raw_equity_value": raw_value,
                "ownership": owned, "owned_equity_value": owned_value,
                "valuation_artifact_id": artifact["artifact_id"],
            })
        adjustment_detail = []
        adjustment_total = 0.0
        for item in adjustments:
            value = _parameter_value(parameters, item["parameter_id_template"], scenario)
            signed = item["sign"] * value
            adjustment_total += signed
            adjustment_detail.append({"name": item["name"], "value": value, "sign": item["sign"], "signed_value": signed})
        scenario_values[scenario] = {
            "parts": parts,
            "parts_total": parts_total,
            "company_adjustments": adjustment_detail,
            "adjustment_total": adjustment_total,
            "sotp_equity_value": parts_total + adjustment_total,
        }
    data = {
        "management_target_coverage_status": revenue_ref["management_target_coverage_status"],
        "management_target_summary": revenue_ref["management_target_summary"],
        "scenario_sotp": scenario_values,
    }
    return create_artifact(
        "sotp", identity, {"type": "company", "name": identity["company_name"]}, data,
        scenario_set=list(SCENARIOS), revenue_forecast_ref=revenue_ref,
        upstream_artifacts=valuations,
        sources=model.get("sources", []), parameters=model.get("parameters", []),
        evidence_claims=model.get("evidence_claims", []), limitations=model.get("limitations", []),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate segment valuation artifacts")
    parser.add_argument("model")
    parser.add_argument("valuations", nargs="+")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = run_sotp([read_json(path) for path in args.valuations], read_json(args.model))
        write_new_json(args.output, result)
        return 0
    except (InvestmentArtifactError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
