"""Ownership on catalog entities — what an owner *is* (CDG-2.2, #5961).

An entity — a project, a catalog item, an MCP endpoint, a consumer or a connector — has at most one
**confirmed** owner team and any number of **suggested** ones. Suggestions come from importers
(gateway tags, CODEOWNERS, an ``x-apiome-owner`` extension, ``info.contact``), each shown with its
source; nothing routes to a suggestion until someone confirms it.

This module holds the vocabulary, the shapes, the per-kind registry and the one SQL fragment every
list read joins to embed ``owner`` in its envelope. :mod:`app.entity_owner_store` reads and writes
``apiome.entity_owners`` (apiome-db V285); :mod:`app.entity_owner_routes` serves it.

**Who may change an owner** is the permission that already guards editing that kind of entity
(:data:`KINDS`): ``projects:edit`` for projects, catalog items and MCP endpoints,
``consumer_contracts:edit`` for consumers and ``imports:edit`` for connectors. Reading owners needs the
matching ``view``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .permissions import Resource

__all__ = [
    "CODE_ENTITY_NOT_FOUND",
    "CODE_INVALID",
    "CODE_NO_SUGGESTION",
    "CODE_TEAM_NOT_FOUND",
    "EXTENSION_KEY",
    "KINDS",
    "MAX_BULK",
    "SOURCE_CODEOWNERS",
    "SOURCE_GATEWAY_TAG",
    "SOURCE_MANUAL",
    "SOURCE_SPEC_EXTENSION",
    "BulkAssignInput",
    "EntityOwnerRef",
    "EntityRef",
    "KindSpec",
    "OwnerAssignInput",
    "OwnerConfirmInput",
    "OwnerRecord",
    "OwnerTeamRef",
    "OwnersResponse",
    "OwnerValidationError",
    "codeowners_for_path",
    "kind_spec",
    "owner_envelope_join",
    "owner_ref_from_value",
    "parse_codeowners",
    "spec_owner_suggestions",
]

#: The entity does not exist in this tenant (or the kind is not one of :data:`KINDS`).
CODE_ENTITY_NOT_FOUND = "owner-entity-not-found"
#: No live team in this tenant has the slug.
CODE_TEAM_NOT_FOUND = "owner-team-not-found"
#: Confirm named a team that has no suggestion for the entity, or there was none to confirm.
CODE_NO_SUGGESTION = "owner-no-suggestion"
#: A malformed request (an unknown kind, an ambiguous confirm, a bad id).
CODE_INVALID = "owner-invalid"

SOURCE_MANUAL = "manual"
SOURCE_GATEWAY_TAG = "gateway_tag"
SOURCE_CODEOWNERS = "codeowners"
SOURCE_SPEC_EXTENSION = "spec_extension"

#: The document-root extension that names an owner team (a slug, or a list of slugs).
EXTENSION_KEY = "x-apiome-owner"

#: Upper bound on one bulk assignment.
MAX_BULK = 200

_TEAM_SLUG = re.compile(r"^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")


@dataclass(frozen=True)
class KindSpec:
    """How to find one kind of entity and who may change its owner.

    Attributes:
        kind: The ``entity_kind`` value.
        table: The table holding the entity.
        where: Extra predicate (on alias ``e``) a live entity of this kind satisfies.
        resource: The RBAC resource whose ``view``/``edit`` gates reading/changing its owner.
    """

    kind: str
    table: str
    where: str
    resource: str


#: The five kinds. A catalog item and a project are both ``apiome.projects`` rows, told apart by
#: ``publishable``.
KINDS: Dict[str, KindSpec] = {
    "project": KindSpec(
        "project", "apiome.projects", "e.publishable AND e.deleted_at IS NULL", Resource.PROJECTS
    ),
    "catalog_item": KindSpec(
        "catalog_item",
        "apiome.projects",
        "NOT e.publishable AND e.deleted_at IS NULL",
        Resource.PROJECTS,
    ),
    "mcp_endpoint": KindSpec(
        "mcp_endpoint", "apiome.mcp_endpoints", "e.deleted_at IS NULL", Resource.PROJECTS
    ),
    "consumer": KindSpec(
        "consumer", "apiome.consumer", "e.deleted_at IS NULL", Resource.CONSUMER_CONTRACTS
    ),
    "connector": KindSpec(
        "connector", "apiome.catalog_connectors", "e.deleted_at IS NULL", Resource.IMPORTS
    ),
}

EntityKind = Literal["project", "catalog_item", "mcp_endpoint", "consumer", "connector"]


class OwnerValidationError(ValueError):
    """An ownership refusal carrying a stable machine code.

    Attributes:
        code: One of the module's ``CODE_*`` constants.
    """

    def __init__(self, code: str, message: str) -> None:
        """Build the refusal.

        Args:
            code: The stable code a client branches on.
            message: The human-readable explanation.
        """
        super().__init__(message)
        self.code = code


def kind_spec(kind: str) -> KindSpec:
    """Return the registry entry for ``kind``, or refuse an unknown kind.

    Args:
        kind: The ``entity_kind`` from the URL or a request body.

    Returns:
        The kind's :class:`KindSpec`.

    Raises:
        OwnerValidationError: ``owner-invalid`` for a kind outside :data:`KINDS`.
    """
    spec = KINDS.get((kind or "").strip())
    if spec is None:
        raise OwnerValidationError(
            CODE_INVALID, f"unknown entity kind '{kind}'; use one of {', '.join(KINDS)}"
        )
    return spec


# ---------------------------------------------------------------------------------------------
# Wire shapes
# ---------------------------------------------------------------------------------------------


class OwnerTeamRef(BaseModel):
    """The team an owner row names."""

    model_config = ConfigDict(extra="ignore")

    id: str
    slug: str
    name: str


class EntityOwnerRef(BaseModel):
    """The ``owner`` every list envelope carries: the confirmed owner, else the first suggestion."""

    model_config = ConfigDict(extra="ignore")

    team: OwnerTeamRef
    status: Literal["confirmed", "suggested"]
    source: str


class OwnerRecord(BaseModel):
    """One owner row, confirmed or suggested."""

    model_config = ConfigDict(extra="forbid")

    team: OwnerTeamRef
    status: Literal["confirmed", "suggested"]
    source: str
    source_ref: Optional[str] = None
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[str] = None
    created_at: Optional[str] = None


class OwnersResponse(BaseModel):
    """An entity's owner and suggestions."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    entity_id: str
    owner: Optional[OwnerRecord] = Field(default=None, description="The confirmed owner, if any.")
    suggestions: List[OwnerRecord] = Field(
        default_factory=list,
        description="Suggested owners with their source; none of them receives findings.",
    )


