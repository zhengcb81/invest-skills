from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from invest_contracts import (  # noqa: E402
    InvestmentArtifactError,
    canonical_sha256,
    compute_security_value,
    render_parameter_template,
)


class PropertyInvariantTests(unittest.TestCase):
    def test_canonical_hash_is_independent_of_mapping_insertion_order(self) -> None:
        generator = random.Random(20260713)
        for _ in range(100):
            pairs = [(f"key_{index}", generator.uniform(-1_000, 1_000)) for index in range(12)]
            left = dict(pairs)
            generator.shuffle(pairs)
            right = dict(pairs)
            self.assertEqual(canonical_sha256(left), canonical_sha256(right))

    def test_security_bridge_obeys_linear_conversion_identity(self) -> None:
        generator = random.Random(50000)
        bridge = {
            "security_id": "TEST-ADS", "security_type": "ADS", "listing_currency": "USD",
            "diluted_share_count_parameter_template": "shares_{scenario}",
            "ordinary_units_per_security_parameter_template": "units_{scenario}",
        }
        identity = {"currency": "USD", "as_of_date": "2026-07-13"}
        for _ in range(100):
            equity = generator.uniform(1, 1_000_000)
            shares = generator.uniform(1, 100_000)
            units = generator.uniform(0.1, 20)
            parameters = [
                {"parameter_id": "shares_base", "value": shares, "dimension": "quantity", "time_basis": "point_in_time", "scenario": "base"},
                {"parameter_id": "units_base", "value": units, "dimension": "quantity", "time_basis": "point_in_time", "scenario": "base"},
            ]
            result = compute_security_value(bridge, parameters, "base", identity, equity)
            assert result is not None
            self.assertAlmostEqual(result["per_security_value_current"], equity * units / shares)

    def test_unknown_parameter_template_placeholders_always_fail(self) -> None:
        for template in ("value_{company}", "value_{scenario}_{period}", "value_{year!bad}", "value_{"):
            with self.subTest(template=template), self.assertRaises(InvestmentArtifactError):
                render_parameter_template(template, "base", year=2027)


if __name__ == "__main__":
    unittest.main()
