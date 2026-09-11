"""Where a project's SDK is delivered — SDK-4.2 (#4496).

Git delivery commits a regenerated SDK to a tenant's own repository and opens a pull request, so
their normal review and CI apply. This module owns the *configuration* half of that: which
repository a project's SDK for one ecosystem goes to, which branch the pull request targets, and
which directory inside the repository the SDK lives in — plus the naming rule that turns a
delivery into a branch.

**No new credential type.** A target names a repository that is already registered with Apiome
(``tenant_repositories``), and a delivery authenticates with that repository's *existing*
linked-account integration — the same token repository scanning and webhook provisioning already
use (:func:`app.repository_webhook_rotation.resolve_linked_account_token`). That is why a target can
only name a repository that was registered through a linked account: one registered from a public
URL holds no credential, and the fix is to register it through an account rather than to paste a
token somewhere new.

**GitHub only, because that is where the integration is.** Registering a repository through a
linked account is GitHub-only today (``create_tenant_repository`` refuses anything else), so a
target that names a GitLab or Bitbucket repository is refused with the reason, not accepted and
left to fail on first delivery.

**One branch per (version, project, ecosystem).** The ticket's branch is
``apiome/sdk-regen-<version>``, and its idempotency key is *(version, target, options)*. Several
projects — or one project's npm and PyPI SDKs — may deliver into one repository, so a branch named
after the version alone would let them overwrite each other's pull requests. The branch therefore
carries the project and the ecosystem as well: ``apiome/sdk-regen-1.4.2-widgets-npm``. Options
(SDK-3.4 branding, the base branch, the path) change a pull request's *content*, never its identity
— re-running after changing them updates the same pull request rather than stacking a second one.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .database import db
from .revision_deprecation import is_uuid_string
from .sdk_publish_version import PUBLISH_ECOSYSTEMS

logger = logging.getLogger(__name__)

__all__ = [
    "BRANCH_MAX_CHARS",
    "BRANCH_PREFIX",
    "DELIVERY_ECOSYSTEMS",
    "GIT_DELIVERY_TARGET_SCHEMA_VERSION",
    "SUPPORTED_PROVIDERS",
    "TARGET_PATH_MAX_CHARS",
    "DeliveryTarget",
    "GitDeliveryTargetError",
    "GitDeliveryTargetOut",
    "TargetProblem",
    "branch_pattern",
    "delete_target",
    "list_targets",
    "normalize_base_branch",
    "normalize_ecosystem",
    "normalize_target_path",
    "parse_repository_full_name",
    "ref_name_problem",
    "ref_segment",
    "regen_branch_name",
    "repository_problem",
    "resolve_target",
    "save_target",
]

#: The shape of a target as the API describes it.
GIT_DELIVERY_TARGET_SCHEMA_VERSION = "sdk.git-delivery-target.v1"

#: The SDK-4.1 packaging layouts a delivery commits. ``gomod`` has no SDK-4.1 layout, so there is
#: nothing to commit for it yet.
DELIVERY_ECOSYSTEMS: Tuple[str, ...] = PUBLISH_ECOSYSTEMS

#: Repository providers a pull request can be opened on. See the module docstring for why.
SUPPORTED_PROVIDERS: Tuple[str, ...] = ("github",)

#: Every delivery branch starts with this, so a repository owner can protect, filter or clean up
#: Apiome's branches with one pattern.
BRANCH_PREFIX = "apiome/sdk-regen-"

#: Longest branch name a delivery will use. Git allows longer, but GitHub's UI and many CI systems
#: truncate well before it, and a name nobody can read is a name nobody can find.
BRANCH_MAX_CHARS = 200

#: Longest repository-relative target path accepted.
TARGET_PATH_MAX_CHARS = 512

#: How much of the version line and the project slug a branch keeps, each.
_BRANCH_SEGMENT_MAX_CHARS = 60

#: Characters git forbids anywhere in a ref name (``git check-ref-format``), plus whitespace.
_REF_ILLEGAL = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]")

#: Everything outside this set becomes ``-`` when a value is turned into a branch segment.
_SEGMENT_UNSAFE = re.compile(r"[^a-z0-9._-]+")

#: Control characters, which have no business in a repository path.
_PATH_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

#: ``owner/repo`` as GitHub spells it.
_FULL_NAME = re.compile(r"^([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100})$")


class GitDeliveryTargetError(ValueError):
    """Raised when a delivery target cannot be accepted.

    Attributes:
        errors: One message per problem, so a form can mark every bad field at once.
        code: A stable reason when a single, named refusal caused it (an ineligible repository);
            ``None`` for ordinary field validation.
    """

    def __init__(self, *errors: str, code: Optional[str] = None) -> None:
        self.errors: List[str] = [str(error) for error in errors if error]
        self.code = code
        super().__init__("; ".join(self.errors) or "invalid git delivery target")


@dataclass(frozen=True)
class TargetProblem:
    """Why a target cannot deliver right now.

    Attributes:
        code: A stable, machine-readable reason (``sdk-git-delivery-repository-unlinked``…).
        message: What is wrong and what to do about it.
    """

    code: str
    message: str


@dataclass(frozen=True)
class DeliveryTarget:
    """A resolved target, as the pipeline consumes it.

    Attributes:
        target_id: The configuration row.
        ecosystem: ``npm`` or ``pypi``.
        repository_id: The registered repository to deliver into.
        base_branch: The pull request's base, or ``None`` for the repository's default branch.
        target_path: The normalised directory inside the repository (``''`` for the root).
    """

    target_id: Optional[str]
    ecosystem: str
    repository_id: str
    base_branch: Optional[str]
    target_path: str


class GitDeliveryTargetOut(BaseModel):
    """A configured delivery target, as the API describes it.

    Attributes:
        schema_version: The projection's shape.
        ecosystem: ``npm`` or ``pypi``.
        repository_id: The registered repository.
        repository_full_name: ``owner/repo``, or ``None`` when the repository has been removed.
        repository_provider: Where the repository is hosted.
        base_branch: The configured base, or ``None`` for the repository's default branch.
        target_path: The directory the SDK is committed under (``''`` for the root).
        branch_pattern: The branch a delivery of this target uses, with ``{version}`` standing in
            for the version line.
        deliverable: Whether a delivery could run with this configuration now.
        problem: Why not, when it could not.
        created_at: When the target was first configured.
        updated_at: When it was last changed.
        updated_by: Who last changed it.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str = Field(
        default=GIT_DELIVERY_TARGET_SCHEMA_VERSION, serialization_alias="schemaVersion"
    )
    ecosystem: str
    repository_id: str = Field(serialization_alias="repositoryId")
    repository_full_name: Optional[str] = Field(
        default=None, serialization_alias="repositoryFullName"
    )
    repository_provider: Optional[str] = Field(
        default=None, serialization_alias="repositoryProvider"
    )
    base_branch: Optional[str] = Field(default=None, serialization_alias="baseBranch")
    target_path: str = Field(default="", serialization_alias="targetPath")
    branch_pattern: str = Field(serialization_alias="branchPattern")
    deliverable: bool = True
    problem: Optional[Dict[str, str]] = None
    created_at: Optional[datetime] = Field(default=None, serialization_alias="createdAt")
    updated_at: Optional[datetime] = Field(default=None, serialization_alias="updatedAt")
    updated_by: Optional[str] = Field(default=None, serialization_alias="updatedBy")


