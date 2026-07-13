# Modular Invest Skills

`invest-skills` is a deterministic, source-traceable extension layer around `revenue-forecast`. Revenue remains owned by `revenue-forecast`; this suite consumes one frozen revenue result and adds financial statements, qualitative evidence modules, valuation, SOTP, comparison, orchestration, and a user-supplied decision-process sidecar.

Current release: invest-suite `5.0.0`, artifact schema `2.0`. See [COMPATIBILITY.md](COMPATIBILITY.md) and [MIGRATION.md](MIGRATION.md) before opening suite-4 artifacts or migrating an old model.

## Dependency graph

```text
revenue-forecast -> invest-core -> invest-financials -> invest-valuation -> invest-sotp
                              \-> invest-moat --------------------/
                              \-> invest-management
                              \-> invest-distribution

validated artifacts -> invest-compare
validated company graph -> invest-framework
user answers only -> invest-psychology
```

## Modules

| Skill | Owns | Key hard gate |
|---|---|---|
| `invest-core` | identity, evidence, parameters, hashes, scenario manifest, revenue adapter, security bridge | finite JSON, immutable hashes and upstream lineage |
| `invest-financials` | deterministic profit, balance-sheet and cash-flow lines | typed dimensions, cash-flow basis, identities, semantic recomputation |
| `invest-valuation` | DCF, typed multiples, asset methods, sensitivity and reverse cases | metric/value/timing compatibility; exit discount before current adjustments |
| `invest-sotp` | ownership-adjusted segment aggregation | one EV/equity basis and one complete company bridge |
| `invest-management` | dated management and governance facts and interpretations | every fact has checked claims; interpretations cite facts |
| `invest-moat` | competitive mechanisms, durability and falsifiers | mappings bind to one revenue result and registered drivers |
| `invest-distribution` | historical allocation flows, dilution and per-share history | reported/derived facts with exact evidence and one share basis |
| `invest-compare` | aligned cross-company artifact comparison | metric-specific definition, period, dimension, value basis, FX and scale |
| `invest-framework` | manifest validation, DAG orchestration, frozen bundle and report | complete segment coverage, identical scenario manifest, atomic publication |
| `invest-psychology` | user-answered process checklist | no inferred answers, no score, all questions use positive polarity |

## Quick start

Install or locate `revenue-forecast`, then point the suite to it:

```powershell
$env:REVENUE_FORECAST_DIR = "C:\path\to\revenue-forecast"
python invest-core/scripts/invest_contracts.py adapt-revenue forecast.json --scope company
python invest-financials/scripts/financial_model.py forecast.json financial-model.json --output financials.json
python invest-valuation/scripts/valuation_model.py financials.json valuation-model.json --output valuation.json
```

For a multi-segment company, use one strict manifest:

```powershell
python invest-framework/scripts/company_orchestrator.py company-manifest.json forecast.json --output-dir analysis-output
```

Every writer refuses to overwrite an existing artifact or output directory. Existing outputs can be checked without rerunning research:

```powershell
python invest-valuation/scripts/valuation_model.py --validate-artifact valuation.json
python invest-framework/scripts/bundle_validator.py --render-markdown bundle.json --markdown-output report.md
```

## Quality gate

```powershell
python tools/verify_suite.py --revenue-dir C:\path\to\revenue-forecast
```

The gate runs explicit test-file discovery, branch coverage, Ruff, mypy, compileall, JSON-Schema checks, skill-package validation, and optional installed-copy manifest comparison. It fails if zero tests are discovered.

Use `python tools/sync_installations.py --check` to compare canonical files with Agents and Claude installations, or add `--apply` after the full verification gate passes.

## Design limits

- A valid artifact proves contract integrity and deterministic recomputation, not that an analyst chose economically correct assumptions.
- Industry family registration is a semantic gate, not a complete accounting template. Material lines and identities still need explicit modeling.
- The suite does not fabricate current market prices, portfolio weights, ratings, or position sizes.
- Direct source checking remains a research responsibility; runtime validation proves internal evidence linkage, not the truth of a live webpage.
