from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SUITE = Path(__file__).resolve().parents[2]
for path in (
    SUITE / "invest-core" / "scripts",
    SUITE / "invest-financials" / "scripts",
    SUITE / "invest-valuation" / "scripts",
    SUITE / "invest-sotp" / "scripts",
    Path(__file__).resolve().parents[1] / "scripts",
):
    sys.path.insert(0, str(path))
sys.path.insert(0, str(SUITE / "tests_support"))

from company_orchestrator import run_company, validate_execution, write_execution  # noqa: E402
from invest_contracts import InvestmentArtifactError, finalize_draft, validate_artifact  # noqa: E402
from revenue_fixtures import load_revenue_fixture  # noqa: E402


def forecast_result() -> dict:
    return load_revenue_fixture("recognition")


def heterogeneous_forecast_result() -> dict:
    return load_revenue_fixture("heterogeneous")
def manifest_for(forecast: dict) -> dict:
    identity = {
        key: forecast[key]
        for key in ("company_name", "as_of_date", "currency", "unit", "fiscal_year_end", "base_year", "forecast_years")
    }
    segments = []
    selections = {}
    ownership_templates = {}
    sotp_parameters = []
    for index, segment in enumerate(forecast["segments"], start=1):
        name = segment["name"]
        financial_parameters = []
        for scenario, margin in (("low", 0.08), ("base", 0.10), ("high", 0.12)):
            for year in forecast["forecast_years"]:
                financial_parameters.append({
                    "parameter_id": f"margin_{index}_{scenario}_{year}",
                    "kind": "analyst_assumption",
                    "value": margin,
                    "unit": "ratio",
                    "period": f"FY{year}",
                    "definition": f"Segment {index} net margin",
                    "dimension": "ratio",
                    "time_basis": "annual",
                    "scenario": scenario,
                    "source_ids": [],
                    "claim_ids": [],
                    "rationale": "Synthetic orchestrator test.",
                })
        valuation_parameters = [{
            "parameter_id": f"pe_{index}_{scenario}",
            "kind": "analyst_assumption",
            "value": multiple,
            "unit": "multiple",
            "period": forecast["as_of_date"],
            "definition": f"Segment {index} PE multiple",
            "dimension": "multiple",
            "time_basis": "point_in_time",
            "scenario": scenario,
            "source_ids": [],
            "claim_ids": [],
            "rationale": "Synthetic orchestrator test.",
        } for scenario, multiple in (("low", 8), ("base", 10), ("high", 12))]
        segments.append({
            "name": name,
            "financial_model": {
                "financial_model_schema_version": "2.0",
                "scope": {"type": "segment", "name": name},
                "model_family": "operating_company",
                "parameters": financial_parameters,
                "lines": [{
                    "line_id": "net_income",
                    "formula": "x0*x1",
                    "input_refs": ["revenue", f"parameter:margin_{index}_{{scenario}}_{{year}}"],
                    "input_dimensions": ["revenue", "ratio"],
                    "output_dimension": "profit", "time_basis": "annual",
                    "metric_role": "net_income", "dimension_rule": "monetary_times_rate",
                }],
                "required_outputs": ["net_income"],
                "sources": [],
                "evidence_claims": [],
                "limitations": ["Synthetic fixture."],
            },
            "valuation_model": {
                "valuation_model_schema_version": "2.0",
                "methods": [{
                    "method_id": "pe",
                    "type": "multiple",
                    "multiple_kind": "pe",
                    "metric": "net_income",
                    "metric_period": f"FY{forecast['forecast_years'][-1]}",
                    "value_basis": "equity",
                    "valuation_timing": "current",
                    "multiple_parameter_template": f"pe_{index}_{{scenario}}",
                }],
                "equity_adjustments": [],
                "parameters": valuation_parameters,
                "sources": [],
                "evidence_claims": [],
                "limitations": ["Synthetic fixture."],
            },
        })
        selections[name] = {"selection_type": "method", "method_id": "pe", "selected_value_basis": "equity"}
        ownership_id = f"ownership_{index}"
        ownership_templates[name] = ownership_id
        sotp_parameters.append({
            "parameter_id": ownership_id,
            "kind": "analyst_assumption",
            "value": 1.0,
            "unit": "ratio",
            "period": forecast["as_of_date"],
            "definition": f"Ownership of {name}",
            "dimension": "ratio",
            "time_basis": "point_in_time",
            "scenario": "shared",
            "source_ids": [],
            "claim_ids": [],
            "rationale": "Synthetic fixture.",
        })
    required_scoped = [
        *[
            {"module": module, "scope": {"type": "segment", "name": segment["name"]}}
            for segment in forecast["segments"] for module in ("financials", "valuation")
        ],
        {"module": "sotp", "scope": {"type": "company", "name": forecast["company_name"]}},
    ]
    return {
        "manifest_version": "2.0",
        "identity": identity,
        "scenario_policy": {
            "scenario_set": ["low", "base", "high"], "source": "unit_test_manifest",
            "definitions": {
                "low": "Downside demand and margin assumptions",
                "base": "Central operating assumptions",
                "high": "Upside adoption and monetization assumptions",
            },
        },
        "required_constraint_ids": [],
        "segments": segments,
        "sotp_model": {
            "sotp_model_schema_version": "2.0", "aggregation_basis": "equity",
            "segment_selections": selections,
            "ownership_parameter_templates": ownership_templates,
            "company_bridge": {
                "stage": "equity_level", "completeness_status": "complete",
                "rationale": "All synthetic segment methods already produce equity values", "adjustments": [],
            },
            "parameters": sotp_parameters,
            "sources": [],
            "evidence_claims": [],
            "limitations": ["Synthetic fixture."],
        },
        "bundle_plan": {
            "bundle_plan_schema_version": "2.0",
            "required_modules": ["financials", "valuation", "sotp"],
            "optional_modules": [],
            "required_scoped_artifacts": required_scoped,
            "optional_scoped_artifacts": [],
            "limitations": ["Synthetic orchestrator test."],
        },
        "supplemental_artifacts": [],
    }


