"""Pure, basis-explicit SOTP composition over validated segment valuations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SUITE = Path(__file__).resolve().parents[2]
for scripts in (SUITE / "invest-core" / "scripts", SUITE / "invest-valuation" / "scripts"):
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))

from invest_contracts import (  # noqa: E402
    ARTIFACT_SCHEMA_VERSION,
    InvestmentArtifactError,
    SCENARIOS,
    artifact_reference,
    compute_security_value,
    create_artifact,
    finite_number,
    parameter_by_id,
    read_json,
    render_parameter_template,
    validate_artifact,
    write_new_json,
)
from valuation_model import validate_valuation_artifact  # noqa: E402


SOTP_MODEL_SCHEMA_VERSION = "2.0"


def _require(condition: object, message: str) -> None:
    if not condition:
        raise InvestmentArtifactError(message)


def _parameter(
    parameters: list[dict[str, Any]], template: str, scenario: str,
    *, dimension: str, time_basis: str,
) -> dict[str, Any]:
    parameter_id = render_parameter_template(template, scenario)
    _require(any(item.get("parameter_id") == parameter_id for item in parameters), f"missing SOTP parameter: {parameter_id}")
    return parameter_by_id(
        parameters, parameter_id, expected_dimensions={dimension},
        expected_time_bases={time_basis}, scenario=scenario,
    )


def _selected_value(artifact: dict[str, Any], selection: dict[str, Any], scenario: str) -> tuple[float, str]:
    scenario_data = artifact["data"]["scenario_valuations"][scenario]
    selection_type = selection["selection_type"]
    basis = selection["selected_value_basis"]
    if selection_type == "weighted":
        _require(basis == "equity", f"weighted SOTP selection is equity-only: {artifact['scope']['name']}")
        _require("weighted_equity_value_current" in scenario_data, f"weighted valuation not available: {artifact['scope']['name']}")
        return finite_number(scenario_data["weighted_equity_value_current"], "weighted SOTP value"), "weighted"
    method_id = selection["method_id"]
    methods = scenario_data["methods"]
    _require(method_id in methods, f"unknown selected method {method_id} for {artifact['scope']['name']}")
    method = methods[method_id]
    if basis == "enterprise":
        _require(method.get("value_basis") == "enterprise", f"selected method is not enterprise basis: {artifact['scope']['name']}/{method_id}")
        return finite_number(method["value_before_adjustments_current"], "selected enterprise value"), method_id
    return finite_number(method["equity_value_current"], "selected equity value"), method_id


def _validate_valuation_parts(
    valuations: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], set[str]]:
    _require(isinstance(valuations, list) and valuations, "SOTP requires valuation artifacts")
    for artifact in valuations:
        validate_valuation_artifact(artifact)
        _require(artifact["module"] == "valuation", "SOTP accepts valuation artifacts only")
        _require(artifact["scope"]["type"] == "segment", "SOTP parts must be segment scoped")
        _require(artifact["scenario_set"] == list(SCENARIOS), "SOTP scenario set mismatch")
    first = valuations[0]
    identity = first["identity"]
    revenue_ref = first["revenue_forecast_ref"]
    scenario_manifest = first["scenario_manifest"]
    names: set[str] = set()
    for artifact in valuations:
        name = artifact["scope"]["name"]
        _require(name not in names, f"duplicate SOTP segment: {name}")
        names.add(name)
        _require(artifact["identity"] == identity, f"SOTP identity mismatch: {name}")
        _require(artifact["revenue_forecast_ref"] == revenue_ref, f"SOTP revenue lineage mismatch: {name}")
        _require(artifact["scenario_manifest"] == scenario_manifest, f"SOTP scenario manifest mismatch: {name}")
    return identity, revenue_ref, names


def _validate_segment_selections(value: Any, names: set[str], aggregation_basis: str) -> None:
    _require(isinstance(value, dict) and set(value) == names, "segment_selections must cover each segment exactly")
    assert isinstance(value, dict)
    for name, selection in value.items():
        _require(isinstance(selection, dict), f"segment selection must be an object: {name}")
        assert isinstance(selection, dict)
        _require(selection.get("selection_type") in {"method", "weighted"}, f"invalid selection_type: {name}")
        _require(selection.get("selected_value_basis") == aggregation_basis, f"segment selection basis mismatch: {name}")
        if selection["selection_type"] == "method":
            _require(isinstance(selection.get("method_id"), str) and selection["method_id"].strip(), f"method selection requires method_id: {name}")
        else:
            _require(selection.get("method_id") in (None, ""), f"weighted selection cannot include method_id: {name}")


def _validate_company_bridge(value: Any, aggregation_basis: str) -> None:
    _require(isinstance(value, dict), "company_bridge must be an object")
    assert isinstance(value, dict)
    expected_stage = "enterprise_to_equity" if aggregation_basis == "enterprise" else "equity_level"
    _require(value.get("stage") == expected_stage, "company_bridge stage does not match aggregation_basis")
    _require(value.get("completeness_status") == "complete", "company_bridge must be complete before publishing SOTP equity value")
    _require(isinstance(value.get("rationale"), str) and value["rationale"].strip(), "company_bridge rationale is required")
    adjustments = value.get("adjustments")
    _require(isinstance(adjustments, list), "company_bridge.adjustments must be a list")
    assert isinstance(adjustments, list)
    adjustment_names: set[str] = set()
    for item in adjustments:
        _require(isinstance(item, dict), "company bridge adjustment must be an object")
        assert isinstance(item, dict)
        name = item.get("name")
        _require(isinstance(name, str) and name.strip() and name not in adjustment_names, "company bridge adjustment name must be unique")
        assert isinstance(name, str)
        adjustment_names.add(name)
        sign = item.get("sign")
        _require(isinstance(sign, int) and not isinstance(sign, bool) and sign in (-1, 1), f"company bridge adjustment sign must be -1 or 1: {name}")
        _require(isinstance(item.get("parameter_id_template"), str) and item["parameter_id_template"], f"company bridge parameter is required: {name}")


def _validate_inputs(valuations: list[dict[str, Any]], model: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], set[str]]:
    identity, revenue_ref, names = _validate_valuation_parts(valuations)
    _require(model.get("sotp_model_schema_version") == SOTP_MODEL_SCHEMA_VERSION, "sotp_model_schema_version must be 2.0")
    aggregation_basis = model.get("aggregation_basis")
    _require(aggregation_basis in {"enterprise", "equity"}, "aggregation_basis must be enterprise or equity")
    assert isinstance(aggregation_basis, str)
    _validate_segment_selections(model.get("segment_selections"), names, aggregation_basis)
    ownership = model.get("ownership_parameter_templates")
    _require(isinstance(ownership, dict) and set(ownership) == names, "ownership parameters must cover each segment exactly")
    _validate_company_bridge(model.get("company_bridge"), aggregation_basis)
    return identity, revenue_ref, names


def _calculate_sotp(valuations: list[dict[str, Any]], model: dict[str, Any]) -> dict[str, Any]:
    parameters = model.get("parameters", [])
    selections = model["segment_selections"]
    ownership = model["ownership_parameter_templates"]
    aggregation_basis = model["aggregation_basis"]
    bridge = model["company_bridge"]
    identity = valuations[0]["identity"]
    scenario_values: dict[str, Any] = {}
    for scenario in SCENARIOS:
        parts: list[dict[str, Any]] = []
        parts_total = 0.0
        for artifact in valuations:
            name = artifact["scope"]["name"]
            selected, selection_label = _selected_value(artifact, selections[name], scenario)
            owned_parameter = _parameter(parameters, ownership[name], scenario, dimension="ratio", time_basis="point_in_time")
            _require(owned_parameter.get("period") == identity["as_of_date"], f"ownership must be measured at value date: {name}/{scenario}")
            owned = finite_number(owned_parameter["value"], f"{owned_parameter['parameter_id']}.value")
            _require(0 <= owned <= 1, f"ownership outside 0..1: {name}/{scenario}")
            owned_value = selected * owned
            parts_total += owned_value
            parts.append({
                "segment": name, "selection": selection_label,
                "selected_value_basis": aggregation_basis,
                "selected_value_current": selected, "ownership": owned,
                "owned_value_current": owned_value,
                "valuation_artifact_id": artifact["artifact_id"],
            })
        adjustment_detail: list[dict[str, Any]] = []
        adjustment_total = 0.0
        for item in bridge["adjustments"]:
            parameter = _parameter(
                parameters, item["parameter_id_template"], scenario,
                dimension="monetary_balance", time_basis="point_in_time",
            )
            _require(parameter.get("period") == identity["as_of_date"], f"company bridge adjustment must be measured at value date: {item['name']}")
            value = finite_number(parameter["value"], f"{parameter['parameter_id']}.value")
            signed = item["sign"] * value
            adjustment_total += signed
            adjustment_detail.append({
                "name": item["name"], "parameter_id": parameter["parameter_id"],
                "value_date": identity["as_of_date"], "value": value,
                "sign": item["sign"], "signed_value": signed,
            })
        equity_value = parts_total + adjustment_total
        scenario_values[scenario] = {
            "aggregation_basis": aggregation_basis, "value_date": identity["as_of_date"],
            "parts": parts, "parts_total_current": parts_total,
            "company_bridge": {
                "stage": bridge["stage"], "completeness_status": bridge["completeness_status"],
                "adjustments": adjustment_detail, "adjustment_total": adjustment_total,
            },
            "sotp_equity_value_current": equity_value,
            "security_value": compute_security_value(model.get("security_bridge"), parameters, scenario, identity, equity_value),
        }
    return scenario_values


def validate_sotp_artifact(artifact: dict[str, Any]) -> None:
    """Recompute SOTP from frozen segment valuation artifacts."""
    validate_artifact(artifact)
    _require(artifact["module"] == "sotp", "expected SOTP artifact")
    if artifact["artifact_schema_version"] != ARTIFACT_SCHEMA_VERSION:
        return
    data = artifact["data"]
    _require(data.get("sotp_model_schema_version") == SOTP_MODEL_SCHEMA_VERSION, "invalid SOTP model schema")
    valuations = data.get("valuation_artifact_snapshots")
    _require(isinstance(valuations, list) and valuations, "SOTP artifact must freeze valuation artifacts")
    model = {
        "sotp_model_schema_version": data["sotp_model_schema_version"],
        "aggregation_basis": data["aggregation_basis"],
        "segment_selections": data["segment_selections"],
        "ownership_parameter_templates": data["ownership_parameter_templates"],
        "company_bridge": data["company_bridge_contract"],
        "security_bridge": data.get("security_bridge"),
        "parameters": artifact["parameters"],
    }
    _validate_inputs(valuations, model)
    _require(artifact["upstream_artifacts"] == [artifact_reference(item) for item in valuations], "SOTP upstream snapshots mismatch")
    expected = _calculate_sotp(valuations, model)
    _require(data.get("scenario_sotp") == expected, "SOTP semantic recomputation mismatch")


def run_sotp(valuations: list[dict[str, Any]], model: dict[str, Any]) -> dict[str, Any]:
    identity, revenue_ref, _ = _validate_inputs(valuations, model)
    scenario_values = _calculate_sotp(valuations, model)
    data = {
        "sotp_model_schema_version": SOTP_MODEL_SCHEMA_VERSION,
        "aggregation_basis": model["aggregation_basis"],
        "segment_selections": model["segment_selections"],
        "ownership_parameter_templates": model["ownership_parameter_templates"],
        "company_bridge_contract": model["company_bridge"],
        "security_bridge": model.get("security_bridge"),
        "valuation_artifact_snapshots": valuations,
        "management_target_coverage_status": revenue_ref["management_target_coverage_status"],
        "management_target_summary": revenue_ref["management_target_summary"],
        "scenario_sotp": scenario_values,
    }
    artifact = create_artifact(
        "sotp", identity, {"type": "company", "name": identity["company_name"]}, data,
        scenario_set=list(SCENARIOS), scenario_manifest=valuations[0]["scenario_manifest"],
        revenue_forecast_ref=revenue_ref,
        upstream_artifacts=valuations, sources=model.get("sources", []),
        parameters=model.get("parameters", []), evidence_claims=model.get("evidence_claims", []),
        limitations=model.get("limitations", []),
    )
    validate_sotp_artifact(artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate segment valuations with an explicit EV/equity bridge")
    parser.add_argument("model", nargs="?")
    parser.add_argument("valuations", nargs="*")
    parser.add_argument("--output")
    parser.add_argument("--validate-artifact")
    args = parser.parse_args()
    try:
        if args.validate_artifact:
            validate_sotp_artifact(read_json(args.validate_artifact))
            print("SOTP artifact valid")
            return 0
        _require(bool(args.model and args.valuations and args.output), "model, valuations, and --output are required")
        result = run_sotp([read_json(path) for path in args.valuations], read_json(args.model))
        write_new_json(args.output, result)
        return 0
    except (InvestmentArtifactError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
