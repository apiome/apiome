"""Just-in-time provisioning for enterprise SSO — EID-1.3 (#5013).

A workspace's identity provider (``sso_provider``, V312) belongs to that workspace. The first time a
person signs in through it, :func:`provision_member` makes them a member of the workspace with the
provider's default role. apiome-ui calls it on every SSO sign-in through the service-token-gated
``POST /v1/tenants/{t}/sso/providers/{id}/provision`` (:mod:`app.tenant_sso_routes`); it is
idempotent on ``(workspace, user)``, so a repeat sign-in changes nothing.

What one call decides, by the membership the user already holds:

=================  =====================  ===========================================================
Membership         Outcome                What is written
=================  =====================  ===========================================================
none, seat free    ``provisioned``        an ``active`` membership with ``provisioned_by =
                                          sso:<slug>``, the default role, and ``member.provisioned``
                                          in the access audit
none, seats full   ``seat-cap-blocked``   no membership; ``member.provision_blocked`` in the access
                                          audit and a ``seat_cap_blocked_sso`` inbox row for every
                                          owner (once per person per 24 hours)
``pending``        ``activated``          the invitation becomes ``active``; the invited role is kept
``active``         ``existing``           nothing — the member keeps their role (never demoted)
``suspended``      ``suspended``          nothing — reinstating a member is an administrator's call
=================  =====================  ===========================================================

**Seats.** The same accounting as the invite path (:mod:`app.license_capacity`): ``active`` and
``pending`` members hold a seat, suspended ones do not. The workspace row is locked for the length
of the transaction, so two first sign-ins racing for the last seat cannot both take it.

**Roles.** The provider's ``default_role_slug`` when the workspace still has that role, otherwise
``viewer``. ``owner`` is never granted by signing in, whatever the provider row says.

**One workspace.** Every statement is scoped to the provider's own ``tenant_id``; there is no
argument through which a provider could add a member anywhere else.

The membership, its role, the audit row and the inbox rows commit together or not at all.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from . import authz_cache
from .notification_fanout import NotificationDraft
from .tenant_admins import tenant_admin_ids
from .notifications import MAX_RECIPIENTS, TYPE_SEAT_CAP_BLOCKED_SSO

__all__ = [
    "AUDIT_MEMBER_PROVISIONED",
    "AUDIT_MEMBER_PROVISION_BLOCKED",
    "AUDIT_SOURCE_SSO",
    "FALLBACK_ROLE_SLUG",
    "MEMBERS_LINK",
    "OUTCOME_ACTIVATED",
    "OUTCOME_EXISTING",
    "OUTCOME_PROVISIONED",
    "OUTCOME_SEAT_CAP_BLOCKED",
    "OUTCOME_SUSPENDED",
    "OUTCOMES",
    "blocked_notification_drafts",
    "choose_role",
    "get_sso_user",
    "get_tenant",
    "provision_member",
    "provisioned_by",
    "user_has_identity",
]

#: The membership was created by this call.
OUTCOME_PROVISIONED = "provisioned"
#: A pending invitation was accepted by signing in.
OUTCOME_ACTIVATED = "activated"
#: The user was already an active member; nothing changed.
OUTCOME_EXISTING = "existing"
#: The user's membership is suspended; nothing changed.
OUTCOME_SUSPENDED = "suspended"
#: Every licensed seat is taken; no membership was created.
OUTCOME_SEAT_CAP_BLOCKED = "seat-cap-blocked"

OUTCOMES = (
    OUTCOME_PROVISIONED,
    OUTCOME_ACTIVATED,
    OUTCOME_EXISTING,
    OUTCOME_SUSPENDED,
    OUTCOME_SEAT_CAP_BLOCKED,
)

#: Access-audit actions this module writes, both with source :data:`AUDIT_SOURCE_SSO`.
AUDIT_MEMBER_PROVISIONED = "member.provisioned"
AUDIT_MEMBER_PROVISION_BLOCKED = "member.provision_blocked"
AUDIT_SOURCE_SSO = "sso"

#: The role a provisioned member receives when the provider names none, or one that is gone.
FALLBACK_ROLE_SLUG = "viewer"

#: The role nobody receives by signing in.
_OWNER_ROLE_SLUG = "owner"

#: Where a ``seat_cap_blocked_sso`` notification sends its reader.
MEMBERS_LINK = "/ade/dashboard/members"

#: A blocked person signing in again does not page the owners again inside this window.
_NOTIFY_WINDOW_HOURS = 24


def provisioned_by(slug: str) -> str:
    """The ``tenant_users.provisioned_by`` value for a provider: ``sso:<slug>``."""
    return f"sso:{slug}"


def choose_role(roles: List[Mapping[str, Any]], default_role_slug: Optional[str]) -> Optional[Mapping[str, Any]]:
    """Pick the role a newly provisioned member receives.

    Args:
        roles: The workspace's roles (``id``, ``slug``, ``name``).
        default_role_slug: The provider's configured default, if any.

    Returns:
        The provider's default role when the workspace has it and it is not ``owner``; otherwise
        the workspace's ``viewer`` role; ``None`` when the workspace has neither (the member then
        holds no explicit role).
    """
    by_slug = {str(role["slug"]): role for role in roles}
    wanted = (default_role_slug or "").strip()
    if wanted and wanted != _OWNER_ROLE_SLUG and wanted in by_slug:
        return by_slug[wanted]
    return by_slug.get(FALLBACK_ROLE_SLUG)


def blocked_notification_drafts(
    owner_ids: List[str],
    *,
    user_id: str,
    user_email: str,
    provider: Mapping[str, Any],
    seat_limit: int,
) -> List[NotificationDraft]:
    """The inbox rows a blocked sign-in sends: one per owner, never to the blocked person.

    Args:
        owner_ids: The workspace's owners and tenant administrators.
        user_id: The person who could not be given a membership.
        user_email: Their email, for the sentence.
        provider: The provider row (``slug``, ``display_name``).
        seat_limit: The workspace's licensed member seats.

    Returns:
        At most :data:`app.notifications.MAX_RECIPIENTS` drafts.
    """
    payload = {
        "summary": (
            f"{user_email} signed in through {provider['display_name']} but was not added: "
            f"all {seat_limit} member seats are in use."
        ),
        "link": MEMBERS_LINK,
        "user_id": user_id,
        "user_email": user_email,
        "provider_slug": provider["slug"],
        "provider_name": provider["display_name"],
        "seat_limit": seat_limit,
    }
    recipients = [owner for owner in dict.fromkeys(owner_ids) if owner and owner != user_id][:MAX_RECIPIENTS]
    return [
        NotificationDraft(user_id=owner, type=TYPE_SEAT_CAP_BLOCKED_SSO, payload=dict(payload), actor_id=user_id)
        for owner in recipients
    ]


# ---------------------------------------------------------------------------
# Reads the route needs before it provisions
# ---------------------------------------------------------------------------


def get_tenant(db, tenant_id: str) -> Optional[Dict[str, Any]]:
    """A live workspace's ``id``, ``slug`` and ``name``, or ``None``."""
    rows = db.execute_query(
        "SELECT id::text AS id, slug, name FROM apiome.tenants WHERE id = %s::uuid AND deleted_at IS NULL",
        (tenant_id,),
    )
    return dict(rows[0]) if rows else None


