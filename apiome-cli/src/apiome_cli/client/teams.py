"""Pure helpers for ``apiome teams`` (CDG-2.4, #5963).

Membership parsing (``--set USER_ID[:lead|:member]``), the owner-entity kinds, and table rows —
kept free of I/O so they are unit-testable on their own. The command module owns the HTTP calls;
REST refusals are read with :func:`apiome_cli.client.connectors.refusal`, which already understands
the ``detail: {code, message}`` shape teams and owners answer with.
"""

from __future__ import annotations

from typing import Any

#: The entity kinds an owner team can be assigned to (``/v1/tenants/{t}/owners/{kind}/{id}``).
ENTITY_KINDS = ("project", "catalog_item", "mcp_endpoint", "consumer", "connector")

#: Team roles REST accepts; ``member`` is the default.
ROLES = ("lead", "member")

#: The default role of a ``--set USER_ID`` with no ``:role`` suffix.
DEFAULT_ROLE = "member"

#: REST's refusal code for an assignment naming a team that does not exist.
CODE_OWNER_TEAM_NOT_FOUND = "owner-team-not-found"

#: REST's refusal code for an assignment naming an entity that does not exist.
CODE_OWNER_ENTITY_NOT_FOUND = "owner-entity-not-found"


def parse_member(spec: str) -> dict[str, str]:
    """Parse one ``--set`` value into a membership entry.

    Args:
        spec: ``USER_ID`` or ``USER_ID:ROLE`` where ``ROLE`` is ``lead`` or ``member``. The role
            is split on the **last** colon, so a user id may itself contain colons as long as a
            role suffix is given.

    Returns:
        ``{"user_id": ..., "role": ...}`` as ``PUT …/members`` expects it.

    Raises:
        ValueError: The user id is empty, or the role is not ``lead`` / ``member``.
    """
    text = (spec or "").strip()
    user_id, role = text, DEFAULT_ROLE
    if ":" in text:
        head, _sep, tail = text.rpartition(":")
        candidate = tail.strip().lower()
        if candidate not in ROLES:
            raise ValueError(
                f"'{spec}': role must be one of {', '.join(ROLES)} (USER_ID[:lead|:member])"
            )
        user_id, role = head.strip(), candidate
    if not user_id:
        raise ValueError(f"'{spec}': a user id is required (USER_ID[:lead|:member])")
    return {"user_id": user_id, "role": role}


def parse_members(specs: list[str]) -> list[dict[str, str]]:
    """Parse every ``--set`` value, refusing the same user twice.

    Args:
        specs: The ``--set`` values in the order given.

    Returns:
        The membership entries, in order.

    Raises:
        ValueError: A value is malformed, or a user id is listed more than once.
    """
    members: list[dict[str, str]] = []
    seen: set[str] = set()
    for spec in specs:
        member = parse_member(spec)
        if member["user_id"] in seen:
            raise ValueError(f"user '{member['user_id']}' is listed more than once")
        seen.add(member["user_id"])
        members.append(member)
    return members


def validate_kind(kind: str) -> str:
    """Normalise and check an owner-entity kind.

    Args:
        kind: The ``<kind>`` argument (``catalog-item`` is accepted for ``catalog_item``).

    Returns:
        The kind as REST names it.

    Raises:
        ValueError: The kind is not one of :data:`ENTITY_KINDS`.
    """
    normalised = (kind or "").strip().lower().replace("-", "_")
    if normalised not in ENTITY_KINDS:
        raise ValueError(f"must be one of {', '.join(ENTITY_KINDS)}")
    return normalised


def links_label(team: dict[str, Any]) -> str:
    """The owner links a team has set, as a short label (``chat, oncall``) or ``-``.

    Args:
        team: A team record.

    Returns:
        The names of the links present, comma-separated, or ``-`` when none are.
    """
    names = [
        name
        for name, key in (
            ("email", "contact_email"),
            ("chat", "chat_url"),
            ("oncall", "oncall_url"),
            ("docs", "docs_url"),
        )
        if team.get(key)
    ]
    return ", ".join(names) if names else "-"


def team_rows(teams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows for the ``teams list`` table.

    Args:
        teams: Team records from ``GET …/teams``.

    Returns:
        One row per team: slug, name, member count and owner links.
    """
    return [
        {
            "slug": t.get("slug"),
            "name": t.get("name"),
            "members": int(t.get("member_count") or 0),
            "links": links_label(t),
        }
        for t in teams
    ]


def member_rows(team: dict[str, Any]) -> list[dict[str, Any]]:
    """Rows for a team's member table (``teams show`` / ``teams members``).

    Args:
        team: A team record read with its members.

    Returns:
        One row per member: user id, role, email and name (``-`` when unknown).
    """
    return [
        {
            "user_id": m.get("user_id"),
            "role": m.get("role"),
            "email": m.get("email") or "-",
            "name": m.get("name") or "-",
        }
        for m in team.get("members") or []
    ]


def detail_lines(team: dict[str, Any]) -> list[str]:
    """The ``teams show`` header: one ``Field: value`` line per set field.

    Args:
        team: A team record.

    Returns:
        The lines, in a fixed order; unset optional fields are left out.
    """
    lines = [f"Team: {team.get('name')} ({team.get('slug')})"]
    for label, key in (
        ("Description", "description"),
        ("Contact email", "contact_email"),
        ("Chat", "chat_url"),
        ("On-call", "oncall_url"),
        ("Docs", "docs_url"),
    ):
        if team.get(key):
            lines.append(f"{label}: {team[key]}")
    lines.append(f"Members: {int(team.get('member_count') or 0)}")
    return lines
