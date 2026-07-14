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
3. Preserve the upstream growth-driver reference exactly for lineage and reporting; do not turn a driver rank or evidence label into a multiple or discount-rate adjustment.
4. Register discount rates, terminal growth, multiples, balance-sheet adjustments, method weights, and other direct inputs as source-linked parameters or explicit assumptions.
5. Select one or more typed methods. DCF declares FCFF/FCFE basis; multiples declare PE, PS, EV/Sales, EV/EBITDA, P/FFO, P/AFFO, or justified custom taxonomy.
6. Declare `current` versus `exit` timing and the metric period. Exit values are discounted to the information date before current balance-sheet adjustments are applied.
7. Calculate every method separately for low/base/high, including explicit terminal/current value fields.
8. Combine methods only when explicit weights sum to one. Otherwise present a range without an invented average.
9. Add the shared security bridge when a per-share, ADS, or listed-currency value is required.
10. Run declared sensitivity cases and reverse-implied multiple or terminal-growth cases; disclose method limitations.

```powershell
python scripts/valuation_model.py financials.json valuation_input.json --output valuation.json
```

## Formal output gate

Accept a formal valuation result only from `scripts/valuation_model.py` after semantic recomputation and the shared schema-2.1 compliance receipt pass. Never repair, average, or extend a failed artifact in prose; a narrative may only summarize frozen method results, assumptions, sensitivities, and limitations.

## Hard rules

- DCF discount rate must exceed terminal growth for every scenario.
- Do not use silent risk-free rates, beta, market premiums, FX, multiples, terminal growth, or method weights.
- Do not turn moat or management scores into automatic valuation premiums.
- Do not reinterpret a management revenue target as a valuation assumption; consume only the already frozen scenario paths.
- Keep enterprise-value to equity-value adjustments explicit and source linked.
- Current adjustments must be point-in-time monetary balances measured at the valuation date.
- Do not require current price or output buy/sell ratings, expected returns, or positions.
- Reject missing upstream hashes, scenario mismatch, metric mismatch, direct forecast overrides, non-finite values, or artifact mutation.

Validate an existing output with deterministic semantic recomputation:

```powershell
python scripts/valuation_model.py --validate-artifact valuation.json
```
