---
name: invest-financials
description: Convert a validated revenue-forecast result into auditable scenario profit, balance-sheet, and cash-flow paths through a deterministic formula DAG. Use for margins, gross profit, operating profit, net income, NOPAT, working capital, capex, free cash flow, ROIC inputs, bank credit costs, insurer results, REIT cash flow, or pre-revenue burn. Never create a second revenue forecast.
---

# Invest Financials

Model profit and cash flow as deterministic lines downstream of a frozen `revenue-forecast` result.

## Required resources

- Read `invest-core/SKILL.md` and [references/model-families.md](references/model-families.md).
- Read the revenue forecast output schema when selecting company or segment scope.
- Use `scripts/financial_model.py`; do not calculate financial paths in prose.

## Workflow

1. Obtain a validated revenue JSON and choose company or one exact segment.
2. Freeze the same company, information date, currency, unit, fiscal years, and `low/base/high` scenarios.
3. Register every non-revenue input as an invest-core parameter with source/claim or an explicit source-free analyst rationale.
4. Select a registered model family: `operating_company`, `bank`, `insurer`, `reit`, `pre_revenue`, or explicit-rationale `custom`.
5. Define ordered financial lines. Every line declares inputs, dimensions, output dimension, annual/point-in-time basis, metric role, dimension rule, and cash-flow basis when applicable.
6. Declare accounting identities and required outputs, then run the deterministic model and its independent semantic recalculation validator.
7. Display the frozen management-target summary beside the corresponding revenue scenarios; do not reinterpret its perimeter or commitment strength.
8. Report scenario paths, identity residuals, limitations, and parameter-level evidence.

```powershell
python scripts/financial_model.py forecast.json financial_input.json --output financials.json
```

## Boundaries

- Copy revenue from the adapter exactly; never accept a revenue override.
- Copy management-target coverage from the revenue reference exactly; never create or remap a target in this module.
- Do not silently assume margins, tax, beta, WACC, capex, working capital, credit losses, or cash conversion.
- Do not treat EBITDA, operating cash flow, free cash flow, equity cash flow, and unlevered cash flow as interchangeable.
- Do not output a valuation, rating, price target, or position size.
- Use formula-DAG templates rather than assigning one company-wide type; segments may use different financial models.

Block output on a missing parameter, wrong period/scenario, forward reference, duplicate line, non-finite value, mutated revenue result, or artifact hash mismatch.

Validate an existing output without rerunning upstream research:

```powershell
python scripts/financial_model.py --validate-artifact financials.json
```
