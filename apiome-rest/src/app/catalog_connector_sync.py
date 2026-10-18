"""Catalog connector sync engine — CDG-1.1 (#5952).

One sync run of one connector, and the scheduled sweep that runs them. A connector is a
:class:`~app.refresh_source.RefreshSource`, so a run goes through the same steps as a Git
refresh (list → newer-than gate → fetch) on the same ledger and quota:

1. **Open a run** on ``tenant_repository_refresh_jobs`` (``refresh_source = 'connector'``). At
   most one run per connector is active at a time (V281's single-flight index).
2. **List the inventory** through the source. A provider refusal (:class:`RefreshSourceError`)
   ends the run as ``failed`` with the provider's error class and HTTP status, never as a
   success with zero changes, and the connector turns ``failing``.
3. **Record what was seen.** Every candidate is upserted into ``catalog_connector_items``; a row
   the inventory no longer lists becomes ``missing``. Nothing is ever deleted, and a missing
   API's catalog item stays where it is.
4. **Gate on freshness.** :func:`~app.refresh_source.decide_refresh` applies the RAR-2.2
   newer-than rule to the remote revision / update time against the anchor stored at the last
   import. ``ignored`` items are skipped.
5. **Fetch and import** each fresh candidate. The document goes through the in-process import
   pipeline as a **catalog item** (the connector payload forces the catalog route, OpenAPI
   included), with the source descriptor ``{inputKind: "connector", connectorId, remoteId,
   remoteRevision}`` in the revision's format metadata, which the Provenance tab shows. A
   remote revision becomes a new revision of the same catalog item.
6. **Close the run**, count the pulls against the tenant's repository quota window
   (``polls``), and write a ``repository.connector.sync`` row to the workflow audit, so the
   repository audit export lists connector runs beside Git refreshes.

A run in which every attempted candidate failed (fetch refused, or import refused) is
``failed``, with the first failure's class and status. A run where some failed and others
succeeded is ``succeeded`` with the failures counted in its summary.

**Credentials** are unsealed in memory for the source and never written anywhere: not to the
run, not to the audit row, not to a log line. A provider error message that happens to echo a
credential value has the value redacted before it is stored.

**Sources** are registered per kind with :func:`register_connector_source`, optionally with a
scope validator the routes run on every write (:func:`validate_connector_scope`). The Kong
sources (``kong-konnect``, ``kong-admin``; CDG-1.2) and the AWS API Gateway source
(``aws-apigateway``; CDG-1.3) and the Azure API Management source (``azure-apim``; CDG-1.4)
register themselves from :mod:`app.kong_connector_source`, :mod:`app.aws_apigateway_connector_source`
and :mod:`app.azure_apim_connector_source`, imported at the bottom of this module; the other
gateway sources are CDG-1.5–1.7 and the ``url`` source is RAR-6.1. A connector whose kind has no source
is listed and editable but cannot sync (``connector-kind-unsupported``), and the sweep skips it.

**Findings.** A source may expose ``findings`` (a list of credential-free dicts with a ``code``)
about the inventory as a whole rather than one API — the Kong source reports a route that
belongs to no service this way. The run records them in its summary (``findings``, capped at
:data:`FINDINGS_MAX`, with ``findingsTotal``).

**Source hooks** (CDG-1.4). A source may decide that a candidate is recorded but not imported
(``should_import(candidate) -> bool``; Azure API Management lists non-current API revisions this
way, as ``discovered`` items, unless the connector opts in) and may finish an imported item with
``after_import(db, candidate, project_id)`` (Azure API Management turns the API's products into tags
on the catalog item). A failing ``after_import`` never fails the import: it is counted on the run
summary as ``postImportFailed``.

**Change reports.** When a sync adds a revision to a catalog item that already had one, the
default importer writes a change report between the two revisions
(:mod:`app.catalog_revision_change_report`), so a gateway change is reviewable like a refresh.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from . import catalog_connector_store as store
from .catalog_connectors import (
    CODE_KIND_UNSUPPORTED,
    CODE_SYNC_RUNNING,
    ITEM_IGNORED,
    STATUS_ACTIVE,
    STATUS_FAILING,
    TRIGGER_MANUAL,
    TRIGGER_SCHEDULED,
    ConnectorError,
    connector_provenance_metadata,
    revision_label,
)
from .refresh_source import (
    ERROR_CLASS_UNEXPECTED,
    FetchedDocument,
    FreshnessKey,
    RefreshCandidate,
    RefreshSource,
    RefreshSourceError,
    decide_refresh,
)

_logger = logging.getLogger(__name__)

__all__ = [
    "AUDIT_SYNC_ACTION",
    "ConnectorImportError",
    "ConnectorRefreshSource",
    "ConnectorSyncResult",
    "import_document_as_catalog_item",
    "process_connector_refresh_sweep",
    "register_connector_source",
    "run_connector_sync",
    "source_factory_for",
    "syncable_kinds",
    "unregister_connector_source",
    "check_connector_connection",
    "connector_accepts_credentials",
    "validate_connector_scope",
]

#: Workflow-audit action for a connector run (the ``repository.`` prefix puts it in the
#: repository audit export, beside Git refresh cycles).
AUDIT_SYNC_ACTION = "repository.connector.sync"

#: Error class for a stored credential that cannot be opened (key rotated away, tampering).
ERROR_CLASS_CREDENTIALS_UNREADABLE = "credentials-unreadable"
#: Error class for a fetched document the import pipeline refused.
ERROR_CLASS_IMPORT_FAILED = "import-failed"

_MESSAGE_MAX_CHARS = 500

#: At most this many source findings are kept on a run's summary (``findingsTotal`` counts all).
FINDINGS_MAX = 50

#: ``(connector_row, credentials or None) -> RefreshSource``.
SourceFactory = Callable[[Mapping[str, Any], Optional[Dict[str, str]]], RefreshSource]

#: ``(scope, base_url) -> None``; raises :class:`ConnectorError` (``connector-invalid``).
ScopeValidator = Callable[[Mapping[str, Any], Optional[str]], None]

#: ``(connector_row) -> None``; a live dry run against the provider. Raises
#: :class:`ConnectorError` (``connector-check-failed``) naming what is missing.
ConnectionCheck = Callable[[Mapping[str, Any]], None]

#: At most this many unchanged items are listed, with their reason, on a run's summary.
UNCHANGED_ITEMS_MAX = 50

_SOURCES: Dict[str, SourceFactory] = {}
_SCOPE_VALIDATORS: Dict[str, ScopeValidator] = {}
_CONNECTION_CHECKS: Dict[str, ConnectionCheck] = {}
_NO_CREDENTIAL_KINDS: set = set()


def register_connector_source(
    kind: str,
    factory: SourceFactory,
    *,
    scope_validator: Optional[ScopeValidator] = None,
    connection_check: Optional[ConnectionCheck] = None,
    accepts_credentials: bool = True,
) -> None:
    """Make connectors of ``kind`` syncable with sources built by ``factory``.

    Args:
        kind: The connector kind.
        factory: Builds the source for one connector row and its unsealed credentials.
        scope_validator: Checks the kind's ``scope`` (and base URL) when a connector is created
            or updated; ``None`` accepts any scope that passes the generic checks.
        connection_check: A live dry run the routes run when a connector is created, or its
            scope changes (CDG-1.3: AWS assumes the role and calls ``GetAccount``); ``None``
            skips it.
        accepts_credentials: ``False`` for a kind that must never hold a stored secret (AWS
            assumes a role instead of storing keys); ``PUT …/credentials`` is then refused.
    """
    _SOURCES[kind] = factory
    for registry, value in ((_SCOPE_VALIDATORS, scope_validator), (_CONNECTION_CHECKS, connection_check)):
        if value is not None:
            registry[kind] = value
        else:
            registry.pop(kind, None)
    if accepts_credentials:
        _NO_CREDENTIAL_KINDS.discard(kind)
    else:
        _NO_CREDENTIAL_KINDS.add(kind)


def unregister_connector_source(kind: str) -> None:
    """Remove the source and every hook registered for ``kind`` (tests)."""
    _SOURCES.pop(kind, None)
    _SCOPE_VALIDATORS.pop(kind, None)
    _CONNECTION_CHECKS.pop(kind, None)
    _NO_CREDENTIAL_KINDS.discard(kind)


def check_connector_connection(connector: Mapping[str, Any]) -> bool:
    """Run the kind's live dry run, when its source registered one.

    Blocking (it calls the provider); routes call it via ``asyncio.to_thread``.

    Returns:
        ``True`` when a check ran and passed, ``False`` when the kind has none.

    Raises:
        ConnectorError: ``connector-check-failed``, naming the missing permission.
    """
    check = _CONNECTION_CHECKS.get(str(connector.get("kind")))
    if check is None:
        return False
    check(connector)
    return True


def connector_accepts_credentials(kind: str) -> bool:
    """``False`` for a kind that must never store a credential (it assumes a role instead)."""
    return kind not in _NO_CREDENTIAL_KINDS


def validate_connector_scope(kind: str, scope: Mapping[str, Any], base_url: Optional[str]) -> None:
    """Run the kind's scope validator, when its source registered one.

    Raises:
        ConnectorError: ``connector-invalid`` naming what is wrong with the scope.
    """
    validator = _SCOPE_VALIDATORS.get(kind)
    if validator is not None:
        validator(scope, base_url)


def source_factory_for(kind: str) -> Optional[SourceFactory]:
    """The registered factory for ``kind``, or ``None``."""
    return _SOURCES.get(kind)


def syncable_kinds() -> List[str]:
    """The kinds this deployment can sync, sorted."""
    return sorted(_SOURCES)


class ConnectorRefreshSource:
    """Base for connector sources: the freshness half of :class:`RefreshSource`.

    A connector source knows the remote side of each candidate; the engine knows what was last
    imported. Before gating, the engine hands the source its inventory
    (:meth:`attach_inventory`), and :meth:`freshness_key` pairs the remote revision and update
    time with the stored import anchor. Subclasses implement ``list_candidates``, ``fetch`` and
    ``describe``.

    Args:
        connector: The connector row (never carries credentials).
        credentials: The unsealed credential fields, or ``None`` when none are stored.
    """

    def __init__(self, connector: Mapping[str, Any], credentials: Optional[Dict[str, str]] = None) -> None:
        self.connector = connector
        self.credentials = credentials
        self._inventory: Mapping[str, Mapping[str, Any]] = {}

    def attach_inventory(self, rows_by_remote_id: Mapping[str, Mapping[str, Any]]) -> None:
        """Give the source the stored inventory rows, keyed by remote id."""
        self._inventory = rows_by_remote_id

    def freshness_key(self, candidate: RefreshCandidate) -> FreshnessKey:
        """Remote revision and update time against the anchor stored at the last import.

        A remote that reports neither has no freshness signal, so the content digest stands in
        for it: the engine fetches and compares digests (see :func:`run_connector_sync`).
        """
        row = self._inventory.get(candidate.remote_id) or {}
        if row.get("project_id") is None:
            return FreshnessKey(remote_checksum=candidate.revision)
        return FreshnessKey(
            remote_updated_at=candidate.updated_at,
            remote_checksum=candidate.revision,
            last_updated_at=row.get("imported_remote_updated_at"),
            last_checksum=row.get("imported_revision"),
        )

    def list_candidates(self) -> Sequence[RefreshCandidate]:  # pragma: no cover - abstract
        raise NotImplementedError

    def fetch(self, candidate: RefreshCandidate) -> FetchedDocument:  # pragma: no cover - abstract
        raise NotImplementedError

    def describe(self) -> Dict[str, Any]:
        """``{kind, connectorId}``."""
        return {"kind": self.connector.get("kind"), "connectorId": str(self.connector.get("id"))}


class ConnectorImportError(RuntimeError):
    """The import pipeline refused a fetched document."""


@dataclass
class ConnectorSyncResult:
    """The outcome of one run.

    Attributes:
        run_id: The ledger row.
        status: ``succeeded`` or ``failed``.
        connector_status: The connector's status after the run.
        pull_count: Documents fetched from the remote.
        summary: Counts (``candidates``, ``fetched``, ``imported``, ``unchanged``, ``missing``,
            ``ignored``, ``deferred``, ``failed``) plus the ``trigger``.
        error_class: The provider error class of a failure, if any.
        http_status: The provider HTTP status of a failure, if any.
        error_message: A redacted, truncated description of the failure, if any.
    """

    run_id: str
    status: str
    connector_status: str
    pull_count: int = 0
    summary: Dict[str, Any] = field(default_factory=dict)
    error_class: Optional[str] = None
    http_status: Optional[int] = None
    error_message: Optional[str] = None


#: ``(connector, candidate, document, item_row, actor_id) -> catalog item (project) id``.
Importer = Callable[[Mapping[str, Any], RefreshCandidate, FetchedDocument, Mapping[str, Any], Optional[str]], str]


def _redact(message: str, credentials: Optional[Mapping[str, str]]) -> str:
    """Remove every credential value from ``message`` and truncate it."""
    text = str(message or "")
    for value in (credentials or {}).values():
        if value and len(value) >= 4:
            text = text.replace(value, "[redacted]")
    return text[:_MESSAGE_MAX_CHARS]


def _unseal(db: Any, connector_id: str) -> tuple:
    """``(credentials, unreadable)`` for a connector: ``(None, False)`` when none are stored."""
    from .mcp_credential_crypto import unseal_credential_payload

    sealed = store.get_sealed_credentials(db, connector_id)
    if not sealed:
        return None, False
    payload = sealed.get("encrypted_payload")
    if isinstance(payload, memoryview):
        payload = payload.tobytes()
    opened = unseal_credential_payload(payload, sealed.get("key_version"))
    if opened is None:
        return None, True
    return {str(k): str(v) for k, v in opened.items()}, False


def _catalog_slug(connector: Mapping[str, Any], candidate: RefreshCandidate) -> str:
    """A slug unique to this connector's remote API, so two connectors never share an item."""
    base = re.sub(r"[^a-z0-9]+", "-", (candidate.name or candidate.remote_id).lower()).strip("-")
    return f"{(base or 'api')[:48]}-{str(connector['id'])[:8]}"


