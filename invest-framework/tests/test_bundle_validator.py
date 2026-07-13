from __future__ import annotations

import sys
import unittest
from pathlib import Path


SUITE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SUITE / "invest-core" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from bundle_validator import render_bundle_markdown, run_bundle, validate_bundle_artifact  # noqa: E402
from invest_contracts import InvestmentArtifactError, SCENARIOS, artifact_reference, canonical_sha256, create_artifact, validate_artifact  # noqa: E402


def identity() -> dict:
    return {
        "company_name": "Test Co", "as_of_date": "2026-07-12", "currency": "USD", "unit": "million",
        "fiscal_year_end": "12-31", "base_year": 2025, "forecast_years": [2026, 2027],
    }


def chain() -> tuple[dict, dict]:
    ref = {"schema_version": "3.0", "engine_version": "3.0.0", "input_sha256": "a" * 64, "result_sha256": "b" * 64}
    def legacy(module: str, data: dict, upstream: list[dict] | None = None) -> dict:
        body = {
            "artifact_schema_version": "1.0", "invest_suite_version": "4.2.0", "module": module,
            "identity": identity(), "scope": {"type": "company", "name": "Test Co"},
            "scenario_set": list(SCENARIOS), "revenue_forecast_ref": ref,
            "upstream_artifacts": [artifact_reference(item) for item in (upstream or [])],
            "sources": [], "parameters": [], "evidence_claims": [], "data": data,
            "limitations": ["Synthetic legacy fixture"],
        }
        artifact = {**body, "artifact_id": canonical_sha256(body)}
        artifact["artifact_sha256"] = canonical_sha256(artifact)
        validate_artifact(artifact)
        return artifact
    financial = legacy("financials", {"annual_financials": {}})
    valuation = legacy("valuation", {"scenario_valuations": {}}, [financial])
    return financial, valuation


def plan() -> dict:
    return {
        "bundle_plan_schema_version": "2.0",
        "required_modules": ["financials", "valuation"], "optional_modules": ["moat"],
        "required_scoped_artifacts": [], "optional_scoped_artifacts": [], "limitations": [],
    }


class BundleValidatorTests(unittest.TestCase):
    def test_valid_dependency_order(self) -> None:
        financial, valuation = chain()
        bundle = run_bundle([valuation, financial], plan())
        validate_artifact(bundle)
        validate_bundle_artifact(bundle)
        order = [item["module"] for item in bundle["data"]["execution_order"]]
        self.assertLess(order.index("financials"), order.index("valuation"))
        self.assertEqual(bundle["data"]["missing_optional_modules"], ["moat"])

    def test_missing_upstream_is_rejected(self) -> None:
        _, valuation = chain()
        with self.assertRaisesRegex(InvestmentArtifactError, "missing upstream"):
            value = plan()
            value["required_modules"] = ["valuation"]
            value["optional_modules"] = []
            run_bundle([valuation], value)

    def test_psychology_is_excluded(self) -> None:
        psychology = create_artifact(
            "psychology", identity(), {"type": "company", "name": "Test Co"}, {"answers": {}}, limitations=["Synthetic"],
        )
        with self.assertRaisesRegex(InvestmentArtifactError, "does not belong"):
            value = plan()
            value["required_modules"] = []
            value["optional_modules"] = []
            run_bundle([psychology], value)

    def test_required_and_optional_modules_must_be_disjoint(self) -> None:
        financial, valuation = chain()
        value = plan()
        value["optional_modules"] = ["valuation"]
        with self.assertRaisesRegex(InvestmentArtifactError, "disjoint"):
            run_bundle([financial, valuation], value)

    def test_bundle_freezes_inputs_and_renders_without_recalculation(self) -> None:
        financial, valuation = chain()
        bundle = run_bundle([financial, valuation], plan())
        self.assertEqual(len(bundle["data"]["artifact_snapshots"]), 2)
        markdown = render_bundle_markdown(bundle)
        self.assertIn("模块与数据血缘", markdown)


if __name__ == "__main__":
    unittest.main()