class OwnerAssignInput(BaseModel):
    """Make a team the confirmed owner."""

    model_config = ConfigDict(extra="forbid")

    team: str = Field(min_length=1, max_length=128, description="The team's slug.")


class OwnerConfirmInput(BaseModel):
    """Confirm a suggestion. ``team`` may be omitted when there is exactly one suggestion."""

    model_config = ConfigDict(extra="forbid")

    team: Optional[str] = Field(default=None, max_length=128)


class EntityRef(BaseModel):
    """One entity in a bulk assignment."""

    model_config = ConfigDict(extra="forbid")

    kind: EntityKind
    id: str = Field(min_length=1, max_length=64)


class BulkAssignInput(BaseModel):
    """Make one team the confirmed owner of many entities."""

    model_config = ConfigDict(extra="forbid")

    team: str = Field(min_length=1, max_length=128)
    entities: List[EntityRef] = Field(min_length=1, max_length=MAX_BULK)


def owner_ref_from_value(value: Any) -> Optional[EntityOwnerRef]:
    """Build the envelope ``owner`` from the ``entity_owner`` column :func:`owner_envelope_join` adds.

    Args:
        value: The JSON object the lateral produced, or ``None`` when the entity has no owner.

    Returns:
        The reference, or ``None``.
    """
    if not isinstance(value, Mapping) or not isinstance(value.get("team"), Mapping):
        return None
    return EntityOwnerRef.model_validate(value)


def owner_envelope_join(kinds: Sequence[str], id_expr: str, tenant_expr: str) -> str:
    """The ``LEFT JOIN LATERAL`` that embeds an entity's owner in a list read, as ``entity_owner``.

    Selecting ``own.entity_owner`` alongside the list's own columns keeps the read one statement:
    the confirmed owner wins, otherwise the oldest suggestion; rows of soft-deleted teams are
    ignored. The value is a JSON object ``{team: {id, slug, name}, status, source}`` or ``NULL``.

    Args:
        kinds: The ``entity_kind`` values the row may be stored under (a projects row may be a
            ``project`` or a ``catalog_item``).
        id_expr: SQL expression for the entity id (``p.id``).
        tenant_expr: SQL expression for the entity's tenant (``p.tenant_id``).

    Returns:
        The SQL fragment.
    """
    for kind in kinds:
        kind_spec(kind)
    kind_list = ", ".join(f"'{kind}'" for kind in kinds)
    return f"""
            LEFT JOIN LATERAL (
                SELECT jsonb_build_object(
                           'team', jsonb_build_object('id', ot.id::text, 'slug', ot.slug, 'name', ot.name),
                           'status', eo.status,
                           'source', eo.source
                       ) AS entity_owner
                FROM apiome.entity_owners eo
                JOIN apiome.teams ot ON ot.id = eo.team_id AND ot.deleted_at IS NULL
                WHERE eo.tenant_id = {tenant_expr}
                  AND eo.entity_id = {id_expr}
                  AND eo.entity_kind IN ({kind_list})
                ORDER BY (eo.status = 'confirmed') DESC, eo.created_at, eo.id
                LIMIT 1
            ) own ON TRUE
    """


