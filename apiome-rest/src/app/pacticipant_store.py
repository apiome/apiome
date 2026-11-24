"""Persistence for the pacticipant registry — PFX-1.1 (#6914).

:mod:`app.pacticipant` says what a pacticipant, a version, a branch and a tag *are*; this module is
the only place one is read or written (apiome-db V432), so the registry's rules are applied once.

**Everything starts from a pacticipant of the caller's tenant.** Only ``pacticipant`` carries
``tenant_id``; versions, branches and tags are always read and written through a
:class:`~app.pacticipant.PacticipantRecord` that :func:`get_pacticipant` resolved inside the
caller's tenant, so no function here can reach another tenant's rows.

**A version is written once.** :func:`record_version` inserts the version or, when it already
exists, returns it untouched — there is no code path that updates one, and V432's trigger refuses
an UPDATE anyway. Recording the same version again is how a build adds a branch or tags to it.

**A branch head only moves forward.** :func:`record_version` is the only writer of
``head_version_id``, and the statement that moves it carries the guard: the head changes only when
the recorded version's ``seq`` is higher than the current head's. Recording an older version on a
branch adds it to the branch and leaves the head where it was.

**Tags and branch membership are idempotent.** Both are ``ON CONFLICT DO NOTHING`` on their natural
keys.

Every function takes the :class:`~app.database.Database` it runs on, so the live-database tests can
pass one bound to a rolled-back transaction.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import psycopg2

from .consumer_contract_store import ConsumerActor
from .keyset_lists import ListOrder, SortColumn, by_name
from .pacticipant import (
    CODE_CONSUMER_NOT_FOUND,
    CODE_NOT_FOUND,
    CODE_PROJECT_NOT_FOUND,
    CODE_SLUG_TAKEN,
    CODE_VERSION_NOT_FOUND,
    PacticipantBranchRecord,
    PacticipantInput,
    PacticipantPatch,
    PacticipantRecord,
    PacticipantValidationError,
    PacticipantVersionInput,
    PacticipantVersionRecord,
    RecordedPacticipantVersion,
    branch_record_from_row,
    pacticipant_record_from_row,
    slugify_pacticipant_name,
    validate_branch,
    validate_name,
    validate_slug,
    validate_tag,
    validate_tags,
    validate_url,
    validate_version_number,
    version_record_from_row,
)
from .revision_deprecation import is_uuid_string

__all__ = [
    "BRANCHES_ORDER",
    "PACTICIPANTS_ORDER",
    "VERSIONS_ORDER",
    "add_tag",
    "create_pacticipant",
    "delete_pacticipant",
    "ensure_pacticipant_tx",
    "get_pacticipant",
    "get_version",
    "list_branches",
    "list_pacticipants",
    "list_versions",
    "record_version",
    "record_version_tx",
    "update_pacticipant",
]

#: The columns every pacticipant read returns.
_PACTICIPANT_COLUMNS = """
    id::text AS id, tenant_id::text AS tenant_id, slug, name, repository_url, main_branch,
    project_id::text AS project_id, consumer_id::text AS consumer_id, created_at, updated_at
"""

#: The columns every version read returns: the row plus its branches and tags, by name.
_VERSION_COLUMNS = """
    v.id::text AS id, v.pacticipant_id::text AS pacticipant_id, v.number, v.seq, v.build_url,
    v.created_by::text AS created_by, v.actor_label, v.created_at,
    COALESCE((SELECT array_agg(b.name ORDER BY b.name)
              FROM apiome.pacticipant_branch_version bv
              JOIN apiome.pacticipant_branch b ON b.id = bv.branch_id
              WHERE bv.version_id = v.id AND bv.pacticipant_id = v.pacticipant_id), '{}') AS branches,
    COALESCE((SELECT array_agg(t.name ORDER BY t.name)
              FROM apiome.pacticipant_version_tag t
              WHERE t.version_id = v.id AND t.pacticipant_id = v.pacticipant_id), '{}') AS tags
