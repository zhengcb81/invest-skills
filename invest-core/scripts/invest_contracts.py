"""Shared contracts and revenue adapter for the modular invest skill suite."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import json
import math
import os
import re
import string
import sys
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse


INVEST_SUITE_VERSION = "5.2.0"
SUPPORTED_INVEST_SUITE_VERSIONS = {"4.0.0", "4.1.0", "4.2.0", "5.0.0", "5.1.0", INVEST_SUITE_VERSION}
CURRENT_SEMANTIC_SUITE_VERSIONS = {"5.1.0", INVEST_SUITE_VERSION}
ARTIFACT_SCHEMA_VERSION = "2.1"
SUPPORTED_ARTIFACT_SCHEMA_VERSIONS = {"1.0", "2.0", ARTIFACT_SCHEMA_VERSION}
ARTIFACT_COMPLIANCE_SCHEMA_VERSION = "1.0"
REVENUE_REFERENCE_SCHEMA_VERSION = "1.2"
SUPPORTED_REVENUE_REFERENCE_SCHEMA_VERSIONS = {"1.1", REVENUE_REFERENCE_SCHEMA_VERSION}
REVENUE_ADAPTER_SCHEMA_VERSION = "1.1"
SCENARIOS = ("low", "base", "high")
MODULE_REGISTRY = {
    "financials": {"requires_revenue": True, "upstream": ()},
    "moat": {"requires_revenue": True, "upstream": ()},
    "management": {"requires_revenue": False, "upstream": ()},
    "distribution": {"requires_revenue": False, "upstream": ("financials",)},
    "valuation": {"requires_revenue": True, "upstream": ("financials",)},
    "sotp": {"requires_revenue": True, "upstream": ("valuation",)},
    "compare": {"requires_revenue": False, "upstream": ()},
    "psychology": {"requires_revenue": False, "upstream": ()},
    "framework": {"requires_revenue": False, "upstream": ()},
}
PARAMETER_KINDS = {
    "reported_fact", "derived_fact", "management_guidance",
    "analyst_assumption", "scenario_stress",
}
PARAMETER_DIMENSIONS = {
    "revenue", "profit", "cash_flow", "asset", "liability", "equity",
    "capex", "working_capital", "quantity", "ratio", "tax_rate",
    "discount_rate", "multiple", "per_share", "currency_rate", "duration",
    "score", "monetary_balance",
}
MONETARY_DIMENSIONS = {
    "revenue", "profit", "cash_flow", "asset", "liability", "equity",
    "capex", "working_capital", "monetary_balance",
}
HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
FY_PATTERN = re.compile(r"FY(\d{4})")
BLOCKED_SOURCE_HOSTS = {
    "example.com", "www.example.com", "example.org", "www.example.org",
    "localhost", "127.0.0.1",
}
TIME_BASES = {"annual", "point_in_time"}
SUPPORT_TYPES = {"exact_value", "rationale_support", "policy_support", "qualitative_support"}
TARGET_TYPES = {"parameter", "policy", "qualitative_assertion", "artifact_assumption"}
QUALITATIVE_DRAFT_MODULES = {"management", "moat"}


class InvestmentArtifactError(ValueError):
    """Raised when an investment artifact violates the shared contract."""


def _fail(condition: object, message: str) -> None:
    if not condition:
        raise InvestmentArtifactError(message)


def _skill_roots() -> list[Path]:
    here = Path(__file__).resolve().parents[1]
    roots = [here.parent, here.parent.parent]
    home = Path.home()
    roots.extend([home / ".agents" / "skills", home / ".claude" / "skills", home / ".codex" / "skills"])
    return roots


def find_skill_dir(name: str, env_var: str | None = None) -> Path:
    if env_var and os.environ.get(env_var):
        candidate = Path(os.environ[env_var]).expanduser().resolve()
        _fail((candidate / "SKILL.md").exists(), f"invalid {env_var}: {candidate}")
        return candidate
    for root in _skill_roots():
        candidate = root / name
        if (candidate / "SKILL.md").exists():
            return candidate.resolve()
    raise InvestmentArtifactError(f"unable to locate required skill: {name}")


@lru_cache(maxsize=1)
def revenue_runtime() -> tuple[Any, Any, Path]:
    skill_dir = find_skill_dir("revenue-forecast", "REVENUE_FORECAST_DIR")
    scripts = skill_dir / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        core = importlib.import_module("revenue_core")
        report = importlib.import_module("revenue_report")
    except Exception as exc:  # pragma: no cover - diagnostic boundary
        raise InvestmentArtifactError(f"failed to load revenue-forecast runtime: {exc}") from exc
    return core, report, skill_dir


def _json_default(value: Any) -> Any:
    raise InvestmentArtifactError(f"value is not JSON serializable: {type(value).__name__}")


def canonical_sha256(value: Any) -> str:
    """Hash canonical JSON without depending on revenue-forecast internals."""
    _validate_finite_json(value, "hash_payload")
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False, default=_json_default,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise InvestmentArtifactError(f"invalid canonical JSON: {exc}") from exc
    return hashlib.sha256(encoded).hexdigest()


def text_sha256(value: str) -> str:
    _fail(isinstance(value, str), "text hash input must be a string")
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def parse_iso_date(value: Any, field: str) -> date:
    _fail(isinstance(value, str) and bool(value.strip()), f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvestmentArtifactError(f"{field} must use YYYY-MM-DD") from exc


def finite_number(value: Any, field: str) -> float:
    _fail(isinstance(value, (int, float)) and not isinstance(value, bool), f"{field} must be numeric")
    number = float(value)
    _fail(math.isfinite(number), f"{field} must be finite")
    return number


def _evaluate_formula_node(node: ast.AST, variables: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _evaluate_formula_node(node.body, variables)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.Name):
        _fail(node.id in variables, f"unsupported formula variable: {node.id}")
        return variables[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate_formula_node(node.operand, variables)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
        left = _evaluate_formula_node(node.left, variables)
        right = _evaluate_formula_node(node.right, variables)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            _fail(not math.isclose(right, 0.0), "formula division by zero")
            return left / right
        _fail(abs(right) <= 10, "formula exponent is outside safe range")
        return left ** right
    raise InvestmentArtifactError(f"unsupported formula node: {type(node).__name__}")


def evaluate_formula(formula: str, inputs: list[float]) -> float:
    _fail(isinstance(formula, str) and bool(formula.strip()), "formula is required")
    _fail(len(formula) <= 500, "formula is too long")
    try:
        parsed = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise InvestmentArtifactError("formula is not valid arithmetic") from exc
    values = [finite_number(value, f"formula.inputs[{index}]") for index, value in enumerate(inputs)]
    result = _evaluate_formula_node(parsed, {f"x{index}": number for index, number in enumerate(values)})
    return finite_number(result, "formula result")


def _validate_finite_json(value: Any, path: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        _fail(math.isfinite(value), f"{path} must not contain NaN or infinity")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_finite_json(child, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            _fail(isinstance(key, str), f"{path} object keys must be strings")
            _validate_finite_json(child, f"{path}.{key}")
        return
    raise InvestmentArtifactError(f"{path} contains unsupported JSON type: {type(value).__name__}")


def valid_source_url(url: Any) -> bool:
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and bool(host) and host not in BLOCKED_SOURCE_HOSTS and "." in host


def build_scenario_manifest(
    scenario_set: list[str], provided: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not scenario_set:
        _fail(provided is None, "non-scenario artifact cannot carry scenario_manifest")
        return None
    _fail(scenario_set == list(SCENARIOS), "scenario manifest requires low/base/high")
    if provided is None:
        provided = {
            "scenario_manifest_version": "1.0",
            "source": "default_label_contract",
            "scenarios": [
                {"scenario": scenario, "definition": f"{scenario} scenario; assumptions remain parameter-linked in the producing module."}
                for scenario in SCENARIOS
            ],
        }
    _fail(isinstance(provided, dict), "scenario_manifest must be an object")
    payload = {key: value for key, value in provided.items() if key != "scenario_manifest_sha256"}
    _fail(set(payload) == {"scenario_manifest_version", "source", "scenarios"}, "scenario_manifest contains unsupported or missing fields")
    _fail(payload["scenario_manifest_version"] == "1.0", "unsupported scenario_manifest_version")
    _fail(isinstance(payload["source"], str) and payload["source"].strip(), "scenario_manifest.source is required")
    records = payload["scenarios"]
    _fail(isinstance(records, list) and len(records) == len(SCENARIOS), "scenario_manifest must define low/base/high")
    _fail([item.get("scenario") for item in records if isinstance(item, dict)] == list(SCENARIOS), "scenario_manifest order must be low/base/high")
    for record in records:
        _fail(isinstance(record, dict) and set(record) == {"scenario", "definition"}, "invalid scenario_manifest record")
        _fail(isinstance(record["definition"], str) and record["definition"].strip(), f"scenario definition is required: {record['scenario']}")
    normalized = {**payload, "scenario_manifest_sha256": canonical_sha256(payload)}
    if "scenario_manifest_sha256" in provided:
        _fail(provided["scenario_manifest_sha256"] == normalized["scenario_manifest_sha256"], "scenario_manifest hash mismatch")
    return normalized


def validate_revenue_forecast(result: dict[str, Any]) -> None:
    _, report, _ = revenue_runtime()
    try:
        report.validate_forecast_output(result)
    except Exception as exc:
        raise InvestmentArtifactError(f"invalid revenue forecast: {exc}") from exc


GROWTH_DRIVER_SUMMARY_FIELDS = {
    "drivers", "unattributed_company_adjustments", "reconciliation", "rationale",
}
GROWTH_DRIVER_ENTRY_FIELDS = {
    "driver_id", "title", "thesis", "direction", "rank", "parameter_ids",
    "segment_names", "causal_chain", "horizon", "persistence",
    "persistence_rationale", "estimated_base_terminal_increment",
    "share_of_positive_driver_increment", "evidence_status", "leading_indicators",
    "falsifiers", "counterevidence_status", "counterevidence_rationale",
}


def _legacy_growth_driver_summary(schema_version: str) -> dict[str, Any]:
    return {
        "drivers": [],
        "unattributed_company_adjustments": None,
        "reconciliation": None,
        "rationale": f"revenue-forecast schema {schema_version} predates the validated growth-driver tree",
    }


def _compact_growth_driver_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    top_ranks = {item["driver_id"]: item["rank"] for item in analysis["top_drivers"]}
    headwind_ranks = {item["driver_id"]: item["rank"] for item in analysis["headwinds"]}
    drivers = []
    for driver in analysis["drivers"]:
        driver_id = driver["driver_id"]
        if driver_id in top_ranks:
            direction = "growth"
            rank = top_ranks[driver_id]
        elif driver_id in headwind_ranks:
            direction = "headwind"
            rank = headwind_ranks[driver_id]
        else:
            direction = "flat"
            rank = None
        drivers.append({
            "driver_id": driver_id,
            "title": driver["title"],
            "thesis": driver["thesis"],
            "direction": direction,
            "rank": rank,
            "parameter_ids": list(driver["parameter_ids"]),
            "segment_names": [item["segment_name"] for item in driver["segment_attribution"]],
            "causal_chain": list(driver["causal_chain"]),
            "horizon": dict(driver["horizon"]),
            "persistence": driver["persistence"],
            "persistence_rationale": driver["persistence_rationale"],
            "estimated_base_terminal_increment": driver["estimated_base_terminal_increment"],
            "share_of_positive_driver_increment": driver["share_of_positive_driver_increment"],
            "evidence_status": driver["evidence_status"],
            "leading_indicators": list(driver["leading_indicators"]),
            "falsifiers": list(driver["falsifiers"]),
            "counterevidence_status": driver["counterevidence_status"],
            "counterevidence_rationale": driver["counterevidence_rationale"],
        })
    return {
        "drivers": drivers,
        "unattributed_company_adjustments": analysis["unattributed_company_adjustments"],
        "reconciliation": dict(analysis["reconciliation"]),
        "rationale": analysis.get("rationale"),
    }


def revenue_reference(result: dict[str, Any]) -> dict[str, Any]:
    validate_revenue_forecast(result)
    reference = {
        "revenue_reference_schema_version": REVENUE_REFERENCE_SCHEMA_VERSION,
        "schema_version": result["schema_version"],
        "engine_version": result["engine_version"],
        "input_sha256": result["input_sha256"],
        "result_sha256": result["result_sha256"],
    }
    workflow_receipt = result.get("workflow_compliance_receipt")
    current_revenue_schema = revenue_runtime()[0].FORECAST_SCHEMA_VERSION
    current_compliance = result["schema_version"] == current_revenue_schema and isinstance(workflow_receipt, dict)
    workflow_receipt_sha256 = None
    if current_compliance:
        assert isinstance(workflow_receipt, dict)
        workflow_receipt_sha256 = workflow_receipt["receipt_sha256"]
    reference.update({
        "revenue_compliance_status": "current_validated" if current_compliance else "legacy_read_only_validated",
        "workflow_compliance_receipt_sha256": workflow_receipt_sha256,
    })
    coverage = result.get("management_target_coverage")
    if coverage is None:
        reference.update({
            "management_target_coverage_status": "legacy_not_available",
            "management_target_counts": None,
            "management_target_summary": [],
            "management_target_summary_sha256": canonical_sha256([]),
        })
    else:
        targets = []
        retained_fields = [
            "target_id", "statement", "metric_name", "target_period",
            "raw_target_value", "raw_unit", "commitment_strength", "scope",
            "perimeter_status", "perimeter_notes", "comparison",
            "comparison_value", "comparison_currency", "comparison_scale",
            "treatment", "mapped_parameter_ids", "mapped_scenarios", "rationale",
            "source_ids", "scenario_comparison",
        ]
        if result["schema_version"] != "3.1":
            retained_fields.extend(["measurement_basis", "measurement_periods", "measurement_rationale"])
        for target in coverage["targets"]:
            targets.append({field: target[field] for field in retained_fields})
        reference.update({
            "management_target_coverage_status": "validated" if result["schema_version"] != "3.1" else "legacy_measurement_semantics",
            "management_target_coverage_sha256": canonical_sha256(coverage),
            "management_target_counts": dict(coverage["counts"]),
            "management_target_summary": targets,
            "management_target_summary_sha256": canonical_sha256(targets),
        })
    analysis = result.get("growth_driver_analysis")
    if analysis is None:
        growth_summary = _legacy_growth_driver_summary(result["schema_version"])
        growth_status = "legacy_not_available"
        analysis_sha256 = None
    else:
        growth_summary = _compact_growth_driver_summary(analysis)
        growth_status = "validated" if analysis["status"] == "modeled" else "data_gap"
        analysis_sha256 = canonical_sha256(analysis)
    reference.update({
        "growth_driver_analysis_status": growth_status,
        "growth_driver_analysis_sha256": analysis_sha256,
        "growth_driver_summary": growth_summary,
        "growth_driver_summary_sha256": canonical_sha256(growth_summary),
    })
    return reference


MANAGEMENT_TARGET_BASE_FIELDS = {
    "target_id", "statement", "metric_name", "target_period", "raw_target_value",
    "raw_unit", "commitment_strength", "scope", "perimeter_status",
    "perimeter_notes", "comparison", "comparison_value", "comparison_currency",
    "comparison_scale", "treatment", "mapped_parameter_ids", "mapped_scenarios",
    "rationale", "source_ids", "scenario_comparison",
}
MANAGEMENT_TARGET_MEASUREMENT_FIELDS = {"measurement_basis", "measurement_periods", "measurement_rationale"}


def _validate_target_summary_entry(
    target: Any, status: str, required: bool, target_ids: set[str],
) -> None:
    _fail(isinstance(target, dict), "invalid management target summary entry")
    assert isinstance(target, dict)
    has_measurement_semantics = MANAGEMENT_TARGET_MEASUREMENT_FIELDS <= set(target)
    if status == "legacy_measurement_semantics":
        _fail(set(target) == MANAGEMENT_TARGET_BASE_FIELDS, "legacy management target summary has unexpected fields")
    elif required:
        _fail(set(target) == MANAGEMENT_TARGET_BASE_FIELDS | MANAGEMENT_TARGET_MEASUREMENT_FIELDS, "management target summary missing measurement semantics")
    else:
        valid_fields = {frozenset(MANAGEMENT_TARGET_BASE_FIELDS), frozenset(MANAGEMENT_TARGET_BASE_FIELDS | MANAGEMENT_TARGET_MEASUREMENT_FIELDS)}
        _fail(frozenset(target) in valid_fields, "invalid management target summary fields")
    target_id = target["target_id"]
    _fail(isinstance(target_id, str) and target_id.strip() and target_id not in target_ids, "management target IDs must be unique")
    assert isinstance(target_id, str)
    target_ids.add(target_id)
    if has_measurement_semantics:
        _fail(target["measurement_basis"] in {"annual_period", "run_rate_at_period_end", "cumulative_periods", "ambiguous"}, f"invalid management target measurement basis: {target_id}")
        _fail(isinstance(target["measurement_periods"], list), f"invalid management target measurement periods: {target_id}")
    _fail(isinstance(target["mapped_scenarios"], list) and set(target["mapped_scenarios"]) <= set(SCENARIOS), f"invalid mapped scenarios: {target_id}")
    comparison = target["scenario_comparison"]
    _fail(isinstance(comparison, dict) and set(comparison) == set(target["mapped_scenarios"]), f"management target scenario comparison mismatch: {target_id}")
    assert isinstance(comparison, dict)
    for scenario, result in comparison.items():
        _fail(isinstance(result, dict) and isinstance(result.get("meets_target"), bool), f"invalid management target attainment: {target_id}/{scenario}")


def _validate_management_target_counts(ref: dict[str, Any], summary: list[Any]) -> None:
    coverage_hash = ref.get("management_target_coverage_sha256")
    _fail(isinstance(coverage_hash, str) and HASH_PATTERN.fullmatch(coverage_hash) is not None, "invalid management target coverage hash")
    counts = ref.get("management_target_counts")
    required_counts = {"communications_checked", "targets_total", "targets_modeled", "targets_unmodeled"}
    _fail(isinstance(counts, dict) and set(counts) == required_counts, "invalid management target counts")
    assert isinstance(counts, dict)
    _fail(all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in counts.values()), "management target counts must be non-negative integers")
    _fail(counts["targets_total"] == len(summary), "management target summary count mismatch")


def _validate_management_target_reference(ref: dict[str, Any], *, required: bool) -> None:
    status = ref.get("management_target_coverage_status")
    if status is None and not required:
        return
    _fail(status in {"validated", "legacy_measurement_semantics", "legacy_not_available"}, "invalid management target coverage status")
    assert isinstance(status, str)
    summary = ref.get("management_target_summary")
    _fail(isinstance(summary, list), "management_target_summary must be a list")
    assert isinstance(summary, list)
    _fail(ref.get("management_target_summary_sha256") == canonical_sha256(summary), "management target summary hash mismatch")
    if status == "legacy_not_available":
        _fail(not summary, "legacy revenue reference cannot contain a management target summary")
        _fail(ref.get("management_target_counts") is None, "legacy revenue reference target counts must be null")
        return
    _validate_management_target_counts(ref, summary)
    target_ids: set[str] = set()
    for target in summary:
        _validate_target_summary_entry(target, status, required, target_ids)


def _validate_growth_driver_summary_entry(
    driver: Any, driver_ids: set[str], ranks: dict[str, list[int]],
) -> None:
    _fail(isinstance(driver, dict) and set(driver) == GROWTH_DRIVER_ENTRY_FIELDS, "invalid growth driver summary fields")
    assert isinstance(driver, dict)
    driver_id = driver["driver_id"]
    _fail(isinstance(driver_id, str) and driver_id.strip() and driver_id not in driver_ids, "growth driver summary IDs must be unique")
    assert isinstance(driver_id, str)
    driver_ids.add(driver_id)
    for field in ("title", "thesis", "persistence", "persistence_rationale", "evidence_status", "counterevidence_status", "counterevidence_rationale"):
        _fail(isinstance(driver[field], str) and driver[field].strip(), f"growth driver {driver_id}.{field} is required")
    direction = driver["direction"]
    _fail(direction in {"growth", "headwind", "flat"}, f"invalid growth driver direction: {driver_id}")
    rank = driver["rank"]
    if direction == "flat":
        _fail(rank is None, f"flat growth driver cannot be ranked: {driver_id}")
    else:
        _fail(isinstance(rank, int) and not isinstance(rank, bool) and rank > 0, f"invalid growth driver rank: {driver_id}")
        assert isinstance(rank, int)
        ranks[direction].append(rank)
    parameter_ids = _string_list(driver["parameter_ids"], f"{driver_id}.parameter_ids", allow_empty=False)
    segment_names = _string_list(driver["segment_names"], f"{driver_id}.segment_names", allow_empty=False)
    _fail(bool(parameter_ids) and bool(segment_names), f"growth driver mappings are required: {driver_id}")
    _string_list(driver["causal_chain"], f"{driver_id}.causal_chain", allow_empty=False)
    _string_list(driver["leading_indicators"], f"{driver_id}.leading_indicators", allow_empty=False)
    _string_list(driver["falsifiers"], f"{driver_id}.falsifiers", allow_empty=False)
    horizon = driver["horizon"]
    _fail(isinstance(horizon, dict) and set(horizon) == {"start_year", "end_year"}, f"invalid growth driver horizon: {driver_id}")
    assert isinstance(horizon, dict)
    start_year = horizon["start_year"]
    end_year = horizon["end_year"]
    _fail(all(isinstance(value, int) and not isinstance(value, bool) for value in (start_year, end_year)) and start_year <= end_year, f"invalid growth driver horizon years: {driver_id}")
    increment = finite_number(driver["estimated_base_terminal_increment"], f"{driver_id}.estimated_base_terminal_increment")
    share = driver["share_of_positive_driver_increment"]
    if share is not None:
        normalized_share = finite_number(share, f"{driver_id}.share_of_positive_driver_increment")
        _fail(0 <= normalized_share <= 1, f"invalid growth driver share: {driver_id}")
    if direction == "growth":
        _fail(increment > 0, f"growth driver increment must be positive: {driver_id}")
    elif direction == "headwind":
        _fail(increment < 0, f"headwind increment must be negative: {driver_id}")
    else:
        _fail(math.isclose(increment, 0.0, rel_tol=0, abs_tol=1e-9), f"flat driver increment must be zero: {driver_id}")


def _validate_growth_driver_reference(ref: dict[str, Any], *, required: bool) -> None:
    version = ref.get("revenue_reference_schema_version")
    status = ref.get("growth_driver_analysis_status")
    if version is None and status is None and not required:
        return
    _fail(version in SUPPORTED_REVENUE_REFERENCE_SCHEMA_VERSIONS, "unsupported revenue reference schema version")
    _fail(status in {"validated", "data_gap", "legacy_not_available"}, "invalid growth driver analysis status")
    summary = ref.get("growth_driver_summary")
    _fail(isinstance(summary, dict) and set(summary) == GROWTH_DRIVER_SUMMARY_FIELDS, "invalid growth driver summary")
    assert isinstance(summary, dict)
    _fail(ref.get("growth_driver_summary_sha256") == canonical_sha256(summary), "growth driver summary hash mismatch")
    analysis_sha256 = ref.get("growth_driver_analysis_sha256")
    if status == "legacy_not_available":
        _fail(analysis_sha256 is None, "legacy growth driver analysis hash must be null")
    else:
        _fail(isinstance(analysis_sha256, str) and HASH_PATTERN.fullmatch(analysis_sha256) is not None, "invalid growth driver analysis hash")
    drivers = summary["drivers"]
    _fail(isinstance(drivers, list), "growth_driver_summary.drivers must be a list")
    assert isinstance(drivers, list)
    driver_ids: set[str] = set()
    ranks: dict[str, list[int]] = {"growth": [], "headwind": []}
    for driver in drivers:
        _validate_growth_driver_summary_entry(driver, driver_ids, ranks)
    for direction, values in ranks.items():
        _fail(sorted(values) == list(range(1, len(values) + 1)), f"growth driver {direction} ranks must be contiguous")
    adjustment = summary["unattributed_company_adjustments"]
    reconciliation = summary["reconciliation"]
    rationale = summary["rationale"]
    if status == "validated":
        _fail(bool(drivers), "validated growth driver analysis requires drivers")
        _fail(rationale is None or isinstance(rationale, str), "invalid growth driver rationale")
    elif status == "data_gap":
        _fail(not drivers, "growth driver data gap cannot contain drivers")
        _fail(isinstance(rationale, str) and rationale.strip(), "growth driver data gap requires rationale")
    else:
        _fail(not drivers and adjustment is None and reconciliation is None, "legacy growth driver summary must not contain modeled values")
        _fail(isinstance(rationale, str) and rationale.strip(), "legacy growth driver summary requires rationale")
        return
    normalized_adjustment = finite_number(adjustment, "growth_driver_summary.unattributed_company_adjustments")
    required_reconciliation = {
        "driver_attributed_segment_increment", "segment_increment_total",
        "unattributed_company_adjustments", "company_increment_total", "difference",
    }
    _fail(isinstance(reconciliation, dict) and set(reconciliation) == required_reconciliation, "invalid growth driver reconciliation")
    assert isinstance(reconciliation, dict)
    for field, value in reconciliation.items():
        finite_number(value, f"growth_driver_summary.reconciliation.{field}")
    _fail(math.isclose(normalized_adjustment, float(reconciliation["unattributed_company_adjustments"]), rel_tol=0, abs_tol=1e-9), "growth driver adjustment reconciliation mismatch")


def _validate_revenue_compliance_reference(ref: dict[str, Any], *, required: bool) -> None:
    version = ref.get("revenue_reference_schema_version")
    if version != REVENUE_REFERENCE_SCHEMA_VERSION and not required:
        return
    _fail(version == REVENUE_REFERENCE_SCHEMA_VERSION, "current artifact requires revenue reference schema 1.2")
    status = ref.get("revenue_compliance_status")
    _fail(status in {"current_validated", "legacy_read_only_validated"}, "invalid revenue compliance status")
    receipt_hash = ref.get("workflow_compliance_receipt_sha256")
    if status == "current_validated":
        _fail(ref.get("schema_version") == revenue_runtime()[0].FORECAST_SCHEMA_VERSION, "current revenue compliance requires current forecast schema")
        _fail(isinstance(receipt_hash, str) and HASH_PATTERN.fullmatch(receipt_hash) is not None, "invalid revenue workflow receipt hash")
    else:
        _fail(receipt_hash is None, "legacy revenue compliance cannot carry a current workflow receipt")


def _normalize_revenue_reference(ref: dict[str, Any] | None) -> dict[str, Any] | None:
    if ref is None:
        return None
    normalized = dict(ref)
    if "management_target_coverage_status" not in normalized:
        _fail(normalized.get("schema_version") == "3.0", "revenue schema 3.1+ requires management target coverage metadata")
        normalized.update({
            "management_target_coverage_status": "legacy_not_available",
            "management_target_counts": None,
            "management_target_summary": [],
            "management_target_summary_sha256": canonical_sha256([]),
        })
    if "revenue_reference_schema_version" not in normalized:
        _fail(normalized.get("schema_version") != "3.3", "revenue schema 3.3 requires growth driver reference metadata")
        growth_summary = _legacy_growth_driver_summary(str(normalized.get("schema_version")))
        normalized.update({
            "revenue_reference_schema_version": REVENUE_REFERENCE_SCHEMA_VERSION,
            "growth_driver_analysis_status": "legacy_not_available",
            "growth_driver_analysis_sha256": None,
            "growth_driver_summary": growth_summary,
            "growth_driver_summary_sha256": canonical_sha256(growth_summary),
        })
    if normalized.get("revenue_reference_schema_version") == "1.1":
        normalized["revenue_reference_schema_version"] = REVENUE_REFERENCE_SCHEMA_VERSION
    if "revenue_compliance_status" not in normalized:
        normalized["revenue_compliance_status"] = "legacy_read_only_validated"
        normalized["workflow_compliance_receipt_sha256"] = None
    _validate_growth_driver_reference(normalized, required=True)
    return normalized


def normalize_revenue_reference(ref: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize a validated legacy or current revenue reference for suite-5.2 descendants."""
    normalized = _normalize_revenue_reference(ref)
    if normalized is None:
        return None
    for key in ("schema_version", "engine_version", "input_sha256", "result_sha256"):
        _fail(isinstance(normalized.get(key), str) and normalized[key], f"revenue reference missing {key}")
    _validate_management_target_reference(normalized, required=True)
    _validate_revenue_compliance_reference(normalized, required=True)
    return normalized


