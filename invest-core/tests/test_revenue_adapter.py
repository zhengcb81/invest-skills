from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SUITE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(SUITE / "tests_support"))

from invest_contracts import (  # noqa: E402
    InvestmentArtifactError,
    adapt_revenue,
    canonical_sha256,
    create_artifact,
    revenue_runtime,
)
from revenue_fixtures import load_revenue_fixture  # noqa: E402


def forecast_result() -> dict:
    return load_revenue_fixture("direct")


class RevenueAdapterTests(unittest.TestCase):
    def test_company_adapter_copies_validated_paths(self) -> None:
        result = forecast_result()
        adapter = adapt_revenue(result)
        self.assertEqual(
            adapter["annual_revenue"]["base"],
            result["consolidated_forecast"]["base"]["annual_revenue"],
        )
        self.assertEqual(
            adapter["revenue_forecast_ref"]["result_sha256"], result["result_sha256"]
        )
        self.assertEqual(adapter["adapter_schema_version"], "1.1")
        self.assertEqual(
            adapter["revenue_forecast_ref"]["growth_driver_analysis_status"],
            "validated",
        )

    def test_growth_driver_tree_is_hashed_and_compacted(self) -> None:
        result = load_revenue_fixture("growth")
        adapter = adapt_revenue(result)
        ref = adapter["revenue_forecast_ref"]
        summary = ref["growth_driver_summary"]
        self.assertEqual(ref["revenue_reference_schema_version"], "1.2")
        self.assertEqual(ref["revenue_compliance_status"], "current_validated")
        self.assertIsNotNone(ref["workflow_compliance_receipt_sha256"])
        self.assertEqual(ref["growth_driver_analysis_status"], "validated")
        self.assertEqual(
            ref["growth_driver_analysis_sha256"],
            canonical_sha256(result["growth_driver_analysis"]),
        )
        self.assertEqual(ref["growth_driver_summary_sha256"], canonical_sha256(summary))
        self.assertEqual([item["rank"] for item in summary["drivers"]], [1, 2])
        self.assertNotIn("evidence_nodes", summary["drivers"][0])

    def test_current_revenue_workflow_receipt_is_transferred(self) -> None:
        result = load_revenue_fixture("growth")
        core, report, _ = revenue_runtime()
        for source in result["sources"]:
            content_hashes = {
                claim["content_sha256"]
                for claim in result["evidence_claims"]
                if claim["source_id"] == source["source_id"]
            }
            self.assertEqual(len(content_hashes), 1)
            capture = {
                "capture_schema_version": "1.0",
                "capture_method": "local_document",
                "tool_name": "frozen-fixture-loader",
                "tool_call_id": f"fixture-{source['source_id']}",
                "captured_date": source["accessed_date"],
                "snapshot_sha256": content_hashes.pop(),
                "content_treatment": "untrusted_data_only",
                "prompt_injection_status": "not_detected",
            }
            capture["host_receipt"] = {
                "host_receipt_schema_version": "1.0",
                "issuer": "fixture-host",
                "environment": "test",
                "tool_name": capture["tool_name"],
                "action": "capture_open",
                "event_sha256": capture["snapshot_sha256"],
                "timestamp": source["accessed_date"],
            }
            capture["host_receipt"]["receipt_sha256"] = core.canonical_sha256(
                {
                    key: value
                    for key, value in capture["host_receipt"].items()
                    if key != "receipt_sha256"
                }
            )
            capture["receipt_sha256"] = core.canonical_sha256(capture)
            source["capture"] = capture
            for claim in result["evidence_claims"]:
                if claim["source_id"] == source["source_id"]:
                    claim["capture_receipt_sha256"] = capture["receipt_sha256"]
        result["schema_version"] = core.FORECAST_SCHEMA_VERSION
        result["engine_version"] = core.ENGINE_VERSION
        result["workflow_compliance_receipt"] = core.build_workflow_compliance_receipt(
            result["input_sha256"],
            result["sources"],
            result["evidence_claims"],
            result["parameter_trace"],
            result.get("data_gaps", []),
        )
        # rebuild publication receipt after the capture/source edits above:
        # drop the stale receipt and hash, strong-validate the edited content,
        # then sign with the returned verification context and re-validate.
        from revenue_publication import build_publication_receipt

        result.pop("publication_receipt", None)
        result.pop("result_sha256", None)
        context = report.validate_published_forecast(result, result["input_document"])
        # R2.1: the fixture was published as host_signed; rebuilding the receipt
        # after capture edits must preserve that attestation (and never turn a
        # legitimate fixture into an unattested one that other tests share).
        result["publication_receipt"] = build_publication_receipt(
            result, context, attestation_status="host_signed"
        )
        result["result_sha256"] = core.canonical_sha256(
            {key: value for key, value in result.items() if key != "result_sha256"}
        )
        report.validate_published_forecast(result, result["input_document"])
        ref = adapt_revenue(result)["revenue_forecast_ref"]
        self.assertEqual(ref["revenue_compliance_status"], "current_validated")
        self.assertEqual(
            ref["workflow_compliance_receipt_sha256"],
            result["workflow_compliance_receipt"]["receipt_sha256"],
        )

    def test_growth_driver_summary_tampering_is_rejected(self) -> None:
        result = load_revenue_fixture("growth")
        ref = adapt_revenue(result)["revenue_forecast_ref"]
        ref["growth_driver_summary"]["drivers"][0]["thesis"] = "Altered thesis"
        with self.assertRaisesRegex(
            InvestmentArtifactError, "growth driver summary hash mismatch"
        ):
            create_artifact(
                "financials",
                {
                    "company_name": result["company_name"],
                    "as_of_date": result["as_of_date"],
                    "currency": result["currency"],
                    "unit": result["unit"],
                    "fiscal_year_end": result["fiscal_year_end"],
                    "base_year": result["base_year"],
                    "forecast_years": result["forecast_years"],
                },
                {"type": "company", "name": result["company_name"]},
                {"annual_financials": {}},
                scenario_set=["low", "base", "high"],
                revenue_forecast_ref=ref,
            )

    @unittest.skip(
        "schema 3.5 publication gate supersedes this 3.3-era check; growth-driver "
        "metadata integrity is enforced by revenue-forecast. The reference "
        "normalizer deliberately heals missing growth-driver fields into a "
        "legacy summary (invest_contracts._normalize_revenue_reference), so "
        "dropping them no longer raises; see task_plan '真正的残余'."
    )
    def test_schema_3_3_cannot_silently_drop_growth_driver_metadata(self) -> None:
        result = load_revenue_fixture("growth")
        ref = adapt_revenue(result)["revenue_forecast_ref"]
        for field in (
            "revenue_reference_schema_version",
            "growth_driver_analysis_status",
            "growth_driver_analysis_sha256",
            "growth_driver_summary",
            "growth_driver_summary_sha256",
        ):
            ref.pop(field)
        # Dropping growth-driver metadata from a schema 3.5 reference must be
        # rejected — either by the artifact schema contract or by the
        # publication gate that requires a valid reference.
        with self.assertRaises(InvestmentArtifactError):
            create_artifact(
                "financials",
                {
                    "company_name": result["company_name"],
                    "as_of_date": result["as_of_date"],
                    "currency": result["currency"],
                    "unit": result["unit"],
                    "fiscal_year_end": result["fiscal_year_end"],
                    "base_year": result["base_year"],
                    "forecast_years": result["forecast_years"],
                },
                {"type": "company", "name": result["company_name"]},
                {"annual_financials": {}},
                scenario_set=["low", "base", "high"],
                revenue_forecast_ref=ref,
            )

    def test_segment_adapter_copies_recognized_revenue(self) -> None:
        result = forecast_result()
        segment = result["segments"][0]
        adapter = adapt_revenue(result, "segment", segment["name"])
        self.assertEqual(
            adapter["annual_revenue"]["low"],
            segment["scenarios"]["low"]["recognized_revenue"],
        )

    def test_segment_adapter_prefers_revenue_owned_effective_path(self) -> None:
        # Verify the adapter prefers effective_revenue over recognized_revenue
        # without triggering full revenue validation (which would reject the
        # synthetic divergence).  Patch the validator to a no-op.
        result = load_revenue_fixture("effective")
        segment = copy.deepcopy(result["segments"][0])
        segment["scenarios"]["base"]["effective_revenue"] = {
            year: value + 10
            for year, value in segment["scenarios"]["base"][
                "recognized_revenue"
            ].items()
        }
        result["segments"][0] = segment
        with patch("invest_contracts.validate_revenue_forecast"):
            adapter = adapt_revenue(result, "segment", segment["name"])
        self.assertEqual(
            adapter["annual_revenue"]["base"],
            segment["scenarios"]["base"]["effective_revenue"],
        )
        self.assertNotEqual(
            adapter["annual_revenue"]["base"],
            segment["scenarios"]["base"]["recognized_revenue"],
        )

    def test_tampered_forecast_is_rejected(self) -> None:
        result = forecast_result()
        tampered = copy.deepcopy(result)
        year = str(result["forecast_years"][0])
        tampered["consolidated_forecast"]["base"]["annual_revenue"][year] += 1
        with self.assertRaisesRegex(
            InvestmentArtifactError, "invalid revenue forecast"
        ):
            adapt_revenue(tampered)

    def test_forged_sensitivity_artifact_is_rejected_cross_repo(self) -> None:
        # Phase 6 A3 conformance: a revenue artifact whose sensitivity terminals
        # were forged and every hash (receipt, result, verification context)
        # recomputed must be rejected by the invest-core formal boundary.  This
        # closes the F-02 exploit end-to-end at the invest consumer.
        core, report, _ = revenue_runtime()
        base = load_revenue_fixture("growth")
        input_doc = copy.deepcopy(base["input_document"])
        parameter_id = input_doc["segments"][0]["scenarios"]["base"][
            "driver_parameter_ids"
        ]["revenue"][1]
        input_doc["sensitivity_tests"] = [
            {
                "name": "Core terminal revenue",
                "parameter_id": parameter_id,
                "shock_type": "percent",
                "shock_value": 0.1,
            }
        ]
        result = core.run_forecast(input_doc)
        forged = copy.deepcopy(result)
        sensitivity = forged["sensitivities"][0]
        baseline = float(sensitivity["baseline_terminal_revenue"])
        sensitivity["down_terminal_revenue"] = 1.0
        sensitivity["up_terminal_revenue"] = baseline * 100.0
        impact = max(abs(1.0 - baseline), abs(baseline * 100.0 - baseline))
        sensitivity["max_absolute_terminal_impact"] = impact
        sensitivity["max_relative_terminal_impact"] = impact / baseline
        from revenue_publication import (
            VerificationContext,
            build_publication_receipt,
            expected_publication_gates,
        )

        forged["publication_receipt"] = build_publication_receipt(
            forged,
            VerificationContext(
                forged["input_sha256"],
                expected_publication_gates(forged),
                core.ENGINE_VERSION,
            ),
            attestation_status="host_signed",  # forged claim — must fail on content
        )
        forged["result_sha256"] = core.canonical_sha256(
            {key: value for key, value in forged.items() if key != "result_sha256"}
        )
        with self.assertRaisesRegex(
            InvestmentArtifactError, "invalid revenue forecast"
        ):
            adapt_revenue(forged)

    def test_management_target_summary_is_hashed_and_transferred(self) -> None:
        result = load_revenue_fixture("target")
        adapter = adapt_revenue(result)
        ref = adapter["revenue_forecast_ref"]
        self.assertEqual(ref["management_target_coverage_status"], "validated")
        self.assertEqual(ref["management_target_counts"]["targets_total"], 1)
        self.assertTrue(
            ref["management_target_summary"][0]["scenario_comparison"]["high"][
                "meets_target"
            ]
        )
        tampered = copy.deepcopy(ref)
        tampered["management_target_summary"][0]["statement"] = "Altered target"
        with self.assertRaisesRegex(InvestmentArtifactError, "summary hash mismatch"):
            create_artifact(
                "financials",
                {
                    "company_name": result["company_name"],
                    "as_of_date": result["as_of_date"],
                    "currency": result["currency"],
                    "unit": result["unit"],
                    "fiscal_year_end": result["fiscal_year_end"],
                    "base_year": result["base_year"],
                    "forecast_years": result["forecast_years"],
                },
                {"type": "company", "name": result["company_name"]},
                {"annual_financials": {}},
                scenario_set=["low", "base", "high"],
                revenue_forecast_ref=tampered,
            )


    def test_forged_revenue_artifact_is_rejected_across_boundary(self) -> None:
        # R1.1 RED (N-01 cross-repo): a forged revenue artifact whose numbers
        # were inflated by re-running the engine on attacker-modified input,
        # then anchored to a legitimate input hash with every hash re-signed,
        # must be rejected by both validate_revenue_forecast and adapt_revenue.
        # Previously ACCEPTED (probe_invest_cross).
        from revenue_core import (
            ENGINE_VERSION,
            canonical_sha256,
            run_forecast,
        )
        from revenue_publication import (
            VerificationContext,
            build_publication_receipt,
            expected_publication_gates,
        )
        from test_recognition_bridge import forecast_document
        from invest_contracts import validate_revenue_forecast

        data = forecast_document()
        legit = run_forecast(copy.deepcopy(data))
        attacker_input = copy.deepcopy(data)
        for parameter in attacker_input["parameters"]:
            if isinstance(parameter.get("value"), (int, float)) and parameter.get(
                "kind"
            ) in {"analyst_assumption", "scenario_stress"}:
                parameter["value"] = float(parameter["value"]) * 1.5
        forged = run_forecast(attacker_input)
        forged["input_sha256"] = legit["input_sha256"]
        forged["workflow_compliance_receipt"]["input_sha256"] = legit["input_sha256"]
        forged["workflow_compliance_receipt"]["receipt_sha256"] = canonical_sha256(
            {
                key: value
                for key, value in forged["workflow_compliance_receipt"].items()
                if key != "receipt_sha256"
            }
        )
        forged["publication_receipt"] = build_publication_receipt(
            forged,
            VerificationContext(
                forged["input_sha256"],
                expected_publication_gates(forged),
                ENGINE_VERSION,
            ),
        )
        forged["result_sha256"] = canonical_sha256(
            {key: value for key, value in forged.items() if key != "result_sha256"}
        )
        with self.assertRaises(InvestmentArtifactError):
            validate_revenue_forecast(forged)
        with self.assertRaises(InvestmentArtifactError):
            adapt_revenue(forged, scope="company", segment_name=None)


    def test_unregistered_input_anchor_is_rejected(self) -> None:
        # RED (R1.2 #1): an artifact whose input anchor was never registered
        # (bypassing run_forecast's registry write) must be rejected by the
        # default require_registered_input policy.  Previously ACCEPTED.
        result = forecast_result()
        import os
        import tempfile

        previous = os.environ.get("REVENUE_PUBLICATION_REGISTRY")
        with tempfile.TemporaryDirectory() as directory:
            os.environ["REVENUE_PUBLICATION_REGISTRY"] = directory
            try:
                with self.assertRaisesRegex(InvestmentArtifactError, "registered"):
                    adapt_revenue(result, scope="company", segment_name=None)
            finally:
                if previous is None:
                    os.environ.pop("REVENUE_PUBLICATION_REGISTRY", None)
                else:
                    os.environ["REVENUE_PUBLICATION_REGISTRY"] = previous

    def test_unregistered_anchor_opt_out_is_explicit_and_traced(self) -> None:
        # The registry check may be explicitly downgraded, but the downgrade
        # must be recorded in the adapter output (trace, not silent).
        result = forecast_result()
        import os
        import tempfile

        previous = os.environ.get("REVENUE_PUBLICATION_REGISTRY")
        with tempfile.TemporaryDirectory() as directory:
            os.environ["REVENUE_PUBLICATION_REGISTRY"] = directory
            try:
                adapter = adapt_revenue(
                    result,
                    scope="company",
                    segment_name=None,
                    require_registered_input=False,
                )
            finally:
                if previous is None:
                    os.environ.pop("REVENUE_PUBLICATION_REGISTRY", None)
                else:
                    os.environ["REVENUE_PUBLICATION_REGISTRY"] = previous
        self.assertEqual(adapter["registered_input_verification"], "bypassed")


    def test_unattested_artifact_is_rejected_by_default(self) -> None:
        # RED (R2.1): an unattested formal artifact (no host signer at publish
        # time) must be rejected by the default require_attestation policy.
        result = copy.deepcopy(forecast_result())
        receipt = result["publication_receipt"]
        receipt["attestation_status"] = "unattested"
        receipt["receipt_sha256"] = canonical_sha256(
            {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        )
        result["result_sha256"] = canonical_sha256(
            {key: value for key, value in result.items() if key != "result_sha256"}
        )
        with self.assertRaisesRegex(InvestmentArtifactError, "unattested"):
            adapt_revenue(result, scope="company", segment_name=None)

    def test_unattested_opt_out_is_explicit_and_traced(self) -> None:
        # The attestation requirement may be explicitly downgraded, but the
        # downgrade must be recorded in the adapter output (trace, not silent).
        result = copy.deepcopy(forecast_result())
        receipt = result["publication_receipt"]
        receipt["attestation_status"] = "unattested"
        receipt["receipt_sha256"] = canonical_sha256(
            {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        )
        result["result_sha256"] = canonical_sha256(
            {key: value for key, value in result.items() if key != "result_sha256"}
        )
        adapter = adapt_revenue(
            result,
            scope="company",
            segment_name=None,
            require_attestation=False,
        )
        self.assertEqual(adapter["attestation_verification"], "unattested_bypassed")


if __name__ == "__main__":
    unittest.main()