"""

#: The order of :func:`list_pacticipants`: by handle.
PACTICIPANTS_ORDER = by_name("pacticipants", "slug", "id", name_field="slug")

#: The order of :func:`list_versions`: latest recorded first.
VERSIONS_ORDER = ListOrder(
    "pacticipant-versions", (SortColumn("v.seq", "int", ("seq",), descending=True),)
)

#: The order of :func:`list_branches`: by name.
BRANCHES_ORDER = by_name("pacticipant-branches", "b.name", "b.id")


def _user_id(actor: ConsumerActor) -> Optional[str]:
    """The actor's user id when it is a storable UUID, else ``None``."""
    return actor.user_id if actor.user_id and is_uuid_string(str(actor.user_id)) else None


# ---------------------------------------------------------------------------------------------
# Bindings
# ---------------------------------------------------------------------------------------------


def _resolve_project_id(db: Any, tenant_id: str, project_ref: str) -> str:
    """Resolve a project slug or id to a live project of the tenant.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.

    Returns:
        The project id.

    Raises:
        PacticipantValidationError: ``pacticipant-project-not-found``.
    """
    ref = (project_ref or "").strip()
    row = None
    if ref:
        row = db.get_project_core(ref, tenant_id) if is_uuid_string(ref) else db.get_project_by_slug(ref, tenant_id)
    if not row:
        raise PacticipantValidationError(CODE_PROJECT_NOT_FOUND, f"no project '{ref}' in this tenant")
    return str(row["id"])


def _resolve_consumer_id(db: Any, tenant_id: str, consumer_id: str) -> str:
    """Check a consumer id names a live consumer of the tenant.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        consumer_id: The consumer's id.

    Returns:
        The consumer id.

    Raises:
        PacticipantValidationError: ``pacticipant-consumer-not-found``.
    """
    ref = (consumer_id or "").strip()
    row = db.get_consumer_by_id(ref, tenant_id) if is_uuid_string(ref) else None
    if not row:
        raise PacticipantValidationError(CODE_CONSUMER_NOT_FOUND, f"no consumer '{ref}' in this tenant")
    return str(row["id"])


# ---------------------------------------------------------------------------------------------
# Pacticipants
# ---------------------------------------------------------------------------------------------


def get_pacticipant(db: Any, tenant_id: str, pacticipant_ref: str) -> PacticipantRecord:
    """Read one pacticipant of the tenant by handle, id, or name.

    A reference that is not an id is reduced to the handle it would be given as a name, so a CI
    job that sends the name its Pact file carries (``Billing Service``) finds ``billing-service``.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        pacticipant_ref: Slug, id, or display name.

    Returns:
        The record.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found`` when nothing matches in this tenant.
    """
    ref = (pacticipant_ref or "").strip()
    if is_uuid_string(str(tenant_id or "")) and ref:
        # A UUID is also a well-formed handle, so an id-shaped reference is tried as both.
        by_id = "id = %s::uuid OR " if is_uuid_string(ref) else ""
        rows = db.execute_query(
            f"""
            SELECT {_PACTICIPANT_COLUMNS}
            FROM apiome.pacticipant
            WHERE tenant_id = %s::uuid AND ({by_id}slug = %s)
            """,
            (tenant_id, *([ref] if by_id else []), slugify_pacticipant_name(ref)),
        )
        if rows:
            return pacticipant_record_from_row(dict(rows[0]))
    raise PacticipantValidationError(CODE_NOT_FOUND, f"no pacticipant '{ref}' in this tenant")


