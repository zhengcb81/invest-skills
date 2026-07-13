"""Deterministic, date-explicit valuation over validated financial artifacts."""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import string
import sys
from pathlib import Path
from typing import Any


SUITE = Path(__file__).resolve().parents[2]
CORE_SCRIPTS = SUITE / "invest-core" / "scripts"
FINANCIAL_SCRIPTS = SUITE / "invest-financials" / "scripts"
for scripts in (CORE_SCRIPTS, FINANCIAL_SCRIPTS):
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))

from financial_model import validate_financial_artifact  # noqa: E402
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
    validate_artifact,
    write_new_json,
)


VALUATION_MODEL_SCHEMA_VERSION = "2.0"
DCF_BASIS_BY_VALUE = {
    "enterprise": {"fcff"},
    "equity": {"fcfe", "dividend", "distributable"},
}
MULTIPLE_KINDS = {
    "pe": {"value_basis": "equity", "dimensions": {"profit"}, "roles": {"net_income"}},
    "ps": {"value_basis": "equity", "dimensions": {"revenue"}, "roles": {"revenue"}},
    "ev_sales": {"value_basis": "enterprise", "dimensions": {"revenue"}, "roles": {"revenue"}},
    "ev_ebitda": {"value_basis": "enterprise", "dimensions": {"profit"}, "roles": {"ebitda"}},
    "p_ffo": {"value_basis": "equity", "dimensions": {"profit", "cash_flow"}, "roles": {"funds_from_operations"}},
    "p_affo": {"value_basis": "equity", "dimensions": {"profit", "cash_flow"}, "roles": {"adjusted_funds_from_operations"}},
}


def _require(condition: object, message: str) -> None:
    if not condition:
        raise InvestmentArtifactError(message)


def _render_parameter_id(template: str, scenario: str, *, year: int | None = None) -> str:
    _require(isinstance(template, str) and template.strip(), "valuation parameter template is required")
    try:
        fields = {field for _, field, _, _ in string.Formatter().parse(template) if field is not None}
    except ValueError as exc:
        raise InvestmentArtifactError(f"invalid valuation parameter template: {template}") from exc
    _require(fields <= {"scenario", "year"}, f"unsupported valuation parameter placeholder: {template}")
    _require("year" not in fields or year is not None, f"valuation parameter template requires year: {template}")
    try:
        return template.format(scenario=scenario, year=year)
    except (KeyError, ValueError) as exc:
        raise InvestmentArtifactError(f"invalid valuation parameter template: {template}") from exc


def _parameter(
    parameters: list[dict[str, Any]],
    template: str,
    scenario: str,
    *,
    dimensions: set[str],
    time_bases: set[str] | None = None,
    year: int | None = None,
) -> dict[str, Any]:
    parameter_id = _render_parameter_id(template, scenario, year=year)
    _require(any(item.get("parameter_id") == parameter_id for item in parameters), f"missing valuation parameter: {parameter_id}")
    return parameter_by_id(
        parameters, parameter_id, expected_dimensions=dimensions,
        expected_time_bases=time_bases, scenario=scenario,
    )


def _metric_catalog(financials: dict[str, Any], metric: str) -> dict[str, Any]:
    catalog = financials["data"].get("metric_catalog")
    _require(isinstance(catalog, dict) and metric in catalog, f"upstream financial metric is not catalogued: {metric}")
    record = catalog[metric]
    _require(isinstance(record, dict), f"invalid upstream metric catalog entry: {metric}")
    return record


def _metric_value(financials: dict[str, Any], scenario: str, metric: str, year: int) -> float:
    _require(year in financials["identity"]["forecast_years"], f"metric_year is outside financial forecast: FY{year}")
    row = financials["data"]["annual_financials"][scenario][str(year)]
    _require(metric in row, f"upstream financial metric missing: {metric}/{scenario}/FY{year}")
    return finite_number(row[metric], f"{metric}/{scenario}/FY{year}")


