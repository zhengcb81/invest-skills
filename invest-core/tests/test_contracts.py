from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from invest_contracts import (  # noqa: E402
    InvestmentArtifactError,
    canonical_sha256,
    create_artifact,
    finalize_draft,
    text_sha256,
    validate_artifact,
)


def identity() -> dict:
    return {
        "company_name": "Test Co",
        "as_of_date": "2026-07-12",
        "currency": "USD",
        "unit": "million",
        "fiscal_year_end": "12-31",
        "base_year": 2025,
        "forecast_years": [2026, 2027],
    }


def evidence() -> tuple[list[dict], list[dict], list[dict]]:
    source = {
        "source_id": "filing",
        "source_type": "exchange_filing",
        "title": "FY2025 filing",
        "publisher": "Test Exchange",
        "url": "https://www.sec.gov/Archives/test.htm",
        "published_date": "2026-03-01",
        "accessed_date": "2026-07-01",
        "page_or_section": "Income statement",
    }
    parameter = {
        "parameter_id": "net_income_2025",
        "kind": "reported_fact",
        "value": 20,
        "unit": "USD million",
        "period": "FY2025",
        "definition": "reported net income",
        "dimension": "profit",
        "time_basis": "annual",
        "scenario": "shared",
        "currency": "USD",
        "scale": "million",
        "source_ids": ["filing"],
        "claim_ids": ["claim_net_income"],
    }
    excerpt = "Reported net income for fiscal 2025 was USD 20 million."
    claim = {
        "claim_id": "claim_net_income",
        "source_id": "filing",
        "target_type": "parameter",
        "target_id": "net_income_2025",
        "support_type": "exact_value",
        "locator": "Income statement, line 12",
        "excerpt": excerpt,
        "excerpt_sha256": text_sha256(excerpt),
        "content_sha256": canonical_sha256({"page": "income statement"}),
        "verified_by": "unit-test",
        "verified_date": "2026-07-01",
        "verification_status": "opened_and_checked",
        "extracted_value": 20,
        "unit": "USD million",
        "period": "FY2025",
    }
    return [source], [parameter], [claim]


class ContractTests(unittest.TestCase):
    def test_create_and_validate_artifact(self) -> None:
        sources, parameters, claims = evidence()
        artifact = create_artifact(
            "management", identity(), {"type": "company", "name": "Test Co"},
            {"integrity_events": []}, sources=sources, parameters=parameters,
            evidence_claims=claims, limitations=["Synthetic fixture"],
        )
        validate_artifact(artifact)

    def test_mutation_breaks_hash(self) -> None:
        artifact = create_artifact(
            "psychology", identity(), {"type": "company", "name": "Test Co"},
            {"user_answers": {}}, limitations=["User-supplied only"],
        )
        tampered = copy.deepcopy(artifact)
        tampered["data"]["user_answers"]["fomo"] = True
        with self.assertRaisesRegex(InvestmentArtifactError, "artifact_id mismatch"):
            validate_artifact(tampered)

    def test_different_content_has_different_artifact_id(self) -> None:
        left = create_artifact(
            "psychology", identity(), {"type": "company", "name": "Test Co"},
            {"user_answers": {"fomo": False}}, limitations=["Synthetic"],
        )
        right = create_artifact(
            "psychology", identity(), {"type": "company", "name": "Test Co"},
            {"user_answers": {"fomo": True}}, limitations=["Synthetic"],
        )
        self.assertNotEqual(left["artifact_id"], right["artifact_id"])

    def test_fact_requires_exact_claim(self) -> None:
        sources, parameters, _ = evidence()
        parameters[0]["claim_ids"] = []
        with self.assertRaisesRegex(InvestmentArtifactError, "exact-value claim required"):
            create_artifact(
                "management", identity(), {"type": "company", "name": "Test Co"},
                {}, sources=sources, parameters=parameters, evidence_claims=[],
            )

    def test_future_source_is_rejected(self) -> None:
        sources, parameters, claims = evidence()
        sources[0]["published_date"] = "2026-07-13"
        with self.assertRaisesRegex(InvestmentArtifactError, "future information leak"):
            create_artifact(
                "management", identity(), {"type": "company", "name": "Test Co"},
                {}, sources=sources, parameters=parameters, evidence_claims=claims,
            )

    def test_finalize_qualitative_draft(self) -> None:
        artifact = finalize_draft({
            "module": "management", "identity": identity(),
            "scope": {"type": "company", "name": "Test Co"},
            "data": {"governance_events": []}, "limitations": ["Synthetic"],
        })
        validate_artifact(artifact)

    def test_finalize_draft_rejects_quantitative_bypass(self) -> None:
        with self.assertRaisesRegex(InvestmentArtifactError, "restricted"):
            finalize_draft({
                "module": "valuation", "identity": identity(),
                "scope": {"type": "company", "name": "Test Co"}, "data": {},
            })


if __name__ == "__main__":
    unittest.main()
