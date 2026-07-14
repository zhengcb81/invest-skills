from __future__ import annotations

import sys
import unittest
from pathlib import Path


SUITE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SUITE / "invest-core" / "scripts"))
sys.path.insert(0, str(SUITE / "tests_support"))

from invest_contracts import (  # noqa: E402
    InvestmentArtifactError, canonical_sha256, finalize_draft,
    revenue_reference, text_sha256,
)
from revenue_fixtures import load_revenue_fixture  # noqa: E402


def forecast() -> dict:
    return load_revenue_fixture("growth")


def draft() -> dict:
    result = forecast()
    excerpt = "Retention remained high because customers integrated the workflow deeply."
    return {
        "module": "moat",
        "identity": {
            "company_name": result["company_name"], "as_of_date": result["as_of_date"],
            "currency": result["currency"], "unit": result["unit"],
            "fiscal_year_end": result["fiscal_year_end"], "base_year": result["base_year"],
            "forecast_years": result["forecast_years"],
        },
        "scope": {"type": "company", "name": result["company_name"]},
        "scenario_set": [], "revenue_forecast_ref": revenue_reference(result),
        "sources": [{
            "source_id": "filing", "source_type": "exchange_filing", "title": "Annual filing",
            "publisher": "Exchange", "url": "https://www.sec.gov/Archives/moat.htm",
            "published_date": "2026-03-01", "accessed_date": "2026-07-01", "page_or_section": "Customers",
        }],
        "evidence_claims": [{
            "claim_id": "claim_retention", "source_id": "filing",
            "target_type": "qualitative_assertion", "target_id": "retention_fact",
            "support_type": "qualitative_support", "locator": "Customers, paragraph 4",
            "excerpt": excerpt, "excerpt_sha256": text_sha256(excerpt),
            "content_sha256": canonical_sha256({"source": "filing"}),
            "verified_by": "unit-test", "verified_date": "2026-07-01",
            "verification_status": "opened_and_checked",
        }],
        "data": {
            "qualitative_schema_version": "2.1",
            "facts": [{
                "fact_id": "retention_fact", "fact_type": "customer_behavior",
                "statement": "Customers showed high retention after workflow integration.",
                "event_date": "2026-03-01", "claim_ids": ["claim_retention"],
            }],
            "driver_registry": {
                "growth_driver_summary_sha256": revenue_reference(result)["growth_driver_summary_sha256"],
                "growth_driver_ids": ["fixture_driver_Segment_A"], "financial_line_ids": [],
            },
            "mechanisms": [{
                "mechanism_id": "switching_cost", "mechanism_type": "switching_cost",
                "business_scope": "Core product", "unit_of_competition": "Customer workflow",
                "causal_chain": "Integration increases migration effort and reduces churn.",
                "customer_consequence": "Replacement requires retraining and data migration.",
                "status": "observed", "fact_ids": ["retention_fact"], "contrary_fact_ids": [],
                "growth_driver_ids": ["fixture_driver_Segment_A"], "financial_line_ids": [],
                "durability_assumption": {"horizon": "Three years", "rationale": "Workflow depth changes gradually"},
                "erosion_events": ["Open standard lowers migration cost"],
                "leading_indicators": ["Cohort retention"], "falsifiers": ["Retention falls below peer median"],
            }],
            "disconfirming_fact_ids": [], "data_gaps": ["No customer-level migration-cost survey"],
        },
        "limitations": ["Synthetic fixture"],
    }


class MoatContractTests(unittest.TestCase):
    def test_mechanism_with_lineage_and_falsifier_finalizes(self) -> None:
        artifact = finalize_draft(draft())
        self.assertEqual(artifact["module"], "moat")

    def test_unregistered_driver_mapping_is_rejected(self) -> None:
        value = draft()
        value["data"]["mechanisms"][0]["growth_driver_ids"] = ["invented_driver"]
        with self.assertRaisesRegex(InvestmentArtifactError, "unknown moat growth driver"):
            finalize_draft(value)

    def test_driver_registry_cannot_invent_growth_drivers(self) -> None:
        value = draft()
        value["data"]["driver_registry"]["growth_driver_ids"] = ["invented_driver"]
        with self.assertRaisesRegex(InvestmentArtifactError, "registry contains unknown"):
            finalize_draft(value)

    def test_falsifier_is_mandatory(self) -> None:
        value = draft()
        value["data"]["mechanisms"][0]["falsifiers"] = []
        with self.assertRaisesRegex(InvestmentArtifactError, "falsifiers must not be empty"):
            finalize_draft(value)


if __name__ == "__main__":
    unittest.main()
