# Migration from invest-suite 4.x to 5.0

Version 5 is intentionally breaking because value timing, dimensional semantics, evidence completeness, and bundle reproducibility are now hard contracts.

## Required changes

1. Keep the suite-4 artifact immutable. Validate it under schema `1.0`; do not edit its body or hashes.
2. Rebuild from the original validated revenue result. A schema-2 artifact must include a hashed `scenario_manifest`.
3. Financial models must use schema `2.0`. Every line declares input/output dimensions, time basis, metric role, dimension rule, and cash-flow basis when applicable. Add required outputs and accounting identities.
4. Valuation methods must declare typed method taxonomy, metric period, current/exit timing, value basis, and cash-flow basis. Exit values require an explicit discount-rate template.
5. Move all current cash/debt/non-operating adjustments to the post-discount current-value bridge. Historical ratio parameters are not valid balance-sheet adjustments.
6. Use the shared security bridge for diluted shares, ADS ratios, and FX. Do not calculate per-share value in ad hoc report code.
7. SOTP must use one aggregation basis across all parts and declare a complete enterprise-to-equity or equity-level company bridge.
8. Convert management and moat prose into typed facts, checked claims, interpretations or mechanisms, contrary evidence, data gaps, and falsifiers.
9. Historical distribution values must be reported or derived facts with exact evidence and one declared share-count basis.
10. Replace hash-only bundles with the manifest-driven orchestrator so the final output freezes the manifest, revenue result, scenario manifest, all leaf artifacts, bundle, receipt, and Markdown report.

## Behavioral differences to reconcile

- A future exit multiple no longer equals current value; it is discounted to the information date.
- Segment revenue uses `effective_revenue` when the revenue owner supplies it.
- Boolean method weights, NaN/Infinity, silent FX, unknown family labels, unsupported placeholders, and mismatched dimensions now fail.
- Artifact schema-2 validators recompute module output, so editing `data` and merely refreshing generic hashes does not pass.

Run the full gate and compare low/base/high current values before retiring a suite-4 workflow:

```powershell
python tools/verify_suite.py --revenue-dir C:\path\to\revenue-forecast
```
