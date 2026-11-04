"""The export git delivery pipeline — MFX-38.1 (#4328).

One entry point, :func:`deliver_export`, that takes a completed export job's bundle and a delivery
request and writes the bundle into a registered repository — as a **pull request** (``mode=pr``,
the default) or a **direct commit** (``mode=commit``). The rules live in
:mod:`app.export_git_delivery` (files, manifest, branch, words); the provider calls behind
:mod:`app.export_git_delivery_providers` (GitHub today); what lives here is the order, what each
outcome means, and the run row (``export_git_delivery_runs``, V354).

It is the SDK-4.2 delivery sequence (:mod:`app.sdk_git_delivery_pipeline`) applied to an export:

* The commit is always built on the **latest base branch**, writing only files that differ from it
  and removing only files a previous delivery's manifest named. Nothing differs → ``up_to_date``.
* **Pull request mode.** The delivery branch (one per artifact, target and path) is force-rebuilt on
  the base, and the one open pull request from it is updated (``updated``) — or opened when none is
  (``opened``). An open pull request already carrying exactly this tree and description is
  ``unchanged``. A re-export therefore updates the same branch and the same pull request.
* **Direct-commit mode.** The commit's parent is the base branch's head and the branch is moved
  **without force**: if the base moved while the delivery ran, or a branch rule protects it, the
  provider refuses and the run fails with that reason — a direct commit never discards anyone's work.

:func:`deliver_export` never raises for a delivery problem: a missing or revoked credential, a token
without write access, a refused push or pull request becomes a ``failed`` run with a stable
``export-git-delivery-*`` code and a redacted log. The repository token is the repository's existing
linked-account credential, added to the log's redactor before any step that could echo it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set

from .database import db
from .export_git_delivery import (
    MANIFEST_RELATIVE_PATH,
    BundleFile,
    DeliverySubject,
    NormalizedRequest,
    commit_message,
    delivery_files,
    export_branch_name,
    export_code,
    pull_request_body,
    pull_request_title,
)
from .export_git_delivery_providers import SUPPORTED_PROVIDERS, GitDeliveryProvider, open_provider
from .repository_webhook_rotation import resolve_linked_account_token
from .sdk_git_delivery_changes import FILE_MODE, ChangeSet, join_repo_path, manifest_paths, plan_changes
from .sdk_git_delivery_github import (
    GIT_TOKEN_REDACTION_MARKER,
    INLINE_BLOB_MAX_BYTES,
    ClientFactory,
    GitProviderError,
    PullRequest,
)
from .sdk_git_delivery_targets import repository_problem
from .sdk_run_log import RunLog

logger = logging.getLogger(__name__)

__all__ = [
    "ERROR_BASE_BRANCH_MISSING",
    "ERROR_CREDENTIAL_MISSING",
    "ERROR_EMPTY_BUNDLE",
    "ERROR_INTERNAL",
    "ERROR_PERMISSION_DENIED",
    "ERROR_PULL_REQUEST_REFUSED",
    "ERROR_REPOSITORY_ARCHIVED",
    "RUN_STATUSES",
    "ExportDeliveryOutcome",
    "deliver_export",
    "run_row_to_outcome",
]

RUN_STATUS_IN_PROGRESS = "in_progress"
RUN_STATUS_OPENED = "opened"
RUN_STATUS_UPDATED = "updated"
RUN_STATUS_UNCHANGED = "unchanged"
RUN_STATUS_UP_TO_DATE = "up_to_date"
RUN_STATUS_COMMITTED = "committed"
RUN_STATUS_FAILED = "failed"

#: Every status, matching V354's ``export_git_delivery_runs_status_check``.
RUN_STATUSES = (RUN_STATUS_IN_PROGRESS, RUN_STATUS_OPENED, RUN_STATUS_UPDATED, RUN_STATUS_UNCHANGED,
                RUN_STATUS_UP_TO_DATE, RUN_STATUS_COMMITTED, RUN_STATUS_FAILED)

ERROR_CREDENTIAL_MISSING = "export-git-delivery-credential-missing"
ERROR_REPOSITORY_ARCHIVED = "export-git-delivery-repository-archived"
ERROR_PERMISSION_DENIED = "export-git-delivery-permission-denied"
ERROR_BASE_BRANCH_MISSING = "export-git-delivery-base-branch-missing"
ERROR_PULL_REQUEST_REFUSED = "export-git-delivery-pull-request-refused"
ERROR_EMPTY_BUNDLE = "export-git-delivery-empty-bundle"
ERROR_INTERNAL = "export-git-delivery-internal-error"


class _DeliveryError(Exception):
    """A delivery that cannot continue, with the code and message its run records."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass
class _Progress:
    """What a delivery has learned so far — kept on a failed run, too."""

    repository_full_name: Optional[str] = None
    base_branch: Optional[str] = None
    branch_name: Optional[str] = None
    base_sha: Optional[str] = None
    commit_sha: Optional[str] = None
    pull_request: Optional[PullRequest] = None
    changes: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExportDeliveryOutcome:
    """What a delivery did.

    Attributes:
        run_id: The run row, when one was written.
        status: One of :data:`RUN_STATUSES`.
        mode: ``pr`` or ``commit``.
        job_id: The export job delivered.
        repository_id: The registered repository.
        repository_full_name: ``owner/repo``.
        base_branch: The base branch used.
        target_path: The directory the bundle was written under.
        branch_name: The delivery branch (the base branch in commit mode).
        base_sha: The base commit.
        commit_sha: The commit the branch points at.
        pull_request_number: The pull request opened or updated (``pr`` mode).
        pull_request_url: Its web page.
        changes: The changed-files overview.
        fidelity: The fidelity summary the pull request carried.
        log: The event log.
        error_code: Set when the run failed.
        error_message: Set when the run failed, redacted.
        retryable: Whether a failed run could plausibly succeed if repeated unchanged (not stored).
    """

    run_id: Optional[str]
    status: str
    mode: str
    job_id: str
    repository_id: Optional[str] = None
    repository_full_name: Optional[str] = None
    base_branch: Optional[str] = None
    target_path: str = ""
    branch_name: Optional[str] = None
    base_sha: Optional[str] = None
    commit_sha: Optional[str] = None
    pull_request_number: Optional[int] = None
    pull_request_url: Optional[str] = None
    changes: Dict[str, Any] = field(default_factory=dict)
    fidelity: Dict[str, Any] = field(default_factory=dict)
    log: List[Dict[str, Any]] = field(default_factory=list)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retryable: bool = False


# -------------------------------------------------------------------------------------------
# Steps
# -------------------------------------------------------------------------------------------


def _resolve_repository(tenant_id: str, repository_id: str) -> Dict[str, Any]:
    """Load the registered repository and confirm it can receive a delivery."""
    try:
        row = db.get_tenant_repository(tenant_id, repository_id)
    except Exception as exc:  # noqa: BLE001 - a lookup fault is a failed run, not a lost one
        logger.warning("Repository lookup failed for %s", repository_id, exc_info=True)
        raise _DeliveryError(ERROR_INTERNAL, "The target repository could not be read. Try again.",
                             retryable=True) from exc
    problem = repository_problem(row, repository_id)
    if problem:
        raise _DeliveryError(export_code(problem.code), problem.message.replace("delivery target", "delivery"))
    provider = str((row or {}).get("provider") or "").strip().lower()
    if provider not in SUPPORTED_PROVIDERS:  # pragma: no cover - repository_problem refuses it first
        raise _DeliveryError("export-git-delivery-provider-unsupported",
                             f"Export git delivery supports {', '.join(SUPPORTED_PROVIDERS)} repositories.")
    return dict(row or {})


def _resolve_token(repository: Dict[str, Any]) -> str:
    """The repository's existing linked-account token."""
    token = resolve_linked_account_token(db, repository)
    if not token:
        name = repository.get("repository_full_name") or repository.get("id")
        raise _DeliveryError(
            ERROR_CREDENTIAL_MISSING,
            f"The GitHub account that registered {name} is no longer linked, or holds no token, so "
            "there is no credential to push with. Re-link that account — or re-register the repository "
            "through an account that can write to it — then deliver again.",
        )
    return token


def _tree_entries(provider: GitDeliveryProvider, changes: ChangeSet, log: RunLog) -> List[Dict[str, Any]]:
    """The tree request for a change set; large files are uploaded as blobs first."""
    entries: List[Dict[str, Any]] = []
    for item in changes.written:
        entry: Dict[str, Any] = {"path": item.path, "mode": FILE_MODE, "type": "blob"}
        if item.size_bytes > INLINE_BLOB_MAX_BYTES:
            entry["sha"] = provider.create_blob(item.text)
            log.add("push", f"Uploaded {item.path} ({item.size_bytes:,} bytes) as a blob.")
        else:
            entry["content"] = item.text
        entries.append(entry)
    for path in changes.deleted:
        entries.append({"path": path, "mode": FILE_MODE, "type": "blob", "sha": None})
    return entries