class CompanyOrchestratorTests(unittest.TestCase):
    def test_manifest_fans_out_segments_and_builds_sotp_bundle(self) -> None:
        forecast = forecast_result()
        manifest = manifest_for(forecast)

        execution = run_company(manifest, forecast)

        self.assertEqual(len(execution["financials"]), len(forecast["segments"]))
        self.assertEqual(len(execution["valuations"]), len(forecast["segments"]))
        self.assertEqual(execution["receipt"]["status"], "pass")
        self.assertEqual(execution["bundle"]["data"]["module_counts"], {"financials": 2, "sotp": 1, "valuation": 2})
        self.assertEqual(execution["bundle"]["data"]["manifest_sha256"], execution["receipt"]["manifest_sha256"])
        for artifact in [*execution["financials"], *execution["valuations"], execution["sotp"], execution["bundle"]]:
            validate_artifact(artifact)

    def test_heterogeneous_segments_constraints_and_sotp_run_end_to_end(self) -> None:
        forecast = heterogeneous_forecast_result()
        self.assertEqual(
            [segment["scenarios"]["base"]["model"] for segment in forecast["segments"]],
            ["capacity_utilization", "subscription", "services"],
        )
        manifest = manifest_for(forecast)
        manifest["required_constraint_ids"] = [
            "equipment_subscription_shared_cap", "services_internal_elimination",
        ]

        execution = run_company(manifest, forecast)

        self.assertEqual(execution["bundle"]["data"]["module_counts"], {"financials": 3, "sotp": 1, "valuation": 3})
        self.assertEqual(execution["receipt"]["segment_count"], 3)
        for index, financial in enumerate(execution["financials"]):
            segment = forecast["segments"][index]
            expected = segment["scenarios"]["base"]["effective_revenue"]["2026"]
            self.assertAlmostEqual(financial["data"]["annual_financials"]["base"]["2026"]["revenue"], expected)
        self.assertGreater(execution["sotp"]["data"]["scenario_sotp"]["base"]["sotp_equity_value_current"], 0)

    def test_revenue_hash_drift_is_rejected_before_fan_out(self) -> None:
        forecast = heterogeneous_forecast_result()
        manifest = manifest_for(forecast)
        manifest["required_constraint_ids"] = [
            "equipment_subscription_shared_cap", "services_internal_elimination",
        ]
        forecast["segments"][0]["scenarios"]["base"]["effective_revenue"]["2026"] += 1
        with self.assertRaisesRegex(InvestmentArtifactError, "invalid revenue forecast: segment effective revenue mismatch"):
            run_company(manifest, forecast)

    def test_manifest_constraint_ids_must_match_frozen_forecast(self) -> None:
        forecast = heterogeneous_forecast_result()
        manifest = manifest_for(forecast)
        with self.assertRaisesRegex(InvestmentArtifactError, "required_constraint_ids"):
            run_company(manifest, forecast)

    def test_manifest_must_cover_every_revenue_segment(self) -> None:
        forecast = forecast_result()
        manifest = manifest_for(forecast)
        manifest["segments"].pop()
        with self.assertRaisesRegex(InvestmentArtifactError, "cover every revenue segment"):
            run_company(manifest, forecast)

    def test_manifest_rejects_embedded_secret_fields(self) -> None:
        forecast = forecast_result()
        manifest = manifest_for(forecast)
        manifest["api_key"] = "not-a-real-key"
        with self.assertRaisesRegex(InvestmentArtifactError, "secret-like field"):
            run_company(manifest, forecast)

    def test_execution_output_is_atomic_and_never_overwritten(self) -> None:
        forecast = forecast_result()
        execution = run_company(manifest_for(forecast), forecast)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "analysis"
            write_execution(output, execution)
            self.assertTrue((output / "receipt.json").exists())
            self.assertTrue((output / "bundle.json").exists())
            self.assertTrue((output / "manifest.snapshot.json").exists())
            self.assertTrue((output / "revenue_forecast.snapshot.json").exists())
            self.assertTrue((output / "report.md").exists())
            with self.assertRaisesRegex(InvestmentArtifactError, "already exists"):
                write_execution(output, execution)

    def test_cli_runs_the_complete_graph_with_one_command(self) -> None:
        forecast = forecast_result()
        manifest = manifest_for(forecast)
        script = Path(__file__).resolve().parents[1] / "scripts" / "company_orchestrator.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            forecast_path = root / "forecast.json"
            manifest_path = root / "manifest.json"
            output = root / "analysis"
            forecast_path.write_text(json.dumps(forecast, ensure_ascii=False), encoding="utf-8")
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(script), str(manifest_path), str(forecast_path), "--output-dir", str(output)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads((output / "receipt.json").read_text(encoding="utf-8"))["status"], "pass")
            self.assertTrue((output / "sotp.json").exists())
            self.assertTrue((output / "bundle.json").exists())

    def test_cli_failure_writes_only_a_machine_readable_failure_receipt(self) -> None:
        forecast = forecast_result()
        manifest = manifest_for(forecast)
        manifest["api_key"] = "not-a-real-key"
        script = Path(__file__).resolve().parents[1] / "scripts" / "company_orchestrator.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            forecast_path = root / "forecast.json"
            manifest_path = root / "manifest.json"
            output = root / "analysis"
            forecast_path.write_text(json.dumps(forecast, ensure_ascii=False), encoding="utf-8")
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(script), str(manifest_path), str(forecast_path), "--output-dir", str(output)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(completed.returncode, 1)
            self.assertFalse(output.exists())
            failure = json.loads((root / "analysis.failure.json").read_text(encoding="utf-8"))
            self.assertEqual(failure["status"], "fail")
            self.assertEqual(failure["stage"], "orchestrate")
            self.assertFalse(failure["success_output_created"])

    def test_forecast_input_is_not_mutated(self) -> None:
        forecast = forecast_result()
        frozen = copy.deepcopy(forecast)
        run_company(manifest_for(forecast), forecast)
        self.assertEqual(forecast, frozen)

    def test_declared_supplemental_management_artifact_is_bundled(self) -> None:
        forecast = forecast_result()
        manifest = manifest_for(forecast)
        management = finalize_draft({
            "module": "management", "identity": manifest["identity"],
            "scope": {"type": "company", "name": forecast["company_name"]},
            "data": {
                "qualitative_schema_version": "2.1", "facts": [], "interpretations": [],
                "commitment_assessments": [], "red_flag_interpretation_ids": [],
                "execution_driver_assessments": [], "disconfirming_fact_ids": [],
                "data_gaps": ["Synthetic empty sidecar"],
            },
            "limitations": ["Synthetic"],
        })
        declaration = {
            "module": "management", "scope": management["scope"],
            "artifact_id": management["artifact_id"], "artifact_sha256": management["artifact_sha256"],
            "required": True,
        }
        manifest["supplemental_artifacts"] = [declaration]
        manifest["bundle_plan"]["required_modules"].append("management")
        manifest["bundle_plan"]["required_scoped_artifacts"].append({"module": "management", "scope": management["scope"]})
        execution = run_company(manifest, forecast, [management])
        self.assertEqual(execution["receipt"]["supplemental_count"], 1)
        self.assertEqual(execution["bundle"]["data"]["module_counts"]["management"], 1)

    def test_freeform_report_override_is_rejected(self) -> None:
        forecast = forecast_result()
        execution = run_company(manifest_for(forecast), forecast)
        execution["report_markdown"] += "\nUnvalidated model-written conclusion.\n"
        with self.assertRaisesRegex(InvestmentArtifactError, "validated bundle renderer"):
            validate_execution(execution)

    def test_skipped_state_transition_is_rejected(self) -> None:
        forecast = forecast_result()
        execution = run_company(manifest_for(forecast), forecast)
        execution["receipt"]["state_transitions"].pop()
        with self.assertRaisesRegex(InvestmentArtifactError, "execution receipt mismatch"):
            validate_execution(execution)

    def test_legacy_revenue_is_explicitly_labeled_not_current_compliant(self) -> None:
        forecast = forecast_result()
        execution = run_company(manifest_for(forecast), forecast)
        self.assertEqual(execution["receipt"]["revenue_compliance_status"], "legacy_read_only_validated")
        self.assertIsNone(execution["receipt"]["revenue_workflow_receipt_sha256"])


if __name__ == "__main__":
    unittest.main()