# -------------------------------------------------------------------------------------------
# Names
# -------------------------------------------------------------------------------------------


def ref_name_problem(name: str) -> Optional[str]:
    """Check a branch name against git's ref-name rules.

    The rules of ``git check-ref-format``, applied to what follows ``refs/heads/``: no control
    characters, whitespace, ``~ ^ : ? * [`` or ``\\``; no ``..`` and no ``@{``; no component that
    starts with ``.`` or ends with ``.lock``; no leading, trailing or doubled ``/``; no trailing
    ``.``; not ``@`` alone. A leading ``-`` is refused too — git accepts it, but every git command
    line would read it as an option.

    Args:
        name: The branch name.

    Returns:
        ``None`` when the name is legal, otherwise what is wrong with it.
    """
    if not name:
        return "a branch name cannot be empty"
    if len(name) > 255:
        return "a branch name cannot be longer than 255 characters"
    if _REF_ILLEGAL.search(name):
        return "a branch name cannot contain whitespace, control characters or any of ~ ^ : ? * [ \\"
    if ".." in name:
        return "a branch name cannot contain '..'"
    if "@{" in name:
        return "a branch name cannot contain '@{'"
    if name == "@":
        return "a branch name cannot be '@'"
    if name.startswith("-"):
        return "a branch name cannot start with '-'"
    if name.startswith("/") or name.endswith("/") or "//" in name:
        return "a branch name cannot start or end with '/' or contain '//'"
    if name.endswith("."):
        return "a branch name cannot end with '.'"
    for component in name.split("/"):
        if component.startswith("."):
            return "no part of a branch name can start with '.'"
        if component.endswith(".lock"):
            return "no part of a branch name can end with '.lock'"
    return None