def adapt_revenue(result: dict[str, Any], scope: str = "company", segment_name: str | None = None) -> dict[str, Any]:
    ref = revenue_reference(result)
    _fail(scope in {"company", "segment"}, "scope must be company or segment")
    years = [str(year) for year in result["forecast_years"]]
    if scope == "company":
        paths = {
            scenario: {year: float(result["consolidated_forecast"][scenario]["annual_revenue"][year]) for year in years}
            for scenario in SCENARIOS
        }
        scope_value = {"type": "company", "name": result["company_name"]}
        base_revenue = float(result["base_revenue"])
    else:
        _fail(isinstance(segment_name, str) and segment_name.strip(), "segment_name is required for segment scope")
        matches = [item for item in result["segments"] if item["name"] == segment_name]
        _fail(len(matches) == 1, f"unknown or duplicate revenue segment: {segment_name}")
        segment = matches[0]
        paths = {
            scenario: {
                year: float(segment["scenarios"][scenario].get(
                    "effective_revenue", segment["scenarios"][scenario]["recognized_revenue"]
                )[year])
                for year in years
            }
            for scenario in SCENARIOS
        }
        scope_value = {"type": "segment", "name": segment_name}
        base_revenue = float(segment["base_revenue"])
    adapter = {
        "adapter_schema_version": REVENUE_ADAPTER_SCHEMA_VERSION,
        "company_name": result["company_name"],
        "as_of_date": result["as_of_date"],
        "currency": result["currency"],
        "unit": result["unit"],
        "fiscal_year_end": result["fiscal_year_end"],
        "base_year": result["base_year"],
        "forecast_years": result["forecast_years"],
        "scope": scope_value,
        "scenario_set": list(SCENARIOS),
        "base_revenue": base_revenue,
        "annual_revenue": paths,
        "revenue_forecast_ref": ref,
    }
    adapter["adapter_sha256"] = canonical_sha256(adapter)
    return adapter


