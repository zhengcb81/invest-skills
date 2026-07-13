# Investment artifact contract

Every schema `2.0` module artifact contains:

- `artifact_schema_version` and `invest_suite_version`;
- `module`, `artifact_id`, and `artifact_sha256`;
- immutable identity: company, information date, reporting currency/unit, fiscal year end, base year, forecast years;
- `scope`: `company`, a named `segment`, or a named multi-company `comparison`;
- `scenario_set`: either empty for non-scenario research or exactly `low/base/high`;
- a hashed `scenario_manifest` for scenario-bound artifacts, with one explicit definition per scenario;
- `revenue_forecast_ref` when the module consumes revenue;
- `upstream_artifacts`, each with module, artifact ID, and complete artifact hash;
- direct `sources`, `parameters`, and `evidence_claims` owned by this module;
- deterministic `data` plus explicit `limitations`.

The content-derived artifact ID covers every body field before IDs are added. The artifact hash then covers every field except `artifact_sha256`. An upstream artifact is referenced by its immutable hash, never by a mutable filename alone.

Schema `1.0` / suite `4.0.0`-`4.2.0` artifacts remain structurally verifiable as immutable legacy records. They do not gain schema `2.0` semantic guarantees, scenario manifests, complete snapshots, or module recalculation merely because a newer runtime opens them.

## Revenue reference

The revenue reference records `schema_version`, `engine_version`, `input_sha256`, and `result_sha256`. Creating it first calls the full revenue output validator, which recomputes segment models, recognition, consolidation, CAGR, sensitivity, confidence, management-target coverage, and the result hash.

For revenue schema 3.1 and later, the reference also carries:

- `management_target_coverage_status=validated`;
- a hash of the complete target-coverage block;
- checked-communication and modeled/unmodeled target counts;
- a separately hashed immutable target summary containing statement, perimeter, treatment, mapped scenarios, and scenario attainment.

Schema 3.2 summaries additionally preserve annual/run-rate/cumulative/ambiguous measurement basis, explicit model periods, and the measurement rationale. Downstream modules copy this summary solely to make revenue assumptions visible beside profit, valuation, and SOTP results. They may not edit it or use it to create another revenue forecast.

Revenue schema 3.0 references are labeled `legacy_not_available`; schema 3.1 references are labeled `legacy_measurement_semantics` because they included targets but did not distinguish cumulative from single-period measurement. Neither label means management had no targets.

## Scope

A company-scoped adapter uses consolidated company revenue. A segment-scoped adapter uses the revenue-owned `effective_revenue` path when present; for immutable pre-3.3 forecasts it falls back to `recognized_revenue`. Effective revenue is still calculated and independently validated by `revenue-forecast`, never by invest-core. The adapter copies values and identities; it never estimates or modifies them.

## Security bridge

Valuation and SOTP share one bridge from current equity value to a listed security. It requires source-linked diluted ordinary units, ordinary units per security or ADS, listing currency, and value-date FX when currencies differ. Same-currency bridges must not carry an FX parameter. The bridge reports total equity and per-security current value separately.
