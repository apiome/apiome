"""Reconcile one-shot file uploads — RAR-6.2 (#3539).

Pins the two acceptance criteria without a network or a database:

* **uploaded specs surface a staleness hint after a configurable age** — an item whose newest
  version came from a file upload is ``stale`` once it is the tenant's ``staleAfterDays`` old (90 by
  default, 1–3650); a URL, paste, live refresh, connector or git import never is;
* **re-upload reuses the stored spec for faithful replay** — every upload records the importer and
  options it ran with on ``format_metadata.importSpec`` (minus the run-only flags), and a re-upload
  hands the import pipeline exactly those options, onto the same item, under a date/time label,
  with a change report; an identical file writes nothing; an upload from before capture falls back
  to the recorded source format with default options and says so.

Also the HTTP contract: the permission each route needs, 404 before 403, the refusal codes, and the
import quality gate a re-upload passes like any upload.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_persist_adapter_import import _catalog_routing, _model, _payload, _text_intake
from test_persist_adapter_import import _FakeDb as _PersistDb

from app import catalog_upload_reconcile as reconcile
from app.auth import validate_authentication
from app.catalog_refresh import RefreshSettingsError
from app.catalog_upload_reconcile import (
    AUDIT_CHANGE_REPORT,
    AUDIT_POLICY,
    AUDIT_REUPLOADED,
    CODE_NOT_AN_UPLOAD,
    CODE_REUPLOAD_FAILED,
    CODE_UNKNOWN_FORMAT,
    STALE_AFTER_DAYS_DEFAULT,
    ReuploadError,
    ReuploadOutcome,
    get_tenant_stale_after_days,
    is_upload_revision,
    reupload_catalog_item,
    set_tenant_stale_after_days,
    stored_upload_spec,
    upload_spec_metadata,
    upload_staleness,
)
from app.database import db
from app.import_source_pipeline import build_job_error, persist_adapter_import
from app.main import app
from app.models import SpecImportJobResult, SpecImportJobStatus
from app.permissions import Action, Resource

_TENANT = "11111111-1111-4111-8111-111111111111"
_ITEM = "22222222-2222-4222-8222-222222222222"
_ACTOR = "33333333-3333-4333-8333-333333333333"
_MISSING = "77777777-7777-4777-8777-777777777777"
_NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)

_SDL_V1 = """type Order {
  id: ID!
  total: Float
}

type Query {
  order(id: ID!): Order
}
"""

_SDL_V2 = """type Order {
  id: ID!
}

