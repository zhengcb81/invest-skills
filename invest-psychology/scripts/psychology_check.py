"""Validate a user-answered investment psychology checklist without scoring it."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"
QUESTIONS = (
    "independent_thesis", "disconfirming_search", "anchoring", "fomo", "sunk_cost",
    "product_affinity", "circle_of_competence", "falsifiers_written", "missing_evidence_written",
)
ADVERSE_YES = {"anchoring", "fomo", "sunk_cost", "product_affinity"}
ADVERSE_NO = {"independent_thesis", "disconfirming_search", "circle_of_competence", "falsifiers_written", "missing_evidence_written"}


class PsychologyInputError(ValueError):
    pass


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_check(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data.get("decision"), str) or not data["decision"].strip():
        raise PsychologyInputError("decision is required")
    if not isinstance(data.get("thesis"), str) or not data["thesis"].strip():
        raise PsychologyInputError("thesis is required")
    answers = data.get("answers")
    if not isinstance(answers, dict):
        raise PsychologyInputError("answers must be an object")
    if set(answers) - set(QUESTIONS):
        raise PsychologyInputError("answers contain unknown questions")
    for key, value in answers.items():
        if value not in {"yes", "no", "unknown"}:
            raise PsychologyInputError(f"answer must be yes/no/unknown: {key}")
    unanswered = [key for key in QUESTIONS if key not in answers or answers[key] == "unknown"]
    triggers = [
        key for key in QUESTIONS
        if (key in ADVERSE_YES and answers.get(key) == "yes") or (key in ADVERSE_NO and answers.get(key) == "no")
    ]
    result = {
        "psychology_schema_version": SCHEMA_VERSION,
        "decision": data["decision"],
        "thesis": data["thesis"],
        "answers": {key: answers.get(key, "unknown") for key in QUESTIONS},
        "user_acknowledged_review_triggers": triggers,
        "unanswered_or_unknown": unanswered,
        "thesis_falsifiers": data.get("thesis_falsifiers", []),
        "missing_evidence": data.get("missing_evidence", []),
        "limitations": ["User-supplied self-check; no company score or inferred mental state"],
    }
    result["result_sha256"] = _hash(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a user-supplied investment psychology checklist")
    parser.add_argument("input")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        source = Path(args.input)
        target = Path(args.output)
        if target.exists():
            raise PsychologyInputError(f"refusing to overwrite existing file: {target}")
        data = json.loads(source.read_text(encoding="utf-8"))
        result = run_check(data)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 0
    except (PsychologyInputError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
