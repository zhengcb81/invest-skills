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

from financial_model import run_financial_model  # noqa: E402
from invest_contracts import InvestmentArtifactError, revenue_runtime, validate_artifact  # noqa: E402
from sotp_model import run_sotp  # noqa: E402
from valuation_model import run_valuation  # noqa: E402


def forecast_result() -> dict:
    core, _, rf_dir = revenue_runtime()
    sys.path.insert(0, str(rf_dir / "tests"))
    from test_management_targets import add_target
    from test_recognition_bridge import forecast_document
    return core.run_forecast(add_target(forecast_document()))


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
            "scope": {"type": "segment", "name": segment["name"]}, "model_family": "operating_company",
            "parameters": params,
            "lines": [{"line_id": "net_income", "formula": "x0*x1", "input_refs": ["revenue", "parameter:margin_{scenario}_{year}"]}],
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
            "methods": [{"method_id": "pe", "type": "multiple", "metric": "net_income", "value_basis": "equity", "multiple_parameter_template": "pe_{scenario}"}],
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
        selections[name] = "pe"
        params.append({
            "parameter_id": parameter_id, "kind": "analyst_assumption", "value": 1.0,
            "unit": "ratio", "period": artifact["identity"]["as_of_date"], "definition": f"ownership of {name}",
            "dimension": "ratio", "time_basis": "point_in_time", "scenario": "shared",
            "source_ids": [], "claim_ids": [], "rationale": "Synthetic",
        })
    return {
        "segment_selections": selections, "ownership_parameter_templates": ownership,
        "company_adjustments": [], "parameters": params, "sources": [], "evidence_claims": [], "limitations": ["Synthetic"],
    }


class SotpModelTests(unittest.TestCase):
    def test_sotp_aggregates_owned_segment_values(self) -> None:
        valuations = valuation_artifacts()
        artifact = run_sotp(valuations, sotp_input(valuations))
        validate_artifact(artifact)
        base = artifact["data"]["scenario_sotp"]["base"]
        self.assertAlmostEqual(base["sotp_equity_value"], sum(item["owned_equity_value"] for item in base["parts"]))
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


if __name__ == "__main__":
    unittest.main()