def list_pacticipants(
    db: Any,
    tenant_id: str,
    *,
    limit: Optional[int] = None,
    cursor: Optional[Sequence[Any]] = None,
) -> List[PacticipantRecord]:
    """The tenant's pacticipants, by handle.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        limit: Rows to read; ``None`` reads every one.
        cursor: :data:`PACTICIPANTS_ORDER` values of the last row already seen.

    Returns:
        The records; empty when none is registered.
    """
    if not is_uuid_string(str(tenant_id or "")):
        return []
    after_sql, after_params, limit_sql, limit_params = PACTICIPANTS_ORDER.window(limit, cursor)
    rows = db.execute_query(
        f"""
        SELECT {_PACTICIPANT_COLUMNS}
        FROM apiome.pacticipant
        WHERE tenant_id = %s::uuid{after_sql}
        ORDER BY {PACTICIPANTS_ORDER.order_by}{limit_sql}
        """,
        (tenant_id, *after_params, *limit_params),
    )
    return [pacticipant_record_from_row(dict(row)) for row in rows]


def create_pacticipant(
    db: Any, tenant_id: str, definition: PacticipantInput, *, actor: ConsumerActor
) -> PacticipantRecord:
    """Register a pacticipant.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        definition: Its identity and optional bindings.
        actor: Who is registering it.

    Returns:
        The stored record.

    Raises:
        PacticipantValidationError: ``pacticipant-invalid-name``, ``pacticipant-invalid-slug``,
            ``pacticipant-invalid-url``, ``pacticipant-invalid-branch``,
            ``pacticipant-project-not-found``, ``pacticipant-consumer-not-found``, or
            ``pacticipant-slug-taken`` when the tenant already has that handle.
    """
    name = validate_name(definition.name)
    slug = validate_slug(definition.slug or slugify_pacticipant_name(name))
    repository_url = validate_url(definition.repository_url, what="repository URL")
    main_branch = validate_branch(definition.main_branch) if definition.main_branch else None
    project_id = _resolve_project_id(db, tenant_id, definition.project) if definition.project else None
    consumer_id = (
        _resolve_consumer_id(db, tenant_id, definition.consumer_id) if definition.consumer_id else None
    )
    user_id = _user_id(actor)
    try:
        rows = db.execute_query(
            f"""
            INSERT INTO apiome.pacticipant (
                tenant_id, slug, name, repository_url, main_branch, project_id, consumer_id,
                created_by, updated_by
            )
            VALUES (%s::uuid, %s, %s, %s, %s, %s::uuid, %s::uuid, %s::uuid, %s::uuid)
            RETURNING {_PACTICIPANT_COLUMNS}
            """,
            (tenant_id, slug, name, repository_url, main_branch, project_id, consumer_id, user_id, user_id),
        )
    except psycopg2.errors.UniqueViolation as exc:
        raise PacticipantValidationError(
            CODE_SLUG_TAKEN, f"a pacticipant '{slug}' already exists in this tenant"
        ) from exc
    return pacticipant_record_from_row(dict(rows[0]))


def update_pacticipant(
    db: Any,
    tenant_id: str,
    pacticipant_ref: str,
    patch: PacticipantPatch,
    *,
    actor: ConsumerActor,
) -> PacticipantRecord:
    """Apply a partial update. An omitted field is left alone; an explicit ``None`` clears it.

    The handle is not updatable: renaming it would orphan every pact and CI job that names it.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        pacticipant_ref: Slug, id or name.
        patch: The fields to change.
        actor: Who is changing them.

    Returns:
        The updated record — unchanged when the patch carried no field.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``, or the same validation codes as
            :func:`create_pacticipant`.
    """
    existing = get_pacticipant(db, tenant_id, pacticipant_ref)
    sent = patch.model_fields_set
    values: Dict[str, Any] = {}
    if "name" in sent:
        values["name"] = validate_name(patch.name or "")
    if "repository_url" in sent:
        values["repository_url"] = validate_url(patch.repository_url, what="repository URL")
    if "main_branch" in sent:
        values["main_branch"] = validate_branch(patch.main_branch) if patch.main_branch else None
    if "project" in sent:
        values["project_id"] = _resolve_project_id(db, tenant_id, patch.project) if patch.project else None
    if "consumer_id" in sent:
        values["consumer_id"] = (
            _resolve_consumer_id(db, tenant_id, patch.consumer_id) if patch.consumer_id else None
        )
    if not values:
        return existing

    # Column names come from the literal keys above, never from the request.
    casts = {"project_id": "::uuid", "consumer_id": "::uuid"}
    assignments = ", ".join(f"{column} = %s{casts.get(column, '')}" for column in values)
    rows = db.execute_query(
        f"""
        UPDATE apiome.pacticipant
        SET {assignments}, updated_at = CURRENT_TIMESTAMP, updated_by = %s::uuid
        WHERE id = %s::uuid AND tenant_id = %s::uuid
        RETURNING {_PACTICIPANT_COLUMNS}
        """,
        (*values.values(), _user_id(actor), existing.id, tenant_id),
    )
    if not rows:
        raise PacticipantValidationError(CODE_NOT_FOUND, f"no pacticipant '{pacticipant_ref}' in this tenant")
    return pacticipant_record_from_row(dict(rows[0]))


