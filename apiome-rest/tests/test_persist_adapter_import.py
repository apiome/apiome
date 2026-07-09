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
from app.import_source_pipeline import _ResolvedIntake, persist_adapter_import


def _text_intake(text: str) -> _ResolvedIntake:
    data = text.encode("utf-8")
    return _ResolvedIntake(raw_bytes=data, text=text, fileset=None, archive_root=None)


class _FakeDb:
    """Records the create/update calls the hook makes, returning plausible rows."""

    def __init__(self) -> None:
        self.created_project: Optional[Dict[str, Any]] = None
        self.created_version: Optional[Dict[str, Any]] = None
        self.source_format_call: Optional[Dict[str, Any]] = None

    def get_project_by_slug(self, slug: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        return None

    def allocate_project_slug(self, tenant_id: str, base_slug: str) -> str:
        return (base_slug or "imported-source").strip().lower() or "imported-source"

    def get_version_by_version_id(self, project_id: str, version_id_str: str, tenant_id: str):
        return None

    def allocate_version_id(self, project_id: str, base_version_id: str) -> str:
        return (base_version_id or "1.0.0").strip() or "1.0.0"

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

    result = persist_adapter_import(_payload(), _model(), _text_intake('syntax = "proto3";'), _catalog_routing())

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

    result = persist_adapter_import(payload, _model(), _text_intake('syntax = "proto3";'), _catalog_routing())

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

    result = persist_adapter_import(payload, _model(), _text_intake('syntax = "proto3";'), _catalog_routing())

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

    persist_adapter_import(payload, _model(), _text_intake("x"), _catalog_routing())

    assert fake.source_format_call["format_metadata"]["inputKind"] == "file"


def test_returns_none_without_a_tenant(monkeypatch) -> None:
    fake = _FakeDb()
    monkeypatch.setattr("app.database.db", fake)
    payload = _payload()
    payload["tenant_id"] = ""

    result = persist_adapter_import(payload, _model(), _text_intake("x"), _catalog_routing())

    assert result is None
    assert fake.created_project is None


def test_reuses_an_existing_project_when_targeted(monkeypatch) -> None:
    fake = _FakeDb()
    # get_project_by_id is only consulted for the existing-project branch.
    fake.get_project_by_id = lambda pid, tid: {"id": pid, "slug": "orders"}  # type: ignore[attr-defined]
    monkeypatch.setattr("app.database.db", fake)
    payload = _payload()
    payload["metadata"]["existing_project_id"] = "proj-existing"

    result = persist_adapter_import(payload, _model(), _text_intake("x"), _catalog_routing())

    assert result is not None
    assert result.project_id == "proj-existing"
    # No new project is created when attaching to an existing one.
    assert fake.created_project is None
    assert fake.created_version["project_id"] == "proj-existing"


def test_reuses_existing_catalog_item_when_slug_collides(monkeypatch) -> None:
    """A catalog import retry reuses the live catalog item instead of violating slug uniqueness."""
    fake = _FakeDb()
    fake.get_project_by_slug = lambda slug, tenant_id: (
        {"id": "cat-existing", "slug": "orders", "publishable": False}
        if slug == "orders"
        else None
    )
    monkeypatch.setattr("app.database.db", fake)

    result = persist_adapter_import(_payload(), _model(), _text_intake('syntax = "proto3";'), _catalog_routing())

    assert result is not None
    assert result.project_id == "cat-existing"
    assert fake.created_project is None
    assert fake.created_version["project_id"] == "cat-existing"


def test_reuses_existing_catalog_version_when_version_collides(monkeypatch) -> None:
    """A catalog import retry reuses the live revision instead of violating version uniqueness."""
    fake = _FakeDb()
    fake.get_project_by_slug = lambda slug, tenant_id: (
        {"id": "cat-existing", "slug": "orders", "publishable": False}
        if slug == "orders"
        else None
    )
    fake.get_version_by_version_id = lambda project_id, version_id_str, tenant_id: (
        {"id": "ver-existing", "version_id": "1.0.0"}
        if project_id == "cat-existing" and version_id_str == "1.0.0"
        else None
    )
    monkeypatch.setattr("app.database.db", fake)

    result = persist_adapter_import(_payload(), _model(), _text_intake('syntax = "proto3";'), _catalog_routing())

    assert result is not None
    assert result.project_id == "cat-existing"
    assert result.version_record_id == "ver-existing"
    assert result.version_id == "1.0.0"
    assert fake.created_project is None
    assert fake.created_version is None
    assert fake.source_format_call["version_record_id"] == "ver-existing"


def test_allocates_a_unique_slug_when_publishable_slug_is_taken(monkeypatch) -> None:
    fake = _FakeDb()
    fake.allocate_project_slug = lambda tenant_id, base: f"{base}-2"
    fake.allocate_version_id = lambda project_id, base: f"{base}-2"
    monkeypatch.setattr("app.database.db", fake)
    routing = ImportRoutingDecision(
        target=ImportTarget.PROJECT,
        publishable=True,
        schemas_only=False,
        reason="openapi",
        source="openapi",
        paradigm="rest",
        format="openapi-3.1",
        operation_count=1,
        type_count=0,
        channel_count=0,
    )

    result = persist_adapter_import(_payload(), _model(), _text_intake("openapi: 3.1.0"), routing)

    assert result is not None
    assert fake.created_project is not None
    assert fake.created_project["slug"] == "orders-2"
    assert fake.created_version is not None
    assert fake.created_version["version_id"] == "1.0.0-2"
