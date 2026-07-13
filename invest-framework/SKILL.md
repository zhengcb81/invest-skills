---
name: invest-framework
description: Orchestrate a modular company investment analysis as a dependency graph across revenue-forecast and validated invest-* artifacts. Use for full-company workflows that combine revenue, financials, moat, management, capital allocation, valuation, SOTP, or comparison while preserving one information date, scenario set, evidence contract, and data lineage. This skill coordinates modules and does not duplicate their formulas.
---

# Invest Framework

Run a dependency graph, not a monolithic scorecard.

## Required resources

- Read `invest-core/SKILL.md` and [references/pipeline.md](references/pipeline.md).
- Load only the leaf skills needed for the user's question.
- Use `scripts/bundle_validator.py` to validate the final single-company bundle.

## Workflow

1. Freeze company identity, `as_of_date`, reporting currency/unit, fiscal calendar, base year, and forecast years.
2. Run `revenue-forecast` first whenever any requested module depends on future revenue. Preserve its complete validated result.
3. Verify that management communication coverage is validated and that every material revenue target is either mapped to a scenario or exposed as an explicit data gap before launching descendants.
4. Route requested work to leaf owners:
   - profit and cash flow → `invest-financials`;
   - competitive durability → `invest-moat`;
   - governance and execution → `invest-management`;
   - capital allocation → `invest-distribution`;
   - valuation → `invest-valuation`;
   - segment aggregation → `invest-sotp`;
   - peer comparison → `invest-compare` after company artifacts exist.
5. Never ask a downstream module to rebuild an upstream path.
6. Validate each artifact immediately, then validate the complete bundle, target-summary hashes, and upstream hashes.
7. Report conclusions by module, management-target coverage, evidence strength, sensitivities, contradictions, and missing modules. Do not collapse unlike dimensions into an arbitrary total score.

```powershell
python scripts/bundle_validator.py bundle_input.json artifact_a.json artifact_b.json --output bundle.json
```

## Boundaries

- Keep `invest-psychology` outside the company bundle; it is a user-state sidecar.
- Do not contain leaf formulas, duplicate source systems, company-type forecasts, scenario probabilities, valuation defaults, or position sizing.
- A missing required module blocks the bundle. An optional missing module is reported as a limitation, not imputed.
- Do not produce buy/sell ratings merely by averaging module judgments.
