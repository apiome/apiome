"""Evaluating and reading the API change check suite — GNC-3.1 (#4740).

The rules are :mod:`app.api_check_suite`, the evidence is :mod:`app.api_check_suite_evidence`, and
the provider side is GNC-2.2's :mod:`app.provider_check_store`. What lives here is the order they
happen in, and the three rules that order enforces.

**The suite judges the draft, and a draft is at exactly one commit.** A bound draft is
synchronized with one commit of its branch — :attr:`binding.commit_sha` — and that is the commit a
verdict about the draft is reported against. A newer commit on the branch (a sync candidate the
draft has not caught up with) gets a *placeholder*: ``skipped`` with ``spec-unchanged`` when the
bound files are byte-for-byte what the draft was synchronized with (the pull request does not touch
the API), otherwise ``pending`` with ``draft-not-synchronized``. Guessing that the draft already
reflects that commit would put a verdict about one document on another. A commit the binding has
never been observed at is refused.

**Same inputs, same row.** An evaluation is inserted under its input fingerprint; a collision means
these exact inputs were already evaluated, and *that* row comes back (``replayed``) — the same
evidence ids, not a new almost-identical record. The provider side is then only touched when it
does not already say the same thing, so a re-run neither stacks a second check on the pull request
nor calls the provider for a publish it already made.

**Recording comes before reporting.** The evaluation is written first; putting it on the provider
is GNC-2.2's job and GNC-2.2's rules apply — a provider that refuses leaves a ``failed`` ledger row,
and the evaluation stands.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Mapping, Optional, Tuple

from . import provider_check_store
from .api_check_suite import (
    CODE_COMMIT_UNKNOWN,
    CODE_INVALID_COMMIT,
    CODE_INVALID_DOCUMENT,
    CODE_NOT_BOUND,
    CODE_NOT_RUN,
    CODE_PROJECT_NOT_FOUND,
    CODE_RUN_NOT_FOUND,
    CODE_VERSION_NOT_FOUND,
    COMPONENT_CONSUMERS,
    REASON_DRAFT_NOT_SYNCHRONIZED,
    REASON_SPEC_UNCHANGED,
    SUITE_CHECK_NAME,
    CheckSuiteError,
    CheckSuiteRunDetail,
    CheckSuiteRunList,
    CheckSuiteRunRecord,
    CheckSuiteRunRequest,
    ProviderReport,
    SuiteComponent,
    aggregate,
    canonical_policy_body,
    component_counts,
    input_fingerprint,
    render_summary,
    render_title,
    requirements_fingerprint,
)
from .api_check_suite_evidence import gather_components
from .api_check_suite_policy_store import load_policy
from .database import db
from .deploy_gate import canonical_thresholds_body
from .deploy_gate_store import load_policy as load_thresholds
from .draft_binding_store import read_source
from .draft_binding_store import resolve_project as _resolve_binding_project
from .draft_binding_store import resolve_version as _resolve_binding_version
from .draft_bindings import DraftBindingValidationError
from .provider_checks import (
    CODE_BINDING_RELEASED,
    OUTCOME_DISPATCHED,
    STATE_PENDING,
    STATE_SKIPPED,
    CheckRunDetail,
    CheckRunUpsert,
    ProviderCheckValidationError,
    normalize_commit_sha,
)
from .spec_sync_store import read_draft_document

logger = logging.getLogger(__name__)

__all__ = [
    "RUN_LIST_LIMIT",
    "drill_down_path",
    "get_run",
    "latest_run",
    "list_runs",
    "record_from_row",
    "resolve_project",
    "redact_consumers",
    "run_suite",
]

#: The largest page of evaluations one read returns.
RUN_LIST_LIMIT = 200

#: How many of a binding's sync candidates are scanned for a named commit. A binding keeps one
#: pending candidate at a time (older ones are superseded), so the commit a pull request is at is
#: always near the top.
_CANDIDATE_SCAN_LIMIT = 50

#: The shortest commit prefix accepted as naming a commit.
_MIN_COMMIT_PREFIX = 7


# ---------------------------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------------------------


def resolve_project(tenant_id: str, project_ref: str) -> Dict[str, Any]:
    """Resolve a project slug or id, re-coding the binding store's refusal.

    Public so the policy routes and the suite agree about what a project reference names — a
    policy saved against ``petstore`` must be the one an evaluation of ``petstore`` reads.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or UUID.

    Returns:
        The project row.

    Raises:
        CheckSuiteError: ``check-suite-project-not-found``.
    """
    try:
        return dict(_resolve_binding_project(tenant_id, project_ref))
    except DraftBindingValidationError as exc:
        raise CheckSuiteError(CODE_PROJECT_NOT_FOUND, str(exc)) from exc


def _resolve_version(tenant_id: str, project_id: str, version_ref: str) -> Dict[str, Any]:
    """Resolve a revision id or version label, re-coding the binding store's refusal.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project the version must belong to.
        version_ref: A revision UUID or a version label.

    Returns:
        The version row.

    Raises:
        CheckSuiteError: ``check-suite-version-not-found``.
    """
    try:
        return dict(_resolve_binding_version(tenant_id, project_id, version_ref))
    except DraftBindingValidationError as exc:
        raise CheckSuiteError(CODE_VERSION_NOT_FOUND, str(exc)) from exc


def _normalize_commit(raw: str) -> str:
    """Validate a named commit, re-coding GNC-2.2's refusal.

    Args:
        raw: The commit as given.

    Returns:
        The lowercased commit id.

    Raises:
        CheckSuiteError: ``check-suite-invalid-commit``.
    """
    try:
        return normalize_commit_sha(raw)
    except ProviderCheckValidationError as exc:
        raise CheckSuiteError(CODE_INVALID_COMMIT, str(exc)) from exc


def _same_commit(named: str, known: Optional[str]) -> bool:
    """Whether a named commit (possibly abbreviated) is a known one.

    Args:
        named: The commit a caller named, already normalized.
        known: A commit the platform recorded.

    Returns:
        True for an exact match, or for a prefix of at least seven characters.
    """
    full = str(known or "").strip().lower()
    if not full or not named:
        return False
    if named == full:
        return True
    return len(named) >= _MIN_COMMIT_PREFIX and full.startswith(named)


def _read_draft(tenant_id: str, version: Mapping[str, Any]) -> Tuple[Dict[str, Any], str]:
    """Rebuild the draft document and its digest, or refuse.

    Args:
        tenant_id: The caller's tenant.
        version: The revision row.

    Returns:
        ``(document, "sha256:…")``.

    Raises:
        CheckSuiteError: ``check-suite-invalid-document`` when the draft cannot be rebuilt — there
            is nothing to judge, and no component could say anything true about it.
    """
    try:
        return read_draft_document(tenant_id, version)
    except Exception as exc:  # noqa: BLE001 - any rebuild failure means the same thing here
        raise CheckSuiteError(
            CODE_INVALID_DOCUMENT, f"The draft could not be rebuilt into a document: {exc}"
        ) from exc


# ---------------------------------------------------------------------------------------------
# A commit the draft is not at
# ---------------------------------------------------------------------------------------------


def _candidate_for(
    tenant_id: str, binding_id: str, commit: str
) -> Optional[Dict[str, Any]]:
    """The sync candidate that observed the branch at a commit, if any.

    Args:
        tenant_id: The caller's tenant.
        binding_id: The binding.
        commit: The named commit.

    Returns:
        The newest candidate naming that commit, or ``None``.
    """
    rows = db.list_binding_sync_candidates(
        tenant_id=tenant_id, binding_id=binding_id, limit=_CANDIDATE_SCAN_LIMIT
    )
    for row in rows or []:
        if _same_commit(commit, row.get("to_commit_sha")):
            return dict(row)
    return None


def _digest_at(
    tenant_id: str, user_id: str, binding: Mapping[str, Any], candidate: Mapping[str, Any]
) -> Optional[str]:
    """The bound selection's digest at a candidate's commit.

    A candidate records it once somebody has read that commit; a webhook-raised one has not, and
    then it is read here through the binding's own proven-read path — the same credential and the
    same digest a binding is written with. Any failure yields ``None``: without the digest the
    suite cannot prove the change leaves the specification alone, so it waits rather than guesses.

    Args:
        tenant_id: The caller's tenant.
        user_id: The acting user.
        binding: The binding.
        candidate: The candidate at the named commit.

    Returns:
        ``"sha256:…"``, or ``None``.
    """
    known = str(candidate.get("to_digest") or "")
    if known:
        return known
    if not binding.get("repository_id"):
        return None
    try:
        resolved = read_source(
            tenant_id,
            user_id,
            repo_url=str(binding.get("repo_url") or ""),
            ref=str(candidate.get("to_commit_sha") or ""),
            path=str(binding.get("path") or ""),
            repository_id=str(binding["repository_id"]),
        )
    except Exception:  # noqa: BLE001 - an unreadable commit is "cannot prove", never a failure
        logger.info(
            "Check suite could not read binding %s at %s; the verdict waits",
            binding.get("id"),
            candidate.get("to_commit_sha"),
            exc_info=True,
        )
        return None
    return resolved.digest


def _placeholder_for(
    tenant_id: str, user_id: str, binding: Mapping[str, Any], commit: str
) -> Tuple[str, str, str]:
    """Decide what the suite can say about a commit the draft is not synchronized with.

    Args:
        tenant_id: The caller's tenant.
        user_id: The acting user.
        binding: The binding.
        commit: The named commit, normalized.

    Returns:
        ``(state, reason, full commit)`` — ``skipped``/``spec-unchanged`` when the bound selection
        at that commit is what the draft was synchronized with, otherwise
        ``pending``/``draft-not-synchronized``.

    Raises:
        CheckSuiteError: ``check-suite-commit-unknown`` when the binding has never been observed
            at that commit.
    """
    candidate = _candidate_for(tenant_id, str(binding["id"]), commit)
    if candidate is None:
        raise CheckSuiteError(
            CODE_COMMIT_UNKNOWN,
            "This binding has never been observed at that commit. A push to the bound branch "
            "raises it; or run the suite without a commit to report against the commit the draft "
            "is synchronized with.",
        )
    full = str(candidate.get("to_commit_sha") or commit)
    digest = _digest_at(tenant_id, user_id, binding, candidate)
    if digest and digest == str(binding.get("source_digest") or ""):
        return STATE_SKIPPED, REASON_SPEC_UNCHANGED, full
    return STATE_PENDING, REASON_DRAFT_NOT_SYNCHRONIZED, full


# ---------------------------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------------------------


def drill_down_path(tenant_slug: str, project_id: str, run_id: str) -> str:
    """The API path of one evaluation — what a provider check's summary points at.

    Args:
        tenant_slug: The tenant.
        project_id: The project.
        run_id: The evaluation.

    Returns:
        The path.
    """
    return f"/v1/tenants/{tenant_slug}/projects/{project_id}/check-suite/runs/{run_id}"


def _render(record: CheckSuiteRunRecord, tenant_slug: str, components: List[SuiteComponent]) -> str:
    """Render the provider summary of an evaluation.

    Args:
        record: The evaluation.
        tenant_slug: The tenant, for the drill-down path.
        components: The components to render (possibly redacted).

    Returns:
        The markdown summary.
    """
    return render_summary(
        run_id=record.id,
        state=record.state,
        reason=record.reason,
        components=components,
        version_label=record.version_label,
        commit_sha=record.commit_sha,
        draft_digest=record.draft_digest,
        policy_source=record.policy_source,
        policy_fingerprint_value=record.policy_fingerprint,
        thresholds_source=record.thresholds_source,
        thresholds_fingerprint=record.thresholds_fingerprint,
        drill_down=drill_down_path(tenant_slug, record.project_id, record.id),
    )


def record_from_row(row: Mapping[str, Any], tenant_slug: str) -> CheckSuiteRunRecord:
    """Map a stored evaluation onto its record, rendering what a reviewer reads.

    The title and summary are not stored: they are a pure function of the row, so rendering them
    on read keeps the row the single source of truth and a replay byte-identical.

    Args:
        row: The database row.
        tenant_slug: The tenant, for the drill-down path.

    Returns:
        The record.
    """
    components = [SuiteComponent(**dict(item)) for item in (row.get("components") or [])]
    record = CheckSuiteRunRecord(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        project_id=str(row["project_id"]),
        version_id=str(row["version_id"]),
        version_label=row.get("version_label"),
        binding_id=str(row["binding_id"]) if row.get("binding_id") else None,
        commit_sha=row.get("commit_sha"),
        pr_number=row.get("pr_number"),
        check_name=str(row.get("check_name") or SUITE_CHECK_NAME),
        evaluated=bool(row.get("evaluated")),
        state=str(row["state"]),
        reason=str(row["reason"]),
        draft_digest=str(row["draft_digest"]),
        policy_source=str(row["policy_source"]),
        policy_fingerprint=str(row["policy_fingerprint"]),
        policy=dict(row.get("policy") or {}),
        thresholds_source=str(row["thresholds_source"]),
        thresholds_fingerprint=str(row["thresholds_fingerprint"]),
        thresholds=dict(row.get("thresholds") or {}),
        components=components,
        counts=component_counts(components),
        input_fingerprint=str(row["input_fingerprint"]),
        created_by=str(row["created_by"]) if row.get("created_by") else None,
        created_by_name=row.get("created_by_name"),
        created_at=row["created_at"],
        title=render_title(str(row["state"]), str(row["reason"]), components),
    )
    return record.model_copy(update={"summary": _render(record, tenant_slug, components)})


def redact_consumers(record: CheckSuiteRunRecord, tenant_slug: str) -> CheckSuiteRunRecord:
    """Hide consumer names from a caller who may not read the consumer registry.

    The verdict is computed once, with the platform's view of the registry, so it never depends on
    who asked. What a *reader* sees is gated, as CTG-4.5's gate gates its consumer signal: without
    ``consumer_contracts:view`` the consumers component keeps its state, reason and counts, and
    loses the names.

    Args:
        record: The evaluation.
        tenant_slug: The tenant, for re-rendering the summary.

    Returns:
        The record, redacted when it named anyone; otherwise unchanged.
    """
    changed = False
    components: List[SuiteComponent] = []
    for component in record.components:
        evidence = component.evidence
        if component.component == COMPONENT_CONSUMERS and (
            evidence.get("breakingConsumers") or evidence.get("summary")
        ):
            counts = evidence.get("counts") or {}
            kept = {k: v for k, v in evidence.items() if k not in ("summary", "breakingConsumers")}
            kept["redacted"] = True
            component = component.model_copy(
                update={
                    "evidence": kept,
                    "detail": (
                        f"{int(counts.get('consumers_breaking', 0) or 0)} broken and "
                        f"{int(counts.get('consumers_affected', 0) or 0)} affected of "
                        f"{int(counts.get('consumers_total', 0) or 0)} registered consumers. This "
                        "credential cannot read the consumer registry (`consumer_contracts:view`), "
                        "so they are not named."
                    ),
                }
            )
            changed = True
        components.append(component)
    if not changed:
        return record
    return record.model_copy(
        update={"components": components, "summary": _render(record, tenant_slug, components)}
    )


def _detail(
    record: CheckSuiteRunRecord,
    *,
    tenant_slug: str,
    consumers_visible: bool,
    replayed: bool = False,
    stale: bool = False,
    provider: Optional[ProviderReport] = None,
    check: Optional[CheckRunDetail] = None,
) -> CheckSuiteRunDetail:
    """Assemble what a caller receives, redacted for what they may read.

    Args:
        record: The evaluation.
        tenant_slug: The tenant.
        consumers_visible: Whether the caller may read consumer contracts.
        replayed: Whether this evaluation already existed.
        stale: Whether the draft or a policy has moved since.
        provider: The provider side.
        check: The GNC-2.2 check run.

    Returns:
        The detail.
    """
    shown = record if consumers_visible else redact_consumers(record, tenant_slug)
    if check is not None and shown is not record and check.check.summary == record.summary:
        # The published text names consumers too; a caller who may not read them gets the same
        # redacted summary the record carries.
        check = check.model_copy(
            update={"check": check.check.model_copy(update={"summary": shown.summary})}
        )
    return CheckSuiteRunDetail(
        run=shown, replayed=replayed, stale=stale, provider=provider, check=check
    )


# ---------------------------------------------------------------------------------------------
# The provider side
# ---------------------------------------------------------------------------------------------


def _existing_check(
    tenant_id: str, binding_id: str, commit_sha: str, name: str
) -> Optional[Dict[str, Any]]:
    """The GNC-2.2 check run a ``(binding, commit, name)`` triple identifies, if there is one.

    Args:
        tenant_id: The tenant.
        binding_id: The binding.
        commit_sha: The commit.
        name: The check name.

    Returns:
        The check row, or ``None``.
    """
    rows = db.list_provider_check_runs(
        tenant_id=tenant_id, binding_id=binding_id, commit_sha=commit_sha, limit=50
    )
    for row in rows or []:
        if str(row.get("name")) == name:
            return dict(row)
    return None


def _report_to_provider(
    *,
    tenant_id: str,
    user_id: str,
    project_id: str,
    version_id: str,
    binding: Mapping[str, Any],
    record: CheckSuiteRunRecord,
    request: CheckSuiteRunRequest,
    replayed: bool,
    client_factory: Optional[Any] = None,
) -> Tuple[ProviderReport, Optional[CheckRunDetail]]:
    """Put an evaluation on the pull request through GNC-2.2 — never raises.

    A replayed evaluation whose check already says exactly the same thing is not re-recorded (that
    would only append audit rows about nothing); it is re-*published* only when its last publish
    did not go out, which is what lets a re-run heal a provider that had a bad minute.

    Args:
        tenant_id: The tenant.
        user_id: The acting user.
        project_id: The project.
        version_id: The version.
        binding: The active binding.
        record: The evaluation.
        request: The caller's request (``publish``, ``pr_number``).
        replayed: Whether the evaluation already existed.
        client_factory: How the adapter obtains an HTTP client; injected in tests.

    Returns:
        ``(what happened, the check run)``.
    """
    if not binding.get("repository_id"):
        return (
            ProviderReport(
                recorded=False,
                reason=CODE_BINDING_RELEASED,
                message=(
                    "The repository this draft is bound to is no longer registered, so the verdict "
                    "was recorded here and could not be reported to the provider."
                ),
            ),
            None,
        )
    commit = str(record.commit_sha or "")
    details_url = provider_check_store.version_details_url(project_id, version_id)
    existing = _existing_check(tenant_id, str(binding["id"]), commit, record.check_name)
    if (
        replayed
        and existing
        and str(existing.get("state")) == record.state
        and str(existing.get("title") or "") == record.title
        and str(existing.get("summary") or "") == record.summary
        and str(existing.get("details_url") or "") == details_url
    ):
        if request.publish and existing.get("last_publish_outcome") != OUTCOME_DISPATCHED:
            provider_check_store.publish_check(
                db,
                existing,
                repository_id=str(binding["repository_id"]),
                actor_id=user_id,
                client_factory=client_factory,
            )
        try:
            detail = provider_check_store.get_check(tenant_id, project_id, str(existing["id"]))
        except ProviderCheckValidationError:  # pragma: no cover - the row was just read
            detail = None
        return ProviderReport(recorded=True), detail

    try:
        detail = provider_check_store.record_check(
            tenant_id,
            user_id,
            project_id,
            version_id,
            CheckRunUpsert(
                name=record.check_name,
                state=record.state,
                commit_sha=commit,
                title=record.title,
                summary=record.summary,
                details_url=details_url,
                pr_number=request.pr_number,
                publish=request.publish,
            ),
            client_factory=client_factory,
        )
    except ProviderCheckValidationError as exc:
        return ProviderReport(recorded=False, reason=exc.code, message=str(exc)), None
    return ProviderReport(recorded=True), detail


def _check_for_record(
    tenant_id: str, project_id: str, record: CheckSuiteRunRecord
) -> Optional[CheckRunDetail]:
    """The GNC-2.2 check run an evaluation was reported as, for a read.

    Args:
        tenant_id: The tenant.
        project_id: The project.
        record: The evaluation.

    Returns:
        The check detail, or ``None`` when it was never reported (or no longer exists).
    """
    if not record.binding_id or not record.commit_sha:
        return None
    existing = _existing_check(tenant_id, record.binding_id, record.commit_sha, record.check_name)
    if not existing:
        return None
    try:
        return provider_check_store.get_check(tenant_id, project_id, str(existing["id"]))
    except ProviderCheckValidationError:
        return None


# ---------------------------------------------------------------------------------------------
# Evaluate
# ---------------------------------------------------------------------------------------------


async def run_suite(
    *,
    tenant_id: str,
    tenant_slug: str,
    user_id: str,
    project_ref: str,
    version_ref: str,
    request: CheckSuiteRunRequest,
    consumers_visible: bool = True,
    client_factory: Optional[Any] = None,
) -> CheckSuiteRunDetail:
    """Evaluate the suite for a version, record it, and report it when the version is bound.

    Args:
        tenant_id: The caller's tenant.
        tenant_slug: The tenant slug (evidence links, the kit's coordinates, the drill-down).
        user_id: The acting user.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.
        request: The commit, pull request and publish choice.
        consumers_visible: Whether the caller may read consumer contracts (the response only —
            the verdict never depends on it).
        client_factory: How the status adapter obtains an HTTP client; injected in tests.

    Returns:
        The evaluation, whether it was a replay, and the provider check it became.

    Raises:
        CheckSuiteError: For an unknown project or version, a commit on an unbound version, an
            invalid or unknown commit, or a draft that cannot be rebuilt.
    """
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    version = _resolve_version(tenant_id, project_id, version_ref)
    version_id = str(version["id"])
    found = db.get_active_draft_binding(
        tenant_id=tenant_id, project_id=project_id, version_id=version_id
    )
    binding = dict(found) if found else None

    requested = (request.commit_sha or "").strip()
    if requested and binding is None:
        raise CheckSuiteError(
            CODE_NOT_BOUND,
            "This version is not bound to a repository ref, so there is no commit to report "
            "against. Run the suite without a commit.",
        )
    named = _normalize_commit(requested) if requested else ""

    policy_out = load_policy(tenant_id, project_id)
    requirements = requirements_fingerprint(policy_out.policy)
    thresholds_out = load_thresholds(tenant_id, project_id)
    draft_document, draft_digest = _read_draft(tenant_id, version)

    commit: Optional[str] = None
    placeholder: Optional[Tuple[str, str, str]] = None
    if binding is not None:
        synchronized = str(binding.get("commit_sha") or "")
        commit = synchronized
        if named and not _same_commit(named, synchronized):
            placeholder = await asyncio.to_thread(
                _placeholder_for, tenant_id, user_id, binding, named
            )
            commit = placeholder[2]

    if placeholder is not None:
        state, reason = placeholder[0], placeholder[1]
        components: List[SuiteComponent] = []
    else:
        components = await gather_components(
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            project=project,
            version=version,
            draft_document=draft_document,
            policy=policy_out.policy,
            thresholds=thresholds_out.thresholds,
        )
        state, reason = aggregate(components)

    binding_id = str(binding["id"]) if binding is not None else None
    fingerprint = input_fingerprint(
        version_id=version_id,
        draft_digest=draft_digest,
        binding_id=binding_id,
        commit_sha=commit,
        check_name=SUITE_CHECK_NAME,
        evaluated=placeholder is None,
        state=state,
        reason=reason,
        policy_fingerprint_value=requirements,
        thresholds_fingerprint=thresholds_out.content_fingerprint,
        components=components,
    )
    produced = db.insert_check_suite_run(
        tenant_id=tenant_id,
        project_id=project_id,
        version_id=version_id,
        binding_id=binding_id,
        commit_sha=commit,
        pr_number=request.pr_number,
        check_name=SUITE_CHECK_NAME,
        evaluated=placeholder is None,
        state=state,
        reason=reason,
        draft_digest=draft_digest,
        policy_source=policy_out.source,
        policy_fingerprint=requirements,
        policy=canonical_policy_body(policy_out.policy),
        thresholds_source=thresholds_out.source,
        thresholds_fingerprint=thresholds_out.content_fingerprint,
        thresholds=canonical_thresholds_body(thresholds_out.thresholds),
        components=[component.model_dump(mode="json") for component in components],
        input_fingerprint=fingerprint,
        created_by=user_id,
    )
    replayed = produced is None
    row = (
        db.get_check_suite_run(tenant_id=tenant_id, run_id=str(produced["id"]))
        if produced
        else db.find_check_suite_run(
            tenant_id=tenant_id, version_id=version_id, input_fingerprint=fingerprint
        )
    )
    if not row:  # pragma: no cover - the row was written or collided with a committed one
        raise RuntimeError("The check-suite evaluation could not be read back.")
    record = record_from_row(row, tenant_slug)

    provider: Optional[ProviderReport] = None
    check: Optional[CheckRunDetail] = None
    if binding is not None:
        # The publish reaches a provider over the network, so it runs on a worker thread rather
        # than holding the event loop for the length of somebody else's API call.
        provider, check = await asyncio.to_thread(
            _report_to_provider,
            tenant_id=tenant_id,
            user_id=user_id,
            project_id=project_id,
            version_id=version_id,
            binding=binding,
            record=record,
            request=request,
            replayed=replayed,
            client_factory=client_factory,
        )

    return _detail(
        record,
        tenant_slug=tenant_slug,
        consumers_visible=consumers_visible,
        replayed=replayed,
        provider=provider,
        check=check,
    )


# ---------------------------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------------------------


def _is_stale(
    tenant_id: str, project_id: str, version: Mapping[str, Any], record: CheckSuiteRunRecord
) -> bool:
    """Whether an evaluation no longer answers for the version as it is now.

    Stale when the draft's content moved, the component requirements did, or the deploy-gate
    thresholds did — the same three facts the publish gate matches an evaluation on. A draft that
    cannot be rebuilt cannot be shown to match, so it reads as stale.

    Args:
        tenant_id: The tenant.
        project_id: The project.
        version: The revision row.
        record: The evaluation.

    Returns:
        True when it is stale.
    """
    try:
        _document, digest = read_draft_document(tenant_id, version)
    except Exception:  # noqa: BLE001 - an unbuildable draft cannot be shown to match
        return True
    return (
        digest != record.draft_digest
        or requirements_fingerprint(load_policy(tenant_id, project_id).policy)
        != record.policy_fingerprint
        or load_thresholds(tenant_id, project_id).content_fingerprint
        != record.thresholds_fingerprint
    )


def latest_run(
    tenant_id: str,
    tenant_slug: str,
    project_ref: str,
    version_ref: str,
    *,
    commit_sha: Optional[str] = None,
    consumers_visible: bool = True,
) -> CheckSuiteRunDetail:
    """The newest evaluation of a version (at a commit, when one is named).

    Args:
        tenant_id: The caller's tenant.
        tenant_slug: The tenant slug.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.
        commit_sha: Only evaluations reported against this commit.
        consumers_visible: Whether the caller may read consumer contracts.

    Returns:
        The evaluation, whether it is stale, and the check it became.

    Raises:
        CheckSuiteError: For an unknown project or version, an invalid commit, or
            ``check-suite-not-run`` when nothing matches.
    """
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    version = _resolve_version(tenant_id, project_id, version_ref)
    commit = _normalize_commit(commit_sha) if (commit_sha or "").strip() else None
    rows = db.list_check_suite_runs(
        tenant_id=tenant_id, version_id=str(version["id"]), commit_sha=commit, limit=1
    )
    if not rows:
        raise CheckSuiteError(
            CODE_NOT_RUN,
            "The API change check suite has not been run for this version"
            + (" at that commit." if commit else "."),
        )
    record = record_from_row(rows[0], tenant_slug)
    return _detail(
        record,
        tenant_slug=tenant_slug,
        consumers_visible=consumers_visible,
        stale=_is_stale(tenant_id, project_id, version, record),
        check=_check_for_record(tenant_id, project_id, record),
    )


def get_run(
    tenant_id: str,
    tenant_slug: str,
    project_ref: str,
    run_id: str,
    *,
    consumers_visible: bool = True,
) -> CheckSuiteRunDetail:
    """One evaluation by id — the drill-down a provider check's summary points at.

    Args:
        tenant_id: The caller's tenant.
        tenant_slug: The tenant slug.
        project_ref: Project slug or id.
        run_id: The evaluation.
        consumers_visible: Whether the caller may read consumer contracts.

    Returns:
        The evaluation, whether it is stale, and the check it became.

    Raises:
        CheckSuiteError: ``check-suite-run-not-found`` when it is not this project's.
    """
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    row = db.get_check_suite_run(tenant_id=tenant_id, run_id=run_id)
    if not row or str(row.get("project_id")) != project_id:
        raise CheckSuiteError(CODE_RUN_NOT_FOUND, "No such check-suite evaluation.")
    record = record_from_row(row, tenant_slug)
    version = db.get_version_by_id(record.version_id, tenant_id)
    return _detail(
        record,
        tenant_slug=tenant_slug,
        consumers_visible=consumers_visible,
        stale=_is_stale(tenant_id, project_id, version, record) if version else True,
        check=_check_for_record(tenant_id, project_id, record),
    )


def list_runs(
    tenant_id: str,
    tenant_slug: str,
    project_ref: str,
    version_ref: str,
    *,
    commit_sha: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    consumers_visible: bool = True,
) -> CheckSuiteRunList:
    """A version's evaluations, newest first.

    Args:
        tenant_id: The caller's tenant.
        tenant_slug: The tenant slug.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.
        commit_sha: Only evaluations reported against this commit.
        limit: Page size.
        offset: Evaluations to skip.
        consumers_visible: Whether the caller may read consumer contracts.

    Returns:
        The page.

    Raises:
        CheckSuiteError: For an unknown project or version, or an invalid commit.
    """
    project = resolve_project(tenant_id, project_ref)
    version = _resolve_version(tenant_id, str(project["id"]), version_ref)
    commit = _normalize_commit(commit_sha) if (commit_sha or "").strip() else None
    page = max(1, min(int(limit), RUN_LIST_LIMIT))
    rows = db.list_check_suite_runs(
        tenant_id=tenant_id,
        version_id=str(version["id"]),
        commit_sha=commit,
        limit=page,
        offset=max(0, int(offset)),
    )
    records = [record_from_row(row, tenant_slug) for row in rows]
    if not consumers_visible:
        records = [redact_consumers(record, tenant_slug) for record in records]
    return CheckSuiteRunList(runs=records, count=len(records), limit=page, offset=max(0, int(offset)))
