from __future__ import annotations

import sys
import unittest
from pathlib import Path


SUITE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SUITE / "invest-core" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(SUITE / "invest-framework" / "scripts"))
sys.path.insert(0, str(SUITE / "tests_support"))

from compare_artifacts import run_comparison, validate_comparison_artifact  # noqa: E402
from bundle_validator import run_bundle  # noqa: E402
from invest_contracts import InvestmentArtifactError, SCENARIOS, canonical_sha256, create_artifact, revenue_reference, validate_artifact  # noqa: E402
from revenue_fixtures import load_revenue_fixture  # noqa: E402
from artifact_test_utils import reseal_artifact  # noqa: E402


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


def growth_bundle(company: str, *, currency: str = "USD") -> dict:
    result = load_revenue_fixture("growth")
    identity = {
        "company_name": company, "as_of_date": result["as_of_date"],
        "currency": currency, "unit": result["unit"],
        "fiscal_year_end": result["fiscal_year_end"], "base_year": result["base_year"],
        "forecast_years": result["forecast_years"],
    }
    body = {
        "artifact_schema_version": "1.0", "invest_suite_version": "4.2.0", "module": "financials",
        "identity": identity, "scope": {"type": "company", "name": company},
        "scenario_set": list(SCENARIOS), "revenue_forecast_ref": revenue_reference(result),
        "upstream_artifacts": [], "sources": [], "parameters": [], "evidence_claims": [],
        "data": {"annual_financials": {}}, "limitations": ["Synthetic legacy carrier"],
    }
    financial = {**body, "artifact_id": canonical_sha256(body)}
    financial["artifact_sha256"] = canonical_sha256(financial)
    validate_artifact(financial)
    plan = {
        "bundle_plan_schema_version": "2.0", "required_modules": ["financials"],
        "optional_modules": [], "required_scoped_artifacts": [],
        "optional_scoped_artifacts": [], "limitations": [],
    }
    return run_bundle([financial], plan)


def growth_model() -> dict:
    return {
        "comparison_model_schema_version": "2.1", "comparison_kind": "growth_drivers",
        "target_currency": "USD", "target_unit": "million",
        "require_same_as_of": True, "require_same_horizon": True,
        "limitations": ["Uses only validated upstream growth-driver summaries"],
    }


class CompareArtifactsTests(unittest.TestCase):
    def test_compares_without_research_or_recalculation(self) -> None:
        result = run_comparison([artifact("A", 2), artifact("B", 3)], model())
        validate_artifact(result)
        validate_comparison_artifact(result)
        self.assertEqual(result["data"]["comparison_model_schema_version"], "2.1")
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
        reseal_artifact(result)
        with self.assertRaisesRegex(InvestmentArtifactError, "semantic recomputation"):
            validate_comparison_artifact(result)

    def test_compares_validated_growth_driver_summaries_without_research(self) -> None:
        result = run_comparison([growth_bundle("A"), growth_bundle("B")], growth_model())
        validate_comparison_artifact(result)
        self.assertEqual(result["data"]["comparison_kind"], "growth_drivers")
        self.assertEqual(result["scenario_set"], [])
        self.assertEqual(len(result["data"]["rows"][0]["growth_driver_summary"]["drivers"]), 2)

    def test_growth_driver_comparison_rejects_currency_mismatch(self) -> None:
        with self.assertRaisesRegex(InvestmentArtifactError, "currency mismatch"):
            run_comparison([growth_bundle("A"), growth_bundle("B", currency="EUR")], growth_model())

    def test_growth_driver_comparison_semantically_recomputes_rows(self) -> None:
        result = run_comparison([growth_bundle("A"), growth_bundle("B")], growth_model())
        result["data"]["rows"][0]["growth_driver_summary"]["drivers"][0]["thesis"] = "Altered"
        reseal_artifact(result)
        with self.assertRaisesRegex(InvestmentArtifactError, "semantic recomputation"):
            validate_comparison_artifact(result)


if __name__ == "__main__":
    unittest.main()