type Query {
  order(id: ID!): Order
  orders: [Order!]!
}
"""

#: What the user chose when they first uploaded the file, as the pipeline records it.
_SPEC = {
    "specSchemaVersion": 1,
    "sourceKind": "graphql",
    "options": {"apply_naming_convention": True, "class_naming_convention": "camelCase", "selected_schemas": ["Order"]},
}


def _revision(
    sdl: Optional[str] = _SDL_V1,
    *,
    input_kind: str = "file",
    spec: Optional[Dict[str, Any]] = _SPEC,
    created_at: Any = None,
    **extra: Any,
) -> Dict[str, Any]:
    meta: Dict[str, Any] = {"sourceLabel": "orders.graphql", "inputKind": input_kind, **extra}
    if sdl is not None:
        meta["sourceContent"] = sdl
    if spec is not None:
        meta["importSpec"] = spec
    return {
        "id": "rev-1",
        "version_id": "1.0.0",
        "created_at": created_at or _NOW - timedelta(days=10),
        "source_format": "graphql",
        "protocol": "graph",
        "format_metadata": meta,
        "metadata": {},
    }


# ===========================================================================
# The stored spec
# ===========================================================================


def test_the_spec_keeps_the_users_choices_and_drops_the_run_only_flags() -> None:
    options = {
        "class_naming_convention": "camelCase",
        "har_hosts": ["api.example.com"],
        "archive_root": "root.proto",
        "dry_run": False,
        "skip_duplicate_versions": True,
        "input_kind": "file",
        "git_source": {"repo_url": "https://example.com/r"},
    }
    assert upload_spec_metadata("graphql", options) == {
        "specSchemaVersion": 1,
        "sourceKind": "graphql",
        "options": {
            "class_naming_convention": "camelCase",
            "har_hosts": ["api.example.com"],
            "archive_root": "root.proto",
        },
    }


@pytest.mark.parametrize("kind", ["", None, "repository_auto_import"])
def test_no_spec_without_a_replayable_importer(kind) -> None:
    assert upload_spec_metadata(kind, {}) is None


def test_a_stored_spec_reads_back_and_a_malformed_one_is_none() -> None:
    assert stored_upload_spec({"importSpec": _SPEC}) == _SPEC
    assert stored_upload_spec({"importSpec": {"sourceKind": "graphql"}})["options"] == {}
    for bad in (None, {}, {"importSpec": "x"}, {"importSpec": {"options": {}}}):
        assert stored_upload_spec(bad) is None


@pytest.mark.parametrize(
    ("fmd", "upload"),
    [
        ({"inputKind": "file"}, True),
        ({"inputKind": "fileset", "intakeKind": "archive"}, True),
        ({"inputKind": "fileset", "intakeKind": "git"}, False),
        ({"inputKind": "url"}, False),
        ({"inputKind": "paste"}, False),
        ({"inputKind": "discovery"}, False),
        ({"inputKind": "connector"}, False),
        ({"inputKind": "backstage"}, False),
        ({}, False),
        (None, False),
    ],
)
def test_only_a_file_upload_is_an_upload(fmd, upload) -> None:
    assert is_upload_revision(fmd) is upload


def test_the_pipeline_records_the_spec_on_an_upload(monkeypatch) -> None:
    fake = _PersistDb()
    monkeypatch.setattr("app.database.db", fake)
    payload = _payload()
    payload["metadata"]["options"] = {"input_kind": "file", "class_naming_convention": "snake_case", "dry_run": False}

    persist_adapter_import(payload, _model(), _text_intake('syntax = "proto3";'), _catalog_routing())

    assert fake.source_format_call["format_metadata"]["importSpec"] == {
        "specSchemaVersion": 1,
        "sourceKind": "protobuf",
        "options": {"class_naming_convention": "snake_case"},
    }


@pytest.mark.parametrize("input_kind", ["url", "paste"])
def test_the_pipeline_records_no_spec_for_other_intakes(monkeypatch, input_kind) -> None:
    fake = _PersistDb()
    monkeypatch.setattr("app.database.db", fake)
    payload = _payload()
    payload["metadata"]["options"] = {"input_kind": input_kind}

    persist_adapter_import(payload, _model(), _text_intake('syntax = "proto3";'), _catalog_routing())

    assert "importSpec" not in fake.source_format_call["format_metadata"]


def test_the_pipeline_records_no_spec_for_a_live_refresh(monkeypatch) -> None:
    fake = _PersistDb()
    monkeypatch.setattr("app.database.db", fake)
    payload = _payload()
    payload["refresh_source"] = {"inputKind": "discovery", "refreshTrigger": "sweep"}

    persist_adapter_import(payload, _model(), _text_intake('syntax = "proto3";'), _catalog_routing())

    assert "importSpec" not in fake.source_format_call["format_metadata"]


# ===========================================================================
# The staleness hint
# ===========================================================================


def test_a_young_upload_is_eligible_but_not_stale() -> None:
    hint = upload_staleness(_revision(), stale_after_days=90, now=_NOW)
    assert (hint.eligible, hint.stale, hint.age_days, hint.stale_after_days) == (True, False, 10, 90)
    assert (hint.version_id, hint.version_label, hint.source_label) == ("rev-1", "1.0.0", "orders.graphql")
    assert hint.spec == _SPEC


@pytest.mark.parametrize(("age", "stale"), [(89, False), (90, True), (400, True)])
def test_an_upload_is_stale_from_the_threshold_on(age, stale) -> None:
    hint = upload_staleness(_revision(created_at=_NOW - timedelta(days=age)), stale_after_days=90, now=_NOW)
    assert hint.stale is stale


def test_the_threshold_is_configurable() -> None:
    revision = _revision(created_at=_NOW - timedelta(days=10))
    assert upload_staleness(revision, stale_after_days=7, now=_NOW).stale
    assert not upload_staleness(revision, stale_after_days=30, now=_NOW).stale


def test_naive_and_string_timestamps_are_read_as_utc() -> None:
    naive = (_NOW - timedelta(days=100)).replace(tzinfo=None)
    assert upload_staleness(_revision(created_at=naive), stale_after_days=90, now=_NOW).age_days == 100
    iso = (_NOW - timedelta(days=5)).isoformat().replace("+00:00", "Z")
    assert upload_staleness(_revision(created_at=iso), stale_after_days=90, now=_NOW).age_days == 5


def test_an_item_that_is_not_an_upload_is_never_stale() -> None:
    old = _NOW - timedelta(days=1000)
    revisions = (None, _revision(input_kind="url", created_at=old), _revision(input_kind="discovery", created_at=old))
    for revision in revisions:
        hint = upload_staleness(revision, stale_after_days=90, now=_NOW)
        assert (hint.eligible, hint.stale) == (False, False)


class _TenantDb:
    """The tenant setting's one column."""

    def __init__(self, value: Optional[int] = None) -> None:
        self.value = value
        self.writes: List[tuple] = []

    def execute_query(self, sql: str, params: Any = None) -> List[Dict[str, Any]]:
        assert "catalog_upload_stale_after_days" in sql
        return [{"catalog_upload_stale_after_days": self.value}] if self.value is not None else []

    def _execute_write(self, sql: str, params: Any = None) -> None:
        self.writes.append(params)
        self.value = params[0]


