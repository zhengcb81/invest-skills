---
name: invest-distribution
description: Analyze capital allocation from source-linked reinvestment, acquisitions, dividends, repurchases, issuance, impairments, and share-count history, while consuming financial artifacts for identity and accounting context. Use for payout, dilution, reinvestment, M&A outcomes, retained earnings, or capital-allocation discipline. Keep governance judgments in invest-management and valuation in invest-valuation.
---

# Invest Distribution

Measure where capital went and what happened afterward. Do not infer management integrity from the calculation alone.

## Required resources

- Read `invest-core/SKILL.md` and [references/capital-allocation.md](references/capital-allocation.md).
- Require a validated `invest-financials` artifact for company identity and lineage.
- Use `scripts/capital_allocation.py` for historical ratios and totals.

## Workflow

1. Freeze a consecutive historical window and define every capital-flow measure.
2. Register net income, dividends, repurchases, issuance, acquisitions, impairments, internal reinvestment, and share count with exact-value evidence.
3. Calculate annual and cumulative allocation metrics, dilution, payout, reinvestment, and acquisition impairment.
4. Attribute outcomes cautiously; separate operating performance, financing, valuation changes, and market beta.
5. Deliver a `distribution` artifact and let `invest-management` reference it when assessing decision quality.

```powershell
python scripts/capital_allocation.py financials.json allocation_input.json --output distribution.json
```

## Hard rules

- Do not use market-cap change divided by retained earnings as a standalone verdict.
- Do not classify buybacks as value creating without price and per-share outcome evidence from the appropriate modules.
- Do not double count repurchases as an income-statement expense.
- Do not silently treat missing flows as zero.
- Do not output valuation, rating, or position conclusions.