def _metric_path(financials: dict[str, Any], scenario: str, metric: str) -> list[float]:
    return [_metric_value(financials, scenario, metric, year) for year in financials["identity"]["forecast_years"]]


def _validate_method_contract(method: dict[str, Any], financials: dict[str, Any]) -> None:
    method_id = method["method_id"]
    method_type = method.get("type")
    value_basis = method.get("value_basis")
    _require(method_type in {"dcf", "multiple", "asset"}, f"unsupported valuation method: {method_id}")
    _require(value_basis in {"enterprise", "equity"}, f"value_basis required: {method_id}")
    timing = method.get("valuation_timing")
    _require(timing in {"current", "exit"}, f"valuation_timing must be current or exit: {method_id}")
    assert isinstance(method_type, str) and isinstance(value_basis, str) and isinstance(timing, str)
    if method_type == "dcf":
        _require(timing == "current", f"DCF valuation_timing must be current: {method_id}")
        metric = method.get("metric")
        _require(isinstance(metric, str) and metric.strip(), f"DCF metric is required: {method_id}")
        assert isinstance(metric, str)
        catalog = _metric_catalog(financials, metric)
        _require(catalog.get("dimension") == "cash_flow", f"DCF metric must be a cash_flow line: {method_id}")
        cash_flow_basis = method.get("cash_flow_basis")
        _require(cash_flow_basis == catalog.get("cash_flow_basis"), f"DCF cash_flow_basis does not match upstream metric: {method_id}")
        _require(cash_flow_basis in DCF_BASIS_BY_VALUE[value_basis], f"DCF cash_flow_basis/value_basis mismatch: {method_id}")
        _require(method.get("terminal_model") == "gordon_growth", f"DCF terminal_model must be gordon_growth: {method_id}")
    elif method_type == "multiple":
        metric = method.get("metric")
        _require(isinstance(metric, str) and metric.strip(), f"multiple metric is required: {method_id}")
        assert isinstance(metric, str)
        catalog = _metric_catalog(financials, metric)
        kind = method.get("multiple_kind")
        if kind == "custom":
            _require(isinstance(method.get("multiple_rationale"), str) and method["multiple_rationale"].strip(), f"custom multiple requires rationale: {method_id}")
            _require(method.get("expected_metric_dimension") == catalog.get("dimension"), f"custom multiple metric dimension mismatch: {method_id}")
        else:
            _require(kind in MULTIPLE_KINDS, f"unsupported multiple_kind: {method_id}")
            assert isinstance(kind, str)
            spec = MULTIPLE_KINDS[kind]
            _require(value_basis == spec["value_basis"], f"multiple_kind/value_basis mismatch: {method_id}")
            _require(catalog.get("dimension") in spec["dimensions"], f"multiple metric dimension mismatch: {method_id}")
            _require(catalog.get("metric_role") in spec["roles"], f"multiple metric role mismatch: {method_id}")
        metric_period = method.get("metric_period")
        _require(isinstance(metric_period, str) and re.fullmatch(r"FY\d{4}", metric_period) is not None, f"metric_period must use FYyyyy: {method_id}")
        assert isinstance(metric_period, str)
        year = int(metric_period[2:])
        _require(year in financials["identity"]["forecast_years"], f"metric_period outside forecast: {method_id}")
        if timing == "exit":
            _require(year > financials["identity"]["base_year"], f"exit metric period must follow base year: {method_id}")
            _require(isinstance(method.get("discount_rate_parameter_template"), str), f"exit multiple requires discount rate: {method_id}")
    else:
        _require(timing == "current", f"asset valuation_timing must be current: {method_id}")
        _require(isinstance(method.get("value_parameter_template"), str), f"asset value parameter is required: {method_id}")


