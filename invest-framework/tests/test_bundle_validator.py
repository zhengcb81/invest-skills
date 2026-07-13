from __future__ import annotations

import sys
import unittest
from pathlib import Path


SUITE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SUITE / "invest-core" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from bundle_validator import run_bundle  # noqa: E402
from invest_contracts import InvestmentArtifactError, SCENARIOS, create_artifact, validate_artifact  # noqa: E402


def identity() -> dict:
    return {
        "company_name": "Test Co", "as_of_date": "2026-07-12", "currency": "USD", "unit": "million",
        "fiscal_year_end": "12-31", "base_year": 2025, "forecast_years": [2026, 2027],
    }


def chain() -> tuple[dict, dict]:
    ref = {"schema_version": "3.0", "engine_version": "3.0.0", "input_sha256": "a" * 64, "result_sha256": "b" * 64}
    financial = create_artifact(
        "financials", identity(), {"type": "company", "name": "Test Co"}, {"annual_financials": {}},
        scenario_set=list(SCENARIOS), revenue_forecast_ref=ref, limitations=["Synthetic"],
    )
    valuation = create_artifact(
        "valuation", identity(), {"type": "company", "name": "Test Co"}, {"scenario_valuations": {}},
        scenario_set=list(SCENARIOS), revenue_forecast_ref=ref, upstream_artifacts=[financial], limitations=["Synthetic"],
    )
    return financial, valuation


class BundleValidatorTests(unittest.TestCase):
    def test_valid_dependency_order(self) -> None:
        financial, valuation = chain()
        bundle = run_bundle([valuation, financial], {"required_modules": ["financials", "valuation"], "optional_modules": ["moat"]})
        validate_artifact(bundle)
        order = [item["module"] for item in bundle["data"]["execution_order"]]
        self.assertLess(order.index("financials"), order.index("valuation"))
        self.assertEqual(bundle["data"]["missing_optional_modules"], ["moat"])

    def test_missing_upstream_is_rejected(self) -> None:
        _, valuation = chain()
        with self.assertRaisesRegex(InvestmentArtifactError, "missing upstream"):
            run_bundle([valuation], {"required_modules": ["valuation"], "optional_modules": []})

    def test_psychology_is_excluded(self) -> None:
        psychology = create_artifact(
            "psychology", identity(), {"type": "company", "name": "Test Co"}, {"answers": {}}, limitations=["Synthetic"],
        )
        with self.assertRaisesRegex(InvestmentArtifactError, "does not belong"):
            run_bundle([psychology], {"required_modules": [], "optional_modules": []})


if __name__ == "__main__":
    unittest.main()