def test_the_tenant_setting_defaults_to_90_and_round_trips() -> None:
    tenant = _TenantDb()
    assert get_tenant_stale_after_days(tenant, _TENANT) == STALE_AFTER_DAYS_DEFAULT == 90
    assert set_tenant_stale_after_days(tenant, _TENANT, 30) == 30
    assert get_tenant_stale_after_days(tenant, _TENANT) == 30


@pytest.mark.parametrize("days", [0, -1, 3651])
def test_the_tenant_setting_refuses_out_of_range(days) -> None:
    tenant = _TenantDb()
    with pytest.raises(ValueError):
        set_tenant_stale_after_days(tenant, _TENANT, days)
    assert tenant.writes == []


# ===========================================================================
# The re-upload
# ===========================================================================


class _ItemDb:
    """Answers the re-upload's reads: the item and its revisions (newest first)."""

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


class _Pipeline:
    """Records the payloads handed to the import pipeline and answers like a completed import."""

    def __init__(self, state: str = "completed") -> None:
        self.calls: List[Dict[str, Any]] = []
        self.state = state

    async def __call__(self, adapter, payload, **kwargs) -> SpecImportJobStatus:
        self.calls.append({"adapter": adapter.key, "payload": payload})
        if self.state != "completed":
            return SpecImportJobStatus(
                job_id="j", state="failed", percent=10, error=build_job_error("INPUT_MALFORMED", "bad schema")
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


def _reupload(db: _ItemDb, document: str = _SDL_V2, **kw: Any) -> ReuploadOutcome:
    kw.setdefault("now", _NOW)
    return reupload_catalog_item(
        db, tenant_id=_TENANT, project_id=_ITEM, raw=document.encode(), filename="orders-v2.graphql",
        actor_id=_ACTOR, **kw
    )


def test_a_changed_file_is_imported_with_the_stored_spec(pipeline, reports) -> None:
    """RAR-6.2 acceptance: the re-upload replays the original options, not importer defaults."""
    outcome = _reupload(_ItemDb(_item(), [_revision()]))

    assert outcome == ReuploadOutcome(changed=True, spec_replayed=True, version_id="rev-new",
                                      version_label="2026-10-30T12:00Z")
    [call] = pipeline.calls
    assert call["adapter"] == "graphql"
    payload = call["payload"]
    assert payload["metadata"]["options"] == {**_SPEC["options"], "input_kind": "file"}
    assert payload["metadata"]["existing_project_id"] == _ITEM
    assert payload["metadata"]["source_kind"] == "graphql"
    assert payload["metadata"]["version"] == {"version_id": "2026-10-30T12:00Z"}
    assert (payload["filename"], payload["user_id"], payload["tenant_id"]) == ("orders-v2.graphql", _ACTOR, _TENANT)
    assert base64.standard_b64decode(payload["document_base64"]).decode() == _SDL_V2
    assert reports == [
        {
            "tenant_id": _TENANT,
            "project_id": _ITEM,
            "revision_version_id": "rev-new",
            "parent_version_id": "rev-1",
            "actor_id": _ACTOR,
            "action": AUDIT_CHANGE_REPORT,
        }
    ]


def test_the_replayed_options_produce_the_same_spec_on_the_new_version(monkeypatch, pipeline, reports) -> None:
    """The next re-upload replays the same spec: the pipeline records what it was handed."""
    _reupload(_ItemDb(_item(), [_revision()]))
    payload = pipeline.calls[0]["payload"]["metadata"]
    assert upload_spec_metadata(payload["source_kind"], payload["options"]) == _SPEC


def test_an_identical_file_writes_nothing(pipeline, reports) -> None:
    outcome = _reupload(_ItemDb(_item(), [_revision()]), _SDL_V1)
    assert outcome == ReuploadOutcome(changed=False, spec_replayed=True)
    assert pipeline.calls == [] and reports == []


def test_a_fileset_upload_stays_a_fileset(pipeline, reports) -> None:
    _reupload(_ItemDb(_item(), [_revision(input_kind="fileset", intakeKind="archive")]))
    assert pipeline.calls[0]["payload"]["metadata"]["options"]["input_kind"] == "fileset"


def test_a_file_the_importer_cannot_read_as_text_goes_to_the_pipeline(pipeline, reports) -> None:
    outcome = reupload_catalog_item(
        _ItemDb(_item(), [_revision()]), tenant_id=_TENANT, project_id=_ITEM, raw=b"\xff\xfe\x00",
        filename="orders.zip", actor_id=_ACTOR, now=_NOW,
    )
    assert outcome.changed and pipeline.calls[0]["payload"]["metadata"]["version"]["version_id"] == "2026-10-30T12:00Z"


def test_an_upload_from_before_capture_runs_with_defaults(pipeline, reports) -> None:
    outcome = _reupload(_ItemDb(_item(), [_revision(spec=None)]))
    assert outcome.changed and outcome.spec_replayed is False
    call = pipeline.calls[0]
    assert call["adapter"] == "graphql"
    assert call["payload"]["metadata"]["options"] == {"input_kind": "file"}


def test_an_unknown_format_before_capture_is_refused(pipeline, reports, monkeypatch) -> None:
    revision = _revision(spec=None)
    revision["source_format"] = "no-such-format"
    monkeypatch.setattr("app.catalog_conversion.detect_import_source", lambda payload: None)
    with pytest.raises(ReuploadError) as caught:
        _reupload(_ItemDb(_item(), [revision]), "not a schema at all")
    assert caught.value.code == CODE_UNKNOWN_FORMAT
    assert pipeline.calls == []


@pytest.mark.parametrize("revisions", [[], [_revision(input_kind="url")], [_revision(input_kind="discovery")]])
def test_only_an_upload_can_be_re_uploaded(pipeline, reports, revisions) -> None:
    with pytest.raises(ReuploadError) as caught:
        _reupload(_ItemDb(_item(), revisions))
    assert caught.value.code == CODE_NOT_AN_UPLOAD
    assert pipeline.calls == []


@pytest.mark.parametrize("item", [None, _item(deleted_at="2026-10-01"), _item(publishable=True)])
def test_an_item_that_is_gone_or_a_project_is_refused(pipeline, reports, item) -> None:
    with pytest.raises(RefreshSettingsError):
        _reupload(_ItemDb(item, [_revision()]))
    assert pipeline.calls == []


def test_a_file_the_pipeline_refuses_fails_without_a_report(monkeypatch, reports) -> None:
    monkeypatch.setattr("app.import_source_pipeline.run_adapter_import_job", _Pipeline(state="failed"))
    with pytest.raises(ReuploadError) as caught:
        _reupload(_ItemDb(_item(), [_revision()]))
    assert caught.value.code == CODE_REUPLOAD_FAILED and "bad schema" in caught.value.message
    assert reports == []


# ===========================================================================
# HTTP contract
# ===========================================================================

client = TestClient(app)
_AUTH = {"tenant_id": _TENANT, "user_id": _ACTOR, "auth_method": "jwt", "user_email": "a@x.io"}
_UPLOAD_URL = f"/v1/catalog/acme/{_ITEM}/upload"
_REUPLOAD_URL = f"/v1/catalog/acme/{_ITEM}/reupload"
_POLICY_URL = "/v1/catalog/acme/upload-policy"
_BODY = {"filename": "orders-v2.graphql", "documentBase64": base64.standard_b64encode(_SDL_V2.encode()).decode()}


class _RouteState:
    """The tenant setting, the item's newest revision, re-upload calls and audit rows."""

    def __init__(self) -> None:
        self.days = 90
        self.revision: Optional[Dict[str, Any]] = _revision(created_at=_NOW - timedelta(days=120))
        self.reuploads: List[Dict[str, Any]] = []
        self.outcome: Any = ReuploadOutcome(changed=True, spec_replayed=True, version_id="rev-new",
                                            version_label="2026-10-30T12:00Z")
        self.audits: List[Dict[str, Any]] = []


@pytest.fixture
def state(monkeypatch) -> _RouteState:
    st = _RouteState()
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    monkeypatch.setattr(
        db,
        "get_catalog_item_by_id",
        lambda item_id, tenant_id, **kw: {"id": item_id} if item_id == _ITEM and tenant_id == _TENANT else None,
    )
    monkeypatch.setattr(db, "insert_workflow_audit",
                        lambda t, p, v, action, outcome, actor, detail=None: st.audits.append(
                            {"action": action, "detail": detail}))
    monkeypatch.setattr(reconcile, "get_tenant_stale_after_days", lambda _db, _t: st.days)

    def _set(_db, _t, days):
        st.days = days
        return days

    monkeypatch.setattr(reconcile, "set_tenant_stale_after_days", _set)
    monkeypatch.setattr(reconcile, "newest_revision", lambda _db, _p, _t: st.revision)

    def _reupload_stub(_db, **kw):
        st.reuploads.append(kw)
        if isinstance(st.outcome, Exception):
            raise st.outcome
        return st.outcome

    monkeypatch.setattr(reconcile, "reupload_catalog_item", _reupload_stub)

    async def _gate(**kw):
        return None

    monkeypatch.setattr("app.spec_import_routes._enforce_quality_gate", _gate)
    yield st
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("method", "url", "body", "grants"),
    [
        ("GET", _UPLOAD_URL, None, [(Resource.PROJECTS, Action.VIEW)]),
        ("POST", _REUPLOAD_URL, _BODY, [(Resource.IMPORTS, Action.CREATE), (Resource.PROJECTS, Action.EDIT)]),
        ("GET", _POLICY_URL, None, [(Resource.PROJECTS, Action.VIEW)]),
        ("PUT", _POLICY_URL, {"staleAfterDays": 30}, [(Resource.IMPORTS, Action.EDIT)]),
    ],
)
def test_each_route_enforces_its_permissions(state, method, url, body, grants) -> None:
    with patch("app.catalog_upload_routes.enforce_permission", return_value=_ACTOR) as guard:
        response = client.request(method, url, json=body)
    assert response.status_code < 400, response.text
    assert [c.args[2:4] for c in guard.call_args_list] == grants


