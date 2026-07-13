"""Strict declarative manifest contract for deterministic company orchestration."""

from __future__ import annotations

import copy
import re
from typing import Any


MANIFEST_VERSION = "2.0"
SCENARIOS = ("low", "base", "high")
IDENTITY_FIELDS = (
    "company_name", "as_of_date", "currency", "unit", "fiscal_year_end", "base_year", "forecast_years",
)
SECRET_FIELD_PATTERN = re.compile(r"(^|_)(api_?key|token|password|secret|authorization|private_?key)$", re.IGNORECASE)


class ManifestContractError(ValueError):
    """Raised when a company manifest is incomplete, unsafe, or inconsistent."""


def _require(condition: object, message: str) -> None:
    if not condition:
        raise ManifestContractError(message)


def _reject_secret_fields(value: Any, path: str = "manifest") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            _require(not SECRET_FIELD_PATTERN.search(normalized), f"secret-like field is prohibited: {path}.{key}")
            _reject_secret_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secret_fields(child, f"{path}[{index}]")


def scenario_manifest_from_policy(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "scenario_manifest_version": "1.0", "source": policy["source"],
        "scenarios": [
            {"scenario": scenario, "definition": policy["definitions"][scenario]}
            for scenario in SCENARIOS
        ],
    }


def _scope_key(module: str, scope: dict[str, Any]) -> tuple[str, str, str]:
    return module, scope["type"], scope.get("name", "")


def _validate_manifest_header(manifest: dict[str, Any], forecast: dict[str, Any]) -> dict[str, Any]:
    allowed_top_level = {
        "manifest_version", "identity", "scenario_policy", "required_constraint_ids",
        "segments", "sotp_model", "bundle_plan", "supplemental_artifacts",
    }
    _require(not (set(manifest) - allowed_top_level), f"unsupported company manifest fields: {sorted(set(manifest) - allowed_top_level)}")
    _require(manifest.get("manifest_version") == MANIFEST_VERSION, "unsupported company manifest_version")
    identity = manifest.get("identity")
    _require(isinstance(identity, dict) and set(identity) == set(IDENTITY_FIELDS), "manifest identity must contain the exact identity fields")
    assert isinstance(identity, dict)
    forecast_identity = {field: forecast.get(field) for field in IDENTITY_FIELDS}
    _require(identity == forecast_identity, "manifest identity does not match frozen revenue forecast")
    return identity


def _validate_scenario_policy(policy: Any) -> None:
    _require(isinstance(policy, dict), "scenario_policy must be an object")
    assert isinstance(policy, dict)
    _require(set(policy) == {"scenario_set", "source", "definitions"}, "scenario_policy contains unsupported or missing fields")
    _require(policy["scenario_set"] == list(SCENARIOS), "scenario_policy must use exactly low/base/high")
    _require(isinstance(policy["source"], str) and policy["source"].strip(), "scenario_policy.source is required")
    definitions = policy["definitions"]
    _require(isinstance(definitions, dict) and list(definitions) == list(SCENARIOS), "scenario definitions must be ordered low/base/high")
    assert isinstance(definitions, dict)
    _require(all(isinstance(value, str) and value.strip() for value in definitions.values()), "scenario definitions must be non-empty")


def _validate_constraint_ids(required: Any, forecast: dict[str, Any]) -> None:
    _require(isinstance(required, list) and len(required) == len(set(required)), "required_constraint_ids must be a unique list")
    actual = [item.get("constraint_id") for item in forecast.get("revenue_constraints", [])]
    _require(required == actual, "manifest required_constraint_ids do not match frozen revenue constraints")


def _validate_segment_config(config: Any, position: int, names: list[str]) -> str:
    prefix = f"segments[{position}]"
    _require(isinstance(config, dict) and set(config) == {"name", "financial_model", "valuation_model"}, f"{prefix} contains unsupported or missing fields")
    assert isinstance(config, dict)
    name = config.get("name")
    _require(isinstance(name, str) and name.strip() and name not in names, f"{prefix}.name must be unique")
    assert isinstance(name, str)
    financial_model = config.get("financial_model")
    valuation_model = config.get("valuation_model")
    _require(isinstance(financial_model, dict), f"{prefix}.financial_model must be an object")
    assert isinstance(financial_model, dict)
    _require(financial_model.get("financial_model_schema_version") == "2.0", f"financial model schema must be 2.0: {name}")
    _require(financial_model.get("scope") == {"type": "segment", "name": name}, f"financial scope must exactly match manifest segment: {name}")
    _require(isinstance(valuation_model, dict) and valuation_model.get("valuation_model_schema_version") == "2.0", f"valuation model schema must be 2.0: {name}")
    assert isinstance(valuation_model, dict)
    for forbidden in ("revenue_override", "profit_override", "cash_flow_override", "scenario_probabilities"):
        _require(forbidden not in financial_model and forbidden not in valuation_model, f"manifest contains prohibited override: {name}/{forbidden}")
    return name


def _validate_segments(segment_configs: Any, forecast: dict[str, Any]) -> list[str]:
    _require(isinstance(segment_configs, list) and segment_configs, "manifest segments must be a non-empty list")
    assert isinstance(segment_configs, list)
    names: list[str] = []
    for position, config in enumerate(segment_configs):
        names.append(_validate_segment_config(config, position, names))
    revenue_names = [segment.get("name") for segment in forecast.get("segments", [])]
    _require(set(names) == set(revenue_names) and len(names) == len(revenue_names), "manifest segments must cover every revenue segment exactly")
    return names


