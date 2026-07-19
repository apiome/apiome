"""Source review/apply API — DCW-2.3 (private-suite#2360).

The DCW-0.2 authorization matrix (cross-tenant reads/writes deny via 404
without mutation, unauthorized-project writes deny 403, published-version
writes deny 409, draft-lock conflicts deny 409 with the lock holder), the
optimistic-concurrency conflict contract (409 STALE_BASE with resolution
choices, never last-write-wins), idempotent replay, structured 422s for
invalid source, and the no-mutation guarantee on every failure path.
"""

import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.database import SourceApplyConflictError
from app.main import app

client = TestClient(app)

_MOCK_JWT = {"tenant_id": "t1", "user_id": "user-a", "auth_method": "jwt"}

_VERSION_ROW = {
    "id": "11111111-1111-1111-1111-111111111111",
    "project_id": "proj",
    "project_slug": "proj",
    "version_id": "1.0.0",
    "published": False,
    "metadata": {"oasDialect": "3.1.0"},
}

_BASE = "/v1/versions/tn/proj/11111111-1111-1111-1111-111111111111"

_CANDIDATE = {
    "openapi": "3.1.0",
    "info": {
        "title": "proj API",
        "version": "1.0.0",
        "description": "No description provided",
    },
    "paths": {},
    "components": {"schemas": {"Pet": {"type": "object", "title": "Pet"}}},
}


def _source(document=None):
    return json.dumps(document if document is not None else _CANDIDATE)


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: dict(_MOCK_JWT)
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _mock_db(mdb, *, version=_VERSION_ROW):
    mdb.get_version_by_id.return_value = dict(version) if version else None
    mdb.get_preservation_claims.return_value = []
    mdb.get_classes_for_version.return_value = []


