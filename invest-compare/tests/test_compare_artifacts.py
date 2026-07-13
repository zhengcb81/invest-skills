from __future__ import annotations

import sys
import unittest
from pathlib import Path


SUITE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SUITE / "invest-core" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from compare_artifacts import run_comparison  # noqa: E402
from invest_contracts import InvestmentArtifactError, create_artifact, validate_artifact  # noqa: E402


def artifact(company: str, metric: float, currency: str = "USD") -> dict:
    identity = {
        "company_name": company, "as_of_date": "2026-07-12", "currency": currency, "unit": "million",
        "fiscal_year_end": "12-31", "base_year": 2025, "forecast_years": [2026, 2027],
    }
    return create_artifact(
        "management", identity, {"type": "company", "name": company},
        {"execution_metric": metric}, limitations=["Synthetic"],
    )


def model() -> dict:
    return {
        "target_currency": "USD", "target_unit": "million", "require_same_as_of": True,
        "metrics": [{"name": "execution", "path": "data.execution_metric", "monetary": False}],
        "parameters": [], "sources": [], "evidence_claims": [], "limitations": ["Synthetic"],
    }


class CompareArtifactsTests(unittest.TestCase):
    def test_compares_without_research_or_recalculation(self) -> None:
        result = run_comparison([artifact("A", 2), artifact("B", 3)], model())
        validate_artifact(result)
        self.assertEqual([row["values"]["execution"] for row in result["data"]["rows"]], [2, 3])

    def test_duplicate_company_is_rejected(self) -> None:
        with self.assertRaisesRegex(InvestmentArtifactError, "unique"):
            run_comparison([artifact("A", 2), artifact("A", 3)], model())

    def test_fx_mismatch_requires_explicit_normalization(self) -> None:
        with self.assertRaisesRegex(InvestmentArtifactError, "normalization parameter"):
            run_comparison([artifact("A", 2), artifact("B", 3, "EUR")], model())


if __name__ == "__main__":
    unittest.main()
