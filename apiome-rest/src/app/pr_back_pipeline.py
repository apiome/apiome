"""The PR-back pipeline: render a version, open a pull request — REPO-5.8 (#2793).

:func:`prepare` decides *whether* a project may PR back into a repository and *what* it would
write — refusing, with a stable code, a request that cannot start (the repository's allow/deny
list does not let the project, the project has no source file in that repository, the files span
branches and no target branch is set). :func:`run_pr_back` then does it against GitHub:

1. Resolve the repository's existing linked-account token — PR-back stores no credential of its
   own, exactly like SDK-4.2 git delivery, whose GitHub client (:mod:`app.sdk_git_delivery_github`)
   it reuses.
2. On the latest base branch, read each source file. A file whose bytes already equal the rendered
   text is ``unchanged``; the rest are ``added`` or ``modified``, and each gets a change report —
   the project's change report templates rendered over
   :func:`app.openapi_change_report.build_change_report` (base file → rendered file).
3. Nothing changed → ``up_to_date``, nothing written. A dry run stops here too (``preview``),
   having written nothing, and returns the title, description and commit message it would use.
4. Otherwise commit the changed files on top of the base, create or force-update the PR-back
   branch (``apiome/pr-back-<project>-<base>``), and open the pull request — or refresh the one
   already open from that branch (``updated``), never a second one. A newly opened pull request
   gets the repository's reviewers.

Every pull request opened is audited as ``repository.pr_back_opened`` and every one refreshed as
``repository.pr_back_updated``, from here rather than the route, so any future caller (an
on-publish trigger) is audited the same way. Once preparation succeeded the pipeline never raises
for a provider problem: a revoked token, a refused push or a rate limit is a ``failed`` outcome
with a code and a redacted, actionable log.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .change_report_render import build_render_metadata, render_from_template_row
from .database import db
from .openapi_change_report import build_change_report, change_report_change_counts
from .pr_back import (
    FileChangeReport,
    PrBackSettings,
    SourceFile,
    commit_message_context,
    foreign_schema_refs,
    owner_of,
    parse_spec_text,
    pr_back_branch_name,
    project_allowed,
    pull_request_body,
    pull_request_title,
    render_commit_message,
    serialize_spec,
    slice_spec_for_source,
    spec_format_for_path,
    split_reviewers,
)
from .publication_change_report import EMPTY_BASELINE_OPENAPI
from .repository_webhook_rotation import resolve_linked_account_token
from .sdk_git_delivery_changes import FILE_MODE, git_blob_sha
from .sdk_git_delivery_github import (
    ERROR_PULL_REQUEST_REFUSED,
    GIT_TOKEN_REDACTION_MARKER,
    INLINE_BLOB_MAX_BYTES,
    ClientFactory,
    GitHubGitClient,
    GitProviderError,
    PullRequest,
)
from .sdk_git_delivery_targets import repository_problem
from .sdk_run_log import RunLog

logger = logging.getLogger(__name__)

__all__ = [
    "AUDIT_PR_BACK_OPENED",
    "AUDIT_PR_BACK_UPDATED",
    "ERROR_BASE_BRANCH_MISSING",
    "ERROR_BRANCH_AMBIGUOUS",
    "ERROR_CREDENTIAL_MISSING",
    "ERROR_INTERNAL",
    "ERROR_NO_RENDERABLE_FILE",
    "ERROR_NO_SOURCE",
    "ERROR_NOT_CONFIGURED",
    "ERROR_PERMISSION_DENIED",
    "ERROR_PROJECT_NOT_ALLOWED",
    "ERROR_REPOSITORY_ARCHIVED",
    "STATUSES",
    "PlannedFile",
    "PrBackOutcome",
    "PrBackPlan",
    "PrBackRefusalError",
    "check_eligibility",
    "prepare",
    "run_pr_back",
]

#: Audit action for a pull request PR-back opened.
AUDIT_PR_BACK_OPENED = "repository.pr_back_opened"

#: Audit action for an open pull request PR-back refreshed with a new commit or description.
AUDIT_PR_BACK_UPDATED = "repository.pr_back_updated"

#: Outcomes, in lifecycle order.
STATUS_PREVIEW = "preview"
STATUS_OPENED = "opened"
STATUS_UPDATED = "updated"
STATUS_UNCHANGED = "unchanged"
STATUS_UP_TO_DATE = "up_to_date"
STATUS_FAILED = "failed"
STATUSES = (
    STATUS_PREVIEW,
    STATUS_OPENED,
    STATUS_UPDATED,
    STATUS_UNCHANGED,
    STATUS_UP_TO_DATE,
    STATUS_FAILED,
)

#: Refusals :func:`prepare` raises (HTTP errors at the route).
ERROR_NOT_CONFIGURED = "pr-back-not-configured"
ERROR_PROJECT_NOT_ALLOWED = "pr-back-project-not-allowed"
ERROR_NO_SOURCE = "pr-back-no-source"
ERROR_BRANCH_AMBIGUOUS = "pr-back-branch-ambiguous"
ERROR_NO_RENDERABLE_FILE = "pr-back-no-renderable-file"

#: Failures :func:`run_pr_back` records on a ``failed`` outcome.
ERROR_CREDENTIAL_MISSING = "pr-back-credential-missing"
ERROR_REPOSITORY_ARCHIVED = "pr-back-repository-archived"
ERROR_BASE_BRANCH_MISSING = "pr-back-base-branch-missing"
ERROR_PERMISSION_DENIED = "pr-back-permission-denied"
ERROR_INTERNAL = "pr-back-internal-error"

#: The shared GitHub client's codes are SDK-4.2's (``sdk-git-delivery-…``); an outcome reports
#: them under PR-back's prefix so a caller dispatches on one vocabulary.
_PROVIDER_CODE_PREFIX = "sdk-git-delivery-"

#: ``(action, detail)`` — how the pipeline writes an audit row. Injected by the route.
AuditWriter = Callable[[str, Dict[str, Any]], None]


class PrBackRefusalError(Exception):
    """A PR-back request that cannot start.

    Attributes:
        code: A stable, machine-readable reason.
        message: What is wrong and how to fix it.
        http_status: The status the route answers with.
    """

    def __init__(self, code: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


@dataclass(frozen=True)
class PlannedFile:
    """One file PR-back renders.

    Attributes:
        path: The repository-relative path.
        format: ``json`` or ``yaml``.
        text: The rendered file text.
        document: The rendered document (the change report's candidate).
        paths: How many paths it carries.
        schemas: How many schemas it carries.
        foreign_refs: Schemas it references that another source file defines.
    """

    path: str
    format: str
    text: str
    document: Dict[str, Any]
    paths: int
    schemas: int
    foreign_refs: Tuple[str, ...] = ()


@dataclass(frozen=True)
class PrBackPlan:
    """What a PR-back would write, decided before GitHub is called.

    Attributes:
        base_branch: The branch the pull request merges into.
        branch_name: The PR-back branch.
        files: The files to render.
        skipped: Sentences about source files that are not rendered back, and why.
    """

    base_branch: str
    branch_name: str
    files: Tuple[PlannedFile, ...]
    skipped: Tuple[str, ...] = ()


@dataclass
class PrBackOutcome:
    """What a PR-back did.

    Attributes:
        status: One of :data:`STATUSES`.
        dry_run: Whether nothing was to be written.
        repository_id: The registered repository.
        repository_full_name: ``owner/repo``.
        base_branch: The base branch.
        branch_name: The PR-back branch.
        base_sha: The base commit the files were compared against.
        commit_sha: The commit the branch points at.
        pull_request_number: The pull request opened or refreshed (or already open).
        pull_request_url: Its web page.
        title: The pull request title.
        body: The pull request description (the change report).
        commit_message: The commit message.
        reviewers: Reviewers requested on a newly opened pull request.
        files: One :class:`FileChangeReport` per rendered file.
        skipped: Source files not rendered back, and why.
        log: The event log.
        error_code: Set when the outcome is ``failed``.
        error_message: Set when the outcome is ``failed``, redacted.
    """

    status: str
    dry_run: bool
    repository_id: str
    repository_full_name: Optional[str] = None
    base_branch: Optional[str] = None
    branch_name: Optional[str] = None
    base_sha: Optional[str] = None
    commit_sha: Optional[str] = None
    pull_request_number: Optional[int] = None
    pull_request_url: Optional[str] = None
    title: Optional[str] = None
    body: Optional[str] = None
    commit_message: Optional[str] = None
    reviewers: List[str] = field(default_factory=list)
    files: List[FileChangeReport] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    log: List[Dict[str, Any]] = field(default_factory=list)
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class _RunFailureError(Exception):
    """A run that cannot continue once started, with the code its outcome records."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# -------------------------------------------------------------------------------------------
# Preparation
# -------------------------------------------------------------------------------------------


def _base_branch(settings: PrBackSettings, files: Sequence[SourceFile], repository_name: str) -> str:
    """Decide the pull request's base branch.

    Args:
        settings: The repository's settings.
        files: The project's source files in this repository.
        repository_name: For the message.

    Returns:
        The configured target branch, or the one branch the files were imported from.

    Raises:
        PrBackRefusalError: ``pr-back-branch-ambiguous`` when the files were imported from several
            branches and no target branch is configured.
    """
    if settings.target_branch:
        return settings.target_branch
    branches = sorted({f.branch for f in files})
    if len(branches) == 1:
        return branches[0]
    raise PrBackRefusalError(
        ERROR_BRANCH_AMBIGUOUS,
        f"This project's files in {repository_name} were imported from several branches "
        f"({', '.join(branches)}). Set a target branch in the repository's PR-back settings.",
        409,
    )


def check_eligibility(
    *,
    project: Mapping[str, Any],
    repository: Mapping[str, Any],
    settings: Optional[PrBackSettings],
    sources: Sequence[SourceFile],
) -> Tuple[List[SourceFile], str]:
    """Decide whether a project may PR back into a repository, without rendering anything.

    Args:
        project: The project row (``id``, ``name``).
        repository: The ``tenant_repositories`` row.
        settings: The repository's PR-back settings, or ``None``.
        sources: Every source file of the project, in precedence order.

    Returns:
        ``(files, base_branch)`` — the project's source files in this repository and the branch a
        pull request would merge into.

    Raises:
        PrBackRefusalError: When the repository cannot receive pull requests (unsupported provider,
            no linked account), has no PR-back settings, does not allow the project, holds none of
            the project's files, or its files span branches and no target branch is set.
    """
    repository_id = str(repository.get("id") or "")
    name = str(repository.get("repository_full_name") or repository_id)
    problem = repository_problem(repository, repository_id)
    if problem:
        message = problem.message.replace("Git delivery", "PR-back").replace("git delivery", "PR-back")
        raise PrBackRefusalError(problem.code.replace("sdk-git-delivery", "pr-back"), message, 409)
    if settings is None:
        raise PrBackRefusalError(
            ERROR_NOT_CONFIGURED,
            f"{name} has no PR-back settings, so no project may open pull requests into it. An "
            "administrator of the repository can allow projects in its Settings tab.",
            403,
        )
    project_name = project.get("name") or "This project"
    if not project_allowed(settings, str(project.get("id") or "")):
        listed = "is not on the allow list" if settings.project_policy == "allow" else "is on the deny list"
        raise PrBackRefusalError(
            ERROR_PROJECT_NOT_ALLOWED,
            f"{project_name} {listed} of {name}'s PR-back settings, so it may not open pull "
            "requests into it.",
            403,
        )
    in_repository = [s for s in sources if s.repository_id == repository_id]
    if not in_repository:
        raise PrBackRefusalError(
            ERROR_NO_SOURCE,
            f"{project_name} was not imported from {name}, so there is no file to render back into it.",
            409,
        )
    return in_repository, _base_branch(settings, in_repository, name)


def prepare(
    *,
    spec: Mapping[str, Any],
    project: Mapping[str, Any],
    repository: Mapping[str, Any],
    settings: Optional[PrBackSettings],
    sources: Sequence[SourceFile],
    entity_sources: Mapping[Tuple[str, str], Optional[str]],
) -> PrBackPlan:
    """Check eligibility (:func:`check_eligibility`), then render what PR-back would write.

    Args:
        spec: The version's rendered OpenAPI document.
        project: The project row (``id``, ``slug``, ``name``).
        repository: The ``tenant_repositories`` row.
        settings: The repository's PR-back settings, or ``None``.
        sources: Every source file of the project, in precedence order.
        entity_sources: ``(kind, key) → source_id`` for the version.

    Returns:
        The :class:`PrBackPlan`.

    Raises:
        PrBackRefusalError: Every refusal of :func:`check_eligibility`, and
            ``pr-back-no-renderable-file`` when none of the files is JSON or YAML.
    """
    in_repository, base = check_eligibility(
        project=project, repository=repository, settings=settings, sources=sources
    )
    name = str(repository.get("repository_full_name") or repository.get("id") or "")

    live = {s.source_id for s in sources if s.source_id}
    primary = sources[0].source_id if sources else None

    def owner(kind: str, key: str) -> Optional[str]:
        return owner_of(kind, key, entity_sources, live, primary)

    planned: List[PlannedFile] = []
    skipped: List[str] = []
    seen_paths: Dict[str, SourceFile] = {}
    for source in in_repository:
        fmt = spec_format_for_path(source.path)
        if fmt is None:
            skipped.append(
                f"`{source.path}` is not a JSON or YAML file; Apiome renders OpenAPI, so it is "
                "left as it is."
            )
            continue
        if source.path in seen_paths:
            skipped.append(
                f"`{source.path}` on {source.branch} would overwrite the same file imported from "
                f"{seen_paths[source.path].branch}; only the first is written to {base}."
            )
            continue
        seen_paths[source.path] = source
        document = slice_spec_for_source(spec, source_id=source.source_id, owner=owner)
        planned.append(
            PlannedFile(
                path=source.path,
                format=fmt,
                text=serialize_spec(document, fmt),
                document=document,
                paths=len(document.get("paths") or {}),
                schemas=len(((document.get("components") or {}).get("schemas")) or {}),
                foreign_refs=tuple(foreign_schema_refs(document)),
            )
        )
    if not planned:
        raise PrBackRefusalError(
            ERROR_NO_RENDERABLE_FILE,
            f"None of this project's files in {name} is a JSON or YAML file, so there is nothing "
            "Apiome can render back.",
            409,
        )
    return PrBackPlan(
        base_branch=base,
        branch_name=pr_back_branch_name(project.get("slug"), base),
        files=tuple(planned),
        skipped=tuple(skipped),
    )


# -------------------------------------------------------------------------------------------
# Running
# -------------------------------------------------------------------------------------------


def _change_report(
    planned: PlannedFile,
    existing_text: Optional[str],
    status: str,
    *,
    template_row: Mapping[str, Any],
    project_name: str,
    version_label: str,
    from_label: str,
) -> FileChangeReport:
    """Build one file's change report: the base file → the rendered file.

    Args:
        planned: The rendered file.
        existing_text: The file on the base branch, or ``None`` when it does not exist.
        status: ``added``, ``modified`` or ``unchanged``.
        template_row: The project's effective change report template.
        project_name: For the report header.
        version_label: The version rendered.
        from_label: How to name the base (``main@abc1234``).

    Returns:
        The :class:`FileChangeReport`.
    """
    notes: List[str] = []
    baseline = parse_spec_text(existing_text, planned.format)
    if existing_text is not None and baseline is None:
        notes.append(
            "The file on the base branch could not be read as JSON or YAML (or is larger than "
            "1 MB), so this report compares against an empty document."
        )
    if baseline is not None and "swagger" in baseline and "openapi" not in baseline:
        notes.append(
            f"The file on the base branch is Swagger {baseline.get('swagger')}; Apiome writes it "
            f"back as OpenAPI {planned.document.get('openapi') or '3.x'}."
        )
    report = FileChangeReport(
        path=planned.path,
        status=status,
        paths=planned.paths,
        schemas=planned.schemas,
        foreign_refs=list(planned.foreign_refs),
        notes=notes,
    )
    if status == "unchanged":
        return report
    model = build_change_report(baseline or dict(EMPTY_BASELINE_OPENAPI), planned.document)
    report.counts = change_report_change_counts(model)
    metadata = build_render_metadata(
        product_name=project_name,
        from_version_label=from_label if existing_text is not None else "New file",
        to_version_label=version_label,
        publish_timestamp="—",
    )
    try:
        report.header, report.body, report.footnote = render_from_template_row(
            model, template_row, metadata=metadata
        )
    except Exception:  # noqa: BLE001 - a broken tenant template must not block the pull request
        logger.warning("Change report template failed to render for %s", planned.path, exc_info=True)
        report.notes.append("The project's change report template failed to render; counts only.")
    return report


def _tree_entries(
    github: GitHubGitClient, files: Sequence[Tuple[PlannedFile, Optional[str]]]
) -> List[Dict[str, Any]]:
    """Build the tree request for the changed files (large ones uploaded as blobs first)."""
    entries: List[Dict[str, Any]] = []
    for planned, mode in files:
        entry: Dict[str, Any] = {"path": planned.path, "mode": mode or FILE_MODE, "type": "blob"}
        if len(planned.text.encode("utf-8")) > INLINE_BLOB_MAX_BYTES:
            entry["sha"] = github.create_blob(planned.text)
        else:
            entry["content"] = planned.text
        entries.append(entry)
    return entries


def _execute(
    plan: PrBackPlan,
    outcome: PrBackOutcome,
    *,
    token: str,
    project_name: str,
    version_label: str,
    settings: PrBackSettings,
    template_row: Mapping[str, Any],
    apiome_version: Optional[str],
    client_factory: Optional[ClientFactory],
    log: RunLog,
) -> str:
    """Compare, then (unless a dry run) commit, push and open or refresh the pull request.

    Returns:
        The final status.

    Raises:
        _RunFailureError: For a problem found before anything is written.
        GitProviderError: For a GitHub refusal.
    """
    with GitHubGitClient(token, outcome.repository_full_name or "", client_factory=client_factory) as github:
        info = github.get_repository()
        outcome.repository_full_name = info.full_name
        if info.archived:
            raise _RunFailureError(
                ERROR_REPOSITORY_ARCHIVED,
                f"{info.full_name} is archived on GitHub, so nothing can be pushed to it.",
            )
        if not info.can_push:
            if not outcome.dry_run:
                raise _RunFailureError(
                    ERROR_PERMISSION_DENIED,
                    f"The linked account can read {info.full_name} but cannot push to it. Grant that "
                    "account write access (a classic token needs the `repo` scope; a fine-grained "
                    "token Contents and Pull requests write access), then try again.",
                )
            log.add("resolve", f"The linked account cannot push to {info.full_name}.", level="warn")

        base = plan.base_branch
        base_sha = github.get_branch_sha(base)
        if not base_sha:
            raise _RunFailureError(
                ERROR_BASE_BRANCH_MISSING,
                f"Base branch {base!r} does not exist in {info.full_name}. Create it, or change the "
                "repository's PR-back target branch.",
            )
        outcome.base_sha = base_sha
        base_tree = github.get_commit_tree_sha(base_sha)
        from_label = f"{base}@{base_sha[:7]}"

        changed: List[Tuple[PlannedFile, Optional[str]]] = []
        for planned in plan.files:
            entry = github.find_file(base_tree, planned.path, ref_label=base)
            if entry is not None and entry.sha == git_blob_sha(planned.text):
                status, existing = "unchanged", None
            else:
                status = "modified" if entry is not None else "added"
                existing = github.get_blob_text(entry.sha) if entry is not None else None
                changed.append((planned, entry.mode if entry is not None else None))
            outcome.files.append(
                _change_report(
                    planned,
                    existing if status != "unchanged" else planned.text,
                    status,
                    template_row=template_row,
                    project_name=project_name,
                    version_label=version_label,
                    from_label=from_label,
                )
            )
        log.add(
            "plan",
            f"Against {from_label}: {len(changed)} of {len(plan.files)} file(s) differ from the "
            "rendered spec.",
        )

        open_pull = github.find_open_pull(info.owner, plan.branch_name)
        if open_pull is not None:
            outcome.pull_request_number = open_pull.number
            outcome.pull_request_url = open_pull.url

        outcome.title = pull_request_title(project_name, version_label)
        outcome.body = pull_request_body(
            project_name=project_name,
            version_label=version_label,
            repository_full_name=info.full_name,
            base_branch=base,
            branch_name=plan.branch_name,
            files=outcome.files,
            skipped=plan.skipped,
            apiome_version=apiome_version,
        )
        outcome.commit_message = render_commit_message(
            settings.commit_message_template,
            commit_message_context(project_name, version_label, info.full_name, base, len(changed)),
        )

        if not changed:
            log.add(
                "plan",
                f"{base} already holds this version's spec, so there is nothing to sync."
                + (
                    f" Pull request #{open_pull.number} is still open with nothing left to merge."
                    if open_pull is not None
                    else ""
                ),
                level="warn" if open_pull is not None else "info",
            )
            return STATUS_UP_TO_DATE
        if outcome.dry_run:
            log.add("plan", "Dry run: nothing was written.")
            return STATUS_PREVIEW

        return _push_and_open(
            github, info.owner, plan, outcome, changed, base_sha, base_tree, open_pull, settings, log
        )


def _push_and_open(
    github: GitHubGitClient,
    owner: str,
    plan: PrBackPlan,
    outcome: PrBackOutcome,
    changed: List[Tuple[PlannedFile, Optional[str]]],
    base_sha: str,
    base_tree: str,
    open_pull: Optional[PullRequest],
    settings: PrBackSettings,
    log: RunLog,
) -> str:
    """Commit the changed files, move the branch, and open or refresh the pull request.

    Returns:
        ``opened``, ``updated`` or ``unchanged``.
    """
    branch, base = plan.branch_name, plan.base_branch
    title, body = outcome.title or "", outcome.body or ""
    new_tree = github.create_tree(base_tree, _tree_entries(github, changed))
    branch_sha = github.get_branch_sha(branch)
    head_tree = github.get_commit_tree_sha(branch_sha) if branch_sha else None
    pushed = head_tree != new_tree
    if pushed:
        commit = github.create_commit(outcome.commit_message or title, new_tree, [base_sha])
        outcome.commit_sha = commit
        if branch_sha:
            github.update_branch(branch, commit, force=True)
            log.add("push", f"Force-updated {branch} to {commit[:12]} on top of {base}.")
        elif github.create_branch(branch, commit):
            log.add("push", f"Created {branch} at {commit[:12]} on top of {base}.")
        else:
            github.update_branch(branch, commit, force=True)
            log.add("push", f"{branch} was created concurrently; force-updated it to {commit[:12]}.", level="warn")
    else:
        outcome.commit_sha = branch_sha
        log.add("push", f"{branch} already holds exactly these files on top of {base}; nothing pushed.")

    if open_pull is None:
        opened = github.create_pull(title=title, body=body, head=branch, base=base)
        if opened is not None:
            outcome.pull_request_number, outcome.pull_request_url = opened.number, opened.url
            log.add("pull-request", f"Opened pull request #{opened.number}: {opened.url or title}.")
            _request_reviewers(github, opened.number, settings, outcome, log)
            return STATUS_OPENED
        open_pull = github.find_open_pull(owner, branch)
        if open_pull is None:
            raise GitProviderError(
                ERROR_PULL_REQUEST_REFUSED,
                f"GitHub reported a pull request already open from {branch}, but none could be "
                "found. The commit was pushed; try again to attach it.",
                retryable=True,
            )
        outcome.pull_request_number, outcome.pull_request_url = open_pull.number, open_pull.url

    if not pushed and (open_pull.title, open_pull.body, open_pull.base) == (title, body, base):
        log.add("pull-request", f"Pull request #{open_pull.number} already carries exactly this sync.")
        return STATUS_UNCHANGED
    refreshed = github.update_pull(open_pull.number, title=title, body=body, base=base)
    outcome.pull_request_url = refreshed.url or outcome.pull_request_url
    log.add("pull-request", f"Refreshed pull request #{open_pull.number} instead of opening another.")
    return STATUS_UPDATED


def _request_reviewers(
    github: GitHubGitClient, number: int, settings: PrBackSettings, outcome: PrBackOutcome, log: RunLog
) -> None:
    """Request the repository's reviewers on a newly opened pull request (a refusal only warns)."""
    if not settings.reviewers:
        return
    logins, teams = split_reviewers(settings.reviewers)
    try:
        github.request_reviewers(number, reviewers=logins, team_reviewers=teams)
    except GitProviderError as exc:
        log.add("reviewers", f"Reviewers could not be requested: {exc.message}", level="warn")
        return
    outcome.reviewers = list(settings.reviewers)
    log.add("reviewers", f"Requested reviews from {', '.join(settings.reviewers)}.")


def run_pr_back(
    plan: PrBackPlan,
    *,
    project: Mapping[str, Any],
    version_label: str,
    repository: Mapping[str, Any],
    settings: PrBackSettings,
    template_row: Mapping[str, Any],
    dry_run: bool = False,
    apiome_version: Optional[str] = None,
    audit: Optional[AuditWriter] = None,
    client_factory: Optional[ClientFactory] = None,
) -> PrBackOutcome:
    """Sync a prepared plan to GitHub as a pull request (or preview it).

    Args:
        plan: From :func:`prepare`.
        project: The project row (``id``, ``slug``, ``name``).
        version_label: The version rendered, e.g. ``1.4.0``.
        repository: The ``tenant_repositories`` row.
        settings: The repository's PR-back settings.
        template_row: The project's effective change report template.
        dry_run: Compare and describe, write nothing.
        apiome_version: The running API version, named in the description.
        audit: Writes one audit row per pull request opened or refreshed.
        client_factory: How to obtain the HTTP client; injected by tests.

    Returns:
        The :class:`PrBackOutcome`. A failure is an outcome with status ``failed``.
    """
    log = RunLog(marker=GIT_TOKEN_REDACTION_MARKER)
    project_name = str(project.get("name") or project.get("slug") or "API")
    outcome = PrBackOutcome(
        status=STATUS_FAILED,
        dry_run=dry_run,
        repository_id=str(repository.get("id") or ""),
        repository_full_name=str(repository.get("repository_full_name") or ""),
        base_branch=plan.base_branch,
        branch_name=plan.branch_name,
        skipped=list(plan.skipped),
    )
    try:
        token = resolve_linked_account_token(db, repository)
        if not token:
            raise _RunFailureError(
                ERROR_CREDENTIAL_MISSING,
                f"The GitHub account that registered {outcome.repository_full_name} is no longer "
                "linked, or holds no token, so there is no credential to push with. Re-link that "
                "account, then try again.",
            )
        log.secrets.append(token)
        log.add(
            "resolve",
            f"Rendering {project_name} {version_label} into {len(plan.files)} file(s) of "
            f"{outcome.repository_full_name} with the repository's linked-account credential.",
        )
        outcome.status = _execute(
            plan,
            outcome,
            token=token,
            project_name=project_name,
            version_label=version_label,
            settings=settings,
            template_row=template_row,
            apiome_version=apiome_version,
            client_factory=client_factory,
            log=log,
        )
    except _RunFailureError as exc:
        outcome.status, outcome.error_code = STATUS_FAILED, exc.code
        outcome.error_message = log.redact(exc.message)
    except GitProviderError as exc:
        outcome.status = STATUS_FAILED
        outcome.error_code = exc.code.replace(_PROVIDER_CODE_PREFIX, "pr-back-", 1)
        outcome.error_message = log.redact(exc.message)
    except Exception as exc:  # noqa: BLE001 - an unexplained fault is still an outcome
        logger.exception("PR-back into %s failed unexpectedly", outcome.repository_full_name)
        outcome.status, outcome.error_code = STATUS_FAILED, ERROR_INTERNAL
        outcome.error_message = f"PR-back failed unexpectedly ({type(exc).__name__}). Try again."
    if outcome.error_message:
        log.add("failed", outcome.error_message, level="error")
    outcome.log = list(log.entries)

    if audit is not None and outcome.status in (STATUS_OPENED, STATUS_UPDATED):
        action = AUDIT_PR_BACK_OPENED if outcome.status == STATUS_OPENED else AUDIT_PR_BACK_UPDATED
        audit(
            action,
            {
                "projectId": str(project.get("id") or ""),
                "versionLabel": version_label,
                "repositoryId": outcome.repository_id,
                "repositoryFullName": outcome.repository_full_name,
                "baseBranch": outcome.base_branch,
                "branchName": outcome.branch_name,
                "commitSha": outcome.commit_sha,
                "pullRequestNumber": outcome.pull_request_number,
                "pullRequestUrl": outcome.pull_request_url,
                "files": [f.path for f in outcome.files if f.status != "unchanged"],
                "reviewers": outcome.reviewers,
            },
        )
    return outcome
