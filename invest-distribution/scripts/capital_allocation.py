"""Deterministic, source-linked capital-allocation history."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast


SUITE = Path(__file__).resolve().parents[2]
for scripts in (SUITE / "invest-core" / "scripts", SUITE / "invest-financials" / "scripts"):
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))

from financial_model import validate_financial_artifact  # noqa: E402
from invest_contracts import (  # noqa: E402
    ARTIFACT_SCHEMA_VERSION,
    InvestmentArtifactError,
    artifact_reference,
    create_artifact,
    finite_number,
    parameter_by_id,
    read_json,
    render_parameter_template,
    validate_artifact,
    write_new_json,
)


DISTRIBUTION_MODEL_SCHEMA_VERSION = "2.0"
MEASURES = (
    "net_income", "dividends", "repurchases", "share_issuance",
    "acquisition_spend", "impairments", "internal_reinvestment", "share_count",
)
SHARE_COUNT_BASES = {"diluted_weighted_average", "basic_weighted_average", "period_end"}


def _require(condition: object, message: str) -> None:
    if not condition:
        raise InvestmentArtifactError(message)


def _ratio(numerator: float, denominator: float) -> float | None:
    return None if denominator <= 0 else numerator / denominator


def _value(parameters: list[dict[str, Any]], template: str, year: int, measure: str) -> float:
    parameter_id = render_parameter_template(template, "shared", year=year)
    _require(any(item.get("parameter_id") == parameter_id for item in parameters), f"missing allocation parameter: {parameter_id}")
    expected_dimension = "quantity" if measure == "share_count" else ("profit" if measure == "net_income" else "cash_flow")
    parameter = parameter_by_id(
        parameters, parameter_id, expected_dimensions={expected_dimension}, expected_time_bases={"annual"},
    )
    _require(parameter.get("period") == f"FY{year}", f"allocation period mismatch: {parameter_id}")
    _require(parameter.get("scenario", "shared") == "shared", f"historical allocation fact cannot be scenario-specific: {parameter_id}")
    _require(parameter.get("kind") in {"reported_fact", "derived_fact"}, f"historical allocation value must be reported_fact or derived_fact: {parameter_id}")
    if parameter["kind"] == "reported_fact":
        _require(bool(parameter.get("source_ids")) and bool(parameter.get("claim_ids")), f"reported allocation fact requires exact evidence: {parameter_id}")
    value = finite_number(parameter["value"], f"{parameter_id}.value")
    if measure != "net_income":
        _require(value >= 0, f"allocation flow cannot be negative: {parameter_id}")
    return value


def _validate_model(model: dict[str, Any], financials: dict[str, Any]) -> tuple[list[int], dict[str, str], dict[str, Any]]:
    _require(model.get("distribution_model_schema_version") == DISTRIBUTION_MODEL_SCHEMA_VERSION, "distribution_model_schema_version must be 2.0")
    years = model.get("historical_years")
    _require(isinstance(years, list) and len(years) >= 2 and all(isinstance(year, int) and not isinstance(year, bool) for year in years), "historical_years requires at least two integers")
    assert isinstance(years, list)
    _require(years == sorted(set(years)) and all(right - left == 1 for left, right in zip(years, years[1:])), "historical_years must be unique and consecutive")
    _require(max(years) <= financials["identity"]["base_year"], "historical_years cannot exceed the frozen base year")
    templates = model.get("parameter_templates")
    _require(isinstance(templates, dict) and set(templates) == set(MEASURES), "parameter_templates must cover all allocation measures")
    assert isinstance(templates, dict)
    _require(all(isinstance(value, str) and value for value in templates.values()), "allocation parameter templates must be non-empty strings")
    share_basis = model.get("share_count_basis")
    _require(isinstance(share_basis, dict), "share_count_basis must be an object")
    assert isinstance(share_basis, dict)
    _require(share_basis.get("basis") in SHARE_COUNT_BASES, "unsupported share_count_basis")
    _require(isinstance(share_basis.get("unit"), str) and share_basis["unit"].strip(), "share_count_basis.unit is required")
    return cast(list[int], years), cast(dict[str, str], templates), share_basis


def _calculate(model: dict[str, Any], financials: dict[str, Any]) -> dict[str, Any]:
    years, templates, share_basis = _validate_model(model, financials)
    parameters = model.get("parameters", [])
    annual: list[dict[str, Any]] = []
    for year in years:
        values: dict[str, Any] = {measure: _value(parameters, templates[measure], year, measure) for measure in MEASURES}
        shares = values["share_count"]
        _require(shares > 0, f"share_count must be positive: FY{year}")
        values.update({
            "year": year,
            "profit_retained_after_dividends": values["net_income"] - values["dividends"],
            "net_repurchase_cash": values["repurchases"] - values["share_issuance"],
            "payout_ratio": _ratio(values["dividends"], values["net_income"]),
            "internal_reinvestment_ratio": _ratio(values["internal_reinvestment"], values["net_income"]),
            "acquisition_impairment_ratio": _ratio(values["impairments"], values["acquisition_spend"]),
            "net_income_per_share_unit": values["net_income"] / shares,
            "dividend_per_share_unit": values["dividends"] / shares,
            "repurchase_cash_per_share_unit": values["repurchases"] / shares,
        })
        annual.append(values)
    totals = {measure: sum(row[measure] for row in annual) for measure in MEASURES if measure != "share_count"}
    first_shares = annual[0]["share_count"]
    last_shares = annual[-1]["share_count"]
    share_cagr = (last_shares / first_shares) ** (1 / (len(years) - 1)) - 1
    return {
        "historical_years": years, "share_count_basis": share_basis,
        "annual_allocation": annual, "cumulative_flows": totals,
        "share_count_cagr": share_cagr,
        "share_count_change": last_shares - first_shares,
    }


def validate_distribution_artifact(artifact: dict[str, Any]) -> None:
    validate_artifact(artifact)
    _require(artifact["module"] == "distribution", "expected distribution artifact")
    if artifact["artifact_schema_version"] != ARTIFACT_SCHEMA_VERSION:
        return
    data = artifact["data"]
    _require(data.get("distribution_model_schema_version") == DISTRIBUTION_MODEL_SCHEMA_VERSION, "invalid distribution model schema")
    financials = data.get("financial_artifact_snapshot")
    _require(isinstance(financials, dict), "distribution artifact must freeze financial artifact")
    validate_financial_artifact(financials)
    _require(artifact["upstream_artifacts"] == [artifact_reference(financials)], "distribution upstream snapshot mismatch")
    model = {
        "distribution_model_schema_version": data["distribution_model_schema_version"],
        "historical_years": data["historical_years"], "parameter_templates": data["parameter_templates"],
        "share_count_basis": data["share_count_basis"], "parameters": artifact["parameters"],
    }
    expected = _calculate(model, financials)
    for key, value in expected.items():
        _require(data.get(key) == value, f"distribution semantic recomputation mismatch: {key}")


def run_capital_allocation(financials: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    validate_financial_artifact(financials)
    _require(financials["module"] == "financials", "distribution requires a financials artifact")
    calculated = _calculate(model, financials)
    data = {
        "distribution_model_schema_version": DISTRIBUTION_MODEL_SCHEMA_VERSION,
        "parameter_templates": model["parameter_templates"],
        "financial_artifact_snapshot": financials,
        **calculated,
    }
    artifact = create_artifact(
        "distribution", financials["identity"], financials["scope"], data,
        revenue_forecast_ref=financials.get("revenue_forecast_ref"), upstream_artifacts=[financials],
        sources=model.get("sources", []), parameters=model.get("parameters", []),
        evidence_claims=model.get("evidence_claims", []), limitations=model.get("limitations", []),
    )
    validate_distribution_artifact(artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description="Calculate source-linked capital-allocation history")
    parser.add_argument("financials", nargs="?")
    parser.add_argument("model", nargs="?")
    parser.add_argument("--output")
    parser.add_argument("--validate-artifact")
    args = parser.parse_args()
    try:
        if args.validate_artifact:
            validate_distribution_artifact(read_json(args.validate_artifact))
            print("distribution artifact valid")
            return 0
        _require(bool(args.financials and args.model and args.output), "financials, model, and --output are required")
        result = run_capital_allocation(read_json(args.financials), read_json(args.model))
        write_new_json(args.output, result)
        return 0
    except (InvestmentArtifactError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
