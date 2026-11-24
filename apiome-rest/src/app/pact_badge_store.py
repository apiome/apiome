"""Reads behind the public pact badges — PFX-1.10 (#6923).

Every read starts from a **public project** — one with a published, public, undeleted version, the
slice ``apiome-browse`` serves — and only reaches pacticipants *bound to that project*
(``pacticipant.project_id``). A private project, an unbound pacticipant and an unknown name all
come back as ``None``, so an anonymous caller cannot learn that a pact exists.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .pact_badge import combine_statuses, pact_status

__all__ = ["find_public_project", "pacticipant_badge", "pair_badge", "project_statuses"]

#: A project of a tenant, by slugs, that the public browse surface serves. %s: tenant, project.
_PUBLIC_PROJECT = """
    SELECT p.id::text AS id, t.id::text AS tenant_id
    FROM apiome.projects p
    JOIN apiome.tenants t ON t.id = p.tenant_id
    WHERE t.slug = %s AND p.slug = %s
      AND p.deleted_at IS NULL AND t.deleted_at IS NULL
      AND EXISTS (SELECT 1 FROM apiome.versions v
                  WHERE v.project_id = p.id AND v.published IS TRUE
                    AND v.visibility = 'public' AND v.deleted_at IS NULL)
"""

#: The pacticipants bound to a project. %s: tenant id, project id.
_BOUND = """
    SELECT id::text AS id, slug, name FROM apiome.pacticipant
    WHERE tenant_id = %s::uuid AND project_id = %s::uuid
    ORDER BY slug
"""

#: One pacticipant of a tenant, by slug. %s: tenant id, slug.
_ONE = """
    SELECT id::text AS id, slug, name, project_id::text AS project_id FROM apiome.pacticipant
    WHERE tenant_id = %s::uuid AND slug = %s
"""

#: The latest pact of every pair a pacticipant is in, with its newest result. %s: pacticipant id,
#: pacticipant id, tenant id.
_PAIRS = """
    WITH latest AS (
        SELECT DISTINCT ON (p.consumer_id, p.provider_id) p.consumer_id, p.provider_id, p.pact_version_id
        FROM apiome.pact_publication p
        WHERE p.consumer_id = %s::uuid OR p.provider_id = %s::uuid
        ORDER BY p.consumer_id, p.provider_id, p.created_at DESC, p.id
    )
    SELECT c.slug AS consumer_slug, pr.slug AS provider_slug,
           (SELECT r.success FROM apiome.verification_result r
            WHERE r.pact_version_id = l.pact_version_id
            ORDER BY r.seq DESC LIMIT 1) AS success
    FROM latest l
    JOIN apiome.pacticipant c ON c.id = l.consumer_id AND c.tenant_id = %s::uuid
    JOIN apiome.pacticipant pr ON pr.id = l.provider_id AND pr.tenant_id = %s::uuid
"""


def find_public_project(db: Any, tenant_slug: str, project_slug: str) -> Optional[Dict[str, str]]:
    """The public project at these slugs.

    Returns:
        ``{"id", "tenant_id"}``, or ``None`` when the project is private, has no published public
        version, is deleted, or does not exist.
    """
    rows = db.execute_query(_PUBLIC_PROJECT, (tenant_slug, project_slug))
    return dict(rows[0]) if rows else None


def _statuses(db: Any, tenant_id: str, pacticipant_id: str) -> List[Dict[str, Any]]:
    """Each pair the pacticipant is in: ``consumer_slug``, ``provider_slug`` and ``status``."""
    rows = db.execute_query(_PAIRS, (pacticipant_id, pacticipant_id, tenant_id, tenant_id)) or []
    return [
        {
            "consumer_slug": row["consumer_slug"],
            "provider_slug": row["provider_slug"],
            "status": pact_status(row["success"]),
        }
        for row in rows
    ]


def _bound(db: Any, project: Dict[str, str], slug: str) -> Optional[Dict[str, Any]]:
    """The pacticipant ``slug`` when it is bound to ``project``, else ``None``."""
    rows = db.execute_query(_ONE, (project["tenant_id"], slug))
    if not rows or rows[0].get("project_id") != project["id"]:
        return None
    return dict(rows[0])


def pacticipant_badge(db: Any, project: Dict[str, str], slug: str) -> Optional[Dict[str, Any]]:
    """The state of one pacticipant bound to the project.

    Returns:
        ``{"slug", "name", "status", "pacts"}``, or ``None`` when the pacticipant does not exist or
        is not bound to the project.
    """
    found = _bound(db, project, slug)
    if found is None:
        return None
    pairs = _statuses(db, project["tenant_id"], found["id"])
    return {
        "slug": found["slug"],
        "name": found["name"],
        "status": combine_statuses(pair["status"] for pair in pairs),
        "pacts": len(pairs),
    }


def pair_badge(db: Any, project: Dict[str, str], provider: str, consumer: str) -> Optional[Dict[str, Any]]:
    """The state of the latest pact between a consumer and a provider.

    Either side must be bound to the project.

    Returns:
        ``{"provider_slug", "consumer_slug", "status"}`` — ``unknown`` when they have no pact —
        or ``None`` when neither side is bound to the project or either does not exist.
    """
    rows = {slug: db.execute_query(_ONE, (project["tenant_id"], slug)) for slug in (provider, consumer)}
    if not all(rows.values()):
        return None
    if project["id"] not in (rows[provider][0].get("project_id"), rows[consumer][0].get("project_id")):
        return None
    pairs = _statuses(db, project["tenant_id"], rows[provider][0]["id"])
    match = [p for p in pairs if p["provider_slug"] == provider and p["consumer_slug"] == consumer]
    return {
        "provider_slug": provider,
        "consumer_slug": consumer,
        "status": match[0]["status"] if match else "unknown",
    }


def project_statuses(db: Any, project: Dict[str, str]) -> List[Dict[str, Any]]:
    """The state of every pacticipant bound to the project, by slug."""
    result = []
    for bound in db.execute_query(_BOUND, (project["tenant_id"], project["id"])) or []:
        pairs = _statuses(db, project["tenant_id"], bound["id"])
        result.append(
            {
                "slug": bound["slug"],
                "name": bound["name"],
                "status": combine_statuses(pair["status"] for pair in pairs),
                "pacts": len(pairs),
            }
        )
    return result
