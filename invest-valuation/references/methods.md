# Valuation methods

## DCF

Discount a named upstream cash-flow line year by year. Calculate terminal value from the terminal upstream cash flow, terminal growth, and discount rate. Require `discount_rate > terminal_growth`; show explicit-period value and terminal value separately.

Use unlevered FCF for enterprise DCF and equity cash flow for equity DCF. Never mix the two with the wrong capital-structure adjustments.

## Multiples

Multiply a named upstream terminal metric by an explicit comparable multiple. Record the comparable set, date, accounting definition, geography, growth, and capital structure in evidence. A PS method reads `revenue` from the financial artifact; it does not create a new revenue estimate.

## Asset method

Use source-linked net assets or adjusted asset values. Make double counting with operating value a hard check in the research workflow.

## Combining methods

Do not average methods by default. If the analyst assigns method weights, register the weights as assumptions, require non-negative weights summing to one, and preserve every standalone result.

## Enterprise-to-equity bridge

Apply signed, source-linked adjustments such as cash, debt, non-operating assets, provisions, pension deficits, leases, and minority interests. Each method declares whether its raw value is enterprise or equity value.
