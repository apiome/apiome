"""Reconcile one-shot file uploads — RAR-6.2 (#3539).

A catalog item imported from an uploaded file has no remote source the refresh sweep could poll
(compare MFI-31.1's live refresh for GraphQL / gRPC endpoints), so it can silently drift from the
file its owner keeps editing elsewhere. This module gives such an item two things:

1. **A staleness hint.** :func:`upload_staleness` reads the item's newest revision: when that
   revision came from an upload and is older than the tenant's ``catalog_upload_stale_after_days``
   (90 by default), the item "may be stale" and the catalog prompts for a re-upload.
2. **A spec-faithful re-upload.** Every upload records the import spec it ran with on the revision's
   ``format_metadata.importSpec`` (:func:`upload_spec_metadata`, captured by the import pipeline):
   the importer kind and the options the user chose, in the same versioned envelope the repository
   import spec uses (RAR-1.4). :func:`reupload_catalog_item` replays that spec over the new file, so
   the re-import uses the user's original options rather than importer defaults. Like a live refresh
   (:mod:`app.catalog_refresh_apply`), an identical file adds no version, and a changed one adds a
   date/time-labelled version with a change report against the version it supersedes.

An upload from before spec capture has no ``importSpec``: its re-upload resolves the importer from
the item's recorded source format, runs with default options, and says so (``spec_replayed`` false).
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

_logger = logging.getLogger(__name__)

__all__ = [
    "AUDIT_CHANGE_REPORT",
    "AUDIT_POLICY",
    "AUDIT_REUPLOADED",
    "CODE_NOT_AN_UPLOAD",
    "CODE_REUPLOAD_FAILED",
    "CODE_UNKNOWN_FORMAT",
    "MAX_STALE_AFTER_DAYS",
    "MIN_STALE_AFTER_DAYS",
    "STALE_AFTER_DAYS_DEFAULT",
    "UPLOAD_SPEC_SCHEMA_VERSION",
    "ReuploadError",
    "ReuploadOutcome",
    "UploadStaleness",
    "get_tenant_stale_after_days",
    "is_upload_revision",
    "newest_revision",
    "replay_spec",
    "reupload_catalog_item",
    "reupload_payload",
    "set_tenant_stale_after_days",
    "stored_upload_spec",
    "upload_spec_metadata",
    "upload_staleness",
]

#: Days after which an uploaded revision "may be stale" when the tenant has not chosen (V339 default).
STALE_AFTER_DAYS_DEFAULT = 90
#: Bounds of the tenant setting (the V339 CHECK constraint).
MIN_STALE_AFTER_DAYS = 1
MAX_STALE_AFTER_DAYS = 3650

#: Envelope version of ``format_metadata.importSpec``; bumped when the stored shape changes.
UPLOAD_SPEC_SCHEMA_VERSION = 1

#: The intake kinds that mean "a person handed us a file" — the uploads this module reconciles.
UPLOAD_INPUT_KINDS = ("file", "fileset")

#: Options that describe one run rather than the user's choice, so a replay never repeats them.
_RUN_ONLY_OPTIONS = ("dry_run", "skip_duplicate_versions", "input_kind", "git_source")

#: Source kinds that are never a one-shot upload (their importer comes from another stored spec).
_NOT_UPLOAD_SOURCE_KINDS = ("repository_auto_import",)

#: Workflow-audit actions this feature writes (metadata only, never the document).
AUDIT_REUPLOADED = "catalog.upload.reuploaded"
AUDIT_POLICY = "catalog.upload.policy_changed"
AUDIT_CHANGE_REPORT = "catalog.upload.change_report.generated"

#: The item's newest revision did not come from an upload (or the item has none).
CODE_NOT_AN_UPLOAD = "not-an-upload"
#: No importer could be resolved for an upload that predates spec capture.
CODE_UNKNOWN_FORMAT = "unknown-format"
#: The import pipeline refused the re-uploaded file.
CODE_REUPLOAD_FAILED = "reupload-failed"


class ReuploadError(Exception):
    """A re-upload that cannot run, with a stable ``code`` the route maps to an HTTP status."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class UploadStaleness:
    """Whether an item's current version came from an upload, and whether it may be stale.

    Attributes:
        eligible: True when the newest revision came from a file upload (so a re-upload applies).
        stale: True when it is eligible and older than ``stale_after_days``.
        stale_after_days: The tenant's threshold.
        uploaded_at: When the newest revision was created (ISO 8601), if known.
        age_days: Whole days since then, if known.
        version_id: The newest revision's id (``versions.id``).
        version_label: Its label.
        source_label: The uploaded file's name.
        spec: The stored import spec envelope, or ``None`` for an upload from before capture.
    """

    eligible: bool
    stale: bool
    stale_after_days: int
    uploaded_at: Optional[str] = None
    age_days: Optional[int] = None
    version_id: Optional[str] = None
    version_label: Optional[str] = None
    source_label: Optional[str] = None
    spec: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class ReuploadOutcome:
    """What a re-upload did.

    Attributes:
        changed: True when the file differed from the current version, so a version was added.
        version_id: The new version (``versions.id``) when one was added.
        version_label: Its label.
        spec_replayed: True when the stored import spec was replayed; False for a pre-capture
            upload, which ran with default options.
    """

    changed: bool
    spec_replayed: bool
    version_id: Optional[str] = None
    version_label: Optional[str] = None


