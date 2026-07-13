---
name: invest-compare
description: Compare already validated invest-* artifacts across companies after aligning module, period, scenario, accounting definition, currency, and unit. Use for peer tables, driver or margin comparisons, scenario dispersion, moat or management evidence differences, and valuation-method comparisons. Never recollect company data, recompute revenue, or issue a rating during comparison.
---

# Invest Compare

Compare artifacts, not ad hoc company snippets.

## Required resources

- Read `invest-core/SKILL.md` and [references/comparability.md](references/comparability.md).
- Require one validated artifact of the same module from every company.
- Use `scripts/compare_artifacts.py` for extraction, normalization, and output validation.

## Workflow

1. Select the module and exact metrics to compare.
2. Validate every artifact and require compatible scenarios and forecast years.
3. For every metric, declare target/source definitions, source periods by company, dimension, annual/point-in-time basis, and total/per-share value basis.
4. Align exact definitions or document a reconciled mapping. Register FX and unit-scale conversions separately; never apply FX to non-monetary ratios.
5. Extract metrics from complete frozen source snapshots; do not rerun their upstream models.
6. Present values, missingness, dispersion, and causal differences. Keep evidence quality separate from company quality.

```powershell
python scripts/compare_artifacts.py compare_input.json company_a.json company_b.json --output comparison.json
```

## Boundaries

- Do not search for new facts inside this skill; return to the owning module if data are missing.
- Do not compare mismatched definitions merely because labels look similar.
- Do not silently convert FX or units.
- Do not produce buy/sell, core-holding, expected-return, or position conclusions.
- Reject mixed modules, duplicate companies, incompatible scenarios/years, absent paths, or untraceable normalization.
