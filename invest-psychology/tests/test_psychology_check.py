from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from psychology_check import PsychologyInputError, QUESTIONS, run_check, validate_check_output  # noqa: E402


def valid_input() -> dict:
    answers = {key: "yes" for key in QUESTIONS}
    return {
        "decision": "research further", "thesis": "test thesis", "answers": answers,
        "thesis_falsifiers": ["Revenue misses the stated threshold"],
        "missing_evidence": ["Customer cohort data"],
    }


class PsychologyCheckTests(unittest.TestCase):
    def test_reports_user_answers_without_score(self) -> None:
        result = run_check(valid_input())
        self.assertNotIn("score", result)
        self.assertNotIn("anchoring", result["user_acknowledged_review_triggers"])
        validate_check_output(result)

    def test_unknown_answer_is_preserved(self) -> None:
        data = valid_input()
        data["answers"] = {key: "unknown" for key in QUESTIONS}
        data["thesis_falsifiers"] = []
        data["missing_evidence"] = []
        result = run_check(data)
        self.assertEqual(len(result["unanswered_or_unknown"]), len(QUESTIONS))

    def test_invalid_answer_is_rejected(self) -> None:
        with self.assertRaisesRegex(PsychologyInputError, "yes/no/unknown"):
            data = valid_input()
            data["answers"]["fomo"] = "maybe"
            run_check(data)

    def test_no_on_positive_control_is_a_review_trigger(self) -> None:
        data = valid_input()
        data["answers"]["anchoring"] = "no"
        result = run_check(data)
        self.assertIn("anchoring", result["user_acknowledged_review_triggers"])

    def test_missing_answers_are_rejected(self) -> None:
        data = valid_input()
        data["answers"].pop("fomo")
        with self.assertRaisesRegex(PsychologyInputError, "cover every"):
            run_check(data)

    def test_claimed_written_falsifiers_require_content(self) -> None:
        data = valid_input()
        data["thesis_falsifiers"] = []
        with self.assertRaisesRegex(PsychologyInputError, "requires thesis_falsifiers"):
            run_check(data)

    def test_tampered_output_hash_is_rejected(self) -> None:
        result = run_check(valid_input())
        result["thesis"] = "tampered"
        with self.assertRaisesRegex(PsychologyInputError, "hash mismatch"):
            validate_check_output(result)


if __name__ == "__main__":
    unittest.main()