def ref_segment(value: Optional[str], fallback: str, *, max_chars: int = _BRANCH_SEGMENT_MAX_CHARS) -> str:
    """Turn an arbitrary label into one legal, readable piece of a branch name.

    Lower-cased (a repository cloned onto a case-insensitive filesystem cannot hold two branches
    that differ only in case), with every run of characters outside ``[a-z0-9._-]`` collapsed to
    ``-``, ``..`` collapsed to ``.``, and leading/trailing ``.``/``-`` and a trailing ``.lock``
    removed.

    Args:
        value: The label (a version line, a project slug, an ecosystem).
        fallback: What to use when nothing legal is left.
        max_chars: The longest the segment may be.

    Returns:
        A segment that is legal anywhere inside a ref component. ``1.4.2`` stays ``1.4.2``;
        ``Release 2 (beta)`` becomes ``release-2-beta``.
    """
    candidate = _SEGMENT_UNSAFE.sub("-", (value or "").strip().lower())
    candidate = re.sub(r"-{2,}", "-", candidate)
    while ".." in candidate:
        candidate = candidate.replace("..", ".")
    candidate = candidate[:max_chars]
    candidate = candidate.strip(".-")
    while candidate.endswith(".lock"):
        candidate = candidate[: -len(".lock")].strip(".-")
    return candidate or fallback


def regen_branch_name(version_line: Optional[str], project_slug: Optional[str], ecosystem: str) -> str:
    """The branch a delivery of one version, project and ecosystem is pushed to.

    Deterministic, so re-running a delivery finds the branch — and the pull request — it pushed
    last time. See the module docstring for why the project and ecosystem are part of it.

    Args:
        version_line: The revision's version label (``1.4.2``).
        project_slug: The project's slug (``widgets``).
        ecosystem: ``npm`` or ``pypi``.

    Returns:
        ``apiome/sdk-regen-1.4.2-widgets-npm``. Always a legal ref name of at most
        :data:`BRANCH_MAX_CHARS` characters.
    """
    name = (
        f"{BRANCH_PREFIX}{ref_segment(version_line, 'unversioned')}"
        f"-{ref_segment(project_slug, 'project')}-{ref_segment(ecosystem, 'sdk')}"
    )
    return name[:BRANCH_MAX_CHARS].rstrip(".-")


def branch_pattern(project_slug: Optional[str], ecosystem: str) -> str:
    """Describe a target's branch with the version left as a placeholder.

    Args:
        project_slug: The project's slug.
        ecosystem: ``npm`` or ``pypi``.

    Returns:
        ``apiome/sdk-regen-{version}-widgets-npm``.
    """
    return (
        f"{BRANCH_PREFIX}{{version}}-{ref_segment(project_slug, 'project')}"
        f"-{ref_segment(ecosystem, 'sdk')}"
    )


