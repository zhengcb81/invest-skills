# Troubleshooting

## Revenue runtime not found

Set `REVENUE_FORECAST_DIR` to the skill root containing `scripts/revenue_core.py`. Do not point it at the `scripts` directory itself.

## Engine or schema mismatch

Check [COMPATIBILITY.md](COMPATIBILITY.md). Same schema numbers do not permit arbitrary engine versions. Unsupported combinations must be migrated or opened with their original runtime.

## Artifact ID or hash mismatch

The artifact body changed after finalization. Restore the immutable file or rerun the owning module from its frozen inputs. Never repair a hash by hand.

## Semantic validator mismatch

The generic envelope may be internally hashed while module data are economically inconsistent. Rerun the owning calculator and compare its frozen model snapshot, parameters, periods, dimensions, and upstream hashes.

## Exit multiple looks too high

Confirm `valuation_timing="exit"`, `metric_period`, `horizon_years`, and the discount-rate parameter. Compare terminal value with `equity_value_current`; do not compare terminal value directly with current market value.

## Per-ADS value is missing

Provide a `security_bridge` and source-linked diluted ordinary units, ordinary-units-per-ADS, and value-date FX when currencies differ. Same-currency bridges must omit FX.

## Orchestrator refuses an output directory

Publication is immutable and atomic. Choose a new directory; the orchestrator never overwrites or merges into an existing result.

## Tests report zero cases

Do not use root `unittest discover` across hyphenated skill directories. Run `python tools/verify_suite.py`, which enumerates test files explicitly and fails on zero discovery.

## Installed Agents or Claude copy differs

Run `python tools/sync_installations.py --check` for a path-by-path hash diff. Run the full verification gate before `--apply`; the sync command updates only the ten invest skills and their shared versioned test fixtures.
