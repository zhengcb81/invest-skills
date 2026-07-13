from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


SUITE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(SUITE / "tests_support"))

from invest_contracts import InvestmentArtifactError, adapt_revenue, create_artifact  # noqa: E402
from revenue_fixtures import load_revenue_fixture  # noqa: E402


def forecast_result() -> dict:
    return load_revenue_fixture("direct")


class RevenueAdapterTests(unittest.TestCase):
    def test_company_adapter_copies_validated_paths(self) -> None:
        result = forecast_result()
        adapter = adapt_revenue(result)
        self.assertEqual(adapter["annual_revenue"]["base"], result["consolidated_forecast"]["base"]["annual_revenue"])
        self.assertEqual(adapter["revenue_forecast_ref"]["result_sha256"], result["result_sha256"])

    def test_segment_adapter_copies_recognized_revenue(self) -> None:
        result = forecast_result()
        segment = result["segments"][0]
        adapter = adapt_revenue(result, "segment", segment["name"])
        self.assertEqual(adapter["annual_revenue"]["low"], segment["scenarios"]["low"]["recognized_revenue"])

    def test_segment_adapter_prefers_revenue_owned_effective_path(self) -> None:
        result = load_revenue_fixture("effective")
        segment = result["segments"][0]
        adapter = adapt_revenue(result, "segment", segment["name"])
        self.assertEqual(adapter["annual_revenue"]["base"], segment["scenarios"]["base"]["effective_revenue"])
        self.assertNotEqual(adapter["annual_revenue"]["base"], segment["scenarios"]["base"]["recognized_revenue"])

    def test_tampered_forecast_is_rejected(self) -> None:
        result = forecast_result()
        tampered = copy.deepcopy(result)
        year = str(result["forecast_years"][0])
        tampered["consolidated_forecast"]["base"]["annual_revenue"][year] += 1
        with self.assertRaisesRegex(InvestmentArtifactError, "invalid revenue forecast"):
            adapt_revenue(tampered)

    def test_management_target_summary_is_hashed_and_transferred(self) -> None:
        result = load_revenue_fixture("target")
        adapter = adapt_revenue(result)
        ref = adapter["revenue_forecast_ref"]
        self.assertEqual(ref["management_target_coverage_status"], "validated")
        self.assertEqual(ref["management_target_counts"]["targets_total"], 1)
        self.assertTrue(ref["management_target_summary"][0]["scenario_comparison"]["high"]["meets_target"])
        tampered = copy.deepcopy(ref)
        tampered["management_target_summary"][0]["statement"] = "Altered target"
        with self.assertRaisesRegex(InvestmentArtifactError, "summary hash mismatch"):
            create_artifact(
                "financials",
                {
                    "company_name": result["company_name"], "as_of_date": result["as_of_date"],
                    "currency": result["currency"], "unit": result["unit"],
                    "fiscal_year_end": result["fiscal_year_end"], "base_year": result["base_year"],
                    "forecast_years": result["forecast_years"],
                },
                {"type": "company", "name": result["company_name"]},
                {"annual_financials": {}}, scenario_set=["low", "base", "high"],
                revenue_forecast_ref=tampered,
            )


if __name__ == "__main__":
    unittest.main()
