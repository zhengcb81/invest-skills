from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT.parent / "invest-core" / "scripts"))

from financial_model import run_financial_model  # noqa: E402
from invest_contracts import InvestmentArtifactError, revenue_runtime, validate_artifact  # noqa: E402


def forecast_result() -> dict:
    core, _, rf_dir = revenue_runtime()
    sys.path.insert(0, str(rf_dir / "tests"))
    from test_industry_end_to_end import model_document
    return core.run_forecast(model_document("direct_revenue"))


def model_input() -> dict:
    parameters = []
    for scenario, margin in (("low", 0.10), ("base", 0.15), ("high", 0.20)):
        for year in (2026, 2027):
            parameters.append({
                "parameter_id": f"operating_margin_{scenario}_{year}",
                "kind": "analyst_assumption",
                "value": margin,
                "unit": "ratio",
                "period": f"FY{year}",
                "definition": "operating margin assumption",
                "dimension": "ratio",
                "time_basis": "annual",
                "scenario": scenario,
                "source_ids": [],
                "claim_ids": [],
                "rationale": "Synthetic scenario assumption",
            })
    return {
        "scope": {"type": "company", "name": "Test Co"},
        "model_family": "operating_company",
        "parameters": parameters,
        "lines": [{
            "line_id": "operating_profit",
            "formula": "x0 * x1",
            "input_refs": ["revenue", "parameter:operating_margin_{scenario}_{year}"],
        }],
        "required_outputs": ["operating_profit"],
        "sources": [],
        "evidence_claims": [],
        "limitations": ["Synthetic fixture"],
    }


class FinancialModelTests(unittest.TestCase):
    def test_revenue_is_copied_and_profit_is_recomputed(self) -> None:
        forecast = forecast_result()
        artifact = run_financial_model(forecast, model_input())
        validate_artifact(artifact)
        year = str(forecast["forecast_years"][0])
        row = artifact["data"]["annual_financials"]["base"][year]
        self.assertEqual(row["revenue"], forecast["consolidated_forecast"]["base"]["annual_revenue"][year])
        self.assertAlmostEqual(row["operating_profit"], row["revenue"] * 0.15)

    def test_missing_parameter_blocks_instead_of_defaulting(self) -> None:
        model = model_input()
        model["parameters"] = model["parameters"][1:]
        with self.assertRaisesRegex(InvestmentArtifactError, "missing financial parameter"):
            run_financial_model(forecast_result(), model)

    def test_forward_line_reference_is_rejected(self) -> None:
        model = model_input()
        model["lines"][0]["input_refs"] = ["line:future_line"]
        with self.assertRaisesRegex(InvestmentArtifactError, "forward or unknown"):
            run_financial_model(forecast_result(), model)


if __name__ == "__main__":
    unittest.main()