def delete_pacticipant(db: Any, tenant_id: str, pacticipant_ref: str) -> PacticipantRecord:
    """Delete a pacticipant with its versions, branches and tags.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        pacticipant_ref: Slug, id or name.

    Returns:
        The record that was deleted.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``.
    """
    existing = get_pacticipant(db, tenant_id, pacticipant_ref)
    rows = db.execute_query(
        """
        DELETE FROM apiome.pacticipant
        WHERE id = %s::uuid AND tenant_id = %s::uuid
        RETURNING id::text AS id
        """,
        (existing.id, tenant_id),
    )
    if not rows:
        raise PacticipantValidationError(CODE_NOT_FOUND, f"no pacticipant '{pacticipant_ref}' in this tenant")
    return existing


# ---------------------------------------------------------------------------------------------
# Versions, branches and tags
# ---------------------------------------------------------------------------------------------


def _read_version(cursor_or_db: Any, pacticipant_id: str, number: str) -> Optional[Dict[str, Any]]:
    """Read one version row with its branches and tags.

    Args:
        cursor_or_db: An open cursor (inside a transaction) or the database.
        pacticipant_id: The owning pacticipant.
        number: The version number.

    Returns:
        The row, or ``None``.
    """
    query = f"""
        SELECT {_VERSION_COLUMNS}
        FROM apiome.pacticipant_version v
        WHERE v.pacticipant_id = %s::uuid AND v.number = %s
    """
    if hasattr(cursor_or_db, "execute_query"):
        rows = cursor_or_db.execute_query(query, (pacticipant_id, number))
        return dict(rows[0]) if rows else None
    cursor_or_db.execute(query, (pacticipant_id, number))
    row = cursor_or_db.fetchone()
    return dict(row) if row else None


def get_version(db: Any, pacticipant: PacticipantRecord, number: str) -> PacticipantVersionRecord:
    """Read one version of a pacticipant by its number.

    Args:
        db: The database.
        pacticipant: The pacticipant, already resolved in the caller's tenant.
        number: The version number, exactly as recorded.

    Returns:
        The record, with its branches and tags.

    Raises:
        PacticipantValidationError: ``pacticipant-version-not-found``.
    """
    row = _read_version(db, pacticipant.id, number or "")
    if row is None:
        raise PacticipantValidationError(
            CODE_VERSION_NOT_FOUND, f"pacticipant '{pacticipant.slug}' has no version '{number}'"
        )
    return version_record_from_row(row)


