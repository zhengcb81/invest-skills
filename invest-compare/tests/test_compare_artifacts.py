from __future__ import annotations

import sys
import unittest
from pathlib import Path


SUITE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SUITE / "invest-core" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from compare_artifacts import run_comparison, validate_comparison_artifact  # noqa: E402
from invest_contracts import InvestmentArtifactError, canonical_sha256, create_artifact, validate_artifact  # noqa: E402


def artifact(company: str, metric: float, currency: str = "USD", unit: str = "million") -> dict:
    identity = {
        "company_name": company, "as_of_date": "2026-07-12", "currency": currency, "unit": unit,
        "fiscal_year_end": "12-31", "base_year": 2025, "forecast_years": [2026, 2027],
    }
    return create_artifact(
        "framework", identity, {"type": "company", "name": company},
        {"execution_metric": metric}, limitations=["Synthetic"],
    )


def metric_contract(companies: tuple[str, ...], *, dimension: str = "score") -> dict:
    return {
        "metric_id": "execution", "label": "Execution metric",
        "path_template": "data.execution_metric", "dimension": dimension,
        "time_basis": "annual", "comparison_period": "FY2027E aligned",
        "value_basis": "not_applicable", "target_definition": "Synthetic aligned metric",
        "source_periods": {company: "FY2027" for company in companies},
        "source_definitions": {company: "Synthetic aligned metric" for company in companies},
        "definition_alignments": {company: "exact" for company in companies},
        "reconciliation_notes": {},
        "normalization": "currency_scale" if dimension in {"profit", "per_share"} else "none",
    }


def model(*, monetary: bool = False) -> dict:
    return {
        "comparison_model_schema_version": "2.0",
        "target_currency": "USD", "target_unit": "million", "require_same_as_of": True,
        "metrics": [metric_contract(("A", "B"), dimension="profit" if monetary else "score")],
        "normalizations": {}, "parameters": [], "sources": [], "evidence_claims": [],
        "limitations": ["Synthetic"],
    }


class CompareArtifactsTests(unittest.TestCase):
    def test_compares_without_research_or_recalculation(self) -> None:
        result = run_comparison([artifact("A", 2), artifact("B", 3)], model())
        validate_artifact(result)
        validate_comparison_artifact(result)
        self.assertEqual([row["values"]["execution"]["normalized_value"] for row in result["data"]["rows"]], [2, 3])

    def test_duplicate_company_is_rejected(self) -> None:
        with self.assertRaisesRegex(InvestmentArtifactError, "unique"):
            run_comparison([artifact("A", 2), artifact("A", 3)], model())

    def test_fx_mismatch_requires_explicit_normalization(self) -> None:
        with self.assertRaisesRegex(InvestmentArtifactError, "currency normalization"):
            run_comparison([artifact("A", 2), artifact("B", 3, "EUR")], model(monetary=True))

    def test_scale_normalization_is_metric_level_and_explicit(self) -> None:
        value = model(monetary=True)
        value["normalizations"] = {"B": {"scale_factor": 1000.0}}
        result = run_comparison([artifact("A", 2), artifact("B", 3, unit="billion")], value)
        row_b = next(row for row in result["data"]["rows"] if row["company_name"] == "B")
        self.assertEqual(row_b["values"]["execution"]["normalized_value"], 3000)

    def test_reconciled_definition_requires_notes(self) -> None:
        value = model()
        value["metrics"][0]["definition_alignments"]["B"] = "reconciled"
        with self.assertRaisesRegex(InvestmentArtifactError, "requires notes"):
            run_comparison([artifact("A", 2), artifact("B", 3)], value)

    def test_semantic_validator_recomputes_rows(self) -> None:
        result = run_comparison([artifact("A", 2), artifact("B", 3)], model())
        result["data"]["rows"][0]["values"]["execution"]["normalized_value"] = 99
        body = {key: value for key, value in result.items() if key not in {"artifact_id", "artifact_sha256"}}
        result["artifact_id"] = canonical_sha256(body)
        result["artifact_sha256"] = canonical_sha256({key: value for key, value in result.items() if key != "artifact_sha256"})
        with self.assertRaisesRegex(InvestmentArtifactError, "semantic recomputation"):
            validate_comparison_artifact(result)


if __name__ == "__main__":
    unittest.main()
