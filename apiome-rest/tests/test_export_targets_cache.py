"""The export targets list cache and its route (``GET /v1/export/{tenant}/targets``).

Covers :mod:`app.export_targets_cache` (key, TTL, LRU) and what the route does with it: a repeat
request for the same source is served from the cache without predicting again, a changed source,
tenant or registry misses, and one target whose prediction fails is listed as unavailable instead
of failing the whole list.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.export_fidelity_jobs import fidelity_jobs
from app.export_source import ExportSource
from app.export_targets_cache import TargetsCache, build_targets_cache_key, targets_cache
from app.main import app

client = TestClient(app)

_AUTH = {"tenant_id": "tenant-a", "user_id": "user-1", "auth_method": "jwt"}
_REGISTRY = [("openapi", True), ("avro", True)]


@pytest.fixture(autouse=True)
def _auth_and_empty_cache():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    targets_cache().clear()
    fidelity_jobs().clear()
    yield
    app.dependency_overrides.clear()
    targets_cache().clear()
    fidelity_jobs().clear()


def _key(**overrides: Any):
    args: Dict[str, Any] = dict(
        tenant_id="tenant-a",
        version_record_id="rev-1",
        source_text='{"openapi": "3.1.0"}',
        source_format="openapi",
        plans=None,
        apiome_version="1.0.0",
        registry=_REGISTRY,
    )
    args.update(overrides)
    return build_targets_cache_key(**args)


def _source(source_text: str = '{"openapi": "3.1.0"}') -> ExportSource:
    widget = Type(
        key="Widget",
        name="Widget",
        kind=TypeKind.RECORD,
        fields=[CanonicalField(key="Widget.id", name="id", type=TypeRef(name="string"))],
    )
    op = Operation(key="GET /widgets", name="listWidgets", kind=OperationKind.QUERY)
    api = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="widgets"),
        services=[Service(key="widgets", name="widgets", operations=[op])],
        types=[widget],
    )
    return ExportSource(
        api=api,
        artifact_id="artifact-1",
        version_record_id="rev-1",
        version_label="1.0.0",
        source_text=source_text,
        source_format="openapi",
    )


# --- key -------------------------------------------------------------------------------------


def test_the_key_is_stable_for_the_same_inputs() -> None:
    assert _key() == _key()


@pytest.mark.parametrize(
    "change",
    [
        {"tenant_id": "tenant-b"},
        {"version_record_id": "rev-2"},
        {"source_text": '{"openapi": "3.0.3"}'},
        {"source_format": "swagger"},
        {"plans": [{"name": "Gold"}]},
        {"apiome_version": "1.0.1"},
        {"registry": [("openapi", True), ("avro", False)]},
        {"registry": [*_REGISTRY, ("probe", True)]},
    ],
)
def test_every_input_changes_the_key(change: Dict[str, Any]) -> None:
    assert _key(**change) != _key()


def test_a_source_without_text_is_not_cached() -> None:
    assert _key(source_text=None) is None
    cache = TargetsCache()
    cache.put(None, ["entry"])
    assert cache.get(None) is None and len(cache) == 0


# --- store -----------------------------------------------------------------------------------


def test_an_entry_expires_after_the_ttl() -> None:
    cache = TargetsCache(ttl_seconds=10.0)
    with patch("app.export_targets_cache.time.monotonic", return_value=100.0):
        cache.put(_key(), ["entry"])
    with patch("app.export_targets_cache.time.monotonic", return_value=109.0):
        assert cache.get(_key()) == ["entry"]
    with patch("app.export_targets_cache.time.monotonic", return_value=111.0):
        assert cache.get(_key()) is None
    assert len(cache) == 0


def test_the_least_recently_used_entry_is_dropped() -> None:
    cache = TargetsCache(max_entries=2)
    first, second, third = _key(version_record_id="1"), _key(version_record_id="2"), _key(version_record_id="3")
    cache.put(first, ["1"])
    cache.put(second, ["2"])
    assert cache.get(first) == ["1"]  # first is now the most recent
    cache.put(third, ["3"])
    assert cache.get(second) is None
    assert cache.get(first) == ["1"] and cache.get(third) == ["3"]


def test_a_returned_list_is_a_copy() -> None:
    cache = TargetsCache()
    cache.put(_key(), ["entry"])
    cache.get(_key()).append("mutated")
    assert cache.get(_key()) == ["entry"]


# --- route -----------------------------------------------------------------------------------


def _targets(artifact: str = "artifact-1"):
    return client.get("/v1/export/tenant-a/targets", params={"artifact": artifact})


def test_a_repeat_request_is_served_from_the_cache() -> None:
    from app import export_routes

    with patch("app.export_routes.load_export_source", side_effect=lambda *a: _source()), patch(
        "app.export_routes.build_target_fidelity_entries", wraps=export_routes.build_target_fidelity_entries
    ) as build:
        first = _targets()
        second = _targets()
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert build.call_count == 1


def test_a_changed_source_is_predicted_again() -> None:
    from app import export_routes

    sources = iter([_source('{"a": 1}'), _source('{"a": 2}')])
    with patch("app.export_routes.load_export_source", side_effect=lambda *a: next(sources)), patch(
        "app.export_routes.build_target_fidelity_entries", wraps=export_routes.build_target_fidelity_entries
    ) as build:
        assert _targets().status_code == 200
        assert _targets().status_code == 200
    assert build.call_count == 2


def test_another_tenant_does_not_see_a_cached_list() -> None:
    from app import export_routes

    with patch("app.export_routes.load_export_source", side_effect=lambda *a: _source()), patch(
        "app.export_routes.build_target_fidelity_entries", wraps=export_routes.build_target_fidelity_entries
    ) as build:
        assert _targets().status_code == 200
        app.dependency_overrides[validate_authentication] = lambda: {**_AUTH, "tenant_id": "tenant-b"}
        assert _targets().status_code == 200
    assert build.call_count == 2


def test_a_target_whose_prediction_fails_is_listed_unavailable() -> None:
    """One failing rule pack used to turn the whole list into a 500."""
    from app import export_fidelity

    real = export_fidelity.build_target_fidelity

    def flaky(api, emitter_cls):
        if emitter_cls.key == "avro":
            raise ValueError("No free segment ID left for 'Widget'")
        return real(api, emitter_cls)

    with patch("app.export_routes.load_export_source", side_effect=lambda *a: _source()), patch(
        "app.export_routes.build_target_fidelity", side_effect=flaky
    ):
        response = _targets()
    assert response.status_code == 200
    by_key = {t["descriptor"]["key"]: t for t in response.json()["targets"]}
    avro = by_key["avro"]["descriptor"]
    assert avro["available"] is False
    assert "cannot be produced from this source" in avro["unavailable_reason"]
    assert "No free segment ID left" in avro["unavailable_reason"]
    # Every other target still carries its prediction.
    assert by_key["openapi"]["descriptor"]["available"] is True
    assert by_key["openapi"]["fidelity"]["total"] > 0


# --- deferred mode ---------------------------------------------------------------------------


def _deferred(artifact: str = "artifact-1"):
    return client.get("/v1/export/tenant-a/targets", params={"artifact": artifact, "fidelity": "deferred"})


def _poll(token: str, *, attempts: int = 200):
    import time

    for _ in range(attempts):
        response = client.get(f"/v1/export/tenant-a/targets/fidelity/{token}")
        if response.status_code != 200 or response.json()["status"] != "pending":
            return response
        time.sleep(0.02)
    raise AssertionError("scoring never finished")


def test_a_deferred_request_returns_unscored_targets_and_a_token() -> None:
    import threading

    from app import export_routes

    release = threading.Event()
    real = export_routes.build_target_fidelity_entries

    def slow(api):
        release.wait(5)
        return real(api)

    with patch("app.export_routes.load_export_source", side_effect=lambda *a: _source()), patch(
        "app.export_routes.build_target_fidelity_entries", side_effect=slow
    ):
        response = _deferred()
        body = response.json()
        assert response.status_code == 200
        assert body["fidelity_status"] == "pending" and body["fidelity_token"]
        assert body["targets"] and all(t["fidelity"] is None for t in body["targets"])
        pending = client.get(f"/v1/export/tenant-a/targets/fidelity/{body['fidelity_token']}")
        assert pending.json() == {"status": "pending", "targets": None, "error": None}
        release.set()
        ready = _poll(body["fidelity_token"])
    assert ready.status_code == 200
    scored = ready.json()
    assert scored["status"] == "ready"
    assert [t["descriptor"]["key"] for t in scored["targets"]] == [t["descriptor"]["key"] for t in body["targets"]]
    assert all(t["fidelity"] is not None for t in scored["targets"])


def test_a_deferred_request_after_scoring_is_answered_scored() -> None:
    with patch("app.export_routes.load_export_source", side_effect=lambda *a: _source()):
        token = _deferred().json()["fidelity_token"]
        _poll(token)
        again = _deferred().json()
    assert again["fidelity_status"] == "ready" and again["fidelity_token"] is None
    assert all(t["fidelity"] is not None for t in again["targets"])


def test_deferred_and_inline_requests_share_one_scoring() -> None:
    from app import export_routes

    with patch("app.export_routes.load_export_source", side_effect=lambda *a: _source()), patch(
        "app.export_routes.build_target_fidelity_entries", wraps=export_routes.build_target_fidelity_entries
    ) as build:
        token = _deferred().json()["fidelity_token"]
        inline = _targets().json()
        assert _poll(token).json()["status"] == "ready"
    assert build.call_count == 1
    assert inline["fidelity_status"] == "ready"


def test_another_tenant_cannot_poll_a_token() -> None:
    with patch("app.export_routes.load_export_source", side_effect=lambda *a: _source()):
        token = _deferred().json()["fidelity_token"]
        _poll(token)
        app.dependency_overrides[validate_authentication] = lambda: {**_AUTH, "tenant_id": "tenant-b"}
        response = client.get(f"/v1/export/tenant-a/targets/fidelity/{token}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "fidelity-job-unknown"


def test_an_unknown_token_is_404() -> None:
    response = client.get("/v1/export/tenant-a/targets/fidelity/0123456789abcdef0123456789abcdef")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "fidelity-job-unknown"


# --- job pool --------------------------------------------------------------------------------


def test_a_failed_job_reports_failed_and_is_retried_by_the_next_submit() -> None:
    from app.export_fidelity_jobs import FidelityJobs

    jobs = FidelityJobs(max_workers=1)
    calls = []

    def boom():
        calls.append("boom")
        raise RuntimeError("out of memory")

    token = jobs.submit(_key(), "tenant-a", boom)
    with pytest.raises(RuntimeError):
        jobs._jobs[token].future.result(timeout=5)
    assert jobs.status(token, "tenant-a") == ("failed", None, "out of memory")
    assert jobs.wait(_key(), "tenant-a", lambda: ["ok"]) == ["ok"]


def test_a_finished_job_expires() -> None:
    from app.export_fidelity_jobs import FidelityJobs

    jobs = FidelityJobs(max_workers=1, ttl_seconds=10.0)
    assert jobs.wait(_key(), "tenant-a", lambda: ["ok"]) == ["ok"]
    token = next(iter(jobs._jobs))
    finished = jobs._jobs[token].finished_at
    with patch("app.export_fidelity_jobs.time.monotonic", return_value=finished + 11.0):
        assert jobs.status(token, "tenant-a") is None
    assert len(jobs) == 0


def test_the_pool_runs_at_most_its_worker_count_at_once() -> None:
    """However many sources are scored at once, only ``max_workers`` threads run."""
    import threading
    import time

    from app.export_fidelity_jobs import FidelityJobs

    jobs = FidelityJobs(max_workers=2)
    running = 0
    peak = 0
    lock = threading.Lock()

    def work():
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.05)
        with lock:
            running -= 1
        return ["done"]

    tokens = [jobs.submit(_key(version_record_id=str(i)), "tenant-a", work) for i in range(6)]
    for token in tokens:
        jobs._jobs[token].future.result(timeout=5)
    assert peak == 2
