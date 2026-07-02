"""Unit tests for the canonical→catalog persistence hook (MFI-23.7).

:func:`app.import_source_pipeline.persist_adapter_import` is the write that stores a non-OpenAPI
import as a **catalog item**, keeping the *original source verbatim* so it can be converted to
OpenAPI later rather than at import time. These tests drive it against a fake DB and assert the
routed row is non-publishable and the raw bytes land in ``format_metadata.sourceContent``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi
from app.import_routing import ImportRoutingDecision, ImportTarget
from app.import_source_pipeline import persist_adapter_import


class _FakeDb:
    """Records the create/update calls the hook makes, returning plausible rows."""

    def __init__(self) -> None:
        self.created_project: Optional[Dict[str, Any]] = None
        self.created_version: Optional[Dict[str, Any]] = None
        self.source_format_call: Optional[Dict[str, Any]] = None

    def create_project(self, tenant_id, creator_id, name, slug, description, metadata, publishable):
        self.created_project = {
            "tenant_id": tenant_id,
            "creator_id": creator_id,
            "name": name,
            "slug": slug,
            "description": description,
            "publishable": publishable,
        }
        return {"id": "proj-1", "slug": slug}

    def create_version(self, project_id, creator_id, version_id, description=None):
        self.created_version = {
            "project_id": project_id,
            "creator_id": creator_id,
            "version_id": version_id,
        }
        return {"id": "ver-1"}

    def set_version_source_format(
        self, version_record_id, tenant_id, source_format=None, protocol=None,
        format_metadata=None, source_tool_versions=None,
    ):
        self.source_format_call = {
            "version_record_id": version_record_id,
            "tenant_id": tenant_id,
            "source_format": source_format,
            "protocol": protocol,
            "format_metadata": format_metadata,
        }
        return True


def _model() -> CanonicalApi:
    return CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="protobuf",
        identity=ApiIdentity(name="Orders"),
    )


def _catalog_routing() -> ImportRoutingDecision:
    return ImportRoutingDecision(
        target=ImportTarget.CATALOG,
        publishable=False,
        schemas_only=False,
        reason="non-OpenAPI format → catalog item",
        source="protobuf",
        paradigm="rpc",
        format="protobuf",
        operation_count=1,
        type_count=2,
        channel_count=0,
    )


def _payload() -> Dict[str, Any]:
    return {
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "filename": "orders.proto",
        "metadata": {
            "source_kind": "protobuf",
            "project": {"name": "Orders", "slug": "orders"},
            "version": {"version_id": "1.0.0"},
            "options": {"input_kind": "file"},
        },
    }


def test_persists_a_non_publishable_catalog_item_with_raw_source(monkeypatch) -> None:
    fake = _FakeDb()
    monkeypatch.setattr("app.database.db", fake)

    result = persist_adapter_import(_payload(), _model(), "syntax = \"proto3\";", _catalog_routing())

    assert result is not None
    assert (result.project_id, result.version_record_id) == ("proj-1", "ver-1")
    # Routed to the catalog: the project is created non-publishable.
    assert fake.created_project["publishable"] is False
    assert fake.created_project["name"] == "Orders"
    # The original source is stored verbatim, with the detected format/protocol off the model.
    call = fake.source_format_call
    assert call["source_format"] == "protobuf"
    assert call["protocol"] == "rpc"
    assert call["format_metadata"]["sourceContent"] == 'syntax = "proto3";'
    assert call["format_metadata"]["sourceLabel"] == "orders.proto"
    assert call["format_metadata"]["inputKind"] == "file"


def test_records_url_intake_kind_and_source_uri(monkeypatch) -> None:
    """A URL import records inputKind='url' and the URL as the source URI (MFI-26.2)."""
    fake = _FakeDb()
    monkeypatch.setattr("app.database.db", fake)
    payload = _payload()
    payload["filename"] = "https://api.example.com/orders.proto"
    payload["metadata"]["options"] = {"input_kind": "url"}

    result = persist_adapter_import(payload, _model(), "syntax = \"proto3\";", _catalog_routing())

    assert result is not None
    fmd = fake.source_format_call["format_metadata"]
    # The intake method drives the catalog source-material badge, and the URL is recorded as the
    # retrievable source URI so the detail panel can link/redirect back to it.
    assert fmd["inputKind"] == "url"
    assert fmd["sourceUri"] == "https://api.example.com/orders.proto"


def test_records_paste_intake_kind_without_source_uri(monkeypatch) -> None:
    """A paste import records inputKind='paste' and does not synthesize a source URI (MFI-26.2)."""
    fake = _FakeDb()
    monkeypatch.setattr("app.database.db", fake)
    payload = _payload()
    payload["filename"] = "Pasted source"
    payload["metadata"]["options"] = {"input_kind": "paste"}

    result = persist_adapter_import(payload, _model(), "syntax = \"proto3\";", _catalog_routing())

    assert result is not None
    fmd = fake.source_format_call["format_metadata"]
    assert fmd["inputKind"] == "paste"
    assert "sourceUri" not in fmd


def test_defaults_input_kind_to_file_when_omitted(monkeypatch) -> None:
    """With no options.input_kind, the recorded intake kind defaults to 'file' (back-compat)."""
    fake = _FakeDb()
    monkeypatch.setattr("app.database.db", fake)
    payload = _payload()
    payload["metadata"]["options"] = {}

    persist_adapter_import(payload, _model(), "x", _catalog_routing())

    assert fake.source_format_call["format_metadata"]["inputKind"] == "file"


def test_returns_none_without_a_tenant(monkeypatch) -> None:
    fake = _FakeDb()
    monkeypatch.setattr("app.database.db", fake)
    payload = _payload()
    payload["tenant_id"] = ""

    result = persist_adapter_import(payload, _model(), "x", _catalog_routing())

    assert result is None
    assert fake.created_project is None


def test_reuses_an_existing_project_when_targeted(monkeypatch) -> None:
    fake = _FakeDb()
    # get_project_by_id is only consulted for the existing-project branch.
    fake.get_project_by_id = lambda pid, tid: {"id": pid, "slug": "orders"}  # type: ignore[attr-defined]
    monkeypatch.setattr("app.database.db", fake)
    payload = _payload()
    payload["metadata"]["existing_project_id"] = "proj-existing"

    result = persist_adapter_import(payload, _model(), "x", _catalog_routing())

    assert result is not None
    assert result.project_id == "proj-existing"
    # No new project is created when attaching to an existing one.
    assert fake.created_project is None
    assert fake.created_version["project_id"] == "proj-existing"
