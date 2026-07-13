# Investment evidence contract

Use the revenue skill's evidence semantics across investment modules.

## Sources

Register an HTTPS source once with source ID, type, title, publisher, URL, publication date, access date, and page or section. Publication cannot be after the artifact information date.

## Parameters

Each parameter has an ID, kind, numeric value, unit, period, definition, dimension, time basis, scenario, source IDs, and claim IDs. Facts and management guidance require exact-value evidence. Source-free analyst assumptions are allowed only with an explicit rationale and remain visible as assumptions.

## Claims

Each claim binds one source to one target and contains a locator, checked excerpt, excerpt hash, content hash, verifier, verification date, and `opened_and_checked` status. Exact-value claims also carry extracted value, unit, and period matching the parameter.

The runtime validates internal evidence integrity. It cannot independently understand a live webpage; the research agent must actually open and check the cited content before creating a claim.