def parse_repository_full_name(full_name: Optional[str]) -> Tuple[str, str]:
    """Split ``owner/repo`` into its parts.

    Args:
        full_name: The repository's full name as registered.

    Returns:
        ``(owner, repo)``.

    Raises:
        ValueError: When the name is not a GitHub ``owner/repo``.
    """
    match = _FULL_NAME.match((full_name or "").strip())
    if not match:
        raise ValueError(f"{full_name!r} is not a GitHub owner/repo name")
    return match.group(1), match.group(2)


# -------------------------------------------------------------------------------------------
# Field validation
# -------------------------------------------------------------------------------------------


def normalize_ecosystem(ecosystem: Optional[str]) -> str:
    """Return the ecosystem key, or refuse.

    Args:
        ecosystem: The requested ecosystem.

    Returns:
        The lower-cased key.

    Raises:
        GitDeliveryTargetError: When the ecosystem has no SDK-4.1 packaging layout to commit.
    """
    key = (ecosystem or "").strip().lower()
    if key not in DELIVERY_ECOSYSTEMS:
        raise GitDeliveryTargetError(
            f"ecosystem must be one of {', '.join(DELIVERY_ECOSYSTEMS)}, got {ecosystem!r}. Git "
            "delivery commits the SDK-4.1 package layout, which exists for those ecosystems only."
        )
    return key


def normalize_target_path(raw: Optional[str]) -> str:
    """Normalise the directory an SDK is committed under.

    Leading, trailing and doubled slashes are dropped (``/sdks//ts/`` is ``sdks/ts``); an empty
    value is the repository root. What cannot be made safe is refused rather than rewritten: a path
    that climbs out of the repository or into its ``.git`` directory is never what was meant.

    Args:
        raw: The configured path.

    Returns:
        The normalised path, ``''`` for the root.

    Raises:
        GitDeliveryTargetError: For a ``.``/``..``/``.git`` segment, a backslash, a control
            character, or a path longer than :data:`TARGET_PATH_MAX_CHARS`.
    """
    candidate = (raw or "").strip()
    problems: List[str] = []
    if "\\" in candidate:
        problems.append("targetPath must use '/' as its separator, not '\\'")
    if _PATH_CONTROL.search(candidate):
        problems.append("targetPath cannot contain control characters")
    segments = [segment for segment in candidate.split("/") if segment]
    for segment in segments:
        if segment in (".", ".."):
            problems.append("targetPath cannot contain '.' or '..' segments")
            break
    if any(segment.lower() == ".git" for segment in segments):
        problems.append("targetPath cannot point into a '.git' directory")
    normalised = "/".join(segments)
    if len(normalised) > TARGET_PATH_MAX_CHARS:
        problems.append(f"targetPath cannot be longer than {TARGET_PATH_MAX_CHARS} characters")
    if problems:
        raise GitDeliveryTargetError(*problems)
    return normalised


def normalize_base_branch(raw: Optional[str]) -> Optional[str]:
    """Normalise the configured base branch.

    Args:
        raw: The branch name, optionally spelled ``refs/heads/<name>``.

    Returns:
        The bare branch name, or ``None`` when blank (meaning the repository's default branch).

    Raises:
        GitDeliveryTargetError: When the name is not a legal git branch name, or is one of Apiome's
            own delivery branches.
    """
    candidate = (raw or "").strip()
    if candidate.startswith("refs/heads/"):
        candidate = candidate[len("refs/heads/"):]
    if not candidate:
        return None
    problem = ref_name_problem(candidate)
    if problem:
        raise GitDeliveryTargetError(f"baseBranch is not a legal branch name: {problem}")
    if candidate.startswith(BRANCH_PREFIX):
        raise GitDeliveryTargetError(
            f"baseBranch cannot be one of Apiome's own delivery branches ({BRANCH_PREFIX}…): a "
            "delivery force-updates those, so a pull request into one would rewrite its own base"
        )
    return candidate


# -------------------------------------------------------------------------------------------
# Repository eligibility
# -------------------------------------------------------------------------------------------


