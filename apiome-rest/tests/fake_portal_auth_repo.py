"""In-memory :class:`app.portal_auth_store.PortalAuthRepository` for the PCX-1.1 tests.

Mirrors the SQL repository's semantics closely enough that the store's rules — one user and one
membership per address, burn-once tokens, revocation on the next request — are tested without a
database: ``ON CONFLICT`` upserts, the conditional ``UPDATE``s that report whether they changed a
row, and the session join.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

TENANT_ID = "11111111-1111-4111-8111-111111111111"
OTHER_TENANT_ID = "22222222-2222-4222-8222-222222222222"


class FakePortalAuthRepository:
    """A dict-backed repository. Inspect ``users``, ``memberships``, ``links``, ``sessions``, ``audit``."""

    def __init__(self) -> None:
        self.tenants: Dict[str, Dict[str, Any]] = {
            "acme": {"tenant_id": TENANT_ID, "tenant_slug": "acme", "tenant_name": "Acme"},
            "globex": {"tenant_id": OTHER_TENANT_ID, "tenant_slug": "globex", "tenant_name": "Globex"},
        }
        self.users: Dict[str, Dict[str, Any]] = {}
        self.memberships: Dict[str, Dict[str, Any]] = {}
        self.links: Dict[str, Dict[str, Any]] = {}
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.audit: List[Dict[str, Any]] = []
        self.fail_audit = False

    # -- helpers for tests ------------------------------------------------------------------
    def add_user(
        self, email: str, *, enabled: bool = True, deleted: bool = False, password: str = "", verified: bool = False
    ) -> str:
        """Seed an existing account and return its id (``password`` non-empty = a usable password)."""
        user_id = str(uuid.uuid4())
        self.users[user_id] = {
            "id": user_id,
            "email": email,
            "name": email.split("@")[0],
            "enabled": enabled,
            "deleted_at": datetime(2026, 1, 1) if deleted else None,
            "verified": verified,
            "password": password,
        }
        return user_id

    def membership_for(self, email: str, tenant_slug: str = "acme") -> Optional[Dict[str, Any]]:
        """The membership of an address in a tenant, if any."""
        tenant_id = self.tenants[tenant_slug]["tenant_id"]
        for membership in self.memberships.values():
            user = self.users[membership["user_id"]]
            if user["email"] == email and membership["tenant_id"] == tenant_id:
                return membership
        return None

    # -- PortalAuthRepository ---------------------------------------------------------------
    def find_tenant(self, tenant_slug: str) -> Optional[Mapping[str, Any]]:
        return self.tenants.get(tenant_slug)

    def find_user_by_email(self, email: str) -> Optional[Mapping[str, Any]]:
        for user in self.users.values():
            if user["email"].lower() == email.lower():
                return user
        return None

    def create_user(self, email: str, name: str) -> Mapping[str, Any]:
        existing = self.find_user_by_email(email)
        if existing:
            return existing
        user_id = self.add_user(email)
        self.users[user_id]["name"] = name
        return self.users[user_id]

    def find_membership(self, tenant_id: str, user_id: str) -> Optional[Mapping[str, Any]]:
        for membership in self.memberships.values():
            if membership["tenant_id"] == tenant_id and membership["user_id"] == user_id:
                return membership
        return None

    def create_membership(self, tenant_id: str, user_id: str, source: str) -> Mapping[str, Any]:
        existing = self.find_membership(tenant_id, user_id)
        if existing:
            return existing
        membership_id = str(uuid.uuid4())
        self.memberships[membership_id] = {
            "id": membership_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "status": "invited",
            "source": source,
            "activated_at": None,
            "revoked_at": None,
        }
        return self.memberships[membership_id]

    def insert_magic_link(self, *, tenant_id, membership_id, lookup_prefix, token_hash, return_to, expires_at):
        assert lookup_prefix not in {link["lookup_prefix"] for link in self.links.values()}
        link_id = str(uuid.uuid4())
        self.links[link_id] = {
            "id": link_id,
            "tenant_id": tenant_id,
            "membership_id": membership_id,
            "lookup_prefix": lookup_prefix,
            "token_hash": token_hash,
            "return_to": return_to,
            "expires_at": expires_at,
            "consumed_at": None,
        }

    def find_magic_link(self, tenant_id: str, lookup_prefix: str) -> Optional[Mapping[str, Any]]:
        for link in self.links.values():
            if link["tenant_id"] == tenant_id and link["lookup_prefix"] == lookup_prefix:
                return dict(link)
        return None

    def burn_magic_link(self, link_id: str, now: datetime) -> bool:
        link = self.links[link_id]
        if link["consumed_at"] is not None or link["expires_at"] <= now:
            return False
        link["consumed_at"] = now
        return True

    def activate_membership(self, membership_id: str, now: datetime) -> bool:
        membership = self.memberships[membership_id]
        if membership["status"] != "invited":
            return False
        membership["status"] = "active"
        membership["activated_at"] = membership["activated_at"] or now
        return True

    def mark_user_verified(self, user_id: str) -> None:
        # Mirrors the SQL guard: only a password-less account is verified.
        if not self.users[user_id]["password"]:
            self.users[user_id]["verified"] = True

    def insert_session(self, *, membership_id, token_hash, expires_at, user_agent_family):
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = {
            "id": session_id,
            "membership_id": membership_id,
            "token_hash": token_hash,
            "expires_at": expires_at,
            "last_seen_at": None,
            "revoked_at": None,
            "user_agent_family": user_agent_family,
        }
        return {"id": session_id, "expires_at": expires_at}

    def find_session(self, token_hash: str) -> Optional[Mapping[str, Any]]:
        for session in self.sessions.values():
            if session["token_hash"] != token_hash:
                continue
            membership = self.memberships[session["membership_id"]]
            user = self.users[membership["user_id"]]
            tenant = next(t for t in self.tenants.values() if t["tenant_id"] == membership["tenant_id"])
            return {
                "session_id": session["id"],
                "expires_at": session["expires_at"],
                "revoked_at": session["revoked_at"],
                "membership_id": membership["id"],
                "membership_status": membership["status"],
                "tenant_id": tenant["tenant_id"],
                "tenant_slug": tenant["tenant_slug"],
                "tenant_name": tenant["tenant_name"],
                "user_id": user["id"],
                "email": user["email"],
                "name": user["name"],
                "user_enabled": user["enabled"],
                "user_deleted_at": user["deleted_at"],
            }
        return None

    def touch_session(self, session_id: str, now: datetime) -> None:
        self.sessions[session_id]["last_seen_at"] = now

    def revoke_session(self, session_id: str, now: datetime) -> bool:
        session = self.sessions[session_id]
        if session["revoked_at"] is not None:
            return False
        session["revoked_at"] = now
        return True

    def write_audit(self, *, tenant_id, action, actor_id, target, detail) -> None:
        if self.fail_audit:
            raise RuntimeError("audit store down")
        self.audit.append(
            {"tenant_id": tenant_id, "action": action, "actor_id": actor_id, "target": target, "detail": detail}
        )


class RecordingMailer:
    """A :class:`app.portal_mail.ReaderMailer` that keeps what it was asked to send."""

    def __init__(self) -> None:
        self.sent: List[Dict[str, str]] = []

    def send_magic_link(self, *, to: str, tenant_name: str, link: str) -> bool:
        self.sent.append({"to": to, "tenant_name": tenant_name, "link": link})
        return True

    def last_token(self) -> str:
        """The token in the most recent link."""
        from urllib.parse import parse_qs, urlparse

        return parse_qs(urlparse(self.sent[-1]["link"]).query)["token"][0]