def _adjustments(
    model: dict[str, Any], parameters: list[dict[str, Any]], scenario: str, as_of_date: str,
) -> tuple[float, list[dict[str, Any]]]:
    total = 0.0
    detail: list[dict[str, Any]] = []
    adjustments = model.get("equity_adjustments", [])
    _require(isinstance(adjustments, list), "equity_adjustments must be a list")
    names: set[str] = set()
    for item in adjustments:
        _require(isinstance(item, dict), "equity adjustment must be an object")
        name = item.get("name")
        _require(isinstance(name, str) and name.strip() and name not in names, "equity adjustment name must be unique")
        names.add(name)
        sign = item.get("sign")
        _require(isinstance(sign, int) and not isinstance(sign, bool) and sign in (-1, 1), f"equity adjustment sign must be -1 or 1: {name}")
        parameter = _parameter(
            parameters, item.get("parameter_id_template", ""), scenario,
            dimensions={"monetary_balance"}, time_bases={"point_in_time"},
        )
        _require(parameter.get("period") == as_of_date, f"equity adjustment must be measured at value date: {name}")
        value = finite_number(parameter["value"], f"{parameter['parameter_id']}.value")
        signed = sign * value
        total += signed
        detail.append({
            "name": name, "parameter_id": parameter["parameter_id"], "value_date": as_of_date,
            "value": value, "sign": sign, "signed_value": signed,
        })
    return total, detail


def _dcf(
    method: dict[str, Any], financials: dict[str, Any], parameters: list[dict[str, Any]], scenario: str,
) -> dict[str, Any]:
    metric = method["metric"]
    cash_flows = _metric_path(financials, scenario, metric)
    discount = _parameter(parameters, method["discount_rate_parameter_template"], scenario, dimensions={"discount_rate"}, time_bases={"point_in_time"})
    growth = _parameter(parameters, method["terminal_growth_parameter_template"], scenario, dimensions={"ratio"}, time_bases={"point_in_time"})
    discount_rate = finite_number(discount["value"], f"{discount['parameter_id']}.value")
    terminal_growth = finite_number(growth["value"], f"{growth['parameter_id']}.value")
    _require(discount.get("period") == financials["identity"]["as_of_date"], f"DCF discount rate must be measured at value date: {scenario}")
    _require(growth.get("period") == financials["identity"]["as_of_date"], f"DCF terminal growth must be measured at value date: {scenario}")
    _require(discount_rate > terminal_growth, f"DCF discount rate must exceed terminal growth: {scenario}")
    _require(discount_rate > -1 and terminal_growth > -1, f"invalid DCF rates: {scenario}")
    explicit_value = sum(value / ((1 + discount_rate) ** index) for index, value in enumerate(cash_flows, start=1))
    terminal_value = cash_flows[-1] * (1 + terminal_growth) / (discount_rate - terminal_growth)
    discounted_terminal = terminal_value / ((1 + discount_rate) ** len(cash_flows))
    present_value = explicit_value + discounted_terminal
    return {
        "method_type": "dcf", "metric": metric, "cash_flow_basis": method["cash_flow_basis"],
        "value_basis": method["value_basis"], "valuation_timing": "current",
        "value_date": financials["identity"]["as_of_date"],
        "terminal_period": f"FY{financials['identity']['forecast_years'][-1]}",
        "discount_rate": discount_rate, "terminal_growth": terminal_growth,
        "explicit_period_present_value": explicit_value,
        "terminal_value_at_horizon": terminal_value,
        "discounted_terminal_value": discounted_terminal,
        "value_before_adjustments_current": present_value,
    }


