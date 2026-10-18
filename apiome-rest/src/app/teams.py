"""Teams — what a team and its membership *are* (CDG-2.1, #5960).

A team is a named group of tenant members that owns catalog entities (CDG-2.2) and receives their
findings (CDG-2.3). It carries the owner links a team migrating from another catalog expects —
contact e-mail, chat channel, on-call schedule and documentation — and a list of members, each a
``lead`` or a ``member``. It is the only group concept: EID-2's SCIM group mapping targets it too.

This module holds the shapes and the validation; :mod:`app.team_store` reads and writes them and
:mod:`app.team_routes` serves them. Every refusal is a :class:`TeamValidationError` carrying a
stable ``team-*`` code, so a client branches on the code and the route maps it onto a status.

**A slug is a handle.** It has the consumer-slug shape (V284 repeats the CHECK constraint), is
derived from the name when omitted, and cannot be changed after creation: Kong tags
(``owner:payments``) and the ``x-apiome-owner`` extension name teams by slug, and renaming one
would silently orphan every such reference.
"""

from __future__ import annotations

import re
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .consumer_contract import _SLUG_PATTERN, slugify_consumer_name
from .revision_deprecation import is_uuid_string

__all__ = [
    "CODE_INVALID",
    "CODE_MEMBER_NOT_IN_TENANT",
    "CODE_NOT_FOUND",
    "CODE_OWNS_ENTITIES",
    "CODE_REASSIGN_INVALID",
    "CODE_SLUG_TAKEN",
    "MAX_MEMBERS",
    "ROLE_LEAD",
    "ROLE_MEMBER",
    "TeamInput",
    "TeamMember",
    "TeamMemberInput",
    "TeamMembersInput",
    "TeamPatch",
    "TeamRecord",
    "TeamValidationError",
    "normalize_contact_email",
    "normalize_link",
    "normalize_name",
    "resolve_slug",
    "validate_members",
]

#: No live team in this tenant has that slug.
CODE_NOT_FOUND = "team-not-found"
#: Another live team in this tenant already has that slug.
CODE_SLUG_TAKEN = "team-slug-taken"
#: A field is malformed (slug shape, blank name, a link that is not http(s), a bad e-mail).
CODE_INVALID = "team-invalid"
#: A member named in a membership write is not a member of the tenant.
CODE_MEMBER_NOT_IN_TENANT = "team-member-not-in-tenant"
#: The team still owns entities and no ``reassign_to`` was given.
CODE_OWNS_ENTITIES = "team-owns-entities"
#: ``reassign_to`` names the team being deleted, or no live team.
CODE_REASSIGN_INVALID = "team-reassign-invalid"

ROLE_LEAD = "lead"
ROLE_MEMBER = "member"

#: Upper bound on one membership write, so a single PUT cannot become an unbounded statement.
MAX_MEMBERS = 500

_LINK_PATTERN = re.compile(r"^https?://[^\s/$.?#][^\s]*$", re.IGNORECASE)
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class TeamValidationError(ValueError):
    """A team refusal carrying a stable machine code.

    Attributes:
        code: One of the module's ``CODE_*`` constants.
        owned_count: For ``team-owns-entities``, how many entities the team owns; else ``None``.
    """

    def __init__(self, code: str, message: str, *, owned_count: Optional[int] = None) -> None:
        """Build the refusal.

        Args:
            code: The stable code a client branches on.
            message: The human-readable explanation.
            owned_count: The owned-entity count, for a delete refused because of it.
        """
        super().__init__(message)
        self.code = code
        self.owned_count = owned_count


def resolve_slug(slug: Optional[str], name: str) -> str:
    """Return the handle a new team is stored under.

    Args:
        slug: The handle the caller supplied, or ``None`` to derive one from ``name``.
        name: The team's display name.

    Returns:
        The trimmed, lowercased handle.

    Raises:
        TeamValidationError: ``team-invalid`` when the handle (supplied or derived) has the wrong
            shape — including a name with no letters or digits to derive one from.
    """
    candidate = (slug if slug is not None else slugify_consumer_name(name)).strip().lower()
    if not candidate or not _SLUG_PATTERN.match(candidate):
        raise TeamValidationError(
            CODE_INVALID,
            f"'{candidate}' is not a valid team slug; use lowercase letters, digits and hyphens "
            f"(1-128 characters, not starting or ending with a hyphen)",
        )
    return candidate


def normalize_name(name: str) -> str:
    """Return a trimmed display name, or refuse a blank one.

    Args:
        name: The candidate name.

    Returns:
        The trimmed name.

    Raises:
        TeamValidationError: ``team-invalid`` when the name is blank.
    """
    trimmed = (name or "").strip()
    if not trimmed:
        raise TeamValidationError(CODE_INVALID, "a team needs a name")
    return trimmed