def list_versions(
    db: Any,
    pacticipant: PacticipantRecord,
    *,
    branch: Optional[str] = None,
    tag: Optional[str] = None,
    limit: Optional[int] = None,
    cursor: Optional[Sequence[Any]] = None,
) -> List[PacticipantVersionRecord]:
    """A pacticipant's versions, latest recorded first.

    Args:
        db: The database.
        pacticipant: The pacticipant, already resolved in the caller's tenant.
        branch: Only versions recorded on this branch.
        tag: Only versions carrying this tag.
        limit: Rows to read; ``None`` reads every one.
        cursor: :data:`VERSIONS_ORDER` values of the last row already seen.

    Returns:
        The records, each with its branches and tags.
    """
    filters = ""
    params: List[Any] = [pacticipant.id]
    if branch:
        filters += """
          AND EXISTS (SELECT 1 FROM apiome.pacticipant_branch_version fbv
                      JOIN apiome.pacticipant_branch fb ON fb.id = fbv.branch_id
                      WHERE fbv.version_id = v.id AND fbv.pacticipant_id = v.pacticipant_id
                        AND fb.name = %s)"""
        params.append(branch)
    if tag:
        filters += """
          AND EXISTS (SELECT 1 FROM apiome.pacticipant_version_tag ft
                      WHERE ft.version_id = v.id AND ft.pacticipant_id = v.pacticipant_id
                        AND ft.name = %s)"""
        params.append(tag)
    after_sql, after_params, limit_sql, limit_params = VERSIONS_ORDER.window(limit, cursor)
    rows = db.execute_query(
        f"""
        SELECT {_VERSION_COLUMNS}
        FROM apiome.pacticipant_version v
        WHERE v.pacticipant_id = %s::uuid{filters}{after_sql}
        ORDER BY {VERSIONS_ORDER.order_by}{limit_sql}
        """,
        (*params, *after_params, *limit_params),
    )
    return [version_record_from_row(dict(row)) for row in rows]


def _insert_tags(cursor: Any, pacticipant_id: str, version_id: str, tags: Sequence[str]) -> None:
    """Put tags on a version; a tag it already carries is left as it is.

    Args:
        cursor: The open transaction's cursor.
        pacticipant_id: The owning pacticipant.
        version_id: The version.
        tags: The tags, already validated.
    """
    if not tags:
        return
    cursor.execute(
        """
        INSERT INTO apiome.pacticipant_version_tag (version_id, pacticipant_id, name)
        SELECT %s::uuid, %s::uuid, tag FROM unnest(%s::text[]) AS tag
        ON CONFLICT (version_id, pacticipant_id, name) DO NOTHING
        """,
        (version_id, pacticipant_id, list(tags)),
    )


