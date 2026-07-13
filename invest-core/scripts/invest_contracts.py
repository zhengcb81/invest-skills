"""Shared contracts and revenue adapter for the modular invest skill suite."""

from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any


INVEST_SUITE_VERSION = "4.2.0"
SUPPORTED_INVEST_SUITE_VERSIONS = {"4.0.0", "4.1.0", INVEST_SUITE_VERSION}
ARTIFACT_SCHEMA_VERSION = "1.0"
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
TIME_BASES = {"annual", "point_in_time"}
SUPPORT_TYPES = {"exact_value", "rationale_support", "policy_support", "qualitative_support"}
TARGET_TYPES = {"parameter", "policy", "qualitative_assertion", "artifact_assumption"}
QUALITATIVE_DRAFT_MODULES = {"management", "moat"}


class InvestmentArtifactError(ValueError):
    """Raised when an investment artifact violates the shared contract."""


def _fail(condition: bool, message: str) -> None:
    if not condition:
        raise InvestmentArtifactError(message)


def _skill_roots() -> list[Path]:
    here = Path(__file__).resolve().parents[1]
    roots = [here.parent]
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


def canonical_sha256(value: Any) -> str:
    core, _, _ = revenue_runtime()
    return core.canonical_sha256(value)


def text_sha256(value: str) -> str:
    core, _, _ = revenue_runtime()
    return core.text_sha256(value)


def parse_iso_date(value: Any, field: str):
    core, _, _ = revenue_runtime()
    try:
        return core.parse_iso_date(value, field)
    except Exception as exc:
        raise InvestmentArtifactError(str(exc)) from exc


def finite_number(value: Any, field: str) -> float:
    core, _, _ = revenue_runtime()
    try:
        return core.finite_number(value, field)
    except Exception as exc:
        raise InvestmentArtifactError(str(exc)) from exc


def evaluate_formula(formula: str, inputs: list[float]) -> float:
    core, _, _ = revenue_runtime()
    try:
        return core.evaluate_derived_formula(formula, inputs)
    except Exception as exc:
        raise InvestmentArtifactError(str(exc)) from exc


def validate_revenue_forecast(result: dict[str, Any]) -> None:
    _, report, _ = revenue_runtime()
    try:
        report.validate_forecast_output(result)
    except Exception as exc:
        raise InvestmentArtifactError(f"invalid revenue forecast: {exc}") from exc


def revenue_reference(result: dict[str, Any]) -> dict[str, Any]:
    validate_revenue_forecast(result)
    reference = {
        "schema_version": result["schema_version"],
        "engine_version": result["engine_version"],
        "input_sha256": result["input_sha256"],
        "result_sha256": result["result_sha256"],
    }
    coverage = result.get("management_target_coverage")
    if coverage is None:
        reference.update({
            "management_target_coverage_status": "legacy_not_available",
            "management_target_counts": None,
            "management_target_summary": [],
            "management_target_summary_sha256": canonical_sha256([]),
        })
        return reference
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
    return reference


