"""Execute every registered financial family through a valuation artifact."""

from __future__ import annotations

import sys
from pathlib import Path


SUITE = Path(__file__).resolve().parents[1]
for path in (
    SUITE / "invest-core" / "scripts", SUITE / "invest-financials" / "scripts",
    SUITE / "invest-valuation" / "scripts", SUITE / "tests_support",
):
    sys.path.insert(0, str(path))

from financial_model import run_financial_model  # noqa: E402
from revenue_fixtures import load_revenue_fixture  # noqa: E402
from valuation_model import run_valuation  # noqa: E402


CASES = {
    "operating_company": ("net_income", "profit", None, "pe"),
    "bank": ("net_income", "profit", None, "pe"),
    "insurer": ("net_income", "profit", None, "pe"),
    "reit": ("adjusted_funds_from_operations", "profit", None, "p_affo"),
    "pre_revenue": ("cash_burn", "cash_flow", "generic", "asset"),
}


def financial_model(forecast: dict, family: str, role: str, dimension: str, cash_basis: str | None) -> dict:
    parameters = []
    for scenario, ratio in (("low", 0.08), ("base", 0.10), ("high", 0.12)):
        for year in forecast["forecast_years"]:
            parameters.append({
                "parameter_id": f"ratio_{scenario}_{year}", "kind": "analyst_assumption", "value": ratio,
                "unit": "ratio", "period": f"FY{year}", "definition": f"Synthetic {role} ratio",
                "dimension": "ratio", "time_basis": "annual", "scenario": scenario,
                "source_ids": [], "claim_ids": [], "rationale": "Executable contract example",
            })
    line = {
        "line_id": role, "formula": "x0*x1",
        "input_refs": ["revenue", "parameter:ratio_{scenario}_{year}"],
        "input_dimensions": ["revenue", "ratio"], "output_dimension": dimension,
        "time_basis": "annual", "metric_role": role, "dimension_rule": "monetary_times_rate",
    }
    if cash_basis is not None:
        line["cash_flow_basis"] = cash_basis
    return {
        "financial_model_schema_version": "2.0",
        "scope": {"type": "company", "name": forecast["company_name"]},
        "model_family": family, "parameters": parameters, "lines": [line],
        "required_outputs": [role], "sources": [], "evidence_claims": [],
        "limitations": ["Synthetic execution example; not an accounting recommendation"],
    }


def valuation_model(forecast: dict, kind: str, metric: str) -> dict:
    parameters = []
    if kind == "asset":
        for scenario, value in (("low", 60.0), ("base", 100.0), ("high", 140.0)):
            parameters.append({
                "parameter_id": f"asset_{scenario}", "kind": "analyst_assumption", "value": value,
                "unit": "USD million", "period": forecast["as_of_date"], "definition": "Adjusted asset value",
                "dimension": "asset", "time_basis": "point_in_time", "scenario": scenario,
                "currency": "USD", "scale": "million", "source_ids": [], "claim_ids": [],
                "rationale": "Synthetic execution example",
            })
        methods = [{
            "method_id": "asset", "type": "asset", "value_basis": "equity",
            "valuation_timing": "current", "value_parameter_template": "asset_{scenario}",
        }]
    else:
        for scenario, multiple in (("low", 8.0), ("base", 10.0), ("high", 12.0)):
            parameters.append({
                "parameter_id": f"multiple_{scenario}", "kind": "analyst_assumption", "value": multiple,
                "unit": "multiple", "period": forecast["as_of_date"], "definition": f"Synthetic {kind} multiple",
                "dimension": "multiple", "time_basis": "point_in_time", "scenario": scenario,
                "source_ids": [], "claim_ids": [], "rationale": "Synthetic execution example",
            })
        methods = [{
            "method_id": kind, "type": "multiple", "multiple_kind": kind, "metric": metric,
            "metric_period": f"FY{forecast['forecast_years'][-1]}", "value_basis": "equity",
            "valuation_timing": "current", "multiple_parameter_template": "multiple_{scenario}",
        }]
    return {
        "valuation_model_schema_version": "2.0", "methods": methods, "equity_adjustments": [],
        "parameters": parameters, "sources": [], "evidence_claims": [],
        "limitations": ["Synthetic execution example; not an investment conclusion"],
    }


def main() -> int:
    forecast = load_revenue_fixture("direct")
    for family, (role, dimension, cash_basis, valuation_kind) in CASES.items():
        financial = run_financial_model(forecast, financial_model(forecast, family, role, dimension, cash_basis))
        valuation = run_valuation(financial, valuation_model(forecast, valuation_kind, role))
        base_value = valuation["data"]["scenario_valuations"]["base"]["methods"][valuation_kind]["equity_value_current"]
        print(f"{family}: base current equity value={base_value:.2f} {forecast['currency']} {forecast['unit']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