def import_document_as_catalog_item(
    connector: Mapping[str, Any],
    candidate: RefreshCandidate,
    document: FetchedDocument,
    item_row: Mapping[str, Any],
    actor_id: Optional[str],
) -> str:
    """Import a fetched document through the in-process pipeline as a catalog item.

    The first import of a remote API creates the catalog item; later imports add a revision to
    the same item (its id is on the inventory row) and write a change report against the
    revision imported before it (CDG-1.2). An item that was deleted, or converted into a Project
    since, is not written to; a new catalog item is created instead.

    Runs the async pipeline to completion on a private event loop, so it must be called from a
    thread with no running loop (the routes and the sweep call the engine via ``to_thread``).

    Returns:
        The catalog item (project) id.

    Raises:
        ConnectorImportError: When the import kind is unknown or the pipeline fails.
    """
    from .database import db
    from .import_source import get_import_source, resolve_import_source_key
    from .import_source_pipeline import run_adapter_import_job

    tenant_id = str(connector["tenant_id"])
    adapter = get_import_source(resolve_import_source_key(document.import_kind))
    if adapter is None:
        raise ConnectorImportError(f"No importer for kind {document.import_kind!r}.")

    existing_project_id = None
    parent_version_id: Optional[str] = None
    prior = item_row.get("project_id")
    if prior:
        project = db.get_project_by_id(str(prior), tenant_id)
        if project and not project.get("deleted_at") and project.get("publishable") is False:
            existing_project_id = str(prior)
            if item_row.get("imported_revision"):
                parent = db.get_version_by_version_id(
                    existing_project_id, revision_label(item_row.get("imported_revision")), tenant_id
                )
                parent_version_id = str(parent["id"]) if parent else None

    revision = document.revision or candidate.revision
    payload: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "user_id": actor_id or connector.get("created_by"),
        "filename": document.filename,
        "document_base64": base64.standard_b64encode(document.content).decode("ascii"),
        "rest_job_id": f"connector-{connector['id']}-{candidate.remote_id}"[:120],
        "metadata": {
            "source_kind": adapter.key,
            "project": {
                "name": candidate.name or candidate.remote_id,
                "slug": _catalog_slug(connector, candidate),
            },
            "version": {"version_id": revision_label(revision)},
            "options": {},
            "existing_project_id": existing_project_id,
        },
        "connector_source": connector_provenance_metadata(
            connector,
            remote_id=candidate.remote_id,
            remote_revision=revision,
            remote_name=candidate.name,
            source_uri=document.source_uri,
        ),
    }
    final = asyncio.run(run_adapter_import_job(adapter, payload))
    if final.state != "completed" or final.result is None or not final.result.project_id:
        reason = final.error.message if final.error is not None else f"import ended {final.state}"
        raise ConnectorImportError(reason)
    project_id = str(final.result.project_id)
    new_version_id = final.result.version_record_id
    if parent_version_id and new_version_id and str(new_version_id) != parent_version_id:
        from .catalog_revision_change_report import generate_catalog_revision_change_report

        generate_catalog_revision_change_report(
            tenant_id=tenant_id,
            project_id=project_id,
            revision_version_id=str(new_version_id),
            parent_version_id=parent_version_id,
            actor_id=actor_id or connector.get("created_by"),
        )
    return project_id