def _validate_management_target_reference(ref: dict[str, Any], *, required: bool) -> None:
    status = ref.get("management_target_coverage_status")
    if status is None and not required:
        return
    _fail(status in {"validated", "legacy_measurement_semantics", "legacy_not_available"}, "invalid management target coverage status")
    summary = ref.get("management_target_summary")
    _fail(isinstance(summary, list), "management_target_summary must be a list")
    _fail(ref.get("management_target_summary_sha256") == canonical_sha256(summary), "management target summary hash mismatch")
    if status == "legacy_not_available":
        _fail(not summary, "legacy revenue reference cannot contain a management target summary")
        _fail(ref.get("management_target_counts") is None, "legacy revenue reference target counts must be null")
        return
    coverage_hash = ref.get("management_target_coverage_sha256")
    _fail(isinstance(coverage_hash, str) and re.fullmatch(r"[0-9a-f]{64}", coverage_hash) is not None, "invalid management target coverage hash")
    counts = ref.get("management_target_counts")
    required_counts = {"communications_checked", "targets_total", "targets_modeled", "targets_unmodeled"}
    _fail(isinstance(counts, dict) and set(counts) == required_counts, "invalid management target counts")
    _fail(all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in counts.values()), "management target counts must be non-negative integers")
    _fail(counts["targets_total"] == len(summary), "management target summary count mismatch")
    target_ids = set()
    base_target_fields = {
        "target_id", "statement", "metric_name", "target_period", "raw_target_value",
        "raw_unit", "commitment_strength", "scope", "perimeter_status",
        "perimeter_notes", "comparison", "comparison_value", "comparison_currency",
        "comparison_scale", "treatment", "mapped_parameter_ids", "mapped_scenarios",
        "rationale", "source_ids", "scenario_comparison",
    }
    measurement_fields = {"measurement_basis", "measurement_periods", "measurement_rationale"}
    for target in summary:
        _fail(isinstance(target, dict), "invalid management target summary entry")
        has_measurement_semantics = measurement_fields <= set(target)
        if status == "legacy_measurement_semantics":
            _fail(set(target) == base_target_fields, "legacy management target summary has unexpected fields")
        elif required:
            _fail(set(target) == base_target_fields | measurement_fields, "management target summary missing measurement semantics")
        else:
            _fail(frozenset(target) in {frozenset(base_target_fields), frozenset(base_target_fields | measurement_fields)}, "invalid management target summary fields")
        target_id = target["target_id"]
        _fail(isinstance(target_id, str) and target_id.strip() and target_id not in target_ids, "management target IDs must be unique")
        target_ids.add(target_id)
        if has_measurement_semantics:
            _fail(target["measurement_basis"] in {"annual_period", "run_rate_at_period_end", "cumulative_periods", "ambiguous"}, f"invalid management target measurement basis: {target_id}")
            _fail(isinstance(target["measurement_periods"], list), f"invalid management target measurement periods: {target_id}")
        _fail(isinstance(target["mapped_scenarios"], list) and set(target["mapped_scenarios"]) <= set(SCENARIOS), f"invalid mapped scenarios: {target_id}")
        comparison = target["scenario_comparison"]
        _fail(isinstance(comparison, dict) and set(comparison) == set(target["mapped_scenarios"]), f"management target scenario comparison mismatch: {target_id}")
        for scenario, result in comparison.items():
            _fail(isinstance(result, dict) and isinstance(result.get("meets_target"), bool), f"invalid management target attainment: {target_id}/{scenario}")


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
            scenario: {year: float(segment["scenarios"][scenario]["recognized_revenue"][year]) for year in years}
            for scenario in SCENARIOS
        }
        scope_value = {"type": "segment", "name": segment_name}
        base_revenue = float(segment["base_revenue"])
    adapter = {
        "adapter_schema_version": "1.0",
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


def _validate_sources(sources: Any, as_of_date: str) -> dict[str, dict[str, Any]]:
    core, _, _ = revenue_runtime()
    _fail(isinstance(sources, list), "sources must be a list")
    as_of = parse_iso_date(as_of_date, "as_of_date")
    index: dict[str, dict[str, Any]] = {}
    for position, source in enumerate(sources):
        prefix = f"sources[{position}]"
        _fail(isinstance(source, dict), f"{prefix} must be an object")
        source_id = source.get("source_id")
        _fail(isinstance(source_id, str) and source_id.strip(), f"{prefix}.source_id is required")
        _fail(source_id not in index, f"duplicate source_id: {source_id}")
        _fail(core.valid_source_url(source.get("url")), f"invalid source URL: {source_id}")
        for field in ("source_type", "title", "publisher", "page_or_section"):
            _fail(isinstance(source.get(field), str) and source[field].strip(), f"{source_id}.{field} is required")
        published = parse_iso_date(source.get("published_date"), f"{source_id}.published_date")
        _fail(published <= as_of, f"future information leak: {source_id}")
        if source.get("accessed_date") is not None:
            parse_iso_date(source["accessed_date"], f"{source_id}.accessed_date")
        index[source_id] = dict(source)
    return index


def _validate_parameter_period(parameter: dict[str, Any], as_of_date: str, parameter_id: str) -> None:
    period = parameter.get("period")
    if parameter.get("time_basis") == "annual":
        _fail(isinstance(period, str) and re.fullmatch(r"FY\d{4}", period) is not None, f"{parameter_id}.period must use FYyyyy")
    else:
        point = parse_iso_date(period, f"{parameter_id}.period")
        _fail(point <= parse_iso_date(as_of_date, "as_of_date"), f"future point-in-time parameter: {parameter_id}")


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
            _fail(isinstance(inputs, list) and inputs, f"derived parameter requires inputs: {parameter_id}")
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


def _validate_claims(claims: Any, source_index: dict[str, dict[str, Any]], parameter_index: dict[str, dict[str, Any]], as_of_date: str) -> dict[str, dict[str, Any]]:
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


def artifact_reference(artifact: dict[str, Any]) -> dict[str, Any]:
    validate_artifact(artifact)
    return {
        "module": artifact["module"],
        "artifact_id": artifact["artifact_id"],
        "artifact_sha256": artifact["artifact_sha256"],
    }


def create_artifact(
    module: str,
    identity: dict[str, Any],
    scope: dict[str, str],
    data: dict[str, Any],
    *,
    scenario_set: list[str] | None = None,
    revenue_forecast_ref: dict[str, Any] | None = None,
    upstream_artifacts: list[dict[str, Any]] | None = None,
    sources: list[dict[str, Any]] | None = None,
    parameters: list[dict[str, Any]] | None = None,
    evidence_claims: list[dict[str, Any]] | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    _fail(module in MODULE_REGISTRY, f"unknown module: {module}")
    upstream_refs = [artifact_reference(item) for item in (upstream_artifacts or [])]
    artifact_body = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "invest_suite_version": INVEST_SUITE_VERSION,
        "module": module,
        "identity": dict(identity),
        "scope": dict(scope),
        "scenario_set": list(scenario_set or []),
        "revenue_forecast_ref": _normalize_revenue_reference(revenue_forecast_ref),
        "upstream_artifacts": upstream_refs,
        "sources": list(sources or []),
        "parameters": list(parameters or []),
        "evidence_claims": list(evidence_claims or []),
        "data": data,
        "limitations": list(limitations or []),
    }
    artifact = {**artifact_body, "artifact_id": canonical_sha256(artifact_body)}
    artifact["artifact_sha256"] = canonical_sha256(artifact)
    validate_artifact(artifact)
    return artifact


def validate_artifact(artifact: dict[str, Any]) -> None:
    _fail(isinstance(artifact, dict), "artifact must be an object")
    required = {
        "artifact_schema_version", "invest_suite_version", "module", "artifact_id",
        "identity", "scope", "scenario_set", "revenue_forecast_ref",
        "upstream_artifacts", "sources", "parameters", "evidence_claims",
        "data", "limitations", "artifact_sha256",
    }
    _fail(required <= set(artifact), f"artifact missing fields: {sorted(required - set(artifact))}")
    _fail(artifact["artifact_schema_version"] == ARTIFACT_SCHEMA_VERSION, "artifact schema version mismatch")
    _fail(artifact["invest_suite_version"] in SUPPORTED_INVEST_SUITE_VERSIONS, "unsupported invest suite version")
    module = artifact["module"]
    _fail(module in MODULE_REGISTRY, f"unknown module: {module}")
    identity = artifact["identity"]
    _fail(isinstance(identity, dict), "identity must be an object")
    for field in ("company_name", "as_of_date", "currency", "unit", "fiscal_year_end", "base_year", "forecast_years"):
        _fail(field in identity, f"identity missing field: {field}")
    _fail(isinstance(identity["company_name"], str) and identity["company_name"].strip(), "company_name is required")
    parse_iso_date(identity["as_of_date"], "as_of_date")
    _fail(isinstance(identity["base_year"], int), "base_year must be an integer")
    _fail(isinstance(identity["forecast_years"], list) and all(isinstance(year, int) for year in identity["forecast_years"]), "forecast_years must be integers")
    _fail(isinstance(artifact["scope"], dict) and artifact["scope"].get("type") in {"company", "segment", "comparison"}, "invalid artifact scope")
    if artifact["scope"]["type"] == "segment":
        _fail(isinstance(artifact["scope"].get("name"), str) and artifact["scope"]["name"].strip(), "segment scope requires name")
    if artifact["scope"]["type"] == "comparison":
        names = artifact["scope"].get("names")
        _fail(isinstance(names, list) and len(names) >= 2 and all(isinstance(name, str) and name.strip() for name in names), "comparison scope requires at least two names")
        _fail(len(names) == len(set(names)), "comparison scope names must be unique")
    scenario_set = artifact["scenario_set"]
    _fail(scenario_set in ([], list(SCENARIOS)), "scenario_set must be empty or low/base/high")
    _fail(isinstance(artifact["limitations"], list) and all(isinstance(item, str) and item.strip() for item in artifact["limitations"]), "limitations must contain strings")
    registry = MODULE_REGISTRY[module]
    ref = artifact["revenue_forecast_ref"]
    if registry["requires_revenue"]:
        _fail(isinstance(ref, dict), f"{module} requires revenue_forecast_ref")
    if ref is not None:
        _fail(isinstance(ref, dict), "revenue_forecast_ref must be an object or null")
        for key in ("schema_version", "engine_version", "input_sha256", "result_sha256"):
            _fail(isinstance(ref.get(key), str) and ref[key], f"revenue reference missing {key}")
        _validate_management_target_reference(ref, required=artifact["invest_suite_version"] == INVEST_SUITE_VERSION)
    upstream = artifact["upstream_artifacts"]
    _fail(isinstance(upstream, list), "upstream_artifacts must be a list")
    seen = set()
    for item in upstream:
        _fail(isinstance(item, dict) and set(item) == {"module", "artifact_id", "artifact_sha256"}, "invalid upstream reference")
        identity_key = (item["module"], item["artifact_id"])
        _fail(identity_key not in seen, "duplicate upstream artifact reference")
        seen.add(identity_key)
    for required_module in registry["upstream"]:
        _fail(any(item["module"] == required_module for item in upstream), f"{module} requires upstream module: {required_module}")
    source_index = _validate_sources(artifact["sources"], identity["as_of_date"])
    parameter_index = _validate_parameters(artifact["parameters"], source_index, identity)
    _validate_claims(artifact["evidence_claims"], source_index, parameter_index, identity["as_of_date"])
    expected_id = canonical_sha256({key: value for key, value in artifact.items() if key not in {"artifact_id", "artifact_sha256"}})
    _fail(artifact["artifact_id"] == expected_id, "artifact_id mismatch")
    payload = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    _fail(artifact["artifact_sha256"] == canonical_sha256(payload), "artifact hash mismatch")


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