def _multiple(
    method: dict[str, Any], financials: dict[str, Any], parameters: list[dict[str, Any]], scenario: str,
) -> dict[str, Any]:
    year = int(method["metric_period"][2:])
    metric_value = _metric_value(financials, scenario, method["metric"], year)
    multiple_parameter = _parameter(
        parameters, method["multiple_parameter_template"], scenario,
        dimensions={"multiple"}, time_bases={"point_in_time"}, year=year,
    )
    multiple = finite_number(multiple_parameter["value"], f"{multiple_parameter['parameter_id']}.value")
    _require(multiple >= 0, f"valuation multiple cannot be negative: {scenario}")
    undiscounted = metric_value * multiple
    discount_rate: float | None = None
    discount_years = 0
    present_value = undiscounted
    if method["valuation_timing"] == "exit":
        discount_parameter = _parameter(
            parameters, method["discount_rate_parameter_template"], scenario,
            dimensions={"discount_rate"}, time_bases={"point_in_time"}, year=year,
        )
        discount_rate = finite_number(discount_parameter["value"], f"{discount_parameter['parameter_id']}.value")
        _require(discount_rate > -1, f"invalid exit multiple discount rate: {scenario}")
        _require(discount_parameter.get("period") == financials["identity"]["as_of_date"], f"exit discount rate must be measured at value date: {scenario}")
        discount_years = year - financials["identity"]["base_year"]
        present_value = undiscounted / ((1 + discount_rate) ** discount_years)
    return {
        "method_type": "multiple", "multiple_kind": method["multiple_kind"],
        "metric": method["metric"], "metric_period": method["metric_period"],
        "metric_value": metric_value, "multiple": multiple, "value_basis": method["value_basis"],
        "valuation_timing": method["valuation_timing"],
        "value_date": financials["identity"]["as_of_date"],
        "undiscounted_value_at_metric_period": undiscounted,
        "discount_rate": discount_rate, "discount_years": discount_years,
        "value_before_adjustments_current": present_value,
    }


def _asset(
    method: dict[str, Any], financials: dict[str, Any], parameters: list[dict[str, Any]], scenario: str,
) -> dict[str, Any]:
    parameter = _parameter(
        parameters, method["value_parameter_template"], scenario,
        dimensions={"asset", "equity", "monetary_balance"}, time_bases={"point_in_time"},
    )
    _require(parameter.get("period") == financials["identity"]["as_of_date"], f"asset value must be measured at value date: {scenario}")
    return {
        "method_type": "asset", "metric": method.get("metric", "adjusted_net_assets"),
        "value_basis": method["value_basis"], "valuation_timing": "current",
        "value_date": financials["identity"]["as_of_date"],
        "value_before_adjustments_current": finite_number(parameter["value"], f"{parameter['parameter_id']}.value"),
    }


def _validated_weights(weights: Any, method_ids: list[str]) -> dict[str, float] | None:
    if weights is None:
        return None
    _require(isinstance(weights, dict) and set(weights) == set(method_ids), "method_weights must cover every method exactly")
    numeric = {key: finite_number(value, f"method_weights.{key}") for key, value in weights.items()}
    _require(all(value >= 0 for value in numeric.values()), "method weights cannot be negative")
    _require(math.isclose(sum(numeric.values()), 1.0, rel_tol=0, abs_tol=1e-9), "method weights must sum to one")
    return numeric


def _evaluate_method(
    method: dict[str, Any], financials: dict[str, Any], parameters: list[dict[str, Any]], scenario: str,
) -> dict[str, Any]:
    if method["type"] == "dcf":
        return _dcf(method, financials, parameters, scenario)
    if method["type"] == "multiple":
        return _multiple(method, financials, parameters, scenario)
    return _asset(method, financials, parameters, scenario)


def _calculate_valuations(financials: dict[str, Any], model: dict[str, Any]) -> tuple[dict[str, Any], dict[str, float] | None]:
    methods = model["methods"]
    parameters = model.get("parameters", [])
    weights = _validated_weights(model.get("method_weights"), [method["method_id"] for method in methods])
    scenario_values: dict[str, Any] = {}
    for scenario in SCENARIOS:
        adjustment_total, adjustment_detail = _adjustments(model, parameters, scenario, financials["identity"]["as_of_date"])
        method_values: dict[str, Any] = {}
        for method in methods:
            result = _evaluate_method(method, financials, parameters, scenario)
            before = result["value_before_adjustments_current"]
            equity_value = before + adjustment_total if result["value_basis"] == "enterprise" else before
            result["equity_adjustments_at_value_date"] = adjustment_detail if result["value_basis"] == "enterprise" else []
            result["equity_value_current"] = equity_value
            result["security_value"] = compute_security_value(model.get("security_bridge"), parameters, scenario, financials["identity"], equity_value)
            method_values[method["method_id"]] = result
        scenario_record: dict[str, Any] = {"methods": method_values}
        if weights is not None:
            scenario_record["weighted_equity_value_current"] = sum(weights[method_id] * method_values[method_id]["equity_value_current"] for method_id in weights)
            security_values = [method_values[method_id]["security_value"] for method_id in weights]
            if all(item is not None for item in security_values):
                scenario_record["weighted_per_security_value_current"] = sum(
                    weights[method_id] * method_values[method_id]["security_value"]["per_security_value_current"]
                    for method_id in weights
                )
        scenario_values[scenario] = scenario_record
    return scenario_values, weights


