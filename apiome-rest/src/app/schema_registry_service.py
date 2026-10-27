"""Schema subject model — registration and attach (CDG-4.2, #5974).

Two ways a subject gains a version, both ending in :func:`app.schema_registry_store.record_version`:

* **Register** (:func:`register_schema`) — the schema text is parsed and fingerprinted through its
  import source (:func:`app.schema_registry.fingerprint_schema`). If the subject already holds that
  fingerprint, its version is returned unchanged. If the tenant already holds it under another
  subject, the new version shares that schema id *and* that revision — nothing is imported. Only a
  schema the tenant has never seen is imported, through the same in-process pipeline every catalog
  upload uses (:func:`app.import_source_pipeline.run_adapter_import_job`), as a new revision of the
  subject's catalog item (created on the subject's first registration). So a subject version **is** a
  catalog item revision, and registering the same schema twice makes one revision.
* **Compatibility** (CDG-4.3) — a new version under a level other than ``NONE`` needs a verdict.
  Avro has one (MFI-12.4, :func:`compatibility_verdict` over :mod:`app.avro_compatibility`): an
  incompatible schema is refused with ``schema-incompatible`` (409), as a Confluent registry does,
  and :func:`check_compatibility` answers with Confluent's verdict and messages. For a schema type
  without rules, :func:`register_schema` refuses it with ``compatibility-rules-unavailable`` rather
  than accepting it unchecked, and :func:`check_compatibility` answers the same way. A subject's
  first version needs no verdict.
* **Attach** (:func:`attach_catalog_item`) — an existing Avro, JSON Schema or Protobuf catalog item
  backs an empty subject: its latest revision becomes version 1, and its earlier revisions are left
  exactly as they are.

Blocking: the import runs the async pipeline on a private event loop and every call is a
synchronous DB round trip, so routes call these functions through ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import base64
import uuid
from typing import Any, Dict, List, Optional

from . import schema_registry_store as store
from .schema_registry import (
    LEVEL_NONE,
    MODE_READONLY,
    SCHEMA_TYPES,
    STRATEGIES,
    SchemaRegistryError,
    effective_mode,
    fingerprint_schema,
    normalize_choice,
    require_verdict_possible,
    schema_type_for_format,
    validate_subject_name,
)


def _require_writable(db: Any, tenant_id: str, subject: Optional[Dict[str, Any]]) -> None:
    """Refuse a write when the tenant default mode or the subject's mode is ``READONLY``.

    Raises:
        SchemaRegistryError: ``subject-read-only`` (409).
    """
    tenant_mode = store.get_config(db, tenant_id).get("mode")
    if effective_mode(subject.get("mode") if subject else None, tenant_mode) == MODE_READONLY:
        raise SchemaRegistryError(
            "subject-read-only", "The registry or this subject is in READONLY mode.", status_code=409
        )


def effective_level(db: Any, tenant_id: str, subject: Optional[Dict[str, Any]]) -> str:
    """Return a subject's compatibility level, else the tenant default."""
    if subject and subject.get("compatibility_level"):
        return str(subject["compatibility_level"])
    return str(store.get_config(db, tenant_id).get("compatibility_level") or LEVEL_NONE)


def _live_catalog_item_id(db: Any, tenant_id: str, project_id: Any) -> Optional[str]:
    """Return ``project_id`` when it is still a live catalog item of the tenant, else ``None``."""
    if not project_id:
        return None
    item = db.get_catalog_item_by_id(str(project_id), tenant_id)
    return str(project_id) if item else None