# ---------------------------------------------------------------------------------------
# The stored spec
# ---------------------------------------------------------------------------------------


def upload_spec_metadata(source_kind: Any, options: Any) -> Optional[Dict[str, Any]]:
    """The ``format_metadata.importSpec`` envelope an upload records (captured by the pipeline).

    Args:
        source_kind: The request's importer discriminator (``SpecImportStartMetadata.source_kind``).
        options: The request's ``SpecImportOptions`` as a dict.

    Returns:
        ``{"specSchemaVersion", "sourceKind", "options"}`` with the run-only flags (dry run,
        duplicate skipping, intake kind, git provenance) left out, or ``None`` when there is no
        importer kind to replay or it is a repository auto-refresh.
    """
    kind = str(source_kind or "").strip()
    if not kind or kind in _NOT_UPLOAD_SOURCE_KINDS:
        return None
    raw = options if isinstance(options, Mapping) else {}
    replayable = {key: value for key, value in raw.items() if key not in _RUN_ONLY_OPTIONS}
    return {"specSchemaVersion": UPLOAD_SPEC_SCHEMA_VERSION, "sourceKind": kind, "options": replayable}


def stored_upload_spec(format_metadata: Any) -> Optional[Dict[str, Any]]:
    """Read a revision's stored import spec, upgraded to the current envelope.

    Args:
        format_metadata: The revision's ``format_metadata``.

    Returns:
        The envelope, or ``None`` when the revision recorded none (or a malformed one).
    """
    fmd = format_metadata if isinstance(format_metadata, Mapping) else {}
    spec = fmd.get("importSpec")
    if not isinstance(spec, Mapping):
        return None
    kind = str(spec.get("sourceKind") or "").strip()
    if not kind:
        return None
    options = spec.get("options")
    # Version 1 is the only shape so far; an older or newer number is read as version 1 until a
    # migration says otherwise, the way the repository spec reader upgrades on read (RAR-1.4).
    return {
        "specSchemaVersion": UPLOAD_SPEC_SCHEMA_VERSION,
        "sourceKind": kind,
        "options": dict(options) if isinstance(options, Mapping) else {},
    }


def is_upload_revision(format_metadata: Any) -> bool:
    """True when a revision's provenance says it came from a one-shot file upload.

    A URL fetch, paste, live refresh (``discovery``), connector sync, migration or git-sourced
    fileset is not: each has a source of its own to go back to.

    Args:
        format_metadata: The revision's ``format_metadata``.

    Returns:
        Whether the revision is an upload.
    """
    fmd = format_metadata if isinstance(format_metadata, Mapping) else {}
    if fmd.get("intakeKind") == "git":
        return False
    return str(fmd.get("inputKind") or "") in UPLOAD_INPUT_KINDS


# ---------------------------------------------------------------------------------------
# The tenant setting
# ---------------------------------------------------------------------------------------


def get_tenant_stale_after_days(db: Any, tenant_id: str) -> int:
    """The tenant's staleness threshold in days (the default when the tenant row is missing)."""
    rows = db.execute_query(
        "SELECT catalog_upload_stale_after_days FROM apiome.tenants WHERE id = %s::uuid",
        (tenant_id,),
    )
    value = rows[0].get("catalog_upload_stale_after_days") if rows else None
    return int(value) if value else STALE_AFTER_DAYS_DEFAULT


def set_tenant_stale_after_days(db: Any, tenant_id: str, days: int) -> int:
    """Store the tenant's staleness threshold.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        days: The threshold, between :data:`MIN_STALE_AFTER_DAYS` and :data:`MAX_STALE_AFTER_DAYS`.

    Returns:
        The stored value.

    Raises:
        ValueError: When ``days`` is out of range.
    """
    if not MIN_STALE_AFTER_DAYS <= int(days) <= MAX_STALE_AFTER_DAYS:
        raise ValueError(f"staleAfterDays must be between {MIN_STALE_AFTER_DAYS} and {MAX_STALE_AFTER_DAYS}.")
    db._execute_write(
        "UPDATE apiome.tenants SET catalog_upload_stale_after_days = %s WHERE id = %s::uuid",
        (int(days), tenant_id),
    )
    return int(days)


