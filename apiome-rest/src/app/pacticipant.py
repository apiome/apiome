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

**A name can change; old names keep resolving** (PFX-8.10, #7307). ``name`` is the name pacts use.
Renaming a pacticipant keeps its handle and records the handle each name reduces to as an
*alias*, so a pact published under any name it has had still lands on it. ``display_name`` is
what people read, optional, and never what pacts use.

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
    "CODE_INVALID_LABEL",
    "CODE_INVALID_REASON",
    "CODE_LABEL_NOT_FOUND",
    "CODE_INVALID_NAME",
    "CODE_INVALID_SLUG",
    "CODE_INVALID_TAG",
    "CODE_INVALID_URL",
    "CODE_INVALID_VERSION",
    "CODE_NOT_FOUND",
    "CODE_PROJECT_NOT_FOUND",
    "CODE_NOT_DELETED",
    "CODE_RESTORE_CONFLICT",
    "CODE_SLUG_TAKEN",
    "CODE_VERSION_IN_USE",
    "CODE_VERSION_NOT_FOUND",
    "DELETE_CAUSES",
    "MAX_LABEL_LENGTH",
    "MAX_REASON_LENGTH",
    "MAX_TAGS_PER_REQUEST",
    "MAX_URL_LENGTH",
    "PacticipantBranchRecord",
    "PacticipantInput",
    "PacticipantLabelRecord",
    "PacticipantPatch",
    "PacticipantRecord",
    "PacticipantValidationError",
    "RecordedPacticipantVersion",
    "PacticipantVersionInput",
    "PacticipantVersionRecord",
    "branch_record_from_row",
    "pacticipant_record_from_row",
    "slugify_pacticipant_name",
    "label_record_from_row",
    "validate_branch",
    "validate_display_name",
    "validate_label",
    "validate_name",
    "validate_reason",
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
# PFX-1.11 (#6924): labels, soft delete and restore.
CODE_INVALID_LABEL = "pacticipant-invalid-label"
CODE_LABEL_NOT_FOUND = "pacticipant-label-not-found"
CODE_INVALID_REASON = "pacticipant-invalid-reason"
CODE_NOT_DELETED = "pacticipant-not-deleted"
CODE_RESTORE_CONFLICT = "pacticipant-restore-conflict"
CODE_VERSION_IN_USE = "pacticipant-version-in-use"

#: Longest version number, branch name, tag and display name (V432: ``VARCHAR(255)``).
MAX_LABEL_LENGTH = 255
#: Longest repository or build URL (V432's URL checks).
MAX_URL_LENGTH = 2048
#: Most tags one "record a version" request may carry.
MAX_TAGS_PER_REQUEST = 50
#: Longest reason a delete may carry (V437's ``delete_reason`` checks).
MAX_REASON_LENGTH = 500

#: Why a version was deleted (V437's ``pacticipant_version_delete_cause_check``): on its own, with
#: its pacticipant (and restored with it), or by a retention run.
DELETE_CAUSES = ("version", "pacticipant", "retention")

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


def validate_display_name(display_name: Optional[str]) -> Optional[str]:
    """Return a trimmed display name, ``None`` for a blank one (clears it), or refuse.

    Args:
        display_name: The candidate display name.

    Returns:
        The trimmed text, or ``None``.

    Raises:
        PacticipantValidationError: ``pacticipant-invalid-name`` when it is too long.
    """
    candidate = (display_name or "").strip()
    if not candidate:
        return None
    if len(candidate) > MAX_LABEL_LENGTH:
        raise PacticipantValidationError(
            CODE_INVALID_NAME, f"a pacticipant display name is at most {MAX_LABEL_LENGTH} characters"
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


def validate_label(name: Optional[str]) -> str:
    """Return a pacticipant label unchanged, or refuse with ``pacticipant-invalid-label``.

    Args:
        name: The label (``team-billing``).

    Returns:
        The label.

    Raises:
        PacticipantValidationError: When the label is not storable (V437's
            ``pacticipant_label_name_check``).
    """
    return _validate_label(name, code=CODE_INVALID_LABEL, what="label")


def validate_reason(reason: Optional[str]) -> Optional[str]:
    """Return a delete reason, trimmed, or ``None`` when none was given.

    Args:
        reason: Why the caller is deleting something, as they wrote it.

    Returns:
        The trimmed reason, or ``None`` for an absent or blank one.

    Raises:
        PacticipantValidationError: ``pacticipant-invalid-reason`` when it is longer than
            :data:`MAX_REASON_LENGTH` or carries a control character other than a line break,
            carriage return or tab.
    """
    if reason is None:
        return None
    candidate = str(reason).strip()
    if not candidate:
        return None
    if len(candidate) > MAX_REASON_LENGTH or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", candidate):
        raise PacticipantValidationError(
            CODE_INVALID_REASON,
            f"a delete reason is at most {MAX_REASON_LENGTH} characters with no control characters",
        )
    return candidate


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
        name: The name pacts use, as a Pact file or a person writes it.
        slug: The handle; derived from ``name`` when omitted, and never editable.
        display_name: What people read, when it differs from ``name``.
        repository_url: http(s) URL of the application's source repository.
        main_branch: The branch read by default when a query names none.
        project: Slug or id of the Apiome project that describes this provider.
        consumer_id: Id of this application's row in the consumer registry.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        description="The name pacts use, as a Pact file or a person writes it.", examples=["Billing Service"]
    )
    slug: Optional[str] = Field(
        default=None,
        description="The handle URLs and CI name. Derived from `name` when omitted; not editable afterwards.",
        examples=["billing-service"],
    )
    display_name: Optional[str] = Field(
        default=None, description="What people read, when it differs from `name`.", examples=["Billing (EU)"]
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
        name: New name pacts use (cannot be cleared). Renaming keeps the handle and the history;
            the old name and the new one both resolve to this pacticipant afterwards.
        display_name: New display name, or ``null`` to clear it.
        repository_url: New repository URL, or ``null`` to clear it.
        main_branch: New main branch, or ``null`` to clear it.
        project: Slug or id of the project to bind, or ``null`` to unbind.
        consumer_id: Id of the consumer to bind, or ``null`` to unbind.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(
        default=None,
        description=(
            "Rename: the new name pacts use. The handle and the history stay; the old name keeps "
            "resolving. `409 pacticipant-slug-taken` when another pacticipant has that name."
        ),
    )
    display_name: Optional[str] = Field(default=None, description="New display name; `null` clears it.")
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
        name: The name pacts use.
        display_name: What people read; ``None`` reads as ``name``.
        aliases: The other names it has had, oldest first; each still resolves to it.
        repository_url: Source repository URL.
        main_branch: The branch read by default.
        project_id: Bound project, when this is a provider described in Apiome.
        consumer_id: Bound consumer-registry row, when this is a registered consumer.
        labels: Its labels, by name.
        created_at: When it was registered.
        updated_at: When it was last changed.
        deleted_at: When it was deleted; ``None`` while it is live.
        deleted_by_label: Who deleted it, as text.
        delete_reason: Why, as the caller said.
        purge_after: When the deleted pacticipant is removed for good, unless restored first.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    tenant_id: str
    slug: str
    name: str
    display_name: Optional[str] = Field(default=None, description="What people read; null reads as `name`.")
    aliases: List[str] = Field(
        default_factory=list,
        description="Other names it has had (PFX-8.10), oldest first. Each still resolves to this pacticipant.",
    )
    repository_url: Optional[str] = None
    main_branch: Optional[str] = None
    project_id: Optional[str] = None
    consumer_id: Optional[str] = None
    labels: List[str] = Field(default_factory=list, description="Its labels, by name.")
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    deleted_at: Optional[str] = Field(default=None, description="When it was deleted; null while it is live.")
    deleted_by_label: Optional[str] = Field(default=None, description="Who deleted it.")
    delete_reason: Optional[str] = Field(default=None, description="Why it was deleted.")
    purge_after: Optional[str] = Field(
        default=None, description="When a deleted pacticipant is removed for good, unless it is restored first."
    )


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
        deleted_at: When it was deleted; ``None`` while it is live.
        deleted_by_label: Who deleted it, as text.
        delete_reason: Why, as the caller said.
        delete_cause: ``version``, ``pacticipant`` or ``retention`` (see :data:`DELETE_CAUSES`).
        purge_after: When the deleted version is removed for good, unless restored first.
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
    deleted_at: Optional[str] = Field(default=None, description="When it was deleted; null while it is live.")
    deleted_by_label: Optional[str] = Field(default=None, description="Who deleted it.")
    delete_reason: Optional[str] = Field(default=None, description="Why it was deleted.")
    delete_cause: Optional[str] = Field(
        default=None,
        description="`version` (deleted on its own), `pacticipant` (with its pacticipant) or `retention`.",
    )
    purge_after: Optional[str] = Field(
        default=None, description="When a deleted version is removed for good, unless it is restored first."
    )


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


class PacticipantLabelRecord(BaseModel):
    """A label on a pacticipant.

    Attributes:
        name: The label.
        pacticipant_id: The labelled pacticipant.
        pacticipant_slug: Its handle.
        pacticipant_name: Its display name.
        created_at: When the label was added.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    pacticipant_id: str
    pacticipant_slug: str
    pacticipant_name: str
    created_at: Optional[str] = None


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


def _other_names(aliases: Any, name: str) -> List[str]:
    """The names a pacticipant had, without the one it has now, each once, oldest first.

    Args:
        aliases: The ``aliases`` column (alias names, oldest first), or ``None``.
        name: Its current name.

    Returns:
        The other names.
    """
    current = slugify_pacticipant_name(name)
    seen = {current}
    names: List[str] = []
    for alias in aliases or []:
        handle = slugify_pacticipant_name(str(alias))
        if handle not in seen:
            seen.add(handle)
            names.append(str(alias))
    return names


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
        display_name=row.get("display_name"),
        aliases=_other_names(row.get("aliases"), str(row.get("name") or "")),
        repository_url=row.get("repository_url"),
        main_branch=row.get("main_branch"),
        project_id=_optional_id(row.get("project_id")),
        consumer_id=_optional_id(row.get("consumer_id")),
        labels=[str(name) for name in row.get("labels") or []],
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
        deleted_at=_iso(row.get("deleted_at")),
        deleted_by_label=row.get("deleted_by_label"),
        delete_reason=row.get("delete_reason"),
        purge_after=_iso(row.get("purge_after")),
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
        deleted_at=_iso(row.get("deleted_at")),
        deleted_by_label=row.get("deleted_by_label"),
        delete_reason=row.get("delete_reason"),
        delete_cause=row.get("delete_cause"),
        purge_after=_iso(row.get("purge_after")),
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


def label_record_from_row(row: Dict[str, Any]) -> PacticipantLabelRecord:
    """Adapt a ``pacticipant_label`` row (joined to its pacticipant) into its record.

    Args:
        row: The row as :mod:`app.pacticipant_store` selects it.

    Returns:
        The record.
    """
    return PacticipantLabelRecord(
        name=str(row.get("name") or ""),
        pacticipant_id=str(row.get("pacticipant_id")),
        pacticipant_slug=str(row.get("pacticipant_slug") or ""),
        pacticipant_name=str(row.get("pacticipant_name") or ""),
        created_at=_iso(row.get("created_at")),
    )
