"""Preservation-envelope API — DCW-2.1 (private-suite#2352).

Tenant/version scoping (404 over 403 for scope misses), published-revision
immutability, structured non-mutating validation failures, and the audited
transactional replace.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
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

_URL = "/v1/versions/tn/proj/11111111-1111-1111-1111-111111111111/preservation"


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: dict(_MOCK_JWT)
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _mock_db(mdb, *, version=_VERSION_ROW, claims=None):
    """Configure the patched routes db for the happy path."""
    mdb.get_version_by_id.return_value = dict(version) if version else None
    mdb.get_preservation_claims.return_value = claims or []
    mdb.get_classes_for_version.return_value = []
    mdb.replace_preservation_claims.return_value = len(claims or [])


class TestGet:
    def test_scope_miss_is_404(self):
        with patch("app.preservation_routes.db") as mdb:
            _mock_db(mdb, version=None)
            r = client.get(_URL)
            assert r.status_code == 404
            mdb.get_preservation_claims.assert_not_called()

    def test_returns_claims_and_fingerprint_with_exclusions(self):
        rows = [
            {
                "pointer": "/x-sdk-config",
                "payload": {"package": "p"},
                "source_file": "openapi.yaml",
                "source_digest": "sha256:abc",
            }
        ]
        with patch("app.preservation_routes.db") as mdb:
            _mock_db(mdb, claims=rows)
            r = client.get(_URL)
            assert r.status_code == 200
            body = r.json()
            assert body["envelopeVersion"] == "1.0.0"
            assert body["dialect"] == "3.1.0"
            assert body["claims"] == [
                {
                    "pointer": "/x-sdk-config",
                    "value": {"package": "p"},
                    "sourceFile": "openapi.yaml",
                    "sourceDigest": "sha256:abc",
                }
            ]
            assert body["fingerprint"]["lexicalExclusions"] == [
                "comments",
                "anchors",
                "key-order",
                "quoting",
                "whitespace",
                "multi-file-layout",
            ]
            assert len(body["fingerprint"]["fingerprint"]) == 64


class TestPutValidation:
    def test_collision_with_canonical_422_no_mutation(self):
        with patch("app.preservation_routes.db") as mdb:
            _mock_db(mdb)
            # The generated canonical document always carries /openapi.
            r = client.put(
                _URL,
                json={
                    "dialect": "3.1.0",
                    "claims": [{"pointer": "/openapi", "value": "9.9"}],
                },
            )
            assert r.status_code == 422
            detail = r.json()["detail"]
            assert detail["code"] == "PRESERVATION_ENVELOPE_INVALID"
            assert detail["errors"][0]["code"] == "PRESERVATION_POINTER_COLLISION"
            mdb.replace_preservation_claims.assert_not_called()

    def test_unsupported_dialect_422_no_mutation(self):
        with patch("app.preservation_routes.db") as mdb:
            _mock_db(mdb)
            r = client.put(_URL, json={"dialect": "2.0", "claims": []})
            assert r.status_code == 422
            codes = [e["code"] for e in r.json()["detail"]["errors"]]
            assert codes == ["PRESERVATION_DIALECT_UNSUPPORTED"]
            mdb.replace_preservation_claims.assert_not_called()

    def test_duplicate_pointer_422_no_mutation(self):
        with patch("app.preservation_routes.db") as mdb:
            _mock_db(mdb)
            r = client.put(
                _URL,
                json={
                    "dialect": "3.1.0",
                    "claims": [
                        {"pointer": "/x-a", "value": 1},
                        {"pointer": "/x-a", "value": 2},
                    ],
                },
            )
            assert r.status_code == 422
            mdb.replace_preservation_claims.assert_not_called()


class TestPutImmutability:
    def test_published_revision_409_no_mutation(self):
        published = dict(_VERSION_ROW, published=True)
        with patch("app.preservation_routes.db") as mdb:
            _mock_db(mdb, version=published)
            r = client.put(_URL, json={"dialect": "3.1.0", "claims": []})
            assert r.status_code == 409
            assert r.json()["detail"]["code"] == "PUBLISHED_IMMUTABLE"
            mdb.replace_preservation_claims.assert_not_called()

    def test_published_race_in_transaction_409(self):
        # The transaction rechecks published state; a publish that lands between
        # the route check and the transaction still answers 409.
        with patch("app.preservation_routes.db") as mdb:
            _mock_db(mdb)
            mdb.replace_preservation_claims.side_effect = ValueError("published_version")
            r = client.put(
                _URL,
                json={"dialect": "3.1.0", "claims": [{"pointer": "/x-a", "value": 1}]},
            )
            assert r.status_code == 409
            assert r.json()["detail"]["code"] == "PUBLISHED_IMMUTABLE"


class TestPutHappyPath:
    def test_valid_envelope_stored_with_audit_detail(self):
        with patch("app.preservation_routes.db") as mdb:
            _mock_db(mdb)
            r = client.put(
                _URL,
                json={
                    "dialect": "3.1.0",
                    "claims": [
                        {
                            "pointer": "/x-sdk-config",
                            "value": {"package": "p"},
                            "sourceFile": "openapi.yaml",
                            "sourceDigest": "sha256:abc",
                        }
                    ],
                },
            )
            assert r.status_code == 200
            body = r.json()
            assert body["claims"][0]["pointer"] == "/x-sdk-config"
            assert len(body["fingerprint"]["fingerprint"]) == 64
            call = mdb.replace_preservation_claims.call_args
            assert call.args[0] == "t1"
            assert call.args[3] == [
                {
                    "pointer": "/x-sdk-config",
                    "value": {"package": "p"},
                    "source_file": "openapi.yaml",
                    "source_digest": "sha256:abc",
                }
            ]
            assert call.args[4] == "user-a"
            assert call.kwargs["detail"]["dialect"] == "3.1.0"

    def test_empty_claims_clears_envelope(self):
        with patch("app.preservation_routes.db") as mdb:
            _mock_db(mdb)
            r = client.put(_URL, json={"dialect": "3.1.0", "claims": []})
            assert r.status_code == 200
            assert r.json()["claims"] == []
            assert mdb.replace_preservation_claims.call_args.args[3] == []

    def test_scope_miss_is_404(self):
        with patch("app.preservation_routes.db") as mdb:
            _mock_db(mdb, version=None)
            r = client.put(_URL, json={"dialect": "3.1.0", "claims": []})
            assert r.status_code == 404
            mdb.replace_preservation_claims.assert_not_called()

    def test_wrong_project_scope_is_404(self):
        other_project = dict(_VERSION_ROW, project_id="other")
        with patch("app.preservation_routes.db") as mdb:
            _mock_db(mdb, version=other_project)
            r = client.put(_URL, json={"dialect": "3.1.0", "claims": []})
            assert r.status_code == 404
