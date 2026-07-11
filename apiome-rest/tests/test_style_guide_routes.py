"""Endpoint tests for the style-guide management API (GOV-2.1, #4433).

The DB layer is mocked (patched on ``app.style_guide_routes.db``) so these tests exercise
the route contract: response shapes (camelCase aliases), admin gating, read-only builtin
handling, and the error codes the Control Panel screen keys off.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_MOCK_AUTH = {"tenant_id": "t1", "user_id": "u1", "auth_method": "jwt"}

BUILTIN_ID = "00000000-0000-0000-0000-0000000000a1"
GUIDE_ID = "00000000-0000-0000-0000-0000000000b2"
PROJECT_ID = "00000000-0000-0000-0000-0000000000c3"
NOW = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)


def _override_auth():
    return _MOCK_AUTH


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = _override_auth
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _admin():
    """Mutations require a tenant admin; default every test to an admin caller."""
    with patch("app.style_guide_routes.db.is_user_tenant_admin", return_value=True):
        yield


def _builtin_row(**over):
    row = {
        "id": BUILTIN_ID,
        "name": "Apiome Recommended",
        "description": "The built-in Apiome style guide.",
        "source": "builtin",
        "is_default": True,
        "rule_count": 37,
        "enabled_rule_count": 37,
        "tenant_assigned": False,
        "created_at": NOW,
        "updated_at": NOW,
    }
    row.update(over)
    return row


def _custom_row(**over):
    row = {
        "id": GUIDE_ID,
        "name": "Payments Guide",
        "description": None,
        "source": "custom",
        "is_default": False,
        "rule_count": 12,
        "enabled_rule_count": 9,
        "tenant_assigned": False,
        "created_at": NOW,
        "updated_at": NOW,
    }
    row.update(over)
    return row


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def test_list_returns_guides_with_rollups_and_camel_case():
    assignments = [
        {"guide_id": GUIDE_ID, "project_id": PROJECT_ID, "project_name": "Payments"}
    ]
    with patch("app.style_guide_routes.db.ensure_builtin_style_guide") as ensure, patch(
        "app.style_guide_routes.db.list_style_guides",
        return_value=[_builtin_row(), _custom_row()],
    ), patch(
        "app.style_guide_routes.db.list_style_guide_project_assignments",
        return_value=assignments,
    ):
        r = client.get("/v1/style-guides/acme")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    ensure.assert_called_once_with("t1")

    builtin, custom = body["guides"]
    assert builtin["name"] == "Apiome Recommended"
    assert builtin["source"] == "builtin"
    assert builtin["isDefault"] is True
    assert builtin["enabledRuleCount"] == 37
    assert builtin["ruleCount"] == 37
    assert builtin["projectAssignments"] == []
    assert custom["projectAssignments"] == [
        {"projectId": PROJECT_ID, "projectName": "Payments"}
    ]
    assert custom["tenantAssigned"] is False
    assert "createdAt" in custom and "updatedAt" in custom


def test_list_is_readable_by_non_admin_members():
    with patch(
        "app.style_guide_routes.db.is_user_tenant_admin", return_value=False
    ), patch("app.style_guide_routes.db.ensure_builtin_style_guide"), patch(
        "app.style_guide_routes.db.list_style_guides", return_value=[]
    ), patch(
        "app.style_guide_routes.db.list_style_guide_project_assignments", return_value=[]
    ):
        r = client.get("/v1/style-guides/acme")
    assert r.status_code == 200
    assert r.json() == {"guides": [], "count": 0}


# ---------------------------------------------------------------------------
# Create / duplicate
# ---------------------------------------------------------------------------


def test_create_empty_guide():
    created = _custom_row(rule_count=0, enabled_rule_count=0)
    with patch(
        "app.style_guide_routes.db.create_style_guide", return_value=created
    ) as create:
        r = client.post(
            "/v1/style-guides/acme",
            json={"name": "Payments Guide", "description": "House rules"},
        )
    assert r.status_code == 201
    assert r.json()["name"] == "Payments Guide"
    assert r.json()["ruleCount"] == 0
    create.assert_called_once_with("t1", "Payments Guide", "House rules", None)


def test_create_duplicates_source_guide_rules():
    rules = [{"rule_id": f"r{i}", "enabled": True, "severity": "warning", "custom_def": None} for i in range(5)]
    with patch(
        "app.style_guide_routes.db.get_style_guide_by_id", return_value=_builtin_row()
    ), patch(
        "app.style_guide_routes.db.get_style_guide_rules", return_value=rules
    ), patch(
        "app.style_guide_routes.db.create_style_guide", return_value=_custom_row()
    ) as create:
        r = client.post(
            "/v1/style-guides/acme",
            json={"name": "My Copy", "sourceGuideId": BUILTIN_ID},
        )
    assert r.status_code == 201
    assert r.json()["ruleCount"] == 5
    assert r.json()["enabledRuleCount"] == 5
    create.assert_called_once_with("t1", "My Copy", None, BUILTIN_ID)


def test_create_with_unknown_source_guide_404s():
    with patch("app.style_guide_routes.db.get_style_guide_by_id", return_value=None):
        r = client.post(
            "/v1/style-guides/acme",
            json={"name": "My Copy", "sourceGuideId": GUIDE_ID},
        )
    assert r.status_code == 404


def test_create_name_conflict_409s_with_code():
    with patch(
        "app.style_guide_routes.db.create_style_guide",
        side_effect=psycopg2.IntegrityError(),
    ):
        r = client.post("/v1/style-guides/acme", json={"name": "Payments Guide"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "STYLE_GUIDE_NAME_CONFLICT"


def test_create_blank_name_400s():
    r = client.post("/v1/style-guides/acme", json={"name": "   "})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Update / delete — read-only builtin
# ---------------------------------------------------------------------------


def test_update_builtin_guide_is_read_only():
    with patch(
        "app.style_guide_routes.db.get_style_guide_by_id", return_value=_builtin_row()
    ):
        r = client.patch(
            f"/v1/style-guides/acme/{BUILTIN_ID}", json={"name": "Renamed"}
        )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "STYLE_GUIDE_READ_ONLY"


def test_update_renames_custom_guide():
    renamed = _custom_row(name="Renamed")
    rules = [{"rule_id": "a", "enabled": True, "severity": "info", "custom_def": None}]
    with patch(
        "app.style_guide_routes.db.get_style_guide_by_id", return_value=_custom_row()
    ), patch(
        "app.style_guide_routes.db.update_style_guide", return_value=renamed
    ) as update, patch(
        "app.style_guide_routes.db.get_style_guide_rules", return_value=rules
    ):
        r = client.patch(f"/v1/style-guides/acme/{GUIDE_ID}", json={"name": "Renamed"})
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed"
    # Description untouched when the body omits it.
    update.assert_called_once_with(GUIDE_ID, "t1", "Renamed", None)


def test_delete_builtin_guide_is_read_only():
    with patch(
        "app.style_guide_routes.db.get_style_guide_by_id", return_value=_builtin_row()
    ):
        r = client.delete(f"/v1/style-guides/acme/{BUILTIN_ID}")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "STYLE_GUIDE_READ_ONLY"


def test_delete_custom_guide():
    with patch(
        "app.style_guide_routes.db.get_style_guide_by_id", return_value=_custom_row()
    ), patch("app.style_guide_routes.db.delete_style_guide", return_value=True):
        r = client.delete(f"/v1/style-guides/acme/{GUIDE_ID}")
    assert r.status_code == 200
    assert r.json() == {"status": "deleted", "id": GUIDE_ID}


def test_delete_missing_guide_404s():
    with patch("app.style_guide_routes.db.get_style_guide_by_id", return_value=None):
        r = client.delete(f"/v1/style-guides/acme/{GUIDE_ID}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------


def test_set_tenant_default():
    promoted = _custom_row(is_default=True)
    with patch(
        "app.style_guide_routes.db.set_style_guide_tenant_default", return_value=promoted
    ), patch("app.style_guide_routes.db.get_style_guide_rules", return_value=[]):
        r = client.put(f"/v1/style-guides/acme/{GUIDE_ID}/default")
    assert r.status_code == 200
    assert r.json()["isDefault"] is True
    assert r.json()["tenantAssigned"] is True


def test_set_tenant_default_missing_guide_404s():
    with patch(
        "app.style_guide_routes.db.set_style_guide_tenant_default", return_value=None
    ):
        r = client.put(f"/v1/style-guides/acme/{GUIDE_ID}/default")
    assert r.status_code == 404


def test_assign_project():
    with patch(
        "app.style_guide_routes.db.get_style_guide_by_id", return_value=_custom_row()
    ), patch(
        "app.style_guide_routes.db.assign_style_guide_to_project", return_value=True
    ) as assign:
        r = client.put(
            f"/v1/style-guides/acme/{GUIDE_ID}/assignments/projects/{PROJECT_ID}"
        )
    assert r.status_code == 200
    assert r.json() == {
        "status": "assigned",
        "guideId": GUIDE_ID,
        "projectId": PROJECT_ID,
    }
    assign.assert_called_once_with(GUIDE_ID, "t1", PROJECT_ID)


def test_assign_project_unknown_project_404s():
    with patch(
        "app.style_guide_routes.db.get_style_guide_by_id", return_value=_custom_row()
    ), patch(
        "app.style_guide_routes.db.assign_style_guide_to_project", return_value=False
    ):
        r = client.put(
            f"/v1/style-guides/acme/{GUIDE_ID}/assignments/projects/{PROJECT_ID}"
        )
    assert r.status_code == 404


def test_unassign_project():
    with patch(
        "app.style_guide_routes.db.unassign_style_guide_from_project", return_value=True
    ):
        r = client.delete(f"/v1/style-guides/acme/assignments/projects/{PROJECT_ID}")
    assert r.status_code == 200
    assert r.json() == {"status": "unassigned", "projectId": PROJECT_ID}


def test_unassign_project_without_assignment_404s():
    with patch(
        "app.style_guide_routes.db.unassign_style_guide_from_project", return_value=False
    ):
        r = client.delete(f"/v1/style-guides/acme/assignments/projects/{PROJECT_ID}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Admin gating
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/v1/style-guides/acme", {"name": "X"}),
        ("patch", f"/v1/style-guides/acme/{GUIDE_ID}", {"name": "X"}),
        ("delete", f"/v1/style-guides/acme/{GUIDE_ID}", None),
        ("put", f"/v1/style-guides/acme/{GUIDE_ID}/default", None),
        (
            "put",
            f"/v1/style-guides/acme/{GUIDE_ID}/assignments/projects/{PROJECT_ID}",
            None,
        ),
        ("delete", f"/v1/style-guides/acme/assignments/projects/{PROJECT_ID}", None),
    ],
)
def test_mutations_require_tenant_admin(method, path, body):
    with patch("app.style_guide_routes.db.is_user_tenant_admin", return_value=False):
        kwargs = {"json": body} if body is not None else {}
        r = getattr(client, method)(path, **kwargs)
    assert r.status_code == 403
