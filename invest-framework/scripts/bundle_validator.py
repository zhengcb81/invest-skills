"""Validate, freeze, and render a single-company bundle of invest artifacts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable


SUITE = Path(__file__).resolve().parents[2]
for scripts in (
    SUITE / "invest-core" / "scripts", SUITE / "invest-financials" / "scripts",
    SUITE / "invest-valuation" / "scripts", SUITE / "invest-sotp" / "scripts",
    SUITE / "invest-distribution" / "scripts", SUITE / "invest-compare" / "scripts",
):
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))

from capital_allocation import validate_distribution_artifact  # noqa: E402
from financial_model import validate_financial_artifact  # noqa: E402
from invest_contracts import (  # noqa: E402
    ARTIFACT_SCHEMA_VERSION,
    INVEST_SUITE_VERSION,
    InvestmentArtifactError,
    SCENARIOS,
    artifact_reference,
    canonical_sha256,
    create_artifact,
    normalize_revenue_reference,
    read_json,
    revenue_reference,
    validate_artifact,
    validate_revenue_forecast,
    write_new_json,
)
from sotp_model import validate_sotp_artifact  # noqa: E402
from valuation_model import validate_valuation_artifact  # noqa: E402


BUNDLE_PLAN_SCHEMA_VERSION = "2.0"
BUNDLE_DATA_SCHEMA_VERSION = "2.1"
LEGACY_BUNDLE_DATA_SCHEMA_VERSION = "2.0"
EXCLUDED_FROM_COMPANY_BUNDLE = {"compare", "psychology", "framework"}
SEMANTIC_VALIDATORS: dict[str, Callable[[dict[str, Any]], None]] = {
    "financials": validate_financial_artifact,
    "valuation": validate_valuation_artifact,
    "sotp": validate_sotp_artifact,
    "distribution": validate_distribution_artifact,
}


def _require(condition: object, message: str) -> None:
    if not condition:
        raise InvestmentArtifactError(message)


def validate_module_semantics(artifact: dict[str, Any]) -> None:
    validate_artifact(artifact)
    validator = SEMANTIC_VALIDATORS.get(artifact["module"])
    if validator is not None:
        validator(artifact)


def _scope_key(artifact: dict[str, Any]) -> tuple[str, str]:
    scope = artifact["scope"]
    return scope["type"], scope.get("name", "")


def _normalized_revenue_refs(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for artifact in artifacts:
        raw_ref = artifact["revenue_forecast_ref"]
        if raw_ref is None:
            continue
        normalized = normalize_revenue_reference(raw_ref)
        assert isinstance(normalized, dict)
        refs.append(normalized)
    return refs


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


def _validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    _require(isinstance(plan, dict), "bundle plan must be an object")
    _require(plan.get("bundle_plan_schema_version") == BUNDLE_PLAN_SCHEMA_VERSION, "bundle_plan_schema_version must be 2.0")
    allowed = {
        "bundle_plan_schema_version", "required_modules", "optional_modules",
        "required_scoped_artifacts", "optional_scoped_artifacts", "limitations",
        "scenario_manifest", "manifest_sha256",
    }
    _require(not (set(plan) - allowed), f"unsupported bundle plan fields: {sorted(set(plan) - allowed)}")
    required_modules = plan.get("required_modules", [])
    optional_modules = plan.get("optional_modules", [])
    _require(isinstance(required_modules, list) and len(required_modules) == len(set(required_modules)), "required_modules must be unique")
    _require(isinstance(optional_modules, list) and len(optional_modules) == len(set(optional_modules)), "optional_modules must be unique")
    _require(not (set(required_modules) & set(optional_modules)), "required_modules and optional_modules must be disjoint")
    for module in [*required_modules, *optional_modules]:
        _require(isinstance(module, str) and module and module not in EXCLUDED_FROM_COMPANY_BUNDLE, f"invalid bundle module: {module}")
    for field in ("required_scoped_artifacts", "optional_scoped_artifacts"):
        values = plan.get(field, [])
        _require(isinstance(values, list), f"{field} must be a list")
        keys: set[tuple[str, str, str]] = set()
        for item in values:
            _require(isinstance(item, dict) and set(item) == {"module", "scope"}, f"invalid {field} entry")
            scope = item["scope"]
            _require(isinstance(scope, dict) and scope.get("type") in {"company", "segment"}, f"invalid scoped artifact scope: {field}")
            if scope["type"] == "segment":
                _require(isinstance(scope.get("name"), str) and scope["name"].strip(), f"segment scope requires name: {field}")
            key = (item["module"], scope["type"], scope.get("name", ""))
            _require(key not in keys, f"duplicate {field} entry: {key}")
            keys.add(key)
    required_keys = {
        (item["module"], item["scope"]["type"], item["scope"].get("name", ""))
        for item in plan.get("required_scoped_artifacts", [])
    }
    optional_keys = {
        (item["module"], item["scope"]["type"], item["scope"].get("name", ""))
        for item in plan.get("optional_scoped_artifacts", [])
    }
    _require(not (required_keys & optional_keys), "required and optional scoped artifacts must be disjoint")
    limitations = plan.get("limitations", [])
    _require(isinstance(limitations, list) and all(isinstance(item, str) and item.strip() for item in limitations), "bundle limitations must contain non-empty strings")
    manifest_sha256 = plan.get("manifest_sha256")
    if manifest_sha256 is not None:
        _require(isinstance(manifest_sha256, str) and re.fullmatch(r"[0-9a-f]{64}", manifest_sha256) is not None, "invalid manifest_sha256")
    return plan


def _validate_bundle_inputs(artifacts: list[dict[str, Any]], plan: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    _require(isinstance(artifacts, list) and artifacts, "bundle requires artifacts")
    for artifact in artifacts:
        validate_module_semantics(artifact)
        _require(artifact["module"] not in EXCLUDED_FROM_COMPANY_BUNDLE, f"module does not belong in a company bundle: {artifact['module']}")
    artifact_ids = [artifact["artifact_id"] for artifact in artifacts]
    _require(len(artifact_ids) == len(set(artifact_ids)), "bundle contains duplicate artifact IDs")
    identity = artifacts[0]["identity"]
    for artifact in artifacts:
        _require(artifact["identity"] == identity, f"bundle identity mismatch: {artifact['module']}/{_scope_key(artifact)}")
    keys = [(artifact["module"], *_scope_key(artifact)) for artifact in artifacts]
    _require(len(keys) == len(set(keys)), "bundle contains duplicate module/scope artifacts")
    raw_revenue_refs = [artifact["revenue_forecast_ref"] for artifact in artifacts if artifact["revenue_forecast_ref"] is not None]
    if raw_revenue_refs:
        _require(all(ref == raw_revenue_refs[0] for ref in raw_revenue_refs), "bundle revenue lineage mismatch")
    revenue_refs = _normalized_revenue_refs(artifacts)
    scenario_manifests = [artifact.get("scenario_manifest") for artifact in artifacts if artifact["scenario_set"] and artifact.get("scenario_manifest") is not None]
    if scenario_manifests:
        _require(all(value == scenario_manifests[0] for value in scenario_manifests), "bundle scenario manifest mismatch")
        if plan.get("scenario_manifest") is not None:
            _require(plan["scenario_manifest"] == scenario_manifests[0], "bundle plan scenario manifest mismatch")
    elif plan.get("scenario_manifest") is not None:
        raise InvestmentArtifactError("non-scenario bundle cannot carry scenario_manifest")
    present_modules = {artifact["module"] for artifact in artifacts}
    missing_required = sorted(set(plan.get("required_modules", [])) - present_modules)
    _require(not missing_required, f"bundle missing required modules: {missing_required}")
    present_keys = set(keys)
    required_keys = {
        (item["module"], item["scope"]["type"], item["scope"].get("name", ""))
        for item in plan.get("required_scoped_artifacts", [])
    }
    _require(not (required_keys - present_keys), f"bundle missing required scoped artifacts: {sorted(required_keys - present_keys)}")
    missing_optional = sorted(set(plan.get("optional_modules", [])) - present_modules)
    return identity, revenue_refs, missing_optional


def _summary(
    artifacts: list[dict[str, Any]], plan: dict[str, Any], missing_optional: list[str],
    *, include_growth_drivers: bool = True,
) -> dict[str, Any]:
    order = _topological_order(artifacts)
    by_id = {artifact["artifact_id"]: artifact for artifact in artifacts}
    inventory = [
        {
            "execution_index": index, "module": by_id[artifact_id]["module"],
            "scope": by_id[artifact_id]["scope"], "artifact_id": artifact_id,
            "artifact_sha256": by_id[artifact_id]["artifact_sha256"],
        }
        for index, artifact_id in enumerate(order, start=1)
    ]
    present_modules = {artifact["module"] for artifact in artifacts}
    revenue_refs = _normalized_revenue_refs(artifacts)
    scenario_manifests = [artifact.get("scenario_manifest") for artifact in artifacts if artifact["scenario_set"] and artifact.get("scenario_manifest") is not None]
    scenario_manifest = scenario_manifests[0] if scenario_manifests else None
    assert scenario_manifest is None or isinstance(scenario_manifest, dict)
    summary = {
        "company_name": artifacts[0]["identity"]["company_name"],
        "management_target_coverage_status": revenue_refs[0].get("management_target_coverage_status", "legacy_not_available") if revenue_refs else "not_applicable",
        "management_target_summary": revenue_refs[0].get("management_target_summary", []) if revenue_refs else [],
        "required_modules": plan.get("required_modules", []), "optional_modules": plan.get("optional_modules", []),
        "required_scoped_artifacts": plan.get("required_scoped_artifacts", []),
        "optional_scoped_artifacts": plan.get("optional_scoped_artifacts", []),
        "missing_optional_modules": missing_optional, "execution_order": inventory,
        "module_counts": {module: sum(1 for artifact in artifacts if artifact["module"] == module) for module in sorted(present_modules)},
        "manifest_sha256": plan.get("manifest_sha256"),
        "scenario_manifest_sha256": scenario_manifest["scenario_manifest_sha256"] if scenario_manifest is not None else None,
    }
    if include_growth_drivers:
        summary.update({
            "growth_driver_analysis_status": revenue_refs[0].get("growth_driver_analysis_status", "legacy_not_available") if revenue_refs else "not_applicable",
            "growth_driver_analysis_sha256": revenue_refs[0].get("growth_driver_analysis_sha256") if revenue_refs else None,
            "growth_driver_summary": revenue_refs[0].get("growth_driver_summary", {
                "drivers": [], "unattributed_company_adjustments": None,
                "reconciliation": None, "rationale": "no revenue-consuming module is present",
            }) if revenue_refs else {
                "drivers": [], "unattributed_company_adjustments": None,
                "reconciliation": None, "rationale": "no revenue-consuming module is present",
            },
            "growth_driver_summary_sha256": revenue_refs[0].get("growth_driver_summary_sha256") if revenue_refs else None,
        })
    return summary


def validate_bundle_artifact(artifact: dict[str, Any]) -> None:
    validate_artifact(artifact)
    _require(artifact["module"] == "framework", "expected framework bundle artifact")
    if artifact["artifact_schema_version"] != ARTIFACT_SCHEMA_VERSION:
        return
    data = artifact["data"]
    expected_data_schema = BUNDLE_DATA_SCHEMA_VERSION if artifact["invest_suite_version"] == INVEST_SUITE_VERSION else LEGACY_BUNDLE_DATA_SCHEMA_VERSION
    _require(data.get("bundle_data_schema_version") == expected_data_schema, "invalid bundle data schema")
    snapshots = data.get("artifact_snapshots")
    _require(isinstance(snapshots, list) and snapshots, "bundle must freeze artifact snapshots")
    plan = data.get("bundle_plan_snapshot")
    _validate_plan(plan)
    _, _, missing_optional = _validate_bundle_inputs(snapshots, plan)
    _require(artifact["upstream_artifacts"] == [artifact_reference(item) for item in snapshots], "bundle upstream snapshots mismatch")
    expected_summary = _summary(
        snapshots, plan, missing_optional,
        include_growth_drivers=expected_data_schema == BUNDLE_DATA_SCHEMA_VERSION,
    )
    _require(data.get("summary") == expected_summary, "bundle semantic summary mismatch")
    manifest_snapshot = data.get("manifest_snapshot")
    if expected_summary["manifest_sha256"] is not None:
        _require(isinstance(manifest_snapshot, dict), "manifest_sha256 requires frozen manifest_snapshot")
        _require(canonical_sha256(manifest_snapshot) == expected_summary["manifest_sha256"], "bundle manifest snapshot hash mismatch")
    frozen_forecast = data.get("frozen_revenue_forecast")
    if frozen_forecast is not None:
        validate_revenue_forecast(frozen_forecast)
        if expected_data_schema == BUNDLE_DATA_SCHEMA_VERSION:
            _require(artifact["revenue_forecast_ref"] == revenue_reference(frozen_forecast), "bundle frozen forecast reference mismatch")
        else:
            _require(artifact["revenue_forecast_ref"] is not None and frozen_forecast["result_sha256"] == artifact["revenue_forecast_ref"]["result_sha256"], "bundle frozen forecast lineage mismatch")
    supplemental_ids = data.get("supplemental_artifact_ids")
    _require(isinstance(supplemental_ids, list) and len(supplemental_ids) == len(set(supplemental_ids)), "invalid supplemental_artifact_ids")
    _require(set(supplemental_ids) <= {item["artifact_id"] for item in snapshots}, "unknown supplemental artifact ID")


def run_bundle(
    artifacts: list[dict[str, Any]],
    plan: dict[str, Any],
    *,
    manifest_snapshot: dict[str, Any] | None = None,
    frozen_revenue_forecast: dict[str, Any] | None = None,
    supplemental_artifact_ids: list[str] | None = None,
) -> dict[str, Any]:
    plan = _validate_plan(plan)
    identity, revenue_refs, missing_optional = _validate_bundle_inputs(artifacts, plan)
    if plan.get("manifest_sha256") is not None:
        _require(isinstance(manifest_snapshot, dict), "manifest_sha256 requires manifest_snapshot")
        _require(canonical_sha256(manifest_snapshot) == plan["manifest_sha256"], "manifest_snapshot hash mismatch")
    if frozen_revenue_forecast is not None:
        validate_revenue_forecast(frozen_revenue_forecast)
        _require(bool(revenue_refs) and revenue_reference(frozen_revenue_forecast) == revenue_refs[0], "frozen forecast reference mismatch")
    supplemental_ids = list(supplemental_artifact_ids or [])
    _require(len(supplemental_ids) == len(set(supplemental_ids)), "supplemental artifact IDs must be unique")
    _require(set(supplemental_ids) <= {item["artifact_id"] for item in artifacts}, "unknown supplemental artifact ID")
    limitations = list(plan.get("limitations", []))
    limitations.extend(f"Optional module not present: {module}" for module in missing_optional)
    summary = _summary(artifacts, plan, missing_optional)
    data = {
        "bundle_data_schema_version": BUNDLE_DATA_SCHEMA_VERSION,
        "bundle_plan_snapshot": plan, "manifest_snapshot": manifest_snapshot,
        "frozen_revenue_forecast": frozen_revenue_forecast,
        "artifact_snapshots": artifacts, "supplemental_artifact_ids": supplemental_ids,
        "summary": summary,
        **summary,
    }
    scenario_set = list(SCENARIOS) if any(artifact["scenario_set"] == list(SCENARIOS) for artifact in artifacts) else []
    scenario_manifest = next((artifact.get("scenario_manifest") for artifact in artifacts if artifact["scenario_set"] and artifact.get("scenario_manifest") is not None), None)
    bundle = create_artifact(
        "framework", identity, {"type": "company", "name": identity["company_name"]}, data,
        scenario_set=scenario_set, scenario_manifest=scenario_manifest,
        revenue_forecast_ref=revenue_refs[0] if revenue_refs else None,
        upstream_artifacts=artifacts, limitations=limitations,
    )
    validate_bundle_artifact(bundle)
    return bundle


def render_bundle_markdown(bundle: dict[str, Any]) -> str:
    """Render a validated bundle without recalculating any forecast or valuation."""
    validate_bundle_artifact(bundle)
    data = bundle["data"]
    summary = data["summary"]
    lines = [
        f"# {summary['company_name']} 投资分析包",
        "",
        f"- 信息日：{bundle['identity']['as_of_date']}",
        f"- Invest suite：{bundle['invest_suite_version']} / artifact {bundle['artifact_schema_version']}",
        f"- Bundle ID：`{bundle['artifact_id']}`",
        f"- 营收目标覆盖：{summary['management_target_coverage_status']}",
        "",
        "## 模块与数据血缘",
        "",
        "| 顺序 | 模块 | 范围 | Artifact ID |",
        "|---:|---|---|---|",
    ]
    for item in summary["execution_order"]:
        scope = item["scope"].get("name", item["scope"]["type"])
        lines.append(f"| {item['execution_index']} | {item['module']} | {scope} | `{item['artifact_id'][:12]}` |")
    sotps = [item for item in data["artifact_snapshots"] if item["module"] == "sotp"]
    valuations = [
        item for item in data["artifact_snapshots"]
        if item["module"] == "valuation" and item["scope"]["type"] == "company"
        and set(item.get("data", {}).get("scenario_valuations", {})) == set(SCENARIOS)
    ]
    if sotps or valuations:
        lines.extend(["", "## 当前价值", "", "| 情景 | 口径 | 当前权益价值 | 每证券价值 |", "|---|---|---:|---:|"])
        if sotps:
            scenario_data = sotps[0]["data"]["scenario_sotp"]
            for scenario in SCENARIOS:
                row = scenario_data[scenario]
                security = row.get("security_value")
                per_security = "—" if security is None else f"{security['per_security_value_current']:.2f} {security['listing_currency']}"
                lines.append(f"| {scenario} | SOTP/{row['aggregation_basis']} | {row['sotp_equity_value_current']:.2f} | {per_security} |")
        else:
            scenario_data = valuations[0]["data"]["scenario_valuations"]
            for scenario in SCENARIOS:
                row = scenario_data[scenario]
                value = row.get("weighted_equity_value_current")
                per_security = row.get("weighted_per_security_value_current")
                lines.append(f"| {scenario} | weighted valuation | {value if value is not None else '—'} | {per_security if per_security is not None else '—'} |")
    targets = summary["management_target_summary"]
    if targets:
        lines.extend(["", "## 管理层营收目标", "", "| Target | Period | Basis | Treatment |", "|---|---|---|---|"])
        for target in targets:
            lines.append(f"| {target['target_id']} | {target['target_period']} | {target.get('measurement_basis', 'legacy')} | {target['treatment']} |")
    growth = summary["growth_driver_summary"]
    drivers = growth["drivers"]
    lines.extend(["", "## 未来收入主要驱动力", ""])
    if drivers:
        for driver in drivers:
            rank = f"#{driver['rank']} " if driver["rank"] is not None else ""
            sign = "+" if driver["estimated_base_terminal_increment"] >= 0 else ""
            lines.extend([
                f"### {rank}{driver['title']}", "",
                f"- 逻辑：{driver['thesis']}",
                f"- 终年基准情景收入增量：{sign}{driver['estimated_base_terminal_increment']:.2f} {bundle['identity']['currency']} {bundle['identity']['unit']}",
                f"- 归属分部：{', '.join(driver['segment_names'])}",
                f"- 持续性：{driver['persistence']}；证据状态：{driver['evidence_status']}",
                f"- 领先指标：{'; '.join(driver['leading_indicators'])}",
                f"- 证伪条件：{'; '.join(driver['falsifiers'])}",
                "",
            ])
    else:
        lines.append(f"- {growth['rationale'] or '未形成可验证的收入增长驱动树。'}")
    lines.extend(["", "## 限制与缺口", ""])
    if bundle["limitations"]:
        lines.extend(f"- {item}" for item in bundle["limitations"])
    else:
        lines.append("- 无已登记限制。")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and render a modular single-company investment bundle")
    parser.add_argument("plan", nargs="?")
    parser.add_argument("artifacts", nargs="*")
    parser.add_argument("--output")
    parser.add_argument("--validate-artifact")
    parser.add_argument("--render-markdown")
    parser.add_argument("--markdown-output")
    args = parser.parse_args()
    try:
        if args.validate_artifact:
            validate_bundle_artifact(read_json(args.validate_artifact))
            print("bundle artifact valid")
            return 0
        if args.render_markdown:
            markdown = render_bundle_markdown(read_json(args.render_markdown))
            if args.markdown_output:
                target = Path(args.markdown_output)
                _require(not target.exists(), f"refusing to overwrite existing file: {target}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(markdown, encoding="utf-8")
            else:
                print(markdown, end="")
            return 0
        _require(bool(args.plan and args.artifacts and args.output), "plan, artifacts, and --output are required")
        result = run_bundle([read_json(path) for path in args.artifacts], read_json(args.plan))
        write_new_json(args.output, result)
        return 0
    except (InvestmentArtifactError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
