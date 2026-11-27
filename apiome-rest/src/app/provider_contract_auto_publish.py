"""Publish provider contracts from their standing sources — PFX-8.7 (#7304).

A provider pacticipant's standing sources (:mod:`app.pacticipant_contract_sources`) say where its
contract comes from. This module publishes it when that source moves:

* :func:`publish_on_project_version` runs after a project version is published
  (``POST /v1/versions/{t}/{project}/{version}/publish``, as a background task). Each provider bound
  to the project with ``onProjectPublish`` on gets the version, rendered as OpenAPI 3.1 exactly as
  ``apiomeVersion`` renders it, as the contract of provider version ``<version label>`` on its main
  branch. **A draft is never published**: the version is re-read and a revision that is not
  published is refused (and audited) whatever the caller says.
* :func:`publish_on_push` runs after a verified push webhook delivery
  (``POST /v1/repositories/webhook/{provider}``). Each provider following a file of that
  repository on the pushed branch gets the file at the pushed commit as the contract of provider
  version ``<commit sha>`` on that branch.

Both go through :func:`app.provider_contract_store.publish_provider_contract` and then
:func:`app.bidirectional_store.compare_provider_contract`, as ``PUT …/contracts/provider/…`` does,
so the verdicts recorded are those the pre-publish check (PFX-8.6) previews.

**Idempotent per version.** A provider version's contract is write-once: publishing the same
document again changes nothing (``unchanged``), and a different one is refused (``failed`` with
the conflict as the reason) — so a redelivered webhook or a re-run never records twice. A push
redelivery is dropped before it gets here (the webhook ledger's delivery id).

**Audited, never silent.** Every attempt appends one ``pacts.contract.auto_publish`` row to
``access_audit`` with the trigger, the outcome (``published`` / ``unchanged`` / ``failed`` /
``skipped``) and, unless it published, the reason. Nothing here ever fails the publish or the push
that triggered it.

**Turning a source off stops new publishes only**: the rows are read when the trigger fires, and
contracts already published are never touched.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from .bidirectional_store import compare_provider_contract
from .config import settings
from .consumer_contract_store import ACTOR_KIND_API_KEY, ACTOR_KIND_USER, ConsumerActor
from .pacticipant import PacticipantValidationError
from .pacticipant_contract_sources import SUPPORTED_REPOSITORY_PROVIDERS
from .provider_contract import ProviderContractError, ProviderContractToStore, parse_openapi, prepare_contract
from .provider_contract_source import ResolvedSource, render_apiome_contract
from .provider_contract_store import publish_provider_contract
from .revision_deprecation import is_uuid_string

logger = logging.getLogger(__name__)

__all__ = [
    "AUDIT_ACTION",
    "OUTCOME_FAILED",
    "OUTCOME_PUBLISHED",
    "OUTCOME_SKIPPED",
    "OUTCOME_UNCHANGED",
    "TRIGGER_PROJECT_PUBLISH",
    "TRIGGER_PUSH",
    "AutoPublishOutcome",
    "publish_on_project_version",
    "publish_on_push",
    "run_on_project_version",
    "run_on_push",
]

#: The ``access_audit`` action of every automatic publish attempt.
AUDIT_ACTION = "pacts.contract.auto_publish"

TRIGGER_PROJECT_PUBLISH = "project-publish"
TRIGGER_PUSH = "push"

OUTCOME_PUBLISHED = "published"
OUTCOME_UNCHANGED = "unchanged"
OUTCOME_FAILED = "failed"
OUTCOME_SKIPPED = "skipped"

#: Reads a repository file: ``(owner, repo, path, ref, token, max_bytes=…) -> (text, truncated)``.
FileReader = Callable[..., Tuple[str, bool]]


class _SourceUnreadableError(Exception):
    """A source that cannot be read; the message is the audited reason."""


@dataclass
class AutoPublishOutcome:
    """What one automatic publish did.

    Attributes:
        provider: The provider's handle.
        provider_version: The provider version the contract was (or would have been) published for.
        trigger: :data:`TRIGGER_PROJECT_PUBLISH` or :data:`TRIGGER_PUSH`.
        outcome: ``published``, ``unchanged``, ``failed`` or ``skipped``.
        reason: Why it did not publish; ``None`` when it did.
        code: The refusal's stable code, when it had one.
        comparisons: The bi-directional comparison counts (``compared``, ``errors``, …).
        source: Where the contract came from (project + version, or repository + path + commit).
    """

    provider: str
    provider_version: str
    trigger: str
    outcome: str
    reason: Optional[str] = None
    code: Optional[str] = None
    comparisons: Dict[str, int] = field(default_factory=dict)
    source: Dict[str, Any] = field(default_factory=dict)

    def detail(self) -> Dict[str, Any]:
        """The audit row's ``detail``."""
        detail: Dict[str, Any] = {
            "trigger": self.trigger,
            "outcome": self.outcome,
            "providerVersion": self.provider_version,
            "source": self.source,
        }
        if self.reason:
            detail["reason"] = self.reason
        if self.code:
            detail["code"] = self.code
        if self.comparisons:
            detail["comparisons"] = self.comparisons
        return detail


