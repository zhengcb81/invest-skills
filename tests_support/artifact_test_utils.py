"""Test-only helpers for reaching downstream semantic tamper validators."""

from __future__ import annotations

from typing import Any

from invest_contracts import build_artifact_compliance_receipt, canonical_sha256


def reseal_artifact(artifact: dict[str, Any]) -> None:
    """Refresh shared compliance and hashes after an intentional test mutation."""
    artifact["compliance_receipt"] = build_artifact_compliance_receipt(
        artifact["module"], artifact["revenue_forecast_ref"], artifact["upstream_artifacts"],
        artifact["sources"], artifact["parameters"], artifact["evidence_claims"],
        artifact["data"], artifact["limitations"],
    )
    body = {key: value for key, value in artifact.items() if key not in {"artifact_id", "artifact_sha256"}}
    artifact["artifact_id"] = canonical_sha256(body)
    artifact["artifact_sha256"] = canonical_sha256({key: value for key, value in artifact.items() if key != "artifact_sha256"})
