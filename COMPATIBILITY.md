# Compatibility matrix

| Input or artifact | Runtime 5.0 behavior | Guarantees |
|---|---|---|
| Revenue schema 3.2, engine 3.3.0 | fully supported | effective segment revenue, constraints and current target semantics |
| Revenue schema 3.2, engine 3.2.0 or 3.2.1 | validated as immutable legacy output | recognized-revenue fallback when `effective_revenue` is absent |
| Revenue schema 3.1, engine 3.1.0 | validated as immutable legacy output | target coverage retained; measurement basis labeled legacy |
| Revenue schema 3.0, engine 3.0.0 | validated as immutable legacy output | target coverage labeled unavailable rather than assumed absent |
| Invest artifact schema 2.0, suite 5.0.0 | fully supported | typed semantic validation, scenario manifest and module recomputation |
| Invest artifact schema 1.0, suite 4.0.0-4.2.0 | structural validation only | identity, evidence, content ID and hash; no retroactive schema-2 guarantees |
| Schema 2.0 with suite 4.x, or schema 1.0 with suite 5.0.0 | rejected | mixed version contracts are not allowed |

The runtime validates an old immutable output under its original contract. It does not mutate, re-hash, or silently upgrade it. To gain schema-2 semantic guarantees, rebuild the model from frozen source inputs and compare the old and new outputs explicitly.