_PROJECT_PROVIDERS = """
    SELECT p.id::text AS id, p.slug, p.name, p.main_branch
    FROM apiome.provider_contract_source s
    JOIN apiome.pacticipant p ON p.id = s.pacticipant_id AND p.tenant_id = s.tenant_id
    WHERE s.tenant_id = %s::uuid AND s.on_project_publish
      AND p.project_id = %s::uuid AND p.deleted_at IS NULL
    ORDER BY p.slug
"""

_PUSH_PROVIDERS = """
    SELECT p.id::text AS id, p.slug, p.name, p.main_branch, s.repository_path
    FROM apiome.provider_contract_source s
    JOIN apiome.pacticipant p ON p.id = s.pacticipant_id AND p.tenant_id = s.tenant_id
    WHERE s.tenant_id = %s::uuid AND s.repository_id = %s::uuid AND s.repository_branch = %s
      AND p.deleted_at IS NULL
    ORDER BY p.slug
"""


def _audit(db: Any, tenant_id: str, outcome: AutoPublishOutcome, actor: ConsumerActor) -> None:
    """Append the attempt's ``access_audit`` row (best-effort: the trigger has already happened)."""
    try:
        db.write_access_audit(
            tenant_id=tenant_id,
            action=AUDIT_ACTION,
            actor_id=actor.user_id if actor.user_id and is_uuid_string(str(actor.user_id)) else None,
            actor_label=actor.label,
            target=f"pacticipant/{outcome.provider}/version/{outcome.provider_version}/contract",
            source="system",
            detail=outcome.detail(),
        )
    except Exception:  # noqa: BLE001 - auditing never fails the trigger
        logger.warning("Failed to audit %s for %s", AUDIT_ACTION, outcome.provider, exc_info=True)


def _publish(
    db: Any,
    tenant_id: str,
    provider: Mapping[str, Any],
    *,
    version_number: str,
    branch: Optional[str],
    make_contract: Callable[[], ProviderContractToStore],
    actor: ConsumerActor,
    trigger: str,
    source: Dict[str, Any],
) -> AutoPublishOutcome:
    """Publish one provider's contract and compare it with the pacts that need it; audit the attempt."""
    outcome = AutoPublishOutcome(
        provider=str(provider["slug"]),
        provider_version=version_number,
        trigger=trigger,
        outcome=OUTCOME_FAILED,
        source=source,
    )
    try:
        contract = make_contract()
        published = publish_provider_contract(
            db,
            tenant_id,
            provider_name=str(provider["slug"]),
            version_number=version_number,
            contract=contract,
            actor=actor,
            branch=branch,
        )
    except _SourceUnreadableError as exc:
        outcome.reason = str(exc)
    except (ProviderContractError, PacticipantValidationError) as exc:
        outcome.reason = str(exc)
        outcome.code = exc.code
    except Exception:  # noqa: BLE001 - never fail the trigger; the audit row says it failed
        logger.exception("auto-publish of %s %s failed", provider.get("slug"), version_number)
        outcome.reason = "an unexpected error stopped the publish; it is logged"
    else:
        outcome.outcome = OUTCOME_PUBLISHED if published.created else OUTCOME_UNCHANGED
        if not published.created:
            outcome.reason = f"version {version_number} already has this contract; nothing changed"
        else:
            run = compare_provider_contract(
                db, tenant_id, published.contract.provider_slug, published.contract.provider_version, actor=actor
            )
            summary = run.to_dict()
            outcome.comparisons = {
                key: int(summary[key]) for key in ("compared", "alreadyCompared", "errors", "skipped")
            }
    _audit(db, tenant_id, outcome, actor)
    return outcome