def _import_revision(
    db: Any,
    *,
    tenant_id: str,
    actor_id: Optional[str],
    subject: str,
    schema: str,
    adapter_key: str,
    filename: str,
    existing_project_id: Optional[str],
    version_number: int,
    connector_source: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Import ``schema`` as a new catalog item revision through the in-process import pipeline.

    A subject's first import creates a catalog item under a freshly allocated slug (never reusing
    an unrelated item that happens to share the name); later imports add a revision to
    ``existing_project_id``. The revision label is the subject version number, made unique within
    the item (an attached item may already use it).

    ``connector_source`` is the connector provenance descriptor
    (:func:`app.catalog_connectors.connector_provenance_metadata`) of a version mirrored from an
    upstream registry (MFI-12.3); the revision's Provenance tab then names the connector.

    Returns:
        ``{"project_id", "version_record_id"}``.

    Raises:
        SchemaRegistryError: ``schema-import-failed`` (422) when the pipeline does not complete.
    """
    from .import_source import get_import_source
    from .import_source_pipeline import _normalize_import_project_slug, run_adapter_import_job

    adapter = get_import_source(adapter_key)
    if adapter is None:  # fingerprint_schema already resolved it; kept for a clean error
        raise SchemaRegistryError("schema-type-unavailable", f"No importer for {adapter_key!r}.")

    project_meta: Dict[str, Any] = {}
    if existing_project_id:
        label = db.allocate_version_id(existing_project_id, str(version_number))
    else:
        label = str(version_number)
        slug = db.allocate_project_slug(tenant_id, _normalize_import_project_slug("", subject))
        project_meta = {"name": subject, "slug": slug}

    payload: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "user_id": actor_id,
        "filename": filename,
        "document_base64": base64.standard_b64encode(schema.encode("utf-8")).decode("ascii"),
        "rest_job_id": f"schema-registry-{uuid.uuid4()}",
        "metadata": {
            "source_kind": adapter.key,
            "project": project_meta,
            "version": {"version_id": label, "description": f"Schema subject {subject} version {version_number}"},
            "options": {},
            "existing_project_id": existing_project_id,
        },
    }
    if connector_source:
        payload["connector_source"] = connector_source
    final = asyncio.run(run_adapter_import_job(adapter, payload))
    result = final.result
    if final.state != "completed" or result is None or not result.version_record_id:
        reason = final.error.message if final.error is not None else f"import ended {final.state}"
        raise SchemaRegistryError("schema-import-failed", f"The schema could not be imported: {reason}")
    return {"project_id": str(result.project_id), "version_record_id": str(result.version_record_id)}


def register_schema(
    db: Any,
    *,
    tenant_id: str,
    actor_id: Optional[str],
    subject: str,
    schema: str,
    schema_type: str,
    references: Optional[List[Any]] = None,
    strategy: Optional[str] = None,
) -> Dict[str, Any]:
    """Register ``schema`` under ``subject``; identical content returns the existing id.

    Args:
        db: The database handle.
        tenant_id: The tenant.
        actor_id: The registering user (recorded on new rows), or ``None``.
        subject: The subject name; created when it does not exist.
        schema: The schema text.
        schema_type: ``AVRO`` / ``JSON`` / ``PROTOBUF``.
        references: Schema references, stored verbatim (resolution is CDG-4.3).
        strategy: Naming strategy recorded on a subject this call creates.

    Returns:
        The version row from :func:`app.schema_registry_store.record_version` (``schema_id``,
        ``version``, ``project_id``, ``version_record_id``, ``created`` …).

    Raises:
        SchemaRegistryError: For an invalid name, type, strategy or schema, a READONLY subject, a
            failed import, or ``schema-incompatible`` (409) when the schema fails the subject's
            compatibility level.
    """
    subject = validate_subject_name(subject)
    normalize_choice(schema_type, SCHEMA_TYPES, field="schemaType")
    normalize_choice(strategy, STRATEGIES, field="strategy")
    if references is not None and not isinstance(references, list):
        raise SchemaRegistryError("references-invalid", "references must be a JSON array.")

    existing_subject = store.get_subject(db, tenant_id, subject)
    _require_writable(db, tenant_id, existing_subject)
    parsed = fingerprint_schema(schema_type, schema, subject)

    if existing_subject is not None:
        held = store.find_version_by_fingerprint(
            db, str(existing_subject["id"]), parsed.schema_type, parsed.fingerprint
        )
        if held is not None:
            return {**held, "created": False, "subject": subject, "subject_id": existing_subject["id"]}

    live_versions = store.list_versions(db, str(existing_subject["id"])) if existing_subject else []
    level = effective_level(db, tenant_id, existing_subject)
    require_verdict_possible(level, parsed.schema_type, bool(live_versions))
    if level != LEVEL_NONE and live_versions:
        verdict = compatibility_verdict(db, level, parsed.schema_type, schema, live_versions)
        if not verdict["is_compatible"]:
            raise SchemaRegistryError(
                "schema-incompatible",
                f'Schema being registered is incompatible with an earlier schema for subject "{subject}", '
                f"details: [{', '.join(verdict['messages'])}]",
                status_code=409,
            )

    known = store.get_schema_by_fingerprint(db, tenant_id, parsed.schema_type, parsed.fingerprint)
    subject_project_id: Optional[str] = None
    if known is not None:
        revision = {
            "project_id": str(known["project_id"]),
            "version_record_id": str(known["version_record_id"]),
        }
    else:
        backing = _live_catalog_item_id(
            db, tenant_id, existing_subject.get("project_id") if existing_subject else None
        )
        next_number = store.next_version_number(db, str(existing_subject["id"])) if existing_subject else 1
        revision = _import_revision(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            subject=subject,
            schema=schema,
            adapter_key=parsed.adapter_key,
            filename=parsed.filename,
            existing_project_id=backing,
            version_number=next_number,
        )
        subject_project_id = revision["project_id"]

    return store.record_version(
        db,
        tenant_id=tenant_id,
        subject=subject,
        schema_type=parsed.schema_type,
        fingerprint=parsed.fingerprint,
        references=list(references or []),
        project_id=revision["project_id"],
        version_record_id=revision["version_record_id"],
        actor_id=actor_id,
        strategy=strategy,
        subject_project_id=subject_project_id,
    )


def lookup_schema(
    db: Any, *, tenant_id: str, subject: str, schema: str, schema_type: str
) -> Optional[Dict[str, Any]]:
    """Find the live version of ``subject`` that holds ``schema`` (Confluent ``POST /subjects/{s}``).

    Args:
        db: The database handle.
        tenant_id: The tenant.
        subject: The subject name.
        schema: The schema text to look up.
        schema_type: ``AVRO`` / ``JSON`` / ``PROTOBUF``.

    Returns:
        The version row, or ``None`` when the subject does not hold this schema.

    Raises:
        SchemaRegistryError: ``subject-not-found`` (404) for an unknown subject; ``schema-invalid``
            when the schema cannot be read.
    """
    subject = validate_subject_name(subject)
    normalize_choice(schema_type, SCHEMA_TYPES, field="schemaType")
    row = store.get_subject(db, tenant_id, subject)
    if row is None:
        raise SchemaRegistryError("subject-not-found", f"Subject {subject!r} not found.", status_code=404)
    parsed = fingerprint_schema(schema_type, schema, subject)
    return store.find_version_by_fingerprint(db, str(row["id"]), parsed.schema_type, parsed.fingerprint)


def check_compatibility(
    db: Any,
    *,
    tenant_id: str,
    subject: str,
    schema: str,
    schema_type: str,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """Test ``schema`` against a subject's versions (Confluent ``POST /compatibility/…``).

    Under ``NONE``, or against a subject with no versions, the answer is compatible. Any other level
    needs a verdict: Avro's is computed (:func:`compatibility_verdict`); for a type without rules
    the call is refused rather than answered. Naming a ``version`` checks that version alone.

    Args:
        db: The database handle.
        tenant_id: The tenant.
        subject: The subject name.
        schema: The candidate schema text (validated by its import source).
        schema_type: ``AVRO`` / ``JSON`` / ``PROTOBUF``.
        version: The version to test against, or ``None`` for the versions the level selects.

    Returns:
        ``{"is_compatible": bool, "messages": [str]}``.

    Raises:
        SchemaRegistryError: ``subject-not-found`` / ``version-not-found`` (404), ``schema-invalid``
            (422), ``compatibility-rules-unavailable`` (422), ``version-has-no-source`` (422).
    """
    subject = validate_subject_name(subject)
    normalize_choice(schema_type, SCHEMA_TYPES, field="schemaType")
    row = store.get_subject(db, tenant_id, subject)
    if row is None:
        raise SchemaRegistryError("subject-not-found", f"Subject {subject!r} not found.", status_code=404)
    versions = store.list_versions(db, str(row["id"]))
    if version is not None and not any(int(v["version"]) == int(version) for v in versions):
        raise SchemaRegistryError("version-not-found", f"Version {version} not found.", status_code=404)
    fingerprint_schema(schema_type, schema, subject)
    level = effective_level(db, tenant_id, row)
    require_verdict_possible(level, schema_type, bool(versions))
    if level == LEVEL_NONE or not versions:
        return {"is_compatible": True, "messages": []}
    if version is not None:
        selected = [v for v in versions if int(v["version"]) <= int(version)]
        return compatibility_verdict(db, level, schema_type, schema, selected, only_latest=True)
    return compatibility_verdict(db, level, schema_type, schema, versions)


def _avro_schema(text: str, *, what: str) -> Any:
    """Parse Avro schema text (``.avsc`` JSON, or IDL) for a compatibility check.

    Raises:
        SchemaRegistryError: ``schema-invalid`` (422) when the text is not a readable Avro schema.
    """
    from .avro_compatibility import AvroCompatibilityError, parse_schema_text, schema_of_document
    from .avro_import_source import AvroImportSource
    from .import_source import ImportSourceError

    try:
        return parse_schema_text(text)
    except AvroCompatibilityError as json_error:
        try:
            return schema_of_document(AvroImportSource().parse(text, source_label="schema.avdl"))
        except (AvroCompatibilityError, ImportSourceError):
            raise SchemaRegistryError("schema-invalid", f"Invalid AVRO schema ({what}): {json_error}") from json_error


def compatibility_verdict(
    db: Any,
    level: str,
    schema_type: str,
    schema: str,
    versions: List[Dict[str, Any]],
    *,
    only_latest: bool = False,
) -> Dict[str, Any]:
    """Judge ``schema`` against a subject's versions under ``level`` (MFI-12.4).

    The versions the level selects are checked newest first and the check stops at the first that
    fails, as a Confluent registry's does; the messages are Confluent's verbose ones
    (:func:`app.avro_compatibility.confluent_messages`).

    Args:
        db: The database handle (each version's schema text is read from its revision).
        level: The effective compatibility level (not ``NONE``).
        schema_type: The schema type; only ``AVRO`` has rules.
        schema: The candidate schema text.
        versions: The subject's live versions, oldest first.
        only_latest: Check only the last of ``versions`` (a request that names a version).

    Returns:
        ``{"is_compatible": bool, "messages": [str]}``.

    Raises:
        SchemaRegistryError: ``compatibility-rules-unavailable`` (422) for a type without rules;
            ``schema-invalid`` (422) for an unreadable candidate; ``version-has-no-source`` (422)
            when a version's schema text was not captured.
    """
    from .avro_compatibility import check_compatibility as check_avro
    from .avro_compatibility import confluent_messages
    from .schema_registry import SCHEMA_TYPE_AVRO

    if schema_type != SCHEMA_TYPE_AVRO:
        raise SchemaRegistryError(
            "compatibility-rules-unavailable", f"No {schema_type} compatibility engine is wired in."
        )
    candidate = _avro_schema(schema, what="candidate")
    texts: List[str] = []
    for row in versions:
        text = schema_text(db, row.get("version_record_id"))
        if text is None:
            raise SchemaRegistryError(
                "version-has-no-source",
                f"Version {row.get('version')} has no captured schema to check compatibility against.",
            )
        texts.append(text)
    previous = [_avro_schema(text, what=f"version {row.get('version')}") for text, row in zip(texts, versions)]
    verdict = check_avro(level, candidate, previous, only_latest=only_latest)
    failed = verdict.failed_version
    messages = confluent_messages(
        verdict,
        old_version=None if failed is None else int(versions[failed]["version"]),
        old_schema=None if failed is None else texts[failed],
    )
    return {"is_compatible": verdict.is_compatible, "messages": messages}


def revision_fingerprint(revision: Dict[str, Any], schema_type: str, subject: str) -> str:
    """Return a revision's fingerprint: the one its import recorded, else recomputed from its source.

    The import pipeline stores the adapter's fingerprint on ``format_metadata.fingerprint`` (MFI-25.8),
    which is the same canonical-model fingerprint :func:`app.schema_registry.fingerprint_schema`
    computes, so an attached item and a registered schema compare like with like.

    Raises:
        SchemaRegistryError: ``item-has-no-source`` (422) when neither is available.
    """
    from .catalog_detail import resolve_source_payload

    fmd = revision.get("format_metadata") if isinstance(revision.get("format_metadata"), dict) else {}
    stored = fmd.get("fingerprint")
    if isinstance(stored, str) and stored.startswith("sha256:"):
        return stored
    payload = resolve_source_payload(revision)
    if not payload or payload.get("mode") != "content":
        raise SchemaRegistryError(
            "item-has-no-source",
            "This catalog item's latest revision has no captured schema to fingerprint.",
        )
    return fingerprint_schema(schema_type, payload["content"], subject).fingerprint


def attach_catalog_item(
    db: Any,
    *,
    tenant_id: str,
    actor_id: Optional[str],
    subject: str,
    project_id: str,
    strategy: Optional[str] = None,
) -> Dict[str, Any]:
    """Attach an existing catalog item to an empty subject: its latest revision becomes version 1.

    The item's history is untouched — no revision is created, moved or deleted — and later
    registrations under the subject add revisions to this item.

    Args:
        db: The database handle.
        tenant_id: The tenant.
        actor_id: The acting user, or ``None``.
        subject: The subject name; created when it does not exist, and must have no versions.
        project_id: The catalog item (a non-publishable project of the tenant).
        strategy: Naming strategy recorded on a subject this call creates.

    Returns:
        The version row (version 1).

    Raises:
        SchemaRegistryError: ``item-not-found`` (404); ``item-not-a-schema`` (422) when the latest
            revision is not Avro, JSON Schema or Protobuf; ``subject-has-versions`` /
            ``subject-attached-elsewhere`` / ``subject-read-only`` (409).
    """
    subject = validate_subject_name(subject)
    normalize_choice(strategy, STRATEGIES, field="strategy")
    existing_subject = store.get_subject(db, tenant_id, subject)
    _require_writable(db, tenant_id, existing_subject)

    revision = store.get_latest_live_revision(db, tenant_id, project_id)
    if revision is None:
        raise SchemaRegistryError("item-not-found", "Catalog item not found.", status_code=404)
    schema_type = schema_type_for_format(revision.get("source_format"))
    if schema_type is None:
        raise SchemaRegistryError(
            "item-not-a-schema",
            "Only Avro, JSON Schema and Protobuf catalog items can be attached to a subject "
            f"(this item is {revision.get('source_format') or 'of unknown format'}).",
        )
    fingerprint = revision_fingerprint(revision, schema_type, subject)
    return store.record_version(
        db,
        tenant_id=tenant_id,
        subject=subject,
        schema_type=schema_type,
        fingerprint=fingerprint,
        references=[],
        project_id=str(project_id),
        version_record_id=str(revision["id"]),
        actor_id=actor_id,
        strategy=strategy,
        subject_project_id=str(project_id),
        require_empty_subject=True,
    )


def schema_text(db: Any, version_record_id: Any) -> Optional[str]:
    """Return the schema text stored on a revision, or ``None`` when none was captured."""
    from .catalog_detail import resolve_source_payload

    revision = store.get_revision_source(db, str(version_record_id))
    payload = resolve_source_payload(revision) if revision else None
    if payload and payload.get("mode") == "content":
        return payload["content"]
    return None
