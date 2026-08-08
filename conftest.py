"""Shared test isolation for every invest-* module.

Legitimate revenue fixtures are generated through revenue-forecast's
run_forecast, which since R1.2/R2.1 registers its anchor and carries an
attestation status.  Point both at test-local state so fixtures are generated
as registered + host_signed and the default consumer gates accept them; no
test may ever write the canonical repo's artifacts/registry.
"""

from __future__ import annotations

import os
import sys

import pytest


@pytest.fixture(scope="session", autouse=True)
def _isolate_publication_registry(tmp_path_factory) -> None:
    directory = tmp_path_factory.mktemp("publication-registry")
    os.environ["REVENUE_PUBLICATION_REGISTRY"] = str(directory)
    os.environ["REVENUE_ATTESTATION_PROVIDER"] = sys.executable
    yield
    os.environ.pop("REVENUE_PUBLICATION_REGISTRY", None)
    os.environ.pop("REVENUE_ATTESTATION_PROVIDER", None)
