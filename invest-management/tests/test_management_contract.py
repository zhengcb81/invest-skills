from __future__ import annotations

import sys
import unittest
from pathlib import Path


SUITE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SUITE / "invest-core" / "scripts"))
sys.path.insert(0, str(SUITE / "tests_support"))

from invest_contracts import InvestmentArtifactError, canonical_sha256, finalize_draft, revenue_reference, text_sha256  # noqa: E402
from revenue_fixtures import load_revenue_fixture  # noqa: E402


def identity() -> dict:
    return {
        "company_name": "Test Co", "as_of_date": "2026-07-12", "currency": "USD",
        "unit": "million", "fiscal_year_end": "12-31", "base_year": 2025,
        "forecast_years": [2026, 2027],
    }


def draft() -> dict:
    excerpt = "The regulator concluded its review and imposed a monetary sanction."
    source = {
        "source_id": "regulator", "source_type": "regulatory_release",
        "title": "Enforcement outcome", "publisher": "Regulator",
        "url": "https://www.sec.gov/Archives/enforcement.htm", "published_date": "2026-01-10",
        "page_or_section": "Outcome", "accessed_date": "2026-07-01",
    }
    capture = {
        "capture_schema_version": "1.0", "capture_method": "browser_open",
        "tool_name": "test-browser", "tool_call_id": "fixture-regulator",
        "captured_date": source["accessed_date"],
        "snapshot_sha256": canonical_sha256({"source": "regulator"}),
        "content_treatment": "untrusted_data_only", "prompt_injection_status": "not_detected",
    }
    capture["receipt_sha256"] = canonical_sha256(capture)
    source["capture"] = capture
    return {
        "module": "management", "identity": identity(),
        "scope": {"type": "company", "name": "Test Co"},
        "sources": [source],
        "evidence_claims": [{
            "claim_id": "claim_event", "source_id": "regulator",
            "target_type": "qualitative_assertion", "target_id": "event_1",
            "support_type": "qualitative_support", "locator": "Outcome paragraph 2",
            "excerpt": excerpt, "excerpt_sha256": text_sha256(excerpt),
            "content_sha256": canonical_sha256({"source": "regulator"}),
            "verified_by": "unit-test", "verified_date": "2026-07-01",
            "verification_status": "opened_and_checked",
            "capture_receipt_sha256": capture["receipt_sha256"],
        }],
        "data": {
            "qualitative_schema_version": "2.1",
            "facts": [{
                "fact_id": "event_1", "fact_type": "integrity_event",
                "statement": "A regulator imposed a sanction after review.",
                "event_date": "2026-01-10", "claim_ids": ["claim_event"],
            }],
            "interpretations": [{
                "interpretation_id": "integrity_risk", "statement": "The event raises disclosure-control questions.",
                "fact_ids": ["event_1"], "contrary_fact_ids": [], "confidence": "medium",
            }],
            "commitment_assessments": [], "red_flag_interpretation_ids": ["integrity_risk"],
            "execution_driver_assessments": [], "disconfirming_fact_ids": [],
            "data_gaps": ["No independent remediation audit was located"],
        },
        "limitations": ["Synthetic fixture"],
    }


def growth_draft() -> dict:
    result = load_revenue_fixture("growth")
    value = draft()
    value["identity"] = {
        "company_name": result["company_name"], "as_of_date": result["as_of_date"],
        "currency": result["currency"], "unit": result["unit"],
        "fiscal_year_end": result["fiscal_year_end"], "base_year": result["base_year"],
        "forecast_years": result["forecast_years"],
    }
    value["scope"] = {"type": "company", "name": result["company_name"]}
    value["revenue_forecast_ref"] = revenue_reference(result)
    return value


class ManagementContractTests(unittest.TestCase):
    def test_checked_fact_and_interpretation_finalize(self) -> None:
        artifact = finalize_draft(draft())
        self.assertEqual(artifact["module"], "management")

    def test_unclaimed_factual_allegation_is_rejected(self) -> None:
        value = draft()
        value["data"]["facts"][0]["claim_ids"] = []
        with self.assertRaisesRegex(InvestmentArtifactError, "claim_ids must not be empty"):
            finalize_draft(value)

    def test_interpretation_cannot_reference_unknown_fact(self) -> None:
        value = draft()
        value["data"]["interpretations"][0]["fact_ids"] = ["invented_fact"]
        with self.assertRaisesRegex(InvestmentArtifactError, "unknown interpretation fact"):
            finalize_draft(value)

    def test_execution_assessment_reuses_revenue_driver_and_checked_fact(self) -> None:
        value = growth_draft()
        value["data"]["execution_driver_assessments"] = [{
            "assessment_id": "execution_1", "growth_driver_ids": ["fixture_driver_Segment_A"],
            "management_target_ids": [], "input_fact_ids": ["event_1"],
            "contrary_fact_ids": [], "status": "on_track",
            "conclusion": "The checked execution fact supports the registered revenue driver.",
        }]
        artifact = finalize_draft(value)
        self.assertEqual(artifact["data"]["execution_driver_assessments"][0]["status"], "on_track")

    def test_execution_assessment_cannot_invent_growth_driver(self) -> None:
        value = growth_draft()
        value["data"]["execution_driver_assessments"] = [{
            "assessment_id": "execution_1", "growth_driver_ids": ["invented_driver"],
            "management_target_ids": [], "input_fact_ids": ["event_1"],
            "contrary_fact_ids": [], "status": "on_track", "conclusion": "Synthetic.",
        }]
        with self.assertRaisesRegex(InvestmentArtifactError, "unknown execution growth driver"):
            finalize_draft(value)


if __name__ == "__main__":
    unittest.main()
