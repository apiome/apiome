"""Schema subject model — persistence (CDG-4.2, #5974).

Reads and writes the V294 tables (``schema_registry_config``, ``schema_registry_schemas``,
``schema_subjects``, ``schema_subject_versions``). Every function takes the ``db`` handle and is
tenant-scoped by its ``tenant_id`` argument. :func:`record_version` is the one multi-statement write:
it creates the subject when needed, finds or allocates the schema id and inserts the next version,
all in one transaction (``Database._guarded_tx``), so ids and version numbers never skip under
concurrent registrations.

Rules the queries enforce (see the V294 header for the why):

* a **schema id names content** — one row per (tenant, schema type, fingerprint kind, fingerprint),
  shared by every subject that holds the schema;
* a **soft-deleted subject** and its versions are left out of every list, but its schema rows stay,
  so :func:`get_schema_by_id` still resolves the id;
* ids come from the tenant's counter (``schema_registry_config.next_schema_id``).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from .schema_registry import FINGERPRINT_KIND, MODE_READWRITE, SchemaRegistryError

#: Columns of a subject, in a stable order shared by every read.
SUBJECT_COLUMNS = (
    "s.id, s.tenant_id, s.name, s.strategy, s.compatibility_level, s.mode, s.project_id, "
    "s.created_by, s.created_at, s.updated_at, s.deleted_at"
)

#: Columns of a subject version.
VERSION_COLUMNS = (
    "v.id, v.subject_id, v.version, v.schema_id, v.project_id, v.version_record_id, v.schema_type, "
    "v.fingerprint, v.\"references\", v.created_by, v.created_at, v.deleted_at"
)

#: Tenant defaults when no ``schema_registry_config`` row exists yet (the V294 column defaults).
DEFAULT_CONFIG = {"compatibility_level": "BACKWARD", "mode": MODE_READWRITE}


def _one(rows: Sequence[Any]) -> Optional[Dict[str, Any]]:
    """Return the first row as a plain dict, or ``None``."""
    return dict(rows[0]) if rows else None


def _fetch_one(cursor: Any, query: str, params: Sequence[Any]) -> Optional[Dict[str, Any]]:
    """Execute ``query`` on ``cursor`` and return the first row as a plain dict, or ``None``."""
    cursor.execute(query, tuple(params))
    row = cursor.fetchone()
    return dict(row) if row is not None else None


# --------------------------------------------------------------------------- config


def get_config(db: Any, tenant_id: str) -> Dict[str, Any]:
    """Return the tenant's registry defaults (``compatibility_level``, ``mode``).

    Args:
        db: The database handle.
        tenant_id: The tenant.

    Returns:
        The stored defaults, or :data:`DEFAULT_CONFIG` when the tenant has none yet.
    """
    row = _one(
        db.execute_query(
            "SELECT compatibility_level, mode FROM apiome.schema_registry_config WHERE tenant_id = %s",
            (tenant_id,),
        )
    )
    return row or dict(DEFAULT_CONFIG)


def put_config(
    db: Any, tenant_id: str, *, compatibility_level: Optional[str], mode: Optional[str]
) -> Dict[str, Any]:
    """Set the tenant's registry defaults; a ``None`` argument keeps the stored value.

    Args:
        db: The database handle.
        tenant_id: The tenant.
        compatibility_level: The new default level, or ``None`` to keep it.
        mode: The new default mode, or ``None`` to keep it.

    Returns:
        The defaults after the write.
    """
    rows = db.execute_query(
        """
        INSERT INTO apiome.schema_registry_config (tenant_id, compatibility_level, mode)
        VALUES (%s, COALESCE(%s, 'BACKWARD'), COALESCE(%s, 'READWRITE'))
        ON CONFLICT (tenant_id) DO UPDATE
           SET compatibility_level = COALESCE(%s, schema_registry_config.compatibility_level),
               mode = COALESCE(%s, schema_registry_config.mode),
               updated_at = CURRENT_TIMESTAMP
        RETURNING compatibility_level, mode
        """,
        (tenant_id, compatibility_level, mode, compatibility_level, mode),
    )
    return dict(rows[0])


# --------------------------------------------------------------------------- subjects


def list_subjects(db: Any, tenant_id: str) -> List[Dict[str, Any]]:
    """List the tenant's live subjects by name, each with ``version_count`` and ``latest_version``.

    Soft-deleted subjects and soft-deleted versions are left out.
    """
    rows = db.execute_query(
        f"""
        SELECT {SUBJECT_COLUMNS},
               COUNT(v.id)::int AS version_count,
               MAX(v.version) AS latest_version
        FROM apiome.schema_subjects s
        LEFT JOIN apiome.schema_subject_versions v
               ON v.subject_id = s.id AND v.deleted_at IS NULL
        WHERE s.tenant_id = %s AND s.deleted_at IS NULL
        GROUP BY s.id
        ORDER BY s.name ASC
        """,
        (tenant_id,),
    )
    return [dict(r) for r in rows or []]


def get_subject(db: Any, tenant_id: str, name: str) -> Optional[Dict[str, Any]]:
    """Return the tenant's live subject called ``name``, or ``None``."""
    return _one(
        db.execute_query(
            f"""
            SELECT {SUBJECT_COLUMNS}
            FROM apiome.schema_subjects s
            WHERE s.tenant_id = %s AND s.name = %s AND s.deleted_at IS NULL
            """,
            (tenant_id, name),
        )
    )


