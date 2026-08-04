"""Generate revenue forecast fixtures at test time using revenue-forecast."""

from __future__ import annotations

import os
import sys
from pathlib import Path


_REVENUE_FORECAST = None
_env_dir = os.environ.get("REVENUE_FORECAST_DIR")
if _env_dir:
    candidate = Path(_env_dir).expanduser().resolve()
    if (candidate / "scripts").is_dir():
        _REVENUE_FORECAST = candidate
if _REVENUE_FORECAST is None:
    here = Path(__file__).resolve().parents[1]
    for candidate in (
        here / "revenue-forecast",
        here.parent / "revenue-forecast",
        here.parent.parent / "revenue-forecast",
    ):
        if (candidate / "scripts").is_dir():
            _REVENUE_FORECAST = candidate
            break
if _REVENUE_FORECAST is None:
    raise ImportError("revenue-forecast not found; set REVENUE_FORECAST_DIR")
if str(_REVENUE_FORECAST / "scripts") not in sys.path:
    sys.path.insert(0, str(_REVENUE_FORECAST / "scripts"))
if str(_REVENUE_FORECAST / "tests") not in sys.path:
    sys.path.insert(0, str(_REVENUE_FORECAST / "tests"))

from revenue_core import run_forecast  # noqa: E402
from test_management_targets import add_target  # noqa: E402
from test_recognition_bridge import forecast_document  # noqa: E402


_FIXTURES = None


def _make_heterogeneous_forecast() -> dict:
    """Build a three-segment multi-model forecast with two revenue constraints."""
    from test_recognition_bridge import add_parameter
    from test_data_contract import apply_parameter_contract, finalize_contract

    data = forecast_document()
    specs = {
        "Equipment": {
            "model": "capacity_utilization",
            "base": 100.0,
            "drivers": {
                "capacity": ("quantity", 100.0),
                "utilization": ("ratio", 0.8),
                "yield": ("ratio", 0.9),
                "unit_revenue": ("revenue_per_unit", 2.0),
            },
        },
        "Subscription": {
            "model": "subscription",
            "base": 60.0,
            "drivers": {
                "average_customers": ("quantity", 30.0),
                "revenue_per_customer": ("revenue_per_unit", 2.0),
            },
        },
        "Services": {
            "model": "services",
            "base": 40.0,
            "drivers": {
                "billable_capacity": ("activity", 40.0),
                "utilization": ("ratio", 0.5),
                "billing_rate": ("revenue_per_activity", 2.0),
            },
        },
    }
    base_driver_ids = []
    segment_objects = []
    for name, spec in specs.items():
        segment = {
            "name": name,
            "base_revenue_parameter_id": name.lower() + "_base",
            "recognition": {
                "mode": "modeled_as_recognized",
                "timing": "point_in_time",
                "trigger": "customer acceptance",
                "presentation": "gross",
            },
            "scenarios": {},
        }
        base_param = {
            "parameter_id": name.lower() + "_base",
            "kind": "reported_fact",
            "value": spec["base"],
            "unit": data["currency"] + " " + data["unit"],
            "period": "FY" + str(data["base_year"]),
            "definition": name + " base revenue",
            "source_ids": ["filing"],
            "scenario": "shared",
            "rationale": "Synthetic heterogeneous fixture base revenue.",
        }
        apply_parameter_contract(data, base_param, "revenue")
        data["parameters"].append(base_param)
        for scenario, multiplier in (("low", 0.85), ("base", 1.0), ("high", 1.15)):
            driver_ids = {}
            for position, (driver, (dimension, base_value)) in enumerate(
                spec["drivers"].items()
            ):
                value = base_value * (multiplier if position == 0 else 1.0)
                ids = [
                    add_parameter(
                        data,
                        name.lower() + "_" + driver + "_" + scenario + "_" + str(year),
                        value,
                        year,
                        scenario,
                        dimension=dimension,
                    )
                    for year in data["forecast_years"]
                ]
                driver_ids[driver] = ids
                if scenario == "base":
                    base_driver_ids.extend(ids)
            segment["scenarios"][scenario] = {
                "model": spec["model"],
                "driver_parameter_ids": driver_ids,
                "rationale": scenario + " heterogeneous " + name + " test",
            }
        segment_objects.append(segment)
    data["segments"] = segment_objects

    reported = sum(spec["base"] for spec in specs.values())
    reported_param = next(
        item
        for item in data["parameters"]
        if item["parameter_id"] == data["reported_total_revenue_parameter_id"]
    )
    reported_param["value"] = reported
    base_year_hist = next(
        item for item in data["historical_revenue"] if item["year"] == data["base_year"]
    )
    base_year_hist["value"] = reported
    for claim_id in base_year_hist["claim_ids"]:
        claim = next(
            item for item in data["evidence_claims"] if item["claim_id"] == claim_id
        )
        claim["extracted_value"] = reported

    cap_params = {}
    for scenario in ("low", "base", "high"):
        cap_params[scenario] = [
            add_parameter(
                data,
                "shared_cap_" + scenario + "_" + str(year),
                150,
                year,
                scenario,
                dimension="revenue",
            )
            for year in data["forecast_years"]
        ]
    data["revenue_constraints"] = [
        {
            "constraint_id": "equipment_subscription_shared_cap",
            "type": "sum_cap",
            "segments": ["Equipment", "Subscription"],
            "allocation": "proportional",
            "scenario_parameter_ids": cap_params,
            "rationale": "Shared capacity budget constrains equipment and subscription revenue.",
        }
    ]

    elim_params = {}
    for scenario in ("low", "base", "high"):
        elim_params[scenario] = [
            add_parameter(
                data,
                "services_elim_" + scenario + "_" + str(year),
                -5,
                year,
                scenario,
                dimension="revenue",
            )
            for year in data["forecast_years"]
        ]
    data["revenue_constraints"].append(
        {
            "constraint_id": "services_internal_elimination",
            "type": "elimination",
            "segment_adjustment_parameter_ids": {"Services": elim_params},
            "rationale": "Internal services delivered to other segments are eliminated from external revenue.",
        }
    )

    data["forecast_adjustments"] = []
    foundation_record = next(
        item
        for item in data["research_coverage"]
        if item["dimension"] == "company_foundation"
    )
    foundation_record.update(
        {
            "parameter_ids": [data["reported_total_revenue_parameter_id"]]
            + [f"{name.lower()}_base" for name in specs],
            "source_ids": ["filing"],
        }
    )
    growth_record = next(
        item
        for item in data["research_coverage"]
        if item["dimension"] == "growth_curve"
    )
    growth_record.update(
        {
            "status": "modeled_driver",
            "conclusion": "Multi-model heterogeneous scenario paths generate the synthetic forecast",
            "revenue_mechanism": "registered scenario revenue parameters aggregate by segment",
            "parameter_ids": base_driver_ids,
            "source_ids": ["filing"],
        }
    )
    growth_record.pop("rationale", None)
    data["growth_driver_tree"] = {
        "status": "modeled",
        "drivers": [
            {
                "driver_id": "heterogeneous_multi_model",
                "title": "Multi-model segment paths drive revenue",
                "thesis": "Capacity, subscription and services drivers determine each segment revenue.",
                "causal_chain": [
                    "registered operating drivers",
                    "model converts inputs into activity",
                    "recognition rules convert activity into revenue",
                ],
                "parameter_ids": base_driver_ids,
                "segment_attribution": [
                    {"segment_name": "Equipment", "weight": 0.5},
                    {"segment_name": "Subscription", "weight": 0.3},
                    {"segment_name": "Services", "weight": 0.2},
                ],
                "horizon": {
                    "start_year": data["forecast_years"][0],
                    "end_year": data["forecast_years"][-1],
                },
                "persistence": "multi_year_structural",
                "persistence_rationale": "Synthetic fixture treats drivers as structurally durable.",
                "evidence_nodes": [
                    {
                        "evidence_id": "heterogeneous_evidence",
                        "evidence_type": "company_execution",
                        "inference_distance": "direct",
                        "conclusion": "Synthetic operating evidence supports the heterogeneous revenue path.",
                        "claim_ids": ["claim_heterogeneous_driver"],
                    }
                ],
                "leading_indicators": ["operating driver execution"],
                "falsifiers": ["operating drivers fall below the low scenario"],
                "counterevidence_status": "searched_none_found",
                "counterevidence_rationale": "Synthetic fixture records no contrary evidence.",
            }
        ],
    }
    data["evidence_claims"].append(
        {
            "claim_id": "claim_heterogeneous_driver",
            "source_id": "filing",
            "target_type": "growth_driver",
            "target_id": "heterogeneous_evidence",
            "support_type": "rationale_support",
            "locator": "Revenue note",
            "excerpt": "Synthetic heterogeneous driver evidence is disclosed here.",
            "excerpt_sha256": None,
            "content_sha256": "a" * 64,
            "verification_status": "opened_and_checked",
            "verified_by": "test-research-agent",
            "verified_date": data["as_of_date"],
            "capture_receipt_sha256": data["sources"][0]["capture"]["receipt_sha256"],
        }
    )
    finalize_contract(data)
    return data


