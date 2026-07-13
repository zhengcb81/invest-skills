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
sys.path.insert(0, str(SUITE / "tests_support"))

from financial_model import run_financial_model  # noqa: E402
from invest_contracts import InvestmentArtifactError, canonical_sha256, validate_artifact  # noqa: E402
from revenue_fixtures import load_revenue_fixture  # noqa: E402
from sotp_model import run_sotp, validate_sotp_artifact  # noqa: E402
from valuation_model import run_valuation  # noqa: E402


def forecast_result() -> dict:
    return load_revenue_fixture("target")


def valuation_artifacts() -> list[dict]:
    forecast = forecast_result()
    artifacts = []
    for segment in forecast["segments"]:
        params = []
        for scenario in ("low", "base", "high"):
            for year in forecast["forecast_years"]:
                params.append({
                    "parameter_id": f"margin_{scenario}_{year}", "kind": "analyst_assumption", "value": 0.1,
                    "unit": "ratio", "period": f"FY{year}", "definition": "profit margin", "dimension": "ratio",
                    "time_basis": "annual", "scenario": scenario, "source_ids": [], "claim_ids": [], "rationale": "Synthetic",
                })
        financial = run_financial_model(forecast, {
            "financial_model_schema_version": "2.0",
            "scope": {"type": "segment", "name": segment["name"]}, "model_family": "operating_company",
            "parameters": params,
            "lines": [{
                "line_id": "net_income", "formula": "x0*x1",
                "input_refs": ["revenue", "parameter:margin_{scenario}_{year}"],
                "input_dimensions": ["revenue", "ratio"], "output_dimension": "profit",
                "time_basis": "annual", "metric_role": "net_income",
                "dimension_rule": "monetary_times_rate",
            }],
            "required_outputs": ["net_income"], "sources": [], "evidence_claims": [], "limitations": ["Synthetic"],
        })
        valuation_params = []
        for scenario in ("low", "base", "high"):
            valuation_params.append({
                "parameter_id": f"pe_{scenario}", "kind": "analyst_assumption", "value": 10,
                "unit": "multiple", "period": forecast["as_of_date"], "definition": "PE multiple", "dimension": "multiple",
                "time_basis": "point_in_time", "scenario": scenario, "source_ids": [], "claim_ids": [], "rationale": "Synthetic",
            })
        artifacts.append(run_valuation(financial, {
            "valuation_model_schema_version": "2.0",
            "methods": [{
                "method_id": "pe", "type": "multiple", "multiple_kind": "pe",
                "metric": "net_income", "metric_period": f"FY{forecast['forecast_years'][-1]}",
                "value_basis": "equity", "valuation_timing": "current",
                "multiple_parameter_template": "pe_{scenario}",
            }],
            "equity_adjustments": [], "parameters": valuation_params, "sources": [], "evidence_claims": [], "limitations": ["Synthetic"],
        }))
    return artifacts


def sotp_input(valuations: list[dict]) -> dict:
    params = []
    ownership = {}
    selections = {}
    for artifact in valuations:
        name = artifact["scope"]["name"]
        parameter_id = "ownership_" + name.replace(" ", "_")
        ownership[name] = parameter_id
        selections[name] = {"selection_type": "method", "method_id": "pe", "selected_value_basis": "equity"}
        params.append({
            "parameter_id": parameter_id, "kind": "analyst_assumption", "value": 1.0,
            "unit": "ratio", "period": artifact["identity"]["as_of_date"], "definition": f"ownership of {name}",
            "dimension": "ratio", "time_basis": "point_in_time", "scenario": "shared",
            "source_ids": [], "claim_ids": [], "rationale": "Synthetic",
        })
    return {
        "sotp_model_schema_version": "2.0", "aggregation_basis": "equity",
        "segment_selections": selections, "ownership_parameter_templates": ownership,
        "company_bridge": {
            "stage": "equity_level", "completeness_status": "complete",
            "rationale": "No additional company-level adjustments in synthetic fixture", "adjustments": [],
        },
        "parameters": params, "sources": [], "evidence_claims": [], "limitations": ["Synthetic"],
    }


class SotpModelTests(unittest.TestCase):
    def test_sotp_aggregates_owned_segment_values(self) -> None:
        valuations = valuation_artifacts()
        artifact = run_sotp(valuations, sotp_input(valuations))
        validate_artifact(artifact)
        validate_sotp_artifact(artifact)
        base = artifact["data"]["scenario_sotp"]["base"]
        self.assertAlmostEqual(base["sotp_equity_value_current"], sum(item["owned_value_current"] for item in base["parts"]))
        self.assertEqual(artifact["data"]["management_target_coverage_status"], "validated")
        self.assertEqual(artifact["data"]["management_target_summary"][0]["target_id"], "five_year_revenue_goal")
        self.assertTrue(artifact["data"]["management_target_summary"][0]["scenario_comparison"]["high"]["meets_target"])

    def test_duplicate_segment_is_rejected(self) -> None:
        valuations = valuation_artifacts()
        with self.assertRaisesRegex(InvestmentArtifactError, "duplicate SOTP segment"):
            run_sotp([valuations[0], valuations[0]], sotp_input([valuations[0]]))

    def test_missing_ownership_is_rejected(self) -> None:
        valuations = valuation_artifacts()
        model = sotp_input(valuations)
        model["ownership_parameter_templates"].pop(next(iter(model["ownership_parameter_templates"])))
        with self.assertRaisesRegex(InvestmentArtifactError, "cover each segment"):
            run_sotp(valuations, model)

    def test_mixed_enterprise_and_equity_selections_are_rejected(self) -> None:
        valuations = valuation_artifacts()
        model = sotp_input(valuations)
        first = next(iter(model["segment_selections"]))
        model["segment_selections"][first]["selected_value_basis"] = "enterprise"
        with self.assertRaisesRegex(InvestmentArtifactError, "selection basis mismatch"):
            run_sotp(valuations, model)

    def test_company_bridge_requires_monetary_balance(self) -> None:
        valuations = valuation_artifacts()
        model = sotp_input(valuations)
        model["company_bridge"]["adjustments"] = [{"name": "cash", "sign": 1, "parameter_id_template": "cash_{scenario}"}]
        for scenario in ("low", "base", "high"):
            model["parameters"].append({
                "parameter_id": f"cash_{scenario}", "kind": "analyst_assumption", "value": 10.0,
                "unit": "currency", "period": valuations[0]["identity"]["as_of_date"], "definition": "cash",
                "dimension": "asset", "time_basis": "point_in_time", "scenario": scenario,
                "currency": valuations[0]["identity"]["currency"], "scale": valuations[0]["identity"]["unit"],
                "source_ids": [], "claim_ids": [], "rationale": "Synthetic",
            })
        with self.assertRaisesRegex(InvestmentArtifactError, "parameter dimension mismatch"):
            run_sotp(valuations, model)

    def test_semantic_validator_recomputes_sotp(self) -> None:
        valuations = valuation_artifacts()
        artifact = run_sotp(valuations, sotp_input(valuations))
        artifact["data"]["scenario_sotp"]["base"]["sotp_equity_value_current"] += 1
        body = {key: value for key, value in artifact.items() if key not in {"artifact_id", "artifact_sha256"}}
        artifact["artifact_id"] = canonical_sha256(body)
        artifact["artifact_sha256"] = canonical_sha256({key: value for key, value in artifact.items() if key != "artifact_sha256"})
        with self.assertRaisesRegex(InvestmentArtifactError, "semantic recomputation"):
            validate_sotp_artifact(artifact)


if __name__ == "__main__":
    unittest.main()