def upsert_subject(
    db: Any,
    tenant_id: str,
    name: str,
    *,
    strategy: Optional[str],
    compatibility_level: Optional[str],
    mode: Optional[str],
    actor_id: Optional[str],
) -> Dict[str, Any]:
    """Create the live subject ``name`` or update its settings; ``None`` keeps a stored value.

    A new subject takes the tenant's default mode when ``mode`` is ``None``; its compatibility
    level stays ``NULL`` (the tenant default) unless one is given.

    Returns:
        The subject after the write.
    """
    defaults = get_config(db, tenant_id)
    rows = db.execute_query(
        f"""
        INSERT INTO apiome.schema_subjects AS s
               (tenant_id, name, strategy, compatibility_level, mode, created_by)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (tenant_id, name) WHERE deleted_at IS NULL DO UPDATE
           SET strategy = COALESCE(%s, s.strategy),
               compatibility_level = COALESCE(%s, s.compatibility_level),
               mode = COALESCE(%s, s.mode),
               updated_at = CURRENT_TIMESTAMP
        RETURNING {SUBJECT_COLUMNS}
        """,
        (
            tenant_id,
            name,
            strategy,
            compatibility_level,
            mode or defaults["mode"],
            actor_id,
            strategy,
            compatibility_level,
            mode,
        ),
    )
    return dict(rows[0])


def soft_delete_subject(db: Any, tenant_id: str, name: str) -> Optional[List[int]]:
    """Soft-delete a live subject and its versions; their schema ids keep resolving.

    Returns:
        The versions that were deleted (ascending), or ``None`` when no live subject has that name.
    """

    def work(cursor: Any) -> Optional[List[int]]:
        subject = _fetch_one(
            cursor,
            """
            UPDATE apiome.schema_subjects
               SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
             WHERE tenant_id = %s AND name = %s AND deleted_at IS NULL
            RETURNING id
            """,
            (tenant_id, name),
        )
        if subject is None:
            return None
        cursor.execute(
            """
            UPDATE apiome.schema_subject_versions
               SET deleted_at = CURRENT_TIMESTAMP
             WHERE subject_id = %s AND deleted_at IS NULL
            RETURNING version
            """,
            (subject["id"],),
        )
        return sorted(int(r["version"]) for r in cursor.fetchall() or [])

    return db._guarded_tx(work)


# --------------------------------------------------------------------------- versions


def list_versions(db: Any, subject_id: str) -> List[Dict[str, Any]]:
    """Return a subject's live versions, oldest first."""
    rows = db.execute_query(
        f"""
        SELECT {VERSION_COLUMNS}
        FROM apiome.schema_subject_versions v
        WHERE v.subject_id = %s AND v.deleted_at IS NULL
        ORDER BY v.version ASC
        """,
        (subject_id,),
    )
    return [dict(r) for r in rows or []]


def get_version(db: Any, subject_id: str, version: int) -> Optional[Dict[str, Any]]:
    """Return one live version of a subject, or ``None``."""
    return _one(
        db.execute_query(
            f"""
            SELECT {VERSION_COLUMNS}
            FROM apiome.schema_subject_versions v
            WHERE v.subject_id = %s AND v.version = %s AND v.deleted_at IS NULL
            """,
            (subject_id, int(version)),
        )
    )


def next_version_number(db: Any, subject_id: str) -> int:
    """Return the version number the subject's next registration gets (deleted versions count)."""
    row = _one(
        db.execute_query(
            "SELECT COALESCE(MAX(version), 0) + 1 AS version FROM apiome.schema_subject_versions "
            "WHERE subject_id = %s",
            (subject_id,),
        )
    )
    return int(row["version"]) if row else 1