def _parameter_template_for_variable(method: dict[str, Any], variable: str) -> tuple[str, str]:
    mapping = {
        "discount_rate": ("discount_rate_parameter_template", "discount_rate"),
        "terminal_growth": ("terminal_growth_parameter_template", "ratio"),
        "multiple": ("multiple_parameter_template", "multiple"),
        "asset_value": ("value_parameter_template", "asset"),
    }
    _require(variable in mapping, f"unsupported valuation sensitivity variable: {variable}")
    field, dimension = mapping[variable]
    _require(isinstance(method.get(field), str) and method[field], f"method does not expose sensitivity variable: {method['method_id']}/{variable}")
    if variable == "discount_rate":
        _require(method["type"] in {"dcf", "multiple"} and (method["type"] == "dcf" or method["valuation_timing"] == "exit"), f"discount-rate sensitivity is not applicable: {method['method_id']}")
    if variable == "terminal_growth":
        _require(method["type"] == "dcf", f"terminal-growth sensitivity requires DCF: {method['method_id']}")
    if variable == "multiple":
        _require(method["type"] == "multiple", f"multiple sensitivity requires a multiple method: {method['method_id']}")
    if variable == "asset_value":
        _require(method["type"] == "asset", f"asset-value sensitivity requires an asset method: {method['method_id']}")
    return field, dimension


def _calculate_sensitivities(financials: dict[str, Any], model: dict[str, Any]) -> list[dict[str, Any]]:
    parameters = model.get("parameters", [])
    methods = {method["method_id"]: method for method in model["methods"]}
    results: list[dict[str, Any]] = []
    for case in model.get("sensitivity_cases", []):
        method = methods[case["method_id"]]
        scenario = case["scenario"]
        variable = case["variable"]
        template_field, dimension = _parameter_template_for_variable(method, variable)
        target_id = _render_parameter_id(method[template_field], scenario, year=int(method["metric_period"][2:]) if method.get("metric_period") else None)
        adjustment_total, _ = _adjustments(model, parameters, scenario, financials["identity"]["as_of_date"])
        base_method = _evaluate_method(method, financials, parameters, scenario)
        base_equity = base_method["value_before_adjustments_current"] + adjustment_total if base_method["value_basis"] == "enterprise" else base_method["value_before_adjustments_current"]
        rows: list[dict[str, Any]] = []
        for parameter_id in case["value_parameter_ids"]:
            shock = parameter_by_id(
                parameters, parameter_id, expected_dimensions={dimension},
                expected_time_bases={"point_in_time"}, scenario=scenario,
            )
            _require(shock.get("kind") == "scenario_stress", f"sensitivity value must be scenario_stress: {parameter_id}")
            shocked_parameters = copy.deepcopy(parameters)
            target = next((item for item in shocked_parameters if item.get("parameter_id") == target_id), None)
            _require(target is not None, f"sensitivity target parameter is missing: {target_id}")
            assert isinstance(target, dict)
            target["value"] = finite_number(shock["value"], f"{parameter_id}.value")
            shocked = _evaluate_method(method, financials, shocked_parameters, scenario)
            equity_value = shocked["value_before_adjustments_current"] + adjustment_total if shocked["value_basis"] == "enterprise" else shocked["value_before_adjustments_current"]
            rows.append({
                "parameter_id": parameter_id, "test_value": shock["value"],
                "equity_value_current": equity_value,
                "security_value": compute_security_value(model.get("security_bridge"), parameters, scenario, financials["identity"], equity_value),
            })
        results.append({
            "sensitivity_id": case["sensitivity_id"], "method_id": method["method_id"],
            "scenario": scenario, "variable": variable,
            "base_equity_value_current": base_equity, "cases": rows,
        })
    return results