# ---------------------------------------------------------------------------------------
# The staleness hint
# ---------------------------------------------------------------------------------------


def _as_datetime(value: Any) -> Optional[datetime]:
    """A timezone-aware datetime from a DB value or ISO string, or ``None``."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def upload_staleness(
    revision: Optional[Mapping[str, Any]],
    *,
    stale_after_days: int,
    now: Optional[datetime] = None,
) -> UploadStaleness:
    """Whether the item whose newest revision is ``revision`` may be stale.

    Args:
        revision: The newest live revision (``id``, ``version_id``, ``created_at``,
            ``format_metadata``), or ``None`` for an item with none.
        stale_after_days: The tenant's threshold.
        now: The time to measure age at (tests pin it); defaults to now.

    Returns:
        :class:`UploadStaleness`. Not eligible (and never stale) unless the revision is an upload.
    """
    if revision is None or not is_upload_revision(revision.get("format_metadata")):
        return UploadStaleness(eligible=False, stale=False, stale_after_days=stale_after_days)
    fmd = revision.get("format_metadata") or {}
    created = _as_datetime(revision.get("created_at"))
    age_days = None
    if created is not None:
        age_days = max(0, ((now or datetime.now(timezone.utc)) - created).days)
    return UploadStaleness(
        eligible=True,
        stale=age_days is not None and age_days >= stale_after_days,
        stale_after_days=stale_after_days,
        uploaded_at=created.isoformat() if created else None,
        age_days=age_days,
        version_id=str(revision.get("id")) if revision.get("id") else None,
        version_label=str(revision.get("version_id")) if revision.get("version_id") else None,
        source_label=fmd.get("sourceLabel") if isinstance(fmd.get("sourceLabel"), str) else None,
        spec=stored_upload_spec(fmd),
    )


def newest_revision(db: Any, project_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    """The item's newest live revision with what the hint and a re-upload need, or ``None``."""
    rows = db.execute_query(
        """
        SELECT v.id, v.version_id, v.created_at, v.source_format, v.protocol, v.format_metadata, p.metadata
        FROM apiome.versions v
        JOIN apiome.projects p ON p.id = v.project_id
        WHERE v.project_id = %s::uuid AND p.tenant_id = %s::uuid AND v.deleted_at IS NULL
        ORDER BY v.created_at DESC, v.id DESC
        LIMIT 1
        """,
        (project_id, tenant_id),
    )
    return dict(rows[0]) if rows else None


# ---------------------------------------------------------------------------------------
# The re-upload
# ---------------------------------------------------------------------------------------


def replay_spec(revision: Mapping[str, Any], raw: bytes) -> tuple:
    """The importer kind and options a re-upload runs with, and whether they came from the spec.

    Args:
        revision: The item's newest revision (``format_metadata``, ``source_format``).
        raw: The re-uploaded file, used to resolve the importer of a pre-capture upload.

    Returns:
        ``(source_kind, options, replayed)``.

    Raises:
        ReuploadError: ``unknown-format`` when a pre-capture upload's importer cannot be resolved.
    """
    spec = stored_upload_spec(revision.get("format_metadata"))
    if spec is not None:
        return spec["sourceKind"], dict(spec["options"]), True
    from .catalog_conversion import resolve_conversion_adapter
    from .conversion_job import ConversionError

    try:
        adapter = resolve_conversion_adapter(revision.get("source_format"), raw.decode("utf-8", errors="replace"))
    except ConversionError as exc:
        raise ReuploadError(CODE_UNKNOWN_FORMAT, str(exc)) from exc
    return adapter.key, {}, False


def reupload_payload(
    item: Mapping[str, Any],
    revision: Mapping[str, Any],
    *,
    tenant_id: str,
    actor_id: Optional[str],
    raw: bytes,
    filename: str,
    source_kind: str,
    options: Mapping[str, Any],
    version_label: str,
) -> Dict[str, Any]:
    """The import-pipeline payload that adds the re-uploaded file to the item.

    The options are the stored spec's, plus the original intake kind (``file`` or ``fileset``) so
    the new revision is itself an upload — and records the same spec for the next re-upload.
    """
    fmd = revision.get("format_metadata") or {}
    input_kind = str(fmd.get("inputKind") or "file")
    project_id = str(item["id"])
    return {
        "tenant_id": tenant_id,
        "user_id": actor_id,
        "filename": filename,
        "document_base64": base64.standard_b64encode(raw).decode("ascii"),
        "rest_job_id": f"reupload-{project_id}",
        "metadata": {
            "source_kind": source_kind,
            "project": {"name": item.get("name"), "slug": item.get("slug")},
            "version": {"version_id": version_label},
            "options": {**options, "input_kind": input_kind},
            "existing_project_id": project_id,
        },
    }


