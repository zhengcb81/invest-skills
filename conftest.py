"""Offline publication-fixture isolation shared by the invest-* tests.

Default results are truthfully unattested; fixture generation does not call a
host signer or require a global registry receipt. Tests that check signatures
configure their own valid provider and still use the real signature validator.
No ordinary test may write the owner's registry or load its production dotenv.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys

import pytest

# Apply before test-module imports as well as lazy fixture construction.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ.pop("REVENUE_ATTESTATION_PROVIDER", None)

# Bind this checkout before test modules add optional installed-skill paths.
# Installed deployment tests use an explicit fresh child; the default suite
# must exercise canonical contracts rather than silently select a HOME copy.
_CORE_SCRIPTS = Path(__file__).resolve().parent / "invest-core" / "scripts"
sys.path.insert(0, str(_CORE_SCRIPTS))
_CANONICAL_CONTRACTS = importlib.import_module("invest_contracts")
assert Path(_CANONICAL_CONTRACTS.__file__).resolve() == _CORE_SCRIPTS / "invest_contracts.py"


@pytest.fixture(scope="session", autouse=True)
def _isolate_publication_registry(tmp_path_factory) -> None:
    directory = tmp_path_factory.mktemp("publication-registry")
    os.environ["REVENUE_PUBLICATION_REGISTRY"] = str(directory)
    os.environ.pop("REVENUE_ATTESTATION_PROVIDER", None)
    yield
    os.environ.pop("REVENUE_PUBLICATION_REGISTRY", None)
    os.environ.pop("REVENUE_ATTESTATION_PROVIDER", None)