def get_sso_user(db, user_id: str) -> Optional[Dict[str, Any]]:
    """A live account's ``id``, ``email`` and ``name``, or ``None`` for a deleted or unknown one."""
    rows = db.execute_query(
        "SELECT id::text AS id, email, name FROM apiome.users WHERE id = %s::uuid AND deleted_at IS NULL",
        (user_id,),
    )
    return dict(rows[0]) if rows else None


def user_has_identity(db, user_id: str, slug: str) -> bool:
    """Whether the account holds this provider's identity (``external_auth_providers``).

    Only a person who has actually signed in through the provider is provisioned by it, so the
    service token alone cannot be used to add an arbitrary account to a workspace.
    """
    rows = db.execute_query(
        "SELECT 1 FROM apiome.external_auth_providers WHERE user_id = %s::uuid AND provider = %s LIMIT 1",
        (user_id, provisioned_by(slug)),
    )
    return bool(rows)


# ---------------------------------------------------------------------------
# The write
# ---------------------------------------------------------------------------


def provision_member(
    db,
    *,
    provider: Mapping[str, Any],
    user: Mapping[str, Any],
    seat_limit: Optional[int],
) -> Dict[str, Any]:
    """Make ``user`` a member of the provider's workspace, or say why not — in one transaction.

    Args:
        db: The database.
        provider: The provider row (``id``, ``slug``, ``display_name``, ``tenant_id``,
            ``default_role_slug``). Its ``tenant_id`` is the only workspace touched.
        user: The signed-in account (``id``, ``email``).
        seat_limit: The workspace's licensed member seats, or ``None`` when seat enforcement is
            switched off.

    Returns:
        ``{"outcome", "role_slug", "role_name", "seat_limit"}`` — ``outcome`` one of
        :data:`OUTCOMES`; the role is the member's role after the call (``None`` when they hold
        none, and for ``seat-cap-blocked``).

    Raises:
        LookupError: The provider's workspace no longer exists.
    """
    tenant_id = str(provider["tenant_id"])
    user_id = str(user["id"])
    email = str(user.get("email") or "")
    source = provisioned_by(str(provider["slug"]))

    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            # Serialize provisioning per workspace: the seat count below must not race.
            cursor.execute(
                "SELECT id FROM apiome.tenants WHERE id = %s::uuid AND deleted_at IS NULL FOR UPDATE",
                (tenant_id,),
            )
            if cursor.fetchone() is None:
                raise LookupError("workspace not found")

            cursor.execute(
                "SELECT status FROM apiome.tenant_users WHERE tenant_id = %s::uuid AND user_id = %s::uuid",
                (tenant_id, user_id),
            )
            membership = cursor.fetchone()

            if membership is not None:
                status = str(membership["status"] or "active")
                outcome = OUTCOME_SUSPENDED if status == "suspended" else OUTCOME_EXISTING
                if status == "pending":
                    cursor.execute(
                        """
                        UPDATE apiome.tenant_users SET status = 'active', updated_at = CURRENT_TIMESTAMP
                        WHERE tenant_id = %s::uuid AND user_id = %s::uuid AND status = 'pending'
                        """,
                        (tenant_id, user_id),
                    )
                    outcome = OUTCOME_ACTIVATED
                    db._append_access_audit(
                        cursor,
                        tenant_id=tenant_id,
                        action=AUDIT_MEMBER_PROVISIONED,
                        actor_id=user_id,
                        actor_label=email or None,
                        target=email or user_id,
                        source=AUDIT_SOURCE_SSO,
                        detail={"user_id": user_id, "provider": source, "accepted_invitation": True},
                    )
                role = _current_role(cursor, tenant_id, user_id)
                conn.commit()
                return _result(outcome, role, seat_limit)

            if seat_limit is not None and _seats_in_use(cursor, tenant_id) >= seat_limit:
                db._append_access_audit(
                    cursor,
                    tenant_id=tenant_id,
                    action=AUDIT_MEMBER_PROVISION_BLOCKED,
                    actor_id=user_id,
                    actor_label=email or None,
                    target=email or user_id,
                    source=AUDIT_SOURCE_SSO,
                    detail={
                        "user_id": user_id,
                        "provider": source,
                        "reason": "license-seats-exhausted",
                        "seat_limit": seat_limit,
                    },
                )
                if not _recently_notified(cursor, tenant_id, user_id):
                    drafts = blocked_notification_drafts(
                        _owner_ids(cursor, tenant_id),
                        user_id=user_id,
                        user_email=email or user_id,
                        provider=provider,
                        seat_limit=seat_limit,
                    )
                    db._insert_notifications(cursor, tenant_id=tenant_id, notify=lambda _produced: drafts)
                conn.commit()
                return _result(OUTCOME_SEAT_CAP_BLOCKED, None, seat_limit)

            cursor.execute(
                """
                INSERT INTO apiome.tenant_users (tenant_id, user_id, status, provisioned_by)
                VALUES (%s::uuid, %s::uuid, 'active', %s)
                """,
                (tenant_id, user_id, source),
            )
            cursor.execute("SELECT apiome.seed_builtin_roles(%s::uuid)", (tenant_id,))
            cursor.execute(
                "SELECT id::text AS id, slug, name FROM apiome.roles WHERE tenant_id = %s::uuid",
                (tenant_id,),
            )
            role = choose_role([dict(row) for row in cursor.fetchall()], provider.get("default_role_slug"))
            if role is not None:
                cursor.execute(
                    """
                    INSERT INTO apiome.tenant_user_roles (tenant_id, user_id, role_id)
                    VALUES (%s::uuid, %s::uuid, %s::uuid)
                    ON CONFLICT (tenant_id, user_id) DO UPDATE SET role_id = EXCLUDED.role_id
                    """,
                    (tenant_id, user_id, role["id"]),
                )
            db._append_access_audit(
                cursor,
                tenant_id=tenant_id,
                action=AUDIT_MEMBER_PROVISIONED,
                actor_id=user_id,
                actor_label=email or None,
                target=email or user_id,
                source=AUDIT_SOURCE_SSO,
                detail={
                    "user_id": user_id,
                    "provider": source,
                    "role": role["name"] if role is not None else None,
                },
            )
        conn.commit()
        return _result(OUTCOME_PROVISIONED, role, seat_limit)
    except Exception:
        conn.rollback()
        raise
    finally:
        # A membership may have been created or activated: the next request must see it
        # (DBP-1.3, #7186).
        authz_cache.invalidate_member(tenant_id, user_id)


