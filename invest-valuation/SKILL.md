---
name: invest-valuation
description: Value a company or segment from validated revenue and financial artifacts using deterministic DCF, market-multiple, or asset methods under the same low/base/high scenarios. Use for enterprise value, equity value, terminal value, PE/PS/EV-based methods, asset value, reverse assumptions, or valuation sensitivity. Never rebuild revenue or profit inside valuation.
---

# Invest Valuation

Calculate value from immutable upstream artifacts. A valuation method may select an upstream revenue or financial metric, but it may not override that metric.

## Required resources

- Read `invest-core/SKILL.md` and [references/methods.md](references/methods.md).
- Require a validated `invest-financials` artifact with the same revenue reference and scenarios.
- Use `scripts/valuation_model.py`; do not calculate DCF or multiples in prose.

## Workflow

1. Validate the financial artifact and its revenue lineage.
2. Preserve and display the upstream management-target summary so readers can see which revenue scenario, if any, reflects each target.
3. Register discount rates, terminal growth, multiples, balance-sheet adjustments, method weights, and other direct inputs as source-linked parameters or explicit assumptions.
4. Select one or more methods. Each method consumes a named upstream metric.
5. Calculate every method separately for low/base/high.
6. Combine methods only when explicit weights sum to one. Otherwise present a range without an invented average.
7. Run sensitivities on the material valuation parameters and disclose method limitations.

```powershell
python scripts/valuation_model.py financials.json valuation_input.json --output valuation.json
```

## Hard rules

- DCF discount rate must exceed terminal growth for every scenario.
- Do not use silent risk-free rates, beta, market premiums, FX, multiples, terminal growth, or method weights.
- Do not turn moat or management scores into automatic valuation premiums.
- Do not reinterpret a management revenue target as a valuation assumption; consume only the already frozen scenario paths.
- Keep enterprise-value to equity-value adjustments explicit and source linked.
- Do not require current price or output buy/sell ratings, expected returns, or positions.
- Reject missing upstream hashes, scenario mismatch, metric mismatch, direct forecast overrides, non-finite values, or artifact mutation.
