"""R1.3 conformance: a forged revenue artifact must be rejected at every hop
of the cross-repo chain — revenue-forecast, invest-core, invest-framework.

This is the audit_review Phase A3 plan (never implemented before): generate a
legitimate forecast, forge it (inflated numbers anchored to the legitimate
input hash, every hash re-signed), and assert all three validation layers
reject it.
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


SUITE = Path(__file__).resolve().parents[2]
for path in (
    SUITE / "invest-core" / "scripts",
    Path(__file__).resolve().parents[1] / "scripts",
):
    sys.path.insert(0, str(path))
sys.path.insert(0, str(SUITE / "tests_support"))
# revenue-forecast is a sibling of invest-skills under ~/Projects; the
# REVENUE_FORECAST_DIR environment variable takes precedence when set.
sys.path.insert(0, str(SUITE.parent / "revenue-forecast" / "scripts"))
sys.path.insert(0, str(SUITE.parent / "revenue-forecast" / "tests"))

from company_orchestrator import validate_execution  # noqa: E402
from invest_contracts import (  # noqa: E402
    InvestmentArtifactError,
    adapt_revenue,
    validate_revenue_forecast,
)
from revenue_core import canonical_sha256, run_forecast  # noqa: E402
from revenue_publication import (  # noqa: E402
    VerificationContext,
    build_publication_receipt,
    expected_publication_gates,
)
from revenue_core import ENGINE_VERSION  # noqa: E402
from revenue_report import validate_forecast_output  # noqa: E402
from test_recognition_bridge import forecast_document  # noqa: E402


def forge_anchored_result() -> dict:
    """Run the engine, inflate assumption/stress parameters, anchor the forged
    result to the legitimate input hash, and re-sign every hash."""
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
    return forged


class ForgedCrossRepoChainTests(unittest.TestCase):
    def test_forged_artifact_rejected_at_all_three_hops(self) -> None:
        forged = forge_anchored_result()
        # Hop 1: revenue-forecast output validator.
        with self.assertRaises(Exception):
            validate_forecast_output(forged)
        # Hop 2: invest-core contract boundary (strong path + adapter).
        with self.assertRaises(InvestmentArtifactError):
            validate_revenue_forecast(forged)
        with self.assertRaises(InvestmentArtifactError):
            adapt_revenue(forged, scope="company", segment_name=None)
        # Hop 3: invest-framework formal execution validation — the first
        # re-validation inside validate_execution is the revenue forecast.
        execution = {
            "normalized_manifest": {},
            "frozen_revenue_forecast": forged,
            "financials": [],
            "valuations": [],
            "sotp": {},
            "supplementals": [],
            "bundle": {},
            "report_markdown": "",
            "output_files": [],
            "receipt": {},
        }
        with self.assertRaises(InvestmentArtifactError):
            validate_execution(execution)

    def test_legitimate_result_passes_revenue_and_invest_hops(self) -> None:
        legit = run_forecast(forecast_document())
        validate_forecast_output(legit)
        validate_revenue_forecast(legit)
        adapter = adapt_revenue(legit, scope="company", segment_name=None)
        self.assertEqual(adapter["registered_input_verification"], "registered")
        self.assertEqual(adapter["attestation_verification"], "host_signed")


if __name__ == "__main__":
    unittest.main()
