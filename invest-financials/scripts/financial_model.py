"""Typed, deterministic profit and cash-flow models downstream of revenue-forecast."""

from __future__ import annotations

import argparse
import json
import string
import sys
from pathlib import Path
from typing import Any


CORE_SCRIPTS = Path(__file__).resolve().parents[2] / "invest-core" / "scripts"
if str(CORE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CORE_SCRIPTS))

from invest_contracts import (  # noqa: E402
    ARTIFACT_SCHEMA_VERSION,
    MONETARY_DIMENSIONS,
    InvestmentArtifactError,
    SCENARIOS,
    adapt_revenue,
    canonical_sha256,
    create_artifact,
    evaluate_formula,
    finite_number,
    parameter_by_id,
    read_json,
    validate_artifact,
    write_new_json,
)


FINANCIAL_MODEL_SCHEMA_VERSION = "2.0"
MODEL_FAMILY_ROLES = {
    "operating_company": {
        "gross_profit", "operating_expense", "operating_profit", "ebitda",
        "net_income", "nopat", "working_capital_change", "capex", "free_cash_flow",
    },
    "bank": {
        "net_interest_income", "fee_income", "pre_provision_profit", "credit_cost",
        "provision_expense", "net_income", "regulatory_capital_generation",
    },
    "insurer": {
        "premium_revenue", "underwriting_result", "investment_income", "net_income",
        "distributable_cash_flow",
    },
    "reit": {"net_operating_income", "ebitda", "funds_from_operations", "adjusted_funds_from_operations"},
    "pre_revenue": {"research_expense", "operating_expense", "cash_burn", "ending_cash"},
    "custom": set(),
}
DIMENSION_RULES = {
    "same_as_input", "monetary_times_rate", "monetary_sum",
    "monetary_to_ratio", "rate_formula", "custom",
}
RATE_DIMENSIONS = {"ratio", "tax_rate", "discount_rate", "currency_rate"}
CASH_FLOW_BASES = {"fcff", "fcfe", "dividend", "distributable", "operating", "generic"}


def _require(condition: object, message: str) -> None:
    if not condition:
        raise InvestmentArtifactError(message)


def _identity(adapter: dict[str, Any]) -> dict[str, Any]:
    return {
        key: adapter[key]
        for key in ("company_name", "as_of_date", "currency", "unit", "fiscal_year_end", "base_year", "forecast_years")
    }


def _parameter_index(parameters: Any) -> dict[str, dict[str, Any]]:
    _require(isinstance(parameters, list), "parameters must be a list")
    index: dict[str, dict[str, Any]] = {}
    for position, parameter in enumerate(parameters):
        _require(isinstance(parameter, dict), f"parameters[{position}] must be an object")
        parameter_id = parameter.get("parameter_id")
        _require(isinstance(parameter_id, str) and parameter_id.strip(), f"parameters[{position}].parameter_id is required")
        _require(parameter_id not in index, f"duplicate parameter_id: {parameter_id}")
        index[parameter_id] = parameter
    return index


def _render_parameter_id(template: str, scenario: str, year: int) -> str:
    _require(isinstance(template, str) and template.strip(), "parameter reference template is required")
    try:
        fields = {field_name for _, field_name, _, _ in string.Formatter().parse(template) if field_name is not None}
    except ValueError as exc:
        raise InvestmentArtifactError(f"invalid parameter template: {template}") from exc
    _require(fields <= {"scenario", "year"}, f"unsupported parameter template placeholder: {template}")
    try:
        return template.format(scenario=scenario, year=year)
    except (KeyError, ValueError) as exc:
        raise InvestmentArtifactError(f"invalid parameter template: {template}") from exc