def test_a_denied_re_upload_writes_nothing(state) -> None:
    with patch("app.catalog_upload_routes.enforce_permission", side_effect=HTTPException(status_code=403)):
        assert client.post(_REUPLOAD_URL, json=_BODY).status_code == 403
    assert state.reuploads == []


@pytest.mark.parametrize(("method", "suffix"), [("GET", "upload"), ("POST", "reupload")])
def test_an_unknown_item_is_404_before_the_permission_check(state, method, suffix) -> None:
    with patch("app.catalog_upload_routes.enforce_permission") as guard:
        response = client.request(method, f"/v1/catalog/acme/{_MISSING}/{suffix}", json=_BODY)
    assert response.status_code == 404
    guard.assert_not_called()


def test_get_reports_a_stale_upload_with_its_spec(state) -> None:
    body = client.get(_UPLOAD_URL).json()
    assert body["itemId"] == _ITEM
    assert (body["eligible"], body["stale"], body["staleAfterDays"]) == (True, True, 90)
    assert body["ageDays"] >= 120 and body["sourceLabel"] == "orders.graphql"
    assert body["spec"] == _SPEC


def test_get_reports_an_item_that_is_not_an_upload(state) -> None:
    state.revision = _revision(input_kind="url")
    body = client.get(_UPLOAD_URL).json()
    assert (body["eligible"], body["stale"], body["spec"]) == (False, False, None)


