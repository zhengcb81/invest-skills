"""Run a complete two-segment financials -> valuation -> SOTP -> bundle example."""

from __future__ import annotations

import json
import sys
from pathlib import Path


SUITE = Path(__file__).resolve().parents[1]
for path in (
    SUITE / "invest-core" / "scripts", SUITE / "invest-financials" / "scripts",
    SUITE / "invest-valuation" / "scripts", SUITE / "invest-sotp" / "scripts",
    SUITE / "invest-framework" / "scripts", SUITE / "tests_support",
):
    sys.path.insert(0, str(path))

from company_orchestrator import run_company  # noqa: E402
from revenue_fixtures import load_revenue_fixture  # noqa: E402


def manifest_for(forecast: dict) -> dict:
    identity = {
        key: forecast[key]
        for key in ("company_name", "as_of_date", "currency", "unit", "fiscal_year_end", "base_year", "forecast_years")
    }
    segments = []
    selections = {}
    ownership_templates = {}
    sotp_parameters = []
    for index, segment in enumerate(forecast["segments"], start=1):
        name = segment["name"]
        financial_parameters = []
        for scenario, margin in (("low", 0.08), ("base", 0.10), ("high", 0.12)):
            for year in forecast["forecast_years"]:
                financial_parameters.append({
                    "parameter_id": f"margin_{index}_{scenario}_{year}",
                    "kind": "analyst_assumption",
                    "value": margin,
                    "unit": "ratio",
                    "period": f"FY{year}",
                    "definition": f"Segment {index} net margin",
                    "dimension": "ratio",
                    "time_basis": "annual",
                    "scenario": scenario,
                    "source_ids": [],
                    "claim_ids": [],
                    "rationale": "Synthetic orchestrator test.",
                })
        valuation_parameters = [{
            "parameter_id": f"pe_{index}_{scenario}",
            "kind": "analyst_assumption",
            "value": multiple,
            "unit": "multiple",
            "period": forecast["as_of_date"],
            "definition": f"Segment {index} PE multiple",
            "dimension": "multiple",
            "time_basis": "point_in_time",
            "scenario": scenario,
            "source_ids": [],
            "claim_ids": [],
            "rationale": "Synthetic orchestrator test.",
        } for scenario, multiple in (("low", 8), ("base", 10), ("high", 12))]
        segments.append({
            "name": name,
            "financial_model": {
                "financial_model_schema_version": "2.0",
                "scope": {"type": "segment", "name": name},
                "model_family": "operating_company",
                "parameters": financial_parameters,
                "lines": [{
                    "line_id": "net_income",
                    "formula": "x0*x1",
                    "input_refs": ["revenue", f"parameter:margin_{index}_{{scenario}}_{{year}}"],
                    "input_dimensions": ["revenue", "ratio"],
                    "output_dimension": "profit", "time_basis": "annual",
                    "metric_role": "net_income", "dimension_rule": "monetary_times_rate",
                }],
                "required_outputs": ["net_income"],
                "sources": [],
                "evidence_claims": [],
                "limitations": ["Synthetic fixture."],
            },
            "valuation_model": {
                "valuation_model_schema_version": "2.0",
                "methods": [{
                    "method_id": "pe",
                    "type": "multiple",
                    "multiple_kind": "pe",
                    "metric": "net_income",
                    "metric_period": f"FY{forecast['forecast_years'][-1]}",
                    "value_basis": "equity",
                    "valuation_timing": "current",
                    "multiple_parameter_template": f"pe_{index}_{{scenario}}",
                }],
                "equity_adjustments": [],
                "parameters": valuation_parameters,
                "sources": [],
                "evidence_claims": [],
                "limitations": ["Synthetic fixture."],
            },
        })
        selections[name] = {"selection_type": "method", "method_id": "pe", "selected_value_basis": "equity"}
        ownership_id = f"ownership_{index}"
        ownership_templates[name] = ownership_id
        sotp_parameters.append({
            "parameter_id": ownership_id,
            "kind": "analyst_assumption",
            "value": 1.0,
            "unit": "ratio",
            "period": forecast["as_of_date"],
            "definition": f"Ownership of {name}",
            "dimension": "ratio",
            "time_basis": "point_in_time",
            "scenario": "shared",
            "source_ids": [],
            "claim_ids": [],
            "rationale": "Synthetic fixture.",
        })
    required_scoped = [
        *[
            {"module": module, "scope": {"type": "segment", "name": segment["name"]}}
            for segment in forecast["segments"] for module in ("financials", "valuation")
        ],
        {"module": "sotp", "scope": {"type": "company", "name": forecast["company_name"]}},
    ]
    return {
        "manifest_version": "2.0",
        "identity": identity,
        "scenario_policy": {
            "scenario_set": ["low", "base", "high"], "source": "unit_test_manifest",
            "definitions": {
                "low": "Downside demand and margin assumptions",
                "base": "Central operating assumptions",
                "high": "Upside adoption and monetization assumptions",
            },
        },
        "required_constraint_ids": [],
        "segments": segments,
        "sotp_model": {
            "sotp_model_schema_version": "2.0", "aggregation_basis": "equity",
            "segment_selections": selections,
            "ownership_parameter_templates": ownership_templates,
            "company_bridge": {
                "stage": "equity_level", "completeness_status": "complete",
                "rationale": "All synthetic segment methods already produce equity values", "adjustments": [],
            },
            "parameters": sotp_parameters,
            "sources": [],
            "evidence_claims": [],
            "limitations": ["Synthetic fixture."],
        },
        "bundle_plan": {
            "bundle_plan_schema_version": "2.0",
            "required_modules": ["financials", "valuation", "sotp"],
            "optional_modules": [],
            "required_scoped_artifacts": required_scoped,
            "optional_scoped_artifacts": [],
            "limitations": ["Synthetic orchestrator test."],
        },
        "supplemental_artifacts": [],
    }


def main() -> int:
    forecast = load_revenue_fixture("recognition")
    execution = run_company(manifest_for(forecast), forecast)
    print(json.dumps(execution["receipt"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
