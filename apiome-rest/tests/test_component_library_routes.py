"""Component-library API — DCW-3.1 (private-suite#2353).

Tenant/scope isolation (404 over 403 for scope misses), the TYPES/VERSIONS
permission matrix, structured non-mutating validation failures, lifecycle
conflicts (immutable published revisions, no-unsafe-downgrade, in-use
blockers, published project versions), and the deterministic materialization
preview.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.database import ComponentLibraryConflictError
from app.main import app

client = TestClient(app)

_MOCK_JWT = {"tenant_id": "t1", "user_id": "user-a", "auth_method": "jwt"}

COMPONENT_ID = "11111111-1111-4111-8111-111111111111"
REVISION_ID = "22222222-2222-4222-8222-222222222222"
VERSION_ID = "33333333-3333-4333-8333-333333333333"

_BASE = "/v1/component-library/tn"
_COMPONENTS = f"{_BASE}/components"
_PINS = f"{_BASE}/projects/proj/versions/{VERSION_ID}/pins"

_COMPONENT_ROW = {
    "id": COMPONENT_ID,
    "name": "PageParam",
    "kind": "parameter",
    "description": None,
    "owner_id": None,
}

_VERSION_ROW = {"id": VERSION_ID, "project_id": "proj", "published": False}

_CREATE_BODY = {
    "name": "PageParam",
    "kind": "parameter",
    "initialRevision": {"revision": "0.1.0", "payload": {"name": "page", "in": "query"}},
}


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: dict(_MOCK_JWT)
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _grant(mdb, allowed=True):
    """Wire the permission plane on the patched routes db."""
    mdb.user_has_permission.return_value = allowed


class TestAuthorizationMatrix:
    def test_write_requires_permission_403(self):
        with patch("app.component_library_routes.db") as mdb:
            _grant(mdb, allowed=False)
            r = client.post(_COMPONENTS, json=_CREATE_BODY)
            assert r.status_code == 403
            mdb.create_operational_component.assert_not_called()

    def test_publish_requires_types_publish(self):
        with patch("app.component_library_routes.db") as mdb:
            _grant(mdb, allowed=False)
            r = client.post(
                f"{_COMPONENTS}/{COMPONENT_ID}/revisions/{REVISION_ID}/publish"
            )
            assert r.status_code == 403
            mdb.publish_component_revision.assert_not_called()

    def test_pin_write_requires_versions_edit(self):
        with patch("app.component_library_routes.db") as mdb:
            _grant(mdb, allowed=False)
            r = client.post(_PINS, json={"componentRevisionId": REVISION_ID})
            assert r.status_code == 403
            mdb.create_version_component_pin.assert_not_called()

    def test_cross_tenant_component_reads_as_404(self):
        with patch("app.component_library_routes.db") as mdb:
            mdb.get_operational_component.return_value = None
            r = client.get(f"{_COMPONENTS}/{COMPONENT_ID}")
            assert r.status_code == 404

    def test_cross_tenant_version_reads_as_404(self):
        with patch("app.component_library_routes.db") as mdb:
            mdb.get_version_by_id.return_value = None
            r = client.get(_PINS)
            assert r.status_code == 404
            mdb.get_component_pins_for_version.assert_not_called()


class TestComponents:
    def test_list_components(self):
        with patch("app.component_library_routes.db") as mdb:
            mdb.list_operational_components.return_value = [
                dict(
                    _COMPONENT_ROW,
                    revision_count=2,
                    published_count=1,
                    head_revision="1.0.0",
                )
            ]
            r = client.get(_COMPONENTS)
            assert r.status_code == 200
            body = r.json()["components"][0]
            assert body["name"] == "PageParam"
            assert body["headRevision"] == "1.0.0"

    def test_create_component_201(self):
        with patch("app.component_library_routes.db") as mdb:
            _grant(mdb)
            mdb.create_operational_component.return_value = {
                "componentId": COMPONENT_ID,
                "revisionId": REVISION_ID,
            }
            r = client.post(_COMPONENTS, json=_CREATE_BODY)
            assert r.status_code == 201
            assert r.json() == {
                "componentId": COMPONENT_ID,
                "revisionId": REVISION_ID,
            }

    def test_invalid_payload_422_no_mutation(self):
        with patch("app.component_library_routes.db") as mdb:
            _grant(mdb)
            bad = dict(_CREATE_BODY, initialRevision={"revision": "0.1.0", "payload": {}})
            r = client.post(_COMPONENTS, json=bad)
            assert r.status_code == 422
            detail = r.json()["detail"]
            assert detail["code"] == "COMPONENT_PAYLOAD_INVALID"
            codes = [e["code"] for e in detail["errors"]]
            assert "PARAMETER_NAME_REQUIRED" in codes
            mdb.create_operational_component.assert_not_called()

    def test_invalid_name_422(self):
        with patch("app.component_library_routes.db") as mdb:
            _grant(mdb)
            r = client.post(_COMPONENTS, json=dict(_CREATE_BODY, name="1 bad name"))
            assert r.status_code == 422
            assert r.json()["detail"]["code"] == "COMPONENT_NAME_INVALID"
            mdb.create_operational_component.assert_not_called()

    def test_invalid_semver_422(self):
        with patch("app.component_library_routes.db") as mdb:
            _grant(mdb)
            bad = dict(
                _CREATE_BODY,
                initialRevision={"revision": "one", "payload": {"name": "p", "in": "query"}},
            )
            r = client.post(_COMPONENTS, json=bad)
            assert r.status_code == 422
            assert r.json()["detail"]["code"] == "REVISION_SEMVER_INVALID"

    def test_duplicate_component_409(self):
        with patch("app.component_library_routes.db") as mdb:
            _grant(mdb)
            mdb.create_operational_component.side_effect = ComponentLibraryConflictError(
                "duplicate_component", {"name": "PageParam"}
            )
            r = client.post(_COMPONENTS, json=_CREATE_BODY)
            assert r.status_code == 409
            assert r.json()["detail"]["code"] == "DUPLICATE_COMPONENT"

    def test_delete_in_use_component_409(self):
        with patch("app.component_library_routes.db") as mdb:
            _grant(mdb)
            mdb.delete_operational_component.side_effect = ComponentLibraryConflictError(
                "component_in_use", {"pinCount": 3}
            )
            r = client.delete(f"{_COMPONENTS}/{COMPONENT_ID}")
            assert r.status_code == 409
            detail = r.json()["detail"]
            assert detail["code"] == "COMPONENT_IN_USE"
            assert detail["pinCount"] == 3


class TestRevisionLifecycle:
    def test_update_published_revision_409(self):
        with patch("app.component_library_routes.db") as mdb:
            _grant(mdb)
            mdb.get_operational_component.return_value = dict(_COMPONENT_ROW)
            mdb.update_component_revision.side_effect = ComponentLibraryConflictError(
                "published_immutable", {"revision": "1.0.0"}
            )
            r = client.put(
                f"{_COMPONENTS}/{COMPONENT_ID}/revisions/{REVISION_ID}",
                json={"payload": {"name": "page", "in": "query"}},
            )
            assert r.status_code == 409
            assert r.json()["detail"]["code"] == "PUBLISHED_IMMUTABLE"

    def test_publish_downgrade_409_names_head(self):
        with patch("app.component_library_routes.db") as mdb:
            _grant(mdb)
            mdb.publish_component_revision.side_effect = ComponentLibraryConflictError(
                "revision_downgrade", {"revision": "0.9.0", "headRevision": "1.0.0"}
            )
            r = client.post(
                f"{_COMPONENTS}/{COMPONENT_ID}/revisions/{REVISION_ID}/publish"
            )
            assert r.status_code == 409
            detail = r.json()["detail"]
            assert detail["code"] == "REVISION_DOWNGRADE"
            assert detail["headRevision"] == "1.0.0"

    def test_publish_success(self):
        with patch("app.component_library_routes.db") as mdb:
            _grant(mdb)
            mdb.publish_component_revision.return_value = {
                "published": True,
                "alreadyPublished": False,
                "revision": "1.1.0",
            }
            r = client.post(
                f"{_COMPONENTS}/{COMPONENT_ID}/revisions/{REVISION_ID}/publish"
            )
            assert r.status_code == 200
            assert r.json() == {
                "published": True,
                "alreadyPublished": False,
                "revision": "1.1.0",
            }

    def test_schema_kind_requires_registry_pin_422(self):
        with patch("app.component_library_routes.db") as mdb:
            _grant(mdb)
            mdb.get_operational_component.return_value = dict(
                _COMPONENT_ROW, kind="schema"
            )
            mdb.create_component_revision.side_effect = ComponentLibraryConflictError(
                "schema_ref_required"
            )
            r = client.post(
                f"{_COMPONENTS}/{COMPONENT_ID}/revisions",
                json={"revision": "1.0.0"},
            )
            assert r.status_code == 422
            assert r.json()["detail"]["code"] == "SCHEMA_REF_REQUIRED"


class TestPins:
    def test_pin_unpublished_revision_409(self):
        with patch("app.component_library_routes.db") as mdb:
            _grant(mdb)
            mdb.get_version_by_id.return_value = dict(_VERSION_ROW)
            mdb.create_version_component_pin.side_effect = ComponentLibraryConflictError(
                "revision_not_published", {"revision": "1.1.0"}
            )
            r = client.post(_PINS, json={"componentRevisionId": REVISION_ID})
            assert r.status_code == 409
            assert r.json()["detail"]["code"] == "REVISION_NOT_PUBLISHED"

    def test_pin_published_version_409(self):
        with patch("app.component_library_routes.db") as mdb:
            _grant(mdb)
            mdb.get_version_by_id.return_value = dict(_VERSION_ROW)
            mdb.create_version_component_pin.side_effect = ComponentLibraryConflictError(
                "published_version"
            )
            r = client.post(_PINS, json={"componentRevisionId": REVISION_ID})
            assert r.status_code == 409
            assert r.json()["detail"]["code"] == "PUBLISHED_VERSION"

    def test_pin_success_lists_pin(self):
        with patch("app.component_library_routes.db") as mdb:
            _grant(mdb)
            mdb.get_version_by_id.return_value = dict(_VERSION_ROW)
            mdb.create_version_component_pin.return_value = {"pinId": "pin-1"}
            r = client.post(
                _PINS,
                json={"componentRevisionId": REVISION_ID, "localName": "Page"},
            )
            assert r.status_code == 201
            assert r.json() == {"pinId": "pin-1"}

            mdb.get_component_pins_for_version.return_value = [
                {
                    "id": "pin-1",
                    "component_id": COMPONENT_ID,
                    "component_name": "PageParam",
                    "kind": "parameter",
                    "revision_id": REVISION_ID,
                    "revision": "1.0.0",
                    "payload_digest": "sha256:abc",
                    "local_name": "Page",
                }
            ]
            r = client.get(_PINS)
            assert r.status_code == 200
            assert r.json()["pins"][0] == {
                "id": "pin-1",
                "componentId": COMPONENT_ID,
                "componentName": "PageParam",
                "kind": "parameter",
                "revisionId": REVISION_ID,
                "revision": "1.0.0",
                "payloadDigest": "sha256:abc",
                "localName": "Page",
            }

    def test_invalid_local_name_422(self):
        with patch("app.component_library_routes.db") as mdb:
            _grant(mdb)
            mdb.get_version_by_id.return_value = dict(_VERSION_ROW)
            r = client.post(
                _PINS,
                json={"componentRevisionId": REVISION_ID, "localName": "bad name"},
            )
            assert r.status_code == 422
            mdb.create_version_component_pin.assert_not_called()


class TestMaterializationPreview:
    def test_preview_reports_deterministic_collisions(self):
        with patch("app.component_library_routes.db") as mdb:
            version = dict(
                _VERSION_ROW,
                project_slug="proj",
                version_id="1.0.0",
                metadata=None,
                project_metadata=None,
                project_description=None,
            )
            mdb.get_version_by_id.return_value = version
            mdb.get_classes_for_version.return_value = [
                {"id": "cls-1", "name": "Pet", "description": None, "schema": "{}"}
            ]
            mdb.get_properties_for_class.return_value = []
            mdb.get_materializable_pins_for_version.return_value = [
                {
                    "kind": "schema",
                    "component_name": "Pet",
                    "local_name": None,
                    "revision": "1.0.0",
                    "payload": {"type": "string"},
                    "component_id": COMPONENT_ID,
                    "revision_id": REVISION_ID,
                }
            ]
            r = client.get(f"{_BASE}/projects/proj/versions/{VERSION_ID}/materialization")
            assert r.status_code == 200
            body = r.json()
            assert body["includeOrigin"] is True
            # The local Pet schema wins; the library Pet gets Pet_2.
            assert body["entries"][0]["requestedName"] == "Pet"
            assert body["entries"][0]["name"] == "Pet_2"
            assert body["entries"][0]["collided"] is True
            assert body["collisions"] == body["entries"]

    def test_preview_never_mutates(self):
        with patch("app.component_library_routes.db") as mdb:
            version = dict(
                _VERSION_ROW,
                project_slug="proj",
                version_id="1.0.0",
                metadata=None,
                project_metadata=None,
                project_description=None,
            )
            mdb.get_version_by_id.return_value = version
            mdb.get_classes_for_version.return_value = []
            mdb.get_materializable_pins_for_version.return_value = []
            r = client.get(
                f"{_BASE}/projects/proj/versions/{VERSION_ID}/materialization",
                params={"includeOrigin": "false"},
            )
            assert r.status_code == 200
            assert r.json() == {"includeOrigin": False, "entries": [], "collisions": []}
            mdb.create_version_component_pin.assert_not_called()
            mdb.delete_version_component_pin.assert_not_called()
