"""The pacticipant registry's vocabulary — PFX-1.1 (#6914).

Pact tooling addresses everything by **pacticipant** (an application that takes part in a pact, as a
consumer, a provider or both), **version** (one build of it), **branch** and **tag**. This module
says what those are and what a valid one looks like; :mod:`app.pacticipant_store` is the only place
one is read or written (apiome-db V432), and :mod:`app.pacticipant_routes` is the REST surface.

Every check here mirrors a V432 constraint, so the API refuses what the database would refuse
anyway — with a stable ``code`` a client can branch on instead of a driver error.

**A handle is derived, never renamed.** ``slug`` is what URLs and CI name. It is taken from the
display name when omitted (``"Billing Service"`` → ``billing-service``, the same derivation a Pact
import uses for a consumer) and cannot be changed afterwards.

**A version is identified by its number, exactly as the build reported it.** It is never parsed,
re-cased or ordered by its text: order is the order of recording.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .consumer_contract import slugify_consumer_name

__all__ = [
    "CODE_CONSUMER_NOT_FOUND",
    "CODE_INVALID_BRANCH",
    "CODE_INVALID_NAME",
    "CODE_INVALID_SLUG",
    "CODE_INVALID_TAG",
    "CODE_INVALID_URL",
    "CODE_INVALID_VERSION",
    "CODE_NOT_FOUND",
    "CODE_PROJECT_NOT_FOUND",
    "CODE_SLUG_TAKEN",
    "CODE_VERSION_NOT_FOUND",
    "MAX_LABEL_LENGTH",
    "MAX_TAGS_PER_REQUEST",
    "MAX_URL_LENGTH",
    "PacticipantBranchRecord",
    "PacticipantInput",
    "PacticipantPatch",
    "PacticipantRecord",
    "PacticipantValidationError",
    "RecordedPacticipantVersion",
    "PacticipantVersionInput",
    "PacticipantVersionRecord",
    "branch_record_from_row",
    "pacticipant_record_from_row",
    "slugify_pacticipant_name",
    "validate_branch",
    "validate_name",
    "validate_slug",
    "validate_tag",
    "validate_tags",
    "validate_url",
    "validate_version_number",
    "version_record_from_row",
]

# Stable refusal codes. A client branches on these, never on the message.
CODE_NOT_FOUND = "pacticipant-not-found"
CODE_INVALID_SLUG = "pacticipant-invalid-slug"
CODE_INVALID_NAME = "pacticipant-invalid-name"
CODE_SLUG_TAKEN = "pacticipant-slug-taken"
CODE_INVALID_URL = "pacticipant-invalid-url"
CODE_INVALID_BRANCH = "pacticipant-invalid-branch"
CODE_INVALID_TAG = "pacticipant-invalid-tag"
CODE_INVALID_VERSION = "pacticipant-invalid-version"
CODE_PROJECT_NOT_FOUND = "pacticipant-project-not-found"
CODE_CONSUMER_NOT_FOUND = "pacticipant-consumer-not-found"
CODE_VERSION_NOT_FOUND = "pacticipant-version-not-found"

#: Longest version number, branch name, tag and display name (V432: ``VARCHAR(255)``).
MAX_LABEL_LENGTH = 255
#: Longest repository or build URL (V432's URL checks).
MAX_URL_LENGTH = 2048
#: Most tags one "record a version" request may carry.
MAX_TAGS_PER_REQUEST = 50

#: Mirrors V432's ``pacticipant_slug_shape_check``.
_SLUG_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")
#: Mirrors V432's URL checks: http or https, no whitespace.
_URL_PATTERN = re.compile(r"^https?://\S+$", re.IGNORECASE)
#: ASCII control characters, which V432 refuses in a version number, branch name or tag.
_CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")


class PacticipantValidationError(ValueError):
    """A registry refusal carrying a stable machine code.

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


def slugify_pacticipant_name(name: str) -> str:
    """Derive a handle from a pacticipant name, the way a Pact import derives a consumer's.

    Args:
        name: The name as a Pact file or a person writes it (``"Billing Service"``).

    Returns:
        A candidate slug (``billing-service``); empty when the name has no letter or digit.
    """
    return slugify_consumer_name(name)


