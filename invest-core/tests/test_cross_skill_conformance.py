"""Cross-skill contract conformance: revenue-forecast ↔ invest-core.

Both repos independently implement canonical hashing and a subset of validation
primitives.  These tests prove they produce identical outputs for identical
inputs, so invest-* consumers can trust the revenue-forecast reference without
re-validating hashes they already verified.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import unittest
from pathlib import Path


_REVENUE = None
_env_dir = os.environ.get("REVENUE_FORECAST_DIR")
if _env_dir:
    candidate = Path(_env_dir).expanduser().resolve()
    if (candidate / "scripts").is_dir():
        _REVENUE = candidate
if _REVENUE is None:
    _REVENUE = Path(__file__).resolve().parents[2] / "revenue-forecast"
sys.path.insert(0, str(_REVENUE / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

# Revenue-forecast impl (schema 3.5, contracts/evidence.py)
from contracts.evidence import (  # noqa: E402
    canonical_sha256 as revenue_canonical_sha256,
    text_sha256 as revenue_text_sha256,
)

# Invest-core impl (independent, suite 5.2)
from invest_contracts import (  # noqa: E402
    canonical_sha256 as invest_canonical_sha256,
    text_sha256 as invest_text_sha256,
)


class CrossSkillConformanceTests(unittest.TestCase):
    """Every primitive that exists in both repos must produce identical output."""

    # ------------------------------------------------------------------
    # canonical_sha256
    # ------------------------------------------------------------------

    def test_canonical_sha256_primitives(self) -> None:
        self.assertEqual(
            revenue_canonical_sha256("hello"),
            invest_canonical_sha256("hello"),
        )
        self.assertEqual(
            revenue_canonical_sha256(42),
            invest_canonical_sha256(42),
        )

    def test_canonical_sha256_dict_is_stable(self) -> None:
        payload = {"b": 1, "a": 2}
        r = revenue_canonical_sha256(payload)
        i = invest_canonical_sha256(payload)
        self.assertEqual(r, i)
        # verify sort-key stability
        self.assertEqual(r, invest_canonical_sha256({"a": 2, "b": 1}))

    def test_canonical_sha256_nested(self) -> None:
        payload = {"key": [1, 2, {"nested": True}]}
        self.assertEqual(
            revenue_canonical_sha256(payload),
            invest_canonical_sha256(payload),
        )

    def test_canonical_sha256_unicode(self) -> None:
        payload = {"公司": "测试", "value": 100.0}
        self.assertEqual(
            revenue_canonical_sha256(payload),
            invest_canonical_sha256(payload),
        )

    # ------------------------------------------------------------------
    # text_sha256
    # ------------------------------------------------------------------

    def test_text_sha256(self) -> None:
        self.assertEqual(
            revenue_text_sha256("  hello world  "),
            invest_text_sha256("  hello world  "),
        )

    def test_text_sha256_unicode(self) -> None:
        self.assertEqual(
            revenue_text_sha256("营收预测"),
            invest_text_sha256("营收预测"),
        )

    # ------------------------------------------------------------------
    # JSON round-trip stability
    # ------------------------------------------------------------------

    def test_json_canonical_form(self) -> None:
        """Both impls must emit the same canonical JSON bytes for hashing."""
        payload = {"c": 3, "a": 1, "b": [1, 2]}
        rev_bytes = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        rev_digest = hashlib.sha256(rev_bytes).hexdigest()
        self.assertEqual(revenue_canonical_sha256(payload), rev_digest)
        self.assertEqual(invest_canonical_sha256(payload), rev_digest)


if __name__ == "__main__":
    unittest.main()
