"""Validate and freeze a single-company bundle of modular investment artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


CORE_SCRIPTS = Path(__file__).resolve().parents[2] / "invest-core" / "scripts"
if str(CORE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CORE_SCRIPTS))

from invest_contracts import (  # noqa: E402
    InvestmentArtifactError,
    SCENARIOS,
    create_artifact,
    read_json,
    validate_artifact,
    write_new_json,
)


EXCLUDED_FROM_COMPANY_BUNDLE = {"compare", "psychology", "framework"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InvestmentArtifactError(message)


def _scope_key(artifact: dict[str, Any]) -> tuple[str, str]:
    scope = artifact["scope"]
    return scope["type"], scope.get("name", "")


def _topological_order(artifacts: list[dict[str, Any]]) -> list[str]:
    by_id = {artifact["artifact_id"]: artifact for artifact in artifacts}
    visiting: set[str] = set()
    visited: set[str] = set()
    order: list[str] = []
    def visit(artifact_id: str) -> None:
        _require(artifact_id not in visiting, f"artifact dependency cycle: {artifact_id}")
        if artifact_id in visited:
            return
        visiting.add(artifact_id)
        artifact = by_id[artifact_id]
        for upstream in artifact["upstream_artifacts"]:
            upstream_id = upstream["artifact_id"]
            _require(upstream_id in by_id, f"bundle missing upstream artifact: {upstream_id}")
            actual = by_id[upstream_id]
            _require(actual["artifact_sha256"] == upstream["artifact_sha256"], f"bundle upstream hash mismatch: {upstream_id}")
            visit(upstream_id)
        visiting.remove(artifact_id)
        visited.add(artifact_id)
        order.append(artifact_id)
    for artifact_id in by_id:
        visit(artifact_id)
    return order


def run_bundle(artifacts: list[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    _require(isinstance(artifacts, list) and artifacts, "bundle requires artifacts")
    for artifact in artifacts:
        validate_artifact(artifact)
        _require(artifact["module"] not in EXCLUDED_FROM_COMPANY_BUNDLE, f"module does not belong in a company bundle: {artifact['module']}")
    artifact_ids = [artifact["artifact_id"] for artifact in artifacts]
    _require(len(artifact_ids) == len(set(artifact_ids)), "bundle contains duplicate artifact IDs")
    identity = artifacts[0]["identity"]
    company_name = identity["company_name"]
    for artifact in artifacts:
        _require(artifact["identity"] == identity, f"bundle identity mismatch: {artifact['module']}/{_scope_key(artifact)}")
    keys = [(artifact["module"], *_scope_key(artifact)) for artifact in artifacts]
    _require(len(keys) == len(set(keys)), "bundle contains duplicate module/scope artifacts")
    revenue_refs = [artifact["revenue_forecast_ref"] for artifact in artifacts if artifact["revenue_forecast_ref"] is not None]
    if revenue_refs:
        _require(all(ref == revenue_refs[0] for ref in revenue_refs), "bundle revenue lineage mismatch")
    required_modules = plan.get("required_modules", [])
    optional_modules = plan.get("optional_modules", [])
    _require(isinstance(required_modules, list) and len(required_modules) == len(set(required_modules)), "required_modules must be unique")
    _require(isinstance(optional_modules, list) and len(optional_modules) == len(set(optional_modules)), "optional_modules must be unique")
    present_modules = {artifact["module"] for artifact in artifacts}
    missing_required = sorted(set(required_modules) - present_modules)
    _require(not missing_required, f"bundle missing required modules: {missing_required}")
    missing_optional = sorted(set(optional_modules) - present_modules)
    order = _topological_order(artifacts)
    by_id = {artifact["artifact_id"]: artifact for artifact in artifacts}
    inventory = [
        {
            "execution_index": index,
            "module": by_id[artifact_id]["module"],
            "scope": by_id[artifact_id]["scope"],
            "artifact_id": artifact_id,
            "artifact_sha256": by_id[artifact_id]["artifact_sha256"],
        }
        for index, artifact_id in enumerate(order, start=1)
    ]
    limitations = list(plan.get("limitations", []))
    limitations.extend(f"Optional module not present: {module}" for module in missing_optional)
    data = {
        "company_name": company_name,
        "management_target_coverage_status": revenue_refs[0]["management_target_coverage_status"] if revenue_refs else "not_applicable",
        "management_target_summary": revenue_refs[0]["management_target_summary"] if revenue_refs else [],
        "required_modules": required_modules,
        "optional_modules": optional_modules,
        "missing_optional_modules": missing_optional,
        "execution_order": inventory,
        "module_counts": {module: sum(1 for artifact in artifacts if artifact["module"] == module) for module in sorted(present_modules)},
    }
    scenario_set = list(SCENARIOS) if any(artifact["scenario_set"] == list(SCENARIOS) for artifact in artifacts) else []
    return create_artifact(
        "framework", identity, {"type": "company", "name": company_name}, data,
        scenario_set=scenario_set, revenue_forecast_ref=revenue_refs[0] if revenue_refs else None,
        upstream_artifacts=artifacts, limitations=limitations,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a modular single-company investment bundle")
    parser.add_argument("plan")
    parser.add_argument("artifacts", nargs="+")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = run_bundle([read_json(path) for path in args.artifacts], read_json(args.plan))
        write_new_json(args.output, result)
        return 0
    except (InvestmentArtifactError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
