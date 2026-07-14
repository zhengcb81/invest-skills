# Moat artifact contract

Use `module="moat"`, the exact company or segment scope, `low/base/high` only when conclusions are scenario bound, and the validated revenue result reference.

Current suite 5.2 artifacts use `qualitative_schema_version="2.1"`. The `driver_registry` contains the exact upstream `growth_driver_summary_sha256`, selected `growth_driver_ids`, and optional `financial_line_ids`.

For every mechanism record:

- `mechanism_id` and `mechanism_type`;
- business scope and unit of competition;
- customer or supplier behavior creating the advantage;
- claim IDs and contrary claim IDs;
- affected revenue-owned growth-driver IDs and optional financial line IDs;
- durability assumption and its rationale;
- erosion events, leading indicators, and explicit falsifiers;
- current status: observed, weakening, unproven, or data gap.

Keep observed facts separate from the analyst's durability assumption. Confidence describes evidence support, not investment quality.

Every registered growth-driver ID must exist in the upstream revenue summary and every mechanism mapping must exist in that registry. Every observed fact needs checked claim IDs, and every mechanism needs a non-empty causal chain, customer consequence, leading indicators, erosion events, and falsifiers. Suite-5.0 qualitative schema 2.0 artifacts remain immutable legacy records with their original revenue-parameter registry; new artifacts must not use that form.
