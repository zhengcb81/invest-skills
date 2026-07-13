---
name: invest-core
description: Provide the shared contracts, evidence rules, revenue-forecast adapter, artifact hashing, dependency registry, and validation runtime used by all invest-* skills. Use when building, validating, combining, or debugging modular investment-analysis artifacts; this infrastructure skill does not make standalone investment conclusions.
---

# Invest Core

Use this skill as shared infrastructure. Do not ask it for a company conclusion by itself.

## Ownership

`revenue-forecast` remains the only owner of segment revenue drivers, recognition, low/base/high revenue paths, CAGR, revenue sensitivity, snapshots, and revenue backtests. Validate its complete result before any investment module consumes it.

`invest-core` owns only:

- discovery and loading of the revenue runtime;
- the versioned investment artifact contract;
- common company, period, scenario, source, claim, parameter, hash, and upstream-lineage validation;
- immutable transfer of revenue-forecast's validated management-target coverage, target perimeter, scenario mapping, and attainment summary;
- the module dependency registry;
- generic artifact read/write and validation commands.

The current contract is invest-suite `5.0.0` / artifact schema `2.0`. It also validates immutable schema `1.0` artifacts from suite `4.0.0` through `4.2.0`, but it never upgrades or silently rewrites them.

Do not put profit, cash-flow, valuation, moat, management, capital-allocation, comparison, or psychology formulas in this skill.

## Resource routing

- Read [references/architecture.md](references/architecture.md) before changing module boundaries or dependencies.
- Read [references/artifact-contract.md](references/artifact-contract.md) before creating or consuming an artifact.
- Read [references/evidence-contract.md](references/evidence-contract.md) before adding direct facts or assumptions.

Use `scripts/invest_contracts.py` to:

- validate and adapt a `revenue-forecast` v3 result without recomputing revenue;
- create and validate investment artifacts;
- verify upstream hashes and scenario identity;
- validate source-linked parameters and claims.

## Hard rules

- Keep dependencies one-way: `revenue-forecast` → `invest-core` → leaf `invest-*` skills → `invest-framework` orchestration.
- Import revenue primitives only through `invest_contracts.py`; leaf modules must not locate or import revenue scripts themselves.
- Use exactly `low`, `base`, and `high` for scenario-bound artifacts.
- Bind every scenario artifact to one hashed scenario manifest with explicit definitions.
- Reject a mutated revenue result, artifact, upstream hash, identity, currency, unit, fiscal period, or scenario set.
- Treat management revenue targets as revenue-owned facts: downstream modules may display the frozen summary but may not reinterpret, remap, or recalculate it.
- Never convert evidence confidence into company quality or valuation.
- Never use silent market, accounting, probability, multiple, discount-rate, or FX defaults.
- Use the shared security bridge for diluted shares, ordinary-units-per-security, ADS ratios, and value-date FX; leaf modules must not implement their own per-share arithmetic.

Validate an artifact with:

```powershell
python scripts/invest_contracts.py validate artifact.json
```

Inspect an immutable revenue adapter with:

```powershell
python scripts/invest_contracts.py adapt-revenue forecast.json --scope company
```

Finalize a qualitative module draft with computed IDs and hashes:

```powershell
python scripts/invest_contracts.py finalize-draft draft.json --output artifact.json
```
