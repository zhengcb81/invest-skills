"""Explicitly rebuild the frozen offline fixture from its embedded input.

This command is never called by the E2E harness. It runs current canonical RF
arithmetic once, without a signer/network, and writes a genuine emitted result.
It does not relabel an old output, mutate assumptions, or update golden values.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import sys
import tempfile

from offline_cli import install_offline_guard

HERE = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=HERE / "fixtures/biren_forecast.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8"))
    embedded = source.get("input_document")
    if not isinstance(embedded, dict):
        parser.error("source must contain its frozen input_document")
    install_offline_guard()
    rf = Path(os.environ.get("REVENUE_FORECAST_DIR") or HERE.parent.parent / "revenue-forecast").resolve()
    sys.path.insert(0, str(rf / "scripts"))
    from revenue_core import run_forecast
    from revenue_report import validate_published_forecast
    previous = os.environ.get("REVENUE_PUBLICATION_REGISTRY")
    try:
        with tempfile.TemporaryDirectory(prefix="invest-fixture-") as registry:
            os.environ["REVENUE_PUBLICATION_REGISTRY"] = registry
            result = run_forecast(copy.deepcopy(embedded))
            validate_published_forecast(result, embedded)
    finally:
        if previous is None:
            os.environ.pop("REVENUE_PUBLICATION_REGISTRY", None)
        else:
            os.environ["REVENUE_PUBLICATION_REGISTRY"] = previous
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "schema_version": result["schema_version"], "engine_version": result["engine_version"],
        "input_sha256": result["input_sha256"], "result_sha256": result["result_sha256"],
        "attestation_status": result["publication_receipt"]["attestation_status"],
        "output": str(args.output.resolve()),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
