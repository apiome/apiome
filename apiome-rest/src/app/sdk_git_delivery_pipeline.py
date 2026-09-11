"""The git delivery pipeline — SDK-4.2 (#4496).

One entry point, :func:`deliver`, that takes a published revision and a configured target and
delivers the regenerated SDK to the tenant's repository as a pull request. Everything it needs is
already owned by another module — the branding, version rule and package build (SDK-4.1, via
:mod:`app.sdk_publish_pipeline`), the target and branch naming (:mod:`app.sdk_git_delivery_targets`),
the change plan (:mod:`app.sdk_git_delivery_changes`), the words
(:mod:`app.sdk_git_delivery_summary`) and the GitHub calls (:mod:`app.sdk_git_delivery_github`) —
so what lives here is the *order* those happen in, what each outcome means, and the ledger row.

**Why this is not a queued job.** SDK-1.1's job service was closed not-planned, so — as SDK-4.1
did — a delivery runs inline and records its own run row. The row has a job's shape (a status, an
event log, an outcome), so SDK-4.3's auto-regen worker calls :func:`deliver` directly and a queue
can be put underneath it later without changing what a caller sees. :func:`deliver` never raises
for a delivery problem: once a target is known, every failure — a missing or revoked credential, a
refused push, a package that cannot be built — becomes a ``failed`` run carrying a stable code and
an actionable, redacted log. That is the ticket's "credential failures and push rejections surface
as failed jobs with actionable logs", and it is what lets a worker treat every attempt uniformly.

**Idempotent per (version, target, options).** The branch is named after the version, the project
and the ecosystem, so a re-run finds the branch and the open pull request it wrote last time:

* The commit is always built on the **latest base branch**, writing only the files that differ
  from it and removing only files a previous delivery generated. If nothing differs, the base
  already contains this SDK: the run is ``up_to_date`` and nothing is written.
* If an open pull request's branch already holds exactly that tree, the run is ``unchanged`` and
  nothing is written (its description is refreshed only if the text differs — ``updated``).
* Otherwise the branch is force-updated to the new commit, and the open pull request is updated
  (``updated``) — or, when none is open, one is opened (``opened``). Never a second one.

Force-updating is deliberate, and the pull request says so: a delivery branch is Apiome's, rebuilt
from the base each time the way a dependency bot's is, so it never accumulates conflicts with a
moving base or stale files from a changed target path.

**The committed package carries the next registry version.** The package version is the one the
next SDK-4.1 publish of this series would claim — exactly what a publish dry run reports — so
merging the pull request and then publishing ships identical files. Nothing is claimed: a pull
request is not a release. SDK-4.3 can pin the counter (``regen_counter``) when it publishes and
delivers in one pass.

**Nothing secret is written anywhere.** The repository token is resolved from the existing
linked-account integration, handed to the GitHub client, and added to the run log's redactor before
any step that could echo it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .canonical_model import CanonicalApi
from .database import db
from .repository_webhook_rotation import resolve_linked_account_token
from .sdk_git_delivery_changes import (
    FILE_MODE,
    MANIFEST_RELATIVE_PATH,
    ChangeSet,
    delivery_files,
    join_repo_path,
    manifest_paths,
    plan_changes,
)
from .sdk_git_delivery_github import (
    ERROR_PERMISSION_DENIED,
    ERROR_PULL_REQUEST_REFUSED,
    GIT_TOKEN_REDACTION_MARKER,
    INLINE_BLOB_MAX_BYTES,
    ClientFactory,
    GitHubGitClient,
    GitProviderError,
    PullRequest,
)
from .sdk_git_delivery_summary import (
    DeliverySummary,
    commit_message,
    pull_request_body,
    pull_request_title,
)
from .sdk_git_delivery_targets import DeliveryTarget, regen_branch_name, repository_problem
from .sdk_kit import KIT_SCHEMA_VERSION
from .sdk_publish_pipeline import (
    PublishContext,
    PublishError,
    build_release_distribution,
    resolve_release_branding,
    resolve_release_series,
)
from .sdk_publish_version import package_version
from .sdk_run_log import RunLog

logger = logging.getLogger(__name__)

__all__ = [
    "ERROR_BASE_BRANCH_MISSING",
    "ERROR_CREDENTIAL_MISSING",
    "ERROR_INTERNAL",
    "ERROR_REPOSITORY_ARCHIVED",
    "RUN_STATUSES",
    "RUN_STATUS_FAILED",
    "RUN_STATUS_IN_PROGRESS",
    "RUN_STATUS_OPENED",
    "RUN_STATUS_UNCHANGED",
    "RUN_STATUS_UPDATED",
    "RUN_STATUS_UP_TO_DATE",
    "DeliveryOutcome",
    "deliver",
    "run_row_to_outcome",
]

#: Lifecycle statuses, matching V257's ``sdk_git_delivery_runs_status_check``.
RUN_STATUS_IN_PROGRESS = "in_progress"
RUN_STATUS_OPENED = "opened"
RUN_STATUS_UPDATED = "updated"
RUN_STATUS_UNCHANGED = "unchanged"
RUN_STATUS_UP_TO_DATE = "up_to_date"
RUN_STATUS_FAILED = "failed"

#: Every status, in lifecycle order.
RUN_STATUSES = (
    RUN_STATUS_IN_PROGRESS,
    RUN_STATUS_OPENED,
    RUN_STATUS_UPDATED,
    RUN_STATUS_UNCHANGED,
    RUN_STATUS_UP_TO_DATE,
    RUN_STATUS_FAILED,
)

#: The repository's linked account has no token to push with.
ERROR_CREDENTIAL_MISSING = "sdk-git-delivery-credential-missing"

#: The repository is archived (read-only) on GitHub.
ERROR_REPOSITORY_ARCHIVED = "sdk-git-delivery-repository-archived"

#: The configured (or default) base branch does not exist.
ERROR_BASE_BRANCH_MISSING = "sdk-git-delivery-base-branch-missing"

#: Something failed that no refusal explains. Recorded rather than raised, so the run is not lost.
ERROR_INTERNAL = "sdk-git-delivery-internal-error"


class _DeliveryError(Exception):
    """A delivery that cannot continue, with the code and message its run records.

    Attributes:
        code: A stable, machine-readable reason.
        message: What went wrong and what to do about it.
        retryable: Whether trying again unchanged could plausibly succeed.
    """

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass
class _Progress:
    """What a delivery has learned so far — kept on a failed run, too.

    Attributes:
        repository_full_name: ``owner/repo``.
        base_branch: The base branch in use.
        branch_name: The delivery branch.
        release_series: The series the package version was derived under.
        regen_counter: The counter the package version carries.
        package_name: The committed package's name.
        package_version: The committed package's version.
        base_sha: The base commit the delivery was built on.
        commit_sha: The commit the branch points at.
        pull_request: The pull request opened or updated.
        changes: The change overview.
        provenance: The provenance embedded in the package.
    """

    repository_full_name: Optional[str] = None
    base_branch: Optional[str] = None
    branch_name: Optional[str] = None
    release_series: Optional[str] = None
    regen_counter: Optional[int] = None
    package_name: Optional[str] = None
    package_version: Optional[str] = None
    base_sha: Optional[str] = None
    commit_sha: Optional[str] = None
    pull_request: Optional[PullRequest] = None
    changes: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeliveryOutcome:
    """What a delivery did.

    Attributes:
        run_id: The ledger row, when one was written.
        status: One of :data:`RUN_STATUSES`.
        ecosystem: ``npm`` or ``pypi``.
        version_line: The API version delivered.
        release_series: The series the package version was derived under.
        regen_counter: The counter the package version carries.
        package_name: The committed package's name.
        package_version: The committed package's version.
        repository_id: The registered repository.
        repository_full_name: ``owner/repo``.
        base_branch: The base branch used.
        target_path: The directory the SDK was committed under.
        branch_name: The delivery branch.
        base_sha: The base commit.
        commit_sha: The commit the branch points at.
        pull_request_number: The pull request opened or updated.
        pull_request_url: Its web page.
        changes: The changed-files overview.
        provenance: The provenance embedded in the committed package.
        log: The event log.
        error_code: Set when the run failed.
        error_message: Set when the run failed, redacted.
        retryable: Whether a failed run could plausibly succeed if repeated unchanged. Not
            persisted — it is for an in-process caller such as SDK-4.3's worker.
    """

    run_id: Optional[str]
    status: str
    ecosystem: str
    version_line: Optional[str] = None
    release_series: Optional[str] = None
    regen_counter: Optional[int] = None
    package_name: Optional[str] = None
    package_version: Optional[str] = None
    repository_id: Optional[str] = None
    repository_full_name: Optional[str] = None
    base_branch: Optional[str] = None
    target_path: Optional[str] = None
    branch_name: Optional[str] = None
    base_sha: Optional[str] = None
    commit_sha: Optional[str] = None
    pull_request_number: Optional[int] = None
    pull_request_url: Optional[str] = None
    changes: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)
    log: List[Dict[str, Any]] = field(default_factory=list)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retryable: bool = False


# -------------------------------------------------------------------------------------------
# Steps
# -------------------------------------------------------------------------------------------


def _resolve_repository(context: PublishContext, target: DeliveryTarget) -> Dict[str, Any]:
    """Load the target's repository and confirm it can still receive a delivery.

    Args:
        context: The revision being delivered.
        target: The configured target.

    Returns:
        The ``tenant_repositories`` row.

    Raises:
        _DeliveryError: When the repository was removed, is not on a supported provider, or has
            no linked account.
    """
    try:
        row = db.get_tenant_repository(context.tenant_id, target.repository_id)
    except Exception as exc:  # noqa: BLE001 - a lookup fault is a failed run, not a lost one
        logger.warning("Repository lookup failed for %s", target.repository_id, exc_info=True)
        raise _DeliveryError(
            ERROR_INTERNAL, "The target repository could not be read. Try again.", retryable=True
        ) from exc
    problem = repository_problem(row, target.repository_id)
    if problem:
        raise _DeliveryError(problem.code, problem.message)
    return dict(row or {})


def _resolve_token(repository: Dict[str, Any]) -> str:
    """Resolve the repository's existing linked-account token.

    Args:
        repository: The ``tenant_repositories`` row.

    Returns:
        The token.

    Raises:
        _DeliveryError: ``sdk-git-delivery-credential-missing`` when the account that registered
            the repository is no longer linked, or holds no token.
    """
    token = resolve_linked_account_token(db, repository)
    if not token:
        name = repository.get("repository_full_name") or repository.get("id")
        raise _DeliveryError(
            ERROR_CREDENTIAL_MISSING,
            f"The GitHub account that registered {name} is no longer linked, or holds no token, so "
            "there is no credential to push with. Re-link that account — or re-register the "
            "repository through an account that can write to it — then deliver again.",
        )
    return token


def _tree_entries(github: GitHubGitClient, changes: ChangeSet, log: RunLog) -> List[Dict[str, Any]]:
    """Build the tree request for a change set.

    Small files are inlined; files over :data:`INLINE_BLOB_MAX_BYTES` are uploaded as blobs first.

    Args:
        github: The client.
        changes: What to write and remove.
        log: The event log.

    Returns:
        The ``tree`` entries for :meth:`GitHubGitClient.create_tree`.
    """
    entries: List[Dict[str, Any]] = []
    for item in changes.written:
        entry: Dict[str, Any] = {"path": item.path, "mode": FILE_MODE, "type": "blob"}
        if item.size_bytes > INLINE_BLOB_MAX_BYTES:
            entry["sha"] = github.create_blob(item.text)
            log.add("push", f"Uploaded {item.path} ({item.size_bytes:,} bytes) as a blob.")
        else:
            entry["content"] = item.text
        entries.append(entry)
    for path in changes.deleted:
        entries.append({"path": path, "mode": FILE_MODE, "type": "blob", "sha": None})
    return entries


def _execute(
    api: CanonicalApi,
    *,
    context: PublishContext,
    target: DeliveryTarget,
    source_text: Optional[str],
    source_format: Optional[str],
    apiome_version: Optional[str],
    regen_counter: Optional[int],
    client_factory: Optional[ClientFactory],
    log: RunLog,
    progress: _Progress,
) -> str:
    """Run every step of a delivery, recording what it learns on ``progress``.

    Args:
        api: The revision's canonical model.
        context: The revision being delivered, and by whom.
        target: The configured target.
        source_text: The captured contract.
        source_format: Its format key.
        apiome_version: The running API version.
        regen_counter: A pinned counter, or ``None`` for the next registry counter.
        client_factory: How to obtain the HTTP client.
        log: The event log.
        progress: Filled in as the delivery proceeds.

    Returns:
        The final status.

    Raises:
        _DeliveryError: For a problem found before GitHub is written to.
        GitProviderError: For a GitHub refusal.
        PublishError: For a package that cannot be named, versioned or built.
    """
    ecosystem = target.ecosystem

    repository = _resolve_repository(context, target)
    progress.repository_full_name = str(repository.get("repository_full_name") or "")
    token = _resolve_token(repository)
    log.secrets.append(token)
    log.add(
        "resolve",
        f"Delivering the {ecosystem} SDK for {context.project_slug} "
        f"{context.version_line or context.version_record_id} to "
        f"{progress.repository_full_name} with the repository's linked-account credential.",
    )

    branding, package_name, fingerprint = resolve_release_branding(context, ecosystem)
    series = resolve_release_series(context)
    counter = (
        int(regen_counter)
        if regen_counter is not None
        else db.next_sdk_publish_counter(context.tenant_id, context.project_id, ecosystem, series.key)
    )
    version = package_version(series, ecosystem, counter)
    progress.package_name = package_name
    progress.package_version = version
    progress.release_series = series.key
    progress.regen_counter = counter
    progress.branch_name = regen_branch_name(context.version_line, context.project_slug, ecosystem)
    log.add(
        "version",
        f"The package is {package_name}@{version} — release series {series.key} at counter "
        f"{counter}{' (pinned)' if regen_counter is not None else ', the next registry release'}.",
    )

    distribution = build_release_distribution(
        api,
        context=context,
        ecosystem=ecosystem,
        branding=branding,
        package_name=package_name,
        version=version,
        series=series,
        counter=counter,
        source_text=source_text,
        source_format=source_format,
        settings_fingerprint=fingerprint,
        apiome_version=apiome_version,
    )
    progress.provenance = dict(distribution.provenance)
    files = delivery_files(distribution, target.target_path)
    log.add(
        "build",
        f"Built the SDK-4.1 {ecosystem} layout: {len(files)} files under "
        f"`{target.target_path or '/'}`.",
    )

    with GitHubGitClient(token, progress.repository_full_name, client_factory=client_factory) as github:
        info = github.get_repository()
        progress.repository_full_name = info.full_name
        if info.archived:
            raise _DeliveryError(
                ERROR_REPOSITORY_ARCHIVED,
                f"{info.full_name} is archived on GitHub, so nothing can be pushed to it. Unarchive "
                "it, or point the delivery target at another repository.",
            )
        if not info.can_push:
            raise _DeliveryError(
                ERROR_PERMISSION_DENIED,
                f"The linked account can read {info.full_name} but cannot push to it. Grant that "
                "account write access to the repository (and the token the `repo` scope, or "
                "Contents and Pull requests write access), then deliver again.",
            )

        base = target.base_branch or info.default_branch
        progress.base_branch = base
        base_sha = github.get_branch_sha(base)
        if not base_sha:
            raise _DeliveryError(
                ERROR_BASE_BRANCH_MISSING,
                f"Base branch {base!r} does not exist in {info.full_name}. Create it, or change the "
                "delivery target's base branch.",
            )
        progress.base_sha = base_sha
        base_tree = github.get_commit_tree_sha(base_sha)

        existing = github.list_directory(base_tree, target.target_path, ref_label=base)
        previous: Set[str] = set()
        manifest = existing.get(join_repo_path(target.target_path, MANIFEST_RELATIVE_PATH))
        if manifest is not None and manifest.type == "blob":
            previous = manifest_paths(github.get_blob_text(manifest.sha), target.target_path)
        changes = plan_changes(files, existing, previous)
        progress.changes = changes.overview()
        log.add(
            "plan",
            f"Against {base} ({base_sha[:12]}): {len(changes.added)} added, "
            f"{len(changes.modified)} modified, {len(changes.deleted)} removed, "
            f"{len(changes.unchanged)} unchanged.",
        )

        branch = progress.branch_name
        branch_sha = github.get_branch_sha(branch)
        open_pull = github.find_open_pull(info.owner, branch)
        if open_pull is not None:
            progress.pull_request = open_pull

        if not changes.has_changes:
            log.add(
                "plan",
                f"{base} already contains this SDK, so there is nothing to deliver."
                + (
                    f" Pull request #{open_pull.number} is still open but has nothing left to "
                    "merge; it is safe to close."
                    if open_pull is not None
                    else ""
                ),
                level="warn" if open_pull is not None else "info",
            )
            return RUN_STATUS_UP_TO_DATE

        summary = DeliverySummary(
            project_slug=context.project_slug,
            api_title=api.title,
            version_line=context.version_line,
            version_record_id=context.version_record_id,
            ecosystem=ecosystem,
            package_name=package_name,
            package_version=version,
            repository_full_name=info.full_name,
            base_branch=base,
            branch_name=branch,
            target_path=target.target_path,
            apiome_version=apiome_version,
            renderer=f"app.snippet_render/{KIT_SCHEMA_VERSION}",
            changes=progress.changes,
            provenance=progress.provenance,
        )
        title = pull_request_title(summary)
        body = pull_request_body(summary)

        new_tree = github.create_tree(base_tree, _tree_entries(github, changes, log))
        head_tree = github.get_commit_tree_sha(branch_sha) if branch_sha else None
        pushed = head_tree != new_tree

        if pushed:
            commit = github.create_commit(commit_message(summary), new_tree, [base_sha])
            progress.commit_sha = commit
            if branch_sha:
                github.update_branch(branch, commit, force=True)
                log.add("push", f"Force-updated {branch} to {commit[:12]} on top of {base}.")
            elif github.create_branch(branch, commit):
                log.add("push", f"Created {branch} at {commit[:12]} on top of {base}.")
            else:
                github.update_branch(branch, commit, force=True)
                log.add(
                    "push",
                    f"{branch} was created by a concurrent delivery; force-updated it to "
                    f"{commit[:12]}.",
                    level="warn",
                )
        else:
            progress.commit_sha = branch_sha
            log.add("push", f"{branch} already holds exactly this SDK on top of {base}; nothing pushed.")

        if open_pull is None:
            opened = github.create_pull(title=title, body=body, head=branch, base=base)
            if opened is not None:
                progress.pull_request = opened
                log.add("pull-request", f"Opened pull request #{opened.number}: {opened.url or title}.")
                return RUN_STATUS_OPENED
            open_pull = github.find_open_pull(info.owner, branch)
            if open_pull is None:
                raise _DeliveryError(
                    ERROR_PULL_REQUEST_REFUSED,
                    f"GitHub reported a pull request already open from {branch}, but none could "
                    "be found. The commit was pushed; deliver again to attach it.",
                    retryable=True,
                )
            progress.pull_request = open_pull

        if not pushed and (open_pull.title, open_pull.body, open_pull.base) == (title, body, base):
            log.add(
                "pull-request",
                f"Pull request #{open_pull.number} already carries exactly this SDK; nothing was "
                "written.",
            )
            return RUN_STATUS_UNCHANGED

        progress.pull_request = github.update_pull(open_pull.number, title=title, body=body, base=base)
        log.add(
            "pull-request",
            f"Updated pull request #{open_pull.number} with the regenerated SDK instead of opening "
            "another."
            if pushed
            else f"Pull request #{open_pull.number} already carries this SDK; refreshed its title, "
            "description and base.",
        )
        return RUN_STATUS_UPDATED


# -------------------------------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------------------------------


def deliver(
    api: CanonicalApi,
    *,
    context: PublishContext,
    target: DeliveryTarget,
    source_text: Optional[str] = None,
    source_format: Optional[str] = None,
    apiome_version: Optional[str] = None,
    regen_counter: Optional[int] = None,
    client_factory: Optional[ClientFactory] = None,
) -> DeliveryOutcome:
    """Deliver one revision's SDK to its configured repository as a pull request.

    Args:
        api: The revision's canonical model.
        context: Which revision is being delivered, and by whom.
        target: The configured target (:func:`app.sdk_git_delivery_targets.resolve_target`).
        source_text: The captured contract, which the package carries.
        source_format: Its format key.
        apiome_version: The running API version, recorded as provenance.
        regen_counter: Pin the package version's counter (SDK-4.3, to match a publish it just
            made). ``None`` uses the counter the next registry publish would claim.
        client_factory: How to obtain the HTTP client; injected by tests.

    Returns:
        The :class:`DeliveryOutcome`. A failure is an outcome with status ``failed``, not an
        exception.

    Raises:
        Exception: Only when the run row itself cannot be written — a delivery is never attempted
            without a record of it.
    """
    log = RunLog(marker=GIT_TOKEN_REDACTION_MARKER)
    progress = _Progress()
    row = db.insert_sdk_git_delivery_run(
        tenant_id=context.tenant_id,
        project_id=context.project_id,
        version_id=context.version_record_id,
        target_id=target.target_id,
        repository_id=target.repository_id,
        ecosystem=target.ecosystem,
        status=RUN_STATUS_IN_PROGRESS,
        version_line=context.version_line,
        base_branch=target.base_branch,
        target_path=target.target_path,
        actor_id=context.actor_id,
    )
    run_id = str(row["id"]) if row and row.get("id") else None

    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retryable = False
    try:
        status = _execute(
            api,
            context=context,
            target=target,
            source_text=source_text,
            source_format=source_format,
            apiome_version=apiome_version,
            regen_counter=regen_counter,
            client_factory=client_factory,
            log=log,
            progress=progress,
        )
    except (_DeliveryError, GitProviderError) as exc:
        status, error_code, retryable = RUN_STATUS_FAILED, exc.code, exc.retryable
        error_message = log.redact(exc.message)
    except PublishError as exc:
        status, error_code = RUN_STATUS_FAILED, exc.code
        error_message = log.redact(exc.message)
    except Exception as exc:  # noqa: BLE001 - an unexplained fault still closes its run
        logger.exception("SDK git delivery %s failed unexpectedly", run_id)
        status, error_code, retryable = RUN_STATUS_FAILED, ERROR_INTERNAL, True
        error_message = log.redact(
            f"The delivery failed unexpectedly ({type(exc).__name__}). Try again; if it keeps "
            "failing, the run id identifies it in the service logs."
        )
    if error_message:
        log.add("failed", error_message, level="error")

    _finish(run_id, context, status, log, progress, error_code, error_message)
    pull = progress.pull_request
    return DeliveryOutcome(
        run_id=run_id,
        status=status,
        ecosystem=target.ecosystem,
        version_line=context.version_line,
        release_series=progress.release_series,
        regen_counter=progress.regen_counter,
        package_name=progress.package_name,
        package_version=progress.package_version,
        repository_id=target.repository_id,
        repository_full_name=progress.repository_full_name,
        base_branch=progress.base_branch or target.base_branch,
        target_path=target.target_path,
        branch_name=progress.branch_name,
        base_sha=progress.base_sha,
        commit_sha=progress.commit_sha,
        pull_request_number=pull.number if pull else None,
        pull_request_url=pull.url if pull else None,
        changes=dict(progress.changes),
        provenance=dict(progress.provenance),
        log=list(log.entries),
        error_code=error_code,
        error_message=error_message,
        retryable=retryable,
    )


def _finish(
    run_id: Optional[str],
    context: PublishContext,
    status: str,
    log: RunLog,
    progress: _Progress,
    error_code: Optional[str],
    error_message: Optional[str],
) -> None:
    """Close a run, best-effort.

    A ledger write that fails must not turn a pull request that was opened into a reported failure,
    so this logs and returns rather than raising.

    Args:
        run_id: The run, or ``None`` when none was written.
        context: The revision delivered (for the tenant scope).
        status: The final status.
        log: The event log.
        progress: What the delivery learned.
        error_code: Machine-readable failure code.
        error_message: Redacted failure message.
    """
    if not run_id:
        return
    pull = progress.pull_request
    try:
        db.finish_sdk_git_delivery_run(
            run_id,
            context.tenant_id,
            status=status,
            log=log.entries,
            release_series=progress.release_series,
            regen_counter=progress.regen_counter,
            package_name=progress.package_name,
            package_version=progress.package_version,
            repository_full_name=progress.repository_full_name,
            base_branch=progress.base_branch,
            branch_name=progress.branch_name,
            base_sha=progress.base_sha,
            commit_sha=progress.commit_sha,
            pull_request_number=pull.number if pull else None,
            pull_request_url=pull.url if pull else None,
            changes=progress.changes or None,
            provenance=progress.provenance or None,
            error_code=error_code,
            error_message=error_message,
        )
    except Exception:  # noqa: BLE001 - GitHub already has the result; the ledger is not the truth
        logger.warning("Could not close SDK git delivery run %s", run_id, exc_info=True)


def run_row_to_outcome(row: Dict[str, Any]) -> DeliveryOutcome:
    """Project a stored run row back onto an outcome, for the history routes.

    Args:
        row: A row from ``sdk_git_delivery_runs``.

    Returns:
        The outcome. ``retryable`` is not stored and reads back ``False``.
    """
    changes = row.get("changes")
    provenance = row.get("provenance")
    log = row.get("log")
    return DeliveryOutcome(
        run_id=str(row["id"]) if row.get("id") else None,
        status=str(row.get("status") or ""),
        ecosystem=str(row.get("ecosystem") or ""),
        version_line=row.get("version_line"),
        release_series=row.get("release_series"),
        regen_counter=row.get("regen_counter"),
        package_name=row.get("package_name"),
        package_version=row.get("package_version"),
        repository_id=str(row["repository_id"]) if row.get("repository_id") else None,
        repository_full_name=row.get("repository_full_name"),
        base_branch=row.get("base_branch"),
        target_path=row.get("target_path"),
        branch_name=row.get("branch_name"),
        base_sha=row.get("base_sha"),
        commit_sha=row.get("commit_sha"),
        pull_request_number=row.get("pull_request_number"),
        pull_request_url=row.get("pull_request_url"),
        changes=dict(changes) if isinstance(changes, dict) else {},
        provenance=dict(provenance) if isinstance(provenance, dict) else {},
        log=list(log) if isinstance(log, list) else [],
        error_code=row.get("error_code"),
        error_message=row.get("error_message"),
    )