def find_version_by_fingerprint(
    db: Any, subject_id: str, schema_type: str, fingerprint: str
) -> Optional[Dict[str, Any]]:
    """Return the subject's live version holding this exact schema, or ``None`` (idempotency)."""
    return _one(
        db.execute_query(
            f"""
            SELECT {VERSION_COLUMNS}
            FROM apiome.schema_subject_versions v
            WHERE v.subject_id = %s AND v.schema_type = %s AND v.fingerprint = %s
              AND v.deleted_at IS NULL
            """,
            (subject_id, schema_type, fingerprint),
        )
    )


# --------------------------------------------------------------------------- schemas


def get_schema_by_fingerprint(
    db: Any, tenant_id: str, schema_type: str, fingerprint: str
) -> Optional[Dict[str, Any]]:
    """Return the tenant's schema row for this fingerprint (current kind), or ``None``."""
    return _one(
        db.execute_query(
            """
            SELECT schema_id, schema_type, fingerprint, fingerprint_kind, project_id,
                   version_record_id, "references", created_at
            FROM apiome.schema_registry_schemas
            WHERE tenant_id = %s AND schema_type = %s AND fingerprint_kind = %s AND fingerprint = %s
            """,
            (tenant_id, schema_type, FINGERPRINT_KIND, fingerprint),
        )
    )


def get_schema_by_id(db: Any, tenant_id: str, schema_id: int) -> Optional[Dict[str, Any]]:
    """Resolve a schema id — even when every subject holding it is soft-deleted.

    Returns:
        The schema row plus the revision's ``source_format`` / ``format_metadata`` (for its text)
        and ``subjects`` — the live ``{subject, version}`` pairs holding it — or ``None``.
    """
    row = _one(
        db.execute_query(
            """
            SELECT r.schema_id, r.schema_type, r.fingerprint, r.fingerprint_kind, r.project_id,
                   r.version_record_id, r."references", r.created_at,
                   ver.source_format, ver.format_metadata
            FROM apiome.schema_registry_schemas r
            LEFT JOIN apiome.versions ver ON ver.id = r.version_record_id
            WHERE r.tenant_id = %s AND r.schema_id = %s
            """,
            (tenant_id, int(schema_id)),
        )
    )
    if row is None:
        return None
    holders = db.execute_query(
        """
        SELECT s.name AS subject, v.version
        FROM apiome.schema_subject_versions v
        JOIN apiome.schema_subjects s ON s.id = v.subject_id
        WHERE v.tenant_id = %s AND v.schema_id = %s
          AND v.deleted_at IS NULL AND s.deleted_at IS NULL
        ORDER BY s.name ASC, v.version ASC
        """,
        (tenant_id, int(schema_id)),
    )
    row["subjects"] = [{"subject": h["subject"], "version": int(h["version"])} for h in holders or []]
    return row


def get_revision_source(db: Any, version_record_id: str) -> Optional[Dict[str, Any]]:
    """Return a revision's ``source_format`` and ``format_metadata`` (where its schema text lives)."""
    return _one(
        db.execute_query(
            "SELECT id, source_format, format_metadata FROM apiome.versions WHERE id = %s",
            (version_record_id,),
        )
    )


def get_latest_live_revision(db: Any, tenant_id: str, project_id: str) -> Optional[Dict[str, Any]]:
    """Return the latest live revision of a tenant's live catalog item, or ``None``.

    "Latest" orders exactly like the catalog's own latest-revision projection (newest
    ``created_at``, then id), so the revision attached is the one the item page shows.
    """
    return _one(
        db.execute_query(
            """
            SELECT v.id, v.version_id, v.source_format, v.format_metadata
            FROM apiome.versions v
            JOIN apiome.projects p ON p.id = v.project_id
            WHERE v.project_id = %s AND p.tenant_id = %s AND p.publishable = false
              AND v.deleted_at IS NULL AND p.deleted_at IS NULL
            ORDER BY v.created_at DESC NULLS LAST, v.id DESC
            LIMIT 1
            """,
            (project_id, tenant_id),
        )
    )


