"""Catalog item refresh → import pipeline (MFI-31.2, #4399).

Pins the acceptance criteria without a network or a database:

* the runners hand the pipeline the document a manual import would upload, and report the
  fingerprint a manual import of that document produces (GraphQL SDL, gRPC descriptor set);
* an unchanged source creates no version and never reaches the pipeline;
* a changed source goes through the import pipeline onto the existing item with a minted
  date/time label, refresh provenance (trigger sweep vs manual), and the change report a
  connector sync writes against the version it supersedes;
* an item that is gone, or a Project, fails the check without writing.

The pipeline itself is replaced with a recorder in the apply tests: what a version stores is the
pipeline's business, pinned by its own tests. Here the point is that the refresh hands it the same
adapter and the same bytes a manual re-import does.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import graphql
import pytest
from google.protobuf import descriptor_pb2

from app import catalog_refresh, catalog_refresh_apply
from app.catalog_refresh import (
    TRIGGER_MANUAL,
    TRIGGER_SWEEP,
    ApplyOutcome,
    RefreshSettingsError,
    pipeline_discovery_result,
)
from app.catalog_refresh_apply import (
    AUDIT_CHANGE_REPORT,
    CODE_ITEM_UNAVAILABLE,
    apply_refresh_to_catalog,
    previous_version,
    refresh_provenance,
)
from app.graphql_import_source import GraphQlImportSource
from app.grpc_import_source import GrpcImportSource
from app.import_source_pipeline import build_job_error, run_adapter_import_job
from app.models import SpecImportJobResult, SpecImportJobStatus

_TENANT = "11111111-1111-4111-8111-111111111111"
_ITEM = "22222222-2222-4222-8222-222222222222"
_NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)

_SDL_V1 = '''"""An order."""
type Order {
  id: ID!
  "The total."
  total: Float
}

type Query {
  order(id: ID!): Order
}
'''

#: v1 with a field removed and a query added: a breaking change and a safe one.
_SDL_V2 = '''"""An order."""
type Order {
  id: ID!
}

type Query {
  order(id: ID!): Order
  orders: [Order!]!
}
'''


def _descriptor_set(method: str = "GetItem") -> bytes:
    """A one-service proto3 descriptor set, as gRPC reflection assembles it."""
    fd = descriptor_pb2.FieldDescriptorProto
    fds = descriptor_pb2.FileDescriptorSet()
    f = fds.file.add(name="inventory.proto", package="inv.v1", syntax="proto3")
    item = f.message_type.add(name="Item")
    item.field.add(name="sku", number=1, type=fd.TYPE_STRING, label=fd.LABEL_OPTIONAL)
    svc = f.service.add(name="InventoryService")
    svc.method.add(name=method, input_type=".inv.v1.Item", output_type=".inv.v1.Item")
    return fds.SerializeToString()


def _discover_graphql(sdl: str, monkeypatch) -> catalog_refresh.DiscoveryResult:
    """Run the real GraphQL runner against a fake introspection that serves ``sdl``."""
    monkeypatch.setattr(GraphQlImportSource, "introspect", lambda self, endpoint, **kw: graphql.build_schema(sdl))
    return catalog_refresh._graphql_runner("https://api.example.com/graphql", {}, "none", None, 5.0)


def _manual_import(adapter_key: str, document: bytes, filename: str) -> catalog_refresh.DiscoveryResult:
    """What a manual import of the document produces (the pipeline, dry run)."""
    return pipeline_discovery_result(adapter_key, document, filename)


# --- runners: discover → document → the pipeline's fingerprint ---------------------------


def test_graphql_runner_fingerprints_like_a_manual_sdl_import(monkeypatch):
    result = _discover_graphql(_SDL_V1, monkeypatch)
    assert result.filename == "schema.graphql"
    assert b"type Order" in result.document
    assert result.fingerprint == _manual_import("graphql", _SDL_V1.encode(), "orders.graphql").fingerprint
    assert result.model is not None and isinstance(result.native, graphql.GraphQLSchema)


def test_graphql_runner_sees_a_change(monkeypatch):
    assert _discover_graphql(_SDL_V1, monkeypatch).fingerprint != _discover_graphql(_SDL_V2, monkeypatch).fingerprint


def test_grpc_runner_imports_the_descriptor_set_like_a_manual_upload(monkeypatch):
    from app.proto_descriptor import read_file_descriptor_set

    seen: Dict[str, Any] = {}

    def _discover(self, target, **kwargs):
        seen.update(target=target, **kwargs)
        return read_file_descriptor_set(_descriptor_set())

    monkeypatch.setattr(GrpcImportSource, "discover", _discover)
    result = catalog_refresh._grpc_runner("h.example.com:443", {"secure": True}, "none", None, 12.0)
    assert (result.filename, result.document) == ("reflection.binpb", _descriptor_set())
    assert result.fingerprint == _manual_import("grpc", _descriptor_set(), "inventory.binpb").fingerprint
    assert (seen["secure"], seen["timeout"]) == (True, 12.0)


def test_a_document_the_pipeline_refuses_fails_the_discovery():
    from app.import_source import ImportSourceError

    with pytest.raises(ImportSourceError, match="could not be imported"):
        pipeline_discovery_result("graphql", b"type {", "schema.graphql")


# --- apply hook -----------------------------------------------------------------------------


class _FakeDb:
    """Answers the hook's two reads: the item and its revisions (newest first)."""

    def __init__(self, item: Optional[Dict[str, Any]], revisions: List[Dict[str, Any]]) -> None:
        self.item = item
        self.revisions = revisions

    def execute_query(self, sql: str, params: Any = None) -> List[Dict[str, Any]]:
        if "FROM apiome.versions v" in sql:
            return list(self.revisions)
        if "FROM apiome.projects p" in sql:
            return [self.item] if self.item else []
        raise AssertionError(f"unexpected query: {sql}")


