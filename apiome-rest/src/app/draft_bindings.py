"""Branch-to-draft bindings — the shared vocabulary of GNC-2.1 (#4737).

A **binding** makes one draft (unpublished) version the durable API review unit of one repository
ref: it pins tenant, project and version to a provider, repository, ref and source path, and
remembers the **source digest** of the files that selection resolved to at a commit. Importing a
repository file produces a snapshot; binding produces a relationship that later pushes have
somewhere to land.

Nothing a provider reports ever rewrites a draft. An observed movement of a bound ref becomes a
**sync candidate** — a pending row naming the commit and digest the binding was at and the commit
the ref moved to — which somebody (GNC-2.3's three-way synchronization, or a person) then applies
or dismisses. A candidate settles exactly once.

This module holds only data and pure functions: the stable refusal codes, the refusal exception,
the digest, and the request/response models the routes (:mod:`app.draft_binding_routes`) and the
store (:mod:`app.draft_binding_store`) share. The storage lives in apiome-db V264.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import List, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AUDIT_BOUND",
    "AUDIT_CANDIDATE_RAISED",
    "AUDIT_CANDIDATE_RESOLVED",
    "AUDIT_REBOUND",
    "AUDIT_RELEASED",
    "CANDIDATE_ORIGINS",
    "CANDIDATE_STATUSES",
    "CODE_ALREADY_BOUND",
    "CODE_CANDIDATE_NOT_FOUND",
    "CODE_CANDIDATE_RESOLVED",
    "CODE_CONFLICT",
    "CODE_INVALID_SOURCE",
    "CODE_NOT_FOUND",
    "CODE_PROJECT_NOT_FOUND",
    "CODE_RELEASED",
    "CODE_REPOSITORY_FORBIDDEN",
    "CODE_REPOSITORY_NOT_FOUND",
    "CODE_REPOSITORY_UNREACHABLE",
    "CODE_UNCHANGED",
    "CODE_VERSION_NOT_FOUND",
    "CODE_VERSION_PUBLISHED",
    "CandidateOrigin",
    "CandidateStatus",
    "DraftBindingCreate",
    "DraftBindingDetail",
    "DraftBindingRecord",
    "DraftBindingValidationError",
    "MAX_NOTE_LENGTH",
    "MAX_PATH_LENGTH",
    "MAX_REF_LENGTH",
    "ORIGIN_MANUAL",
    "ORIGIN_SWEEP",
    "ORIGIN_WEBHOOK",
    "PROVIDERS",
    "RELEASE_REASONS",
    "RELEASE_REASON_REPOSITORY_REMOVED",
    "RELEASE_REASON_REPLACED",
    "RELEASE_REASON_UNBOUND",
    "ReleaseReason",
    "ResolvableStatus",
    "STATUS_APPLIED",
    "STATUS_DISMISSED",
    "STATUS_PENDING",
    "STATUS_SUPERSEDED",
    "SyncCandidateRecord",
    "SyncCandidateResolve",
    "VersionBindingStatus",
    "browse_url",
    "normalize_path",
    "normalize_ref",
    "normalize_repo_full_name",
    "source_digest",
]

#: The longest resolution / release note, in characters.
MAX_NOTE_LENGTH = 2_000

#: Mirrors ``draft_repository_bindings.ref VARCHAR(255)``.
MAX_REF_LENGTH = 255

#: A path or glob selecting the source inside the repository. The column is TEXT; this is the bound
#: a request is held to, so a pathological selector never reaches the provider client.
MAX_PATH_LENGTH = 1_024

#: Providers a binding may name. Mirrors the V264 CHECK; only ``github`` can be read today
#: (:mod:`app.git_intake`), and the other two are accepted so GNC-2.2's adapters need no migration.
PROVIDERS = ("github", "gitlab", "bitbucket")

#: Why an active binding stopped being one. Mirrors the V264 CHECK.
RELEASE_REASON_REPLACED = "replaced"
RELEASE_REASON_UNBOUND = "unbound"
RELEASE_REASON_REPOSITORY_REMOVED = "repository_removed"
RELEASE_REASONS = (
    RELEASE_REASON_REPLACED,
    RELEASE_REASON_UNBOUND,
    RELEASE_REASON_REPOSITORY_REMOVED,
)

#: How a candidate was raised. Mirrors the V264 CHECK.
ORIGIN_WEBHOOK = "webhook"
ORIGIN_MANUAL = "manual"
ORIGIN_SWEEP = "sweep"
CANDIDATE_ORIGINS = (ORIGIN_WEBHOOK, ORIGIN_MANUAL, ORIGIN_SWEEP)

#: A candidate's states. Mirrors the V264 CHECK.
STATUS_PENDING = "pending"
STATUS_APPLIED = "applied"
STATUS_DISMISSED = "dismissed"
STATUS_SUPERSEDED = "superseded"
CANDIDATE_STATUSES = (STATUS_PENDING, STATUS_APPLIED, STATUS_DISMISSED, STATUS_SUPERSEDED)

#: ``workflow_audit`` actions, written inside the transaction of the change they record.
AUDIT_BOUND = "binding.bound"
AUDIT_REBOUND = "binding.rebound"
AUDIT_RELEASED = "binding.released"
AUDIT_CANDIDATE_RAISED = "binding.sync_candidate"
AUDIT_CANDIDATE_RESOLVED = "binding.sync_resolved"

# Stable refusal codes. A client branches on the code, never on the message.
CODE_PROJECT_NOT_FOUND = "binding-project-not-found"
CODE_VERSION_NOT_FOUND = "binding-version-not-found"
CODE_NOT_FOUND = "binding-not-found"
#: Only a draft (unpublished) version can be bound.
CODE_VERSION_PUBLISHED = "binding-version-published"
#: The version already has an active binding; release it, or bind with ``replace``.
CODE_ALREADY_BOUND = "binding-already-bound"
#: The named registered repository is not this tenant's, or the provider has no such repository.
CODE_REPOSITORY_NOT_FOUND = "binding-repository-not-found"
#: No stored credential grants the acting user a read of that repository at that ref.
CODE_REPOSITORY_FORBIDDEN = "binding-repository-forbidden"
#: The provider could not be reached, or refused the read for a transport reason.
CODE_REPOSITORY_UNREACHABLE = "binding-repository-unreachable"
#: The selection resolves to nothing, to more than the intake budget allows, or the URL names a
#: provider git intake cannot read.
CODE_INVALID_SOURCE = "binding-invalid-source"
#: The binding has been released; it is history and accepts no changes.
CODE_RELEASED = "binding-released"
#: A manual check found the ref exactly where the binding already is.
CODE_UNCHANGED = "binding-unchanged"
CODE_CANDIDATE_NOT_FOUND = "binding-candidate-not-found"
#: The candidate already settled; settlements are immutable.
CODE_CANDIDATE_RESOLVED = "binding-candidate-resolved"
#: Someone else changed the binding between the read and the write; read it again and retry.
CODE_CONFLICT = "binding-conflict"

CandidateOrigin = Literal["webhook", "manual", "sweep"]
CandidateStatus = Literal["pending", "applied", "dismissed", "superseded"]
ReleaseReason = Literal["replaced", "unbound", "repository_removed"]
ResolvableStatus = Literal["applied", "dismissed"]


class DraftBindingValidationError(Exception):
    """A refusal from the binding store, carrying a stable code.

    Attributes:
        code: One of the ``CODE_*`` constants in this module.
    """

    def __init__(self, code: str, message: str) -> None:
        """Create the refusal.

        Args:
            code: The stable refusal code.
            message: A human-readable explanation.
        """
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------------------------


def source_digest(members: Mapping[str, str]) -> str:
    """Return a stable ``sha256:`` digest of a repository selection's contents.

    Every member's path *and* body feed the hash, length-prefixed and NUL-separated, so that
    renaming a file, moving content between two files, or adding an empty one all change the
    digest — none of which a hash of the concatenated bodies would catch. Paths are hashed in
    sorted order so the digest depends only on the selection, never on the order the provider
    listed its tree in.

    Args:
        members: Selection-relative path -> file text, as :func:`app.git_intake.fetch_git_fileset`
            returns them.

    Returns:
        ``"sha256:<hex>"`` — the spelling ``app.version_quality_capture.openapi_source_fingerprint``
        uses, so the two fingerprints are never mistaken for one another's format.
    """
    digest = hashlib.sha256()
    for path in sorted(members):
        body = members[path].encode("utf-8")
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(body)).encode("ascii"))
        digest.update(b"\0")
        digest.update(body)
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def normalize_ref(raw: Optional[str]) -> str:
    """Return a ref as it is stored: trimmed, with any ``refs/heads/`` prefix removed.

    A webhook delivery reports ``refs/heads/main`` while a person types ``main``; storing the short
    form is what lets the two be matched with an equality test.

    Args:
        raw: The ref as given.

    Returns:
        The short ref, or ``""`` when there is none.
    """
    text = (raw or "").strip()
    for prefix in ("refs/heads/", "refs/tags/"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    return text.strip("/")


def normalize_path(raw: Optional[str]) -> str:
    """Return a source path as it is stored: trimmed, without leading or trailing slashes.

    Args:
        raw: The path or glob as given.

    Returns:
        The normalized selector; ``""`` selects the whole tree.
    """
    return (raw or "").strip().strip("/")


def normalize_repo_full_name(owner: str, repo: str) -> str:
    """Return the lowercased ``owner/name`` a webhook delivery is matched against.

    Args:
        owner: Repository owner or organisation.
        repo: Repository name.

    Returns:
        ``"owner/name"``, lowercased.
    """
    return f"{(owner or '').strip()}/{(repo or '').strip()}".lower()


def browse_url(provider: str, repo_url: str, commit_sha: str, path: str) -> Optional[str]:
    """Build the human URL for a binding's source at a commit.

    Args:
        provider: The provider key.
        repo_url: The canonical repository URL.
        commit_sha: The commit to link at.
        path: The binding's path; a glob is dropped, since no provider can browse one.

    Returns:
        The URL, or ``None`` for a provider whose browse layout is not known here.
    """
    base = (repo_url or "").rstrip("/")
    sha = (commit_sha or "").strip()
    if not base or not sha:
        return None
    static = normalize_path(path)
    if any(token in static for token in ("*", "?", "[")):
        static = static.split("*", 1)[0].split("?", 1)[0].split("[", 1)[0].rstrip("/")
    if provider == "github":
        return f"{base}/tree/{sha}/{static}" if static else f"{base}/tree/{sha}"
    if provider == "gitlab":
        return f"{base}/-/tree/{sha}/{static}" if static else f"{base}/-/tree/{sha}"
    if provider == "bitbucket":
        return f"{base}/src/{sha}/{static}" if static else f"{base}/src/{sha}"
    return None


# ---------------------------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------------------------


class DraftBindingRecord(BaseModel):
    """One stored binding — active or released."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The binding id.")
    tenant_id: str
    project_id: str
    version_id: str = Field(description="The bound draft version (revision).")
    version_label: Optional[str] = Field(default=None, description="The version's label, e.g. `1.2.0`.")
    repository_id: Optional[str] = Field(
        default=None,
        description=(
            "The registered tenant repository the binding was authorized through; null once that "
            "registration is removed, which leaves the binding readable but unusable."
        ),
    )
    provider: str = Field(description="`github`, `gitlab`, or `bitbucket`.")
    repo_full_name: str = Field(description="Lowercased `owner/name`.")
    repo_url: str = Field(description="Canonical repository URL.")
    ref: str = Field(description="Branch or tag the draft is the review unit of.")
    path: str = Field(default="", description="Path or glob selecting the source; empty is the whole tree.")
    commit_sha: str = Field(description="Commit the binding is currently synchronized with.")
    source_digest: str = Field(description="`sha256:` digest of the selected source at `commit_sha`.")
    synchronized_at: datetime = Field(description="When `commit_sha` / `source_digest` last moved.")
    browse_url: Optional[str] = Field(
        default=None, description="Human URL for the bound source at `commit_sha`."
    )
    active: bool = Field(description="True while this is the draft's binding.")
    created_by: Optional[str] = Field(default=None, description="Who bound it; null once that user is deleted.")
    created_by_name: Optional[str] = Field(default=None, description="Their display name.")
    created_at: datetime
    updated_at: datetime
    released_at: Optional[datetime] = Field(
        default=None, description="When it stopped being the draft's binding; null while it is."
    )
    released_by: Optional[str] = Field(default=None, description="Who released it.")
    release_reason: Optional[ReleaseReason] = Field(
        default=None, description="`replaced`, `unbound`, or `repository_removed`."
    )
    pending_candidate_count: int = Field(
        default=0, ge=0, description="Outstanding sync candidates on this binding."
    )


