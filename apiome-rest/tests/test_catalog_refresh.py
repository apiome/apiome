"""Catalog item refresh rules and the one-check runner (MFI-31.1, #4398).

The discovery runners are replaced with fakes, so no network is touched. The tests pin:
validation (refreshable adapters, SSRF URL shape, credential shapes), the fingerprint compare,
the apply hook (called on success only), and failure handling (recorded with backoff, never
applied, so no version can be created).
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Any, List

import pytest
from catalog_refresh_fakes import FakeRefreshStore

from app import catalog_refresh
from app.catalog_refresh import (
    CODE_ADAPTER_NOT_REFRESHABLE,
    CODE_INVALID_CREDENTIAL,
    CODE_INVALID_ENDPOINT,
    TRIGGER_SWEEP,
    ApplyOutcome,
    DiscoveryResult,
    RefreshSettingsError,
    backoff_seconds,
    endpoint_host,
    get_discovery_runner,
    refreshable_adapters,
    register_discovery_runner,
    register_refresh_apply,
    run_refresh_check,
    validate_refresh_settings,
)
from app.config import settings
from app.import_source import ImportSourceError
from app.mcp_credential_crypto import seal_credential_payload

_TENANT = "11111111-1111-4111-8111-111111111111"
_ITEM = "22222222-2222-4222-8222-222222222222"


@pytest.fixture(autouse=True)
def _restore_registry():
    runners = dict(catalog_refresh._RUNNERS)
    hook = catalog_refresh._APPLY_HOOK
    # Each test starts with no hook; the MFI-31.2 versioning hook has its own tests.
    register_refresh_apply(None)
    yield
    catalog_refresh._RUNNERS.clear()
    catalog_refresh._RUNNERS.update(runners)
    register_refresh_apply(hook)


@pytest.fixture
def store(monkeypatch) -> FakeRefreshStore:
    return FakeRefreshStore().install(monkeypatch)


def _fake_runner(fingerprint: str = "fp-1", calls: List[Any] | None = None):
    def _run(endpoint, options, auth_type, auth_payload, timeout):
        if calls is not None:
            calls.append((endpoint, options, auth_type, auth_payload, timeout))
        return DiscoveryResult(fingerprint=fingerprint, model=object(), native=object())

    return _run


def _check(store: FakeRefreshStore, row=None):
    row = row or store.get_refresh_for_check(None, _ITEM)
    return asyncio.run(
        run_refresh_check(None, row, timeout_seconds=5, backoff_base_seconds=300, backoff_max_seconds=86400)
    )


# --- validation ------------------------------------------------------------------------


def test_graphql_grpc_and_fhir_are_the_refreshable_adapters():
    # FHIR joined with MFI-20.1 (#3985): a server's CapabilityStatement from /metadata.
    assert refreshable_adapters() == ["fhir", "graphql", "grpc"]


def test_aliases_resolve_to_the_canonical_adapter():
    assert validate_refresh_settings(cadence="daily", adapter_key="protobuf", endpoint="10.0.0.1:50051") == "grpc"
    assert get_discovery_runner("protobuf") is get_discovery_runner("grpc")


@pytest.mark.parametrize("adapter", ["openapi", "odata", "nope"])
def test_an_adapter_without_a_runner_is_refused(adapter):
    with pytest.raises(RefreshSettingsError) as err:
        validate_refresh_settings(cadence="daily", adapter_key=adapter, endpoint="https://x.example.com")
    assert err.value.code == CODE_ADAPTER_NOT_REFRESHABLE
    assert "graphql" in err.value.message


def test_registering_a_runner_makes_a_live_adapter_refreshable():
    register_discovery_runner("odata", _fake_runner())
    assert (
        validate_refresh_settings(cadence="weekly", adapter_key="odata", endpoint="https://x.example.com/$metadata")
        == "odata"
    )


@pytest.mark.parametrize(
    "endpoint",
    ["file:///etc/passwd", "ftp://x.example.com", "https://user:pw@x.example.com/graphql", "   "],
)
def test_graphql_endpoints_must_pass_the_ssrf_url_policy(endpoint):
    with pytest.raises(RefreshSettingsError) as err:
        validate_refresh_settings(cadence="daily", adapter_key="graphql", endpoint=endpoint)
    assert err.value.code == CODE_INVALID_ENDPOINT


def test_an_unknown_cadence_is_refused():
    with pytest.raises(RefreshSettingsError):
        validate_refresh_settings(cadence="monthly", adapter_key="graphql", endpoint="https://x.example.com")


@pytest.mark.parametrize(
    ("auth_type", "payload"),
    [("bearer", {}), ("header", {"name": "X-Key"}), ("oauth2", {}), ("env", {"A": "b"})],
)
def test_a_malformed_credential_is_refused(auth_type, payload):
    with pytest.raises(RefreshSettingsError) as err:
        validate_refresh_settings(
            cadence="daily",
            adapter_key="graphql",
            endpoint="https://x.example.com",
            auth_type=auth_type,
            auth_payload=payload,
        )
    assert err.value.code == CODE_INVALID_CREDENTIAL


def test_endpoint_host_reads_urls_and_grpc_targets():
    assert endpoint_host("graphql", "https://API.example.com:8443/graphql") == "api.example.com"
    assert endpoint_host("grpc", "grpc.example.com:50051") == "grpc.example.com"
    assert endpoint_host("grpc", "[::1]:50051") == "::1"


def test_backoff_doubles_and_caps():
    assert backoff_seconds(1, base_seconds=300, max_seconds=86400) == 300
    assert backoff_seconds(3, base_seconds=300, max_seconds=86400) == 1200
    assert backoff_seconds(30, base_seconds=300, max_seconds=86400) == 86400


# --- one check -------------------------------------------------------------------------


def test_the_first_check_records_the_baseline_fingerprint(store):
    register_discovery_runner("graphql", _fake_runner("fp-a"))
    store.add(_ITEM, _TENANT)
    outcome = _check(store)
    assert (outcome.status, outcome.fingerprint) == ("unchanged", "fp-a")
    assert store.rows[_ITEM]["last_fingerprint"] == "fp-a"
    assert store.rows[_ITEM]["last_success_at"] is not None


def test_a_different_fingerprint_is_changed_and_the_same_is_unchanged(store):
    register_discovery_runner("graphql", _fake_runner("fp-b"))
    store.add(_ITEM, _TENANT, last_fingerprint="fp-a")
    assert _check(store).status == "changed"
    assert _check(store).status == "unchanged"


def test_the_apply_hook_sees_the_result_and_the_change_flag(store):
    seen = []
    register_discovery_runner("graphql", _fake_runner("fp-b"))
    register_refresh_apply(
        lambda db, row, result, changed, **kw: seen.append((row["project_id"], result.fingerprint, changed, kw))
    )
    store.add(_ITEM, _TENANT, last_fingerprint="fp-a")
    _check(store)
    assert seen == [(_ITEM, "fp-b", True, {"trigger": "manual", "actor_id": None})]


def test_the_trigger_and_actor_reach_the_hook(store):
    seen = []
    register_discovery_runner("graphql", _fake_runner())
    register_refresh_apply(lambda *a, **kw: seen.append(kw))
    store.add(_ITEM, _TENANT)
    row = store.get_refresh_for_check(None, _ITEM)
    asyncio.run(
        run_refresh_check(
            None,
            row,
            timeout_seconds=5,
            backoff_base_seconds=300,
            backoff_max_seconds=86400,
            trigger=TRIGGER_SWEEP,
            actor_id="u-1",
        )
    )
    assert seen == [{"trigger": "sweep", "actor_id": "u-1"}]


def test_an_apply_outcome_decides_the_status_and_names_the_version(store):
    register_discovery_runner("graphql", _fake_runner("fp-a"))
    register_refresh_apply(
        lambda *a, **kw: ApplyOutcome(changed=True, version_id="v-9", version_label="2026-10-27T12:00Z")
    )
    store.add(_ITEM, _TENANT)  # first check: no last fingerprint, yet the source differs from the item
    outcome = _check(store)
    assert (outcome.status, outcome.version_id, outcome.version_label) == ("changed", "v-9", "2026-10-27T12:00Z")
    assert store.rows[_ITEM]["status"] == "changed"

    register_refresh_apply(lambda *a, **kw: ApplyOutcome(changed=False))
    store.rows[_ITEM]["last_fingerprint"] = "fp-old"  # differs from the last check, matches the item
    outcome = _check(store)
    assert (outcome.status, outcome.version_id) == ("unchanged", None)


def test_a_failure_is_recorded_with_backoff_and_never_applied(store):
    applied = []

    def _boom(*args):
        raise ImportSourceError("introspection is disabled on this server")

    register_discovery_runner("graphql", _boom)
    register_refresh_apply(lambda *args: applied.append(args))
    store.add(_ITEM, _TENANT, last_fingerprint="fp-a", status="unchanged")
    outcome = _check(store)
    row = store.rows[_ITEM]
    assert outcome.status == "failed"
    assert row["status"] == "failed" and "introspection is disabled" in row["last_error"]
    assert row["consecutive_failures"] == 1
    assert row["next_check_after"] > store.now
    assert row["last_fingerprint"] == "fp-a"  # history untouched
    assert applied == []


def test_consecutive_failures_back_off_exponentially(store):
    register_discovery_runner("graphql", lambda *a: (_ for _ in ()).throw(RuntimeError("down")))
    store.add(_ITEM, _TENANT, consecutive_failures=2)
    _check(store)
    row = store.rows[_ITEM]
    assert row["consecutive_failures"] == 3
    assert (row["next_check_after"] - store.now).total_seconds() == 1200


def test_a_hook_error_fails_the_check(store):
    register_discovery_runner("graphql", _fake_runner())
    register_refresh_apply(lambda *args: (_ for _ in ()).throw(RuntimeError("pipeline down")))
    store.add(_ITEM, _TENANT)
    assert _check(store).status == "failed"
    assert store.rows[_ITEM]["last_fingerprint"] is None


def test_a_slow_discovery_times_out_as_a_failure(store):
    import time

    register_discovery_runner("graphql", lambda *a: time.sleep(0.5))
    store.add(_ITEM, _TENANT)
    row = store.get_refresh_for_check(None, _ITEM)
    outcome = asyncio.run(
        run_refresh_check(None, row, timeout_seconds=0.05, backoff_base_seconds=60, backoff_max_seconds=600)
    )
    assert outcome.status == "failed" and outcome.error == "The check timed out."


def test_the_error_is_trimmed_to_one_line(store):
    register_discovery_runner("graphql", lambda *a: (_ for _ in ()).throw(RuntimeError("a\nb  " + "x" * 2000)))
    store.add(_ITEM, _TENANT)
    error = _check(store).error
    assert "\n" not in error and len(error) == catalog_refresh.MAX_ERROR_LENGTH


def test_the_sealed_credential_reaches_the_runner(store, monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", None)
    blob, version = seal_credential_payload({"token": "s3cret"})
    calls: List[Any] = []
    register_discovery_runner("graphql", _fake_runner(calls=calls))
    store.add(_ITEM, _TENANT, auth_type="bearer", encrypted_payload=blob, key_version=version)
    assert _check(store).status == "unchanged"
    assert calls[0][2:4] == ("bearer", {"token": "s3cret"})


def test_an_unsealable_credential_fails_instead_of_running_anonymously(store):
    calls: List[Any] = []
    register_discovery_runner("graphql", _fake_runner(calls=calls))
    store.add(_ITEM, _TENANT, auth_type="bearer", encrypted_payload=b"garbage", key_version=9)
    outcome = _check(store)
    assert outcome.status == "failed" and "could not be unsealed" in outcome.error
    assert calls == []


def test_grpc_runner_passes_the_secure_option(monkeypatch):
    seen = {}

    class _Compiled:
        descriptor_set_bytes = b"descriptor-set"

    class _Source:
        supports_live_discovery = True

        def discover(self, target, **kwargs):
            seen.update(target=target, **kwargs)
            return _Compiled()

    imported = []
    monkeypatch.setattr(catalog_refresh, "get_import_source", lambda key: _Source())
    monkeypatch.setattr(
        catalog_refresh,
        "pipeline_discovery_result",
        lambda key, document, filename, native=None: imported.append((key, document, filename))
        or DiscoveryResult(fingerprint="fp-grpc", model=object(), native=native, document=document),
    )
    result = catalog_refresh._grpc_runner("h.example.com:443", {"secure": True}, "none", None, 12.0)
    assert result.fingerprint == "fp-grpc"
    assert imported == [("grpc", b"descriptor-set", "reflection.binpb")]
    assert seen == {
        "target": "h.example.com:443",
        "secure": True,
        "timeout": 12.0,
        "auth_type": None,
        "auth_payload": None,
    }
