from __future__ import annotations

import sys
import unittest
from pathlib import Path


SUITE = Path(__file__).resolve().parents[2]
for path in (
    SUITE / "invest-core" / "scripts",
    SUITE / "invest-financials" / "scripts",
    SUITE / "invest-valuation" / "scripts",
    Path(__file__).resolve().parents[1] / "scripts",
):
    sys.path.insert(0, str(path))

from bundle_validator import run_bundle  # noqa: E402
from financial_model import run_financial_model  # noqa: E402
from invest_contracts import revenue_runtime, validate_artifact  # noqa: E402
from valuation_model import run_valuation  # noqa: E402


class EndToEndTests(unittest.TestCase):
    def test_revenue_to_financials_to_valuation_to_bundle(self) -> None:
        core, _, rf_dir = revenue_runtime()
        sys.path.insert(0, str(rf_dir / "tests"))
        from test_industry_end_to_end import model_document
        forecast = core.run_forecast(model_document("direct_revenue"))
        financial_parameters = []
        for scenario, margin in (("low", 0.08), ("base", 0.10), ("high", 0.12)):
            for year in forecast["forecast_years"]:
                financial_parameters.append({
                    "parameter_id": f"fcf_margin_{scenario}_{year}", "kind": "analyst_assumption", "value": margin,
                    "unit": "ratio", "period": f"FY{year}", "definition": "FCF margin", "dimension": "ratio",
                    "time_basis": "annual", "scenario": scenario, "source_ids": [], "claim_ids": [], "rationale": "Synthetic",
                })
        financials = run_financial_model(forecast, {
            "scope": {"type": "company", "name": forecast["company_name"]}, "model_family": "operating_company",
            "parameters": financial_parameters,
            "lines": [{"line_id": "free_cash_flow", "formula": "x0*x1", "input_refs": ["revenue", "parameter:fcf_margin_{scenario}_{year}"]}],
            "required_outputs": ["free_cash_flow"], "sources": [], "evidence_claims": [], "limitations": ["Synthetic"],
        })
        valuation_parameters = []
        for scenario, rate, growth in (("low", 0.12, 0.01), ("base", 0.10, 0.02), ("high", 0.09, 0.025)):
            valuation_parameters.extend([
                {"parameter_id": f"discount_{scenario}", "kind": "analyst_assumption", "value": rate, "unit": "ratio", "period": forecast["as_of_date"], "definition": "discount rate", "dimension": "discount_rate", "time_basis": "point_in_time", "scenario": scenario, "source_ids": [], "claim_ids": [], "rationale": "Synthetic"},
                {"parameter_id": f"growth_{scenario}", "kind": "analyst_assumption", "value": growth, "unit": "ratio", "period": forecast["as_of_date"], "definition": "terminal growth", "dimension": "ratio", "time_basis": "point_in_time", "scenario": scenario, "source_ids": [], "claim_ids": [], "rationale": "Synthetic"},
            ])
        valuation = run_valuation(financials, {
            "methods": [{"method_id": "dcf", "type": "dcf", "metric": "free_cash_flow", "value_basis": "enterprise", "discount_rate_parameter_template": "discount_{scenario}", "terminal_growth_parameter_template": "growth_{scenario}"}],
            "equity_adjustments": [], "parameters": valuation_parameters, "sources": [], "evidence_claims": [], "limitations": ["Synthetic"],
        })
        bundle = run_bundle([valuation, financials], {"required_modules": ["financials", "valuation"], "optional_modules": ["moat", "management"]})
        validate_artifact(bundle)
        self.assertEqual(bundle["data"]["module_counts"], {"financials": 1, "valuation": 1})


if __name__ == "__main__":
    unittest.main()
