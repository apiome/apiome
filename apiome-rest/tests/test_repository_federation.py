"""Multi-repository federation — V2-REPO-8.2 (#2806).

The pure rules (finding and bounding a definition, filling the existing side of a conflict), the
routes' contract with the store patched (permissions, audit-bearing writes, 404s), the store's
SQL over a scripted transaction, and the V303 migration's shape.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import repository_federation_store as store
from app.auth import validate_authentication
from app.main import app
from app.permissions import Action, Resource
from app.repository_federation import (
    AUDIT_BY_STATUS,
    DEFINITION_MAX_BYTES,
    FederationMergeCreate,
    bound_definition,
    definition_in_spec,
    with_existing_definitions,
)

client = TestClient(app)

TENANT = "11111111-1111-4111-8111-111111111111"
USER = "33333333-3333-4333-8333-333333333333"
PROJECT = "22222222-2222-4222-8222-222222222222"
REPO = "66666666-6666-4666-8666-666666666666"
PARENT = "44444444-4444-4444-8444-444444444444"
AUTH = {"tenant_id": TENANT, "user_id": USER, "user_email": "ada@acme.io", "auth_method": "jwt"}
NOW = dt.datetime(2026, 10, 19, 12, 0, tzinfo=dt.timezone.utc)

MIGRATION = (
    Path(__file__).resolve().parents[2] / "apiome-db" / "scripts" / "V303__repository_federation_v2_repo_8_2.sql"
)

SPEC = {
    "paths": {"/users": {"get": {"summary": "List"}}},
    "components": {"schemas": {"User": {"type": "object", "properties": {"id": {"type": "string"}}}}},
}


def _report(**overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "status": "conflicted",
        "parentVersionId": PARENT,
        "repositoryId": REPO,
        "repositoryFullName": "acme/billing",
        "branch": "main",
        "path": "openapi.yaml",
        "sourceCount": 2,
        "sources": [
            {"repositoryFullName": "acme/users", "branch": "main", "path": "openapi.yaml", "precedence": 1},
            {"repositoryFullName": "acme/billing", "branch": "main", "path": "openapi.yaml", "precedence": 2},
        ],
        "conflicts": [
            {
                "kind": "class",
                "key": "User",
                "sources": [
                    {
                        "role": "incoming",
                        "repositoryFullName": "acme/billing",
                        "branch": "main",
                        "path": "openapi.yaml",
                        "definition": {"type": "object", "properties": {"id": {"type": "integer"}}},
                    },
                    {"role": "existing", "repositoryFullName": "acme/users", "branch": "main", "path": "openapi.yaml"},
                ],
            }
        ],
    }
    body.update(overrides)
    return body


def _row(**overrides: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "id": "m1",
        "project_id": PROJECT,
        "project_name": "Shop",
        "status": "merged",
        "version_id": PARENT,
        "version_label": "1.2.0",
        "parent_version_id": None,
        "repository_id": REPO,
        "repository_full_name": "acme/billing",
        "branch": "main",
        "path": "openapi.yaml",
        "source_count": 2,
        "classes_carried": 3,
        "paths_carried": 1,
        "removed_count": 0,
        "conflict_count": 0,
        "sources": [],
        "conflicts": [],
        "actor_id": USER,
        "created_at": NOW,
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------


def test_definition_in_spec_finds_schemas_and_paths():
    assert definition_in_spec(SPEC, "class", "User") == SPEC["components"]["schemas"]["User"]
    assert definition_in_spec(SPEC, "path", "/users") == {"get": {"summary": "List"}}
    assert definition_in_spec(SPEC, "class", "Missing") is None
    assert definition_in_spec(None, "path", "/users") is None
    assert definition_in_spec({"components": "bad"}, "class", "User") is None


def test_bound_definition_marks_oversized_values():
    assert bound_definition(None) is None
    assert bound_definition({"a": 1}) == {"a": 1}
    big = {"x": "y" * (DEFINITION_MAX_BYTES + 10)}
    marker = bound_definition(big)
    assert marker["$truncated"] is True and marker["bytes"] > DEFINITION_MAX_BYTES


def test_with_existing_definitions_fills_and_orders_existing_first():
    report = FederationMergeCreate.model_validate(_report())
    [conflict] = with_existing_definitions(report.conflicts, SPEC)
    existing, incoming = conflict["sources"]
    assert existing["role"] == "existing" and existing["definition"] == SPEC["components"]["schemas"]["User"]
    assert incoming["role"] == "incoming" and incoming["definition"]["properties"]["id"]["type"] == "integer"
    assert existing["repositoryFullName"] == "acme/users"
    [unfilled] = with_existing_definitions(report.conflicts, None)
    assert unfilled["sources"][0]["definition"] is None


def test_report_validation_limits():
    with pytest.raises(ValueError):
        FederationMergeCreate.model_validate(_report(status="exploded"))
    one_side = _report()
    one_side["conflicts"][0]["sources"] = one_side["conflicts"][0]["sources"][:1]
    with pytest.raises(ValueError):
        FederationMergeCreate.model_validate(one_side)
    with pytest.raises(ValueError):
        FederationMergeCreate.model_validate({**_report(), "token": "x"})


def test_every_status_has_an_audit_action():
    assert AUDIT_BY_STATUS == {
        "merged": "repository.federation_merged",
        "conflicted": "repository.federation_conflicted",
        "replaced": "repository.federation_replaced",
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: AUTH
    yield
    app.dependency_overrides.clear()


def _patch(name: str, **kwargs: Any):
    return patch(f"app.repository_federation_routes.{name}", **kwargs)


def _guards(mock) -> list:
    return [call.args[2:] for call in mock.call_args_list]


URL = f"/v1/tenants/acme/projects/{PROJECT}"


def test_get_and_put_the_switch():
    with _patch("enforce_permission") as guard, _patch("resolve_project", return_value={"id": PROJECT}), _patch(
        "store.get_federation_enabled", return_value=None
    ):
        response = client.get(f"{URL}/repository-federation")
    assert response.status_code == 200
    assert response.json() == {"projectId": PROJECT, "enabled": True}
    assert _guards(guard) == [(Resource.PROJECTS, Action.VIEW)]

    with _patch("enforce_permission") as guard, _patch("resolve_project", return_value={"id": PROJECT}), _patch(
        "store.set_federation_enabled", return_value=False
    ) as setter:
        response = client.put(f"{URL}/repository-federation", json={"enabled": False})
    assert response.json() == {"projectId": PROJECT, "enabled": False}
    assert _guards(guard) == [(Resource.PROJECTS, Action.EDIT)]
    assert setter.call_args.args == (TENANT, PROJECT, False)
    assert setter.call_args.kwargs == {"actor_id": USER, "actor_label": "ada@acme.io"}

    with _patch("enforce_permission"), _patch("resolve_project", return_value={"id": PROJECT}), _patch(
        "store.set_federation_enabled", return_value=None
    ):
        assert client.put(f"{URL}/repository-federation", json={"enabled": True}).status_code == 404
    with _patch("enforce_permission"), _patch("resolve_project", return_value={"id": PROJECT}):
        assert client.put(f"{URL}/repository-federation", json={"enabled": "maybe"}).status_code == 422


def test_record_a_conflict_fills_the_existing_side_from_the_parent():
    with _patch("enforce_permission") as guard, _patch("resolve_project", return_value={"id": PROJECT}), _patch(
        "_parent_spec", return_value=SPEC
    ) as parent, _patch("store.insert_merge", return_value="m1") as insert, _patch(
        "store.list_project_merges", return_value=[_row(status="conflicted", version_id=None, conflict_count=1)]
    ):
        response = client.post(f"{URL}/federation-merges", json=_report())
    assert response.status_code == 201, response.text
    assert _guards(guard) == [(Resource.IMPORTS, Action.CREATE)]
    assert parent.call_args.args == (TENANT, "acme", PROJECT, PARENT)
    args, kwargs = insert.call_args
    assert args[0:2] == (TENANT, PROJECT)
    stored_conflicts = args[3]
    assert stored_conflicts[0]["sources"][0]["definition"] == SPEC["components"]["schemas"]["User"]
    assert kwargs == {"actor_id": USER, "actor_label": "ada@acme.io"}
    assert response.json()["status"] == "conflicted"


def test_record_a_merge_skips_the_parent_render():
    with _patch("enforce_permission"), _patch("resolve_project", return_value={"id": PROJECT}), _patch(
        "_parent_spec"
    ) as parent, _patch("store.insert_merge", return_value="m1"), _patch(
        "store.list_project_merges", return_value=[_row()]
    ):
        response = client.post(
            f"{URL}/federation-merges",
            json=_report(status="merged", versionId=PARENT, conflicts=[], classesCarried=3, pathsCarried=1),
        )
    assert response.status_code == 201
    parent.assert_not_called()
    body = response.json()
    assert body["classesCarried"] == 3 and body["versionLabel"] == "1.2.0" and body["projectName"] == "Shop"


def test_record_for_a_project_outside_the_tenant_is_404():
    with _patch("enforce_permission"), _patch("resolve_project", return_value={"id": PROJECT}), _patch(
        "_parent_spec", return_value=None
    ), _patch("store.insert_merge", return_value=None):
        assert client.post(f"{URL}/federation-merges", json=_report()).status_code == 404


def test_history_reads():
    with _patch("enforce_permission") as guard, _patch("resolve_project", return_value={"id": PROJECT}), _patch(
        "store.list_project_merges", return_value=[_row(), _row(id="m2", status="replaced")]
    ) as listing:
        response = client.get(f"{URL}/federation-merges?limit=10")
    assert [m["id"] for m in response.json()["merges"]] == ["m1", "m2"]
    assert listing.call_args.args == (TENANT, PROJECT, 10)
    assert _guards(guard) == [(Resource.PROJECTS, Action.VIEW)]

    repo_url = f"/v1/tenants/acme/repositories/{REPO}/federation-merges"
    with _patch("enforce_permission") as guard, _patch("db.get_tenant_repository", return_value={"id": REPO}), _patch(
        "store.list_repository_merges", return_value=[_row()]
    ):
        response = client.get(repo_url)
    assert response.status_code == 200 and len(response.json()["merges"]) == 1
    assert _guards(guard) == [(Resource.IMPORTS, Action.VIEW)]
    with _patch("enforce_permission"), _patch("db.get_tenant_repository", return_value=None):
        assert client.get(repo_url).status_code == 404
    with _patch("enforce_permission"):
        assert client.get("/v1/tenants/acme/repositories/nope/federation-merges").status_code == 404


def test_parent_spec_is_best_effort():
    from app import repository_federation_routes as routes

    assert routes._parent_spec(TENANT, "acme", PROJECT, None) is None
    assert routes._parent_spec(TENANT, "acme", PROJECT, "not-a-uuid") is None
    with _patch("db.get_version_by_id", return_value={"id": PARENT, "project_id": "other"}):
        assert routes._parent_spec(TENANT, "acme", PROJECT, PARENT) is None
    with _patch("db.get_version_by_id", return_value={"id": PARENT, "project_id": PROJECT}), _patch(
        "openapi_for_revision", side_effect=RuntimeError("boom")
    ):
        assert routes._parent_spec(TENANT, "acme", PROJECT, PARENT) is None
    with _patch("db.get_version_by_id", return_value={"id": PARENT, "project_id": PROJECT}), _patch(
        "openapi_for_revision", return_value=SPEC
    ):
        assert routes._parent_spec(TENANT, "acme", PROJECT, PARENT) == SPEC


# ---------------------------------------------------------------------------
# Store, over a scripted transaction
# ---------------------------------------------------------------------------


class _Cursor:
    def __init__(self, answers: List[Any]) -> None:
        self.answers = list(answers)
        self.statements: List[Any] = []

    def execute(self, query: str, params: Any = None) -> None:
        self.statements.append((" ".join(query.split()), params))

    def fetchone(self) -> Any:
        return self.answers.pop(0) if self.answers else None


def _run_tx(cursor: _Cursor):
    return lambda work: work(cursor)


def test_insert_merge_writes_row_and_audit_together():
    cursor = _Cursor([{"id": "m1"}])
    report = FederationMergeCreate.model_validate(_report(versionId=PARENT))
    conflicts = with_existing_definitions(report.conflicts, SPEC)
    with patch.object(store.db, "_guarded_tx", side_effect=_run_tx(cursor)), patch.object(
        store.db, "_append_access_audit"
    ) as audit:
        assert store.insert_merge(TENANT, PROJECT, report, conflicts, actor_id=USER, actor_label="ada") == "m1"
    query, params = cursor.statements[0]
    assert "INSERT INTO apiome.project_federation_merges" in query
    assert params[2] is None  # a conflicted import has no version, whatever was sent
    assert params[12] == 1  # conflict_count
    kwargs = audit.call_args.kwargs
    assert kwargs["action"] == "repository.federation_conflicted"
    assert kwargs["detail"]["conflicts"] == ["class User"]


def test_insert_merge_outside_tenant_writes_no_audit():
    cursor = _Cursor([None])
    report = FederationMergeCreate.model_validate(_report(status="merged", conflicts=[]))
    with patch.object(store.db, "_guarded_tx", side_effect=_run_tx(cursor)), patch.object(
        store.db, "_append_access_audit"
    ) as audit:
        assert store.insert_merge(TENANT, PROJECT, report, [], actor_id=None, actor_label=None) is None
    audit.assert_not_called()


def test_set_federation_audits_the_toggle():
    cursor = _Cursor([{"repository_federation": False}])
    with patch.object(store.db, "_guarded_tx", side_effect=_run_tx(cursor)), patch.object(
        store.db, "_append_access_audit"
    ) as audit:
        assert store.set_federation_enabled(TENANT, PROJECT, False, actor_id=USER, actor_label="ada") is False
    assert audit.call_args.kwargs["action"] == "repository.federation_toggled"
    assert audit.call_args.kwargs["detail"] == {"projectId": PROJECT, "enabled": False}


def test_list_normalizes_json_columns_and_clamps_limit():
    raw = _row(sources='[{"repositoryFullName": "a/b", "branch": "main", "path": "x.yaml"}]', conflicts=None)
    with patch.object(store.db, "execute_query", return_value=[raw]) as query:
        [row] = store.list_project_merges(TENANT, PROJECT, 9999)
    assert row["sources"][0]["repositoryFullName"] == "a/b" and row["conflicts"] == []
    assert query.call_args.args[1][-1] == store.MAX_HISTORY_LIMIT


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def test_v303_migration_shape():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "set search_path to apiome, public" in sql
    assert "add column if not exists repository_federation boolean not null default true" in sql
    assert "create table if not exists apiome.project_federation_merges" in sql
    assert "check (status in ('merged', 'conflicted', 'replaced'))" in sql
    assert "check (status <> 'conflicted' or version_id is null)" in sql
    assert "create index if not exists idx_project_federation_merges_project" in sql
    assert "rollback" in sql
