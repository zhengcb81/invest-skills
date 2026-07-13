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

`company_orchestrator.py` performs this fan-out from a versioned manifest. Every revenue segment must appear exactly once; the orchestrator does not silently omit, invent, merge, or rename segments.

### Peer comparison

Complete and validate the same owning module for every company, then pass those artifacts to `invest-compare`. Do not place the multi-company comparison artifact inside a single-company bundle.

## Execution policy

- Reuse an artifact only when its hash validates and its information date is appropriate.
- If an upstream artifact changes, every descendant is stale because its stored upstream hash no longer matches.
- Scenario-bound descendants use the same hashed scenario manifest, not merely matching `low/base/high` labels.
- Revenue schema 3.1+ descendants preserve one hashed management-target summary. Schema 3.2 additionally preserves annual/run-rate/cumulative measurement semantics. A mismatch blocks valuation aggregation or bundling; downstream modules never reconstruct the target test.
- Optional qualitative modules can be omitted with an explicit limitation. Quantitative dependencies cannot be skipped.
- The framework report preserves standalone method outputs and disagreements; it does not force a consensus score.
- A manifest-driven execution freezes the complete manifest and revenue result, then binds their hashes, the scenario-manifest hash, every leaf artifact hash, the final bundle hash, and a machine-readable receipt.
- All leaf calculations complete and validate in memory before output publication. An existing output path or any failed leaf blocks publication.