def _calculate_reverse_cases(financials: dict[str, Any], model: dict[str, Any]) -> list[dict[str, Any]]:
    parameters = model.get("parameters", [])
    methods = {method["method_id"]: method for method in model["methods"]}
    results: list[dict[str, Any]] = []
    for case in model.get("reverse_cases", []):
        method = methods[case["method_id"]]
        scenario = case["scenario"]
        target = parameter_by_id(
            parameters, case["target_equity_value_parameter_id"], expected_dimensions={"equity"},
            expected_time_bases={"point_in_time"}, scenario=scenario,
        )
        _require(target.get("period") == financials["identity"]["as_of_date"], f"reverse target must be current: {case['reverse_id']}")
        target_equity = finite_number(target["value"], f"{target['parameter_id']}.value")
        adjustment_total, _ = _adjustments(model, parameters, scenario, financials["identity"]["as_of_date"])
        target_before_adjustments = target_equity - adjustment_total if method["value_basis"] == "enterprise" else target_equity
        solve_for = case["solve_for"]
        if solve_for == "multiple":
            _require(method["type"] == "multiple", f"reverse multiple requires a multiple method: {case['reverse_id']}")
            year = int(method["metric_period"][2:])
            metric_value = _metric_value(financials, scenario, method["metric"], year)
            _require(not math.isclose(metric_value, 0.0), f"cannot reverse-solve multiple on zero metric: {case['reverse_id']}")
            value_at_metric_period = target_before_adjustments
            if method["valuation_timing"] == "exit":
                discount = _parameter(parameters, method["discount_rate_parameter_template"], scenario, dimensions={"discount_rate"}, time_bases={"point_in_time"}, year=year)
                rate = finite_number(discount["value"], f"{discount['parameter_id']}.value")
                value_at_metric_period *= (1 + rate) ** (year - financials["identity"]["base_year"])
            implied = value_at_metric_period / metric_value
        else:
            _require(solve_for == "terminal_growth" and method["type"] == "dcf", f"unsupported reverse solve: {case['reverse_id']}")
            cash_flows = _metric_path(financials, scenario, method["metric"])
            discount = _parameter(parameters, method["discount_rate_parameter_template"], scenario, dimensions={"discount_rate"}, time_bases={"point_in_time"})
            rate = finite_number(discount["value"], f"{discount['parameter_id']}.value")
            explicit = sum(value / ((1 + rate) ** index) for index, value in enumerate(cash_flows, start=1))
            terminal_present = target_before_adjustments - explicit
            _require(terminal_present > 0, f"reverse target is below explicit-period DCF value: {case['reverse_id']}")
            terminal_value = terminal_present * (1 + rate) ** len(cash_flows)
            terminal_cash_flow = cash_flows[-1]
            implied = (terminal_value * rate - terminal_cash_flow) / (terminal_value + terminal_cash_flow)
            _require(-1 < implied < rate, f"implied terminal growth is economically invalid: {case['reverse_id']}")
        results.append({
            "reverse_id": case["reverse_id"], "method_id": method["method_id"],
            "scenario": scenario, "target_equity_value_current": target_equity,
            "solve_for": solve_for, "implied_value": implied,
        })
    return results


