"""Validate a user-answered investment psychology checklist without scoring it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


CORE_SCRIPTS = Path(__file__).resolve().parents[2] / "invest-core" / "scripts"
if str(CORE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CORE_SCRIPTS))

from invest_contracts import canonical_sha256  # noqa: E402


SCHEMA_VERSION = "2.0"
QUESTIONS = (
    "independent_thesis", "disconfirming_search", "anchoring", "fomo", "sunk_cost",
    "product_affinity", "circle_of_competence", "falsifiers_written", "missing_evidence_written",
)
# Every question is deliberately phrased as a positive control. A "no" is adverse.
ADVERSE_NO = set(QUESTIONS)


class PsychologyInputError(ValueError):
    pass


def _require(condition: object, message: str) -> None:
    if not condition:
        raise PsychologyInputError(message)


def _string_list(value: Any, field: str) -> list[str]:
    _require(isinstance(value, list), f"{field} must be a list")
    _require(all(isinstance(item, str) and item.strip() for item in value), f"{field} must contain non-empty strings")
    normalized = [item.strip() for item in value]
    _require(len(normalized) == len(set(normalized)), f"{field} must be unique")
    return normalized


def validate_check_output(result: dict[str, Any]) -> None:
    _require(isinstance(result, dict), "psychology output must be an object")
    _require(result.get("psychology_schema_version") == SCHEMA_VERSION, "psychology schema version mismatch")
    _require(isinstance(result.get("decision"), str) and result["decision"].strip(), "decision is required")
    _require(isinstance(result.get("thesis"), str) and result["thesis"].strip(), "thesis is required")
    answers = result.get("answers")
    _require(isinstance(answers, dict) and list(answers) == list(QUESTIONS), "psychology output answers must be complete and ordered")
    assert isinstance(answers, dict)
    _require(all(value in {"yes", "no", "unknown"} for value in answers.values()), "invalid psychology output answer")
    expected_unknown = [key for key in QUESTIONS if answers[key] == "unknown"]
    expected_triggers = [key for key in QUESTIONS if key in ADVERSE_NO and answers[key] == "no"]
    _require(result.get("user_acknowledged_review_triggers") == expected_triggers, "psychology trigger polarity mismatch")
    _require(result.get("unanswered_or_unknown") == expected_unknown, "psychology unknown-answer mismatch")
    falsifiers = _string_list(result.get("thesis_falsifiers"), "thesis_falsifiers")
    missing = _string_list(result.get("missing_evidence"), "missing_evidence")
    if answers["falsifiers_written"] == "yes":
        _require(bool(falsifiers), "falsifiers_written=yes requires thesis_falsifiers")
    if answers["missing_evidence_written"] == "yes":
        _require(bool(missing), "missing_evidence_written=yes requires missing_evidence")
    _require(result.get("limitations") == ["User-supplied self-check; no company score or inferred mental state"], "psychology limitations mismatch")
    provided_hash = result.get("result_sha256")
    _require(isinstance(provided_hash, str), "psychology result hash is required")
    _require(provided_hash == canonical_sha256({key: value for key, value in result.items() if key != "result_sha256"}), "psychology result hash mismatch")


def run_check(data: dict[str, Any]) -> dict[str, Any]:
    _require(isinstance(data, dict), "psychology input must be an object")
    _require(isinstance(data.get("decision"), str) and data["decision"].strip(), "decision is required")
    _require(isinstance(data.get("thesis"), str) and data["thesis"].strip(), "thesis is required")
    answers = data.get("answers")
    _require(isinstance(answers, dict), "answers must be an object")
    assert isinstance(answers, dict)
    _require(set(answers) == set(QUESTIONS), "answers must cover every checklist question exactly")
    for key, value in answers.items():
        _require(value in {"yes", "no", "unknown"}, f"answer must be yes/no/unknown: {key}")
    falsifiers = _string_list(data.get("thesis_falsifiers", []), "thesis_falsifiers")
    missing = _string_list(data.get("missing_evidence", []), "missing_evidence")
    if answers["falsifiers_written"] == "yes":
        _require(bool(falsifiers), "falsifiers_written=yes requires thesis_falsifiers")
    if answers["missing_evidence_written"] == "yes":
        _require(bool(missing), "missing_evidence_written=yes requires missing_evidence")
    unanswered = [key for key in QUESTIONS if answers[key] == "unknown"]
    triggers = [key for key in QUESTIONS if answers[key] == "no"]
    result = {
        "psychology_schema_version": SCHEMA_VERSION,
        "decision": data["decision"].strip(), "thesis": data["thesis"].strip(),
        "answers": {key: answers[key] for key in QUESTIONS},
        "user_acknowledged_review_triggers": triggers,
        "unanswered_or_unknown": unanswered,
        "thesis_falsifiers": falsifiers, "missing_evidence": missing,
        "limitations": ["User-supplied self-check; no company score or inferred mental state"],
    }
    result["result_sha256"] = canonical_sha256(result)
    validate_check_output(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a user-supplied investment psychology checklist")
    parser.add_argument("input", nargs="?")
    parser.add_argument("--output")
    parser.add_argument("--validate-output")
    args = parser.parse_args()
    try:
        if args.validate_output:
            validate_check_output(json.loads(Path(args.validate_output).read_text(encoding="utf-8")))
            print("psychology output valid")
            return 0
        _require(bool(args.input and args.output), "input and --output are required")
        source = Path(args.input)
        target = Path(args.output)
        _require(not target.exists(), f"refusing to overwrite existing file: {target}")
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
