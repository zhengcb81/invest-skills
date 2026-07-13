from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT.parent / "invest-core" / "scripts"))
sys.path.insert(0, str(ROOT.parent / "tests_support"))

from financial_model import run_financial_model, validate_financial_artifact  # noqa: E402
from invest_contracts import InvestmentArtifactError, validate_artifact  # noqa: E402
from revenue_fixtures import load_revenue_fixture  # noqa: E402


def forecast_result() -> dict:
    return load_revenue_fixture("direct")


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
        "financial_model_schema_version": "2.0",
        "scope": {"type": "company", "name": "Test Co"},
        "model_family": "operating_company",
        "parameters": parameters,
        "lines": [{
            "line_id": "operating_profit",
            "formula": "x0 * x1",
            "input_refs": ["revenue", "parameter:operating_margin_{scenario}_{year}"],
            "input_dimensions": ["revenue", "ratio"],
            "output_dimension": "profit",
            "time_basis": "annual",
            "metric_role": "operating_profit",
            "dimension_rule": "monetary_times_rate",
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
        validate_financial_artifact(artifact)
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
        model["lines"][0]["input_dimensions"] = ["profit"]
        with self.assertRaisesRegex(InvestmentArtifactError, "forward or unknown"):
            run_financial_model(forecast_result(), model)

    def test_unsupported_model_family_is_rejected(self) -> None:
        model = model_input()
        model["model_family"] = "magic_company"
        with self.assertRaisesRegex(InvestmentArtifactError, "unsupported model_family"):
            run_financial_model(forecast_result(), model)

    def test_parameter_dimension_mismatch_is_rejected(self) -> None:
        model = model_input()
        model["lines"][0]["input_dimensions"][1] = "discount_rate"
        with self.assertRaisesRegex(InvestmentArtifactError, "parameter dimension mismatch"):
            run_financial_model(forecast_result(), model)

    def test_malformed_accounting_identity_is_rejected(self) -> None:
        model = model_input()
        model["accounting_identities"] = [{
            "identity_id": "profit_equals_revenue",
            "formula": "x0",
            "input_refs": ["revenue"],
            "expected_ref": "line:operating_profit",
            "tolerance": 1e-9,
        }]
        with self.assertRaisesRegex(InvestmentArtifactError, "accounting identity mismatch"):
            run_financial_model(forecast_result(), model)

    def test_semantic_validator_recomputes_financial_paths(self) -> None:
        artifact = run_financial_model(forecast_result(), model_input())
        artifact["data"]["annual_financials"]["base"]["2026"]["operating_profit"] += 1
        from invest_contracts import canonical_sha256
        body = {key: value for key, value in artifact.items() if key not in {"artifact_id", "artifact_sha256"}}
        artifact["artifact_id"] = canonical_sha256(body)
        artifact["artifact_sha256"] = canonical_sha256({key: value for key, value in artifact.items() if key != "artifact_sha256"})
        with self.assertRaisesRegex(InvestmentArtifactError, "semantic recomputation"):
            validate_financial_artifact(artifact)

    def test_registered_business_model_families_execute(self) -> None:
        cases = {
            "operating_company": "operating_profit",
            "bank": "net_interest_income",
            "insurer": "underwriting_result",
            "reit": "net_operating_income",
            "pre_revenue": "operating_expense",
        }
        for family, role in cases.items():
            with self.subTest(family=family):
                model = model_input()
                model["model_family"] = family
                model["lines"][0]["line_id"] = role
                model["lines"][0]["metric_role"] = role
                model["required_outputs"] = [role]
                validate_financial_artifact(run_financial_model(forecast_result(), model))

    def test_custom_family_requires_explicit_rationale(self) -> None:
        model = model_input()
        model["model_family"] = "custom"
        model["lines"][0]["metric_role"] = "custom_operating_result"
        with self.assertRaisesRegex(InvestmentArtifactError, "requires rationale"):
            run_financial_model(forecast_result(), model)
        model["model_family_rationale"] = "Special statutory reporting model"
        validate_financial_artifact(run_financial_model(forecast_result(), model))


if __name__ == "__main__":
    unittest.main()