def _execute(
    *,
    tenant_id: str,
    subject: DeliverySubject,
    request: NormalizedRequest,
    files: Sequence[BundleFile],
    client_factory: Optional[ClientFactory],
    log: RunLog,
    progress: _Progress,
) -> str:
    """Run every step of a delivery, recording what it learns on ``progress``; returns the status."""
    if not files:
        raise _DeliveryError(ERROR_EMPTY_BUNDLE, "The export job holds no file to deliver. Run the export "
                             "again (not as a dry run), then deliver it.")
    repository = _resolve_repository(tenant_id, request.repository_id)
    progress.repository_full_name = str(repository.get("repository_full_name") or "")
    token = _resolve_token(repository)
    log.secrets.append(token)
    log.add("resolve", f"Delivering export job {subject.job_id} ({subject.target}, {len(files)} file(s)) to "
            f"{progress.repository_full_name} with the repository's linked-account credential.")

    with open_provider(repository.get("provider") or "github", token, progress.repository_full_name,
                       client_factory=client_factory) as provider:
        info = provider.get_repository()
        progress.repository_full_name = info.full_name
        if info.archived:
            raise _DeliveryError(ERROR_REPOSITORY_ARCHIVED, f"{info.full_name} is archived, so nothing can be "
                                 "pushed to it. Unarchive it, or deliver to another repository.")
        if not info.can_push:
            raise _DeliveryError(
                ERROR_PERMISSION_DENIED,
                f"The linked account can read {info.full_name} but cannot push to it. Grant that account "
                "write access (and the token the `repo` scope, or Contents and Pull requests write "
                "access), then deliver again.",
            )

        base = request.base_branch or info.default_branch
        progress.base_branch = base
        base_sha = provider.get_branch_sha(base)
        if not base_sha:
            raise _DeliveryError(ERROR_BASE_BRANCH_MISSING, f"Base branch {base!r} does not exist in "
                                 f"{info.full_name}. Create it, or deliver to another base branch.")
        progress.base_sha = base_sha
        base_tree = provider.get_commit_tree_sha(base_sha)

        generated = delivery_files(subject, files, request.target_path)
        existing = provider.list_directory(base_tree, request.target_path, ref_label=base)
        previous: Set[str] = set()
        manifest = existing.get(join_repo_path(request.target_path, MANIFEST_RELATIVE_PATH))
        if manifest is not None and manifest.type == "blob":
            previous = manifest_paths(provider.get_blob_text(manifest.sha), request.target_path)
        changes = plan_changes(generated, existing, previous)
        progress.changes = changes.overview()
        log.add("plan", f"Against {base} ({base_sha[:12]}): {len(changes.added)} added, "
                f"{len(changes.modified)} modified, {len(changes.deleted)} removed, "
                f"{len(changes.unchanged)} unchanged.")

        if request.mode == "commit":
            return _commit(provider, subject, changes, base, base_sha, base_tree, log, progress)
        return _pull_request(provider, info.owner, subject, request, changes, base, base_sha, base_tree, log,
                             progress)


def _commit(provider: GitDeliveryProvider, subject: DeliverySubject, changes: ChangeSet, base: str,
            base_sha: str, base_tree: str, log: RunLog, progress: _Progress) -> str:
    """Direct-commit mode: one commit on top of the base branch, moved without force."""
    progress.branch_name = base
    if not changes.has_changes:
        log.add("plan", f"{base} already holds this export, so there is nothing to commit.")
        return RUN_STATUS_UP_TO_DATE
    tree = provider.create_tree(base_tree, _tree_entries(provider, changes, log))
    commit = provider.create_commit(commit_message(subject), tree, [base_sha])
    try:
        provider.update_branch(base, commit, force=False)
    except GitProviderError as exc:
        raise _DeliveryError(
            export_code(exc.code),
            f"{base} could not be moved to the export's commit: {exc.message} A direct commit only "
            "fast-forwards, so it fails rather than discard work when the branch moved during the delivery "
            "or a branch rule protects it. Deliver again, or deliver as a pull request (mode `pr`).",
            retryable=exc.retryable,
        ) from exc
    progress.commit_sha = commit
    log.add("push", f"Committed the export to {base} at {commit[:12]} (fast-forward from {base_sha[:12]}).")
    return RUN_STATUS_COMMITTED


