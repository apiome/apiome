"""Schema-registry crawl budgets, checkpoint resume and incremental passes (MFI-31.4, #4401).

The acceptance criteria, over the real connector engine and the fake upstream registry
(:mod:`tests.schema_registry_upstream_fake`):

* a crawl of a **10,000-subject** registry stays inside its request and page budget, records where
  it stopped, and the next sync resumes there instead of listing from the start;
* a sync **killed** mid-way resumes from the last checkpoint: the subjects it had settled are not
  read again;
* after a completed full pass, an **incremental** sync probes the schema ids above the watermark and
  reads only the subjects that changed, never the rest; a later full pass catches a deletion;
* a registry that does not answer the probe (Apicurio's compatibility API) gets a full pass.

The checkpoint store is an in-memory fake; everything else is the production code path.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest
from catalog_connector_fakes import FakeConnectorStore, restore_builtin_sources

from app import catalog_connector_sync as sync
from app import schema_registry_connector_source as src
from app.catalog_connector_sync import register_connector_source, run_connector_sync
from app.catalog_connectors import ConnectorError
from app.config import settings
from app.crawl_budget import CrawlState, HostRateLimiter
from tests.schema_registry_fakes import FakeStore
from tests.schema_registry_upstream_fake import APICURIO, FakeUpstreamRegistry
from tests.test_schema_registry_connector_source import MirrorDb

TENANT = "11111111-1111-4111-8111-111111111111"
ACTOR = "33333333-3333-4333-8333-333333333333"


def _avro(n: int) -> str:
    return json.dumps(
        {"type": "record", "name": f"Rec{n}", "namespace": "acme", "fields": [{"name": "id", "type": "string"}]}
    )


def _registry(count: int, *, flavor: str = "confluent") -> FakeUpstreamRegistry:
    """``count`` subjects ``topic-00000-value`` … each with one version whose schema id is ``n + 1``."""
    subjects = {f"topic-{n:05d}-value": {1: {"id": n + 1, "schema": _avro(n)}} for n in range(count)}
    return FakeUpstreamRegistry(subjects, flavor=flavor)


class _NoWait(HostRateLimiter):
    def __init__(self) -> None:
        super().__init__(1.0)

    def wait(self, host: str) -> None:
        del host


class _Checkpoints:
    """In-memory ``catalog_connector_crawl_state``."""

    def __init__(self) -> None:
        self.rows: Dict[str, CrawlState] = {}
        self.writes = 0

    def install(self, monkeypatch) -> "_Checkpoints":
        monkeypatch.setattr(src, "load_crawl_state", lambda db, cid: self.rows.get(cid, CrawlState()))
        monkeypatch.setattr(src, "save_crawl_state", self._save)
        return self

    def _save(self, db, cid, state):
        self.rows[cid] = state
        self.writes += 1


class _Killed(BaseException):
    """Stands in for the process dying: not an ``Exception``, so the engine cannot catch it."""


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(
        settings, "mcp_credential_encryption_keys", json.dumps({"1": base64.b64encode(os.urandom(32)).decode()})
    )
    monkeypatch.setattr(settings, "ssrf_allow_private", True)
    monkeypatch.setattr(sync, "owner_recorder", lambda *a, **k: [])
    monkeypatch.setattr("app.gateway_config_store.refresh_gateway_configs", lambda *a, **k: 0)
    yield
    restore_builtin_sources()


@pytest.fixture
def store(monkeypatch):
    return FakeConnectorStore().install(monkeypatch)


@pytest.fixture
def db(monkeypatch):
    catalog = MirrorDb()
    monkeypatch.setattr("app.import_source_pipeline.run_adapter_import_job", catalog.run_import)
    return catalog


@pytest.fixture
def subjects(monkeypatch, db):
    return FakeStore(db).install(monkeypatch)


@pytest.fixture
def checkpoints(monkeypatch):
    return _Checkpoints().install(monkeypatch)


def _use(fake: FakeUpstreamRegistry) -> None:
    register_connector_source(
        src.KIND,
        lambda c, creds: src.SchemaRegistrySource(c, creds, transport=fake.transport(), limiter=_NoWait()),
        scope_validator=src.validate_schema_registry_scope,
    )


def _connector(store, fake: FakeUpstreamRegistry, scope: Dict[str, Any]):
    return store.add_connector(
        TENANT, kind=src.KIND, name="Prod registry", base_url=fake.base_url + "/", scope=scope, created_by=ACTOR
    )


def _sync(store, db, connector):
    return run_connector_sync(db, store.connectors[connector["id"]], actor_id=ACTOR)


def _requests_since(fake: FakeUpstreamRegistry, start: int) -> List[str]:
    return fake.paths()[start:]


def _detail_subjects(paths: List[str]) -> List[str]:
    """The subjects whose version list a run read (one ``/subjects/{s}/versions`` per listed subject)."""
    return [p.split("/")[2] for p in paths if p.startswith("/subjects/") and p.endswith("/versions")]


# --- budget and resume over 10,000 subjects --------------------------------------------------


def test_a_10k_registry_is_crawled_within_budget_and_each_sync_resumes(store, db, subjects, checkpoints):
    fake = _registry(10_000)
    _use(fake)
    connector = _connector(store, fake, {"maxRequests": 400, "maxPages": 3})

    first = _sync(store, db, connector)
    paths = _requests_since(fake, 0)
    crawl = first.summary["crawl"]
    assert first.status == "succeeded"
    assert len(paths) <= 400 and crawl["requests"] == len(paths)
    assert crawl["pages"] <= 3
    assert crawl["mode"] == "full" and crawl["partial"] is True
    listed = _detail_subjects(paths)
    assert listed == sorted(listed) and listed[0] == "topic-00000-value"
    cursor = checkpoints.rows[connector["id"]].cursor
    assert cursor == listed[-1] == crawl["resumesAfter"]
    assert first.summary["missing"] == 0  # GET /subjects still lists every live subject

    mark = len(fake.paths())
    second = _sync(store, db, connector)
    paths = _requests_since(fake, mark)
    assert len(paths) <= 400
    resumed = _detail_subjects(paths)
    assert resumed[0] > cursor  # resumed after the checkpoint, not from the start
    assert not set(resumed) & set(listed)
    assert second.summary["crawl"]["resumesAfter"] == resumed[-1]


def test_a_killed_sync_resumes_from_its_last_checkpoint(store, db, subjects, checkpoints, monkeypatch):
    fake = _registry(500)
    _use(fake)
    connector = _connector(store, fake, {"maxRequests": 1000})

    real = src.SchemaRegistrySource.sync_item
    synced: List[str] = []

    def dying(self, db_, candidate, row, actor_id):
        if len(synced) == 30:
            raise _Killed()
        synced.append(candidate.remote_id)
        return real(self, db_, candidate, row, actor_id)

    monkeypatch.setattr(src.SchemaRegistrySource, "sync_item", dying)
    with pytest.raises(_Killed):
        _sync(store, db, connector)
    cursor = checkpoints.rows[connector["id"]].cursor
    assert cursor == synced[-1] == "topic-00029-value"  # the checkpoint was written as subjects settled

    # The stale-run reaper closes the dead run; the next sync starts.
    for run in store.runs.values():
        run["status"] = "failed"
    monkeypatch.setattr(src.SchemaRegistrySource, "sync_item", real)
    mark = len(fake.paths())
    result = _sync(store, db, connector)
    resumed = _detail_subjects(_requests_since(fake, mark))
    assert result.status == "succeeded"
    assert resumed[0] == "topic-00030-value"  # the subject it died on is read again …
    assert not set(resumed) & set(synced)  # … the ones it had settled are not


def test_a_spent_request_budget_defers_the_rest_without_failing(store, db, subjects, checkpoints):
    fake = FakeUpstreamRegistry(
        {f"s-{n:03d}": {v: {"id": n * 10 + v, "schema": _avro(n * 10 + v)} for v in range(1, 6)} for n in range(40)}
    )
    _use(fake)
    connector = _connector(store, fake, {"maxRequests": 60})
    result = _sync(store, db, connector)
    crawl = result.summary["crawl"]
    assert result.status == "succeeded"
    assert crawl["exhaustedBy"] == "requests" and crawl["requests"] == 60
    assert result.summary["deferred"] > 0 and result.summary["failed"] == 0
    # The cursor stops before the first subject that was not fully mirrored.
    cursor = checkpoints.rows[connector["id"]].cursor
    deferred_from = sorted(name for name in fake.subjects if name > (cursor or ""))
    assert deferred_from and crawl["partial"] is True


# --- incremental ----------------------------------------------------------------------------


def test_after_a_full_pass_an_incremental_sync_reads_only_changed_subjects(store, db, subjects, checkpoints):
    fake = _registry(300)
    _use(fake)
    connector = _connector(store, fake, {"maxRequests": 5000, "maxPages": 10})

    full = _sync(store, db, connector)
    state = checkpoints.rows[connector["id"]]
    assert full.summary["crawl"]["mode"] == "full" and full.summary["crawl"]["partial"] is False
    assert state.cursor is None and state.pass_started_at is None and state.last_full_pass_at is not None
    assert state.watermark == 300

    # Two subjects gain a version and one subject is new; one subject is deleted.
    fake.subjects["topic-00007-value"][2] = {"id": 301, "schema": _avro(1007)}
    fake.subjects["topic-00150-value"][2] = {"id": 302, "schema": _avro(1150)}
    fake.subjects["topic-new-value"] = {1: {"id": 303, "schema": _avro(1303)}}
    del fake.subjects["topic-00299-value"]

    mark = len(fake.paths())
    incremental = _sync(store, db, connector)
    paths = _requests_since(fake, mark)
    crawl = incremental.summary["crawl"]
    assert crawl["mode"] == "incremental"
    assert "/subjects" not in paths  # no full listing
    assert sorted(set(_detail_subjects(paths))) == ["topic-00007-value", "topic-00150-value", "topic-new-value"]
    assert paths[0] == "/schemas/ids/300/versions?deleted=true"  # the support check at the watermark
    assert checkpoints.rows[connector["id"]].watermark == 303
    assert incremental.summary["missing"] == 0  # an incremental pass never marks anything missing
    assert incremental.summary["imported"] == 3

    # Nothing changed since: the next incremental sync probes and reads no subject.
    mark = len(fake.paths())
    quiet = _sync(store, db, connector)
    assert _detail_subjects(_requests_since(fake, mark)) == []
    assert quiet.summary["crawl"]["mode"] == "incremental"

    # Once fullPassHours has passed, a full pass runs and catches the deletion.
    checkpoints.rows[connector["id"]] = checkpoints.rows[connector["id"]].with_changes(
        last_full_pass_at=datetime.now(timezone.utc) - timedelta(hours=25)
    )
    again = _sync(store, db, connector)
    assert again.summary["crawl"]["mode"] == "full"
    assert again.summary["missing"] == 1


def test_a_registry_without_the_probe_gets_full_passes(store, db, subjects, checkpoints):
    fake = _registry(20, flavor=APICURIO)
    _use(fake)
    connector = _connector(store, fake, {})
    _sync(store, db, connector)
    assert checkpoints.rows[connector["id"]].last_full_pass_at is not None

    result = _sync(store, db, connector)
    crawl = result.summary["crawl"]
    assert crawl["mode"] == "full" and crawl["fallback"] == "probe-unsupported"
    assert checkpoints.rows[connector["id"]].probe_supported is False

    # From then on the probe is not tried again.
    mark = len(fake.paths())
    _sync(store, db, connector)
    assert not any(p.startswith("/schemas/ids/") for p in _requests_since(fake, mark))


def test_without_a_checkpoint_store_a_sync_still_runs_a_full_pass(store, db, subjects):
    fake = _registry(5)
    _use(fake)
    connector = _connector(store, fake, {})
    result = _sync(store, db, connector)  # MirrorDb has no execute_query: the checkpoint is unavailable
    assert result.status == "succeeded" and result.summary["imported"] == 5
    assert result.summary["crawl"]["mode"] == "full"


# --- scope ----------------------------------------------------------------------------------


def test_scope_accepts_the_budget_keys_and_full_pass_hours():
    src.validate_schema_registry_scope(
        {"requestsPerSecond": 5, "maxRequests": 20_000, "maxPages": 100, "maxBytes": 10_000_000, "fullPassHours": 6},
        "https://sr.example.test",
    )


@pytest.mark.parametrize(
    "scope,message",
    [
        ({"maxRequests": 0}, "maxRequests must be a whole number above 0"),
        ({"requestsPerSecond": 100}, "at most 50"),
        ({"fullPassHours": 0}, "fullPassHours must be a whole number from 1 to 720"),
        ({"fullPassHours": 1.5}, "fullPassHours"),
        ({"subjects": ["a"]}, "Unknown scope key(s)"),
    ],
)
def test_scope_refuses_bad_values(scope, message):
    with pytest.raises(ConnectorError) as exc:
        src.validate_schema_registry_scope(scope, "https://sr.example.test")
    assert exc.value.code == "connector-invalid" and message in str(exc.value)
