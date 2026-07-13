"""Deterministic profit and cash-flow line model downstream of revenue-forecast."""

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
    adapt_revenue,
    create_artifact,
    evaluate_formula,
    read_json,
    write_new_json,
)


def _require(condition: bool, message: str) -> None:
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


def _resolve_input(
    ref: str,
    scenario: str,
    year: int,
    revenue: float,
    lines: dict[str, float],
    parameters: dict[str, dict[str, Any]],
) -> float:
    if ref == "revenue":
        return revenue
    if ref.startswith("line:"):
        line_id = ref.split(":", 1)[1]
        _require(line_id in lines, f"financial line forward or unknown reference: {line_id}")
        return lines[line_id]
    if ref.startswith("parameter:"):
        template = ref.split(":", 1)[1]
        parameter_id = template.format(scenario=scenario, year=year)
        _require(parameter_id in parameters, f"missing financial parameter: {parameter_id}")
        parameter = parameters[parameter_id]
        _require(parameter.get("scenario", "shared") in {"shared", scenario}, f"parameter scenario mismatch: {parameter_id}")
        _require(parameter.get("time_basis") == "annual", f"financial line parameter must be annual: {parameter_id}")
        _require(parameter.get("period") == f"FY{year}", f"financial line parameter period mismatch: {parameter_id}")
        value = parameter.get("value")
        _require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)), f"invalid parameter value: {parameter_id}")
        return float(value)
    raise InvestmentArtifactError(f"unsupported financial input reference: {ref}")


def run_financial_model(forecast: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    scope = model.get("scope", {"type": "company", "name": forecast.get("company_name")})
    _require(isinstance(scope, dict) and scope.get("type") in {"company", "segment"}, "invalid financial scope")
    adapter = adapt_revenue(forecast, scope["type"], scope.get("name") if scope["type"] == "segment" else None)
    model_family = model.get("model_family")
    _require(isinstance(model_family, str) and model_family.strip(), "model_family is required")
    line_definitions = model.get("lines")
    _require(isinstance(line_definitions, list) and line_definitions, "lines must be a non-empty list")
    line_ids: list[str] = []
    for position, line in enumerate(line_definitions):
        _require(isinstance(line, dict), f"lines[{position}] must be an object")
        line_id = line.get("line_id")
        _require(isinstance(line_id, str) and line_id.strip(), f"lines[{position}].line_id is required")
        _require(line_id != "revenue" and line_id not in line_ids, f"duplicate or reserved financial line: {line_id}")
        _require(isinstance(line.get("formula"), str) and line["formula"].strip(), f"formula is required: {line_id}")
        _require(isinstance(line.get("input_refs"), list) and line["input_refs"], f"input_refs are required: {line_id}")
        line_ids.append(line_id)
    required_outputs = model.get("required_outputs", [])
    _require(isinstance(required_outputs, list) and required_outputs, "required_outputs must be a non-empty list")
    _require(set(required_outputs) <= set(line_ids), "required_outputs contain an unknown line")
    parameters = model.get("parameters", [])
    parameter_index = _parameter_index(parameters)
    years = adapter["forecast_years"]
    annual: dict[str, dict[str, dict[str, float]]] = {}
    for scenario in SCENARIOS:
        annual[scenario] = {}
        for year in years:
            revenue = float(adapter["annual_revenue"][scenario][str(year)])
            calculated: dict[str, float] = {"revenue": revenue}
            for line in line_definitions:
                inputs = [
                    _resolve_input(ref, scenario, year, revenue, calculated, parameter_index)
                    for ref in line["input_refs"]
                ]
                value = evaluate_formula(line["formula"], inputs)
                _require(math.isfinite(value), f"non-finite financial line: {line['line_id']}/{scenario}/FY{year}")
                calculated[line["line_id"]] = value
            annual[scenario][str(year)] = calculated
    data = {
        "model_family": model_family,
        "revenue_adapter_sha256": adapter["adapter_sha256"],
        "management_target_coverage_status": adapter["revenue_forecast_ref"]["management_target_coverage_status"],
        "management_target_summary": adapter["revenue_forecast_ref"]["management_target_summary"],
        "line_definitions": line_definitions,
        "required_outputs": required_outputs,
        "annual_financials": annual,
    }
    return create_artifact(
        "financials", _identity(adapter), adapter["scope"], data,
        scenario_set=list(SCENARIOS),
        revenue_forecast_ref=adapter["revenue_forecast_ref"],
        sources=model.get("sources", []),
        parameters=parameters,
        evidence_claims=model.get("evidence_claims", []),
        limitations=model.get("limitations", []),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build profit and cash-flow paths from a validated revenue forecast")
    parser.add_argument("forecast")
    parser.add_argument("model")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        artifact = run_financial_model(read_json(args.forecast), read_json(args.model))
        write_new_json(args.output, artifact)
        return 0
    except (InvestmentArtifactError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