def _validate_dimension_rule(line: dict[str, Any]) -> None:
    line_id = line["line_id"]
    output = line["output_dimension"]
    inputs = line["input_dimensions"]
    rule = line["dimension_rule"]
    _require(rule in DIMENSION_RULES, f"unsupported dimension_rule: {line_id}")
    if rule == "same_as_input":
        _require(len(inputs) == 1 and inputs[0] == output, f"same_as_input dimension mismatch: {line_id}")
    elif rule == "monetary_times_rate":
        _require(len(inputs) == 2 and sum(item in MONETARY_DIMENSIONS for item in inputs) == 1 and sum(item in RATE_DIMENSIONS for item in inputs) == 1, f"monetary_times_rate inputs invalid: {line_id}")
        _require(output in MONETARY_DIMENSIONS, f"monetary_times_rate output must be monetary: {line_id}")
    elif rule == "monetary_sum":
        _require(len(inputs) >= 1 and all(item in MONETARY_DIMENSIONS for item in inputs), f"monetary_sum inputs invalid: {line_id}")
        _require(output in MONETARY_DIMENSIONS, f"monetary_sum output must be monetary: {line_id}")
    elif rule == "monetary_to_ratio":
        _require(len(inputs) == 2 and all(item in MONETARY_DIMENSIONS for item in inputs) and output == "ratio", f"monetary_to_ratio dimensions invalid: {line_id}")
    elif rule == "rate_formula":
        _require(all(item in RATE_DIMENSIONS for item in inputs) and output in RATE_DIMENSIONS, f"rate_formula dimensions invalid: {line_id}")
    else:
        _require(isinstance(line.get("dimension_rationale"), str) and line["dimension_rationale"].strip(), f"custom dimension rule requires rationale: {line_id}")


def _validate_input_reference(ref: str, dimension: str, line_id: str, known_dimensions: dict[str, str]) -> None:
    if ref == "revenue":
        _require(dimension == "revenue", f"revenue input dimension mismatch: {line_id}")
        return
    if ref.startswith("line:"):
        upstream = ref.split(":", 1)[1]
        _require(upstream in known_dimensions, f"financial line forward or unknown reference: {upstream}")
        _require(dimension == known_dimensions[upstream], f"line input dimension mismatch: {line_id}/{upstream}")
        return
    if ref.startswith("parameter:"):
        _require(bool(ref.split(":", 1)[1]), f"empty parameter reference: {line_id}")
        return
    raise InvestmentArtifactError(f"unsupported financial input reference: {ref}")


def _validate_line_contract(
    line: Any, position: int, family: str, line_ids: list[str], line_dimensions: dict[str, str],
) -> tuple[str, str]:
    _require(isinstance(line, dict), f"lines[{position}] must be an object")
    assert isinstance(line, dict)
    line_id = line.get("line_id")
    _require(isinstance(line_id, str) and line_id.strip(), f"lines[{position}].line_id is required")
    assert isinstance(line_id, str)
    _require(line_id != "revenue" and line_id not in line_ids, f"duplicate or reserved financial line: {line_id}")
    _require(isinstance(line.get("formula"), str) and line["formula"].strip(), f"formula is required: {line_id}")
    refs = line.get("input_refs")
    dimensions = line.get("input_dimensions")
    _require(isinstance(refs, list) and refs and all(isinstance(ref, str) and ref for ref in refs), f"input_refs are required: {line_id}")
    assert isinstance(refs, list)
    _require(isinstance(dimensions, list) and len(dimensions) == len(refs), f"input_dimensions must align with input_refs: {line_id}")
    assert isinstance(dimensions, list)
    output_dimension = line.get("output_dimension")
    _require(isinstance(output_dimension, str) and output_dimension, f"output_dimension is required: {line_id}")
    assert isinstance(output_dimension, str)
    _require(line.get("time_basis") in {"annual", "point_in_time"}, f"invalid time_basis: {line_id}")
    role = line.get("metric_role")
    _require(isinstance(role, str) and role.strip(), f"metric_role is required: {line_id}")
    assert isinstance(role, str)
    if family != "custom":
        _require(role in MODEL_FAMILY_ROLES[family], f"metric_role is not registered for {family}: {role}")
    if output_dimension == "cash_flow":
        _require(line.get("cash_flow_basis") in CASH_FLOW_BASES, f"cash_flow_basis is required: {line_id}")
    else:
        _require(line.get("cash_flow_basis") in (None, ""), f"cash_flow_basis is only valid for cash_flow lines: {line_id}")
    for ref, dimension in zip(refs, dimensions):
        _validate_input_reference(ref, dimension, line_id, line_dimensions)
    _validate_dimension_rule(line)
    return line_id, output_dimension