def _validate_sources(
    sources: Any, as_of_date: str, *, require_capture: bool = False,
) -> dict[str, dict[str, Any]]:
    _fail(isinstance(sources, list), "sources must be a list")
    as_of = parse_iso_date(as_of_date, "as_of_date")
    index: dict[str, dict[str, Any]] = {}
    for position, source in enumerate(sources):
        prefix = f"sources[{position}]"
        _fail(isinstance(source, dict), f"{prefix} must be an object")
        source_id = source.get("source_id")
        _fail(isinstance(source_id, str) and source_id.strip(), f"{prefix}.source_id is required")
        _fail(source_id not in index, f"duplicate source_id: {source_id}")
        _fail(valid_source_url(source.get("url")), f"invalid source URL: {source_id}")
        for field in ("source_type", "title", "publisher", "page_or_section"):
            _fail(isinstance(source.get(field), str) and source[field].strip(), f"{source_id}.{field} is required")
        published = parse_iso_date(source.get("published_date"), f"{source_id}.published_date")
        _fail(published <= as_of, f"future information leak: {source_id}")
        if source.get("accessed_date") is not None:
            parse_iso_date(source["accessed_date"], f"{source_id}.accessed_date")
        if require_capture:
            try:
                revenue_runtime()[0].validate_source_capture(source, as_of)
            except Exception as exc:
                raise InvestmentArtifactError(f"invalid source capture {source_id}: {exc}") from exc
        index[source_id] = dict(source)
    return index


