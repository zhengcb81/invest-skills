# Modular pipeline

## Typical graphs

### Operating company valuation

```text
revenue-forecast -> financials -> valuation
        |               |
        +-> moat        +-> distribution
             management
```

### Multi-segment SOTP

```text
revenue-forecast segment A -> financials A -> valuation A --+
revenue-forecast segment B -> financials B -> valuation B --+-> SOTP
```

### Peer comparison

Complete and validate the same owning module for every company, then pass those artifacts to `invest-compare`. Do not place the multi-company comparison artifact inside a single-company bundle.

## Execution policy

- Reuse an artifact only when its hash validates and its information date is appropriate.
- If an upstream artifact changes, every descendant is stale because its stored upstream hash no longer matches.
- Scenario-bound descendants use the exact upstream `low/base/high` identities.
- Revenue schema 3.1 descendants preserve one hashed management-target summary. A mismatch blocks valuation aggregation or bundling; downstream modules never reconstruct the target test.
- Optional qualitative modules can be omitted with an explicit limitation. Quantitative dependencies cannot be skipped.
- The framework report preserves standalone method outputs and disagreements; it does not force a consensus score.
