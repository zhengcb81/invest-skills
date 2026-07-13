from __future__ import annotations

import sys
import unittest
from pathlib import Path


SUITE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SUITE / "invest-core" / "scripts"))

from invest_contracts import InvestmentArtifactError, canonical_sha256, finalize_draft, text_sha256  # noqa: E402


def identity() -> dict:
    return {
        "company_name": "Test Co", "as_of_date": "2026-07-12", "currency": "USD",
        "unit": "million", "fiscal_year_end": "12-31", "base_year": 2025,
        "forecast_years": [2026, 2027],
    }


def draft() -> dict:
    excerpt = "The regulator concluded its review and imposed a monetary sanction."
    return {
        "module": "management", "identity": identity(),
        "scope": {"type": "company", "name": "Test Co"},
        "sources": [{
            "source_id": "regulator", "source_type": "regulatory_release",
            "title": "Enforcement outcome", "publisher": "Regulator",
            "url": "https://www.sec.gov/Archives/enforcement.htm", "published_date": "2026-01-10",
            "page_or_section": "Outcome", "accessed_date": "2026-07-01",
        }],
        "evidence_claims": [{
            "claim_id": "claim_event", "source_id": "regulator",
            "target_type": "qualitative_assertion", "target_id": "event_1",
            "support_type": "qualitative_support", "locator": "Outcome paragraph 2",
            "excerpt": excerpt, "excerpt_sha256": text_sha256(excerpt),
            "content_sha256": canonical_sha256({"source": "regulator"}),
            "verified_by": "unit-test", "verified_date": "2026-07-01",
            "verification_status": "opened_and_checked",
        }],
        "data": {
            "qualitative_schema_version": "2.0",
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
            "disconfirming_fact_ids": [], "data_gaps": ["No independent remediation audit was located"],
        },
        "limitations": ["Synthetic fixture"],
    }


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


if __name__ == "__main__":
    unittest.main()
