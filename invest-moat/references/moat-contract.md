# Moat artifact contract

Use `module="moat"`, the exact company or segment scope, `low/base/high` only when conclusions are scenario bound, and the validated revenue result reference.

For every mechanism record:

- `mechanism_id` and `mechanism_type`;
- business scope and unit of competition;
- customer or supplier behavior creating the advantage;
- claim IDs and contrary claim IDs;
- affected revenue parameter IDs and optional financial parameter/line IDs;
- durability assumption and its rationale;
- erosion events, leading indicators, and explicit falsifiers;
- current status: observed, weakening, unproven, or data gap.

Keep observed facts separate from the analyst's durability assumption. Confidence describes evidence support, not investment quality.

The artifact must also carry a `driver_registry` bound to the exact revenue result hash. Every mapped revenue parameter and financial line must exist in that registry. Every observed fact needs checked claim IDs, and every mechanism needs a non-empty causal chain, customer consequence, leading indicators, erosion events, and falsifiers.
