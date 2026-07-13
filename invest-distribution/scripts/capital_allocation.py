"""Deterministic capital-allocation history over a validated financial artifact."""

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


MEASURES = (
    "net_income", "dividends", "repurchases", "share_issuance",
    "acquisition_spend", "impairments", "internal_reinvestment", "share_count",
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InvestmentArtifactError(message)


def _index(parameters: Any) -> dict[str, dict[str, Any]]:
    _require(isinstance(parameters, list), "parameters must be a list")
    index = {}
    for parameter in parameters:
        _require(isinstance(parameter, dict), "allocation parameter must be an object")
        parameter_id = parameter.get("parameter_id")
        _require(isinstance(parameter_id, str) and parameter_id.strip() and parameter_id not in index, "allocation parameter_id must be unique")
        index[parameter_id] = parameter
    return index


def _value(index: dict[str, dict[str, Any]], template: str, year: int, measure: str) -> float:
    parameter_id = template.format(year=year)
    _require(parameter_id in index, f"missing allocation parameter: {parameter_id}")
    parameter = index[parameter_id]
    _require(parameter.get("period") == f"FY{year}" and parameter.get("time_basis") == "annual", f"allocation period mismatch: {parameter_id}")
    expected_dimension = "quantity" if measure == "share_count" else ("profit" if measure == "net_income" else "cash_flow")
    _require(parameter.get("dimension") == expected_dimension, f"allocation dimension mismatch: {parameter_id}")
    value = parameter.get("value")
    _require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)), f"invalid allocation value: {parameter_id}")
    if measure not in {"net_income"}:
        _require(float(value) >= 0, f"allocation flow cannot be negative: {parameter_id}")
    return float(value)


def _ratio(numerator: float, denominator: float) -> float | None:
    return None if denominator <= 0 else numerator / denominator


def run_capital_allocation(financials: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    validate_artifact(financials)
    _require(financials["module"] == "financials", "distribution requires a financials artifact")
    years = model.get("historical_years")
    _require(isinstance(years, list) and len(years) >= 2 and all(isinstance(year, int) for year in years), "historical_years requires at least two integers")
    _require(years == sorted(years) and all(right - left == 1 for left, right in zip(years, years[1:])), "historical_years must be consecutive")
    templates = model.get("parameter_templates")
    _require(isinstance(templates, dict) and set(templates) == set(MEASURES), "parameter_templates must cover all allocation measures")
    parameters = _index(model.get("parameters", []))
    annual = []
    for year in years:
        values = {measure: _value(parameters, templates[measure], year, measure) for measure in MEASURES}
        values.update({
            "year": year,
            "retained_earnings": values["net_income"] - values["dividends"],
            "net_repurchase_cash": values["repurchases"] - values["share_issuance"],
            "payout_ratio": _ratio(values["dividends"], values["net_income"]),
            "internal_reinvestment_ratio": _ratio(values["internal_reinvestment"], values["net_income"]),
            "acquisition_impairment_ratio": _ratio(values["impairments"], values["acquisition_spend"]),
        })
        annual.append(values)
    totals = {measure: sum(row[measure] for row in annual) for measure in MEASURES if measure != "share_count"}
    first_shares = annual[0]["share_count"]
    last_shares = annual[-1]["share_count"]
    _require(first_shares > 0 and last_shares > 0, "share_count must be positive")
    share_cagr = (last_shares / first_shares) ** (1 / (len(years) - 1)) - 1
    data = {
        "historical_years": years,
        "annual_allocation": annual,
        "cumulative_flows": totals,
        "share_count_cagr": share_cagr,
    }
    return create_artifact(
        "distribution", financials["identity"], financials["scope"], data,
        revenue_forecast_ref=financials.get("revenue_forecast_ref"), upstream_artifacts=[financials],
        sources=model.get("sources", []), parameters=model.get("parameters", []),
        evidence_claims=model.get("evidence_claims", []), limitations=model.get("limitations", []),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Calculate source-linked capital-allocation history")
    parser.add_argument("financials")
    parser.add_argument("model")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = run_capital_allocation(read_json(args.financials), read_json(args.model))
        write_new_json(args.output, result)
        return 0
    except (InvestmentArtifactError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