def _result(outcome: str, role: Optional[Mapping[str, Any]], seat_limit: Optional[int]) -> Dict[str, Any]:
    """Shape :func:`provision_member`'s return value."""
    return {
        "outcome": outcome,
        "role_slug": role["slug"] if role is not None else None,
        "role_name": role["name"] if role is not None else None,
        "seat_limit": seat_limit,
    }


def _current_role(cursor: Any, tenant_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """The role a member holds now (``slug``, ``name``), or ``None``."""
    cursor.execute(
        """
        SELECT r.slug, r.name
        FROM apiome.tenant_user_roles tur
        JOIN apiome.roles r ON r.id = tur.role_id
        WHERE tur.tenant_id = %s::uuid AND tur.user_id = %s::uuid
        """,
        (tenant_id, user_id),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def _seats_in_use(cursor: Any, tenant_id: str) -> int:
    """Seats taken, by the rule of :meth:`app.database.Database.count_member_seats_in_use`."""
    cursor.execute(
        """
        SELECT COUNT(*)::int AS c
        FROM apiome.tenant_users tu
        JOIN apiome.users u ON u.id = tu.user_id
        WHERE tu.tenant_id = %s::uuid AND tu.status <> 'suspended' AND u.deleted_at IS NULL
        """,
        (tenant_id,),
    )
    row = cursor.fetchone()
    return int(row["c"]) if row and row.get("c") is not None else 0


def _owner_ids(cursor: Any, tenant_id: str) -> List[str]:
    """The workspace's active owners and tenant administrators — who a blocked sign-in is told to."""
    return tenant_admin_ids(cursor, tenant_id)


def _recently_notified(cursor: Any, tenant_id: str, user_id: str) -> bool:
    """Whether the owners were already told about this person within the notify window."""
    cursor.execute(
        """
        SELECT 1 FROM apiome.notifications
        WHERE tenant_id = %s::uuid AND type = %s AND payload->>'user_id' = %s
          AND created_at > CURRENT_TIMESTAMP - make_interval(hours => %s)
        LIMIT 1
        """,
        (tenant_id, TYPE_SEAT_CAP_BLOCKED_SSO, user_id, _NOTIFY_WINDOW_HOURS),
    )
    return cursor.fetchone() is not None
