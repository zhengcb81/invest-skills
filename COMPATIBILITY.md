# Compatibility matrix

| Input or artifact | Runtime 5.1 behavior | Guarantees |
|---|---|---|
| Revenue schema 3.3, engine 3.4.0 | fully supported | ranked growth-driver tree, analysis hash, compact driver summary and exact frozen-forecast lineage |
| Revenue schema 3.2, engine 3.3.0 | fully supported | effective segment revenue, constraints and current target semantics |
| Revenue schema 3.2, engine 3.2.0 or 3.2.1 | validated as immutable legacy output | recognized-revenue fallback when `effective_revenue` is absent |
| Revenue schema 3.1, engine 3.1.0 | validated as immutable legacy output | target coverage retained; measurement basis labeled legacy |
| Revenue schema 3.0, engine 3.0.0 | validated as immutable legacy output | target coverage labeled unavailable rather than assumed absent |
| Invest artifact schema 2.0, suite 5.1.0 | fully supported | typed semantic validation, scenario manifest, growth-driver propagation and module recomputation |
| Invest artifact schema 2.0, suite 5.0.0 | immutable compatibility validation | original schema-2 semantics; no retroactive growth-driver guarantees |
| Invest artifact schema 1.0, suite 4.0.0-4.2.0 | structural validation only | identity, evidence, content ID and hash; no retroactive schema-2 guarantees |
| Schema 2.0 with suite 4.x, or schema 1.0 with suite 5.x | rejected | mixed version contracts are not allowed |

The runtime validates an old immutable output under its original contract. It does not mutate, re-hash, or silently upgrade it. Revenue schema 3.0-3.2 references created by suite 5.1 are explicitly marked `legacy_not_available` for growth drivers. To gain 5.1 growth-driver guarantees, rerun revenue-forecast 3.4 from frozen source inputs and rebuild descendants.