def _validate_methods(value: Any, financials: dict[str, Any]) -> tuple[list[dict[str, Any]], set[str]]:
    _require(isinstance(value, list) and value, "valuation methods must be a non-empty list")
    assert isinstance(value, list)
    method_ids: set[str] = set()
    for method in value:
        _require(isinstance(method, dict), "valuation method must be an object")
        assert isinstance(method, dict)
        method_id = method.get("method_id")
        _require(isinstance(method_id, str) and method_id.strip() and method_id not in method_ids, "valuation method_id must be unique")
        assert isinstance(method_id, str)
        method_ids.add(method_id)
        _validate_method_contract(method, financials)
    return value, method_ids


def _validate_sensitivity_cases(value: Any, methods: list[dict[str, Any]], method_ids: set[str]) -> None:
    _require(isinstance(value, list), "sensitivity_cases must be a list")
    assert isinstance(value, list)
    sensitivity_ids: set[str] = set()
    for case in value:
        _require(isinstance(case, dict), "sensitivity case must be an object")
        assert isinstance(case, dict)
        sensitivity_id = case.get("sensitivity_id")
        _require(isinstance(sensitivity_id, str) and sensitivity_id.strip() and sensitivity_id not in sensitivity_ids, "sensitivity IDs must be unique")
        assert isinstance(sensitivity_id, str)
        sensitivity_ids.add(sensitivity_id)
        _require(case.get("method_id") in method_ids, f"unknown sensitivity method: {sensitivity_id}")
        _require(case.get("scenario") in SCENARIOS, f"invalid sensitivity scenario: {sensitivity_id}")
        method = next(item for item in methods if item["method_id"] == case["method_id"])
        variable = case.get("variable")
        _require(isinstance(variable, str), f"sensitivity variable is required: {sensitivity_id}")
        assert isinstance(variable, str)
        _parameter_template_for_variable(method, variable)
        value_ids = case.get("value_parameter_ids")
        _require(isinstance(value_ids, list) and len(value_ids) >= 2 and len(value_ids) == len(set(value_ids)), f"sensitivity requires at least two unique values: {sensitivity_id}")


def _validate_reverse_cases(value: Any, method_ids: set[str]) -> None:
    _require(isinstance(value, list), "reverse_cases must be a list")
    assert isinstance(value, list)
    reverse_ids: set[str] = set()
    for case in value:
        _require(isinstance(case, dict), "reverse case must be an object")
        assert isinstance(case, dict)
        reverse_id = case.get("reverse_id")
        _require(isinstance(reverse_id, str) and reverse_id.strip() and reverse_id not in reverse_ids, "reverse IDs must be unique")
        assert isinstance(reverse_id, str)
        reverse_ids.add(reverse_id)
        _require(case.get("method_id") in method_ids, f"unknown reverse method: {reverse_id}")
        _require(case.get("scenario") in SCENARIOS, f"invalid reverse scenario: {reverse_id}")
        _require(case.get("solve_for") in {"multiple", "terminal_growth"}, f"invalid reverse solve_for: {reverse_id}")
        _require(isinstance(case.get("target_equity_value_parameter_id"), str) and case["target_equity_value_parameter_id"], f"reverse target parameter is required: {reverse_id}")


def _validate_model(model: dict[str, Any], financials: dict[str, Any]) -> list[dict[str, Any]]:
    _require(model.get("valuation_model_schema_version") == VALUATION_MODEL_SCHEMA_VERSION, "valuation_model_schema_version must be 2.0")
    for forbidden in ("revenue_override", "profit_override", "cash_flow_override", "scenario_probabilities"):
        _require(forbidden not in model, f"valuation input contains prohibited override: {forbidden}")
    methods, method_ids = _validate_methods(model.get("methods"), financials)
    _validated_weights(model.get("method_weights"), list(method_ids))
    _validate_sensitivity_cases(model.get("sensitivity_cases", []), methods, method_ids)
    _validate_reverse_cases(model.get("reverse_cases", []), method_ids)
    return methods