def _item(**overrides: Any) -> Dict[str, Any]:
    item = {"id": _ITEM, "name": "Orders", "slug": "orders", "publishable": False, "deleted_at": None}
    item.update(overrides)
    return item


def _revision(sdl: Optional[str], *, version_id: str = "1.0.0", rid: str = "rev-1") -> Dict[str, Any]:
    meta = {"sourceLabel": "orders.graphql", "inputKind": "file"}
    if sdl is not None:
        meta["sourceContent"] = sdl
    return {
        "id": rid,
        "version_id": version_id,
        "source_format": "graphql",
        "protocol": "graph",
        "format_metadata": meta,
        "metadata": {},
    }


def _row(**overrides: Any) -> Dict[str, Any]:
    row = {
        "project_id": _ITEM,
        "tenant_id": _TENANT,
        "adapter_key": "graphql",
        "endpoint": "https://api.example.com/graphql",
        "created_by": "u-creator",
        "updated_by": "u-editor",
    }
    row.update(overrides)
    return row


_REAL_PIPELINE = run_adapter_import_job


class _Pipeline:
    """Records the payloads the hook hands the import pipeline and answers like a completed import.

    The runners' dry runs (nothing written) still go to the real pipeline.
    """

    def __init__(self, state: str = "completed") -> None:
        self.calls: List[Dict[str, Any]] = []
        self.state = state

    async def __call__(self, adapter, payload, **kwargs) -> SpecImportJobStatus:
        if payload["metadata"].get("options", {}).get("dry_run"):
            return await _REAL_PIPELINE(adapter, payload, **kwargs)
        self.calls.append({"adapter": adapter.key, "payload": payload})
        if self.state != "completed":
            return SpecImportJobStatus(
                job_id="j",
                state="failed",
                percent=10,
                error=build_job_error("INPUT_MALFORMED", "bad schema"),
            )
        return SpecImportJobStatus(
            job_id="j",
            state="completed",
            percent=100,
            result=SpecImportJobResult(
                project_id=_ITEM,
                project_slug="orders",
                version_id=payload["metadata"]["version"]["version_id"],
                version_record_id="rev-new",
            ),
        )


@pytest.fixture
def pipeline(monkeypatch) -> _Pipeline:
    recorder = _Pipeline()
    monkeypatch.setattr("app.import_source_pipeline.run_adapter_import_job", recorder)
    return recorder