def _validate_parameter_period(parameter: dict[str, Any], as_of_date: str, parameter_id: str) -> None:
    period = parameter.get("period")
    if parameter.get("time_basis") == "annual":
        _fail(isinstance(period, str) and re.fullmatch(r"FY\d{4}", period) is not None, f"{parameter_id}.period must use FYyyyy")
    else:
        point = parse_iso_date(period, f"{parameter_id}.period")
        _fail(point <= parse_iso_date(as_of_date, "as_of_date"), f"future point-in-time parameter: {parameter_id}")


def _validate_identity(identity: Any, *, strict: bool, allow_mixed_fiscal_year_end: bool = False) -> dict[str, Any]:
    _fail(isinstance(identity, dict), "identity must be an object")
    required = {"company_name", "as_of_date", "currency", "unit", "fiscal_year_end", "base_year", "forecast_years"}
    _fail(required <= set(identity), f"identity missing fields: {sorted(required - set(identity))}")
    _fail(isinstance(identity["company_name"], str) and identity["company_name"].strip(), "company_name is required")
    parse_iso_date(identity["as_of_date"], "as_of_date")
    _fail(isinstance(identity["currency"], str) and identity["currency"].strip(), "identity.currency is required")
    _fail(isinstance(identity["unit"], str) and identity["unit"].strip(), "identity.unit is required")
    _fail(isinstance(identity["base_year"], int) and not isinstance(identity["base_year"], bool), "base_year must be an integer")
    years = identity["forecast_years"]
    _fail(isinstance(years, list) and all(isinstance(year, int) and not isinstance(year, bool) for year in years), "forecast_years must be integers")
    if strict:
        _fail(re.fullmatch(r"[A-Z]{3}", identity["currency"]) is not None, "identity.currency must use an uppercase ISO-style code")
        if allow_mixed_fiscal_year_end:
            _fail(identity["fiscal_year_end"] == "mixed", "comparison fiscal_year_end must be mixed")
        else:
            _fail(isinstance(identity["fiscal_year_end"], str) and re.fullmatch(r"\d{2}-\d{2}", identity["fiscal_year_end"]) is not None, "fiscal_year_end must use MM-DD")
            try:
                date.fromisoformat(f"2000-{identity['fiscal_year_end']}")
            except ValueError as exc:
                raise InvestmentArtifactError("fiscal_year_end is not a valid month/day") from exc
        _fail(bool(years), "forecast_years must not be empty")
        _fail(years == sorted(set(years)), "forecast_years must be unique and increasing")
        _fail(all(year > identity["base_year"] for year in years), "forecast_years must be after base_year")
        if identity.get("company_id") is not None:
            _fail(isinstance(identity["company_id"], str) and identity["company_id"].strip(), "company_id must be a non-empty string")
        security = identity.get("security")
        if security is not None:
            _fail(isinstance(security, dict), "identity.security must be an object")
            _fail(isinstance(security.get("security_id"), str) and security["security_id"].strip(), "identity.security.security_id is required")
            _fail(isinstance(security.get("security_type"), str) and security["security_type"].strip(), "identity.security.security_type is required")
            _fail(finite_number(security.get("units_per_security"), "identity.security.units_per_security") > 0, "units_per_security must be positive")
    return identity


def parameter_by_id(
    parameters: list[dict[str, Any]],
    parameter_id: str,
    *,
    expected_dimensions: set[str] | None = None,
    expected_time_bases: set[str] | None = None,
    scenario: str | None = None,
) -> dict[str, Any]:
    """Resolve one validated parameter with clean errors and semantic guards."""
    _fail(isinstance(parameter_id, str) and parameter_id.strip(), "parameter_id is required")
    matches = [item for item in parameters if isinstance(item, dict) and item.get("parameter_id") == parameter_id]
    _fail(len(matches) == 1, f"unknown or duplicate parameter_id: {parameter_id}")
    parameter = matches[0]
    if expected_dimensions is not None:
        _fail(parameter.get("dimension") in expected_dimensions, f"parameter dimension mismatch: {parameter_id}")
    if expected_time_bases is not None:
        _fail(parameter.get("time_basis") in expected_time_bases, f"parameter time_basis mismatch: {parameter_id}")
    if scenario is not None:
        _fail(parameter.get("scenario", "shared") in {"shared", scenario}, f"parameter scenario mismatch: {parameter_id}/{scenario}")
    finite_number(parameter.get("value"), f"{parameter_id}.value")
    return parameter


def render_parameter_template(template: str, scenario: str, *, year: int | None = None) -> str:
    _fail(isinstance(template, str) and template.strip(), "parameter template is required")
    try:
        fields = {field for _, field, _, _ in string.Formatter().parse(template) if field is not None}
    except ValueError as exc:
        raise InvestmentArtifactError(f"invalid parameter template: {template}") from exc
    _fail(fields <= {"scenario", "year"}, f"unsupported parameter template placeholder: {template}")
    _fail("year" not in fields or year is not None, f"parameter template requires year: {template}")
    try:
        return template.format(scenario=scenario, year=year)
    except (KeyError, ValueError) as exc:
        raise InvestmentArtifactError(f"invalid parameter template: {template}") from exc


