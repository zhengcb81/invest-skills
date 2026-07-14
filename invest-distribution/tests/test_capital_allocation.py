from __future__ import annotations

import sys
import unittest
from pathlib import Path


SUITE = Path(__file__).resolve().parents[2]
for scripts in (
    SUITE / "invest-core" / "scripts", SUITE / "invest-financials" / "scripts",
    Path(__file__).resolve().parents[1] / "scripts",
):
    sys.path.insert(0, str(scripts))
sys.path.insert(0, str(SUITE / "tests_support"))

from capital_allocation import run_capital_allocation, validate_distribution_artifact  # noqa: E402
from financial_model import run_financial_model  # noqa: E402
from invest_contracts import (  # noqa: E402
    InvestmentArtifactError, canonical_sha256, text_sha256, validate_artifact,
)
from revenue_fixtures import load_revenue_fixture  # noqa: E402
from artifact_test_utils import reseal_artifact  # noqa: E402


def financials() -> dict:
    forecast = load_revenue_fixture("direct")
    params = []
    for scenario in ("low", "base", "high"):
        for year in forecast["forecast_years"]:
            params.append({
                "parameter_id": f"fcf_margin_{scenario}_{year}", "kind": "analyst_assumption",
                "value": 0.1, "unit": "ratio", "period": f"FY{year}", "definition": "FCF margin",
                "dimension": "ratio", "time_basis": "annual", "scenario": scenario,
                "source_ids": [], "claim_ids": [], "rationale": "Synthetic fixture",
            })
    return run_financial_model(forecast, {
        "financial_model_schema_version": "2.0", "model_family": "operating_company",
        "scope": {"type": "company", "name": forecast["company_name"]}, "parameters": params,
        "lines": [{
            "line_id": "free_cash_flow", "formula": "x0*x1",
            "input_refs": ["revenue", "parameter:fcf_margin_{scenario}_{year}"],
            "input_dimensions": ["revenue", "ratio"], "output_dimension": "cash_flow",
            "time_basis": "annual", "metric_role": "free_cash_flow", "cash_flow_basis": "fcff",
            "dimension_rule": "monetary_times_rate",
        }],
        "required_outputs": ["free_cash_flow"], "sources": [], "evidence_claims": [],
        "limitations": ["Synthetic"],
    })


def model() -> dict:
    measures = (
        "net_income", "dividends", "repurchases", "share_issuance",
        "acquisition_spend", "impairments", "internal_reinvestment", "share_count",
    )
    templates = {measure: measure + "_{year}" for measure in measures}
    values = {
        "net_income": [100, 120], "dividends": [20, 24], "repurchases": [10, 12], "share_issuance": [2, 1],
        "acquisition_spend": [30, 10], "impairments": [0, 5], "internal_reinvestment": [50, 60], "share_count": [100, 98],
    }
    sources = []
    captures: dict[int, dict] = {}
    for year in (2024, 2025):
        source = {
            "source_id": f"filing_{year}", "source_type": "exchange_filing",
            "title": f"FY{year} filing", "publisher": "Exchange",
            "url": f"https://www.sec.gov/Archives/filing-{year}.htm",
            "published_date": f"{year + 1}-03-01", "accessed_date": "2026-07-01",
            "page_or_section": "Capital allocation table",
        }
        capture = {
            "capture_schema_version": "1.0", "capture_method": "browser_open",
            "tool_name": "test-browser", "tool_call_id": f"fixture-filing-{year}",
            "captured_date": source["accessed_date"],
            "snapshot_sha256": canonical_sha256({"year": year, "document": "capital allocation table"}),
            "content_treatment": "untrusted_data_only", "prompt_injection_status": "not_detected",
        }
        capture["receipt_sha256"] = canonical_sha256(capture)
        source["capture"] = capture
        captures[year] = capture
        sources.append(source)
    params = []
    claims = []
    for measure, series in values.items():
        for year, value in zip((2024, 2025), series):
            parameter_id = f"{measure}_{year}"
            claim_id = f"claim_{parameter_id}"
            unit = "shares" if measure == "share_count" else "USD million"
            excerpt = f"The FY{year} capital allocation table reports {measure} of {value} {unit}."
            params.append({
                "parameter_id": parameter_id, "kind": "reported_fact", "value": value,
                "unit": unit, "period": f"FY{year}", "definition": measure.replace("_", " "),
                "dimension": "quantity" if measure == "share_count" else ("profit" if measure == "net_income" else "cash_flow"),
                "time_basis": "annual", "scenario": "shared",
                "currency": None if measure == "share_count" else "USD",
                "scale": None if measure == "share_count" else "million",
                "source_ids": [f"filing_{year}"], "claim_ids": [claim_id],
            })
            claims.append({
                "claim_id": claim_id, "source_id": f"filing_{year}", "target_type": "parameter",
                "target_id": parameter_id, "support_type": "exact_value", "locator": f"Capital allocation/{measure}",
                "excerpt": excerpt, "excerpt_sha256": text_sha256(excerpt),
                "content_sha256": captures[year]["snapshot_sha256"],
                "verified_by": "unit-test", "verified_date": "2026-07-01",
                "verification_status": "opened_and_checked", "extracted_value": value,
                "capture_receipt_sha256": captures[year]["receipt_sha256"],
                "unit": unit, "period": f"FY{year}",
            })
    return {
        "distribution_model_schema_version": "2.0", "historical_years": [2024, 2025],
        "parameter_templates": templates,
        "share_count_basis": {"basis": "diluted_weighted_average", "unit": "ordinary shares"},
        "parameters": params, "sources": sources, "evidence_claims": claims,
        "limitations": ["Synthetic"],
    }


class CapitalAllocationTests(unittest.TestCase):
    def test_calculates_dilution_flows_and_per_share_history(self) -> None:
        result = run_capital_allocation(financials(), model())
        validate_artifact(result)
        validate_distribution_artifact(result)
        self.assertLess(result["data"]["share_count_cagr"], 0)
        self.assertEqual(result["data"]["annual_allocation"][0]["net_repurchase_cash"], 8)
        self.assertEqual(result["data"]["annual_allocation"][0]["profit_retained_after_dividends"], 80)
        self.assertEqual(result["data"]["annual_allocation"][0]["net_income_per_share_unit"], 1)

    def test_missing_flow_does_not_default_to_zero(self) -> None:
        value = model()
        value["parameters"] = [item for item in value["parameters"] if item["parameter_id"] != "dividends_2024"]
        with self.assertRaisesRegex(InvestmentArtifactError, "missing allocation parameter"):
            run_capital_allocation(financials(), value)

    def test_historical_assumption_cannot_bypass_fact_evidence(self) -> None:
        value = model()
        value["parameters"][0]["kind"] = "analyst_assumption"
        value["parameters"][0]["rationale"] = "Not an acceptable substitute for history"
        with self.assertRaisesRegex(InvestmentArtifactError, "reported_fact or derived_fact"):
            run_capital_allocation(financials(), value)

    def test_semantic_validator_recomputes_distribution(self) -> None:
        artifact = run_capital_allocation(financials(), model())
        artifact["data"]["share_count_cagr"] = 0.99
        reseal_artifact(artifact)
        with self.assertRaisesRegex(InvestmentArtifactError, "semantic recomputation"):
            validate_distribution_artifact(artifact)


if __name__ == "__main__":
    unittest.main()
