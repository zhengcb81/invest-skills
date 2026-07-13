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
3. Align accounting definitions, scope, period, currency, and scale. Register any FX or scale conversion as explicit parameters.
4. Extract metrics from artifact paths; do not rerun their upstream models.
5. Present values, missingness, dispersion, and causal differences. Keep evidence quality separate from company quality.

```powershell
python scripts/compare_artifacts.py compare_input.json company_a.json company_b.json --output comparison.json
```

## Boundaries

- Do not search for new facts inside this skill; return to the owning module if data are missing.
- Do not compare mismatched definitions merely because labels look similar.
- Do not silently convert FX or units.
- Do not produce buy/sell, core-holding, expected-return, or position conclusions.
- Reject mixed modules, duplicate companies, incompatible scenarios/years, absent paths, or untraceable normalization.
