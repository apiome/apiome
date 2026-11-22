"""OpenAPI spec upgrade assistant — REST contract (COA-2.6, #7049).

``POST /v1/openapi-upgrade/{tenant}/plan`` and ``…/apply``: sources (pasted text, a captured
version source, a rebuilt decomposed import), refusals, the stale-plan guard, the new version
the apply imports, permissions and the audit row.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict, List, Optional

import pytest
import yaml
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import openapi_upgrade_routes as routes
from app.auth import validate_authentication
from app.database import db
from app.main import app
from app.models import SpecImportJobResult, SpecImportJobStatus
from app.permissions import Action, Resource

_TENANT = "11111111-1111-1111-1111-111111111111"
_PROJECT = "22222222-2222-2222-2222-222222222222"
_REVISION = "33333333-3333-3333-3333-333333333333"
_ACTOR = "44444444-4444-4444-4444-444444444444"
_AUTH = {"tenant_id": _TENANT, "user_id": _ACTOR, "auth_method": "jwt", "user_email": "a@x.io"}
_PLAN_URL = "/v1/openapi-upgrade/acme/plan"
_APPLY_URL = "/v1/openapi-upgrade/acme/apply"

_SWAGGER = {
    "swagger": "2.0",
    "info": {"title": "Pets", "version": "1.0.0"},
    "host": "api.example.com",
    "schemes": ["https"],
    "paths": {"/pets": {"get": {"responses": {"200": {"description": "ok", "schema": {"$ref": "#/definitions/Pet"}}}}}},
    "definitions": {"Pet": {"type": "object", "properties": {"name": {"type": "string", "x-nullable": True}}}},
}

client = TestClient(app)


class _State:
    """The stubbed version row, labels, imports and audit rows."""

    def __init__(self) -> None:
        self.row: Optional[Dict[str, Any]] = {
            "id": _PROJECT,
            "project_slug": "pets",
            "version_label": "1.0.0",
            "source_format": "openapi",
            "format_metadata": {"sourceContent": yaml.safe_dump(_SWAGGER), "intakeKind": "file"},
            "metadata": {},
        }
        self.labels: List[str] = ["1.0.0"]
        self.imports: List[Dict[str, Any]] = []
        self.audits: List[Dict[str, Any]] = []
        self.gates: List[Dict[str, Any]] = []
        self.import_state = "completed"


@pytest.fixture
def state(monkeypatch) -> _State:
    st = _State()
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    monkeypatch.setattr(routes, "enforce_permission", lambda *a, **k: _ACTOR)
    monkeypatch.setattr(routes, "resolve_revision_id", lambda tenant, project, version: _REVISION)
    monkeypatch.setattr(db, "get_version_source_projection", lambda rev, tenant: st.row)
    monkeypatch.setattr(db, "get_versions_for_project", lambda p, t, *a, **k: [{"version_id": v} for v in st.labels])
    monkeypatch.setattr(db, "get_project_by_id", lambda p, t, **k: {"id": p, "name": "Pets", "slug": "pets"})
    monkeypatch.setattr(db, "get_project_core", lambda p, t, **k: {"id": p, "name": "Pets", "slug": "pets"})
    monkeypatch.setattr(
        db,
        "insert_workflow_audit",
        lambda t, p, v, action, outcome, actor, detail=None: st.audits.append({"action": action, "detail": detail}),
    )

    async def _gate(**kw):
        st.gates.append(kw)

    monkeypatch.setattr("app.spec_import_routes._enforce_quality_gate", _gate)

    async def _pipeline(adapter, payload, **kw):
        st.imports.append({"adapter": adapter.key, "payload": payload})
        if st.import_state != "completed":
            return SpecImportJobStatus(job_id="j", state="failed", percent=10)
        return SpecImportJobStatus(
            job_id="j",
            state="completed",
            percent=100,
            result=SpecImportJobResult(
                project_id=_PROJECT,
                project_slug="pets",
                version_id=payload["metadata"]["version"]["version_id"],
                version_record_id="rev-new",
            ),
        )

    monkeypatch.setattr("app.import_source_pipeline.run_adapter_import_job", _pipeline)
    yield st
    app.dependency_overrides.clear()


def _plan(**body: Any):
    return client.post(_PLAN_URL, json={"target": "3.1", **body})


# ---------------------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------------------


def test_plan_from_pasted_yaml(state) -> None:
    response = _plan(document_text=yaml.safe_dump(_SWAGGER))
    assert response.status_code == 200
    plan = response.json()
    assert plan["origin"] == "request"
    assert plan["source_family"] == "2.0"
    assert plan["target_version"] == "3.1.2"
    assert plan["hops"] == ["2.0→3.0", "3.0→3.1"]
    assert plan["document"]["components"]["schemas"]["Pet"]["properties"]["name"]["type"] == ["string", "null"]
    rules = {row["rule"] for row in plan["rules"]}
    assert {"definition-to-component-schema", "x-nullable-to-nullable", "nullable-to-type-array"} <= rules
    assert plan["change_count"] == len(plan["changes"])
    assert plan["plan_digest"].startswith("sha256:")


def test_plan_from_a_version_uses_its_captured_source(state) -> None:
    response = _plan(project_id=_PROJECT, include_document=False)
    assert response.status_code == 200
    plan = response.json()
    assert plan["origin"] == "captured"
    assert plan["project_id"] == _PROJECT
    assert plan["version_record_id"] == _REVISION
    assert plan["version_label"] == "1.0.0"
    assert "document" not in plan


def test_plan_rebuilds_a_decomposed_import(state, monkeypatch) -> None:
    state.row["format_metadata"] = {}
    rebuilt = {"openapi": "3.1.0", "info": {"title": "Pets", "version": "1"}, "paths": {}}
    monkeypatch.setattr(
        routes,
        "_reconstructed_openapi_item",
        lambda item, tenant, rev: {**item, "format_metadata": {"sourceContent": json.dumps(rebuilt)}},
    )
    plan = client.post(_PLAN_URL, json={"target": "3.2", "project_id": _PROJECT}).json()
    assert plan["origin"] == "rebuilt"
    assert [row["rule"] for row in plan["rules"]] == ["openapi-version"]


@pytest.mark.parametrize(
    "fmd,code",
    [
        ({"sourceWithheld": "secrets-detected", "sourceContent": None}, "source-withheld"),
        ({"intakeKind": "archive", "sourceContent": "UEsD", "sourceEncoding": "base64"}, "unsupported-source"),
    ],
)
def test_plan_refuses_a_source_it_cannot_read(state, fmd, code) -> None:
    state.row["format_metadata"] = fmd
    response = _plan(project_id=_PROJECT)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == code


def test_plan_refuses_a_version_with_no_source(state) -> None:
    state.row["format_metadata"] = {}
    state.row["source_format"] = "graphql"
    response = _plan(project_id=_PROJECT)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no-source"


def test_plan_404s_a_version_of_another_project(state) -> None:
    state.row["id"] = "99999999-9999-9999-9999-999999999999"
    assert _plan(project_id=_PROJECT).status_code == 404


def test_plan_404s_an_unknown_version(state) -> None:
    state.row = None
    assert _plan(project_id=_PROJECT).status_code == 404


@pytest.mark.parametrize(
    "text,target,status,code",
    [
        ("asyncapi: 2.6.0\ninfo: {title: x, version: '1'}\n", "3.1", 422, "not-openapi"),
        ("{not json or yaml: [", "3.1", 422, "unparseable"),
        (
            json.dumps({"openapi": "3.2.0", "info": {"title": "x", "version": "1"}, "paths": {}}),
            "3.1",
            422,
            "target-older",
        ),
    ],
)
def test_plan_refusals(state, text, target, status, code) -> None:
    response = client.post(_PLAN_URL, json={"target": target, "document_text": text})
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


@pytest.mark.parametrize(
    "body",
    [
        {"target": "3.1"},
        {"target": "3.1", "document_text": "x", "project_id": _PROJECT},
        {"target": "3.1", "document_text": "x", "version": "1.0.0"},
        {"target": "4.0", "document_text": "x"},
    ],
)
def test_plan_validates_the_request(state, body) -> None:
    assert client.post(_PLAN_URL, json=body).status_code == 422


def test_plan_permissions(state, monkeypatch) -> None:
    grants: List[Any] = []
    monkeypatch.setattr(
        routes, "enforce_permission", lambda _db, _auth, resource, action, **k: grants.append((resource, action))
    )
    _plan(project_id=_PROJECT)
    _plan(document_text=json.dumps(_SWAGGER))
    assert grants == [(Resource.IMPORTS, Action.VIEW), (Resource.PROJECTS, Action.VIEW)]


# ---------------------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------------------


def _digest(target: str = "3.1") -> str:
    return client.post(_PLAN_URL, json={"target": target, "project_id": _PROJECT}).json()["plan_digest"]


def test_apply_imports_the_upgraded_document_as_a_new_version(state) -> None:
    digest = _digest()
    response = client.post(
        _APPLY_URL,
        json={"target": "3.1", "project_id": _PROJECT, "plan_digest": digest, "version_label": "2.0.0"},
    )
    assert response.status_code == 200, response.text
    out = response.json()
    assert out == {
        "project_id": _PROJECT,
        "version_record_id": "rev-new",
        "version_label": "2.0.0",
        "source_version_record_id": _REVISION,
        "target_version": "3.1.2",
        "change_count": out["change_count"],
    }
    [call] = state.imports
    assert call["adapter"] == "openapi"
    metadata = call["payload"]["metadata"]
    assert metadata["existing_project_id"] == _PROJECT
    assert metadata["version"]["version_id"] == "2.0.0"
    assert "Upgraded from OpenAPI 2.0 to 3.1.2" in metadata["version"]["description"]
    imported = json.loads(base64.standard_b64decode(call["payload"]["document_base64"]))
    assert imported["openapi"] == "3.1.2"
    assert "components" in imported and "definitions" not in imported
    [gate] = state.gates
    assert gate["metadata"].project.project_id == _PROJECT
    [audit] = state.audits
    assert audit["action"] == routes.AUDIT_APPLIED
    assert audit["detail"]["from"] == "2.0" and audit["detail"]["to"] == "3.1.2"


def test_apply_mints_a_label_when_none_is_given(state) -> None:
    response = client.post(_APPLY_URL, json={"target": "3.1", "project_id": _PROJECT, "plan_digest": _digest()})
    assert response.status_code == 200
    label = response.json()["version_label"]
    assert label and label != "1.0.0"


def test_apply_refuses_a_stale_plan(state) -> None:
    digest = _digest()
    state.row["format_metadata"]["sourceContent"] = yaml.safe_dump(
        {**_SWAGGER, "info": {"title": "Changed", "version": "2"}}
    )
    response = client.post(_APPLY_URL, json={"target": "3.1", "project_id": _PROJECT, "plan_digest": digest})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "plan-stale"
    assert state.imports == []


def test_apply_refuses_a_digest_for_another_target(state) -> None:
    response = client.post(_APPLY_URL, json={"target": "3.2", "project_id": _PROJECT, "plan_digest": _digest("3.1")})
    assert response.json()["detail"]["code"] == "plan-stale"


def test_apply_refuses_an_existing_label(state) -> None:
    response = client.post(
        _APPLY_URL, json={"target": "3.1", "project_id": _PROJECT, "plan_digest": _digest(), "version_label": "1.0.0"}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "version-exists"
    assert state.imports == []


def test_apply_refuses_nothing_to_upgrade(state) -> None:
    state.row["format_metadata"]["sourceContent"] = json.dumps(
        {"openapi": "3.1.0", "info": {"title": "x", "version": "1"}, "paths": {}}
    )
    response = client.post(_APPLY_URL, json={"target": "3.1", "project_id": _PROJECT, "plan_digest": "sha256:x"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "nothing-to-upgrade"


def test_apply_reports_a_failed_import(state) -> None:
    state.import_state = "failed"
    response = client.post(_APPLY_URL, json={"target": "3.1", "project_id": _PROJECT, "plan_digest": _digest()})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "upgrade-import-failed"
    assert state.audits == []


def test_apply_stops_at_the_quality_gate(state, monkeypatch) -> None:
    async def _blocked(**kw):
        raise HTTPException(status_code=409, detail={"code": "QUALITY_POLICY_BLOCKED"})

    monkeypatch.setattr("app.spec_import_routes._enforce_quality_gate", _blocked)
    response = client.post(_APPLY_URL, json={"target": "3.1", "project_id": _PROJECT, "plan_digest": _digest()})
    assert response.status_code == 409
    assert state.imports == []


def test_apply_permissions(state, monkeypatch) -> None:
    digest = _digest()
    grants: List[Any] = []

    def _grant(_db, _auth, resource, action, **k):
        grants.append((resource, action))
        return _ACTOR

    monkeypatch.setattr(routes, "enforce_permission", _grant)
    client.post(_APPLY_URL, json={"target": "3.1", "project_id": _PROJECT, "plan_digest": digest})
    assert grants == [(Resource.IMPORTS, Action.CREATE), (Resource.PROJECTS, Action.EDIT)]


def test_apply_is_refused_without_permission(state, monkeypatch) -> None:
    def _deny(*a, **k):
        raise HTTPException(status_code=403, detail="forbidden")

    monkeypatch.setattr(routes, "enforce_permission", _deny)
    response = client.post(_APPLY_URL, json={"target": "3.1", "project_id": _PROJECT, "plan_digest": "sha256:x"})
    assert response.status_code == 403
    assert state.imports == []
