from __future__ import annotations

import sys
import unittest
from pathlib import Path


SUITE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SUITE / "invest-core" / "scripts"))
sys.path.insert(0, str(SUITE / "invest-financials" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(SUITE / "tests_support"))

from financial_model import run_financial_model  # noqa: E402
from invest_contracts import InvestmentArtifactError, canonical_sha256, validate_artifact  # noqa: E402
from revenue_fixtures import load_revenue_fixture  # noqa: E402
from valuation_model import run_valuation, validate_valuation_artifact  # noqa: E402


def forecast_result() -> dict:
    return load_revenue_fixture("direct")


def financial_artifact() -> dict:
    params = []
    for scenario, margin in (("low", 0.08), ("base", 0.10), ("high", 0.12)):
        for year in (2026, 2027):
            params.append({
                "parameter_id": f"fcf_margin_{scenario}_{year}", "kind": "analyst_assumption",
                "value": margin, "unit": "ratio", "period": f"FY{year}",
                "definition": "FCF margin", "dimension": "ratio", "time_basis": "annual",
                "scenario": scenario, "source_ids": [], "claim_ids": [], "rationale": "Synthetic fixture",
            })
    model = {
        "financial_model_schema_version": "2.0",
        "scope": {"type": "company", "name": "Test Co"}, "model_family": "operating_company",
        "parameters": params,
        "lines": [{
            "line_id": "free_cash_flow", "formula": "x0*x1",
            "input_refs": ["revenue", "parameter:fcf_margin_{scenario}_{year}"],
            "input_dimensions": ["revenue", "ratio"], "output_dimension": "cash_flow",
            "time_basis": "annual", "metric_role": "free_cash_flow",
            "cash_flow_basis": "fcff", "dimension_rule": "monetary_times_rate",
        }],
        "required_outputs": ["free_cash_flow"], "sources": [], "evidence_claims": [], "limitations": ["Synthetic"],
    }
    return run_financial_model(forecast_result(), model)


def valuation_input() -> dict:
    params = []
    for scenario, rate, growth in (("low", 0.12, 0.01), ("base", 0.10, 0.02), ("high", 0.09, 0.025)):
        for name, value, dimension in (("discount_rate", rate, "discount_rate"), ("terminal_growth", growth, "ratio")):
            params.append({
                "parameter_id": f"{name}_{scenario}", "kind": "analyst_assumption", "value": value,
                "unit": "ratio", "period": "2026-07-12", "definition": name.replace("_", " "),
                "dimension": dimension, "time_basis": "point_in_time", "scenario": scenario,
                "source_ids": [], "claim_ids": [], "rationale": "Synthetic fixture",
            })
    return {
        "valuation_model_schema_version": "2.0",
        "methods": [{
            "method_id": "dcf", "type": "dcf", "metric": "free_cash_flow", "value_basis": "enterprise",
            "valuation_timing": "current", "cash_flow_basis": "fcff", "terminal_model": "gordon_growth",
            "discount_rate_parameter_template": "discount_rate_{scenario}",
            "terminal_growth_parameter_template": "terminal_growth_{scenario}",
        }],
        "equity_adjustments": [], "parameters": params, "sources": [], "evidence_claims": [],
        "limitations": ["Synthetic"],
    }


class ValuationModelTests(unittest.TestCase):
    def test_dcf_consumes_upstream_cash_flow(self) -> None:
        artifact = run_valuation(financial_artifact(), valuation_input())
        validate_artifact(artifact)
        validate_valuation_artifact(artifact)
        self.assertGreater(artifact["data"]["scenario_valuations"]["base"]["methods"]["dcf"]["equity_value_current"], 0)

    def test_discount_rate_must_exceed_growth(self) -> None:
        model = valuation_input()
        next(item for item in model["parameters"] if item["parameter_id"] == "terminal_growth_base")["value"] = 0.11
        with self.assertRaisesRegex(InvestmentArtifactError, "must exceed"):
            run_valuation(financial_artifact(), model)

    def test_no_silent_method_average(self) -> None:
        model = valuation_input()
        model["method_weights"] = {"dcf": 0.8}
        with self.assertRaisesRegex(InvestmentArtifactError, "sum to one"):
            run_valuation(financial_artifact(), model)

    def test_exit_multiple_is_discounted_before_current_adjustments(self) -> None:
        model = {
            "valuation_model_schema_version": "2.0",
            "methods": [{
                "method_id": "exit_ev_sales", "type": "multiple", "multiple_kind": "ev_sales",
                "metric": "revenue", "metric_period": "FY2027", "value_basis": "enterprise",
                "valuation_timing": "exit", "multiple_parameter_template": "sales_multiple_{scenario}",
                "discount_rate_parameter_template": "exit_discount_{scenario}",
            }],
            "equity_adjustments": [], "parameters": [], "sources": [], "evidence_claims": [],
            "limitations": ["Synthetic"],
        }
        for scenario in ("low", "base", "high"):
            for name, value, dimension in (("sales_multiple", 2.0, "multiple"), ("exit_discount", 0.10, "discount_rate")):
                model["parameters"].append({
                    "parameter_id": f"{name}_{scenario}", "kind": "analyst_assumption", "value": value,
                    "unit": "ratio", "period": "2026-07-12", "definition": name,
                    "dimension": dimension, "time_basis": "point_in_time", "scenario": scenario,
                    "source_ids": [], "claim_ids": [], "rationale": "Synthetic fixture",
                })
        financials = financial_artifact()
        artifact = run_valuation(financials, model)
        result = artifact["data"]["scenario_valuations"]["base"]["methods"]["exit_ev_sales"]
        terminal = financials["data"]["annual_financials"]["base"]["2027"]["revenue"] * 2.0
        self.assertAlmostEqual(result["undiscounted_value_at_metric_period"], terminal)
        self.assertAlmostEqual(result["value_before_adjustments_current"], terminal / 1.1 ** 2)
        self.assertEqual(result["discount_years"], 2)

    def test_dcf_cash_flow_basis_mismatch_is_rejected(self) -> None:
        model = valuation_input()
        model["methods"][0]["cash_flow_basis"] = "fcfe"
        with self.assertRaisesRegex(InvestmentArtifactError, "does not match upstream"):
            run_valuation(financial_artifact(), model)

    def test_adjustment_requires_current_monetary_balance(self) -> None:
        model = valuation_input()
        model["equity_adjustments"] = [{"name": "cash", "sign": 1, "parameter_id_template": "cash_{scenario}"}]
        for scenario in ("low", "base", "high"):
            model["parameters"].append({
                "parameter_id": f"cash_{scenario}", "kind": "analyst_assumption", "value": 10.0,
                "unit": "CNY millions", "period": "2026-07-12", "definition": "cash",
                "dimension": "asset", "time_basis": "point_in_time", "scenario": scenario,
                "currency": "CNY", "scale": "millions", "source_ids": [], "claim_ids": [],
                "rationale": "Synthetic fixture",
            })
        with self.assertRaisesRegex(InvestmentArtifactError, "parameter dimension mismatch"):
            run_valuation(financial_artifact(), model)

    def test_security_bridge_calculates_ads_value(self) -> None:
        model = valuation_input()
        for scenario in ("low", "base", "high"):
            for name, value in (("shares", 1000.0), ("units_per_ads", 8.0)):
                model["parameters"].append({
                    "parameter_id": f"{name}_{scenario}", "kind": "analyst_assumption", "value": value,
                    "unit": "units", "period": "2026-07-12", "definition": name,
                    "dimension": "quantity", "time_basis": "point_in_time", "scenario": scenario,
                    "source_ids": [], "claim_ids": [], "rationale": "Synthetic fixture",
                })
        model["security_bridge"] = {
            "security_id": "TEST ADS", "security_type": "ADS", "listing_currency": "USD",
            "diluted_share_count_parameter_template": "shares_{scenario}",
            "ordinary_units_per_security_parameter_template": "units_per_ads_{scenario}",
        }
        artifact = run_valuation(financial_artifact(), model)
        result = artifact["data"]["scenario_valuations"]["base"]["methods"]["dcf"]
        self.assertAlmostEqual(result["security_value"]["per_security_value_current"], result["equity_value_current"] * 8 / 1000)

    def test_boolean_method_weight_is_rejected(self) -> None:
        model = valuation_input()
        model["method_weights"] = {"dcf": True}
        with self.assertRaisesRegex(InvestmentArtifactError, "must be numeric"):
            run_valuation(financial_artifact(), model)

    def test_semantic_validator_recomputes_valuation(self) -> None:
        artifact = run_valuation(financial_artifact(), valuation_input())
        artifact["data"]["scenario_valuations"]["base"]["methods"]["dcf"]["equity_value_current"] += 1
        body = {key: value for key, value in artifact.items() if key not in {"artifact_id", "artifact_sha256"}}
        artifact["artifact_id"] = canonical_sha256(body)
        artifact["artifact_sha256"] = canonical_sha256({key: value for key, value in artifact.items() if key != "artifact_sha256"})
        with self.assertRaisesRegex(InvestmentArtifactError, "semantic recomputation"):
            validate_valuation_artifact(artifact)

    def test_dcf_sensitivity_recomputes_current_equity_value(self) -> None:
        model = valuation_input()
        for name, value in (("discount_stress_down", 0.08), ("discount_stress_up", 0.12)):
            model["parameters"].append({
                "parameter_id": name, "kind": "scenario_stress", "value": value,
                "unit": "ratio", "period": "2026-07-12", "definition": name,
                "dimension": "discount_rate", "time_basis": "point_in_time", "scenario": "base",
                "source_ids": [], "claim_ids": [], "rationale": "Sensitivity boundary",
            })
        model["sensitivity_cases"] = [{
            "sensitivity_id": "discount_grid", "method_id": "dcf", "scenario": "base",
            "variable": "discount_rate", "value_parameter_ids": ["discount_stress_down", "discount_stress_up"],
        }]
        artifact = run_valuation(financial_artifact(), model)
        rows = artifact["data"]["sensitivity_results"][0]["cases"]
        self.assertGreater(rows[0]["equity_value_current"], rows[1]["equity_value_current"])

    def test_reverse_dcf_recovers_implied_terminal_growth(self) -> None:
        baseline_model = valuation_input()
        baseline = run_valuation(financial_artifact(), baseline_model)
        target_value = baseline["data"]["scenario_valuations"]["base"]["methods"]["dcf"]["equity_value_current"]
        model = valuation_input()
        model["parameters"].append({
            "parameter_id": "target_equity_base", "kind": "analyst_assumption", "value": target_value,
            "unit": "USD million", "period": "2026-07-12", "definition": "Target current equity value",
            "dimension": "equity", "time_basis": "point_in_time", "scenario": "base",
            "currency": "USD", "scale": "million", "source_ids": [], "claim_ids": [],
            "rationale": "Synthetic reverse valuation target",
        })
        model["reverse_cases"] = [{
            "reverse_id": "implied_growth", "method_id": "dcf", "scenario": "base",
            "target_equity_value_parameter_id": "target_equity_base", "solve_for": "terminal_growth",
        }]
        artifact = run_valuation(financial_artifact(), model)
        self.assertAlmostEqual(artifact["data"]["reverse_results"][0]["implied_value"], 0.02)


if __name__ == "__main__":
    unittest.main()
