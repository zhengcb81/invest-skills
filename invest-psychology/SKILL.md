---
name: invest-psychology
description: Run a user-supplied decision-process and cognitive-bias checklist as a sidecar to investment research. Use for confirmation bias, anchoring, FOMO, sunk-cost thinking, thesis falsification, information gaps, or pre-commitment review. This skill does not score the company, infer the user's state, set a position size, or enter the fundamental-analysis DAG.
---

# Invest Psychology

Ask the user for answers. Do not infer private motives from company data or conversation tone.

## Workflow

1. Freeze the decision being considered and the user's stated thesis.
2. Require explicit answers to the checklist in [references/checklist.md](references/checklist.md).
3. Run `scripts/psychology_check.py`. All questions are positive controls: `yes` passes the control, `no` requests review, and `unknown` remains unresolved.
4. Ask the user to state thesis falsifiers and evidence still missing.
5. Return a sidecar checklist. Do not merge it into company score or valuation.

```powershell
python scripts/psychology_check.py psychology_input.json --output psychology.json
```

## Formal output gate

Accept a formal checklist result only from `scripts/psychology_check.py` and its schema-2.1 compliance receipt. Preserve the user's explicit `yes/no/unknown` inputs exactly; do not infer answers, diagnose the user, or extend the script result in prose.

## Boundaries

- No automated score, pass/fail verdict, expected return, price target, or maximum position.
- No price-based sell rule unless the user explicitly supplies it for a separate portfolio process.
- Do not fabricate an answer for an unanswered question.
- A review trigger is a prompt for review, not proof the investment is wrong.
