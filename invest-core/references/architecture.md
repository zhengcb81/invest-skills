# Investment skill architecture

## Dependency graph

```text
revenue-forecast
      |
      v
invest-core contracts
      |
      +--> invest-financials --> invest-valuation --> invest-sotp
      +--> invest-moat -----------^       |
      +--> invest-management -----^       +--> invest-compare
      +--> invest-distribution ---^

invest-framework orchestrates validated artifacts only.
invest-psychology is a user-state sidecar and never enters company scoring.
```

## Module ownership

| Module | Owns | Must not own |
|---|---|---|
| `revenue-forecast` | revenue curves, recognition, scenarios, CAGR, management revenue-target discovery/reconciliation, revenue evidence and backtests | profit, cash flow, valuation |
| `invest-financials` | source-linked profit and cash-flow lines derived from frozen revenue | a second revenue path |
| `invest-moat` | competitive mechanism, durability, erosion events, references to affected model parameters | arbitrary valuation premiums |
| `invest-management` | integrity, governance, incentives, execution, succession | capital-allocation outcome calculations |
| `invest-distribution` | reinvestment, M&A, dividends, repurchases, dilution and measured outcomes | management integrity scoring |
| `invest-valuation` | DCF, multiple and asset-method calculations from upstream artifacts | new revenue or profit forecasts |
| `invest-sotp` | EV/equity-aware ownership aggregation, company bridge, and shared security bridge | segment forecasting |
| `invest-compare` | accounting/scenario alignment and cross-company comparison | new company research |
| `invest-psychology` | user-supplied bias checklist | company score, price target, or position size |
| `invest-framework` | dependency resolution, frozen inputs, atomic execution, bundle validation and read-only reporting | leaf formulas or duplicated research |

## Design tests

Any new feature must answer:

1. Which module owns the fact or calculation?
2. Which immutable upstream artifact supplies each input?
3. Can the output be recomputed without an LLM?
4. Does every direct fact respect the same `as_of_date`?
5. Does a missing input block output rather than trigger a silent default?
6. If management stated a material revenue target, does the final artifact preserve its revenue-owned perimeter, scenario mapping, and attainment without reforecasting it?
7. Does a semantic validator independently recompute quantitative output from frozen inputs?
8. Does every scenario-bound artifact carry the same scenario-manifest hash?
