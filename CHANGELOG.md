# Changelog

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
