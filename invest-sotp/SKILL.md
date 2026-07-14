---
name: invest-sotp
description: Aggregate validated segment-level valuation artifacts into a source-traceable Sum-of-the-Parts equity value under identical low/base/high scenarios. Use for multi-business groups, holding companies, ownership adjustments, net debt, non-operating assets, minority interests, or conglomerate adjustments. This skill composes values and never forecasts segment revenue, profit, or valuation inputs.
---

# Invest SOTP

Treat SOTP as a pure composition step.

## Required resources

- Read `invest-core/SKILL.md` and [references/sotp-contract.md](references/sotp-contract.md).
- Require one validated `invest-valuation` artifact per segment.
- Use `scripts/sotp_model.py`; never sum values manually.

## Workflow

1. Validate every segment valuation artifact and its complete upstream lineage.
2. Require identical company, information date, reporting currency/unit, fiscal years, scenario set, and revenue result hash.
3. Require identical hashed management-target summaries across all segment valuations and report target measurement basis, perimeter, treatment, and scenario attainment or explicit non-comparability at company level.
4. Require identical growth-driver summary and analysis hashes across segment valuations; preserve them for framework reporting without aggregating or re-ranking drivers in SOTP.
5. Select one explicit valuation method or an explicitly weighted method result for each segment, and declare whether all selected values are enterprise or equity values.
6. Register ownership percentages and one complete company bridge. Enterprise selections require an enterprise-to-equity bridge; equity selections require an equity-level bridge.
7. Calculate low/base/high ownership-adjusted segment values, company bridge, and optional shared security bridge.
8. Report each part, ownership, adjustment, scenario total, management-target coverage, evidence, and limitations.

```powershell
python scripts/sotp_model.py sotp_input.json valuation_a.json valuation_b.json --output sotp.json
```

## Formal output gate

Accept a formal SOTP only from `scripts/sotp_model.py` after every valuation input, ownership bridge, semantic recomputation, and shared schema-2.1 compliance receipt pass. Never hand-sum or patch a failed SOTP in prose.

## Hard rules

- Reject duplicate or company-scoped parts; every part must be a unique segment.
- Do not use default ownership, FX, net debt, minority interest, or conglomerate discount.
- Do not create a new scenario, probability, TAM, market share, margin, multiple, or revenue path.
- Do not declare a target reflected merely because a segment value is high; use only the revenue-owned `scenario_comparison.meets_target` result.
- Do not require current price or output upside, ratings, or positions.
- Apply a conglomerate discount only as an explicit signed adjustment with a documented assumption; never infer it from the number of segments.
