"""Deterministic valuation methods over validated financial artifacts."""

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


def _parameters(model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    values = model.get("parameters", [])
    _require(isinstance(values, list), "parameters must be a list")
    index: dict[str, dict[str, Any]] = {}
    for parameter in values:
        _require(isinstance(parameter, dict), "valuation parameter must be an object")
        parameter_id = parameter.get("parameter_id")
        _require(isinstance(parameter_id, str) and parameter_id.strip(), "valuation parameter_id is required")
        _require(parameter_id not in index, f"duplicate valuation parameter: {parameter_id}")
        index[parameter_id] = parameter
    return index


def _parameter_value(index: dict[str, dict[str, Any]], template: str, scenario: str, expected_dimension: str | None = None) -> float:
    parameter_id = template.format(scenario=scenario)
    _require(parameter_id in index, f"missing valuation parameter: {parameter_id}")
    parameter = index[parameter_id]
    _require(parameter.get("scenario", "shared") in {"shared", scenario}, f"valuation parameter scenario mismatch: {parameter_id}")
    if expected_dimension:
        _require(parameter.get("dimension") == expected_dimension, f"valuation parameter dimension mismatch: {parameter_id}")
    value = parameter.get("value")
    _require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)), f"invalid valuation parameter: {parameter_id}")
    return float(value)


def _adjustments(model: dict[str, Any], index: dict[str, dict[str, Any]], scenario: str) -> tuple[float, list[dict[str, Any]]]:
    total = 0.0
    detail = []
    adjustments = model.get("equity_adjustments", [])
    _require(isinstance(adjustments, list), "equity_adjustments must be a list")
    names = set()
    for item in adjustments:
        _require(isinstance(item, dict), "equity adjustment must be an object")
        name = item.get("name")
        _require(isinstance(name, str) and name.strip() and name not in names, "equity adjustment name must be unique")
        names.add(name)
        sign = item.get("sign")
        _require(sign in (-1, 1), f"equity adjustment sign must be -1 or 1: {name}")
        value = _parameter_value(index, item.get("parameter_id_template", ""), scenario)
        signed = sign * value
        total += signed
        detail.append({"name": name, "value": value, "sign": sign, "signed_value": signed})
    return total, detail


def _metric_path(financials: dict[str, Any], scenario: str, metric: str) -> list[float]:
    years = financials["identity"]["forecast_years"]
    annual = financials["data"]["annual_financials"][scenario]
    values = []
    for year in years:
        row = annual[str(year)]
        _require(metric in row, f"upstream financial metric missing: {metric}/{scenario}/FY{year}")
        value = row[metric]
        _require(isinstance(value, (int, float)) and math.isfinite(float(value)), f"invalid upstream metric: {metric}/{scenario}/FY{year}")
        values.append(float(value))
    return values


def _dcf(method: dict[str, Any], financials: dict[str, Any], parameters: dict[str, dict[str, Any]], scenario: str) -> dict[str, Any]:
    metric = method.get("metric")
    _require(isinstance(metric, str) and metric.strip(), "DCF metric is required")
    cash_flows = _metric_path(financials, scenario, metric)
    discount_rate = _parameter_value(parameters, method.get("discount_rate_parameter_template", ""), scenario, "discount_rate")
    terminal_growth = _parameter_value(parameters, method.get("terminal_growth_parameter_template", ""), scenario, "ratio")
    _require(discount_rate > terminal_growth, f"DCF discount rate must exceed terminal growth: {scenario}")
    _require(discount_rate > -1 and terminal_growth > -1, f"invalid DCF rates: {scenario}")
    explicit_value = sum(value / ((1 + discount_rate) ** index) for index, value in enumerate(cash_flows, start=1))
    terminal_value = cash_flows[-1] * (1 + terminal_growth) / (discount_rate - terminal_growth)
    discounted_terminal = terminal_value / ((1 + discount_rate) ** len(cash_flows))
    return {
        "method_type": "dcf",
        "metric": metric,
        "value_basis": method.get("value_basis"),
        "discount_rate": discount_rate,
        "terminal_growth": terminal_growth,
        "explicit_period_value": explicit_value,
        "terminal_value_at_horizon": terminal_value,
        "discounted_terminal_value": discounted_terminal,
        "raw_value": explicit_value + discounted_terminal,
    }


