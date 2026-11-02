"""Repeatable, self-validating Biren invest-suite E2E harness (ADR: E2E_DESIGN.md).

Runs the invest-framework orchestrator against the real formal Biren revenue
forecast and asserts every step, then compares against a golden expected
result keyed by the input forecast's sha256. A second identical run verifies
deterministic reproducibility.

Usage:
    python run_biren_invest_e2e.py [--forecast PATH] [--manifest PATH] [--update-golden] [--keep-runs]

Exit codes:
    0 = all green
    1 = a step assertion failed (regression or environment)
    2 = input/contract error (missing file, invalid forecast, missing golden key)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import shutil
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent  # invest-skills repo root
INVEST_FRAMEWORK = REPO / "invest-framework"
REVENUE_FORECAST = Path(os.environ.get("REVENUE_FORECAST_DIR") or str(REPO.parent / "revenue-forecast"))
DEFAULT_FORECAST = HERE / 'fixtures' / 'biren_forecast.json'
DEFAULT_MANIFEST = HERE / "biren_manifest.json"
EXPECTED_DIR = HERE / "expected"

# deterministic orchestration inputs: only these files matter
# (orchestrator is pure-local, no network/clock/random)


def sha256_of(path: Path) -> str:
    # CRLF (Windows) vs LF (Linux) produce different bytes for identical text
    # content; normalize so the golden hashes are byte-stable across OSes.
    # (The skill's own receipt formal_report_sha256 is already LF-normalized
    # via read_text() universal newlines, so this matches it on both OSes.)
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _report(msg: str) -> None:
    print(f"[e2e] {msg}", flush=True)


def fail(step: str, message: str) -> None:
    raise AssertionError(f"STEP {step} FAILED: {message}")


class StepCollector:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, step: str, condition: bool, message: str) -> None:
        if not condition:
            self.failures.append(f"STEP {step}: {message}")
            _report(f"  FAIL {step}: {message}")
        else:
            _report(f"  ok   {step}")


def collect_step_1_forecast_valid(forecast: dict, forecast_path: Path) -> None:
    """Step 1: the input is a valid formal forecast (publication receipt recomputes)."""
    if forecast.get("publication_receipt", {}).get("formal_output_mode") != "formal":
        raise AssertionError("STEP 1 FAILED: forecast is not a formal artifact")
    if not isinstance(forecast.get("result_sha256"), str) or len(forecast["result_sha256"]) != 64:
        raise AssertionError("STEP 1 FAILED: result_sha256 missing/invalid")
    if not isinstance(forecast.get("input_sha256"), str) or len(forecast["input_sha256"]) != 64:
        raise AssertionError("STEP 1 FAILED: input_sha256 missing/invalid")
    if not isinstance(forecast.get("input_document"), dict):
        raise AssertionError("STEP 1 FAILED: input_document not embedded (strong validation impossible)")
    # Strong validation: recompute the publication receipt from the embedded input.
    sys.path.insert(0, str(REVENUE_FORECAST / "scripts"))
    try:
        from revenue_report import validate_published_forecast  # noqa: E402
    except Exception as exc:
        raise AssertionError(f"STEP 1 FAILED: cannot import revenue-forecast strong validator: {exc}")
    try:
        validate_published_forecast(forecast, forecast["input_document"])
    except Exception as exc:
        raise AssertionError(f"STEP 1 FAILED: strong forecast validation rejected the artifact: {exc}")
    _report("  ok   STEP 1: input forecast is a strong-validated formal artifact (index independent)")


def collect_step_2_manifest_contract(manifest: dict, forecast: dict) -> None:
    """Step 2: the manifest satisfies the v2.0 contract against the forecast."""
    sys.path.insert(0, str(INVEST_FRAMEWORK / "scripts"))
    try:
        from manifest_contract import validate_manifest  # noqa: E402
    except Exception as exc:
        raise AssertionError(f"STEP 2 FAILED: cannot import manifest contract: {exc}")
    try:
        validate_manifest(manifest, forecast)
    except Exception as exc:
        raise AssertionError(f"STEP 2 FAILED: manifest contract rejected: {exc}")
    _report("  ok   STEP 2: manifest contract valid")


def run_orchestrator(manifest_path: Path, forecast_path: Path, out_dir: Path) -> None:
    env = dict(os.environ)
    env.setdefault("REVENUE_FORECAST_DIR", str(REVENUE_FORECAST))
    env["PYTHON_DOTENV_DISABLED"] = "1"
    env.pop("REVENUE_ATTESTATION_PROVIDER", None)
    print(f"[e2e-diag] REVENUE_FORECAST_DIR={env.get('REVENUE_FORECAST_DIR')}", flush=True)
    print(f"[e2e-diag] REVENUE_FORECAST={REVENUE_FORECAST} exists={REVENUE_FORECAST.is_dir()}", flush=True)
    print(f"[e2e-diag] INVEST_FRAMEWORK={INVEST_FRAMEWORK} exists={INVEST_FRAMEWORK.is_dir()}", flush=True)
    print(f"[e2e-diag] cwd will be={INVEST_FRAMEWORK}", flush=True)
    proc = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", str(HERE / "offline_cli.py"),
         str(INVEST_FRAMEWORK / "scripts" / "company_orchestrator.py"),
         str(manifest_path), str(forecast_path), "--output-dir", str(out_dir)],
        cwd=str(INVEST_FRAMEWORK), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"STEP 3 FAILED: orchestrator exited {proc.returncode}: "
            f"{proc.stdout[-1500:]}{proc.stderr[-1500:]}"
        )


def collect_steps_3_to_8(out_dir: Path, expected: dict) -> None:
    c = StepCollector()
    fin = json.loads((out_dir / "segment_001_financials.json").read_text(encoding="utf-8"))
    val = json.loads((out_dir / "segment_001_valuation.json").read_text(encoding="utf-8"))
    sotp = json.loads((out_dir / "sotp.json").read_text(encoding="utf-8"))
    bundle = json.loads((out_dir / "bundle.json").read_text(encoding="utf-8"))
    receipt = json.loads((out_dir / "receipt.json").read_text(encoding="utf-8"))
    report = (out_dir / "report.md").read_text(encoding="utf-8")

    # A fresh public read verifies every emitted member and state transition.
    # This catches changed intermediate files, even when the bundle is intact.
    from company_orchestrator import validate_execution
    try:
        validate_execution({
            "normalized_manifest": json.loads((out_dir / "manifest.snapshot.json").read_text(encoding="utf-8")),
            "frozen_revenue_forecast": json.loads((out_dir / "revenue_forecast.snapshot.json").read_text(encoding="utf-8")),
            "financials": [fin], "valuations": [val], "sotp": sotp,
            "supplementals": [], "bundle": bundle, "report_markdown": report,
            "output_files": receipt["output_files"], "receipt": receipt,
        })
    except Exception as exc:
        fail("3", f"emitted execution failed its public validation: {exc}")
    c.check("3", sorted(path.name for path in out_dir.iterdir()) == sorted(receipt["output_files"]),
            "emitted file inventory differs from the execution receipt")

    # Step 4: financials compliance + terminal net income
    fin_rec = (fin.get("compliance_receipt") or {}).get("receipt_sha256")
    c.check("4a", bool(fin_rec), "financials compliance receipt missing")
    for scen, exp in expected["financials_terminal_net_income"].items():
        actual = fin["data"]["annual_financials"][scen]["2030"].get("net_income")
        c.check(f"4b-{scen}", actual is not None and math.isclose(actual, exp, rel_tol=1e-9, abs_tol=1e-6),
                f"terminal net_income {scen}: expected {exp}, got {actual}")
    # revenue must equal the forecast's effective revenue (no re-forecast inside invest)
    fc_eff = expected["revenue_effective_2030"]
    actual_rev = fin["data"]["annual_financials"]["base"]["2030"].get("revenue")
    c.check("4c", actual_rev is not None and math.isclose(actual_rev, fc_eff["base"], rel_tol=1e-9, abs_tol=1e-6),
            f"financials revenue must equal forecast effective revenue: expected {fc_eff['base']}, got {actual_rev}")

    # Step 5: valuation method + equity
    c.check("5a", val["data"]["scenario_valuations"]["base"]["methods"].get("ps") is not None,
            "valuation must use ps method")
    for scen, exp in expected["valuation_equity"].items():
        actual = val["data"]["scenario_valuations"][scen]["methods"]["ps"].get("value_before_adjustments_current")
        c.check(f"5b-{scen}", actual is not None and math.isclose(actual, exp, rel_tol=1e-9, abs_tol=1e-6),
                f"valuation equity {scen}: expected {exp}, got {actual}")

    # Step 6: SOTP segment coverage + equity
    c.check("6a", set(sotp["data"]["scenario_sotp"]) == {"low", "base", "high"}, "SOTP scenario coverage")
    for scen, exp in expected["sotp_equity"].items():
        actual = sotp["data"]["scenario_sotp"][scen].get("sotp_equity_value_current")
        c.check(f"6b-{scen}", actual is not None and math.isclose(actual, exp, rel_tol=1e-9, abs_tol=1e-6),
                f"SOTP equity {scen}: expected {exp}, got {actual}")

    # Step 7: bundle module counts + upstream hash chain
    c.check("7a", bundle["data"]["module_counts"] == expected["module_counts"],
            f"module_counts {bundle['data']['module_counts']} != expected {expected['module_counts']}")
    c.check("7b", sha256_of(out_dir / "bundle.json") == expected["bundle_sha256"],
            "bundle file hash drift")

    # Step 8: receipt + report
    c.check("8a", receipt.get("status") == "pass", f"receipt status {receipt.get('status')}")
    c.check("8b", receipt.get("freeform_formal_output_allowed") is False, "freeform must be false")
    from invest_contracts import text_sha256
    c.check("8c", receipt.get("formal_report_sha256") == text_sha256(report),
            "receipt formal_report_sha256 must equal report.md hash")
    c.check("8d", expected["report_contains_drivers"] and "未来收入主要驱动力" in report,
            "report missing revenue driver section")
    c.check("8e", expected["report_contains_value_table"] and "当前价值" in report,
            "report missing value table")
    c.check("8f", sha256_of(out_dir / "receipt.json") == expected["receipt_sha256"],
            "receipt file hash drift")

    if c.failures:
        raise AssertionError("; ".join(c.failures))
    _report("  ok   STEPS 4-8: financials / valuation / SOTP / bundle / receipt / report all green")


ECONOMIC_KEYS = (
    "financials_terminal_net_income", "valuation_equity", "sotp_equity", "revenue_effective_2030",
)


def economic_differences(actual: dict, expected: dict) -> list[str]:
    differences = []
    if actual.get("module_counts") != expected.get("module_counts"):
        differences.append("module_counts changed")
    for key in ECONOMIC_KEYS:
        for scenario in ("low", "base", "high"):
            a = (actual.get(key) or {}).get(scenario)
            g = (expected.get(key) or {}).get(scenario)
            if not (type(a) in (int, float) and type(g) in (int, float)
                    and math.isclose(a, g, rel_tol=1e-9, abs_tol=1e-6)):
                differences.append(f"{key}[{scenario}]: expected {g} got {a}")
    return differences


def check_runs(args, forecast: dict, forecast_path: Path, manifest_path: Path,
               golden_path: Path, run_root: Path) -> int:
    hashes_run = []
    for attempt in (1, 2):
        out_dir = run_root / f"run-{attempt}"
        run_orchestrator(manifest_path, forecast_path, out_dir)
        hashes_run.append({name: sha256_of(out_dir / filename) for name, filename in (
            ("bundle", "bundle.json"), ("report", "report.md"), ("receipt", "receipt.json"),
        )})
        _report(f"  run {attempt} ok: bundle={hashes_run[-1]['bundle'][:12]} "
                f"report={hashes_run[-1]['report'][:12]}")
    if hashes_run[0] != hashes_run[1]:
        fail("9", "two identical inputs produced different outputs")
    _report("  ok   STEP 9: outputs byte-identical across two runs")
    out_dir = run_root / "run-1"
    def read(name):
        return json.loads((out_dir / name).read_text(encoding="utf-8"))
    fin, val, sotp, bundle, receipt = map(read, (
        "segment_001_financials.json", "segment_001_valuation.json", "sotp.json", "bundle.json", "receipt.json",
    ))
    report = (out_dir / "report.md").read_text(encoding="utf-8")
    actual = {
        "input_forecast_sha256": forecast["input_sha256"],
        "input_forecast_input_sha256": forecast["input_sha256"],
        "input_forecast_result_sha256": forecast["result_sha256"],
        "module_counts": bundle["data"]["module_counts"],
        "bundle_sha256": hashes_run[0]["bundle"],
        "report_sha256": hashes_run[0]["report"], "receipt_sha256": hashes_run[0]["receipt"],
        "receipt_status": receipt.get("status"),
        "receipt_freeform": receipt.get("freeform_formal_output_allowed"),
        "receipt_formal_report_sha256": receipt.get("formal_report_sha256"),
        "revenue_effective_2030": {s: forecast["segments"][0]["scenarios"][s]["effective_revenue"]["2030"] for s in ("low", "base", "high")},
        "financials_terminal_net_income": {s: fin["data"]["annual_financials"][s]["2030"]["net_income"] for s in ("low", "base", "high")},
        "valuation_equity": {s: val["data"]["scenario_valuations"][s]["methods"]["ps"]["value_before_adjustments_current"] for s in ("low", "base", "high")},
        "sotp_equity": {s: sotp["data"]["scenario_sotp"][s]["sotp_equity_value_current"] for s in ("low", "base", "high")},
        "report_contains_drivers": "未来收入主要驱动力" in report,
        "report_contains_value_table": "当前价值" in report,
    }
    for repo, path in (("invest_skills", REPO), ("revenue_forecast", REVENUE_FORECAST)):
        actual[f"{repo}_head"] = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True,
        ).stdout.strip() or None
    golden = json.loads(golden_path.read_text(encoding="utf-8")) if golden_path.is_file() else None
    if golden is not None:
        differences = economic_differences(actual, golden)
        if differences:
            fail("10", "economic drift (also blocks --update-golden): " + "; ".join(differences))
    # These checks previously existed but were never invoked by main.
    for attempt in (1, 2):
        collect_steps_3_to_8(run_root / f"run-{attempt}", actual if args.update_golden else golden)
    if args.update_golden:
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(json.dumps(actual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _report(f"golden metadata updated with unchanged economic values: {golden_path.name}")
    else:
        keys = ("input_forecast_input_sha256", "input_forecast_result_sha256", "bundle_sha256", "report_sha256", "receipt_sha256", "receipt_status", "receipt_freeform", "receipt_formal_report_sha256", "module_counts", "report_contains_drivers", "report_contains_value_table")
        differences = [f"{key}: expected {golden.get(key)} got {actual.get(key)}" for key in keys if actual.get(key) != golden.get(key)]
        if differences:
            fail("10", "golden mismatch: " + "; ".join(differences))
        _report("  ok   STEP 10: golden comparison identical")
    _report(f"E2E PASS: forecast={forecast['input_sha256'][:12]} invest_head={actual['invest_skills_head']}")
    return 0


def main() -> int:
    from offline_cli import install_offline_guard
    install_offline_guard()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast", type=Path, default=DEFAULT_FORECAST)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--expected-dir", type=Path, default=EXPECTED_DIR)
    parser.add_argument("--runs-dir", type=Path, help="existing parent for one fresh owned temporary tree")
    parser.add_argument("--update-golden", action="store_true", help="refresh technical metadata only if existing economic values are unchanged")
    parser.add_argument("--keep-runs", action="store_true", help="retain only this invocation's fresh temporary tree")
    args = parser.parse_args()
    forecast_path, manifest_path = args.forecast.resolve(), args.manifest.resolve()
    try:
        forecast = json.loads(forecast_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        collect_step_1_forecast_valid(forecast, forecast_path)
        collect_step_2_manifest_contract(manifest, forecast)
        golden_path = args.expected_dir.resolve() / f"expected-{forecast['input_sha256'][:12]}.json"
        if not golden_path.is_file() and not args.update_golden:
            raise ValueError(f"no golden for input {forecast['input_sha256'][:12]}")
        if args.runs_dir is not None and not args.runs_dir.is_dir():
            raise ValueError("--runs-dir must be an existing parent directory")
    except (AssertionError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    run_root = Path(tempfile.mkdtemp(prefix="invest-e2e-", dir=args.runs_dir))
    previous_registry = os.environ.get("REVENUE_PUBLICATION_REGISTRY")
    os.environ["REVENUE_PUBLICATION_REGISTRY"] = str(run_root / "registry")
    _report(f"owned runs: {run_root}")
    try:
        return check_runs(args, forecast, forecast_path, manifest_path, golden_path, run_root)
    except (AssertionError, OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        if previous_registry is None:
            os.environ.pop("REVENUE_PUBLICATION_REGISTRY", None)
        else:
            os.environ["REVENUE_PUBLICATION_REGISTRY"] = previous_registry
        if args.keep_runs:
            _report(f"kept owned runs: {run_root}")
        else:
            shutil.rmtree(run_root)
            _report(f"owned runs removed: {not run_root.exists()}")


if __name__ == "__main__":
    raise SystemExit(main())
