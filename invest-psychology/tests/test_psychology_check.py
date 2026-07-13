from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from psychology_check import PsychologyInputError, QUESTIONS, run_check  # noqa: E402


class PsychologyCheckTests(unittest.TestCase):
    def test_reports_user_answers_without_score(self) -> None:
        answers = {key: "yes" for key in QUESTIONS}
        result = run_check({"decision": "research further", "thesis": "test thesis", "answers": answers})
        self.assertNotIn("score", result)
        self.assertIn("anchoring", result["user_acknowledged_review_triggers"])

    def test_unknown_answer_is_preserved(self) -> None:
        result = run_check({"decision": "research further", "thesis": "test thesis", "answers": {}})
        self.assertEqual(len(result["unanswered_or_unknown"]), len(QUESTIONS))

    def test_invalid_answer_is_rejected(self) -> None:
        with self.assertRaisesRegex(PsychologyInputError, "yes/no/unknown"):
            run_check({"decision": "x", "thesis": "y", "answers": {"fomo": "maybe"}})


if __name__ == "__main__":
    unittest.main()
