"""Evidence integrity is content-based, never a quotation-length permit."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

from invest_contracts import InvestmentArtifactError, create_artifact, text_sha256, validate_artifact

_spec = importlib.util.spec_from_file_location("_claim_fixture", Path(__file__).with_name("test_contracts.py"))
assert _spec is not None and _spec.loader is not None
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)


def make_artifact(excerpt: str, *, wrong_hash=False, wrong_unit=False):
    sources, parameters, claims = _fixture.evidence()
    claims[0]["excerpt"] = excerpt
    claims[0]["excerpt_sha256"] = "a" * 64 if wrong_hash else text_sha256(excerpt.strip())
    if wrong_unit:
        claims[0]["unit"] = "USD billion"
    return create_artifact(
        "management", _fixture.identity(), {"type": "company", "name": "Test Co"},
        _fixture.management_data(), sources=sources, parameters=parameters,
        evidence_claims=claims, limitations=["Synthetic source capture."],
    )


@pytest.mark.parametrize("excerpt", ["USD 20m.", "Reported net income was USD 20 million. " + "This amount is annual, with no acquisition contribution. " * 18])
def test_supported_quote_has_no_arbitrary_minimum_or_maximum(excerpt):
    artifact = make_artifact(excerpt)
    validate_artifact(artifact)
    assert artifact["evidence_claims"][0]["excerpt"] == excerpt


@pytest.mark.parametrize("kwargs, message", [
    ({"wrong_hash": True}, "excerpt hash mismatch"),
    ({"wrong_unit": True}, "unit mismatch"),
])
def test_length_simplification_preserves_actual_integrity(kwargs, message):
    with pytest.raises(InvestmentArtifactError, match=message):
        make_artifact("Reported net income was USD 20 million.", **kwargs)


def test_empty_quote_is_still_missing_evidence():
    with pytest.raises(InvestmentArtifactError, match="excerpt is required"):
        make_artifact("   ")


def test_public_read_rejects_quotation_mutation():
    artifact = make_artifact("Reported net income was USD 20 million.")
    damaged = copy.deepcopy(artifact)
    damaged["evidence_claims"][0]["excerpt"] = "USD 20 billion."
    with pytest.raises(InvestmentArtifactError):
        validate_artifact(damaged)