def publish_on_project_version(
    db: Any, tenant_id: str, project_id: str, version_record_id: str, *, actor_id: Optional[str] = None
) -> List[AutoPublishOutcome]:
    """Publish a project version as the contract of every provider that follows the project.

    Args:
        db: The database.
        tenant_id: The project's tenant; providers are read in it only.
        project_id: The project.
        version_record_id: The revision that was just published (``versions.id``).
        actor_id: Who published the version (recorded as the contract's publisher).

    Returns:
        One outcome per provider with ``onProjectPublish`` on, in handle order; empty when none
        follows the project.
    """
    providers = db.execute_query(_PROJECT_PROVIDERS, (tenant_id, project_id)) or []
    if not providers:
        return []
    actor = ConsumerActor(user_id=actor_id, label="Apiome · on every project publish", kind=ACTOR_KIND_USER)
    version = db.get_version_core(version_record_id, tenant_id)
    project = db.get_project_core(project_id, tenant_id)
    label = str((version or {}).get("version_id") or version_record_id)
    source = {
        "kind": "apiome",
        "project": (project or {}).get("slug"),
        "version": label,
        "revisionId": version_record_id,
    }
    refusal: Optional[str] = None
    if not version or str(version.get("project_id")) != str(project_id) or not project:
        refusal = "the version is no longer in this project"
    elif not version.get("published"):
        refusal = f"version {label} is a draft; drafts are never published as a provider contract"
    outcomes: List[AutoPublishOutcome] = []
    for provider in providers:
        if refusal is not None:
            skipped = AutoPublishOutcome(
                provider=str(provider["slug"]),
                provider_version=label,
                trigger=TRIGGER_PROJECT_PUBLISH,
                outcome=OUTCOME_SKIPPED,
                reason=refusal,
                source=source,
            )
            _audit(db, tenant_id, skipped, actor)
            outcomes.append(skipped)
            continue
        resolved = ResolvedSource(
            project_id=str(project_id),
            project_slug=str(project.get("slug") or project_id),
            version_id=str(version_record_id),
            version_label=label,
        )
        outcomes.append(
            _publish(
                db,
                tenant_id,
                provider,
                version_number=label,
                branch=provider.get("main_branch") or None,
                make_contract=lambda resolved=resolved: render_apiome_contract(db, tenant_id, resolved),
                actor=actor,
                trigger=TRIGGER_PROJECT_PUBLISH,
                source=source,
            )
        )
    return outcomes


def _default_reader() -> FileReader:
    """The GitHub contents reader the repository scanner uses."""
    from .repository_file_scan import fetch_github_repository_file_text

    return fetch_github_repository_file_text


