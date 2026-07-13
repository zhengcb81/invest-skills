---
name: invest-moat
description: Analyze competitive mechanisms, durability, erosion, and falsifiers while mapping each conclusion to existing revenue drivers or financial lines. Use for pricing power, switching costs, network effects, cost advantage, intangible assets, efficient scale, customer retention, market-share durability, technology substitution, or regulatory barriers. Do not create valuation premiums or a new forecast.
---

# Invest Moat

Treat a moat as a causal mechanism that changes the durability or range of an already modeled revenue or financial driver.

## Required resources

- Read `invest-core/SKILL.md` and [references/moat-contract.md](references/moat-contract.md).
- Validate the relevant `revenue-forecast` result first; optionally consume `invest-financials` for margin or capital-intensity evidence.
- Finalize the draft with `invest-core/scripts/invest_contracts.py finalize-draft`.

## Workflow

1. Identify the economic mechanism: switching cost, network effect, cost advantage, intangible asset, efficient scale, distribution, data, or another explicit mechanism.
2. Record the unit of competition, relevant segment, competitors, customer decision, and evidence.
3. Map the mechanism to exact RF parameter IDs or financial line/parameter IDs already used downstream.
4. Estimate a durability horizon or erosion condition as an assumption, not a score.
5. Define falsifiers and observable leading indicators.
6. Produce a `moat` artifact with the validated revenue reference; do not alter the frozen forecast artifact.

## Boundaries

- Market share, retention, price, or win rate belongs to revenue modeling; reference its parameter rather than reforecasting it.
- Margin, ROIC, and capital intensity belong to financials; use them as evidence, not moat points.
- A patent, brand, licence, or large scale is not a moat without an economic mechanism and customer consequence.
- Never translate a moat label or score directly into a PE/PS premium.
- Do not output ratings or positions.
