"""API products — what a product and its members *are* (APX-1.1, #6098).

Access is granted to a thing a consumer understands ("Payments API"), which is usually several
projects and versions, possibly MCP servers and catalog items. An **API product** is that bundle: a
named, team-owned set of **members** with a visibility and a lifecycle state (apiome-db V387).

==================  ===============================================================================
Member kind         What it includes
==================  ===============================================================================
``project_latest``  a Project at whatever version was published last — it follows new publishes
``project_version`` a Project at a version label (``1.4.0``) or a range (``2.x``, ``2.1.x``): the
                    newest published version the selector matches
``mcp_server``      an MCP server
``catalog_item``    a catalog item (a spec that is not a publishable Project)
==================  ===============================================================================

**Visibility.** ``private`` (the owner team and admins), ``workspace`` (every tenant member) or
``portal`` (the developer portal). A ``portal`` product must have every member *published* — a
Project member resolves to a published version, an MCP server is published — so the portal never
lists a product whose parts a reader cannot open. :func:`portal_blockers` names the members that
fail; the store refuses a visibility change or a member add that would leave a ``portal`` product
with any.

This module holds the shapes and the pure rules; :mod:`app.api_product_store` reads and writes
them and :mod:`app.api_product_routes` serves them. Every refusal is an
:class:`ApiProductValidationError` carrying a stable ``api-product-*`` code.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from .consumer_contract import _SLUG_PATTERN, slugify_consumer_name

__all__ = [
    "CODE_INVALID",
    "CODE_MEMBER_DUPLICATE",
    "CODE_MEMBER_NOT_FOUND",
    "CODE_MEMBER_REF_NOT_FOUND",
    "CODE_NOT_FOUND",
    "CODE_PORTAL_UNPUBLISHED",
    "CODE_SLUG_TAKEN",
    "CODE_TEAM_NOT_FOUND",
    "MAX_MEMBERS",
    "MEMBER_KINDS",
    "PROJECT_MEMBER_KINDS",
    "STATES",
    "VISIBILITIES",
    "ApiProductInput",
    "ApiProductMember",
    "ApiProductMemberInput",
    "ApiProductPatch",
    "ApiProductRecord",
    "ApiProductValidationError",
    "MemberVersion",
    "OwnerTeam",
    "normalize_environment",
    "normalize_name",
    "normalize_selector",
    "pick_version",
    "portal_blockers",
    "resolve_slug",
    "selector_matches",
]

#: No live product in this tenant has that slug.
CODE_NOT_FOUND = "api-product-not-found"
#: Another live product in this tenant already has that slug.
CODE_SLUG_TAKEN = "api-product-slug-taken"
#: A field is malformed (slug shape, blank name, a selector on the wrong kind, …).
CODE_INVALID = "api-product-invalid"
#: ``owner_team`` names no live team of the tenant.
CODE_TEAM_NOT_FOUND = "api-product-team-not-found"
#: A member's ``ref`` names no live entity of its kind in the tenant.
CODE_MEMBER_REF_NOT_FOUND = "api-product-member-ref-not-found"
#: The product has no member with that id.
CODE_MEMBER_NOT_FOUND = "api-product-member-not-found"
#: The product already includes that member (same kind, ref, selector and environment).
CODE_MEMBER_DUPLICATE = "api-product-member-duplicate"
#: A ``portal`` product would include a member that is not published.
CODE_PORTAL_UNPUBLISHED = "api-product-portal-unpublished"

VISIBILITIES = ("private", "workspace", "portal")
STATES = ("draft", "published", "deprecated", "retired")
MEMBER_KINDS = ("project_latest", "project_version", "mcp_server", "catalog_item")

#: The member kinds whose ref is a publishable Project.
PROJECT_MEMBER_KINDS = ("project_latest", "project_version")

#: Upper bound on one product's members, so one product cannot become an unbounded read.
MAX_MEMBERS = 200

_SELECTOR_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,99}$")
_ENVIRONMENT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

Visibility = Literal["private", "workspace", "portal"]
State = Literal["draft", "published", "deprecated", "retired"]
MemberKind = Literal["project_latest", "project_version", "mcp_server", "catalog_item"]


class ApiProductValidationError(ValueError):
    """An API product refusal carrying a stable machine code.

    Attributes:
        code: One of the module's ``CODE_*`` constants.
        blockers: For ``api-product-portal-unpublished``, the members that are not published
            (``{kind, ref, name}``); else ``None``.
    """

    def __init__(self, code: str, message: str, *, blockers: Optional[List[Dict[str, Any]]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.blockers = blockers


# ---------------------------------------------------------------------------------------------
# Field rules
# ---------------------------------------------------------------------------------------------


def resolve_slug(slug: Optional[str], name: str) -> str:
    """Return the handle a new product is stored under.

    Args:
        slug: The handle the caller supplied, or ``None`` to derive one from ``name``.
        name: The product's display name.

    Returns:
        The trimmed, lowercased handle.

    Raises:
        ApiProductValidationError: ``api-product-invalid`` when the handle (supplied or derived) has
            the wrong shape — including a name with no letters or digits to derive one from.
    """
    candidate = (slug if slug is not None else slugify_consumer_name(name)).strip().lower()
    if not candidate or not _SLUG_PATTERN.match(candidate):
        raise ApiProductValidationError(
            CODE_INVALID,
            f"'{candidate}' is not a valid product slug; use lowercase letters, digits and hyphens "
            f"(1-128 characters, not starting or ending with a hyphen)",
        )
    return candidate


def normalize_name(name: Optional[str]) -> str:
    """Return a trimmed display name, or refuse a blank one.

    Args:
        name: The candidate name.

    Returns:
        The trimmed name.

    Raises:
        ApiProductValidationError: ``api-product-invalid`` when the name is blank.
    """
    trimmed = (name or "").strip()
    if not trimmed:
        raise ApiProductValidationError(CODE_INVALID, "a product needs a name")
    return trimmed


def normalize_selector(kind: str, version: Optional[str]) -> Optional[str]:
    """Return a member's version selector: required for ``project_version``, refused elsewhere.

    Args:
        kind: The member kind.
        version: The selector sent (``1.4.0``, ``2.x``, ``2.1.x``), or ``None``.

    Returns:
        The trimmed selector for a ``project_version`` member; ``None`` for every other kind.

    Raises:
        ApiProductValidationError: ``api-product-invalid`` for a missing, malformed or misplaced
            selector.
    """
    trimmed = (version or "").strip()
    if kind != "project_version":
        if trimmed:
            raise ApiProductValidationError(
                CODE_INVALID, f"a {kind} member takes no version; use project_version to pin one"
            )
        return None
    if not trimmed:
        raise ApiProductValidationError(CODE_INVALID, "a project_version member needs a version (e.g. 1.4.0 or 2.x)")
    if not _SELECTOR_PATTERN.match(trimmed):
        raise ApiProductValidationError(CODE_INVALID, f"'{trimmed}' is not a version label or range")
    return trimmed


def normalize_environment(environment: Optional[str]) -> Optional[str]:
    """Return a member's environment, lowercased, or ``None`` for every environment.

    Args:
        environment: ``production``, ``sandbox``, …, or empty.

    Returns:
        The lowercased environment, or ``None``.

    Raises:
        ApiProductValidationError: ``api-product-invalid`` when it is not a short lowercase name.
    """
    trimmed = (environment or "").strip().lower()
    if not trimmed:
        return None
    if not _ENVIRONMENT_PATTERN.match(trimmed):
        raise ApiProductValidationError(
            CODE_INVALID, "environment must be lowercase letters, digits, '-' or '_' (at most 64 characters)"
        )
    return trimmed


# ---------------------------------------------------------------------------------------------
# Version resolution
# ---------------------------------------------------------------------------------------------


def _bare(label: str) -> str:
    """A version label without a leading ``v`` (``v2.1.0`` → ``2.1.0``), for range comparison."""
    return label[1:] if label[:1] in ("v", "V") and label[1:2].isdigit() else label


def selector_matches(selector: str, label: Optional[str]) -> bool:
    """Whether a version label satisfies a ``project_version`` selector.

    A selector ending in ``.x`` (``2.x``, ``2.1.x``) is a range: it matches its prefix and every
    label below it (``2``, ``2.0.0``, ``2.9.1``, not ``20.1``). Any other selector matches its exact
    label. A leading ``v`` is ignored on both sides of a range.

    Args:
        selector: The selector.
        label: A version label.

    Returns:
        True when the label is within the selector.
    """
    if not label:
        return False
    if selector.lower().endswith(".x"):
        prefix = _bare(selector[:-2])
        bare = _bare(label)
        return bare == prefix or bare.startswith(prefix + ".")
    return label == selector


def pick_version(
    kind: str, selector: Optional[str], versions: Sequence[Mapping[str, Any]]
) -> Optional[Dict[str, Any]]:
    """The version a Project member resolves to today.

    ``versions`` arrive newest first (the store orders them by publish time, then creation). The
    member resolves to the newest *published* version it covers; with none published it resolves
    to the newest version it covers, unpublished, so a draft product still shows what it points at.

    Args:
        kind: ``project_latest`` (every version) or ``project_version`` (the selector's).
        selector: The ``project_version`` selector; ignored for ``project_latest``.
        versions: ``{id, label, published}`` rows, newest first.

    Returns:
        The chosen row, or ``None`` when no version is covered.
    """
    covered = [
        row for row in versions
        if kind != "project_version" or selector_matches(selector or "", row.get("label"))
    ]
    for row in covered:
        if row.get("published"):
            return dict(row)
    return dict(covered[0]) if covered else None


def portal_blockers(members: Sequence["ApiProductMember"]) -> List[Dict[str, Any]]:
    """The members that keep a product off the portal: every one that is not published.

    Args:
        members: The product's resolved members.

    Returns:
        ``{kind, ref, name}`` per unpublished member, in member order; empty when all are published.
    """
    return [
        {"kind": member.kind, "ref": member.ref, "name": member.name}
        for member in members
        if not member.published
    ]


# ---------------------------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------------------------


class ApiProductMemberInput(BaseModel):
    """One member to add.

    Attributes:
        kind: The member kind.
        ref: The member's id, or its slug (a Project, catalog item or MCP server slug).
        version: For ``project_version`` only: a version label or a ``2.x`` range.
        environment: Narrows the member to one environment (``production``); empty for all.
    """

    model_config = ConfigDict(extra="forbid")

    kind: MemberKind
    ref: str = Field(min_length=1, max_length=255)
    version: Optional[str] = Field(default=None, max_length=100)
    environment: Optional[str] = Field(default=None, max_length=64)


class ApiProductInput(BaseModel):
    """A product to create.

    Attributes:
        slug: The handle; derived from ``name`` when omitted. Not editable afterwards.
        name: The display name.
        summary: What the product is, in a sentence or two.
        owner_team: The owning team's slug.
        visibility: ``private`` (default), ``workspace`` or ``portal``.
        state: ``draft`` (default), ``published``, ``deprecated`` or ``retired``.
        members: Members to include from the start.
    """

    model_config = ConfigDict(extra="forbid")

    slug: Optional[str] = Field(default=None, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    summary: Optional[str] = Field(default=None, max_length=4000)
    owner_team: Optional[str] = Field(default=None, max_length=128, description="The owning team's slug.")
    visibility: Visibility = "private"
    state: State = "draft"
    members: List[ApiProductMemberInput] = Field(default_factory=list, max_length=MAX_MEMBERS)


class ApiProductPatch(BaseModel):
    """A partial update. Omitted fields are left alone; ``null`` clears ``summary`` or ``owner_team``.

    The slug is deliberately absent: it is the handle URLs and plans name. Members change through
    the members sub-resource.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    summary: Optional[str] = Field(default=None, max_length=4000)
    owner_team: Optional[str] = Field(default=None, max_length=128)
    visibility: Optional[Visibility] = None
    state: Optional[State] = None


class OwnerTeam(BaseModel):
    """The team that owns a product."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str


class MemberVersion(BaseModel):
    """The version a Project member resolves to today."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: Optional[str] = None
    published: bool = False


class ApiProductMember(BaseModel):
    """One member, as a read returns it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: MemberKind
    ref: str = Field(description="The member's id.")
    slug: Optional[str] = Field(default=None, description="The member's slug; `null` when it is gone.")
    name: Optional[str] = Field(default=None, description="The member's name; `null` when it is gone.")
    version_selector: Optional[str] = Field(
        default=None, description="`project_version` only: the label or range it was added with."
    )
    environment: Optional[str] = None
    resolved_version: Optional[MemberVersion] = Field(
        default=None,
        description=(
            "Project members: the newest published version the member covers (else the newest it "
            "covers). A `project_latest` member moves with every publish."
        ),
    )
    published: bool = Field(
        description="Whether the member is published: a Project member's resolved version is, or the MCP server is."
    )
    missing: bool = Field(default=False, description="True when the member's entity was deleted.")
    created_at: Optional[str] = None


class ApiProductRecord(BaseModel):
    """A stored product."""

    model_config = ConfigDict(extra="forbid")

    id: str
    slug: str
    name: str
    summary: Optional[str] = None
    owner_team: Optional[OwnerTeam] = None
    visibility: Visibility
    state: State
    member_count: int = Field(default=0, description="How many members the product has.")
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    members: Optional[List[ApiProductMember]] = Field(
        default=None, description="The members; present on single-product reads and writes."
    )
    portal_ready: Optional[bool] = Field(
        default=None,
        description="Present with `members`: true when every member is published, so `portal` is allowed.",
    )