def _note_unchanged(summary: Dict[str, Any], source: Any, candidate: RefreshCandidate, reason_code: str) -> None:
    """Record why ``candidate`` was not re-imported on the run summary (``unchangedItems``).

    A source may phrase the reason in its own terms with ``explain_unchanged(candidate)`` (AWS:
    "deploymentId … is unchanged"); otherwise the newer-than gate's reason code stands.
    """
    items = summary.setdefault("unchangedItems", [])
    if len(items) >= UNCHANGED_ITEMS_MAX:
        return
    explain = getattr(source, "explain_unchanged", None)
    reason = explain(candidate) if callable(explain) else None
    items.append(
        {
            "remoteId": candidate.remote_id,
            "name": candidate.name,
            "revision": candidate.revision,
            "reasonCode": reason_code,
            "reason": reason or f"Not newer than the last import ({reason_code}).",
        }
    )


def _after_import(db: Any, source: Any, candidate: RefreshCandidate, project_id: str, summary: Dict[str, Any]) -> None:
    """Run the source's ``after_import`` hook, when it has one (see the module docstring).

    A hook failure is logged and counted (``summary.postImportFailed``), never raised: the import
    itself already succeeded.
    """
    hook = getattr(source, "after_import", None)
    if not callable(hook):
        return
    try:
        hook(db, candidate, project_id)
    except Exception as exc:  # noqa: BLE001 - a post-import step must not undo the import
        _logger.warning(
            "connector post-import step failed remote_id=%s project_id=%s error=%s",
            candidate.remote_id,
            project_id,
            f"{type(exc).__name__}: {exc}"[:_MESSAGE_MAX_CHARS],
        )
        summary["postImportFailed"] = int(summary.get("postImportFailed", 0)) + 1