def normalize_link(field: str, value: Optional[str]) -> Optional[str]:
    """Return an owner link, or ``None`` for an empty one, refusing anything not http(s).

    Args:
        field: The field name, for the refusal message (``chat_url``, ``oncall_url``, ``docs_url``).
        value: The candidate URL.

    Returns:
        The trimmed URL, or ``None`` when ``value`` is empty.

    Raises:
        TeamValidationError: ``team-invalid`` when the URL is not an absolute http(s) URL.
    """
    trimmed = (value or "").strip()
    if not trimmed:
        return None
    if not _LINK_PATTERN.match(trimmed):
        raise TeamValidationError(CODE_INVALID, f"{field} must be an absolute http(s) URL")
    return trimmed


def normalize_contact_email(value: Optional[str]) -> Optional[str]:
    """Return a lowercased contact e-mail, or ``None`` for an empty one.

    Args:
        value: The candidate address.

    Returns:
        The trimmed, lowercased address, or ``None`` when ``value`` is empty.

    Raises:
        TeamValidationError: ``team-invalid`` when the value does not look like an address.
    """
    trimmed = (value or "").strip().lower()
    if not trimmed:
        return None
    if not _EMAIL_PATTERN.match(trimmed):
        raise TeamValidationError(CODE_INVALID, "contact_email must be an e-mail address")
    return trimmed


class TeamInput(BaseModel):
    """A team to create.

    Attributes:
        slug: The handle; derived from ``name`` when omitted. Not editable afterwards.
        name: The display name.
        description: Free text about what the team does.
        contact_email: A shared mailbox.
        chat_url: Link to the team's chat channel.
        oncall_url: Link to the team's on-call schedule.
        docs_url: Link to the team's documentation.
    """

    model_config = ConfigDict(extra="forbid")

    slug: Optional[str] = Field(default=None, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=4000)
    contact_email: Optional[str] = Field(default=None, max_length=320)
    chat_url: Optional[str] = Field(default=None, max_length=2000)
    oncall_url: Optional[str] = Field(default=None, max_length=2000)
    docs_url: Optional[str] = Field(default=None, max_length=2000)


class TeamPatch(BaseModel):
    """A partial update. Omitted fields are left alone; ``null`` clears an optional field.

    The slug is deliberately absent: it is the handle tags and extensions name.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=4000)
    contact_email: Optional[str] = Field(default=None, max_length=320)
    chat_url: Optional[str] = Field(default=None, max_length=2000)
    oncall_url: Optional[str] = Field(default=None, max_length=2000)
    docs_url: Optional[str] = Field(default=None, max_length=2000)


class TeamMember(BaseModel):
    """One member of a team, as a read returns it."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    role: Literal["lead", "member"]
    email: Optional[str] = None
    name: Optional[str] = None
    added_at: Optional[str] = None


class TeamRecord(BaseModel):
    """A stored team."""

    model_config = ConfigDict(extra="forbid")

    id: str
    slug: str
    name: str
    description: Optional[str] = None
    contact_email: Optional[str] = None
    chat_url: Optional[str] = None
    oncall_url: Optional[str] = None
    docs_url: Optional[str] = None
    member_count: int = Field(default=0, description="How many members the team has.")
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    members: Optional[List[TeamMember]] = Field(
        default=None,
        description="The members, leads first; present on single-team reads and member writes.",
    )


class TeamMemberInput(BaseModel):
    """One member in a membership write."""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=64)
    role: Literal["lead", "member"] = ROLE_MEMBER


class TeamMembersInput(BaseModel):
    """The complete membership of a team; it replaces whatever was there."""

    model_config = ConfigDict(extra="forbid")

    members: List[TeamMemberInput] = Field(default_factory=list, max_length=MAX_MEMBERS)


def validate_members(members: List[TeamMemberInput]) -> List[TeamMemberInput]:
    """Refuse a membership list that names a user twice or names a malformed id.

    Args:
        members: The requested membership.

    Returns:
        The same members with trimmed, lowercased user ids, in the order given.

    Raises:
        TeamValidationError: ``team-invalid`` for a duplicate or non-UUID user id.
    """
    seen: set[str] = set()
    cleaned: List[TeamMemberInput] = []
    for member in members:
        user_id = member.user_id.strip().lower()
        if not is_uuid_string(user_id):
            raise TeamValidationError(CODE_INVALID, f"'{member.user_id}' is not a user id")
        if user_id in seen:
            raise TeamValidationError(CODE_INVALID, f"user {user_id} is listed more than once")
        seen.add(user_id)
        cleaned.append(TeamMemberInput(user_id=user_id, role=member.role))
    return cleaned
