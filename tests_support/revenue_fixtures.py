"""Versioned public revenue-forecast outputs used by invest-suite tests.

These fixtures deliberately freeze validated outputs instead of importing helper
functions from another project's private test modules.  Callers receive a fresh
object on every load so mutation tests cannot contaminate later cases.
"""

from __future__ import annotations

import json
import base64
import gzip
from pathlib import Path
from typing import Any


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURES = {
    "direct": "revenue-direct-3.2-v3.3.0.json",
    "effective": "revenue-effective-3.2-v3.3.0.json",
    "heterogeneous": "revenue-heterogeneous-3.2-v3.3.0.json.gz.b64",
    "recognition": "revenue-recognition-3.2-v3.3.0.json",
    "target": "revenue-target-3.2-v3.3.0.json",
}


def load_revenue_fixture(name: str = "direct") -> dict[str, Any]:
    """Load one immutable, version-named revenue output as a fresh mapping."""
    try:
        path = FIXTURE_DIR / FIXTURES[name]
    except KeyError as exc:
        raise ValueError(f"unknown revenue fixture: {name}") from exc
    if path.name.endswith(".json.gz.b64"):
        compressed = base64.b64decode(path.read_text(encoding="ascii"))
        return json.loads(gzip.decompress(compressed).decode("utf-8"))
    return json.loads(path.read_text(encoding="utf-8"))