def _validate_accounting_identities(value: Any) -> list[dict[str, Any]]:
    _require(isinstance(value, list), "accounting_identities must be a list")
    assert isinstance(value, list)
    identity_ids: set[str] = set()
    for position, identity in enumerate(value):
        _require(isinstance(identity, dict), f"accounting_identities[{position}] must be an object")
        assert isinstance(identity, dict)
        identity_id = identity.get("identity_id")
        _require(isinstance(identity_id, str) and identity_id.strip() and identity_id not in identity_ids, "accounting identity IDs must be unique")
        assert isinstance(identity_id, str)
        identity_ids.add(identity_id)
        _require(isinstance(identity.get("formula"), str) and identity["formula"].strip(), f"identity formula is required: {identity_id}")
        _require(isinstance(identity.get("input_refs"), list) and identity["input_refs"], f"identity inputs are required: {identity_id}")
        _require(isinstance(identity.get("expected_ref"), str) and identity["expected_ref"], f"identity expected_ref is required: {identity_id}")
        tolerance = finite_number(identity.get("tolerance", 1e-9), f"{identity_id}.tolerance")
        _require(tolerance >= 0, f"identity tolerance must be non-negative: {identity_id}")
    return value


def _validate_model_contract(model: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    _require(model.get("financial_model_schema_version") == FINANCIAL_MODEL_SCHEMA_VERSION, "financial_model_schema_version must be 2.0")
    family = model.get("model_family")
    _require(family in MODEL_FAMILY_ROLES, f"unsupported model_family: {family}")
    assert isinstance(family, str)
    if family == "custom":
        _require(isinstance(model.get("model_family_rationale"), str) and model["model_family_rationale"].strip(), "custom model family requires rationale")
    lines = model.get("lines")
    _require(isinstance(lines, list) and lines, "lines must be a non-empty list")
    assert isinstance(lines, list)
    line_ids: list[str] = []
    line_dimensions: dict[str, str] = {"revenue": "revenue"}
    for position, line in enumerate(lines):
        line_id, output_dimension = _validate_line_contract(line, position, family, line_ids, line_dimensions)
        line_ids.append(line_id)
        line_dimensions[line_id] = output_dimension
    required_outputs = model.get("required_outputs")
    _require(isinstance(required_outputs, list) and required_outputs and len(required_outputs) == len(set(required_outputs)), "required_outputs must be a non-empty unique list")
    assert isinstance(required_outputs, list)
    _require(set(required_outputs) <= set(line_ids), "required_outputs contain an unknown line")
    identities = _validate_accounting_identities(model.get("accounting_identities", []))
    return lines, required_outputs, identities


def _resolve_input(
    ref: str,
    declared_dimension: str,
    scenario: str,
    year: int,
    revenue: float,
    lines: dict[str, float],
    line_dimensions: dict[str, str],
    parameters: list[dict[str, Any]],
) -> float:
    if ref == "revenue":
        _require(declared_dimension == "revenue", "revenue input dimension mismatch")
        return revenue
    if ref.startswith("line:"):
        line_id = ref.split(":", 1)[1]
        _require(line_id in lines, f"financial line forward or unknown reference: {line_id}")
        _require(line_dimensions[line_id] == declared_dimension, f"financial line dimension mismatch: {line_id}")
        return lines[line_id]
    if ref.startswith("parameter:"):
        parameter_id = _render_parameter_id(ref.split(":", 1)[1], scenario, year)
        _require(any(item.get("parameter_id") == parameter_id for item in parameters), f"missing financial parameter: {parameter_id}")
        parameter = parameter_by_id(
            parameters, parameter_id,
            expected_dimensions={declared_dimension}, expected_time_bases={"annual"}, scenario=scenario,
        )
        _require(parameter.get("period") == f"FY{year}", f"financial line parameter period mismatch: {parameter_id}")
        return finite_number(parameter["value"], f"{parameter_id}.value")
    raise InvestmentArtifactError(f"unsupported financial input reference: {ref}")


def _calculate_paths(
    adapter: dict[str, Any],
    lines: list[dict[str, Any]],
    parameters: list[dict[str, Any]],
    identities: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, dict[str, float]]], dict[str, dict[str, dict[str, float]]]]:
    line_dimensions = {line["line_id"]: line["output_dimension"] for line in lines}
    annual: dict[str, dict[str, dict[str, float]]] = {}
    identity_checks: dict[str, dict[str, dict[str, float]]] = {}
    for scenario in SCENARIOS:
        annual[scenario] = {}
        identity_checks[scenario] = {}
        for year in adapter["forecast_years"]:
            revenue = finite_number(adapter["annual_revenue"][scenario][str(year)], f"revenue/{scenario}/FY{year}")
            calculated: dict[str, float] = {"revenue": revenue}
            for line in lines:
                inputs = [
                    _resolve_input(ref, dimension, scenario, year, revenue, calculated, line_dimensions, parameters)
                    for ref, dimension in zip(line["input_refs"], line["input_dimensions"])
                ]
                calculated[line["line_id"]] = evaluate_formula(line["formula"], inputs)
            annual[scenario][str(year)] = calculated
            checks: dict[str, float] = {}
            for identity in identities:
                inputs = [
                    _resolve_input(ref, line_dimensions.get(ref.split(":", 1)[1], "revenue") if ref.startswith("line:") else "revenue", scenario, year, revenue, calculated, line_dimensions, parameters)
                    for ref in identity["input_refs"]
                ]
                expected_ref = identity["expected_ref"]
                expected_dimension = line_dimensions.get(expected_ref.split(":", 1)[1], "revenue") if expected_ref.startswith("line:") else "revenue"
                expected = _resolve_input(expected_ref, expected_dimension, scenario, year, revenue, calculated, line_dimensions, parameters)
                residual = evaluate_formula(identity["formula"], inputs) - expected
                tolerance = finite_number(identity.get("tolerance", 1e-9), f"{identity['identity_id']}.tolerance")
                _require(abs(residual) <= tolerance, f"accounting identity mismatch: {identity['identity_id']}/{scenario}/FY{year}")
                checks[identity["identity_id"]] = residual
            identity_checks[scenario][str(year)] = checks
    return annual, identity_checks