def record_version_tx(
    cursor: Any,
    pacticipant: PacticipantRecord,
    version_number: str,
    *,
    build_url: Optional[str],
    branch: Optional[str],
    tags: Sequence[str],
    actor: ConsumerActor,
) -> RecordedPacticipantVersion:
    """Record a version inside the caller's transaction — the statements of :func:`record_version`.

    A pact publication (:mod:`app.pact_publication_store`) records the consumer version and stores
    its pacts in one transaction, so it calls this with its own cursor.

    Args:
        cursor: The open transaction's cursor.
        pacticipant: The pacticipant, already resolved in the caller's tenant.
        version_number: The version number, already validated.
        build_url: The build URL, already validated, or ``None``.
        branch: The branch, already validated, or ``None``.
        tags: The tags, already validated and distinct.
        actor: Who is recording it.

    Returns:
        The version as stored, whether this call created it, and whether the branch head moved.
    """
    cursor.execute(
        """
        INSERT INTO apiome.pacticipant_version (pacticipant_id, number, build_url, created_by, actor_label)
        VALUES (%s::uuid, %s, %s, %s::uuid, %s)
        ON CONFLICT (pacticipant_id, number) DO NOTHING
        RETURNING id::text AS id, seq
        """,
        (pacticipant.id, version_number, build_url, _user_id(actor), actor.label),
    )
    inserted = cursor.fetchone()
    created = inserted is not None
    if inserted is None:
        cursor.execute(
            """
            SELECT id::text AS id, seq FROM apiome.pacticipant_version
            WHERE pacticipant_id = %s::uuid AND number = %s
            """,
            (pacticipant.id, version_number),
        )
        inserted = cursor.fetchone()
    version_id, seq = inserted["id"], inserted["seq"]

    head_moved = False
    if branch:
        # One statement creates the branch or moves its head, and the WHERE is the rule: the
        # head moves only to a version recorded later than the one it points at.
        cursor.execute(
            """
            INSERT INTO apiome.pacticipant_branch AS b (pacticipant_id, name, head_version_id)
            VALUES (%s::uuid, %s, %s::uuid)
            ON CONFLICT (pacticipant_id, name) DO UPDATE
                SET head_version_id = EXCLUDED.head_version_id, updated_at = CURRENT_TIMESTAMP
                WHERE (SELECT h.seq FROM apiome.pacticipant_version h WHERE h.id = b.head_version_id) < %s
            RETURNING b.id::text AS id
            """,
            (pacticipant.id, branch, version_id, seq),
        )
        head_moved = cursor.fetchone() is not None
        cursor.execute(
            """
            INSERT INTO apiome.pacticipant_branch_version (branch_id, pacticipant_id, version_id)
            SELECT b.id, b.pacticipant_id, %s::uuid
            FROM apiome.pacticipant_branch b
            WHERE b.pacticipant_id = %s::uuid AND b.name = %s
            ON CONFLICT (branch_id, pacticipant_id, version_id) DO NOTHING
            """,
            (version_id, pacticipant.id, branch),
        )
    _insert_tags(cursor, pacticipant.id, version_id, tags)

    row = _read_version(cursor, pacticipant.id, version_number)
    return RecordedPacticipantVersion(
        version=version_record_from_row(row or {}), created=created, head_moved=head_moved
    )


def ensure_pacticipant_tx(
    cursor: Any, tenant_id: str, name: str, *, actor: ConsumerActor
) -> PacticipantRecord:
    """Return the tenant's pacticipant of this name, registering it when it does not exist yet.

    A Pact publication names its consumer and provider; the first one to name an application
    registers it, as a Pact Broker does. The handle is derived from the name, so ``Billing
    Service`` and ``billing-service`` are the same pacticipant.

    Args:
        cursor: The open transaction's cursor.
        tenant_id: The caller's tenant.
        name: The pacticipant name, as the Pact file or the URL carries it.
        actor: Who is publishing.

    Returns:
        The stored record — the existing one, unchanged, when the handle was already registered.

    Raises:
        PacticipantValidationError: ``pacticipant-invalid-name`` or ``pacticipant-invalid-slug``
            when no handle can be derived from the name.
    """
    display_name = validate_name(name)
    slug = validate_slug(slugify_pacticipant_name(display_name))
    user_id = _user_id(actor)
    cursor.execute(
        """
        INSERT INTO apiome.pacticipant (tenant_id, slug, name, created_by, updated_by)
        VALUES (%s::uuid, %s, %s, %s::uuid, %s::uuid)
        ON CONFLICT (tenant_id, slug) DO NOTHING
        """,
        (tenant_id, slug, display_name, user_id, user_id),
    )
    cursor.execute(
        f"""
        SELECT {_PACTICIPANT_COLUMNS}
        FROM apiome.pacticipant
        WHERE tenant_id = %s::uuid AND slug = %s
        """,
        (tenant_id, slug),
    )
    return pacticipant_record_from_row(dict(cursor.fetchone()))