def _pull_request(provider: GitDeliveryProvider, owner: str, subject: DeliverySubject,
                  request: NormalizedRequest, changes: ChangeSet, base: str, base_sha: str, base_tree: str,
                  log: RunLog, progress: _Progress) -> str:
    """Pull request mode: rebuild the delivery branch on the base and open or update its one pull request."""
    branch = export_branch_name(subject.artifact_slug or subject.artifact_id, subject.target, request.target_path)
    progress.branch_name = branch
    branch_sha = provider.get_branch_sha(branch)
    open_pull = provider.find_open_pull(owner, branch)
    if open_pull is not None:
        progress.pull_request = open_pull

    if not changes.has_changes:
        log.add("plan", f"{base} already holds this export, so there is nothing to deliver."
                + (f" Pull request #{open_pull.number} is still open but has nothing left to merge; it is safe "
                   "to close." if open_pull is not None else ""),
                level="warn" if open_pull is not None else "info")
        return RUN_STATUS_UP_TO_DATE

    title = pull_request_title(subject)
    body = pull_request_body(subject, progress.changes, target_path=request.target_path, mode="pr")
    new_tree = provider.create_tree(base_tree, _tree_entries(provider, changes, log))
    head_tree = provider.get_commit_tree_sha(branch_sha) if branch_sha else None
    pushed = head_tree != new_tree
    if pushed:
        commit = provider.create_commit(commit_message(subject), new_tree, [base_sha])
        progress.commit_sha = commit
        if branch_sha:
            provider.update_branch(branch, commit, force=True)
            log.add("push", f"Force-updated {branch} to {commit[:12]} on top of {base}.")
        elif provider.create_branch(branch, commit):
            log.add("push", f"Created {branch} at {commit[:12]} on top of {base}.")
        else:
            provider.update_branch(branch, commit, force=True)
            log.add("push", f"{branch} was created by a concurrent delivery; force-updated it to {commit[:12]}.",
                    level="warn")
    else:
        progress.commit_sha = branch_sha
        log.add("push", f"{branch} already holds exactly this export on top of {base}; nothing pushed.")

    if open_pull is None:
        opened = provider.create_pull(title=title, body=body, head=branch, base=base)
        if opened is not None:
            progress.pull_request = opened
            log.add("pull-request", f"Opened pull request #{opened.number}: {opened.url or title}.")
            return RUN_STATUS_OPENED
        open_pull = provider.find_open_pull(owner, branch)
        if open_pull is None:
            raise _DeliveryError(ERROR_PULL_REQUEST_REFUSED, f"The provider reported a pull request already open "
                                 f"from {branch}, but none could be found. The commit was pushed; deliver again "
                                 "to attach it.", retryable=True)
        progress.pull_request = open_pull

    if not pushed and (open_pull.title, open_pull.body, open_pull.base) == (title, body, base):
        log.add("pull-request", f"Pull request #{open_pull.number} already carries exactly this export; nothing "
                "was written.")
        return RUN_STATUS_UNCHANGED
    progress.pull_request = provider.update_pull(open_pull.number, title=title, body=body, base=base)
    log.add("pull-request", f"Updated pull request #{open_pull.number} with this export instead of opening "
            "another." if pushed else f"Pull request #{open_pull.number} already carries this export; "
            "refreshed its title, description and base.")
    return RUN_STATUS_UPDATED


# -------------------------------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------------------------------