def validate_financial_artifact(artifact: dict[str, Any]) -> None:
    """Recompute a schema-2 financial artifact from its frozen adapter and model contract."""
    validate_artifact(artifact)
    _require(artifact["module"] == "financials", "expected financials artifact")
    if artifact["artifact_schema_version"] != ARTIFACT_SCHEMA_VERSION:
        return
    data = artifact["data"]
    _require(data.get("financial_model_schema_version") == FINANCIAL_MODEL_SCHEMA_VERSION, "invalid financial model schema")
    adapter = data.get("revenue_adapter")
    _require(isinstance(adapter, dict), "financial artifact must freeze revenue_adapter")
    provided_adapter_hash = adapter.get("adapter_sha256")
    _require(provided_adapter_hash == canonical_sha256({key: value for key, value in adapter.items() if key != "adapter_sha256"}), "revenue adapter hash mismatch")
    _require(data.get("revenue_adapter_sha256") == provided_adapter_hash, "financial revenue adapter reference mismatch")
    model = {
        "financial_model_schema_version": data["financial_model_schema_version"],
        "model_family": data["model_family"],
        "model_family_rationale": data.get("model_family_rationale"),
        "lines": data["line_definitions"],
        "required_outputs": data["required_outputs"],
        "accounting_identities": data.get("accounting_identities", []),
    }
    lines, required_outputs, identities = _validate_model_contract(model)
    _require(required_outputs == data["required_outputs"], "financial required_outputs mismatch")
    expected_annual, expected_checks = _calculate_paths(adapter, lines, artifact["parameters"], identities)
    _require(expected_annual == data.get("annual_financials"), "financial path semantic recomputation mismatch")
    _require(expected_checks == data.get("identity_checks"), "financial identity check mismatch")
    expected_catalog = {
        "revenue": {
            "dimension": "revenue", "time_basis": "annual",
            "metric_role": "revenue", "cash_flow_basis": None,
        },
        **{
        line["line_id"]: {
            "dimension": line["output_dimension"],
            "time_basis": line["time_basis"],
            "metric_role": line["metric_role"],
            "cash_flow_basis": line.get("cash_flow_basis"),
        }
        for line in lines
        },
    }
    _require(data.get("metric_catalog") == expected_catalog, "financial metric catalog mismatch")


