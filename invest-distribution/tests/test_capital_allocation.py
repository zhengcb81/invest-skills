from __future__ import annotations

import sys
import unittest
from pathlib import Path


SUITE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SUITE / "invest-core" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from capital_allocation import run_capital_allocation  # noqa: E402
from invest_contracts import InvestmentArtifactError, SCENARIOS, create_artifact, validate_artifact  # noqa: E402


def financials() -> dict:
    identity = {
        "company_name": "Test Co", "as_of_date": "2026-07-12", "currency": "USD", "unit": "million",
        "fiscal_year_end": "12-31", "base_year": 2025, "forecast_years": [2026, 2027],
    }
    ref = {"schema_version": "3.0", "engine_version": "3.0.0", "input_sha256": "a" * 64, "result_sha256": "b" * 64}
    return create_artifact(
        "financials", identity, {"type": "company", "name": "Test Co"},
        {"annual_financials": {scenario: {} for scenario in SCENARIOS}}, scenario_set=list(SCENARIOS),
        revenue_forecast_ref=ref, limitations=["Synthetic"],
    )


def model() -> dict:
    templates = {measure: measure + "_{year}" for measure in (
        "net_income", "dividends", "repurchases", "share_issuance", "acquisition_spend", "impairments", "internal_reinvestment", "share_count"
    )}
    params = []
    values = {
        "net_income": [100, 120], "dividends": [20, 24], "repurchases": [10, 12], "share_issuance": [2, 1],
        "acquisition_spend": [30, 10], "impairments": [0, 5], "internal_reinvestment": [50, 60], "share_count": [100, 98],
    }
    for measure, series in values.items():
        for year, value in zip((2024, 2025), series):
            params.append({
                "parameter_id": f"{measure}_{year}", "kind": "analyst_assumption", "value": value,
                "unit": "shares" if measure == "share_count" else "USD million", "period": f"FY{year}",
                "definition": measure.replace("_", " "), "dimension": "quantity" if measure == "share_count" else ("profit" if measure == "net_income" else "cash_flow"),
                "time_basis": "annual", "scenario": "shared", "currency": None if measure == "share_count" else "USD",
                "scale": None if measure == "share_count" else "million", "source_ids": [], "claim_ids": [], "rationale": "Synthetic",
            })
    return {"historical_years": [2024, 2025], "parameter_templates": templates, "parameters": params, "sources": [], "evidence_claims": [], "limitations": ["Synthetic"]}


class CapitalAllocationTests(unittest.TestCase):
    def test_calculates_dilution_and_flows(self) -> None:
        result = run_capital_allocation(financials(), model())
        validate_artifact(result)
        self.assertLess(result["data"]["share_count_cagr"], 0)
        self.assertEqual(result["data"]["annual_allocation"][0]["net_repurchase_cash"], 8)

    def test_missing_flow_does_not_default_to_zero(self) -> None:
        value = model()
        value["parameters"] = [item for item in value["parameters"] if item["parameter_id"] != "dividends_2024"]
        with self.assertRaisesRegex(InvestmentArtifactError, "missing allocation parameter"):
            run_capital_allocation(financials(), value)


if __name__ == "__main__":
    unittest.main()