# ---------------------------------------------------------------------------------------------
# Suggestion producers
# ---------------------------------------------------------------------------------------------


def _slug(value: Any) -> Optional[str]:
    """A lower-cased team slug, or ``None`` when ``value`` is not shaped like one."""
    if not isinstance(value, str):
        return None
    candidate = value.strip().lower()
    return candidate if _TEAM_SLUG.fullmatch(candidate) else None


def spec_owner_suggestions(document: Any) -> List[Dict[str, str]]:
    """Suggested owners a specification document names about itself.

    Two places count: an ``x-apiome-owner`` extension at the document root (a slug or a list of
    slugs), and ``info.contact.name`` when it is shaped like a team slug — whether that team exists
    is checked when the suggestion is recorded, and a contact name that names no team suggests
    nothing.

    Args:
        document: The parsed document (an OpenAPI/AsyncAPI-style mapping); anything else yields none.

    Returns:
        ``[{team, sourceRef}]``, one per distinct slug, extension entries first.
    """
    if not isinstance(document, Mapping):
        return []
    found: List[Dict[str, str]] = []
    seen: set[str] = set()

    raw = document.get(EXTENSION_KEY)
    for value in raw if isinstance(raw, list) else [raw]:
        slug = _slug(value)
        if slug and slug not in seen:
            seen.add(slug)
            found.append({"team": slug, "sourceRef": f"{EXTENSION_KEY}: {slug}"})

    info = document.get("info")
    contact = info.get("contact") if isinstance(info, Mapping) else None
    name = _slug(contact.get("name")) if isinstance(contact, Mapping) else None
    if name and name not in seen:
        found.append({"team": name, "sourceRef": f"info.contact.name: {name}"})
    return found


def parse_codeowners(text: str) -> List[Tuple[str, List[str]]]:
    """Parse a CODEOWNERS file into ``(pattern, owners)`` rules, in file order.

    Comments, blank lines and ``[Section]`` headers (GitLab) are skipped; a rule with no owners is
    kept, because in CODEOWNERS it *removes* ownership from paths an earlier rule matched.

    Args:
        text: The file's text.

    Returns:
        The rules.
    """
    rules: List[Tuple[str, List[str]]] = []
    for line in (text or "").splitlines():
        stripped = line.split(" #", 1)[0].strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("["):
            continue
        parts = stripped.split()
        rules.append((parts[0], parts[1:]))
    return rules


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    """Translate a CODEOWNERS (gitignore-style) pattern into a regex over repository paths."""
    anchored = pattern.startswith("/") or "/" in pattern.rstrip("/")
    body = pattern.strip("/")
    directory = pattern.endswith("/")
    out = ""
    i = 0
    while i < len(body):
        if body.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif body.startswith("**", i):
            out += ".*"
            i += 2
        elif body[i] == "*":
            out += "[^/]*"
            i += 1
        elif body[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(body[i])
            i += 1
    prefix = "^" if anchored else "^(?:.*/)?"
    suffix = "/.*$" if directory else "(?:/.*)?$"
    return re.compile(prefix + out + suffix)


def codeowners_for_path(rules: Sequence[Tuple[str, List[str]]], path: str) -> List[str]:
    """The owners of ``path``: the last matching rule wins, as in GitHub and GitLab.

    Args:
        rules: Parsed rules from :func:`parse_codeowners`.
        path: A repository path (no leading slash).

    Returns:
        The owners as written (``@org/team``, ``@user``, e-mail); empty when no rule matches.
    """
    target = (path or "").lstrip("/")
    owners: List[str] = []
    for pattern, rule_owners in rules:
        if pattern == "*" or _pattern_regex(pattern).match(target):
            owners = list(rule_owners)
    return owners