def validate_slug(slug: str) -> str:
    """Return a normalized pacticipant handle, or refuse.

    Args:
        slug: The candidate handle.

    Returns:
        The trimmed, lowercased handle.

    Raises:
        PacticipantValidationError: ``pacticipant-invalid-slug`` when the shape is wrong.
    """
    candidate = (slug or "").strip().lower()
    if not candidate or not _SLUG_PATTERN.match(candidate):
        raise PacticipantValidationError(
            CODE_INVALID_SLUG,
            f"'{candidate}' is not a valid pacticipant slug; use lowercase letters, digits and "
            f"hyphens (1-128 characters, not starting or ending with a hyphen)",
        )
    return candidate


def validate_name(name: str) -> str:
    """Return a trimmed display name, or refuse.

    Args:
        name: The candidate display name.

    Returns:
        The trimmed name.

    Raises:
        PacticipantValidationError: ``pacticipant-invalid-name`` when blank or too long.
    """
    candidate = (name or "").strip()
    if not candidate or len(candidate) > MAX_LABEL_LENGTH:
        raise PacticipantValidationError(
            CODE_INVALID_NAME, f"a pacticipant name is 1-{MAX_LABEL_LENGTH} characters"
        )
    return candidate


def validate_url(url: Optional[str], *, what: str) -> Optional[str]:
    """Return a trimmed http(s) URL, ``None`` for a blank one, or refuse.

    Args:
        url: The candidate URL, or ``None``.
        what: What the URL is, for the message (``"repository URL"``, ``"build URL"``).

    Returns:
        The trimmed URL, or ``None`` when nothing was given.

    Raises:
        PacticipantValidationError: ``pacticipant-invalid-url`` when it is not an http(s) URL
            without whitespace, or is longer than :data:`MAX_URL_LENGTH`.
    """
    candidate = (url or "").strip()
    if not candidate:
        return None
    if len(candidate) > MAX_URL_LENGTH or not _URL_PATTERN.match(candidate):
        raise PacticipantValidationError(
            CODE_INVALID_URL,
            f"the {what} must be an http or https URL of at most {MAX_URL_LENGTH} characters",
        )
    return candidate


def _validate_label(value: Optional[str], *, code: str, what: str) -> str:
    """Return a version number, branch name or tag unchanged, or refuse.

    These are stored exactly as sent, so nothing is trimmed or re-cased: a value that would need
    trimming is refused instead.

    Args:
        value: The candidate.
        code: The refusal code for this kind of label.
        what: What the label is, for the message.

    Returns:
        The value.

    Raises:
        PacticipantValidationError: ``code`` when empty, padded with whitespace, longer than
            :data:`MAX_LABEL_LENGTH`, or carrying a control character.
    """
    candidate = value if isinstance(value, str) else ""
    if (
        not candidate
        or candidate != candidate.strip()
        or len(candidate) > MAX_LABEL_LENGTH
        or _CONTROL_PATTERN.search(candidate)
    ):
        raise PacticipantValidationError(
            code,
            f"a {what} is 1-{MAX_LABEL_LENGTH} characters with no leading or trailing space and "
            f"no control characters",
        )
    return candidate


def validate_version_number(number: Optional[str]) -> str:
    """Return a version number unchanged, or refuse with ``pacticipant-invalid-version``.

    Args:
        number: The version string as the build reported it.

    Returns:
        The number.

    Raises:
        PacticipantValidationError: When the number is not storable (see :func:`_validate_label`).
    """
    return _validate_label(number, code=CODE_INVALID_VERSION, what="version number")


def validate_branch(name: Optional[str]) -> str:
    """Return a branch name unchanged, or refuse with ``pacticipant-invalid-branch``.

    Args:
        name: The branch as git names it.

    Returns:
        The name.

    Raises:
        PacticipantValidationError: When the name is not storable.
    """
    return _validate_label(name, code=CODE_INVALID_BRANCH, what="branch name")


def validate_tag(name: Optional[str]) -> str:
    """Return a tag unchanged, or refuse with ``pacticipant-invalid-tag``.

    Args:
        name: The tag.

    Returns:
        The tag.

    Raises:
        PacticipantValidationError: When the tag is not storable.
    """
    return _validate_label(name, code=CODE_INVALID_TAG, what="tag")