def repository_problem(row: Optional[Mapping[str, Any]], repository_ref: str = "") -> Optional[TargetProblem]:
    """Say why a registered repository cannot receive a delivery, if it cannot.

    Checked when a target is saved *and* when a delivery runs — a repository can be removed, or
    its linked account unlinked, between the two.

    Args:
        row: The ``tenant_repositories`` row (``provider``, ``repository_full_name``,
            ``linked_account_id``), or ``None`` when no live repository matched.
        repository_ref: How the caller named the repository, for the message.

    Returns:
        ``None`` when a delivery could proceed, otherwise the :class:`TargetProblem`.
    """
    if not row:
        return TargetProblem(
            "sdk-git-delivery-repository-missing",
            f"No repository {repository_ref!r} is registered in this workspace (it may have been "
            "removed). Register the repository, then point the delivery target at it.",
        )
    full_name = str(row.get("repository_full_name") or row.get("clone_url") or repository_ref)
    provider = str(row.get("provider") or "").strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        return TargetProblem(
            "sdk-git-delivery-provider-unsupported",
            f"{full_name} is hosted on {provider or 'an unknown provider'}. Git delivery opens pull "
            "requests through the repository's linked-account integration, which is available "
            f"for {', '.join(SUPPORTED_PROVIDERS)} repositories only.",
        )
    if not row.get("linked_account_id"):
        return TargetProblem(
            "sdk-git-delivery-repository-unlinked",
            f"{full_name} was registered from a public URL, so it holds no credential Apiome could "
            "push with. Register it through a linked GitHub account that can write to it — git "
            "delivery reuses that integration rather than storing a token of its own.",
        )
    try:
        parse_repository_full_name(row.get("repository_full_name"))
    except ValueError:
        return TargetProblem(
            "sdk-git-delivery-repository-invalid",
            f"Repository {full_name!r} has no GitHub owner/repo name on record. Re-register it "
            "through the GitHub integration.",
        )
    return None


# -------------------------------------------------------------------------------------------
# Store
# -------------------------------------------------------------------------------------------


def _out(row: Mapping[str, Any], project_slug: Optional[str]) -> GitDeliveryTargetOut:
    """Project a joined target row onto its API description.

    Args:
        row: A row from :meth:`app.database.Database.list_sdk_git_delivery_targets`.
        project_slug: The project's slug, for the branch pattern.

    Returns:
        The description, including whether the target can deliver right now.
    """
    # Re-shape the joined repository columns into the row shape repository_problem() reads, so a
    # listing and a delivery judge eligibility by one rule. The join never selects the linked
    # account's id, only whether there is one — a truthy placeholder stands in for it.
    repository = None
    if row.get("repository_full_name") is not None or row.get("repository_provider") is not None:
        repository = {
            "provider": row.get("repository_provider"),
            "repository_full_name": row.get("repository_full_name"),
            "linked_account_id": "linked" if row.get("repository_has_linked_account") else None,
        }
    problem = repository_problem(repository, str(row.get("repository_id") or ""))
    return GitDeliveryTargetOut(
        ecosystem=str(row.get("ecosystem") or ""),
        repository_id=str(row.get("repository_id") or ""),
        repository_full_name=row.get("repository_full_name"),
        repository_provider=row.get("repository_provider"),
        base_branch=row.get("base_branch"),
        target_path=str(row.get("target_path") or ""),
        branch_pattern=branch_pattern(project_slug, str(row.get("ecosystem") or "")),
        deliverable=problem is None,
        problem={"code": problem.code, "message": problem.message} if problem else None,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        updated_by=str(row["updated_by"]) if row.get("updated_by") else None,
    )


def list_targets(
    tenant_id: str, project_id: str, *, project_slug: Optional[str] = None
) -> List[GitDeliveryTargetOut]:
    """List a project's delivery targets.

    Args:
        tenant_id: Owning tenant.
        project_id: The project.
        project_slug: The project's slug, for each target's branch pattern.

    Returns:
        One entry per configured ecosystem. Never raises: a store failure logs and returns an empty
        list, because this is a read of configuration rather than a step in a delivery.
    """
    try:
        rows = db.list_sdk_git_delivery_targets(tenant_id, project_id)
    except Exception:  # noqa: BLE001 - listing configuration must not take a screen down
        logger.warning(
            "Could not list SDK git delivery targets for project %s", project_id, exc_info=True
        )
        return []
    return [_out(row, project_slug) for row in rows]


