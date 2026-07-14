# Declarative company manifest

Use this contract when one company has multiple economically different revenue curves and each curve must pass through its own financial and valuation model before SOTP.

## Non-negotiable execution model

```text
validated frozen revenue result
  -> validate manifest identity, scenarios, constraints, and exact segment coverage
  -> for each manifest segment in declared order:
       run financial_model(scope=that segment)
       validate financial artifact
       run valuation_model(financial artifact)
       validate valuation artifact
  -> run SOTP over every segment valuation
  -> validate bundle dependency graph and hashes
  -> render report from validated bundle
  -> validate ordered pass-state receipt and report hash
  -> atomically publish a new output directory
```

The orchestrator owns only this wiring. Revenue formulas remain in `revenue-forecast`; profit/cash-flow formulas remain in `invest-financials`; valuation formulas remain in `invest-valuation`; aggregation remains in `invest-sotp`.

## Top-level fields

| Field | Required | Exact rule |
|---|---|---|
| `manifest_version` | yes | Must equal `2.0`. |
| `identity` | yes | Exact company identity copied from the frozen forecast; no missing or extra fields. |
| `scenario_policy` | yes | Exactly `scenario_set=[low,base,high]` and `alignment=global_labels`. |
| `required_constraint_ids` | yes | Ordered list exactly equal to the frozen forecast's constraint IDs; use `[]` when none. |
| `segments` | yes | One and only one config for every frozen revenue segment. |
| `sotp_model` | yes | Complete selections, ownership parameters, adjustments, evidence, and limitations. |
| `bundle_plan` | yes | Required/optional modules and limitations; required must include financials, valuation, and SOTP. |
| `supplemental_artifacts` | no | Immutable management, moat, or distribution declarations; defaults to `[]`. |

Unknown top-level fields fail. Any field named like an API key, token, password, secret, authorization, or private key fails at any nesting level.

## Identity

```json
"identity": {
  "company_name": "Example Co",
  "as_of_date": "2026-07-13",
  "currency": "USD",
  "unit": "million",
  "fiscal_year_end": "12-31",
  "base_year": 2025,
  "forecast_years": [2026, 2027, 2028]
}
```

Do not retype or reinterpret these values. Copy them from the validated forecast. A single mismatch blocks execution.

## Segment entry

```json
{
  "name": "Subscription",
  "financial_model": {
    "financial_model_schema_version": "2.0",
    "scope": {"type": "segment", "name": "Subscription"},
    "model_family": "operating_company",
    "parameters": [],
    "lines": [],
    "required_outputs": [],
    "sources": [],
    "evidence_claims": [],
    "limitations": []
  },
  "valuation_model": {
    "valuation_model_schema_version": "2.0",
    "methods": [],
    "equity_adjustments": [],
    "parameters": [],
    "sources": [],
    "evidence_claims": [],
    "limitations": []
  }
}
```

The example shows shape only: empty `lines`, `required_outputs`, and `methods` will fail in the leaf modules. Fill them with explicit, source-linked or rationale-backed assumptions. The financial scope name must match the entry name byte-for-byte. Never place a revenue override, profit override, cash-flow override, or scenario probabilities in either model.

Different segments may use different financial line DAGs and valuation methods. Low/base/high inside one segment must use the same line DAG and method set; only registered scenario parameters vary.

## SOTP rules

- `segment_selections` and `ownership_parameter_templates` must cover the manifest segment names exactly.
- Select one named valuation method or `weighted` only when the valuation artifact contains explicit method weights summing to one.
- Ownership, net debt, non-operating assets, minority interests, and holding-company adjustments are never defaulted.
- SOTP consumes every segment valuation and never forecasts a missing segment.
- All selections use one `aggregation_basis`; the complete company bridge declares `enterprise_to_equity` or `equity_level` treatment.

## Bundle plan

```json
"bundle_plan": {
  "bundle_plan_schema_version": "2.0",
  "required_modules": ["financials", "valuation", "sotp"],
  "optional_modules": ["moat", "management"],
  "required_scoped_artifacts": [],
  "optional_scoped_artifacts": [],
  "limitations": ["State any module intentionally omitted from this execution."]
}
```

An optional module that is absent becomes a bundle limitation. A required module that is absent blocks the bundle. Required and optional module lists must be unique and disjoint.

## Output contract

The CLI writes a brand-new directory containing:

```text
manifest.snapshot.json
revenue_forecast.snapshot.json
segment_001_financials.json
segment_001_valuation.json
...
sotp.json
supplemental_001_management.json
bundle.json
report.md
receipt.json
```

`receipt.json` binds the manifest hash, revenue input/result and workflow-receipt hashes, current/legacy revenue status, scenario-manifest hash, frozen revenue reference, global scenario set, ordered state transitions, segment and supplemental counts, every artifact ID/hash and compliance-receipt hash, report hash, output filenames, formal-output authority, and its own hash. Segment file order follows manifest order and is recorded through each artifact scope.

The output directory must not exist. The command calculates and validates all artifacts first, writes a unique sibling temporary directory, then renames it into place. Any exception removes the temporary directory and produces no success bundle.

On CLI failure, the output directory remains absent and the command writes a non-overwriting sibling `<output-name>.failure.json`. It records the failed stage (`load_inputs`, `orchestrate`, or `publish`), exception type/message, available manifest/revenue hashes, `success_output_created=false`, and a receipt hash. It never includes the manifest body or secret value. If that failure receipt already exists, it is not overwritten and the CLI reports the receipt-write error separately.

## Weak-model checklist

Before running, verify every item literally; do not infer missing values:

1. Forecast output validation passes and `result_sha256` is unchanged.
2. Manifest identity exactly equals the forecast identity.
3. Scenario policy is exactly low/base/high with global labels.
4. `required_constraint_ids` exactly equals the forecast constraint order.
5. Manifest segment names exactly equal all forecast segment names.
6. Every financial scope is `segment` with the exact corresponding name.
7. Every financial input is revenue, an earlier line, or a registered parameter.
8. Every valuation method consumes a named upstream metric and has all scenario parameters.
9. SOTP selections and ownership cover every segment exactly.
10. No secret, network action, override, default multiple, default discount rate, default ownership, or output path reuse exists.
11. Run the full test suites before accepting a framework change.
12. Require the report to equal the bundle renderer and the execution receipt to recompute exactly.
13. Treat a pass receipt as `candidate` evidence; it is not an independent human review or proof that external facts are true.

## Required regression command

```powershell
python tools/verify_suite.py --revenue-dir C:\path\to\revenue-forecast
```