def _build_legacy_fixture() -> dict:
    """Build a schema 3.4 legacy forecast with a receipt that matches the legacy schema."""
    from contracts.evidence import canonical_sha256
    from revenue_publication import (
        VerificationContext,
        build_publication_receipt,
        expected_publication_gates,
    )

    result = run_forecast(forecast_document())
    result["schema_version"] = "3.4"
    result["engine_version"] = "3.10.0"
    result["publication_receipt"] = build_publication_receipt(
        result,
        VerificationContext(
            result["input_sha256"],
            expected_publication_gates(result),
            result["engine_version"],
        ),
    )
    result["result_sha256"] = canonical_sha256(
        {k: v for k, v in result.items() if k != "result_sha256"}
    )
    return result


def _build_fixtures() -> dict:
    global _FIXTURES
    if _FIXTURES is not None:
        return _FIXTURES
    _FIXTURES = {
        "direct": run_forecast(forecast_document()),
        "growth": run_forecast(forecast_document()),
        "target": run_forecast(add_target(forecast_document())),
        "effective": run_forecast(forecast_document()),
        "recognition": run_forecast(forecast_document()),
        "heterogeneous": run_forecast(_make_heterogeneous_forecast()),
        "legacy": _build_legacy_fixture(),
    }
    return _FIXTURES


def load_revenue_fixture(name: str) -> dict:
    fixtures = _build_fixtures()
    if name not in fixtures:
        raise KeyError(f"unknown revenue fixture: {name}")
    return fixtures[name]