def record_version(
    db: Any,
    *,
    tenant_id: str,
    subject: str,
    schema_type: str,
    fingerprint: str,
    references: List[Any],
    project_id: str,
    version_record_id: str,
    actor_id: Optional[str],
    strategy: Optional[str] = None,
    subject_project_id: Optional[str] = None,
    require_empty_subject: bool = False,
) -> Dict[str, Any]:
    """Register ``fingerprint`` under ``subject`` in one transaction and return the version.

    Steps, under a row lock on the subject:

    1. create the live subject when it does not exist (tenant default mode);
    2. back the subject with ``subject_project_id`` when it has no catalog item yet;
    3. find the schema id for (type, fingerprint) or allocate the next one from the tenant counter;
    4. if the subject already holds that id, return that version (idempotent — revived when it had
       been soft-deleted on its own);
    5. otherwise insert version ``max + 1`` pointing at ``project_id`` / ``version_record_id``.

    Args:
        db: The database handle.
        tenant_id: The tenant.
        subject: The subject name.
        schema_type: ``AVRO`` / ``JSON`` / ``PROTOBUF``.
        fingerprint: The canonical-model fingerprint.
        references: Schema references as sent (stored verbatim, a JSON array).
        project_id: The catalog item holding the schema.
        version_record_id: The revision holding the schema.
        actor_id: The registering user, or ``None``.
        strategy: The strategy a newly created subject records.
        subject_project_id: The catalog item to back the subject with, when it has none.
        require_empty_subject: Refuse when the subject already has a version (attach).

    Returns:
        The version row plus ``created`` (``False`` when the subject already held the schema),
        ``subject`` (name) and ``subject_id``.

    Raises:
        SchemaRegistryError: ``subject-has-versions`` (409) when ``require_empty_subject`` and the
            subject is not empty; ``subject-attached-elsewhere`` (409) when attaching a subject that
            is already backed by another catalog item.
    """
    refs_json = json.dumps(references or [])

    def work(cursor: Any) -> Dict[str, Any]:
        cursor.execute(
            """
            INSERT INTO apiome.schema_subjects (tenant_id, name, strategy, mode, created_by)
            VALUES (%s, %s, %s,
                    COALESCE((SELECT mode FROM apiome.schema_registry_config WHERE tenant_id = %s),
                             'READWRITE'),
                    %s)
            ON CONFLICT (tenant_id, name) WHERE deleted_at IS NULL DO NOTHING
            """,
            (tenant_id, subject, strategy, tenant_id, actor_id),
        )
        row = _fetch_one(
            cursor,
            f"""
            SELECT {SUBJECT_COLUMNS} FROM apiome.schema_subjects s
            WHERE s.tenant_id = %s AND s.name = %s AND s.deleted_at IS NULL
            FOR UPDATE
            """,
            (tenant_id, subject),
        )
        if row is None:  # deleted between the insert and the lock
            raise SchemaRegistryError(
                "subject-not-found", f"Subject {subject!r} was deleted meanwhile.", status_code=409
            )
        subject_id = row["id"]

        if require_empty_subject:
            if row.get("project_id") and str(row["project_id"]) != str(subject_project_id):
                raise SchemaRegistryError(
                    "subject-attached-elsewhere",
                    f"Subject {subject!r} is already backed by another catalog item.",
                    status_code=409,
                )
            taken = _fetch_one(
                cursor,
                "SELECT 1 AS taken FROM apiome.schema_subject_versions WHERE subject_id = %s LIMIT 1",
                (subject_id,),
            )
            if taken:
                raise SchemaRegistryError(
                    "subject-has-versions",
                    f"Subject {subject!r} already has versions; attach an item to an empty subject.",
                    status_code=409,
                )
        if subject_project_id and not row.get("project_id"):
            cursor.execute(
                "UPDATE apiome.schema_subjects SET project_id = %s, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = %s",
                (subject_project_id, subject_id),
            )

        schema = _fetch_one(
            cursor,
            """
            SELECT schema_id FROM apiome.schema_registry_schemas
            WHERE tenant_id = %s AND schema_type = %s AND fingerprint_kind = %s AND fingerprint = %s
            """,
            (tenant_id, schema_type, FINGERPRINT_KIND, fingerprint),
        )
        if schema is None:
            cursor.execute(
                "INSERT INTO apiome.schema_registry_config (tenant_id) VALUES (%s) "
                "ON CONFLICT (tenant_id) DO NOTHING",
                (tenant_id,),
            )
            allocated = _fetch_one(
                cursor,
                """
                UPDATE apiome.schema_registry_config
                   SET next_schema_id = next_schema_id + 1, updated_at = CURRENT_TIMESTAMP
                 WHERE tenant_id = %s
                RETURNING next_schema_id - 1 AS schema_id
                """,
                (tenant_id,),
            )
            schema = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.schema_registry_schemas
                       (tenant_id, schema_id, schema_type, fingerprint, fingerprint_kind,
                        project_id, version_record_id, "references")
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                RETURNING schema_id
                """,
                (
                    tenant_id,
                    allocated["schema_id"],
                    schema_type,
                    fingerprint,
                    FINGERPRINT_KIND,
                    project_id,
                    version_record_id,
                    refs_json,
                ),
            )
        schema_id = int(schema["schema_id"])

        existing = _fetch_one(
            cursor,
            f"SELECT {VERSION_COLUMNS} FROM apiome.schema_subject_versions v "
            "WHERE v.subject_id = %s AND v.schema_id = %s",
            (subject_id, schema_id),
        )
        if existing is not None:
            if existing.get("deleted_at") is not None:
                cursor.execute(
                    "UPDATE apiome.schema_subject_versions SET deleted_at = NULL WHERE id = %s",
                    (existing["id"],),
                )
                existing["deleted_at"] = None
            return {**existing, "created": False, "subject": subject, "subject_id": subject_id}

        next_version = _fetch_one(
            cursor,
            "SELECT COALESCE(MAX(version), 0) + 1 AS version FROM apiome.schema_subject_versions "
            "WHERE subject_id = %s",
            (subject_id,),
        )
        inserted = _fetch_one(
            cursor,
            f"""
            INSERT INTO apiome.schema_subject_versions AS v
                   (tenant_id, subject_id, version, schema_id, project_id, version_record_id,
                    schema_type, fingerprint, "references", created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            RETURNING {VERSION_COLUMNS}
            """,
            (
                tenant_id,
                subject_id,
                int(next_version["version"]),
                schema_id,
                project_id,
                version_record_id,
                schema_type,
                fingerprint,
                refs_json,
                actor_id,
            ),
        )
        return {**inserted, "created": True, "subject": subject, "subject_id": subject_id}

    return db._guarded_tx(work)


# --------------------------------------------------------------------------- Confluent API (CDG-4.3)


def list_subject_names(db: Any, tenant_id: str, *, include_deleted: bool = False) -> List[str]:
    """Return the tenant's subject names, sorted; soft-deleted ones only with ``include_deleted``.

    A name both live and soft-deleted (deleted, then registered again) appears once.
    """
    deleted_clause = "" if include_deleted else "AND deleted_at IS NULL"
    rows = db.execute_query(
        f"""
        SELECT DISTINCT name FROM apiome.schema_subjects
        WHERE tenant_id = %s {deleted_clause}
        ORDER BY name ASC
        """,
        (tenant_id,),
    )
    return [str(r["name"]) for r in rows or []]


def hard_delete_subject(db: Any, tenant_id: str, name: str) -> Optional[List[int]]:
    """Permanently delete a subject that was soft-deleted first (Confluent ``?permanent=true``).

    Removes the soft-deleted subject rows called ``name`` and their versions. Schema rows stay, so an
    id another subject still holds keeps resolving, and the catalog item revisions are untouched.

    Returns:
        The versions removed (ascending), or ``None`` when no soft-deleted subject has that name.

    Raises:
        SchemaRegistryError: ``subject-not-soft-deleted`` (404) when the subject is still live.
    """

    def work(cursor: Any) -> Optional[List[int]]:
        live = _fetch_one(
            cursor,
            "SELECT id FROM apiome.schema_subjects WHERE tenant_id = %s AND name = %s AND deleted_at IS NULL",
            (tenant_id, name),
        )
        if live is not None:
            raise SchemaRegistryError(
                "subject-not-soft-deleted",
                f"Subject {name!r} must be soft-deleted before it is permanently deleted.",
                status_code=404,
            )
        cursor.execute(
            """
            DELETE FROM apiome.schema_subject_versions v
             USING apiome.schema_subjects s
             WHERE v.subject_id = s.id AND s.tenant_id = %s AND s.name = %s AND s.deleted_at IS NOT NULL
            RETURNING v.version
            """,
            (tenant_id, name),
        )
        versions = sorted(int(r["version"]) for r in cursor.fetchall() or [])
        cursor.execute(
            """
            DELETE FROM apiome.schema_subjects
             WHERE tenant_id = %s AND name = %s AND deleted_at IS NOT NULL
            RETURNING id
            """,
            (tenant_id, name),
        )
        if not cursor.fetchall():
            return None
        return versions

    return db._guarded_tx(work)