def test_the_policy_reads_and_writes_with_an_audit_row(state) -> None:
    assert client.get(_POLICY_URL).json() == {"staleAfterDays": 90}
    assert client.put(_POLICY_URL, json={"staleAfterDays": 14}).json() == {"staleAfterDays": 14}
    assert state.audits == [{"action": AUDIT_POLICY, "detail": {"staleAfterDays": 14}}]
    # A stale threshold of 14 now flags a 120-day-old upload as well; a fresh one is not.
    state.revision = _revision(created_at=datetime.now(timezone.utc) - timedelta(days=3))
    assert client.get(_UPLOAD_URL).json()["stale"] is False


@pytest.mark.parametrize("days", [0, 3651, "x"])
def test_the_policy_refuses_out_of_range(state, days) -> None:
    assert client.put(_POLICY_URL, json={"staleAfterDays": days}).status_code == 422
    assert state.audits == []


def test_a_re_upload_answers_changed_and_audits(state) -> None:
    response = client.post(_REUPLOAD_URL, json=_BODY)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["status"], body["specReplayed"], body["versionId"], body["versionLabel"]) == (
        "changed", True, "rev-new", "2026-10-30T12:00Z")
    assert body["upload"]["itemId"] == _ITEM
    [call] = state.reuploads
    assert (call["tenant_id"], call["project_id"], call["filename"], call["actor_id"]) == (
        _TENANT, _ITEM, "orders-v2.graphql", _ACTOR)
    assert call["raw"] == _SDL_V2.encode()
    assert state.audits[-1]["action"] == AUDIT_REUPLOADED
    assert state.audits[-1]["detail"]["versionId"] == "rev-new"
    assert "documentBase64" not in state.audits[-1]["detail"]


