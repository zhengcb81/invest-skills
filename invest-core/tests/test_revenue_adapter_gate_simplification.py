"""Self-contained RF artifacts do not need a second publication permit."""
from __future__ import annotations
import copy
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests_support"))

import pytest
from invest_contracts import InvestmentArtifactError, adapt_revenue, canonical_sha256
from revenue_fixtures import load_revenue_fixture


def unattested_result():
    result = copy.deepcopy(load_revenue_fixture("direct"))
    receipt = result["publication_receipt"]
    receipt["attestation_status"] = "unattested"
    receipt["receipt_sha256"] = canonical_sha256({k: v for k, v in receipt.items() if k != "receipt_sha256"})
    result["result_sha256"] = canonical_sha256({k: v for k, v in result.items() if k != "result_sha256"})
    return result


@pytest.mark.parametrize("registry", [False, RuntimeError("index unavailable")])
def test_validated_result_is_independent_of_global_registry(registry):
    result = copy.deepcopy(load_revenue_fixture("direct"))
    with patch("publication_registry.is_registered", **({"side_effect": registry} if isinstance(registry, Exception) else {"return_value": registry})) as lookup:
        adapter = adapt_revenue(result)
    lookup.assert_not_called()
    assert adapter["annual_revenue"]["base"] == result["consolidated_forecast"]["base"]["annual_revenue"]
    assert adapter["registered_input_verification"] == "not_required_self_contained"


def test_unattested_valid_result_is_not_promoted_to_signed_or_rejected():
    result = unattested_result()
    adapter = adapt_revenue(result)
    assert adapter["attestation_verification"] == "unattested_observed"
    assert result["publication_receipt"]["attestation_status"] == "unattested"


def test_unattested_does_not_allow_mutated_economic_output():
    result = unattested_result()
    year = str(result["forecast_years"][0])
    result["consolidated_forecast"]["base"]["annual_revenue"][year] *= 1000
    result["result_sha256"] = canonical_sha256({k: v for k, v in result.items() if k != "result_sha256"})
    with pytest.raises(InvestmentArtifactError):
        adapt_revenue(result)


def test_cached_fixture_cannot_be_mutated_by_another_test():
    first = load_revenue_fixture("growth")
    expected = copy.deepcopy(first)
    first.pop("publication_receipt")
    first["sources"][0]["title"] = "mutated by an independent test"
    assert load_revenue_fixture("growth") == expected
