---
name: invest-management
description: Assess source-linked management integrity, governance, incentives, execution, team depth, and succession without duplicating capital-allocation calculations. Use for CEO/CFO/founder track records, regulatory or disclosure events, compensation alignment, insider ownership, succession, board oversight, or execution against prior commitments.
---

# Invest Management

Evaluate people and decision processes from dated evidence. Keep measured capital-allocation outcomes in `invest-distribution` and reference that artifact rather than recalculating it.

## Required resources

- Read `invest-core/SKILL.md` and [references/management-contract.md](references/management-contract.md).
- Use the same company identity and information date as the active analysis bundle.
- Finalize the draft with `invest-core/scripts/invest_contracts.py finalize-draft`.

## Workflow

1. Identify decision makers, board oversight, material business owners, and succession candidates as of the frozen date.
2. Register regulatory findings, restatements, disclosure failures, related-party transactions, incentive terms, insider transactions, succession events, and prior commitments with exact locators and claims.
3. Encode every factual node with checked claim IDs; orphan claims and unclaimed facts fail validation.
4. Separate facts from interpretations. Every interpretation names input facts, contrary facts, rationale, and data gaps.
5. Compare prior explicit commitments with later outcomes using typed commitment assessments. Reference `invest-distribution` for measured allocation results.
6. When judging execution of a revenue-growth thesis, map checked supporting and contrary facts to existing `growth_driver_ids` and optional revenue-owned `management_target_ids` in `execution_driver_assessments`.
7. Produce mechanism-specific findings, red flags, disconfirming evidence, and unresolved questions; do not convert source confidence into a management score.

```powershell
python ../invest-core/scripts/invest_contracts.py finalize-draft management_draft.json --output management.json
```

## Formal output gate

Accept a formal management artifact only after `invest_contracts.py finalize-draft` validates every factual claim, source capture, interpretation mapping, and schema-2.1 compliance receipt. Model-written prose cannot introduce an allegation, execution status, or red flag absent from the validated artifact.

## Boundaries

- Do not equate founder ownership with alignment without control, compensation, dilution, and transaction evidence.
- Do not treat every regulatory event as fraud; preserve event type, status, materiality, and resolution.
- Do not calculate M&A returns, repurchase effectiveness, or dilution here.
- Do not create, edit, re-rank, or quantify a revenue driver; only assess execution against the frozen upstream driver.
- Do not output valuation premiums, ratings, or positions.
- Block factual findings without a checked claim or findings published after `as_of_date`.