def run_financial_model(forecast: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    scope = model.get("scope", {"type": "company", "name": forecast.get("company_name")})
    _require(isinstance(scope, dict) and scope.get("type") in {"company", "segment"}, "invalid financial scope")
    adapter = adapt_revenue(forecast, scope["type"], scope.get("name") if scope["type"] == "segment" else None)
    lines, required_outputs, identities = _validate_model_contract(model)
    parameters = model.get("parameters", [])
    _parameter_index(parameters)
    annual, identity_checks = _calculate_paths(adapter, lines, parameters, identities)
    metric_catalog = {
        "revenue": {
            "dimension": "revenue", "time_basis": "annual",
            "metric_role": "revenue", "cash_flow_basis": None,
        },
        **{
        line["line_id"]: {
            "dimension": line["output_dimension"],
            "time_basis": line["time_basis"],
            "metric_role": line["metric_role"],
            "cash_flow_basis": line.get("cash_flow_basis"),
        }
        for line in lines
        },
    }
    data = {
        "financial_model_schema_version": FINANCIAL_MODEL_SCHEMA_VERSION,
        "model_family": model["model_family"],
        "model_family_rationale": model.get("model_family_rationale"),
        "revenue_adapter": adapter,
        "revenue_adapter_sha256": adapter["adapter_sha256"],
        "management_target_coverage_status": adapter["revenue_forecast_ref"]["management_target_coverage_status"],
        "management_target_summary": adapter["revenue_forecast_ref"]["management_target_summary"],
        "line_definitions": lines,
        "metric_catalog": metric_catalog,
        "required_outputs": required_outputs,
        "accounting_identities": identities,
        "identity_checks": identity_checks,
        "annual_financials": annual,
    }
    artifact = create_artifact(
        "financials", _identity(adapter), adapter["scope"], data,
        scenario_set=list(SCENARIOS), scenario_manifest=model.get("scenario_manifest"),
        revenue_forecast_ref=adapter["revenue_forecast_ref"],
        sources=model.get("sources", []), parameters=parameters,
        evidence_claims=model.get("evidence_claims", []), limitations=model.get("limitations", []),
    )
    validate_financial_artifact(artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description="Build typed profit and cash-flow paths from a validated revenue forecast")
    parser.add_argument("forecast", nargs="?")
    parser.add_argument("model", nargs="?")
    parser.add_argument("--output")
    parser.add_argument("--validate-artifact")
    args = parser.parse_args()
    try:
        if args.validate_artifact:
            validate_financial_artifact(read_json(args.validate_artifact))
            print("financial artifact valid")
            return 0
        _require(bool(args.forecast and args.model and args.output), "forecast, model, and --output are required")
        artifact = run_financial_model(read_json(args.forecast), read_json(args.model))
        write_new_json(args.output, artifact)
        return 0
    except (InvestmentArtifactError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
