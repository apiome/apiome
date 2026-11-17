"""Just-in-time SSO provisioning against a live Postgres — EID-1.3 (#5013).

What only the real schema can prove about :func:`app.sso_provisioning.provision_member`: the
membership, its role and its audit row are written together; a repeat sign-in writes nothing more;
a member is never demoted; a full workspace gets no membership but an audit row and one inbox row
per owner, once per person per day; a pending invitation is accepted; a suspended member stays
suspended; nothing is ever written to another workspace; and the members list reports where a
membership came from.

Runs inside one always-rolled-back transaction (the ``tx`` fixture of ``test_usage_index_db``), with
V312, V393 and V394 applied inside it when the database does not have them yet. Skipped when no
database is reachable.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import pytest

from app import sso_provider_store as store
from app import sso_provisioning as provisioning
from tests import test_sso_provider_db as provider_db

tx = provider_db.tx
sso = provider_db.sso

pytestmark = pytest.mark.requires_db


def _user(cursor: Any, email: Optional[str] = None) -> Dict[str, Any]:
    """A fresh account."""
    email = email or f"{uuid.uuid4().hex[:10]}@acme.example"
    cursor.execute(
        "INSERT INTO apiome.users (name, email, password, verified, enabled) "
        "VALUES (%s, %s, '', true, true) RETURNING id::text AS id, email",
        (email.split("@")[0], email),
    )
    return dict(cursor.fetchone())


def _workspace(db, cursor: Any, *, owners: int = 1) -> Dict[str, Any]:
    """A workspace with its built-in roles and ``owners`` active owners."""
    tenant_id = provider_db._workspace(db)
    cursor.execute("SELECT apiome.seed_builtin_roles(%s::uuid)", (tenant_id,))
    owner_ids = []
    for _ in range(owners):
        owner = _user(cursor)
        _member(cursor, tenant_id, owner["id"], role="owner")
        owner_ids.append(owner["id"])
    return {"id": tenant_id, "owners": owner_ids}


def _member(cursor: Any, tenant_id: str, user_id: str, *, role: Optional[str] = None, status: str = "active") -> None:
    cursor.execute(
        "INSERT INTO apiome.tenant_users (tenant_id, user_id, status) VALUES (%s::uuid, %s::uuid, %s)",
        (tenant_id, user_id, status),
    )
    if role:
        cursor.execute(
            """
            INSERT INTO apiome.tenant_user_roles (tenant_id, user_id, role_id)
            SELECT %s::uuid, %s::uuid, id FROM apiome.roles WHERE tenant_id = %s::uuid AND slug = %s
            """,
            (tenant_id, user_id, tenant_id, role),
        )


def _provider(db, tenant_id: str, **extra) -> Dict[str, Any]:
    return provider_db._oidc(db, slug=f"p-{uuid.uuid4().hex[:10]}", tenant_id=tenant_id, enabled=True, **extra)


def _membership(cursor: Any, tenant_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    cursor.execute(
        """
        SELECT tu.status, tu.provisioned_by, r.slug AS role
        FROM apiome.tenant_users tu
        LEFT JOIN apiome.tenant_user_roles tur ON tur.tenant_id = tu.tenant_id AND tur.user_id = tu.user_id
        LEFT JOIN apiome.roles r ON r.id = tur.role_id
        WHERE tu.tenant_id = %s::uuid AND tu.user_id = %s::uuid
        """,
        (tenant_id, user_id),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def _audit(cursor: Any, tenant_id: str) -> List[Dict[str, Any]]:
    cursor.execute(
        "SELECT action, source, target, actor_id::text AS actor_id, detail FROM apiome.access_audit "
        "WHERE tenant_id = %s::uuid AND action LIKE 'member.provision%%' ORDER BY created_at, id",
        (tenant_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def _inbox(cursor: Any, tenant_id: str) -> List[Dict[str, Any]]:
    cursor.execute(
        "SELECT user_id::text AS user_id, type, payload FROM apiome.notifications "
        "WHERE tenant_id = %s::uuid AND type = 'seat_cap_blocked_sso' ORDER BY user_id",
        (tenant_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def test_a_first_sign_in_creates_the_membership_its_role_and_its_audit_row(sso) -> None:
    db, cursor = sso
    workspace = _workspace(db, cursor)
    provider = _provider(db, workspace["id"], default_role_slug="editor")
    user = _user(cursor)

    result = provisioning.provision_member(db, provider=provider, user=user, seat_limit=5)

    assert result == {"outcome": "provisioned", "role_slug": "editor", "role_name": "Editor", "seat_limit": 5}
    assert _membership(cursor, workspace["id"], user["id"]) == {
        "status": "active",
        "provisioned_by": f"sso:{provider['slug']}",
        "role": "editor",
    }
    (row,) = _audit(cursor, workspace["id"])
    assert (row["action"], row["source"], row["target"], row["actor_id"]) == (
        "member.provisioned",
        "sso",
        user["email"],
        user["id"],
    )
    assert row["detail"] == {"user_id": user["id"], "provider": f"sso:{provider['slug']}", "role": "Editor"}


def test_a_repeat_sign_in_writes_nothing_more(sso) -> None:
    db, cursor = sso
    workspace = _workspace(db, cursor)
    provider = _provider(db, workspace["id"])
    user = _user(cursor)
    provisioning.provision_member(db, provider=provider, user=user, seat_limit=5)
    before = _membership(cursor, workspace["id"], user["id"])

    again = provisioning.provision_member(db, provider=provider, user=user, seat_limit=5)

    assert again["outcome"] == "existing" and again["role_slug"] == "viewer"
    assert _membership(cursor, workspace["id"], user["id"]) == before
    assert len(_audit(cursor, workspace["id"])) == 1


def test_owner_is_never_granted_and_no_default_means_viewer(sso) -> None:
    db, cursor = sso
    workspace = _workspace(db, cursor)
    for default in ("owner", None, "no-such-role"):
        provider = _provider(db, workspace["id"], default_role_slug=default)
        user = _user(cursor)
        assert provisioning.provision_member(db, provider=provider, user=user, seat_limit=None)["role_slug"] == "viewer"


def test_an_existing_member_keeps_their_role_and_their_provenance(sso) -> None:
    db, cursor = sso
    workspace = _workspace(db, cursor)
    provider = _provider(db, workspace["id"], default_role_slug="viewer")
    user = _user(cursor)
    _member(cursor, workspace["id"], user["id"], role="admin")

    result = provisioning.provision_member(db, provider=provider, user=user, seat_limit=5)

    assert result["outcome"] == "existing" and result["role_slug"] == "admin"
    assert _membership(cursor, workspace["id"], user["id"]) == {
        "status": "active",
        "provisioned_by": None,
        "role": "admin",
    }
    assert _audit(cursor, workspace["id"]) == []


def test_a_pending_invitation_is_accepted_with_the_invited_role(sso) -> None:
    db, cursor = sso
    workspace = _workspace(db, cursor)
    provider = _provider(db, workspace["id"], default_role_slug="viewer")
    user = _user(cursor)
    _member(cursor, workspace["id"], user["id"], role="editor", status="pending")

    result = provisioning.provision_member(db, provider=provider, user=user, seat_limit=1)  # holds its seat already

    assert result["outcome"] == "activated" and result["role_slug"] == "editor"
    assert _membership(cursor, workspace["id"], user["id"])["status"] == "active"
    (row,) = _audit(cursor, workspace["id"])
    assert row["detail"]["accepted_invitation"] is True


def test_a_suspended_member_stays_suspended(sso) -> None:
    db, cursor = sso
    workspace = _workspace(db, cursor)
    provider = _provider(db, workspace["id"])
    user = _user(cursor)
    _member(cursor, workspace["id"], user["id"], role="viewer", status="suspended")

    assert provisioning.provision_member(db, provider=provider, user=user, seat_limit=5)["outcome"] == "suspended"
    assert _membership(cursor, workspace["id"], user["id"])["status"] == "suspended"
    assert _audit(cursor, workspace["id"]) == []


def test_a_full_workspace_gets_no_membership_but_an_audit_row_and_an_inbox_row_per_owner(sso) -> None:
    db, cursor = sso
    workspace = _workspace(db, cursor, owners=2)
    provider = _provider(db, workspace["id"])
    user = _user(cursor)

    result = provisioning.provision_member(db, provider=provider, user=user, seat_limit=2)  # both seats: the owners

    assert result == {"outcome": "seat-cap-blocked", "role_slug": None, "role_name": None, "seat_limit": 2}
    assert _membership(cursor, workspace["id"], user["id"]) is None
    (row,) = _audit(cursor, workspace["id"])
    assert (row["action"], row["source"], row["target"]) == ("member.provision_blocked", "sso", user["email"])
    assert row["detail"]["reason"] == "license-seats-exhausted" and row["detail"]["seat_limit"] == 2
    inbox = _inbox(cursor, workspace["id"])
    assert sorted(n["user_id"] for n in inbox) == sorted(workspace["owners"])
    assert inbox[0]["payload"]["user_email"] == user["email"]
    assert inbox[0]["payload"]["link"] == "/ade/dashboard/members"


def test_a_blocked_person_trying_again_is_audited_each_time_but_pages_the_owners_once(sso) -> None:
    db, cursor = sso
    workspace = _workspace(db, cursor)
    provider = _provider(db, workspace["id"])
    user = _user(cursor)
    for _ in range(3):
        provisioning.provision_member(db, provider=provider, user=user, seat_limit=1)

    assert len(_audit(cursor, workspace["id"])) == 3
    assert len(_inbox(cursor, workspace["id"])) == 1

    # Someone else being blocked is its own news.
    provisioning.provision_member(db, provider=provider, user=_user(cursor), seat_limit=1)
    assert len(_inbox(cursor, workspace["id"])) == 2


def test_a_suspended_member_frees_a_seat_and_no_limit_means_no_cap(sso) -> None:
    db, cursor = sso
    workspace = _workspace(db, cursor)
    provider = _provider(db, workspace["id"])
    parked = _user(cursor)
    _member(cursor, workspace["id"], parked["id"], status="suspended")

    assert provisioning.provision_member(db, provider=provider, user=_user(cursor), seat_limit=2)["outcome"] == (
        "provisioned"
    )
    assert provisioning.provision_member(db, provider=provider, user=_user(cursor), seat_limit=2)["outcome"] == (
        "seat-cap-blocked"
    )
    assert provisioning.provision_member(db, provider=provider, user=_user(cursor), seat_limit=None)["outcome"] == (
        "provisioned"
    )


def test_provisioning_never_touches_another_workspace(sso) -> None:
    db, cursor = sso
    acme = _workspace(db, cursor)
    globex = _workspace(db, cursor)
    provider = _provider(db, acme["id"])
    user = _user(cursor)

    provisioning.provision_member(db, provider=provider, user=user, seat_limit=5)

    assert _membership(cursor, acme["id"], user["id"]) is not None
    assert _membership(cursor, globex["id"], user["id"]) is None
    assert _audit(cursor, globex["id"]) == [] and _inbox(cursor, globex["id"]) == []


def test_one_person_can_be_provisioned_into_two_workspaces_through_their_own_providers(sso) -> None:
    db, cursor = sso
    acme = _workspace(db, cursor)
    globex = _workspace(db, cursor)
    user = _user(cursor)

    provisioning.provision_member(db, provider=_provider(db, acme["id"]), user=user, seat_limit=5)
    provisioning.provision_member(
        db, provider=_provider(db, globex["id"], default_role_slug="editor"), user=user, seat_limit=5
    )

    assert _membership(cursor, acme["id"], user["id"])["role"] == "viewer"
    assert _membership(cursor, globex["id"], user["id"])["role"] == "editor"


def test_a_workspace_that_is_gone_provisions_nobody(sso) -> None:
    db, cursor = sso
    workspace = _workspace(db, cursor)
    provider = _provider(db, workspace["id"])
    cursor.execute("UPDATE apiome.tenants SET deleted_at = now() WHERE id = %s::uuid", (workspace["id"],))
    user = _user(cursor)

    with pytest.raises(LookupError):
        provisioning.provision_member(db, provider=provider, user=user, seat_limit=5)
    assert _membership(cursor, workspace["id"], user["id"]) is None


def test_the_route_reads_find_live_rows_and_the_identity(sso) -> None:
    db, cursor = sso
    workspace = _workspace(db, cursor)
    provider = _provider(db, workspace["id"])
    user = _user(cursor)

    assert provisioning.get_tenant(db, workspace["id"])["id"] == workspace["id"]
    assert provisioning.get_sso_user(db, user["id"])["email"] == user["email"]
    assert provisioning.user_has_identity(db, user["id"], provider["slug"]) is False
    cursor.execute(
        "INSERT INTO apiome.external_auth_providers (user_id, provider, provider_user_id) VALUES (%s, %s, %s)",
        (user["id"], f"sso:{provider['slug']}", f"sub-{uuid.uuid4().hex[:8]}"),
    )
    assert provisioning.user_has_identity(db, user["id"], provider["slug"]) is True

    cursor.execute("UPDATE apiome.users SET deleted_at = now() WHERE id = %s::uuid", (user["id"],))
    assert provisioning.get_sso_user(db, user["id"]) is None


def test_the_members_list_says_where_a_membership_came_from(sso) -> None:
    db, cursor = sso
    workspace = _workspace(db, cursor)
    provider = _provider(db, workspace["id"])
    user = _user(cursor)
    provisioning.provision_member(db, provider=provider, user=user, seat_limit=5)

    members = {row["user_id"]: row for row in db.list_members(workspace["id"])}

    assert members[user["id"]]["provisioned_by"] == f"sso:{provider['slug']}"
    assert members[user["id"]]["provisioned_by_label"] == provider["display_name"]
    owner = members[workspace["owners"][0]]
    assert owner["provisioned_by"] is None and owner["provisioned_by_label"] is None

    # The provider is removed: the provenance stays, its name is gone.
    store.delete_provider(db, provider["id"])
    after = {row["user_id"]: row for row in db.list_members(workspace["id"])}
    assert after[user["id"]]["provisioned_by"] == f"sso:{provider['slug']}"
    assert after[user["id"]]["provisioned_by_label"] is None


def test_a_provider_without_a_workspace_is_never_routable(sso) -> None:
    db, cursor = sso
    workspace = _workspace(db, cursor)
    provider = _provider(db, workspace["id"])
    store.add_domain(db, provider["id"], f"{uuid.uuid4().hex[:8]}.example", token="t")
    domain = store.list_domains(db, provider["id"])[0]["domain"]
    store.verify_domain(db, provider["id"], domain, actor="admin")
    assert any(row["slug"] == provider["slug"] for row in store.list_routable_with_secrets(db))
    assert all(row["tenant_id"] for row in store.list_routable_with_secrets(db))