class TestReview:
    def test_scope_miss_is_404_not_403(self):
        """Cross-tenant read: prefer 404 over 403 to avoid leaking existence."""
        with patch("app.source_review_routes.db") as mdb:
            _mock_db(mdb, version=None)
            r = client.post(
                f"{_BASE}/source-review",
                json={"sourceText": _source(), "sourceFormat": "json"},
            )
            assert r.status_code == 404

    def test_invalid_source_is_structured_422(self):
        with patch("app.source_review_routes.db") as mdb:
            _mock_db(mdb)
            r = client.post(
                f"{_BASE}/source-review",
                json={"sourceText": "openapi: [unclosed", "sourceFormat": "yaml"},
            )
            assert r.status_code == 422
            assert r.json()["detail"]["code"] == "SOURCE_INVALID"
            assert r.json()["detail"]["diagnostics"]

    def test_dangling_ref_is_structured_422(self):
        bad = dict(_CANDIDATE)
        bad["components"] = {
            "schemas": {
                "Pet": {
                    "type": "object",
                    "properties": {"toy": {"$ref": "#/components/schemas/Toy"}},
                }
            }
        }
        with patch("app.source_review_routes.db") as mdb:
            _mock_db(mdb)
            r = client.post(
                f"{_BASE}/source-review",
                json={"sourceText": _source(bad), "sourceFormat": "json"},
            )
            assert r.status_code == 422
            assert r.json()["detail"]["refIntegrity"][0]["ref"] == "#/components/schemas/Toy"

    def test_review_returns_grouped_change_set_without_mutation(self):
        with patch("app.source_review_routes.db") as mdb:
            _mock_db(mdb)
            r = client.post(
                f"{_BASE}/source-review",
                json={"sourceText": _source(), "sourceFormat": "json"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["dialect"] == "3.1.0"
            change_set = body["changeSet"]
            assert change_set["baseDigest"] and change_set["changeSetDigest"]
            schema_changes = [
                c for c in change_set["changes"] if c["scope"] == "schema"
            ]
            assert schema_changes and schema_changes[0]["group"] == "Pet"
            assert change_set["counts"]["total"] == len(change_set["changes"])
            mdb.apply_source_change_set.assert_not_called()

    def test_unauthorized_project_member_is_403(self):
        with patch("app.source_review_routes.db") as mdb, patch(
            "app.source_review_routes.enforce_permission",
            side_effect=HTTPException(status_code=403, detail="denied"),
        ):
            _mock_db(mdb)
            r = client.post(
                f"{_BASE}/source-review",
                json={"sourceText": _source(), "sourceFormat": "json"},
            )
            assert r.status_code == 403


class TestApplyConflicts:
    def _apply(self, mdb, *, error=None, result=None, document=None):
        _mock_db(mdb)
        if error is not None:
            mdb.apply_source_change_set.side_effect = error
        if result is not None:
            mdb.apply_source_change_set.return_value = result
        return client.post(
            f"{_BASE}/source-apply",
            json={
                "sourceText": _source(document),
                "sourceFormat": "json",
                "baseDigest": "sha256:base",
                "changeSetDigest": "sha256:cs",
            },
        )

    def test_cross_tenant_write_denies_404_without_mutation(self):
        with patch("app.source_review_routes.db") as mdb:
            _mock_db(mdb, version=None)
            r = client.post(
                f"{_BASE}/source-apply",
                json={
                    "sourceText": _source(),
                    "sourceFormat": "json",
                    "baseDigest": "sha256:base",
                    "changeSetDigest": "sha256:cs",
                },
            )
            assert r.status_code == 404
            mdb.apply_source_change_set.assert_not_called()

    def test_published_version_write_is_409_immutable(self):
        with patch("app.source_review_routes.db") as mdb:
            r = self._apply(mdb, error=SourceApplyConflictError("published_version"))
            assert r.status_code == 409
            assert r.json()["detail"]["code"] == "PUBLISHED_IMMUTABLE"

    def test_draft_lock_conflict_names_the_holder(self):
        with patch("app.source_review_routes.db") as mdb:
            r = self._apply(
                mdb,
                error=SourceApplyConflictError(
                    "draft_lock_conflict", {"ownerUserId": "user-b"}
                ),
            )
            assert r.status_code == 409
            detail = r.json()["detail"]
            assert detail["code"] == "DRAFT_LOCK_CONFLICT"
            assert detail["ownerUserId"] == "user-b"

    def test_permission_denied_inside_transaction_is_403(self):
        with patch("app.source_review_routes.db") as mdb:
            r = self._apply(mdb, error=SourceApplyConflictError("permission_denied"))
            assert r.status_code == 403
            assert r.json()["detail"]["code"] == "PERMISSION_DENIED"

    def test_stale_base_is_409_with_resolution_choices(self):
        """Conflicts offer choices (rebase/reparse), never last-write-wins."""
        with patch("app.source_review_routes.db") as mdb:
            r = self._apply(
                mdb,
                error=SourceApplyConflictError(
                    "stale_base", {"currentDigest": "sha256:now"}
                ),
            )
            assert r.status_code == 409
            detail = r.json()["detail"]
            assert detail["code"] == "STALE_BASE"
            assert detail["currentDigest"] == "sha256:now"
            assert detail["choices"] == ["rebase-reparse", "discard"]

    def test_blockers_are_409_with_explanations(self):
        with patch("app.source_review_routes.db") as mdb:
            r = self._apply(
                mdb,
                error=SourceApplyConflictError(
                    "blocked",
                    {
                        "blockers": [
                            {
                                "code": "REFERENCED_COMPONENT_DELETION",
                                "pointer": "/components/schemas/Toy",
                                "message": "Schema 'Toy' is deleted but referenced.",
                                "referencedBy": ["/paths/~1pets/get"],
                            }
                        ]
                    },
                ),
            )
            assert r.status_code == 409
            detail = r.json()["detail"]
            assert detail["code"] == "SOURCE_APPLY_BLOCKED"
            assert detail["blockers"][0]["referencedBy"] == ["/paths/~1pets/get"]

    def test_lossy_apply_is_422(self):
        with patch("app.source_review_routes.db") as mdb:
            r = self._apply(
                mdb,
                error=SourceApplyConflictError(
                    "apply_lossy", {"losses": ["/webhooks"], "valueChanges": []}
                ),
            )
            assert r.status_code == 422
            assert r.json()["detail"]["code"] == "SOURCE_APPLY_LOSSY"

    def test_invalid_source_never_reaches_the_transaction(self):
        with patch("app.source_review_routes.db") as mdb:
            _mock_db(mdb)
            r = client.post(
                f"{_BASE}/source-apply",
                json={
                    "sourceText": "not: [valid",
                    "sourceFormat": "yaml",
                    "baseDigest": "sha256:base",
                    "changeSetDigest": "sha256:cs",
                },
            )
            assert r.status_code == 422
            mdb.apply_source_change_set.assert_not_called()

    def test_successful_apply_reports_revision_and_enrichments(self):
        with patch("app.source_review_routes.db") as mdb:
            r = self._apply(
                mdb,
                result={
                    "applied": True,
                    "resultDigest": "sha256:result",
                    "auditId": "audit-1",
                    "counts": {
                        "additions": 1,
                        "updates": 0,
                        "deletions": 0,
                        "unsupportedPreserved": 0,
                        "total": 1,
                    },
                    "enrichments": ["/components/schemas/Pet/title"],
                    "claimCount": 2,
                },
            )
            assert r.status_code == 200
            body = r.json()
            assert body["applied"] is True
            assert body["resultDigest"] == "sha256:result"
            assert body["auditId"] == "audit-1"
            assert body["counts"]["total"] == 1
            assert body["enrichments"] == ["/components/schemas/Pet/title"]
            call = mdb.apply_source_change_set.call_args
            assert call.kwargs["base_digest"] == "sha256:base"
            assert call.kwargs["change_set_digest_value"] == "sha256:cs"
            assert call.kwargs["source_digest"].startswith("sha256:")

    def test_idempotent_replay_reports_already_applied(self):
        with patch("app.source_review_routes.db") as mdb:
            r = self._apply(
                mdb,
                result={
                    "applied": False,
                    "alreadyApplied": True,
                    "resultDigest": "sha256:result",
                    "auditId": "audit-1",
                },
            )
            assert r.status_code == 200
            body = r.json()
            assert body["applied"] is False
            assert body["alreadyApplied"] is True