def validate_valuation_artifact(artifact: dict[str, Any]) -> None:
    """Recompute a schema-2 valuation artifact, including timing and security bridges."""
    validate_artifact(artifact)
    _require(artifact["module"] == "valuation", "expected valuation artifact")
    if artifact["artifact_schema_version"] != ARTIFACT_SCHEMA_VERSION:
        return
    data = artifact["data"]
    _require(data.get("valuation_model_schema_version") == VALUATION_MODEL_SCHEMA_VERSION, "invalid valuation model schema")
    financials = data.get("financial_artifact_snapshot")
    _require(isinstance(financials, dict), "valuation artifact must freeze financial artifact")
    validate_financial_artifact(financials)
    _require(artifact["upstream_artifacts"] == [artifact_reference(financials)], "valuation upstream snapshot mismatch")
    model = {
        "valuation_model_schema_version": data["valuation_model_schema_version"],
        "methods": data["methods"], "method_weights": data.get("method_weights"),
        "equity_adjustments": data.get("equity_adjustments", []),
        "security_bridge": data.get("security_bridge"),
        "sensitivity_cases": data.get("sensitivity_cases", []),
        "reverse_cases": data.get("reverse_cases", []),
        "parameters": artifact["parameters"],
    }
    _validate_model(model, financials)
    expected, normalized_weights = _calculate_valuations(financials, model)
    _require(data.get("method_weights") == normalized_weights, "valuation normalized method weights mismatch")
    _require(data.get("scenario_valuations") == expected, "valuation semantic recomputation mismatch")
    _require(data.get("sensitivity_results") == _calculate_sensitivities(financials, model), "valuation sensitivity recomputation mismatch")
    _require(data.get("reverse_results") == _calculate_reverse_cases(financials, model), "valuation reverse-case recomputation mismatch")


def run_valuation(financials: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    validate_financial_artifact(financials)
    _require(financials["module"] == "financials", "valuation requires a financials artifact")
    _require(financials["scenario_set"] == list(SCENARIOS), "financial scenario set mismatch")
    if model.get("scenario_manifest") is not None:
        _require(model["scenario_manifest"] == financials["scenario_manifest"], "valuation scenario manifest mismatch")
    methods = _validate_model(model, financials)
    scenario_values, weights = _calculate_valuations(financials, model)
    data = {
        "valuation_model_schema_version": VALUATION_MODEL_SCHEMA_VERSION,
        "methods": methods, "method_weights": weights,
        "equity_adjustments": model.get("equity_adjustments", []),
        "security_bridge": model.get("security_bridge"),
        "sensitivity_cases": model.get("sensitivity_cases", []),
        "reverse_cases": model.get("reverse_cases", []),
        "financial_artifact_snapshot": financials,
        "management_target_coverage_status": financials["revenue_forecast_ref"]["management_target_coverage_status"],
        "management_target_summary": financials["revenue_forecast_ref"]["management_target_summary"],
        "scenario_valuations": scenario_values,
        "sensitivity_results": _calculate_sensitivities(financials, model),
        "reverse_results": _calculate_reverse_cases(financials, model),
    }
    artifact = create_artifact(
        "valuation", financials["identity"], financials["scope"], data,
        scenario_set=list(SCENARIOS), scenario_manifest=financials["scenario_manifest"],
        revenue_forecast_ref=financials["revenue_forecast_ref"],
        upstream_artifacts=[financials], sources=model.get("sources", []),
        parameters=model.get("parameters", []), evidence_claims=model.get("evidence_claims", []),
        limitations=model.get("limitations", []),
    )
    validate_valuation_artifact(artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description="Value a validated financial artifact with explicit value dates")
    parser.add_argument("financials", nargs="?")
    parser.add_argument("model", nargs="?")
    parser.add_argument("--output")
    parser.add_argument("--validate-artifact")
    args = parser.parse_args()
    try:
        if args.validate_artifact:
            validate_valuation_artifact(read_json(args.validate_artifact))
            print("valuation artifact valid")
            return 0
        _require(bool(args.financials and args.model and args.output), "financials, model, and --output are required")
        result = run_valuation(read_json(args.financials), read_json(args.model))
        write_new_json(args.output, result)
        return 0
    except (InvestmentArtifactError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