class SyncCandidateRecord(BaseModel):
    """One observed movement of a bound ref."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The candidate id.")
    binding_id: str
    tenant_id: str
    ref: str = Field(description="The ref the movement was seen on.")
    from_commit_sha: str = Field(description="The binding's synchronized commit when it was observed.")
    from_digest: str = Field(description="The binding's source digest when it was observed.")
    to_commit_sha: str = Field(description="The commit the ref now points at.")
    to_digest: Optional[str] = Field(
        default=None,
        description=(
            "Digest of the selected source at `to_commit_sha`; null until that source has been "
            "read, because a provider delivery names a commit and not a document."
        ),
    )
    origin: CandidateOrigin = Field(description="`webhook`, `manual`, or `sweep`.")
    delivery_id: Optional[str] = Field(default=None, description="Provider delivery that raised it.")
    status: CandidateStatus = Field(description="`pending`, `applied`, `dismissed`, or `superseded`.")
    detected_at: datetime
    detected_by: Optional[str] = Field(default=None, description="Who raised it, for a manual check.")
    detected_by_name: Optional[str] = Field(default=None, description="Their display name.")
    resolved_at: Optional[datetime] = Field(default=None, description="When it settled; null while pending.")
    resolved_by: Optional[str] = Field(default=None, description="Who settled it.")
    resolved_by_name: Optional[str] = Field(default=None, description="Their display name.")
    resolution_note: Optional[str] = Field(default=None, description="Why, in the resolver's words.")


class DraftBindingDetail(BaseModel):
    """A binding with what is outstanding on it and what has already been settled."""

    model_config = ConfigDict(extra="forbid")

    binding: DraftBindingRecord
    pending: List[SyncCandidateRecord] = Field(
        default_factory=list, description="Outstanding sync candidates, newest first."
    )
    history: List[SyncCandidateRecord] = Field(
        default_factory=list,
        description="Settled candidates, newest first — applied, dismissed, and superseded.",
    )


class VersionBindingStatus(BaseModel):
    """Where one version stands with respect to a repository."""

    model_config = ConfigDict(extra="forbid")

    version_id: str
    version_label: Optional[str] = None
    published: bool = Field(description="Published versions cannot be bound; an existing binding stays readable.")
    bound: bool = Field(description="Whether the version has an active binding.")
    binding: Optional[DraftBindingDetail] = Field(
        default=None, description="The active binding, when there is one."
    )
    released: List[DraftBindingRecord] = Field(
        default_factory=list, description="Previously active bindings, newest first."
    )


# ---------------------------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------------------------


class DraftBindingCreate(BaseModel):
    """Bind a draft version to a repository ref and source path.

    Exactly one of ``repository_id`` and ``repo_url`` identifies the repository: a registered
    tenant repository (whose stored linked-account credential authorizes the read) or a URL, for a
    public repository or one the caller's own linked account can reach. A credential is never
    accepted in the body.
    """

    model_config = ConfigDict(extra="forbid")

    repository_id: Optional[str] = Field(
        default=None, description="Registered tenant repository to bind to."
    )
    repo_url: Optional[str] = Field(
        default=None, description="Repository URL, when no registered repository is used."
    )
    ref: Optional[str] = Field(
        default=None,
        max_length=MAX_REF_LENGTH,
        description="Branch or tag; defaults to the repository's default branch.",
    )
    path: str = Field(
        default="",
        max_length=MAX_PATH_LENGTH,
        description="Path or glob selecting the source; empty selects the whole tree.",
    )
    linked_account_id: Optional[str] = Field(
        default=None,
        description="The caller's own linked account whose stored token authorizes the read.",
    )
    replace: bool = Field(
        default=False,
        description=(
            "Release the version's current binding and bind it anew. Without it a version that is "
            "already bound is refused with `binding-already-bound`."
        ),
    )


class SyncCandidateResolve(BaseModel):
    """Settle an outstanding sync candidate.

    Attributes:
        status: ``applied`` — the draft is now in sync with the candidate's commit, so the
            binding's synchronized pair advances to it — or ``dismissed``, which leaves the
            binding exactly where it is.
        note: Why, kept with the settled row.
    """

    model_config = ConfigDict(extra="forbid")

    status: ResolvableStatus
    note: Optional[str] = Field(default=None, max_length=MAX_NOTE_LENGTH)