def _audit(db: Any, connector: Mapping[str, Any], result: ConnectorSyncResult, actor_id: Optional[str]) -> None:
    """Write the run's ``repository.connector.sync`` workflow-audit row (no credentials)."""
    db.insert_workflow_audit(
        str(connector["tenant_id"]),
        None,
        None,
        AUDIT_SYNC_ACTION,
        "success" if result.status == "succeeded" else "failure",
        actor_id,
        {
            "connectorId": str(connector["id"]),
            "connectorKind": connector.get("kind"),
            "connectorName": connector.get("name"),
            "runId": result.run_id,
            "status": result.status,
            "pullCount": result.pull_count,
            "summary": result.summary,
            "errorClass": result.error_class,
            "httpStatus": result.http_status,
        },
    )


def run_connector_sync(
    db: Any,
    connector: Mapping[str, Any],
    *,
    trigger: str = TRIGGER_MANUAL,
    actor_id: Optional[str] = None,
    importer: Optional[Importer] = None,
    max_pulls: Optional[int] = None,
    only_remote_ids: Optional[Sequence[str]] = None,
) -> ConnectorSyncResult:
    """Run one sync of one connector (see the module docstring for the steps).

    Args:
        db: Database handle.
        connector: The live connector row.
        trigger: ``manual`` or ``scheduled``.
        actor_id: Who asked (``None`` for the sweep; imports are then attributed to the
            connector's creator).
        importer: Override for the catalog import step (tests); defaults to
            :func:`import_document_as_catalog_item`.
        max_pulls: Fetch at most this many documents; the rest are deferred to a later run
            (the scheduled sweep passes the tenant's remaining quota). ``None`` is unbounded.
        only_remote_ids: Import only these remote ids, now (CDG-1.6 "Import" on a shadow-report
            row). The whole inventory is still listed and recorded, but only these candidates are
            fetched, and they skip the ignore, ``should_import`` and newer-than gates: a person
            asked for them.

    Returns:
        The :class:`ConnectorSyncResult`.

    Raises:
        ConnectorError: ``connector-kind-unsupported`` when no source is registered for the kind,
            ``connector-sync-running`` when a run is already active. Neither opens a run.
    """
    from .repository_quota_window import METRIC_FILES_DEFERRED, METRIC_POLLS, record_quota_usage

    connector_id = str(connector["id"])
    tenant_id = str(connector["tenant_id"])
    factory = source_factory_for(str(connector.get("kind")))
    if factory is None:
        raise ConnectorError(
            CODE_KIND_UNSUPPORTED,
            f"Connectors of kind {connector.get('kind')!r} cannot sync on this deployment yet.",
        )
    run = store.start_run(db, tenant_id, connector_id, trigger=trigger, created_by=actor_id)
    if run is None:
        raise ConnectorError(CODE_SYNC_RUNNING, "A sync of this connector is already running.")
    run_id = str(run["id"])
    importer = importer or import_document_as_catalog_item

    summary: Dict[str, Any] = {
        "trigger": trigger,
        "candidates": 0,
        "fetched": 0,
        "imported": 0,
        "unchanged": 0,
        "missing": 0,
        "ignored": 0,
        "deferred": 0,
        "failed": 0,
    }
    pulls = 0
    # Candidates this run brought up to date (imported, or re-anchored on identical content).
    settled = 0
    failures: List[tuple] = []
    new_rows: List[Dict[str, Any]] = []
    only = set(only_remote_ids) if only_remote_ids is not None else None
    if only is not None:
        summary["requested"] = sorted(only)
    credentials: Optional[Dict[str, str]] = None
    result: ConnectorSyncResult

    try:
        credentials, unreadable = _unseal(db, connector_id)
        if unreadable:
            raise RefreshSourceError(
                "The stored credential cannot be opened; replace it with PUT …/credentials.",
                error_class=ERROR_CLASS_CREDENTIALS_UNREADABLE,
            )
        source = factory(connector, credentials)
        candidates = list(source.list_candidates())
        summary["candidates"] = len(candidates)
        findings = [dict(f) for f in (getattr(source, "findings", None) or [])]
        if findings:
            summary["findings"] = findings[:FINDINGS_MAX]
            summary["findingsTotal"] = len(findings)

        rows: Dict[str, Dict[str, Any]] = {}
        for candidate in candidates:
            rows[candidate.remote_id] = store.upsert_seen_item(db, connector_id, candidate)
            if rows[candidate.remote_id].get("inserted"):
                new_rows.append(rows[candidate.remote_id])
        summary["missing"] = store.mark_missing_items(db, connector_id, rows.keys())
        if hasattr(source, "attach_inventory"):
            source.attach_inventory(rows)

        for candidate in candidates:
            row = rows[candidate.remote_id]
            forced = only is not None
            if forced and candidate.remote_id not in only:
                continue
            if not forced and row.get("status") == ITEM_IGNORED:
                summary["ignored"] += 1
                continue
            should_import = getattr(source, "should_import", None)
            if not forced and callable(should_import) and not should_import(candidate):
                # Recorded (``discovered``) but not imported: the source says so (CDG-1.4).
                summary["discovered"] = int(summary.get("discovered", 0)) + 1
                continue
            decision = None if forced else decide_refresh(source, candidate)
            if decision is not None and not decision.should_refresh:
                summary["unchanged"] += 1
                _note_unchanged(summary, source, candidate, decision.reason.value)
                continue
            if max_pulls is not None and pulls >= max_pulls:
                summary["deferred"] += 1
                continue
            try:
                document = source.fetch(candidate)
            except RefreshSourceError as exc:
                failures.append((exc.error_class, exc.http_status, str(exc)))
                summary["failed"] += 1
                continue
            pulls += 1
            summary["fetched"] += 1
            digest = hashlib.sha256(document.content).hexdigest()
            revision = document.revision or candidate.revision
            if row.get("project_id") and row.get("imported_sha256") == digest:
                # Revision marker moved but the content did not: re-anchor, import nothing.
                store.mark_item_imported(
                    db,
                    str(row["id"]),
                    project_id=str(row["project_id"]),
                    revision=revision,
                    remote_updated_at=candidate.updated_at,
                    content_sha256=digest,
                )
                summary["unchanged"] += 1
                settled += 1
                _after_import(db, source, candidate, str(row["project_id"]), summary)
                continue
            try:
                project_id = importer(connector, candidate, document, row, actor_id)
            except Exception as exc:  # noqa: BLE001 - one bad document must not end the run
                failures.append((ERROR_CLASS_IMPORT_FAILED, None, str(exc)))
                summary["failed"] += 1
                continue
            store.mark_item_imported(
                db,
                str(row["id"]),
                project_id=project_id,
                revision=revision,
                remote_updated_at=candidate.updated_at,
                content_sha256=digest,
            )
            summary["imported"] += 1
            settled += 1
            _after_import(db, source, candidate, project_id, summary)

        if failures and settled == 0:
            error_class, http_status, message = failures[0]
            result = ConnectorSyncResult(
                run_id=run_id,
                status="failed",
                connector_status=STATUS_FAILING,
                error_class=error_class,
                http_status=http_status,
                error_message=_redact(
                    f"Fetched {summary['fetched']} of {summary['candidates']} candidate(s), "
                    f"imported none: {message}", credentials
                ),
            )
        else:
            first = failures[0] if failures else (None, None, None)
            result = ConnectorSyncResult(
                run_id=run_id,
                status="succeeded",
                connector_status=STATUS_ACTIVE,
                error_class=first[0],
                http_status=first[1],
                error_message=_redact(first[2], credentials) if first[2] else None,
            )
    except RefreshSourceError as exc:
        result = ConnectorSyncResult(
            run_id=run_id,
            status="failed",
            connector_status=STATUS_FAILING,
            error_class=exc.error_class,
            http_status=exc.http_status,
            error_message=_redact(str(exc), credentials),
        )
    except Exception as exc:  # noqa: BLE001 - the run must close whatever went wrong
        # No traceback: a source's exception text can carry a credential, so only the redacted
        # message is logged.
        _logger.error(
            "connector sync failed connector_id=%s run_id=%s error=%s",
            connector_id,
            run_id,
            _redact(f"{type(exc).__name__}: {exc}", credentials),
        )
        result = ConnectorSyncResult(
            run_id=run_id,
            status="failed",
            connector_status=STATUS_FAILING,
            error_class=ERROR_CLASS_UNEXPECTED,
            error_message=_redact(f"{type(exc).__name__}: {exc}", credentials),
        )

    result.pull_count = pulls
    result.summary = summary
    store.finish_run(
        db,
        run_id,
        status=result.status,
        pull_count=pulls,
        summary=summary,
        error_class=result.error_class,
        http_status=result.http_status,
        error_message=result.error_message,
    )
    store.record_connector_outcome(db, connector_id, status=result.connector_status)
    record_quota_usage(db, tenant_id, METRIC_POLLS, pulls)
    record_quota_usage(db, tenant_id, METRIC_FILES_DEFERRED, int(summary["deferred"]))
    _audit(db, connector, result, actor_id)
    if new_rows and only is None:
        # CDG-1.6: APIs seen for the first time that match nothing in the catalog (best-effort).
        from .shadow_api_notifications import notify_new_shadow_apis

        notify_new_shadow_apis(db, connector, new_rows)
    _logger.info(
        "connector sync finished connector_id=%s run_id=%s status=%s pulls=%s imported=%s "
        "missing=%s error_class=%s http_status=%s",
        connector_id,
        run_id,
        result.status,
        pulls,
        summary["imported"],
        summary["missing"],
        result.error_class,
        result.http_status,
    )
    return result