def test_an_unchanged_re_upload_answers_unchanged(state) -> None:
    state.outcome = ReuploadOutcome(changed=False, spec_replayed=True)
    body = client.post(_REUPLOAD_URL, json=_BODY).json()
    assert (body["status"], body["versionId"]) == ("unchanged", None)


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (ReuploadError(CODE_NOT_AN_UPLOAD, "no"), 409, CODE_NOT_AN_UPLOAD),
        (ReuploadError(CODE_UNKNOWN_FORMAT, "no"), 422, CODE_UNKNOWN_FORMAT),
        (ReuploadError(CODE_REUPLOAD_FAILED, "bad schema"), 422, CODE_REUPLOAD_FAILED),
    ],
)
def test_re_upload_refusals_map_to_status_codes(state, error, status, code) -> None:
    state.outcome = error
    response = client.post(_REUPLOAD_URL, json=_BODY)
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


def test_a_re_upload_of_an_item_that_is_not_an_upload_is_refused_before_the_gate(state) -> None:
    state.revision = _revision(input_kind="paste")
    response = client.post(_REUPLOAD_URL, json=_BODY)
    assert response.status_code == 409 and response.json()["detail"]["code"] == CODE_NOT_AN_UPLOAD
    assert state.reuploads == []


def test_a_re_upload_passes_the_quality_gate_with_the_replayed_spec(state, monkeypatch) -> None:
    seen: Dict[str, Any] = {}

    async def _gate(**kw):
        seen.update(kw)
        raise HTTPException(status_code=409, detail={"code": "QUALITY_POLICY_BLOCKED"})

    monkeypatch.setattr("app.spec_import_routes._enforce_quality_gate", _gate)
    response = client.post(_REUPLOAD_URL, json=_BODY)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "QUALITY_POLICY_BLOCKED"
    assert seen["metadata"].source_kind == "graphql"
    assert seen["metadata"].options.class_naming_convention == "camelCase"
    assert seen["metadata"].options.input_kind == "file"
    assert seen["raw"] == _SDL_V2.encode() and seen["filename"] == "orders-v2.graphql"
    assert state.reuploads == []


@pytest.mark.parametrize("document", ["not base64!!", ""])
def test_a_bad_or_empty_file_is_422(state, document) -> None:
    response = client.post(_REUPLOAD_URL, json={"filename": "a.graphql", "documentBase64": document})
    assert response.status_code == 422
    assert state.reuploads == []


def test_a_file_over_the_intake_limit_is_413(state, monkeypatch) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.intake_resource_guard.resolve_guard_profile",
        lambda **kw: SimpleNamespace(limits=SimpleNamespace(max_bytes=10)),
    )
    assert client.post(_REUPLOAD_URL, json=_BODY).status_code == 413
    assert state.reuploads == []
