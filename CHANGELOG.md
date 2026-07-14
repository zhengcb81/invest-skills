# Changelog

## 5.1.0 - 2026-07-14

- Added revenue reference and adapter schema 1.1 with separate hashes for the complete revenue-owned growth-driver analysis and its compact downstream summary.
- Added explicit `validated`, `data_gap`, and `legacy_not_available` driver states; revenue schema 3.3 cannot silently omit growth-driver metadata.
- Upgraded framework bundle data to 2.1, enforced exact frozen-forecast/reference equality, and added a concise growth-driver section to the read-only report.
- Upgraded moat and management qualitative contracts to 2.1 so mechanisms and execution assessments reuse revenue-owned driver IDs instead of recreating revenue registries.
- Added comparison model 2.1 `growth_drivers` mode over validated framework bundles with hard information-date, horizon, currency and unit alignment.
- Preserved immutable validation for suite 5.0 artifact schema 2.0 and suite 4.0-4.2 artifact schema 1.0. Financial, valuation and SOTP formulas are unchanged.

## 5.0.0 - 2026-07-13

- Introduced artifact schema 2.0 with strict finite JSON, typed identity and period rules, hashed scenario manifests, complete frozen snapshots, and semantic recalculation validators.
- Corrected exit-multiple timing: terminal values are discounted to the information date before current balance-sheet adjustments.
- Added cash-flow/value-basis and metric-taxonomy gates, deterministic sensitivity and reverse-valuation cases, and a shared diluted-share/ADS/FX security bridge.
- Registered operating-company, bank, insurer, REIT, pre-revenue, and explicit-rationale custom financial families with line dimensions and accounting identities.
- Added EV/equity-aware SOTP bridges; typed management and moat evidence contracts; audited distribution, comparison, and psychology semantics; and a complete manifest-driven company orchestrator with frozen inputs and read-only reporting.
- Added versioned revenue-output fixtures, cross-version golden tests, property invariants, CLI smoke tests, static typing, JSON schemas, CI, compatibility and migration documentation, and deterministic installation synchronization.
- Preserved structural validation for immutable artifact schema 1.0 / invest-suite 4.0.0-4.2.0 outputs. Version 5 inputs and outputs are otherwise intentionally breaking.

## 4.2.0 - 2026-07-12

- Added immutable propagation and validation of revenue-forecast 3.2 target measurement semantics and model periods.
- Distinguishes cumulative, annual, run-rate, ambiguous, and legacy-3.1 target summaries in every downstream artifact.
- Preserved validation support for invest-suite 4.0.0 and 4.1.0 artifacts.

## 4.1.0 - 2026-07-12

- Added immutable propagation of revenue-forecast 3.1 management-target coverage into financials, valuation, SOTP, and framework artifacts.
- Added hashed target summaries, target counts, perimeter/treatment metadata, and scenario-attainment visibility.
- Added adversarial tests for target-summary tampering and end-to-end SOTP propagation.
- Preserved validation support for immutable invest-suite 4.0.0 artifacts and revenue-forecast 3.0 references.

## 4.0.0

- Introduced the modular invest-core, financials, valuation, SOTP, moat, management, distribution, compare, psychology, and framework architecture.