def _repository_contract(
    db: Any, repository: Optional[Mapping[str, Any]], path: str, commit_sha: str, read: FileReader
) -> ProviderContractToStore:
    """Read ``path`` at ``commit_sha`` and validate it as a provider contract.

    Raises:
        _SourceUnreadableError: the repository is gone, not readable, or the file is over the size limit.
        ProviderContractError: the file is not an OpenAPI 3.x or AsyncAPI document.
    """
    from .repository_file_scan import _github_owner_repo, _resolve_scan_token

    if not repository:
        raise _SourceUnreadableError("the repository is no longer registered in this workspace")
    provider = str(repository.get("provider") or "").lower()
    if provider not in SUPPORTED_REPOSITORY_PROVIDERS:
        raise _SourceUnreadableError(
            f"files of a {provider or 'unknown'} repository cannot be read on a push; only GitHub's can"
        )
    try:
        owner, name = _github_owner_repo(dict(repository))
        token = _resolve_scan_token(db, dict(repository))
        text, truncated = read(owner, name, path, commit_sha, token, max_bytes=settings.pact_max_bytes)
    except ValueError as exc:
        raise _SourceUnreadableError(f"could not read {path} at {commit_sha[:12]}: {exc}") from exc
    if truncated:
        raise _SourceUnreadableError(
            f"{path} is larger than the {settings.pact_max_bytes}-byte limit (APIOME_PACT_MAX_BYTES)"
        )
    document, content_type = parse_openapi(text.encode("utf-8"), content_type=None, max_bytes=settings.pact_max_bytes)
    return prepare_contract(document, content_type=content_type)


def publish_on_push(
    db: Any,
    tenant_id: str,
    repository_id: str,
    branch: str,
    commit_sha: str,
    *,
    read: Optional[FileReader] = None,
) -> List[AutoPublishOutcome]:
    """Publish a pushed file as the contract of every provider that follows it.

    Args:
        db: The database.
        tenant_id: The repository's tenant; providers are read in it only.
        repository_id: The registered repository that was pushed to.
        branch: The pushed branch.
        commit_sha: The pushed head commit: the provider version.
        read: Reads a repository file (tests inject one); GitHub's contents API by default.

    Returns:
        One outcome per provider following a file of the repository on ``branch``; empty when none.
    """
    providers = db.execute_query(_PUSH_PROVIDERS, (tenant_id, repository_id, branch)) or []
    if not providers:
        return []
    reader = read or _default_reader()
    repository = db.get_tenant_repository(tenant_id, repository_id)
    full_name = (repository or {}).get("repository_full_name")
    actor = ConsumerActor(
        user_id=None, label=f"Apiome · on every push to {full_name or 'a repository'}", kind=ACTOR_KIND_API_KEY
    )
    outcomes: List[AutoPublishOutcome] = []
    for provider in providers:
        path = str(provider["repository_path"])
        outcomes.append(
            _publish(
                db,
                tenant_id,
                provider,
                version_number=commit_sha,
                branch=branch,
                make_contract=lambda path=path: _repository_contract(db, repository, path, commit_sha, reader),
                actor=actor,
                trigger=TRIGGER_PUSH,
                source={
                    "kind": "repository",
                    "repositoryId": repository_id,
                    "repository": full_name,
                    "path": path,
                    "branch": branch,
                    "commit": commit_sha,
                },
            )
        )
    return outcomes


def run_on_project_version(
    *, tenant_id: str, project_id: str, version_record_id: str, actor_id: Optional[str] = None
) -> None:
    """Background-task entry point for :func:`publish_on_project_version`; never raises."""
    from .database import db

    try:
        publish_on_project_version(db, tenant_id, project_id, version_record_id, actor_id=actor_id)
    except Exception:  # noqa: BLE001 - a background task after a committed publish
        logger.exception("auto-publish after the publish of version %s failed", version_record_id)


def run_on_push(*, tenant_id: str, repository_id: str, branch: str, commit_sha: str) -> None:
    """Background-task entry point for :func:`publish_on_push`; never raises."""
    from .database import db

    try:
        publish_on_push(db, tenant_id, repository_id, branch, commit_sha)
    except Exception:  # noqa: BLE001 - a background task after an accepted webhook
        logger.exception("auto-publish after a push to %s@%s failed", repository_id, branch)