def validate_tags(tags: Optional[List[str]]) -> List[str]:
    """Validate a request's tags and drop repeats, keeping first-seen order.

    Args:
        tags: The tags of one request, or ``None``.

    Returns:
        The distinct tags.

    Raises:
        PacticipantValidationError: ``pacticipant-invalid-tag`` for an unstorable tag or more than
            :data:`MAX_TAGS_PER_REQUEST` of them.
    """
    distinct = list(dict.fromkeys(validate_tag(tag) for tag in tags or []))
    if len(distinct) > MAX_TAGS_PER_REQUEST:
        raise PacticipantValidationError(
            CODE_INVALID_TAG, f"at most {MAX_TAGS_PER_REQUEST} tags may be sent in one request"
        )
    return distinct


# ---------------------------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------------------------


class PacticipantInput(BaseModel):
    """A new pacticipant.

    Attributes:
        name: Display name, as a Pact file or a person writes it.
        slug: The handle; derived from ``name`` when omitted, and never editable.
        repository_url: http(s) URL of the application's source repository.
        main_branch: The branch read by default when a query names none.
        project: Slug or id of the Apiome project that describes this provider.
        consumer_id: Id of this application's row in the consumer registry.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Display name, as a Pact file or a person writes it.", examples=["Billing Service"])
    slug: Optional[str] = Field(
        default=None,
        description="The handle URLs and CI name. Derived from `name` when omitted; not editable afterwards.",
        examples=["billing-service"],
    )
    repository_url: Optional[str] = Field(
        default=None,
        description="http(s) URL of the application's source repository.",
        examples=["https://github.com/example/billing-service"],
    )
    main_branch: Optional[str] = Field(
        default=None, description="The branch read by default when a query names none.", examples=["main"]
    )
    project: Optional[str] = Field(
        default=None,
        description="Slug or id of the project that describes this application as a provider.",
        examples=["billing-api"],
    )
    consumer_id: Optional[str] = Field(
        default=None,
        description="Id of this application's consumer in the consumer registry.",
        examples=["7b1f0c1e-6f4e-4f0a-9d53-3d0e3f5a2a11"],
    )


class PacticipantPatch(BaseModel):
    """A partial update of a pacticipant. An omitted field is left alone; ``null`` clears it.

    Attributes:
        name: New display name (cannot be cleared).
        repository_url: New repository URL, or ``null`` to clear it.
        main_branch: New main branch, or ``null`` to clear it.
        project: Slug or id of the project to bind, or ``null`` to unbind.
        consumer_id: Id of the consumer to bind, or ``null`` to unbind.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, description="New display name.")
    repository_url: Optional[str] = Field(default=None, description="New repository URL; `null` clears it.")
    main_branch: Optional[str] = Field(default=None, description="New main branch; `null` clears it.")
    project: Optional[str] = Field(default=None, description="Project slug or id to bind; `null` unbinds.")
    consumer_id: Optional[str] = Field(default=None, description="Consumer id to bind; `null` unbinds.")


class PacticipantVersionInput(BaseModel):
    """What a build reports when it records a version.

    Attributes:
        build_url: http(s) URL of the CI build. Kept only when this request creates the version.
        branch: The repository branch the version was built from.
        tags: Tags to put on the version.
    """

    model_config = ConfigDict(extra="forbid")

    build_url: Optional[str] = Field(
        default=None,
        description="http(s) URL of the CI build. Stored only when this request creates the version.",
        examples=["https://ci.example.com/builds/4812"],
    )
    branch: Optional[str] = Field(
        default=None, description="The repository branch this version was built from.", examples=["main"]
    )
    tags: List[str] = Field(
        default_factory=list, description="Tags to put on the version (at most 50).", examples=[["prod"]]
    )


# ---------------------------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------------------------


class PacticipantRecord(BaseModel):
    """A stored pacticipant.

    Attributes:
        id: Row id.
        tenant_id: Owning tenant.
        slug: Stable handle.
        name: Display name.
        repository_url: Source repository URL.
        main_branch: The branch read by default.
        project_id: Bound project, when this is a provider described in Apiome.
        consumer_id: Bound consumer-registry row, when this is a registered consumer.
        created_at: When it was registered.
        updated_at: When it was last changed.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    tenant_id: str
    slug: str
    name: str
    repository_url: Optional[str] = None
    main_branch: Optional[str] = None
    project_id: Optional[str] = None
    consumer_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class PacticipantVersionRecord(BaseModel):
    """A stored pacticipant version.

    Attributes:
        id: Row id.
        pacticipant_id: Owning pacticipant.
        number: The version string, as the build reported it.
        seq: Order of recording; a higher value was recorded later.
        build_url: The CI build that produced it.
        branches: Branches it was recorded on, by name.
        tags: Its tags, by name.
        created_by: The user who recorded it, when still known.
        actor_label: Who recorded it, as text.
        created_at: When it was recorded.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    pacticipant_id: str
    number: str
    seq: int = Field(description="Order of recording; a higher value was recorded later.")
    build_url: Optional[str] = None
    branches: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    created_by: Optional[str] = None
    actor_label: Optional[str] = None
    created_at: Optional[str] = None


