"""Project activity timeline correlated with schema revisions (#2594).

Covers the pure rules (:mod:`app.project_timeline`), the timeline query's SQL shape, the route
(``GET /v1/versions/{tenant}/{project}/timeline``) and the new audit events: ``version.publish``
and ``tag.create`` / ``tag.update`` / ``tag.delete``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.database import Database
from app.main import app
from app.project_timeline import (
    ALL_KINDS,
    KIND_MERGE,
    KIND_OTHER,
    KIND_PROTECTION,
    KIND_PUBLISH,
    KIND_TAG,
    PUBLIC_OUTCOMES,
    SOURCE_PROTECTION,
    SOURCE_WORKFLOW,
    classify,
    kind_filter,
    parse_kinds,
    publish_audit_detail,
    revision_links,
    tag_audit_detail,
    to_event,
    visible_outcomes,
)

U = [f"00000000-0000-4000-8000-00000000000{i}" for i in range(8)]
_PROJECT = "00000000-0000-4000-8000-0000000000a1"
_T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _row(**overrides: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "id": U[7],
        "source": SOURCE_WORKFLOW,
        "action": "version.publish",
        "outcome": "success",
        "actor_id": U[6],
        "revision_id": U[2],
        "version_label": "1.2.0",
        "resource_type": None,
        "resource_id": None,
        "detail": {"visibility": "private", "mergeParentRevisionId": U[1]},
        "created_at": _T0,
    }
    row.update(overrides)
    return row


# ===========================================================================
# Pure rules
# ===========================================================================


class TestClassify:
    def test_workflow_actions(self) -> None:
        assert classify(SOURCE_WORKFLOW, "version.publish") == KIND_PUBLISH
        assert classify(SOURCE_WORKFLOW, "version.merge") == KIND_MERGE
        assert classify(SOURCE_WORKFLOW, "version.rollback") == KIND_MERGE
        assert classify(SOURCE_WORKFLOW, "tag.create") == KIND_TAG
        assert classify(SOURCE_WORKFLOW, "version.compat_gate_override") == KIND_PROTECTION

    def test_unmapped_workflow_action_is_other(self) -> None:
        assert classify(SOURCE_WORKFLOW, "version.push") == KIND_OTHER
        assert classify(SOURCE_WORKFLOW, "") == KIND_OTHER

    def test_every_protection_ledger_row_is_protection(self) -> None:
        assert classify(SOURCE_PROTECTION, "tag.update") == KIND_PROTECTION
        assert classify(SOURCE_PROTECTION, "version.rollback") == KIND_PROTECTION


class TestParseKinds:
    def test_none_and_blank_mean_no_filter(self) -> None:
        assert parse_kinds(None) is None
        assert parse_kinds([]) is None
        assert parse_kinds(["", " , "]) is None

    def test_repeated_and_comma_separated_case_insensitive(self) -> None:
        assert parse_kinds(["Publish,tag", "merge"]) == {KIND_PUBLISH, KIND_TAG, KIND_MERGE}

    def test_every_kind_is_no_filter(self) -> None:
        assert parse_kinds([",".join(ALL_KINDS)]) is None

    def test_unknown_kind_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unknown kind"):
            parse_kinds(["publish", "deploy"])


class TestKindFilter:
    def test_no_filter(self) -> None:
        assert kind_filter(None) is None

    def test_publish_and_protection(self) -> None:
        f = kind_filter(frozenset({KIND_PUBLISH, KIND_PROTECTION}))
        assert f is not None
        assert "version.publish" in f["workflow_actions"]
        assert "version.compat_gate_override" in f["workflow_actions"]
        assert "tag.create" not in f["workflow_actions"]
        assert f["protection_ledger"] is True and f["workflow_other"] is False

    def test_other_excludes_every_mapped_action(self) -> None:
        f = kind_filter(frozenset({KIND_OTHER}))
        assert f is not None
        assert f["workflow_actions"] == [] and f["workflow_other"] is True
        assert "version.publish" in f["excluded_actions"] and "tag.delete" in f["excluded_actions"]
        assert f["protection_ledger"] is False


def test_visible_outcomes() -> None:
    assert visible_outcomes(True) is None
    assert visible_outcomes(False) == PUBLIC_OUTCOMES
    assert "failure" not in PUBLIC_OUTCOMES and "denied" not in PUBLIC_OUTCOMES


def test_revision_links_round_trip_to_the_dag_and_back() -> None:
    links = revision_links("acme", _PROJECT, U[2])
    assert links == {
        "revision": f"/v1/versions/acme/{_PROJECT}/{U[2]}",
        "ancestors": f"/v1/versions/acme/{_PROJECT}/{U[2]}/ancestors",
        "timeline": f"/v1/versions/acme/{_PROJECT}/timeline?revisionId={U[2]}",
    }


class TestToEvent:
    def test_publish_of_a_merge_revision(self) -> None:
        e = to_event(_row(), tenant_slug="acme", project_id=_PROJECT)
        assert e.kind == KIND_PUBLISH and e.revision_id == U[2] and e.version_label == "1.2.0"
        assert e.merge_from_revision_id == U[1]
        assert e.links["ancestors"].endswith(f"/{U[2]}/ancestors")

    def test_merge_reads_source_tip_and_branches(self) -> None:
        e = to_event(
            _row(
                action="version.merge",
                detail={
                    "sourceBranch": "feature",
                    "targetBranch": "main",
                    "sourceTipRevisionId": U[3],
                    "mergeBaseRevisionId": U[0],
                },
            ),
            tenant_slug="acme",
            project_id=_PROJECT,
        )
        assert e.kind == KIND_MERGE
        assert (e.merge_from_revision_id, e.merge_from_branch, e.branch_name) == (U[3], "feature", "main")

    def test_branch_protection_has_no_revision_or_links(self) -> None:
        e = to_event(
            _row(
                source=SOURCE_PROTECTION,
                action="branch.protection_policy",
                outcome="policy_change",
                revision_id=None,
                version_label=None,
                resource_type="version_branch",
                resource_id=U[4],
                detail={"branchName": "main", "isDefaultBranch": True, "protected": True},
            ),
            tenant_slug="acme",
            project_id=_PROJECT,
        )
        assert e.kind == KIND_PROTECTION and e.revision_id is None and e.links == {}
        assert e.branch_name == "main" and e.resource_type == "version_branch" and e.resource_id == U[4]

    def test_tag_event_and_bad_values(self) -> None:
        e = to_event(
            _row(action="tag.update", actor_id=None, detail={"tagName": "stable", "sourceTipRevisionId": "x"}),
            tenant_slug="acme",
            project_id=_PROJECT,
        )
        assert e.kind == KIND_TAG and e.tag_name == "stable"
        assert e.actor_id is None and e.merge_from_revision_id is None

    def test_non_dict_detail_is_dropped(self) -> None:
        e = to_event(_row(detail="oops", revision_id="not-a-uuid"), tenant_slug="acme", project_id=_PROJECT)
        assert e.detail is None and e.revision_id is None and e.links == {}


class TestAuditDetails:
    def test_publish_detail(self) -> None:
        detail = publish_audit_detail(
            {"version_id": "1.2.0", "parent_version_id": U[0], "merge_parent_version_id": None}, "public"
        )
        assert detail == {"visibility": "public", "versionLine": "1.2.0", "parentRevisionId": U[0]}

    def test_tag_detail_move(self) -> None:
        tag = {"id": U[5], "name": "stable", "version_id": U[2], "immutable": False, "protected": True}
        detail = tag_audit_detail(tag, from_revision_id=U[1], changes=["revision"])
        assert detail == {
            "tagId": U[5],
            "tagName": "stable",
            "revisionId": U[2],
            "fromRevisionId": U[1],
            "immutable": False,
            "protected": True,
            "changes": ["revision"],
        }

    def test_tag_detail_same_revision_is_not_a_move(self) -> None:
        detail = tag_audit_detail({"id": U[5], "name": "v1", "version_id": U[2]}, from_revision_id=U[2])
        assert "fromRevisionId" not in detail and "changes" not in detail and "immutable" not in detail


# ===========================================================================
# Query
# ===========================================================================


class TestQuery:
    def _db(self) -> Database:
        db = Database.__new__(Database)
        db.execute_query = MagicMock(return_value=[])  # type: ignore[method-assign]
        return db

    def _call(self, **kwargs: Any) -> tuple:
        db = self._db()
        db.list_project_timeline("t1", _PROJECT, **kwargs)
        sql, params = db.execute_query.call_args.args
        assert sql.count("%s") == len(params)
        return sql, params

    def test_scoped_to_tenant_and_project_in_both_ledgers(self) -> None:
        sql, params = self._call(limit=11)
        assert "UNION ALL" in sql
        assert "wa.tenant_id = %s AND wa.project_id = %s" in sql
        assert "pa.tenant_id = %s AND pa.project_id = %s" in sql
        assert params == ("t1", _PROJECT, "t1", _PROJECT, _PROJECT, 11)
        assert "ORDER BY e.created_at DESC, e.id DESC" in sql

    def test_every_filter(self) -> None:
        sql, params = self._call(
            revision_id=U[2],
            kinds=kind_filter(frozenset({KIND_PUBLISH, KIND_OTHER, KIND_PROTECTION})),
            outcomes=PUBLIC_OUTCOMES,
            actor_id=U[6],
            since=_T0,
            until=_T0,
            limit=5,
            cursor_created_at=_T0,
            cursor_id=U[7],
        )
        assert "e.revision_id = %s::uuid" in sql
        assert "e.action NOT IN" in sql and "e.source = 'protection'" in sql
        assert "e.outcome IN (%s,%s,%s)" in sql
        assert "(e.created_at, e.id) < (%s, %s::uuid)" in sql
        assert params[5] == U[2] and params[-1] == 5

    def test_empty_kind_filter_matches_nothing(self) -> None:
        sql, _ = self._call(kinds={"workflow_actions": [], "workflow_other": False, "protection_ledger": False})
        assert "WHERE FALSE" in sql


# ===========================================================================
# Route
# ===========================================================================

client = TestClient(app)
_AUTH = {"tenant_id": "t1", "user_id": U[6], "auth_method": "jwt"}
_URL = f"/v1/versions/acme/{_PROJECT}/timeline"


@pytest.fixture
def mdb():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    with (
        patch("app.project_timeline_routes.db") as mock_db,
        patch("app.project_timeline_routes.enforce_permission") as permission,
        patch("app.project_timeline_routes.get_authenticated_user_id", return_value=U[6]),
    ):
        mock_db.get_project_by_id.return_value = {"id": _PROJECT}
        mock_db.is_user_tenant_admin.return_value = False
        mock_db.list_project_timeline.return_value = [_row()]
        mock_db.permission = permission
        yield mock_db
    app.dependency_overrides.pop(validate_authentication, None)


class TestRoute:
    def test_lists_events_with_revision_links(self, mdb: MagicMock) -> None:
        r = client.get(_URL)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["projectId"] == _PROJECT and data["hasMore"] is False and data["nextCursor"] is None
        item = data["items"][0]
        assert item["kind"] == "publish" and item["revisionId"] == U[2]
        assert item["mergeFromRevisionId"] == U[1] and item["versionLabel"] == "1.2.0"
        assert item["links"]["ancestors"] == f"/v1/versions/acme/{_PROJECT}/{U[2]}/ancestors"
        mdb.permission.assert_called_once()
        assert mdb.permission.call_args.args[2:] == ("versions", "view")

    def test_non_admins_see_public_outcomes_only(self, mdb: MagicMock) -> None:
        data = client.get(_URL).json()
        assert data["restricted"] is True
        assert mdb.list_project_timeline.call_args.kwargs["outcomes"] == PUBLIC_OUTCOMES

    def test_admins_see_every_outcome(self, mdb: MagicMock) -> None:
        mdb.is_user_tenant_admin.return_value = True
        data = client.get(_URL).json()
        assert data["restricted"] is False
        assert mdb.list_project_timeline.call_args.kwargs["outcomes"] is None

    def test_filters_are_passed_through(self, mdb: MagicMock) -> None:
        params = {"revisionId": U[2], "kind": "tag,merge", "actorId": U[6], "since": "2026-10-01T00:00:00Z"}
        r = client.get(_URL, params=params)
        assert r.status_code == 200
        kw = mdb.list_project_timeline.call_args.kwargs
        assert kw["revision_id"] == U[2] and kw["actor_id"] == U[6]
        assert set(kw["kinds"]["workflow_actions"]) >= {"tag.create", "version.merge"}
        assert kw["since"] == datetime(2026, 10, 1, tzinfo=timezone.utc)
        assert mdb.list_project_timeline.call_args.args == ("t1", _PROJECT)

    def test_pagination_cursor_round_trip(self, mdb: MagicMock) -> None:
        mdb.list_project_timeline.return_value = [_row(id=U[i], created_at=_T0) for i in range(3)]
        data = client.get(_URL, params={"limit": 2}).json()
        assert data["hasMore"] is True and len(data["items"]) == 2
        assert mdb.list_project_timeline.call_args.kwargs["limit"] == 3
        r = client.get(_URL, params={"limit": 2, "cursor": data["nextCursor"]})
        assert r.status_code == 200
        kw = mdb.list_project_timeline.call_args.kwargs
        assert kw["cursor_id"] == U[1] and kw["cursor_created_at"] == _T0

    def test_bad_input(self, mdb: MagicMock) -> None:
        assert client.get(_URL, params={"kind": "deploy"}).status_code == 400
        assert client.get(_URL, params={"revisionId": "nope"}).status_code == 400
        assert client.get(_URL, params={"cursor": "!!"}).status_code == 400
        assert client.get(_URL, params={"limit": 0}).status_code == 422
        assert client.get(_URL, params={"limit": 201}).status_code == 422

    def test_unknown_project_is_404(self, mdb: MagicMock) -> None:
        mdb.get_project_by_id.return_value = None
        assert client.get(_URL).status_code == 404
        mdb.list_project_timeline.assert_not_called()


# ===========================================================================
# Tag audit events
# ===========================================================================

_TAG = {"id": U[5], "project_id": _PROJECT, "version_id": U[2], "name": "stable", "message": None,
        "channel": None, "immutable": False, "protected": False, "created_by": U[6],
        "created_at": _T0, "updated_at": _T0}


@pytest.fixture
def tag_db():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    with (
        patch("app.version_tags_routes.db") as mock_db,
        patch("app.version_tags_routes.enforce_permission"),
        patch("app.version_tags_routes.get_authenticated_user_id", return_value=U[6]),
    ):
        mock_db.get_project_by_id.return_value = {"id": _PROJECT}
        mock_db.is_user_tenant_admin.return_value = False
        yield mock_db
    app.dependency_overrides.pop(validate_authentication, None)


def _audit_calls(mock_db: MagicMock) -> List[tuple]:
    return [c.args for c in mock_db.insert_workflow_audit.call_args_list]


class TestTagAudit:
    def test_create(self, tag_db: MagicMock) -> None:
        tag_db.create_version_tag.return_value = _TAG
        r = client.post(f"/v1/version-tags/acme/{_PROJECT}", json={"name": "stable", "version_id": U[2]})
        assert r.status_code == 200, r.text
        (args,) = _audit_calls(tag_db)
        assert args[:6] == ("t1", _PROJECT, U[2], "tag.create", "success", U[6])
        assert args[6]["tagName"] == "stable" and args[6]["tagId"] == U[5]

    def test_failed_create_is_not_audited(self, tag_db: MagicMock) -> None:
        tag_db.create_version_tag.side_effect = ValueError("Target version not found in this project")
        r = client.post(f"/v1/version-tags/acme/{_PROJECT}", json={"name": "stable", "version_id": U[2]})
        assert r.status_code == 400
        tag_db.insert_workflow_audit.assert_not_called()

    def test_move_records_both_revisions(self, tag_db: MagicMock) -> None:
        tag_db.get_version_tag_by_id.return_value = {**_TAG, "version_id": U[1]}
        tag_db.update_version_tag.return_value = _TAG
        r = client.patch(f"/v1/version-tags/acme/{_PROJECT}/{U[5]}", json={"version_id": U[2], "message": "GA"})
        assert r.status_code == 200, r.text
        (args,) = _audit_calls(tag_db)
        assert args[2] == U[2] and args[3] == "tag.update"
        assert args[6]["fromRevisionId"] == U[1] and args[6]["changes"] == ["revision", "message"]

    def test_refused_update_is_not_audited(self, tag_db: MagicMock) -> None:
        tag_db.get_version_tag_by_id.return_value = _TAG
        tag_db.update_version_tag.side_effect = PermissionError("TAG_IMMUTABLE")
        r = client.patch(f"/v1/version-tags/acme/{_PROJECT}/{U[5]}", json={"version_id": U[2]})
        assert r.status_code == 409
        tag_db.insert_workflow_audit.assert_not_called()

    def test_delete_records_the_last_revision(self, tag_db: MagicMock) -> None:
        tag_db.get_version_tag_by_id.return_value = _TAG
        tag_db.delete_version_tag.return_value = True
        r = client.delete(f"/v1/version-tags/acme/{_PROJECT}/{U[5]}")
        assert r.status_code == 200
        (args,) = _audit_calls(tag_db)
        assert args[2] == U[2] and args[3] == "tag.delete"

    def test_missing_tag_delete_is_not_audited(self, tag_db: MagicMock) -> None:
        tag_db.get_version_tag_by_id.return_value = None
        tag_db.delete_version_tag.return_value = False
        assert client.delete(f"/v1/version-tags/acme/{_PROJECT}/{U[5]}").status_code == 404
        tag_db.insert_workflow_audit.assert_not_called()