def process_connector_refresh_sweep(db: Any) -> int:
    """Run the scheduled sync of every due, syncable connector (one sweep tick).

    Called from the repository refresh sweep's tick, so ``APIOME_REFRESH_ENABLED`` stops both,
    and the tenant quota is shared: a connector's pulls come out of the same per-tenant budget as
    Git refresh jobs, and a tenant with no budget left has its connectors deferred (they stay
    due). A paused connector is never due; a failing one keeps retrying on its cadence.

    Returns:
        The number of documents pulled this tick.
    """
    from .config import settings
    from .repository_quota_window import METRIC_POLLS_DEFERRED, record_quota_usage
    from .repository_refresh_quota import load_tenant_refresh_quota_tracker

    if not settings.refresh_enabled or not _SOURCES:
        return 0
    quota = load_tenant_refresh_quota_tracker(db)
    pulled = 0
    for connector in store.list_due_connectors(
        db,
        default_interval_seconds=int(settings.refresh_default_interval_seconds),
        floor_seconds=int(settings.refresh_min_interval_seconds),
    ):
        if str(connector.get("kind")) not in _SOURCES:
            continue
        tenant_id = str(connector["tenant_id"])
        if quota is not None and quota.is_exhausted(tenant_id):
            record_quota_usage(db, tenant_id, METRIC_POLLS_DEFERRED, 1)
            continue
        try:
            result = run_connector_sync(
                db,
                connector,
                trigger=TRIGGER_SCHEDULED,
                max_pulls=quota.remaining(tenant_id) if quota is not None else None,
            )
        except ConnectorError:
            # Already running (a manual sync got there first) or the kind lost its source.
            continue
        except Exception:  # noqa: BLE001 - one connector must not stop the sweep
            _logger.exception("connector sweep failed connector_id=%s", connector.get("id"))
            continue
        pulled += result.pull_count
        if quota is not None:
            quota.consume(tenant_id, result.pull_count)
    return pulled


# Built-in sources register themselves on import (they subclass ConnectorRefreshSource above).
from . import aws_apigateway_connector_source, azure_apim_connector_source, kong_connector_source  # noqa: E402,F401