def _multiple(method: dict[str, Any], financials: dict[str, Any], parameters: dict[str, dict[str, Any]], scenario: str) -> dict[str, Any]:
    metric = method.get("metric")
    _require(isinstance(metric, str) and metric.strip(), "multiple metric is required")
    terminal_metric = _metric_path(financials, scenario, metric)[-1]
    multiple = _parameter_value(parameters, method.get("multiple_parameter_template", ""), scenario, "multiple")
    _require(multiple >= 0, f"valuation multiple cannot be negative: {scenario}")
    return {
        "method_type": "multiple",
        "metric": metric,
        "value_basis": method.get("value_basis"),
        "terminal_metric": terminal_metric,
        "multiple": multiple,
        "raw_value": terminal_metric * multiple,
    }


def _asset(method: dict[str, Any], parameters: dict[str, dict[str, Any]], scenario: str) -> dict[str, Any]:
    value = _parameter_value(parameters, method.get("value_parameter_template", ""), scenario)
    return {
        "method_type": "asset",
        "metric": method.get("metric", "adjusted_net_assets"),
        "value_basis": method.get("value_basis"),
        "raw_value": value,
    }


def run_valuation(financials: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    validate_artifact(financials)
    _require(financials["module"] == "financials", "valuation requires a financials artifact")
    _require(financials["scenario_set"] == list(SCENARIOS), "financial scenario set mismatch")
    for forbidden in ("revenue_override", "profit_override", "cash_flow_override", "scenario_probabilities"):
        _require(forbidden not in model, f"valuation input contains prohibited override: {forbidden}")
    methods = model.get("methods")
    _require(isinstance(methods, list) and methods, "valuation methods must be a non-empty list")
    method_ids = []
    for method in methods:
        _require(isinstance(method, dict), "valuation method must be an object")
        method_id = method.get("method_id")
        _require(isinstance(method_id, str) and method_id.strip() and method_id not in method_ids, "valuation method_id must be unique")
        method_ids.append(method_id)
        _require(method.get("type") in {"dcf", "multiple", "asset"}, f"unsupported valuation method: {method_id}")
        _require(method.get("value_basis") in {"enterprise", "equity"}, f"value_basis required: {method_id}")
    parameters = _parameters(model)
    scenario_values: dict[str, Any] = {}
    for scenario in SCENARIOS:
        adjustment_total, adjustment_detail = _adjustments(model, parameters, scenario)
        method_values: dict[str, Any] = {}
        for method in methods:
            if method["type"] == "dcf":
                result = _dcf(method, financials, parameters, scenario)
            elif method["type"] == "multiple":
                result = _multiple(method, financials, parameters, scenario)
            else:
                result = _asset(method, parameters, scenario)
            equity_value = result["raw_value"] + adjustment_total if result["value_basis"] == "enterprise" else result["raw_value"]
            result["equity_adjustments"] = adjustment_detail if result["value_basis"] == "enterprise" else []
            result["equity_value"] = equity_value
            method_values[method["method_id"]] = result
        scenario_values[scenario] = {"methods": method_values}
    weights = model.get("method_weights")
    if weights is not None:
        _require(isinstance(weights, dict) and set(weights) == set(method_ids), "method_weights must cover every method exactly")
        numeric_weights = {key: float(value) for key, value in weights.items()}
        _require(all(value >= 0 for value in numeric_weights.values()), "method weights cannot be negative")
        _require(math.isclose(sum(numeric_weights.values()), 1.0, rel_tol=0, abs_tol=1e-9), "method weights must sum to one")
        for scenario in SCENARIOS:
            scenario_values[scenario]["weighted_equity_value"] = sum(
                numeric_weights[method_id] * scenario_values[scenario]["methods"][method_id]["equity_value"]
                for method_id in method_ids
            )
    data = {
        "methods": methods,
        "method_weights": weights,
        "management_target_coverage_status": financials["revenue_forecast_ref"]["management_target_coverage_status"],
        "management_target_summary": financials["revenue_forecast_ref"]["management_target_summary"],
        "scenario_valuations": scenario_values,
    }
    return create_artifact(
        "valuation", financials["identity"], financials["scope"], data,
        scenario_set=list(SCENARIOS),
        revenue_forecast_ref=financials["revenue_forecast_ref"],
        upstream_artifacts=[financials],
        sources=model.get("sources", []),
        parameters=model.get("parameters", []),
        evidence_claims=model.get("evidence_claims", []),
        limitations=model.get("limitations", []),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Value a validated financial artifact")
    parser.add_argument("financials")
    parser.add_argument("model")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = run_valuation(read_json(args.financials), read_json(args.model))
        write_new_json(args.output, result)
        return 0
    except (InvestmentArtifactError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