@pytest.fixture
def reports(monkeypatch) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []
    monkeypatch.setattr(
        "app.catalog_revision_change_report.generate_catalog_revision_change_report",
        lambda **kw: calls.append(kw) or {"id": "report"},
    )
    return calls


def _apply(db: _FakeDb, result, **kw) -> ApplyOutcome:
    kw.setdefault("now", _NOW)
    return apply_refresh_to_catalog(db, _row(**kw.pop("row", {})), result, False, **kw)


def test_the_hook_is_registered():
    assert catalog_refresh._APPLY_HOOK is apply_refresh_to_catalog


def test_an_unchanged_source_creates_no_version(monkeypatch, pipeline, reports):
    db = _FakeDb(_item(), [_revision(_SDL_V1)])
    outcome = _apply(db, _discover_graphql(_SDL_V1, monkeypatch), trigger=TRIGGER_SWEEP)
    assert outcome == ApplyOutcome(changed=False)
    assert pipeline.calls == [] and reports == []


def test_a_changed_source_is_imported_like_a_manual_re_import(monkeypatch, pipeline, reports):
    db = _FakeDb(_item(), [_revision(_SDL_V1)])
    result = _discover_graphql(_SDL_V2, monkeypatch)

    outcome = _apply(db, result, trigger=TRIGGER_SWEEP)

    assert outcome == ApplyOutcome(changed=True, version_id="rev-new", version_label="2026-10-27T12:00Z")
    [call] = pipeline.calls
    payload = call["payload"]
    assert call["adapter"] == "graphql"
    assert base64.standard_b64decode(payload["document_base64"]) == result.document
    assert payload["filename"] == "schema.graphql"
    assert payload["metadata"]["existing_project_id"] == _ITEM
    assert payload["metadata"]["version"] == {"version_id": "2026-10-27T12:00Z"}
    assert payload["metadata"]["options"] == {}  # not a dry run: the pipeline persists and lints
    assert payload["refresh_source"] == {
        "inputKind": "discovery",
        "sourceLabel": "https://api.example.com/graphql",
        "refreshAdapter": "graphql",
        "refreshTrigger": "sweep",
    }
    assert payload["user_id"] == "u-editor"  # a sweep acts as whoever last saved the setting
    assert reports == [
        {
            "tenant_id": _TENANT,
            "project_id": _ITEM,
            "revision_version_id": "rev-new",
            "parent_version_id": "rev-1",
            "actor_id": "u-editor",
            "action": AUDIT_CHANGE_REPORT,
        }
    ]


def test_the_imported_document_fingerprints_like_a_manual_upload_of_the_same_api(monkeypatch, pipeline, reports):
    """The bytes the refresh imports read back to the model a manual import of the source produces."""
    db = _FakeDb(_item(), [_revision(_SDL_V1)])
    _apply(db, _discover_graphql(_SDL_V2, monkeypatch))
    imported = base64.standard_b64decode(pipeline.calls[0]["payload"]["document_base64"])
    assert (
        _manual_import("graphql", imported, "schema.graphql").fingerprint
        == _manual_import("graphql", _SDL_V2.encode(), "orders.graphql").fingerprint
    )


def test_a_manual_check_records_the_caller(monkeypatch, pipeline, reports):
    db = _FakeDb(_item(), [_revision(_SDL_V1)])
    _apply(db, _discover_graphql(_SDL_V2, monkeypatch), trigger=TRIGGER_MANUAL, actor_id="u-caller")
    payload = pipeline.calls[0]["payload"]
    assert payload["refresh_source"]["refreshTrigger"] == "manual"
    assert payload["user_id"] == "u-caller"
    assert reports[0]["actor_id"] == "u-caller"


def test_the_label_never_collides_with_an_existing_version(monkeypatch, pipeline, reports):
    db = _FakeDb(
        _item(),
        [_revision(_SDL_V1, version_id="2026-10-27T12:00Z", rid="rev-2"), _revision(_SDL_V1, rid="rev-1")],
    )
    outcome = _apply(db, _discover_graphql(_SDL_V2, monkeypatch))
    assert outcome.version_label == "2026-10-27T12:00Z-2"
    assert reports[0]["parent_version_id"] == "rev-2"  # diffed against the current (newest) version