def save_target(
    tenant_id: str,
    project_id: str,
    *,
    ecosystem: str,
    repository_id: str,
    base_branch: Optional[str] = None,
    target_path: Optional[str] = None,
    project_slug: Optional[str] = None,
    actor_id: Optional[str] = None,
) -> GitDeliveryTargetOut:
    """Store (or replace) a project's delivery target for one ecosystem.

    Every field is validated before the repository is looked up, and every field problem is
    reported at once; an ineligible repository is then refused with its own code.

    Args:
        tenant_id: Owning tenant.
        project_id: The project.
        ecosystem: ``npm`` or ``pypi``.
        repository_id: The registered repository to deliver into.
        base_branch: The pull request's base; blank for the repository's default branch.
        target_path: The directory inside the repository; blank for the root.
        project_slug: The project's slug, for the branch pattern in the response.
        actor_id: The user configuring it.

    Returns:
        The stored target.

    Raises:
        GitDeliveryTargetError: When a field is invalid, or the repository cannot receive a
            delivery (``code`` names which).
        RuntimeError: When the write returned no row.
    """
    problems: List[str] = []
    key = ""
    path = ""
    branch: Optional[str] = None
    try:
        key = normalize_ecosystem(ecosystem)
    except GitDeliveryTargetError as exc:
        problems.extend(exc.errors)
    try:
        path = normalize_target_path(target_path)
    except GitDeliveryTargetError as exc:
        problems.extend(exc.errors)
    try:
        branch = normalize_base_branch(base_branch)
    except GitDeliveryTargetError as exc:
        problems.extend(exc.errors)
    repository_ref = (repository_id or "").strip()
    if not is_uuid_string(repository_ref):
        problems.append("repositoryId must be the id of a registered repository")
    if problems:
        raise GitDeliveryTargetError(*problems)

    problem = repository_problem(db.get_tenant_repository(tenant_id, repository_ref), repository_ref)
    if problem:
        raise GitDeliveryTargetError(problem.message, code=problem.code)

    row = db.upsert_sdk_git_delivery_target(
        tenant_id=tenant_id,
        project_id=project_id,
        ecosystem=key,
        repository_id=repository_ref,
        base_branch=branch,
        target_path=path,
        actor_id=actor_id,
    )
    if not row:
        raise RuntimeError("The git delivery target could not be stored for this project.")
    return _out(row, project_slug)


def delete_target(tenant_id: str, project_id: str, ecosystem: str) -> bool:
    """Remove a project's delivery target for one ecosystem.

    Args:
        tenant_id: Owning tenant.
        project_id: The project.
        ecosystem: ``npm`` or ``pypi``.

    Returns:
        Whether a target was configured.

    Raises:
        GitDeliveryTargetError: When the ecosystem is not one git delivery supports.
    """
    key = normalize_ecosystem(ecosystem)
    return db.delete_sdk_git_delivery_target(tenant_id, project_id, key) > 0


def resolve_target(tenant_id: str, project_id: str, ecosystem: str) -> Optional[DeliveryTarget]:
    """Find the target a delivery of one ecosystem uses.

    Args:
        tenant_id: Owning tenant.
        project_id: The project.
        ecosystem: A normalised ecosystem key.

    Returns:
        The :class:`DeliveryTarget`, or ``None`` when none is configured.
    """
    row = db.get_sdk_git_delivery_target(tenant_id, project_id, ecosystem)
    if not row:
        return None
    return DeliveryTarget(
        target_id=str(row["id"]) if row.get("id") else None,
        ecosystem=str(row.get("ecosystem") or ecosystem),
        repository_id=str(row.get("repository_id") or ""),
        base_branch=row.get("base_branch"),
        target_path=str(row.get("target_path") or ""),
    )
