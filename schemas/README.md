# JSON schemas

These Draft 2020-12 schemas document structural contracts for artifact, financial, valuation, SOTP, and company-manifest JSON. Runtime validators remain authoritative for constraints JSON Schema cannot express: hashes, formulas, dimension algebra, scenario lineage, period ordering, evidence coverage, accounting identities, and deterministic semantic recomputation.

The release gate validates every schema against the Draft 2020-12 meta-schema. Examples are validated structurally and then executed through the runtime in tests.