def compute_security_value(
    bridge: dict[str, Any] | None,
    parameters: list[dict[str, Any]],
    scenario: str,
    identity: dict[str, Any],
    equity_value: float,
) -> dict[str, Any] | None:
    """Convert current equity value to one listed security without recomputing valuation."""
    if bridge is None:
        return None
    _fail(isinstance(bridge, dict), "security_bridge must be an object")
    for field in ("security_id", "security_type", "listing_currency"):
        _fail(isinstance(bridge.get(field), str) and bridge[field].strip(), f"security_bridge.{field} is required")
    shares_id = render_parameter_template(bridge.get("diluted_share_count_parameter_template", ""), scenario)
    units_id = render_parameter_template(bridge.get("ordinary_units_per_security_parameter_template", ""), scenario)
    shares = parameter_by_id(parameters, shares_id, expected_dimensions={"quantity"}, expected_time_bases={"point_in_time", "annual"}, scenario=scenario)
    units = parameter_by_id(parameters, units_id, expected_dimensions={"quantity"}, expected_time_bases={"point_in_time"}, scenario=scenario)
    share_count = finite_number(shares["value"], f"{shares_id}.value")
    units_per_security = finite_number(units["value"], f"{units_id}.value")
    _fail(share_count > 0 and units_per_security > 0, "security share count and conversion ratio must be positive")
    fx_rate = 1.0
    if bridge["listing_currency"] == identity["currency"]:
        _fail(bridge.get("fx_rate_parameter_template") in (None, ""), "same-currency security bridge must not carry FX")
    else:
        fx_id = render_parameter_template(bridge.get("fx_rate_parameter_template", ""), scenario)
        fx = parameter_by_id(parameters, fx_id, expected_dimensions={"currency_rate"}, expected_time_bases={"point_in_time"}, scenario=scenario)
        _fail(fx.get("period") == identity["as_of_date"], "security FX rate must be measured at value date")
        fx_rate = finite_number(fx["value"], f"{fx_id}.value")
        _fail(fx_rate > 0, "security FX rate must be positive")
    return {
        "security_id": bridge["security_id"], "security_type": bridge["security_type"],
        "listing_currency": bridge["listing_currency"], "diluted_ordinary_units": share_count,
        "ordinary_units_per_security": units_per_security, "fx_listing_per_model_currency": fx_rate,
        "per_security_value_current": finite_number(equity_value, "equity_value") * units_per_security / share_count * fx_rate,
    }


def _validate_parameters(parameters: Any, source_index: dict[str, dict[str, Any]], identity: dict[str, Any]) -> dict[str, dict[str, Any]]:
    _fail(isinstance(parameters, list), "parameters must be a list")
    index: dict[str, dict[str, Any]] = {}
    for position, parameter in enumerate(parameters):
        prefix = f"parameters[{position}]"
        _fail(isinstance(parameter, dict), f"{prefix} must be an object")
        parameter_id = parameter.get("parameter_id")
        _fail(isinstance(parameter_id, str) and parameter_id.strip(), f"{prefix}.parameter_id is required")
        _fail(parameter_id not in index, f"duplicate parameter_id: {parameter_id}")
        _fail(parameter.get("kind") in PARAMETER_KINDS, f"unsupported parameter kind: {parameter_id}")
        value = finite_number(parameter.get("value"), f"{parameter_id}.value")
        for field in ("unit", "definition", "dimension", "time_basis"):
            _fail(isinstance(parameter.get(field), str) and parameter[field].strip(), f"{parameter_id}.{field} is required")
        _fail(parameter["dimension"] in PARAMETER_DIMENSIONS, f"unsupported parameter dimension: {parameter_id}")
        _fail(parameter["time_basis"] in TIME_BASES, f"unsupported time_basis: {parameter_id}")
        _validate_parameter_period(parameter, identity["as_of_date"], parameter_id)
        scenario = parameter.get("scenario", "shared")
        _fail(scenario in {*SCENARIOS, "shared"}, f"invalid parameter scenario: {parameter_id}")
        if parameter["dimension"] in MONETARY_DIMENSIONS:
            _fail(parameter.get("currency") == identity["currency"], f"currency mismatch: {parameter_id}")
            _fail(parameter.get("scale") == identity["unit"], f"scale mismatch: {parameter_id}")
        else:
            _fail(parameter.get("currency") in (None, ""), f"non-monetary parameter cannot carry currency: {parameter_id}")
            _fail(parameter.get("scale") in (None, ""), f"non-monetary parameter cannot carry scale: {parameter_id}")
        source_ids = parameter.get("source_ids", [])
        claim_ids = parameter.get("claim_ids", [])
        _fail(isinstance(source_ids, list) and len(source_ids) == len(set(source_ids)), f"invalid source_ids: {parameter_id}")
        _fail(isinstance(claim_ids, list) and len(claim_ids) == len(set(claim_ids)), f"invalid claim_ids: {parameter_id}")
        for source_id in source_ids:
            _fail(source_id in source_index, f"unknown source_id {source_id} on {parameter_id}")
        if parameter["kind"] in {"reported_fact", "management_guidance"}:
            _fail(bool(source_ids), f"{parameter['kind']} requires a source: {parameter_id}")
        if parameter["kind"] in {"analyst_assumption", "scenario_stress"}:
            _fail(isinstance(parameter.get("rationale"), str) and parameter["rationale"].strip(), f"assumption requires rationale: {parameter_id}")
        if parameter["kind"] == "derived_fact":
            _fail(isinstance(parameter.get("formula"), str) and parameter["formula"].strip(), f"derived parameter requires formula: {parameter_id}")
            inputs = parameter.get("input_parameter_ids")
            _fail(isinstance(inputs, list) and inputs and len(inputs) == len(set(inputs)), f"derived parameter requires unique inputs: {parameter_id}")
        normalized = dict(parameter)
        normalized["value"] = value
        normalized["scenario"] = scenario
        index[parameter_id] = normalized
    resolved: dict[str, float] = {}
    def resolve(parameter_id: str, stack: set[str]) -> float:
        _fail(parameter_id in index, f"unknown derived input: {parameter_id}")
        _fail(parameter_id not in stack, f"derived parameter cycle: {parameter_id}")
        if parameter_id in resolved:
            return resolved[parameter_id]
        parameter = index[parameter_id]
        if parameter["kind"] != "derived_fact":
            resolved[parameter_id] = float(parameter["value"])
            return resolved[parameter_id]
        inputs = [resolve(item, stack | {parameter_id}) for item in parameter["input_parameter_ids"]]
        calculated = evaluate_formula(parameter["formula"], inputs)
        _fail(math.isclose(calculated, float(parameter["value"]), rel_tol=0, abs_tol=max(1.0, abs(calculated)) * 1e-9), f"derived parameter value mismatch: {parameter_id}")
        resolved[parameter_id] = calculated
        return calculated
    for parameter_id in index:
        resolve(parameter_id, set())
    return index