def deliver_export(
    *,
    tenant_id: str,
    actor_id: Optional[str],
    subject: DeliverySubject,
    request: NormalizedRequest,
    files: Sequence[BundleFile],
    client_factory: Optional[ClientFactory] = None,
) -> ExportDeliveryOutcome:
    """Deliver a completed export job's bundle to a repository.

    Args:
        tenant_id: The caller's tenant.
        actor_id: The user who asked for the delivery.
        subject: What is being delivered (job, artifact, target, fidelity summary, report link).
        request: Where, and how (``pr`` or ``commit``).
        files: The bundle's files at bundle-relative paths.
        client_factory: How to obtain the HTTP client; injected by tests.

    Returns:
        The :class:`ExportDeliveryOutcome`. A failure is an outcome with status ``failed``, not an
        exception.

    Raises:
        Exception: Only when the run row itself cannot be written.
    """
    log = RunLog(marker=GIT_TOKEN_REDACTION_MARKER)
    progress = _Progress()
    row = db.insert_export_git_delivery_run(
        tenant_id=tenant_id,
        job_id=subject.job_id,
        artifact_id=subject.artifact_id,
        repository_id=request.repository_id,
        mode=request.mode,
        status=RUN_STATUS_IN_PROGRESS,
        version_record_id=subject.version_record_id,
        version_label=subject.version_label,
        export_target=subject.target,
        base_branch=request.base_branch,
        target_path=request.target_path,
        actor_id=actor_id,
    )
    run_id = str(row["id"]) if row and row.get("id") else None

    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retryable = False
    try:
        status = _execute(tenant_id=tenant_id, subject=subject, request=request, files=files,
                          client_factory=client_factory, log=log, progress=progress)
    except _DeliveryError as exc:
        status, error_code, retryable = RUN_STATUS_FAILED, exc.code, exc.retryable
        error_message = log.redact(exc.message)
    except GitProviderError as exc:
        status, error_code, retryable = RUN_STATUS_FAILED, export_code(exc.code), exc.retryable
        error_message = log.redact(exc.message)
    except Exception as exc:  # noqa: BLE001 - an unexplained fault still closes its run
        logger.exception("Export git delivery %s failed unexpectedly", run_id)
        status, error_code, retryable = RUN_STATUS_FAILED, ERROR_INTERNAL, True
        error_message = log.redact(f"The delivery failed unexpectedly ({type(exc).__name__}). Try again; if it "
                                   "keeps failing, the run id identifies it in the service logs.")
    if error_message:
        log.add("failed", error_message, level="error")

    _finish(run_id, tenant_id, status, log, progress, subject, error_code, error_message)
    pull = progress.pull_request
    return ExportDeliveryOutcome(
        run_id=run_id,
        status=status,
        mode=request.mode,
        job_id=subject.job_id,
        repository_id=request.repository_id,
        repository_full_name=progress.repository_full_name,
        base_branch=progress.base_branch or request.base_branch,
        target_path=request.target_path,
        branch_name=progress.branch_name,
        base_sha=progress.base_sha,
        commit_sha=progress.commit_sha,
        pull_request_number=pull.number if pull else None,
        pull_request_url=pull.url if pull else None,
        changes=dict(progress.changes),
        fidelity=dict(subject.fidelity),
        log=list(log.entries),
        error_code=error_code,
        error_message=error_message,
        retryable=retryable,
    )


def _finish(run_id: Optional[str], tenant_id: str, status: str, log: RunLog, progress: _Progress,
            subject: DeliverySubject, error_code: Optional[str], error_message: Optional[str]) -> None:
    """Close a run, best-effort: the provider already holds the result; the ledger is not the truth."""
    if not run_id:
        return
    pull = progress.pull_request
    try:
        db.finish_export_git_delivery_run(
            run_id,
            tenant_id,
            status=status,
            log=log.entries,
            repository_full_name=progress.repository_full_name,
            base_branch=progress.base_branch,
            branch_name=progress.branch_name,
            base_sha=progress.base_sha,
            commit_sha=progress.commit_sha,
            pull_request_number=pull.number if pull else None,
            pull_request_url=pull.url if pull else None,
            changes=progress.changes or None,
            fidelity=subject.fidelity or None,
            error_code=error_code,
            error_message=error_message,
        )
    except Exception:  # noqa: BLE001
        logger.warning("Could not close export git delivery run %s", run_id, exc_info=True)


def run_row_to_outcome(row: Dict[str, Any]) -> ExportDeliveryOutcome:
    """Project a stored run row back onto an outcome, for the history route."""
    def _obj(value: Any) -> Dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

    return ExportDeliveryOutcome(
        run_id=str(row["id"]) if row.get("id") else None,
        status=str(row.get("status") or ""),
        mode=str(row.get("mode") or "pr"),
        job_id=str(row.get("job_id") or ""),
        repository_id=str(row["repository_id"]) if row.get("repository_id") else None,
        repository_full_name=row.get("repository_full_name"),
        base_branch=row.get("base_branch"),
        target_path=str(row.get("target_path") or ""),
        branch_name=row.get("branch_name"),
        base_sha=row.get("base_sha"),
        commit_sha=row.get("commit_sha"),
        pull_request_number=row.get("pull_request_number"),
        pull_request_url=row.get("pull_request_url"),
        changes=_obj(row.get("changes")),
        fidelity=_obj(row.get("fidelity")),
        log=list(row.get("log")) if isinstance(row.get("log"), list) else [],
        error_code=row.get("error_code"),
        error_message=row.get("error_message"),
    )