def record_version(
    db: Any,
    pacticipant: PacticipantRecord,
    number: str,
    details: PacticipantVersionInput,
    *,
    actor: ConsumerActor,
) -> RecordedPacticipantVersion:
    """Record a version of a pacticipant, with the branch it was built from and its tags.

    This is the write a publish makes. It is safe to repeat: the version is created once and never
    changed afterwards, a branch membership and a tag exist once, and the branch head moves only
    to a version recorded later than the current head.

    Args:
        db: The database.
        pacticipant: The pacticipant, already resolved in the caller's tenant.
        number: The version number, as the build reported it.
        details: The build URL, branch and tags.
        actor: Who is recording it.

    Returns:
        The version as stored, whether this call created it, and whether the branch head moved.

    Raises:
        PacticipantValidationError: ``pacticipant-invalid-version``, ``pacticipant-invalid-url``,
            ``pacticipant-invalid-branch`` or ``pacticipant-invalid-tag``.
    """
    version_number = validate_version_number(number)
    build_url = validate_url(details.build_url, what="build URL")
    branch = validate_branch(details.branch) if details.branch else None
    tags = validate_tags(details.tags)

    def work(cursor: Any) -> RecordedPacticipantVersion:
        return record_version_tx(
            cursor, pacticipant, version_number, build_url=build_url, branch=branch, tags=tags, actor=actor
        )

    try:
        return db._guarded_tx(work)
    except psycopg2.errors.ForeignKeyViolation as exc:
        # The pacticipant was deleted between the caller resolving it and this write.
        raise PacticipantValidationError(
            CODE_NOT_FOUND, f"pacticipant '{pacticipant.slug}' no longer exists"
        ) from exc


def add_tag(db: Any, pacticipant: PacticipantRecord, number: str, tag: str) -> PacticipantVersionRecord:
    """Put one tag on an existing version. Tagging it again changes nothing.

    Args:
        db: The database.
        pacticipant: The pacticipant, already resolved in the caller's tenant.
        number: The version number.
        tag: The tag.

    Returns:
        The version with its tags.

    Raises:
        PacticipantValidationError: ``pacticipant-invalid-tag`` or ``pacticipant-version-not-found``.
    """
    name = validate_tag(tag)
    existing = get_version(db, pacticipant, number)

    def work(cursor: Any) -> Optional[PacticipantVersionRecord]:
        _insert_tags(cursor, pacticipant.id, existing.id, [name])
        row = _read_version(cursor, pacticipant.id, existing.number)
        return version_record_from_row(row) if row else None

    try:
        tagged = db._guarded_tx(work)
    except psycopg2.errors.ForeignKeyViolation:
        tagged = None
    if tagged is None:
        raise PacticipantValidationError(
            CODE_VERSION_NOT_FOUND, f"pacticipant '{pacticipant.slug}' has no version '{number}'"
        )
    return tagged


def list_branches(
    db: Any,
    pacticipant: PacticipantRecord,
    *,
    limit: Optional[int] = None,
    cursor: Optional[Sequence[Any]] = None,
) -> List[PacticipantBranchRecord]:
    """A pacticipant's branches with their heads, by name.

    Args:
        db: The database.
        pacticipant: The pacticipant, already resolved in the caller's tenant.
        limit: Rows to read; ``None`` reads every one.
        cursor: :data:`BRANCHES_ORDER` values of the last row already seen.

    Returns:
        The records; empty when no version was recorded on a branch yet.
    """
    after_sql, after_params, limit_sql, limit_params = BRANCHES_ORDER.window(limit, cursor)
    rows = db.execute_query(
        f"""
        SELECT b.id::text AS id, b.pacticipant_id::text AS pacticipant_id, b.name,
               b.head_version_id::text AS head_version_id, h.number AS head_version,
               (b.name = %s) AS is_main, b.created_at, b.updated_at
        FROM apiome.pacticipant_branch b
        JOIN apiome.pacticipant_version h ON h.id = b.head_version_id
        WHERE b.pacticipant_id = %s::uuid{after_sql}
        ORDER BY {BRANCHES_ORDER.order_by}{limit_sql}
        """,
        (pacticipant.main_branch or "", pacticipant.id, *after_params, *limit_params),
    )
    return [branch_record_from_row(dict(row)) for row in rows]