def reupload_catalog_item(
    db: Any,
    *,
    tenant_id: str,
    project_id: str,
    raw: bytes,
    filename: str,
    actor_id: Optional[str],
    now: Optional[datetime] = None,
) -> ReuploadOutcome:
    """Re-import a new copy of an uploaded catalog item's file with its stored import spec.

    Blocking (the pipeline runs on a private event loop) — call via ``asyncio.to_thread``.

    1. The item must be a live catalog item whose newest revision is an upload.
    2. The file is parsed with the stored spec's importer and compared with the current version
       (:func:`app.versioning.decide_version`): equal adds nothing.
    3. Otherwise it goes through the import pipeline onto the item with the stored options, under
       a date/time label, and gets a change report against the version it supersedes.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        project_id: The catalog item.
        raw: The new file's bytes.
        filename: Its name (the new revision's source label).
        actor_id: Who re-uploaded it.
        now: The time the version label is minted from (tests pin it).

    Returns:
        :class:`ReuploadOutcome`.

    Raises:
        RefreshSettingsError: ``item-unavailable`` when the item is gone or is a Project.
        ReuploadError: ``not-an-upload``, ``unknown-format`` or ``reupload-failed``.
    """
    from .catalog_refresh_apply import _catalog_item, _revisions, previous_version
    from .import_source import ImportSourceError, get_import_source
    from .import_source_pipeline import run_adapter_import_job
    from .versioning import decide_version, mint_version_tag

    item = _catalog_item(db, project_id, tenant_id)
    revisions = _revisions(db, project_id, tenant_id)
    if not revisions or not is_upload_revision(revisions[0].get("format_metadata")):
        raise ReuploadError(CODE_NOT_AN_UPLOAD, "Only an item imported from an uploaded file can be re-uploaded.")
    current = revisions[0]
    source_kind, options, replayed = replay_spec(current, raw)
    adapter = get_import_source(source_kind)
    if adapter is None:
        raise ReuploadError(CODE_UNKNOWN_FORMAT, f"No importer is registered for {source_kind!r}.")

    # Compare first, with the replayed importer, so an unchanged file writes nothing. An archive
    # (or any file the importer cannot read as text) skips the comparison: the pipeline judges it.
    try:
        new_model = adapter.normalize(adapter.parse(raw.decode("utf-8"), source_label=filename))
    except (ImportSourceError, UnicodeDecodeError):
        new_model = None
    when = now or datetime.now(timezone.utc)
    existing_tags = [str(r.get("version_id")) for r in revisions if r.get("version_id")]
    if new_model is not None:
        decision = decide_version(
            new_model,
            previous=previous_version(project_id, current),
            when=when,
            existing_tags=existing_tags,
        )
        if not decision.created:
            return ReuploadOutcome(changed=False, spec_replayed=replayed)
        label = str(decision.version_tag)
    else:
        label = mint_version_tag(when, existing_tags)

    payload = reupload_payload(
        item,
        current,
        tenant_id=tenant_id,
        actor_id=actor_id,
        raw=raw,
        filename=filename,
        source_kind=source_kind,
        options=options,
        version_label=label,
    )
    final = asyncio.run(run_adapter_import_job(adapter, payload))
    if final.state != "completed" or final.result is None or not final.result.version_record_id:
        reason = final.error.message if final.error is not None else f"the import ended {final.state}"
        raise ReuploadError(CODE_REUPLOAD_FAILED, f"The file could not be imported: {reason}")
    version_id = str(final.result.version_record_id)

    from .catalog_revision_change_report import generate_catalog_revision_change_report

    generate_catalog_revision_change_report(
        tenant_id=tenant_id,
        project_id=project_id,
        revision_version_id=version_id,
        parent_version_id=str(current["id"]),
        actor_id=actor_id,
        action=AUDIT_CHANGE_REPORT,
    )
    _logger.info("catalog re-upload created version project_id=%s version=%s", project_id, label)
    return ReuploadOutcome(
        changed=True, spec_replayed=replayed, version_id=version_id, version_label=final.result.version_id
    )
