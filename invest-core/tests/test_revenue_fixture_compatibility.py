"""Legacy compatibility fixtures bind RF's documented versions, not the live engine."""
from copy import deepcopy
import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(params=["tests_support/revenue_fixtures.py", "invest-core/tests_support/revenue_fixtures.py"])
def factory(request):
    path = ROOT / request.param
    spec = importlib.util.spec_from_file_location("fixture_" + request.param.replace("/", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixture_suite_loads_the_canonical_contract_module():
    import invest_contracts
    assert Path(invest_contracts.__file__).resolve() == ROOT / "invest-core/scripts/invest_contracts.py"


def test_default_fixture_session_does_not_invoke_a_host_signer():
    assert not bool(os.environ.get("REVENUE_ATTESTATION_PROVIDER")), "default test fixtures must be unsigned"
    assert os.environ.get("PYTHON_DOTENV_DISABLED") == "1"


def test_legacy_fixture_uses_a_documented_output_pair(factory):
    from schema_compatibility import validating_engine_allowed, requires_bound_input_schema
    from revenue_report import validate_forecast_output
    result = factory._build_legacy_fixture()
    assert validating_engine_allowed(result["schema_version"], result["engine_version"], "output")
    assert not requires_bound_input_schema(result["schema_version"])
    assert result["publication_receipt"]["engine_version"] == result["engine_version"]
    validate_forecast_output(result)
    assert result["publication_receipt"]["attestation_status"] == "unattested"


def test_new_provider_tags_cannot_retag_or_mutate_the_legacy_fixture(factory, monkeypatch):
    from schema_compatibility import validating_engine_allowed
    from revenue_report import validate_forecast_output
    provider = factory.run_forecast(factory.forecast_document())
    provider.update(schema_version="future-provider-schema", engine_version="9999.0.0")
    before = deepcopy(provider)
    monkeypatch.setattr(factory, "run_forecast", lambda _data: provider)
    result = factory._build_legacy_fixture()
    assert provider == before, "legacy projection must own its data, not mutate a provider cache"
    assert validating_engine_allowed(result["schema_version"], result["engine_version"], "output")
    assert result["engine_version"] != provider["engine_version"]
    validate_forecast_output(result)


def test_cached_fixture_returns_owned_copies_without_recalling_changed_provider(factory, monkeypatch):
    legacy = factory._build_legacy_fixture()
    direct = factory.run_forecast(factory.forecast_document())
    cache = {"legacy": legacy, "direct": direct}
    before = deepcopy(cache)
    monkeypatch.setattr(factory, "_FIXTURES", cache)
    def changed_provider(*_args):
        pytest.fail("cached fixtures must not follow later provider/current-engine changes")
    monkeypatch.setattr(factory, "run_forecast", changed_provider)
    first = factory.load_revenue_fixture("legacy")
    first["engine_version"] = "caller-mutated"
    first["publication_receipt"]["engine_version"] = "caller-mutated"
    current = factory.load_revenue_fixture("direct")
    current["schema_version"] = "caller-mutated"
    assert factory.load_revenue_fixture("legacy") == before["legacy"]
    assert factory.load_revenue_fixture("direct") == before["direct"]
    assert cache == before


def test_invalid_legacy_pair_stays_rejected_even_after_rehash(factory):
    from contracts.evidence import canonical_sha256
    from revenue_report import validate_forecast_output
    result = factory._build_legacy_fixture()
    result["engine_version"] = "9999.0.0"
    result["result_sha256"] = canonical_sha256({k:v for k,v in result.items() if k != "result_sha256"})
    with pytest.raises(ValueError, match="documented compatibility pair"):
        validate_forecast_output(result)