def _validate_claims(
    claims: Any,
    source_index: dict[str, dict[str, Any]],
    parameter_index: dict[str, dict[str, Any]],
    as_of_date: str,
    *,
    require_capture: bool = False,
) -> dict[str, dict[str, Any]]:
    _fail(isinstance(claims, list), "evidence_claims must be a list")
    as_of = parse_iso_date(as_of_date, "as_of_date")
    index: dict[str, dict[str, Any]] = {}
    for position, claim in enumerate(claims):
        prefix = f"evidence_claims[{position}]"
        _fail(isinstance(claim, dict), f"{prefix} must be an object")
        claim_id = claim.get("claim_id")
        _fail(isinstance(claim_id, str) and claim_id.strip(), f"{prefix}.claim_id is required")
        _fail(claim_id not in index, f"duplicate claim_id: {claim_id}")
        _fail(claim.get("source_id") in source_index, f"unknown claim source: {claim_id}")
        _fail(claim.get("target_type") in TARGET_TYPES, f"unsupported claim target_type: {claim_id}")
        _fail(claim.get("support_type") in SUPPORT_TYPES, f"unsupported claim support_type: {claim_id}")
        _fail(isinstance(claim.get("target_id"), str) and claim["target_id"].strip(), f"{claim_id}.target_id is required")
        for field in ("locator", "excerpt", "verified_by"):
            _fail(isinstance(claim.get(field), str) and claim[field].strip(), f"{claim_id}.{field} is required")
        excerpt = claim["excerpt"].strip()
        _fail(10 <= len(excerpt) <= 500, f"invalid claim excerpt length: {claim_id}")
        _fail(claim.get("excerpt_sha256") == text_sha256(excerpt), f"claim excerpt hash mismatch: {claim_id}")
        _fail(isinstance(claim.get("content_sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", claim["content_sha256"]) is not None, f"invalid content hash: {claim_id}")
        _fail(claim.get("verification_status") == "opened_and_checked", f"claim must be opened_and_checked: {claim_id}")
        if require_capture:
            source_capture = source_index[claim["source_id"]].get("capture")
            _fail(isinstance(source_capture, dict), f"claim source capture is missing: {claim_id}")
            assert isinstance(source_capture, dict)
            _fail(claim.get("capture_receipt_sha256") == source_capture["receipt_sha256"], f"claim capture receipt mismatch: {claim_id}")
            _fail(claim["content_sha256"] == source_capture["snapshot_sha256"], f"claim/source snapshot mismatch: {claim_id}")
        verified = parse_iso_date(claim.get("verified_date"), f"{claim_id}.verified_date")
        published = parse_iso_date(source_index[claim["source_id"]]["published_date"], "published_date")
        _fail(published <= verified <= as_of, f"claim verification outside information set: {claim_id}")
        if claim["target_type"] == "parameter":
            target_id = claim["target_id"]
            _fail(target_id in parameter_index, f"unknown claim parameter target: {target_id}")
            parameter = parameter_index[target_id]
            _fail(claim["source_id"] in parameter.get("source_ids", []), f"claim source not registered on parameter: {target_id}")
            if claim["support_type"] == "exact_value":
                extracted = finite_number(claim.get("extracted_value"), f"{claim_id}.extracted_value")
                _fail(math.isclose(extracted, float(parameter["value"]), rel_tol=0, abs_tol=1e-9), f"claim value mismatch: {target_id}")
                _fail(claim.get("unit") == parameter["unit"], f"claim unit mismatch: {target_id}")
                _fail(claim.get("period") == parameter["period"], f"claim period mismatch: {target_id}")
        index[claim_id] = dict(claim)
    for parameter_id, parameter in parameter_index.items():
        linked = []
        for claim_id in parameter.get("claim_ids", []):
            _fail(claim_id in index, f"unknown claim_id {claim_id} on {parameter_id}")
            claim = index[claim_id]
            _fail(claim["target_type"] == "parameter" and claim["target_id"] == parameter_id, f"claim target mismatch: {claim_id}")
            linked.append(claim)
        if parameter["kind"] in {"reported_fact", "management_guidance"}:
            _fail(any(item["support_type"] == "exact_value" for item in linked), f"exact-value claim required: {parameter_id}")
        if parameter["kind"] in {"analyst_assumption", "scenario_stress"} and parameter.get("source_ids"):
            _fail(bool(linked), f"source-linked assumption requires claim: {parameter_id}")
    return index


def _string_list(value: Any, field: str, *, allow_empty: bool = True) -> list[str]:
    _fail(isinstance(value, list), f"{field} must be a list")
    _fail(allow_empty or bool(value), f"{field} must not be empty")
    _fail(all(isinstance(item, str) and item.strip() for item in value), f"{field} must contain non-empty strings")
    _fail(len(value) == len(set(value)), f"{field} must contain unique values")
    return value


def _validate_qualitative_facts(
    facts: Any,
    claim_index: dict[str, dict[str, Any]],
    as_of_date: str,
) -> dict[str, dict[str, Any]]:
    _fail(isinstance(facts, list), "qualitative facts must be a list")
    fact_index: dict[str, dict[str, Any]] = {}
    as_of = parse_iso_date(as_of_date, "as_of_date")
    for position, fact in enumerate(facts):
        _fail(isinstance(fact, dict), f"facts[{position}] must be an object")
        fact_id = fact.get("fact_id")
        _fail(isinstance(fact_id, str) and fact_id.strip() and fact_id not in fact_index, "qualitative fact IDs must be unique")
        for field in ("fact_type", "statement"):
            _fail(isinstance(fact.get(field), str) and fact[field].strip(), f"{fact_id}.{field} is required")
        event_date = fact.get("event_date")
        if event_date is not None:
            _fail(parse_iso_date(event_date, f"{fact_id}.event_date") <= as_of, f"future qualitative fact: {fact_id}")
        claim_ids = _string_list(fact.get("claim_ids"), f"{fact_id}.claim_ids", allow_empty=False)
        for claim_id in claim_ids:
            _fail(claim_id in claim_index, f"unknown qualitative claim: {fact_id}/{claim_id}")
            claim = claim_index[claim_id]
            _fail(claim["target_type"] == "qualitative_assertion" and claim["target_id"] == fact_id, f"qualitative claim target mismatch: {claim_id}")
        fact_index[fact_id] = fact
    for claim_id, claim in claim_index.items():
        if claim["target_type"] != "qualitative_assertion":
            continue
        target_id = claim["target_id"]
        _fail(target_id in fact_index, "qualitative claim targets an unregistered fact")
        _fail(claim_id in fact_index[target_id]["claim_ids"], f"qualitative claim is not linked back from fact: {claim_id}")
    return fact_index


def _validate_interpretations(
    interpretations: Any,
    fact_index: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    _fail(isinstance(interpretations, list), "interpretations must be a list")
    index: dict[str, dict[str, Any]] = {}
    for position, item in enumerate(interpretations):
        _fail(isinstance(item, dict), f"interpretations[{position}] must be an object")
        interpretation_id = item.get("interpretation_id")
        _fail(isinstance(interpretation_id, str) and interpretation_id.strip() and interpretation_id not in index, "interpretation IDs must be unique")
        _fail(isinstance(item.get("statement"), str) and item["statement"].strip(), f"{interpretation_id}.statement is required")
        fact_ids = _string_list(item.get("fact_ids"), f"{interpretation_id}.fact_ids", allow_empty=False)
        contrary_ids = _string_list(item.get("contrary_fact_ids", []), f"{interpretation_id}.contrary_fact_ids")
        _fail(set(fact_ids) <= set(fact_index), f"unknown interpretation fact: {interpretation_id}")
        _fail(set(contrary_ids) <= set(fact_index), f"unknown contrary fact: {interpretation_id}")
        _fail(not (set(fact_ids) & set(contrary_ids)), f"fact cannot be both supporting and contrary: {interpretation_id}")
        _fail(item.get("confidence") in {"high", "medium", "low", "data_gap"}, f"invalid interpretation confidence: {interpretation_id}")
        index[interpretation_id] = item
    return index


def _validate_management_data(
    data: dict[str, Any], claim_index: dict[str, dict[str, Any]], identity: dict[str, Any], scenario_set: list[str],
    revenue_ref: dict[str, Any] | None, suite_version: str,
) -> None:
    expected_version = "2.1" if suite_version in CURRENT_SEMANTIC_SUITE_VERSIONS else "2.0"
    _fail(data.get("qualitative_schema_version") == expected_version, f"management qualitative_schema_version must be {expected_version}")
    _fail(scenario_set == [], "management artifact must be non-scenario")
    facts = _validate_qualitative_facts(data.get("facts"), claim_index, identity["as_of_date"])
    interpretations = _validate_interpretations(data.get("interpretations"), facts)
    red_flags = _string_list(data.get("red_flag_interpretation_ids", []), "red_flag_interpretation_ids")
    _fail(set(red_flags) <= set(interpretations), "red flags must reference registered interpretations")
    disconfirming = _string_list(data.get("disconfirming_fact_ids", []), "disconfirming_fact_ids")
    _fail(set(disconfirming) <= set(facts), "disconfirming evidence must reference registered facts")
    _string_list(data.get("data_gaps", []), "management.data_gaps")
    commitments = data.get("commitment_assessments", [])
    _fail(isinstance(commitments, list), "commitment_assessments must be a list")
    commitment_ids: set[str] = set()
    for item in commitments:
        _fail(isinstance(item, dict), "commitment assessment must be an object")
        assessment_id = item.get("assessment_id")
        _fail(isinstance(assessment_id, str) and assessment_id.strip() and assessment_id not in commitment_ids, "commitment assessment IDs must be unique")
        commitment_ids.add(assessment_id)
        _fail(item.get("commitment_fact_id") in facts, f"unknown commitment fact: {assessment_id}")
        outcome_ids = _string_list(item.get("outcome_fact_ids"), f"{assessment_id}.outcome_fact_ids", allow_empty=False)
        _fail(set(outcome_ids) <= set(facts), f"unknown commitment outcome fact: {assessment_id}")
        _fail(isinstance(item.get("conclusion"), str) and item["conclusion"].strip(), f"commitment conclusion is required: {assessment_id}")
    if expected_version == "2.0":
        return
    execution_assessments = data.get("execution_driver_assessments", [])
    _fail(isinstance(execution_assessments, list), "execution_driver_assessments must be a list")
    if not execution_assessments:
        return
    _fail(isinstance(revenue_ref, dict), "execution driver assessments require revenue_forecast_ref")
    assert isinstance(revenue_ref, dict)
    growth_summary = revenue_ref.get("growth_driver_summary")
    _fail(isinstance(growth_summary, dict), "execution driver assessments require a growth driver summary")
    assert isinstance(growth_summary, dict)
    available_driver_ids = {item["driver_id"] for item in growth_summary["drivers"]}
    available_target_ids = {item["target_id"] for item in revenue_ref.get("management_target_summary", [])}
    assessment_ids: set[str] = set()
    required_fields = {
        "assessment_id", "growth_driver_ids", "management_target_ids", "input_fact_ids",
        "contrary_fact_ids", "status", "conclusion",
    }
    for item in execution_assessments:
        _fail(isinstance(item, dict) and set(item) == required_fields, "invalid execution driver assessment fields")
        assert isinstance(item, dict)
        assessment_id = item["assessment_id"]
        _fail(isinstance(assessment_id, str) and assessment_id.strip() and assessment_id not in assessment_ids, "execution driver assessment IDs must be unique")
        assert isinstance(assessment_id, str)
        assessment_ids.add(assessment_id)
        driver_ids = _string_list(item["growth_driver_ids"], f"{assessment_id}.growth_driver_ids", allow_empty=False)
        target_ids = _string_list(item["management_target_ids"], f"{assessment_id}.management_target_ids")
        input_fact_ids = _string_list(item["input_fact_ids"], f"{assessment_id}.input_fact_ids")
        contrary_fact_ids = _string_list(item["contrary_fact_ids"], f"{assessment_id}.contrary_fact_ids")
        _fail(set(driver_ids) <= available_driver_ids, f"unknown execution growth driver mapping: {assessment_id}")
        _fail(set(target_ids) <= available_target_ids, f"unknown execution management target mapping: {assessment_id}")
        _fail(set(input_fact_ids) <= set(facts) and set(contrary_fact_ids) <= set(facts), f"unknown execution fact mapping: {assessment_id}")
        _fail(not (set(input_fact_ids) & set(contrary_fact_ids)), f"execution fact cannot be both supporting and contrary: {assessment_id}")
        status = item["status"]
        _fail(status in {"on_track", "delayed", "off_track", "unproven", "data_gap"}, f"invalid execution driver status: {assessment_id}")
        if status in {"on_track", "delayed", "off_track"}:
            _fail(bool(input_fact_ids), f"execution status requires supporting facts: {assessment_id}")
        _fail(isinstance(item["conclusion"], str) and item["conclusion"].strip(), f"execution driver conclusion is required: {assessment_id}")


def _validate_moat_data(
    data: dict[str, Any], claim_index: dict[str, dict[str, Any]], identity: dict[str, Any], revenue_ref: dict[str, Any] | None,
    suite_version: str,
) -> None:
    expected_version = "2.1" if suite_version in CURRENT_SEMANTIC_SUITE_VERSIONS else "2.0"
    _fail(data.get("qualitative_schema_version") == expected_version, f"moat qualitative_schema_version must be {expected_version}")
    facts = _validate_qualitative_facts(data.get("facts"), claim_index, identity["as_of_date"])
    registry = data.get("driver_registry")
    _fail(isinstance(registry, dict), "moat driver_registry must be an object")
    assert isinstance(registry, dict)
    assert revenue_ref is not None
    if expected_version == "2.0":
        _fail(revenue_ref is not None and registry.get("revenue_result_sha256") == revenue_ref.get("result_sha256"), "moat driver registry revenue lineage mismatch")
        revenue_ids = set(_string_list(registry.get("revenue_parameter_ids", []), "driver_registry.revenue_parameter_ids"))
    else:
        _fail(set(registry) == {"growth_driver_summary_sha256", "growth_driver_ids", "financial_line_ids"}, "invalid moat driver_registry fields")
        growth_summary = revenue_ref.get("growth_driver_summary")
        _fail(isinstance(growth_summary, dict), "moat requires upstream growth driver summary")
        assert isinstance(growth_summary, dict)
        _fail(registry.get("growth_driver_summary_sha256") == revenue_ref.get("growth_driver_summary_sha256"), "moat growth driver registry lineage mismatch")
        available_ids = {item["driver_id"] for item in growth_summary["drivers"]}
        revenue_ids = set(_string_list(registry.get("growth_driver_ids", []), "driver_registry.growth_driver_ids"))
        _fail(revenue_ids <= available_ids, "moat driver_registry contains unknown growth drivers")
    financial_ids = set(_string_list(registry.get("financial_line_ids", []), "driver_registry.financial_line_ids"))
    mechanisms = data.get("mechanisms")
    _fail(isinstance(mechanisms, list) and mechanisms, "moat mechanisms must be a non-empty list")
    assert isinstance(mechanisms, list)
    mechanism_ids: set[str] = set()
    for position, mechanism in enumerate(mechanisms):
        _fail(isinstance(mechanism, dict), f"mechanisms[{position}] must be an object")
        mechanism_id = mechanism.get("mechanism_id")
        _fail(isinstance(mechanism_id, str) and mechanism_id.strip() and mechanism_id not in mechanism_ids, "moat mechanism IDs must be unique")
        mechanism_ids.add(mechanism_id)
        for field in ("mechanism_type", "business_scope", "unit_of_competition", "causal_chain", "customer_consequence"):
            _fail(isinstance(mechanism.get(field), str) and mechanism[field].strip(), f"{mechanism_id}.{field} is required")
        status = mechanism.get("status")
        _fail(status in {"observed", "weakening", "unproven", "data_gap"}, f"invalid moat status: {mechanism_id}")
        fact_ids = _string_list(mechanism.get("fact_ids", []), f"{mechanism_id}.fact_ids")
        contrary_ids = _string_list(mechanism.get("contrary_fact_ids", []), f"{mechanism_id}.contrary_fact_ids")
        _fail(set(fact_ids) <= set(facts) and set(contrary_ids) <= set(facts), f"unknown moat fact mapping: {mechanism_id}")
        if status in {"observed", "weakening"}:
            _fail(bool(fact_ids), f"observed moat mechanism requires facts: {mechanism_id}")
        mapping_field = "growth_driver_ids" if expected_version == "2.1" else "revenue_parameter_ids"
        mapped_revenue = _string_list(mechanism.get(mapping_field, []), f"{mechanism_id}.{mapping_field}")
        mapped_financial = _string_list(mechanism.get("financial_line_ids", []), f"{mechanism_id}.financial_line_ids")
        _fail(set(mapped_revenue) <= revenue_ids, f"unknown moat growth driver mapping: {mechanism_id}")
        _fail(set(mapped_financial) <= financial_ids, f"unknown moat financial line mapping: {mechanism_id}")
        if status != "data_gap":
            _fail(bool(mapped_revenue or mapped_financial), f"moat mechanism requires a modeled driver mapping: {mechanism_id}")
        durability = mechanism.get("durability_assumption")
        _fail(isinstance(durability, dict), f"durability_assumption is required: {mechanism_id}")
        for field in ("horizon", "rationale"):
            _fail(isinstance(durability.get(field), str) and durability[field].strip(), f"{mechanism_id}.durability_assumption.{field} is required")
        _string_list(mechanism.get("erosion_events", []), f"{mechanism_id}.erosion_events")
        _string_list(mechanism.get("leading_indicators"), f"{mechanism_id}.leading_indicators", allow_empty=False)
        _string_list(mechanism.get("falsifiers"), f"{mechanism_id}.falsifiers", allow_empty=False)
    disconfirming = _string_list(data.get("disconfirming_fact_ids", []), "moat.disconfirming_fact_ids")
    _fail(set(disconfirming) <= set(facts), "moat disconfirming evidence must reference registered facts")
    _string_list(data.get("data_gaps", []), "moat.data_gaps")


def artifact_reference(artifact: dict[str, Any]) -> dict[str, Any]:
    validate_artifact(artifact)
    return {
        "module": artifact["module"],
        "artifact_id": artifact["artifact_id"],
        "artifact_sha256": artifact["artifact_sha256"],
    }


def build_artifact_compliance_receipt(
    module: str,
    revenue_forecast_ref: dict[str, Any] | None,
    upstream_refs: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    parameters: list[dict[str, Any]],
    evidence_claims: list[dict[str, Any]],
    data: dict[str, Any],
    limitations: list[str],
) -> dict[str, Any]:
    """Build the shared, machine-recomputed artifact-contract receipt."""
    for source in sources:
        _fail(isinstance(source.get("capture"), dict), f"source capture is required: {source.get('source_id', '<unknown>')}")
    capture_hashes = sorted(source["capture"]["receipt_sha256"] for source in sources)
    receipt = {
        "compliance_schema_version": ARTIFACT_COMPLIANCE_SCHEMA_VERSION,
        "status": "pass",
        "execution_mode": "deterministic_runtime",
        "module": module,
        "contract_validator_ids": [
            "invest_core.envelope", "invest_core.lineage", "invest_core.source_capture",
            "invest_core.evidence_claims", "invest_core.content_hash",
        ],
        "revenue_result_sha256": None if revenue_forecast_ref is None else revenue_forecast_ref["result_sha256"],
        "upstream_artifact_sha256s": sorted(item["artifact_sha256"] for item in upstream_refs),
        "source_capture_receipt_sha256s": capture_hashes,
        "source_capture_count": len(capture_hashes),
        "checked_claim_count": len(evidence_claims),
        "assumption_parameter_ids": sorted(
            parameter["parameter_id"] for parameter in parameters
            if parameter["kind"] in {"analyst_assumption", "scenario_stress"}
        ),
        "artifact_data_sha256": canonical_sha256(data),
        "limitations_sha256": canonical_sha256(limitations),
        "prompt_injection_flagged_source_ids": sorted(
            source["source_id"] for source in sources
            if source["capture"]["prompt_injection_status"] == "detected_and_ignored"
        ),
        "untrusted_content_treatment": "data_only_never_instructions",
        "formal_output_authority": "validated_artifact_or_bundle_renderer_only",
        "freeform_formal_output_allowed": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return receipt


def create_artifact(
    module: str,
    identity: dict[str, Any],
    scope: dict[str, Any],
    data: dict[str, Any],
    *,
    scenario_set: list[str] | None = None,
    scenario_manifest: dict[str, Any] | None = None,
    revenue_forecast_ref: dict[str, Any] | None = None,
    upstream_artifacts: list[dict[str, Any]] | None = None,
    sources: list[dict[str, Any]] | None = None,
    parameters: list[dict[str, Any]] | None = None,
    evidence_claims: list[dict[str, Any]] | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    _fail(module in MODULE_REGISTRY, f"unknown module: {module}")
    upstream_refs = [artifact_reference(item) for item in (upstream_artifacts or [])]
    normalized_scenario_set = list(scenario_set or [])
    normalized_sources = list(sources or [])
    normalized_parameters = list(parameters or [])
    normalized_claims = list(evidence_claims or [])
    normalized_limitations = list(limitations or [])
    normalized_revenue_ref = normalize_revenue_reference(revenue_forecast_ref)
    artifact_body = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "invest_suite_version": INVEST_SUITE_VERSION,
        "module": module,
        "identity": dict(identity),
        "scope": dict(scope),
        "scenario_set": normalized_scenario_set,
        "scenario_manifest": build_scenario_manifest(normalized_scenario_set, scenario_manifest),
        "revenue_forecast_ref": normalized_revenue_ref,
        "upstream_artifacts": upstream_refs,
        "sources": normalized_sources,
        "parameters": normalized_parameters,
        "evidence_claims": normalized_claims,
        "data": data,
        "limitations": normalized_limitations,
    }
    artifact_body["compliance_receipt"] = build_artifact_compliance_receipt(
        module, normalized_revenue_ref, upstream_refs, normalized_sources,
        normalized_parameters, normalized_claims, data, normalized_limitations,
    )
    artifact = {**artifact_body, "artifact_id": canonical_sha256(artifact_body)}
    artifact["artifact_sha256"] = canonical_sha256(artifact)
    validate_artifact(artifact)
    return artifact


def _validate_artifact_envelope(artifact: dict[str, Any]) -> tuple[str, bool, str]:
    required = {
        "artifact_schema_version", "invest_suite_version", "module", "artifact_id",
        "identity", "scope", "scenario_set", "revenue_forecast_ref",
        "upstream_artifacts", "sources", "parameters", "evidence_claims",
        "data", "limitations", "artifact_sha256",
    }
    _fail(required <= set(artifact), f"artifact missing fields: {sorted(required - set(artifact))}")
    schema_version = artifact["artifact_schema_version"]
    suite_version = artifact["invest_suite_version"]
    _fail(schema_version in SUPPORTED_ARTIFACT_SCHEMA_VERSIONS, "unsupported artifact schema version")
    _fail(suite_version in SUPPORTED_INVEST_SUITE_VERSIONS, "unsupported invest suite version")
    strict = schema_version in {"2.0", ARTIFACT_SCHEMA_VERSION}
    current = schema_version == ARTIFACT_SCHEMA_VERSION
    if strict:
        _fail("scenario_manifest" in artifact, "artifact missing field: scenario_manifest")
    if current:
        _fail(suite_version == INVEST_SUITE_VERSION, "artifact schema 2.1 requires invest suite 5.2.0")
        _fail("compliance_receipt" in artifact, "artifact missing field: compliance_receipt")
    elif schema_version == "2.0":
        _fail(suite_version in {"5.0.0", "5.1.0"}, "artifact schema 2.0 requires invest suite 5.0.0 or 5.1.0")
    else:
        _fail(suite_version not in {"5.0.0", "5.1.0", INVEST_SUITE_VERSION}, "invest suite 5.x requires artifact schema 2.x")
    module = artifact["module"]
    _fail(module in MODULE_REGISTRY, f"unknown module: {module}")
    assert isinstance(module, str)
    assert isinstance(suite_version, str)
    return module, strict, suite_version


def _validate_artifact_scope(artifact: dict[str, Any], strict: bool) -> dict[str, Any]:
    raw_scope = artifact.get("scope")
    identity = _validate_identity(
        artifact["identity"], strict=strict,
        allow_mixed_fiscal_year_end=strict and isinstance(raw_scope, dict) and raw_scope.get("type") == "comparison",
    )
    _fail(isinstance(raw_scope, dict) and raw_scope.get("type") in {"company", "segment", "comparison"}, "invalid artifact scope")
    assert isinstance(raw_scope, dict)
    if raw_scope["type"] == "segment":
        _fail(isinstance(raw_scope.get("name"), str) and raw_scope["name"].strip(), "segment scope requires name")
    if raw_scope["type"] == "comparison":
        names = raw_scope.get("names")
        _fail(isinstance(names, list) and len(names) >= 2 and all(isinstance(name, str) and name.strip() for name in names), "comparison scope requires at least two names")
        assert isinstance(names, list)
        _fail(len(names) == len(set(names)), "comparison scope names must be unique")
    return identity


def _validate_artifact_scenarios(artifact: dict[str, Any], strict: bool) -> list[str]:
    scenario_set = artifact["scenario_set"]
    _fail(scenario_set in ([], list(SCENARIOS)), "scenario_set must be empty or low/base/high")
    assert isinstance(scenario_set, list)
    if strict:
        expected = build_scenario_manifest(scenario_set, artifact["scenario_manifest"])
        _fail(artifact["scenario_manifest"] == expected, "scenario_manifest normalization mismatch")
    return scenario_set


def _validate_artifact_revenue_reference(module: str, ref: Any, strict: bool, suite_version: str) -> None:
    registry = MODULE_REGISTRY[module]
    if registry["requires_revenue"]:
        _fail(isinstance(ref, dict), f"{module} requires revenue_forecast_ref")
    if ref is None:
        return
    _fail(isinstance(ref, dict), "revenue_forecast_ref must be an object or null")
    assert isinstance(ref, dict)
    for key in ("schema_version", "engine_version", "input_sha256", "result_sha256"):
        _fail(isinstance(ref.get(key), str) and ref[key], f"revenue reference missing {key}")
    _validate_management_target_reference(ref, required=strict)
    _validate_growth_driver_reference(ref, required=suite_version in CURRENT_SEMANTIC_SUITE_VERSIONS)
    _validate_revenue_compliance_reference(ref, required=suite_version == INVEST_SUITE_VERSION)


def _validate_artifact_upstream(module: str, upstream: Any) -> None:
    _fail(isinstance(upstream, list), "upstream_artifacts must be a list")
    assert isinstance(upstream, list)
    seen: set[tuple[Any, Any]] = set()
    for item in upstream:
        _fail(isinstance(item, dict) and set(item) == {"module", "artifact_id", "artifact_sha256"}, "invalid upstream reference")
        assert isinstance(item, dict)
        identity_key = (item["module"], item["artifact_id"])
        _fail(identity_key not in seen, "duplicate upstream artifact reference")
        seen.add(identity_key)
    for required_module in cast(tuple[str, ...], MODULE_REGISTRY[module]["upstream"]):
        _fail(any(item["module"] == required_module for item in upstream), f"{module} requires upstream module: {required_module}")


def _validate_artifact_content_hashes(artifact: dict[str, Any], strict: bool) -> None:
    if strict:
        _fail(isinstance(artifact["artifact_id"], str) and HASH_PATTERN.fullmatch(artifact["artifact_id"]) is not None, "invalid artifact_id")
        _fail(isinstance(artifact["artifact_sha256"], str) and HASH_PATTERN.fullmatch(artifact["artifact_sha256"]) is not None, "invalid artifact_sha256")
    expected_id = canonical_sha256({key: value for key, value in artifact.items() if key not in {"artifact_id", "artifact_sha256"}})
    _fail(artifact["artifact_id"] == expected_id, "artifact_id mismatch")
    payload = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    _fail(artifact["artifact_sha256"] == canonical_sha256(payload), "artifact hash mismatch")


def validate_artifact(artifact: dict[str, Any]) -> None:
    _fail(isinstance(artifact, dict), "artifact must be an object")
    _validate_finite_json(artifact, "artifact")
    module, strict, suite_version = _validate_artifact_envelope(artifact)
    current = artifact["artifact_schema_version"] == ARTIFACT_SCHEMA_VERSION
    identity = _validate_artifact_scope(artifact, strict)
    scenario_set = _validate_artifact_scenarios(artifact, strict)
    _fail(isinstance(artifact["limitations"], list) and all(isinstance(item, str) and item.strip() for item in artifact["limitations"]), "limitations must contain strings")
    _fail(len(artifact["limitations"]) == len(set(artifact["limitations"])), "limitations must be unique")
    _fail(isinstance(artifact["data"], dict), "data must be an object")
    ref = artifact["revenue_forecast_ref"]
    _validate_artifact_revenue_reference(module, ref, strict, suite_version)
    _validate_artifact_upstream(module, artifact["upstream_artifacts"])
    source_index = _validate_sources(artifact["sources"], identity["as_of_date"], require_capture=current)
    parameter_index = _validate_parameters(artifact["parameters"], source_index, identity)
    claim_index = _validate_claims(
        artifact["evidence_claims"], source_index, parameter_index, identity["as_of_date"],
        require_capture=current,
    )
    if strict and module == "management":
        _validate_management_data(artifact["data"], claim_index, identity, scenario_set, ref, suite_version)
    if strict and module == "moat":
        _validate_moat_data(artifact["data"], claim_index, identity, ref, suite_version)
    if current:
        expected_receipt = build_artifact_compliance_receipt(
            module, ref, artifact["upstream_artifacts"], artifact["sources"],
            artifact["parameters"], artifact["evidence_claims"], artifact["data"],
            artifact["limitations"],
        )
        _fail(artifact["compliance_receipt"] == expected_receipt, "artifact compliance receipt mismatch")
    _validate_artifact_content_hashes(artifact, strict)


def read_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    _fail(isinstance(value, dict), f"JSON root must be an object: {path}")
    return value


def write_new_json(path: str | Path, value: dict[str, Any]) -> None:
    target = Path(path)
    _fail(not target.exists(), f"refusing to overwrite existing file: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def finalize_draft(draft: dict[str, Any]) -> dict[str, Any]:
    """Finalize a qualitative or externally assembled module draft."""
    required = {"module", "identity", "scope", "data"}
    _fail(required <= set(draft), f"artifact draft missing fields: {sorted(required - set(draft))}")
    _fail(draft["module"] in QUALITATIVE_DRAFT_MODULES, "finalize-draft is restricted to qualitative management or moat artifacts")
    return create_artifact(
        draft["module"], draft["identity"], draft["scope"], draft["data"],
        scenario_set=draft.get("scenario_set", []),
        scenario_manifest=draft.get("scenario_manifest"),
        revenue_forecast_ref=draft.get("revenue_forecast_ref"),
        upstream_artifacts=draft.get("upstream_artifacts", []),
        sources=draft.get("sources", []), parameters=draft.get("parameters", []),
        evidence_claims=draft.get("evidence_claims", []), limitations=draft.get("limitations", []),
    )


def _identity_from_adapter(adapter: dict[str, Any]) -> dict[str, Any]:
    return {key: adapter[key] for key in ("company_name", "as_of_date", "currency", "unit", "fiscal_year_end", "base_year", "forecast_years")}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate investment artifacts and adapt revenue forecasts")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("artifact")
    adapt_parser = subparsers.add_parser("adapt-revenue")
    adapt_parser.add_argument("forecast")
    adapt_parser.add_argument("--scope", choices=("company", "segment"), default="company")
    adapt_parser.add_argument("--segment")
    adapt_parser.add_argument("--output")
    finalize_parser = subparsers.add_parser("finalize-draft")
    finalize_parser.add_argument("draft")
    finalize_parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        if args.command == "validate":
            validate_artifact(read_json(args.artifact))
            print("artifact valid")
            return 0
        if args.command == "finalize-draft":
            write_new_json(args.output, finalize_draft(read_json(args.draft)))
            return 0
        adapter = adapt_revenue(read_json(args.forecast), args.scope, args.segment)
        if args.output:
            write_new_json(args.output, adapter)
        else:
            print(json.dumps(adapter, ensure_ascii=False, indent=2))
        return 0
    except (InvestmentArtifactError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