class PacticipantBranchRecord(BaseModel):
    """A stored branch and its head.

    Attributes:
        id: Row id.
        pacticipant_id: Owning pacticipant.
        name: The branch, as git names it.
        head_version_id: Id of the latest version recorded on it.
        head_version: That version's number.
        is_main: Whether this is the pacticipant's main branch.
        created_at: When a version was first recorded on it.
        updated_at: When the head last moved.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    pacticipant_id: str
    name: str
    head_version_id: str
    head_version: str = Field(description="Number of the latest version recorded on this branch.")
    is_main: bool = Field(default=False, description="Whether this is the pacticipant's main branch.")
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class RecordedPacticipantVersion(BaseModel):
    """The outcome of recording a version.

    Attributes:
        version: The version as stored, with every branch and tag it now has.
        created: Whether this request created the version (false: it already existed, unchanged).
        head_moved: Whether the named branch's head moved to this version.
        branch_created: Whether the named branch did not exist before this request.
    """

    model_config = ConfigDict(extra="forbid")

    version: PacticipantVersionRecord
    created: bool = Field(description="False when the version already existed; it is returned unchanged.")
    head_moved: bool = Field(
        default=False, description="Whether the branch named in the request now has this version as its head."
    )
    branch_created: bool = Field(
        default=False, description="Whether this request recorded the first version on the named branch."
    )


def _iso(value: Any) -> Optional[str]:
    """Render a timestamp column as ISO-8601 text (``None`` stays ``None``)."""
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)


def _optional_id(value: Any) -> Optional[str]:
    """Render a nullable id column as text."""
    return str(value) if value else None


def pacticipant_record_from_row(row: Dict[str, Any]) -> PacticipantRecord:
    """Adapt a ``pacticipant`` row into its record.

    Args:
        row: The row as :mod:`app.pacticipant_store` selects it.

    Returns:
        The record.
    """
    return PacticipantRecord(
        id=str(row.get("id")),
        tenant_id=str(row.get("tenant_id")),
        slug=str(row.get("slug") or ""),
        name=str(row.get("name") or ""),
        repository_url=row.get("repository_url"),
        main_branch=row.get("main_branch"),
        project_id=_optional_id(row.get("project_id")),
        consumer_id=_optional_id(row.get("consumer_id")),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
    )


def version_record_from_row(row: Dict[str, Any]) -> PacticipantVersionRecord:
    """Adapt a ``pacticipant_version`` row (with its ``branches`` and ``tags``) into its record.

    Args:
        row: The row as :mod:`app.pacticipant_store` selects it.

    Returns:
        The record.
    """
    return PacticipantVersionRecord(
        id=str(row.get("id")),
        pacticipant_id=str(row.get("pacticipant_id")),
        number=str(row.get("number") or ""),
        seq=int(row.get("seq") or 0),
        build_url=row.get("build_url"),
        branches=[str(name) for name in row.get("branches") or []],
        tags=[str(name) for name in row.get("tags") or []],
        created_by=_optional_id(row.get("created_by")),
        actor_label=row.get("actor_label"),
        created_at=_iso(row.get("created_at")),
    )


def branch_record_from_row(row: Dict[str, Any]) -> PacticipantBranchRecord:
    """Adapt a ``pacticipant_branch`` row (joined to its head version) into its record.

    Args:
        row: The row as :mod:`app.pacticipant_store` selects it.

    Returns:
        The record.
    """
    return PacticipantBranchRecord(
        id=str(row.get("id")),
        pacticipant_id=str(row.get("pacticipant_id")),
        name=str(row.get("name") or ""),
        head_version_id=str(row.get("head_version_id")),
        head_version=str(row.get("head_version") or ""),
        is_main=bool(row.get("is_main")),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
    )