def _validate_sotp_model(sotp_model: Any, names: list[str]) -> None:
    _require(isinstance(sotp_model, dict) and sotp_model.get("sotp_model_schema_version") == "2.0", "sotp_model schema must be 2.0")
    assert isinstance(sotp_model, dict)
    selections = sotp_model.get("segment_selections")
    ownership = sotp_model.get("ownership_parameter_templates")
    _require(isinstance(selections, dict) and set(selections) == set(names), "SOTP segment selections must cover every manifest segment")
    _require(isinstance(ownership, dict) and set(ownership) == set(names), "SOTP ownership templates must cover every manifest segment")


def _validate_supplementals(supplemental: Any, names: list[str]) -> set[tuple[str, str, str]]:
    _require(isinstance(supplemental, list), "supplemental_artifacts must be a list")
    assert isinstance(supplemental, list)
    supplemental_keys: set[tuple[str, str, str]] = set()
    supplemental_ids: set[str] = set()
    for position, item in enumerate(supplemental):
        _require(isinstance(item, dict) and set(item) == {"module", "scope", "artifact_id", "artifact_sha256", "required"}, f"invalid supplemental_artifacts[{position}]")
        assert isinstance(item, dict)
        _require(item["module"] in {"management", "moat", "distribution"}, f"unsupported supplemental module: {item['module']}")
        scope = item["scope"]
        _require(isinstance(scope, dict) and scope.get("type") in {"company", "segment"}, f"invalid supplemental scope: {position}")
        assert isinstance(scope, dict)
        if scope["type"] == "segment":
            _require(scope.get("name") in names, f"supplemental segment is not in manifest: {scope.get('name')}")
        key = _scope_key(item["module"], scope)
        _require(key not in supplemental_keys, f"duplicate supplemental module/scope: {key}")
        supplemental_keys.add(key)
        _require(isinstance(item["artifact_id"], str) and re.fullmatch(r"[0-9a-f]{64}", item["artifact_id"]) is not None, "invalid supplemental artifact_id")
        _require(isinstance(item["artifact_sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", item["artifact_sha256"]) is not None, "invalid supplemental artifact_sha256")
        _require(item["artifact_id"] not in supplemental_ids, "duplicate supplemental artifact_id")
        supplemental_ids.add(item["artifact_id"])
        _require(isinstance(item["required"], bool), "supplemental required must be boolean")
    return supplemental_keys


def _validate_bundle_plan(bundle_plan: Any, names: list[str], company_name: str, supplemental_keys: set[tuple[str, str, str]]) -> None:
    _require(isinstance(bundle_plan, dict), "bundle_plan must be an object")
    assert isinstance(bundle_plan, dict)
    allowed_fields = {
        "bundle_plan_schema_version", "required_modules", "optional_modules",
        "required_scoped_artifacts", "optional_scoped_artifacts", "limitations",
    }
    _require(not (set(bundle_plan) - allowed_fields), "bundle_plan contains unsupported fields")
    _require(bundle_plan.get("bundle_plan_schema_version") == "2.0", "bundle plan schema must be 2.0")
    required_modules = bundle_plan.get("required_modules")
    optional_modules = bundle_plan.get("optional_modules")
    limitations = bundle_plan.get("limitations", [])
    _require(isinstance(required_modules, list) and len(required_modules) == len(set(required_modules)), "bundle required_modules must be unique")
    _require(isinstance(required_modules, list) and {"financials", "valuation", "sotp"} <= set(required_modules), "bundle required_modules must include financials, valuation, and sotp")
    _require(isinstance(optional_modules, list) and len(optional_modules) == len(set(optional_modules)), "bundle optional_modules must be unique")
    assert isinstance(required_modules, list) and isinstance(optional_modules, list)
    _require(not (set(required_modules) & set(optional_modules)), "bundle required and optional modules must be disjoint")
    _require(isinstance(limitations, list) and all(isinstance(item, str) and item.strip() for item in limitations), "bundle limitations must be non-empty strings")
    required_scoped = bundle_plan.get("required_scoped_artifacts", [])
    optional_scoped = bundle_plan.get("optional_scoped_artifacts", [])
    _require(isinstance(required_scoped, list) and isinstance(optional_scoped, list), "bundle scoped artifact lists are required")
    assert isinstance(required_scoped, list) and isinstance(optional_scoped, list)
    required_keys = {_scope_key(item["module"], item["scope"]) for item in required_scoped if isinstance(item, dict) and isinstance(item.get("scope"), dict)}
    expected_core_keys = {
        *{("financials", "segment", name) for name in names},
        *{("valuation", "segment", name) for name in names},
        ("sotp", "company", company_name),
    }
    _require(expected_core_keys <= required_keys, "bundle required_scoped_artifacts must cover every segment financial/valuation and company SOTP")
    declared_keys = {
        _scope_key(item["module"], item["scope"])
        for item in [*required_scoped, *optional_scoped]
        if isinstance(item, dict) and isinstance(item.get("scope"), dict)
    }
    _require(supplemental_keys <= declared_keys, "every supplemental artifact must be declared in bundle scoped requirements")


def validate_manifest(manifest: Any, forecast: dict[str, Any]) -> dict[str, Any]:
    _require(isinstance(manifest, dict), "company manifest must be an object")
    assert isinstance(manifest, dict)
    _reject_secret_fields(manifest)
    identity = _validate_manifest_header(manifest, forecast)
    _validate_scenario_policy(manifest.get("scenario_policy"))
    _validate_constraint_ids(manifest.get("required_constraint_ids"), forecast)
    names = _validate_segments(manifest.get("segments"), forecast)
    _validate_sotp_model(manifest.get("sotp_model"), names)
    supplemental_keys = _validate_supplementals(manifest.get("supplemental_artifacts", []), names)
    _validate_bundle_plan(manifest.get("bundle_plan"), names, identity["company_name"], supplemental_keys)
    return copy.deepcopy(manifest)