def test_an_item_without_versions_gets_one_and_no_change_report(monkeypatch, pipeline, reports):
    db = _FakeDb(_item(), [])
    outcome = _apply(db, _discover_graphql(_SDL_V1, monkeypatch))
    assert outcome.changed and outcome.version_id == "rev-new"
    assert reports == []


def test_a_current_version_without_a_source_is_superseded(monkeypatch, pipeline, reports):
    db = _FakeDb(_item(), [_revision(None)])
    outcome = _apply(db, _discover_graphql(_SDL_V1, monkeypatch))
    assert outcome.changed
    assert reports[0]["parent_version_id"] == "rev-1"


def test_previous_version_carries_the_semantic_fingerprint_and_model(monkeypatch):
    from app.fingerprint import fingerprint

    prev = previous_version(_ITEM, _revision(_SDL_V1))
    assert prev.version_tag == "1.0.0"
    assert prev.fingerprint == fingerprint(_discover_graphql(_SDL_V1, monkeypatch).model).fingerprint
    assert previous_version(_ITEM, _revision(None)) is None


@pytest.mark.parametrize(
    "item",
    [None, _item(deleted_at=datetime(2026, 10, 1, tzinfo=timezone.utc)), _item(publishable=True)],
    ids=["missing", "deleted", "project"],
)
def test_an_unavailable_item_fails_without_writing(monkeypatch, pipeline, reports, item):
    db = _FakeDb(item, [_revision(_SDL_V1)])
    with pytest.raises(RefreshSettingsError) as err:
        _apply(db, _discover_graphql(_SDL_V2, monkeypatch))
    assert err.value.code == CODE_ITEM_UNAVAILABLE
    assert pipeline.calls == [] and reports == []


def test_a_pipeline_failure_fails_the_check(monkeypatch, reports):
    monkeypatch.setattr("app.import_source_pipeline.run_adapter_import_job", _Pipeline(state="failed"))
    db = _FakeDb(_item(), [_revision(_SDL_V1)])
    with pytest.raises(RuntimeError, match="bad schema"):
        _apply(db, _discover_graphql(_SDL_V2, monkeypatch))
    assert reports == []


def test_a_discovery_without_a_document_is_refused(pipeline):
    result = catalog_refresh.DiscoveryResult(fingerprint="fp", model=None, native=None)
    with pytest.raises(ValueError, match="no document"):
        _apply(_FakeDb(_item(), []), result)
    assert pipeline.calls == []


def test_refresh_provenance_never_carries_the_credential():
    row = _row(encrypted_payload=b"sealed", auth_type="bearer")
    assert set(refresh_provenance(row, TRIGGER_SWEEP)) == {
        "inputKind",
        "sourceLabel",
        "refreshAdapter",
        "refreshTrigger",
    }


def test_the_check_records_changed_and_the_version_through_the_real_hook(monkeypatch, pipeline, reports):
    """End to end over the check runner: discovery → hook → status ``changed`` with the version."""
    import asyncio

    from catalog_refresh_fakes import FakeRefreshStore

    store = FakeRefreshStore().install(monkeypatch)
    store.add(_ITEM, _TENANT, created_by="u-creator", updated_by=None)
    monkeypatch.setattr(GraphQlImportSource, "introspect", lambda self, endpoint, **kw: graphql.build_schema(_SDL_V2))
    db = _FakeDb(_item(), [_revision(_SDL_V1)])
    monkeypatch.setattr(catalog_refresh_apply, "_catalog_item", lambda d, p, t: _item())
    outcome = asyncio.run(
        catalog_refresh.run_refresh_check(
            db,
            store.get_refresh_for_check(None, _ITEM),
            timeout_seconds=30,
            backoff_base_seconds=300,
            backoff_max_seconds=86400,
            trigger=TRIGGER_SWEEP,
        )
    )
    assert (outcome.status, outcome.version_id) == ("changed", "rev-new")
    assert store.rows[_ITEM]["status"] == "changed"
    assert pipeline.calls[0]["payload"]["user_id"] == "u-creator"
