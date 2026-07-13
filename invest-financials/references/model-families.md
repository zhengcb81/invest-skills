# Financial formula families

Use these as line-DAG templates, not as hidden defaults. Every ratio or amount remains a registered parameter.

## Operating company

```text
gross_profit = revenue - cost_of_revenue
operating_profit = gross_profit - operating_expense
NOPAT = operating_profit - cash_tax
unlevered_FCF = NOPAT + D&A - capex - change_in_working_capital
net_income = operating_profit - net_interest - income_tax - minority_profit
```

## Bank

First ensure the revenue forecast defines bank revenue consistently.

```text
pre_provision_profit = revenue - operating_expense
pre_tax_profit = pre_provision_profit - credit_loss - other_loss
net_income = pre_tax_profit - income_tax - minority_profit
equity_cash_flow = net_income - required_equity_growth
```

## Insurer

Separate insurance-service and investment results according to the reporting framework.

```text
operating_result = insurance_service_result + investment_result - operating_expense
net_income = operating_result - finance_expense - income_tax
equity_cash_flow = net_income - required_capital_growth
```

## REIT or property vehicle

```text
NOI = revenue - property_operating_cost
FFO = net_income + depreciation - property_sale_gain
AFFO = FFO - maintenance_capex - straight_line_adjustments
```

## Pre-revenue company

Keep revenue at the validated zero or early path. Model operating expense, capex, financing need, and cash runway explicitly; do not invent a margin on zero revenue.

## Line rules

Each line declares a formula using `x0`, `x1`, and so on plus ordered `input_refs`. Valid references are:

- `revenue`;
- `line:<earlier_line_id>`;
- `parameter:<parameter_id_template>`, where `{scenario}` and `{year}` are substituted at runtime.
