# Valuation methods

## DCF

Discount a named upstream cash-flow line year by year. Calculate terminal value from the terminal upstream cash flow, terminal growth, and discount rate. Require `discount_rate > terminal_growth`; show explicit-period value and terminal value separately.

Use unlevered FCF for enterprise DCF and equity cash flow for equity DCF. Never mix the two with the wrong capital-structure adjustments.

## Multiples

Multiply a named upstream metric by an explicit comparable multiple. Supported taxonomy is PE, PS, EV/Sales, EV/EBITDA, P/FFO, P/AFFO, and explicit-rationale custom methods. Record the comparable set, date, accounting definition, geography, growth, and capital structure in evidence. A PS method reads `revenue` from the financial artifact; it does not create a new revenue estimate.

Every method declares `metric_period` and `valuation_timing`. A `current` multiple produces value at the information date. An `exit` multiple first produces terminal value at the metric period, then discounts it to the information date. Current cash, debt, and other balance-sheet adjustments are applied only after discounting.

## Asset method

Use source-linked net assets or adjusted asset values. Make double counting with operating value a hard check in the research workflow.

## Combining methods

Do not average methods by default. If the analyst assigns method weights, register the weights as assumptions, require non-negative weights summing to one, and preserve every standalone result.

## Enterprise-to-equity bridge

Apply signed, source-linked adjustments such as cash, debt, non-operating assets, provisions, pension deficits, leases, and minority interests. Each method declares whether its raw value is enterprise or equity value.

Current adjustments must be point-in-time monetary balances measured at the valuation date. Do not apply a present balance directly to a future terminal value.

## Sensitivity and reverse cases

Sensitivity cases may stress registered discount-rate, terminal-growth, multiple, or asset-value parameters and recompute current equity value. Reverse cases solve either the multiple or terminal growth implied by a stated current equity value. These are deterministic diagnostics; they do not change the base model parameters.

## Listed security value

Use the invest-core security bridge after current equity value is known. Report source-linked diluted ordinary units, ordinary-units-per-security or ADS ratio, value-date FX, and per-security current value. Do not divide a terminal value by current shares.
