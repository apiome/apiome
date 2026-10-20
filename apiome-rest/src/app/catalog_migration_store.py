"""Persistence for the Backstage and Compass import — CDG-5.5 (#5983).

:mod:`app.catalog_migration` reads a catalog; this module stages what it read in apiome-db V299 and
applies a person's decisions:

* :func:`record_backstage_catalog` — a repository scan's ``catalog-info`` files: ``kind: API``
  definitions are imported through the import pipeline as catalog items, everything else is staged.
  Called by :func:`app.repository_file_scan.apply_backstage`; never raises.
* :func:`import_compass_export` — an uploaded Compass export, staged as one report.
* :func:`accept_suggestion` / :func:`dismiss_suggestion` — the click that makes a component or a
  team real (or not).

**Nothing becomes a confirmed owner or a resolved entity without a click.** Staging writes owner
*suggestions* only (``entity_owners`` sources ``backstage`` / ``compass``), and only onto entities
that already exist: an imported API, a Project a component matched, a component someone accepted.
An owner naming a team that does not exist yet waits until that team's suggestion is accepted.
A reference to a staged component stays unresolved (CDG-3.2) until the component is accepted, and
then :func:`app.declared_dependencies.promote_unresolved` resolves it.

**A re-run refreshes, it never duplicates.** Suggestions are keyed by (source, kind, external
ref), so a re-scan or a newer export updates a pending suggestion and keeps every decision. An
accepted Backstage component follows its file: its fields and declarations are rewritten on each
scan. A pending suggestion the file no longer declares is removed.

Every decision is audited (``catalog.migration.accept`` / ``catalog.migration.dismiss``) on the
cursor that makes it.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import psycopg2

from .catalog_migration import (
    MAX_UNMAPPED,
    SOURCE_BACKSTAGE,
    SOURCE_COMPASS,
    CatalogParseError,
    ParsedCatalog,
    StagedApi,
    StagedComponent,
    UnmappedField,
    imply_backstage_teams,
    parse_backstage_file,
    parse_compass_export,
)
from .catalog_migration_models import (
    CODE_COMPONENT_NOT_FOUND,
    CODE_DECIDED,
    CODE_INVALID,
    CODE_RUN_NOT_FOUND,
    CODE_SLUG_TAKEN,
    CODE_SUGGESTION_NOT_FOUND,
    AcceptInput,
    ComponentOut,
    MigrationError,
    MigrationRun,
    MigrationSuggestion,
    UnmappedFieldOut,
)
from .consumer_contract_store import ConsumerActor
from .database import db
from .declared_dependencies import DeclaredReference, backstage_name, promote_unresolved, replace_declared
from .entity_owner_store import record_suggestions_on_cursor
from .entity_owners import owner_envelope_join, owner_ref_from_value
from .revision_deprecation import is_uuid_string
from .team_store import insert_team
from .teams import TeamInput, TeamValidationError

__all__ = [
    "accept_suggestion",
    "backstage_run_ref",
    "dismiss_suggestion",
    "import_backstage_api",
    "import_compass_export",
    "list_runs",
    "read_component",
    "read_run",
    "read_suggestion",
    "record_backstage_catalog",
    "stage_catalog",
]

_logger = logging.getLogger(__name__)

#: Most reports one list returns.
_RUN_LIST_LIMIT = 100

_RUN_COLUMNS = """
    r.id::text AS id, r.source, r.label, r.repository_id::text AS repository_id, r.branch, r.counts,
    r.unmapped, r.unmapped_total, r.created_at, r.updated_at,
    (SELECT count(*) FROM apiome.catalog_import_suggestions s
      WHERE s.run_id = r.id AND s.status = 'suggested')::int AS pending
"""

_SUGGESTION_COLUMNS = """
    s.id::text AS id, s.run_id::text AS run_id, s.source, s.suggestion_kind, s.external_ref, s.name, s.slug,
    s.payload, s.status, s.match_kind, s.match_id::text AS match_id, s.entity_kind,
    s.entity_id::text AS entity_id, s.decided_at,
    mp.name AS match_name, mp.slug AS match_slug,
    COALESCE(ep.slug, et.slug, ec.slug) AS entity_slug
"""

_SUGGESTION_JOINS = """
    LEFT JOIN apiome.projects mp ON mp.id = s.match_id
    LEFT JOIN apiome.projects ep ON s.entity_kind IN ('project', 'catalog_item') AND ep.id = s.entity_id
    LEFT JOIN apiome.teams et ON s.entity_kind = 'team' AND et.id = s.entity_id
    LEFT JOIN apiome.catalog_components ec ON s.entity_kind = 'component' AND ec.id = s.entity_id
"""


def _iso(value: Any) -> Optional[str]:
    """An ISO timestamp, or ``None``."""
    return value.isoformat() if isinstance(value, datetime) else (str(value) if value else None)


def backstage_run_ref(repository_id: str, branch: str) -> str:
    """The ``source_ref`` of a repository branch's report: ``backstage:<repository id>@<branch>``."""
    return f"backstage:{repository_id}@{branch}"[:600]


def _references(payload: Mapping[str, Any]) -> List[DeclaredReference]:
    """A staged component's declared references, back from its payload."""
    return [
        DeclaredReference(reference=str(ref.get("reference")), edge_kind=str(ref.get("edgeKind")), slug=ref.get("slug"))
        for ref in payload.get("references") or []
        if isinstance(ref, Mapping) and ref.get("reference") and ref.get("edgeKind") in ("depends_on", "consumes")
    ]


# ---------------------------------------------------------------------------------------------
# Owners
# ---------------------------------------------------------------------------------------------


def _team_slug_for(cursor: Any, tenant_id: str, source: str, owner_ref: str) -> Optional[str]:
    """The live team an owner reference names, if there is one yet.

    A team made by accepting this owner's suggestion wins; otherwise a live team whose slug is the
    suggestion's slug (or, for Backstage, the group's name).
    """
    cursor.execute(
        """
        SELECT t.slug, s.slug AS suggested_slug
          FROM apiome.catalog_import_suggestions s
          LEFT JOIN apiome.teams t
                 ON s.status = 'accepted' AND t.id = s.entity_id AND t.deleted_at IS NULL
         WHERE s.tenant_id = %s::uuid AND s.source = %s AND s.suggestion_kind = 'team' AND s.external_ref = %s
        """,
        (tenant_id, source, owner_ref),
    )
    row = cursor.fetchone()
    if row and row.get("slug"):
        return str(row["slug"])
    candidates = [c for c in ((row or {}).get("suggested_slug"), backstage_name(owner_ref)) if c]
    if not candidates:
        return None
    cursor.execute(
        "SELECT slug FROM apiome.teams WHERE tenant_id = %s::uuid AND deleted_at IS NULL AND slug = ANY(%s::text[]) "
        "ORDER BY array_position(%s::text[], slug) LIMIT 1",
        (tenant_id, candidates, candidates),
    )
    found = cursor.fetchone()
    return str(found["slug"]) if found else None


def _apply_owner(cursor: Any, tenant_id: str, source: str, kind: str, entity_id: str, owner_ref: Optional[str]) -> bool:
    """Suggest the owner a catalog read for an existing entity; ``False`` when its team is not there yet."""
    if not owner_ref:
        return False
    slug = _team_slug_for(cursor, tenant_id, source, owner_ref)
    if not slug:
        return False
    record_suggestions_on_cursor(cursor, tenant_id, kind, entity_id, source, [{"team": slug, "sourceRef": owner_ref}])
    return True


def _apply_waiting_owners(cursor: Any, tenant_id: str, source: str, owner_ref: str) -> int:
    """Suggest a just-created team to every entity whose imported owner it is."""
    cursor.execute(
        """
        SELECT elem->>'entityKind' AS kind, elem->>'entityId' AS id
          FROM apiome.catalog_import_runs r
         CROSS JOIN LATERAL jsonb_array_elements(r.entity_refs) elem
         WHERE r.tenant_id = %s::uuid AND r.source = %s AND elem->>'ownerRef' = %s
        UNION
        SELECT s.entity_kind, s.entity_id::text
          FROM apiome.catalog_import_suggestions s
         WHERE s.tenant_id = %s::uuid AND s.source = %s AND s.suggestion_kind = 'component'
           AND s.status = 'accepted' AND s.payload->>'ownerRef' = %s
        """,
        (tenant_id, source, owner_ref, tenant_id, source, owner_ref),
    )
    applied = 0
    for row in cursor.fetchall():
        if row.get("kind") and is_uuid_string(row.get("id") or ""):
            applied += int(_apply_owner(cursor, tenant_id, source, str(row["kind"]), str(row["id"]), owner_ref))
    return applied


# ---------------------------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------------------------


def _match(cursor: Any, tenant_id: str, component: StagedComponent) -> Optional[Dict[str, Any]]:
    """The Project or catalog item a component already is: one its ``providesApis`` names, else
    one with its slug."""
    candidates = [*component.provides, component.slug]
    cursor.execute(
        """
        SELECT id::text AS id, publishable, lower(slug) AS slug FROM apiome.projects
         WHERE tenant_id = %s::uuid AND deleted_at IS NULL AND lower(slug) = ANY(%s::text[])
        """,
        (tenant_id, candidates),
    )
    by_slug = {row["slug"]: row for row in cursor.fetchall()}
    for candidate in candidates:
        row = by_slug.get(candidate)
        if row:
            return {"kind": "project" if row["publishable"] else "catalog_item", "id": row["id"]}
    return None


def _upsert_suggestion(
    cursor: Any,
    tenant_id: str,
    run_id: str,
    source: str,
    kind: str,
    external_ref: str,
    name: str,
    slug: str,
    payload: Mapping[str, Any],
    match: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Insert or refresh one suggestion, keeping its decision (and, once decided, its name and slug)."""
    cursor.execute(
        """
        INSERT INTO apiome.catalog_import_suggestions
            (tenant_id, run_id, source, suggestion_kind, external_ref, name, slug, payload, match_kind, match_id)
        VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::uuid)
        ON CONFLICT ON CONSTRAINT catalog_import_suggestions_identity_key DO UPDATE SET
            run_id = EXCLUDED.run_id,
            payload = EXCLUDED.payload,
            name = CASE WHEN catalog_import_suggestions.status = 'suggested'
                        THEN EXCLUDED.name ELSE catalog_import_suggestions.name END,
            slug = CASE WHEN catalog_import_suggestions.status = 'suggested'
                        THEN EXCLUDED.slug ELSE catalog_import_suggestions.slug END,
            match_kind = EXCLUDED.match_kind,
            match_id = EXCLUDED.match_id,
            updated_at = CURRENT_TIMESTAMP
        RETURNING id::text AS id, status, entity_kind, entity_id::text AS entity_id
        """,
        (
            tenant_id,
            run_id,
            source,
            kind,
            external_ref[:600],
            name[:400],
            slug,
            json.dumps(dict(payload)),
            (match or {}).get("kind"),
            (match or {}).get("id"),
        ),
    )
    return dict(cursor.fetchone())


def _write_component(cursor: Any, component_id: str, component: StagedComponent) -> None:
    """Refresh an accepted component from its source (a Backstage file it still follows)."""
    cursor.execute(
        """
        UPDATE apiome.catalog_components
           SET description = %s, category = %s, component_type = %s, lifecycle = %s, parent_ref = %s,
               links = %s::jsonb, source_ref = %s, updated_at = CURRENT_TIMESTAMP
         WHERE id = %s::uuid AND deleted_at IS NULL
        """,
        (
            component.description,
            component.category,
            component.component_type,
            component.lifecycle,
            component.parent_ref,
            json.dumps([link.as_json() for link in component.links]),
            component.source_ref,
            component_id,
        ),
    )


def stage_catalog(
    cursor: Any,
    tenant_id: str,
    *,
    source: str,
    source_ref: str,
    label: str,
    parsed: ParsedCatalog,
    repository_id: Optional[str] = None,
    branch: Optional[str] = None,
    actor_id: Optional[str] = None,
    files: int = 0,
    entity_refs: Sequence[Mapping[str, Any]] = (),
    apis_imported: int = 0,
) -> str:
    """Write one report and its suggestions on the caller's transaction (module docstring).

    Args:
        cursor: An open cursor; nothing is committed.
        tenant_id: The tenant.
        source: ``backstage`` or ``compass``.
        source_ref: The report's identity (:func:`backstage_run_ref` or ``compass:<upload id>``).
        label: What the person sees.
        parsed: What the catalog yielded.
        repository_id: The scanned repository (Backstage).
        branch: The scanned branch (Backstage).
        actor_id: Who uploaded it (Compass).
        files: How many files were read.
        entity_refs: Existing entities the run already knows (imported APIs: ``{entityKind, entityId,
            externalRef, ownerRef, digest}``).
        apis_imported: How many API definitions were imported (or were unchanged).

    Returns:
        The report id.
    """
    cursor.execute(
        """
        INSERT INTO apiome.catalog_import_runs (tenant_id, source, source_ref, label, repository_id, branch, created_by)
        VALUES (%s::uuid, %s, %s, %s, %s::uuid, %s, %s::uuid)
        ON CONFLICT ON CONSTRAINT catalog_import_runs_identity_key
        DO UPDATE SET label = EXCLUDED.label, updated_at = CURRENT_TIMESTAMP
        RETURNING id::text AS id
        """,
        (
            tenant_id,
            source,
            source_ref,
            label[:400],
            repository_id,
            branch,
            actor_id if is_uuid_string(actor_id or "") else None,
        ),
    )
    run_id = str(cursor.fetchone()["id"])
    refs: List[Dict[str, Any]] = [dict(ref) for ref in entity_refs]
    seen: List[str] = []
    counts = {
        "files": files,
        "entities": parsed.entities,
        "apisImported": apis_imported,
        "components": 0,
        "teams": 0,
        "teamsMatched": 0,
        "matched": 0,
        "ownerSuggestions": 0,
        "declared": 0,
    }

    for team in parsed.teams:
        cursor.execute(
            "SELECT 1 FROM apiome.teams WHERE tenant_id = %s::uuid AND slug = %s AND deleted_at IS NULL",
            (tenant_id, team.slug),
        )
        # A team with the slug is already here: owners resolve to it straight away, and accepting
        # the suggestion links it rather than creating another.
        exists = cursor.fetchone() is not None
        row = _upsert_suggestion(
            cursor,
            tenant_id,
            run_id,
            source,
            "team",
            team.external_ref,
            team.name,
            team.slug,
            {**team.payload(), "existingTeam": exists},
            None,
        )
        seen.append(row["id"])
        counts["teamsMatched" if exists else "teams"] += 1

    for component in parsed.components:
        match = _match(cursor, tenant_id, component)
        row = _upsert_suggestion(
            cursor,
            tenant_id,
            run_id,
            source,
            "component",
            component.external_ref,
            component.name,
            component.slug,
            component.payload(),
            match,
        )
        seen.append(row["id"])
        counts["components"] += 1
        if match:
            counts["matched"] += 1
            refs.append(
                {
                    "entityKind": match["kind"],
                    "entityId": match["id"],
                    "externalRef": component.external_ref,
                    "ownerRef": component.owner_ref,
                }
            )
        if row["status"] == "accepted" and row.get("entity_kind") == "component" and source == SOURCE_BACKSTAGE:
            _write_component(cursor, row["entity_id"], component)
            counts["declared"] += replace_declared(
                cursor, tenant_id, "component", row["entity_id"], component.source_ref, list(component.references)
            )["declared"]
            _apply_owner(cursor, tenant_id, source, "component", row["entity_id"], component.owner_ref)

    # Imported APIs and matched Projects get their owner suggestion now (when the team exists).
    for ref in refs:
        if _apply_owner(cursor, tenant_id, source, str(ref["entityKind"]), str(ref["entityId"]), ref.get("ownerRef")):
            counts["ownerSuggestions"] += 1

    cursor.execute(
        "DELETE FROM apiome.catalog_import_suggestions "
        "WHERE run_id = %s::uuid AND status = 'suggested' AND NOT (id = ANY(%s::uuid[]))",
        (run_id, seen),
    )
    unmapped = [item.as_json() for item in parsed.unmapped[:MAX_UNMAPPED]]
    cursor.execute(
        """
        UPDATE apiome.catalog_import_runs
           SET counts = %s::jsonb, unmapped = %s::jsonb, unmapped_total = %s, entity_refs = %s::jsonb,
               updated_at = CURRENT_TIMESTAMP
         WHERE id = %s::uuid
        """,
        (json.dumps(counts), json.dumps(unmapped), len(parsed.unmapped), json.dumps(refs), run_id),
    )
    return run_id


# ---------------------------------------------------------------------------------------------
# Backstage (repository scans)
# ---------------------------------------------------------------------------------------------


def _detect_kind(api: StagedApi, text: str) -> Optional[str]:
    """The import-source key for an API definition: what detection says, else its ``spec.type``."""
    from .format_detection import detect_format
    from .import_source import DetectionInput

    filename = (api.definition_path or f"{api.slug}.yaml").rsplit("/", 1)[-1]
    try:
        found = detect_format(DetectionInput(text=text, filename=filename))
    except Exception:  # noqa: BLE001 - fall back on the declared type
        found = None
    if found is not None and found.detected is not None and found.detected.importable and found.detected.source_key:
        return str(found.detected.source_key)
    return {"openapi": "openapi", "asyncapi": "asyncapi", "graphql": "graphql", "grpc": "grpc"}.get(
        (api.api_type or "").lower()
    )


def import_backstage_api(
    tenant_id: str,
    repository_id: str,
    branch: str,
    api: StagedApi,
    text: str,
    *,
    existing_project_id: Optional[str],
    actor_id: Optional[str],
) -> str:
    """Import one Backstage API definition through the import pipeline, as a catalog item.

    The first import creates the catalog item (slug: the API's name, or the name plus the
    repository when another entity has it); later ones add a revision to the same item. Runs the
    async pipeline on a private event loop, so call it from a thread with no running loop (the
    repository scan worker is one).

    Args:
        tenant_id: The repository's tenant.
        repository_id: The repository.
        branch: The scanned branch.
        api: The API.
        text: Its definition.
        existing_project_id: The catalog item an earlier scan imported it into, if it is still live.
        actor_id: The repository's creator (the import's user).

    Returns:
        The catalog item id.

    Raises:
        ValueError: No importer reads the definition, or the import failed.
    """
    from .import_source import get_import_source, resolve_import_source_key
    from .import_source_pipeline import run_adapter_import_job

    kind = _detect_kind(api, text)
    adapter = get_import_source(resolve_import_source_key(kind)) if kind else None
    if adapter is None:
        raise ValueError("no importer reads this definition")
    slug = api.slug
    if not existing_project_id:
        taken = db.execute_query(
            "SELECT 1 FROM apiome.projects WHERE tenant_id = %s::uuid AND lower(slug) = %s AND deleted_at IS NULL",
            (tenant_id, slug),
        )
        if taken:
            slug = f"{slug[:100]}-{str(repository_id)[:8]}"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    payload: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "user_id": actor_id,
        "filename": (api.definition_path or f"{api.slug}.yaml").rsplit("/", 1)[-1],
        "document_base64": base64.standard_b64encode(text.encode("utf-8")).decode("ascii"),
        "rest_job_id": f"backstage-{str(repository_id)[:8]}-{digest[:16]}",
        "metadata": {
            "source_kind": adapter.key,
            "project": {"name": api.name, "slug": slug},
            "version": {"version_id": f"backstage-{digest[:12]}"},
            "options": {},
            "existing_project_id": existing_project_id,
        },
        "migration_source": {
            "inputKind": "backstage",
            "repositoryId": str(repository_id),
            "branch": branch,
            "catalogInfoPath": api.path,
            "entityRef": api.external_ref,
            "definitionPath": api.definition_path,
        },
    }
    final = asyncio.run(run_adapter_import_job(adapter, payload))
    if final.state != "completed" or final.result is None or not final.result.project_id:
        raise ValueError(final.error.message if final.error is not None else f"import ended {final.state}")
    return str(final.result.project_id)


def _previous_apis(tenant_id: str, source_ref: str) -> Dict[str, Dict[str, Any]]:
    """The APIs the branch's last report imported, by entity ref, when their catalog item is live."""
    rows = db.execute_query(
        """
        SELECT elem->>'externalRef' AS external_ref, elem->>'entityId' AS entity_id, elem->>'digest' AS digest
          FROM apiome.catalog_import_runs r
         CROSS JOIN LATERAL jsonb_array_elements(r.entity_refs) elem
          JOIN apiome.projects p ON p.id = (elem->>'entityId')::uuid AND p.deleted_at IS NULL AND NOT p.publishable
         WHERE r.tenant_id = %s::uuid AND r.source_ref = %s AND elem ? 'digest'
        """,
        (tenant_id, source_ref),
    )
    return {str(row["external_ref"]): dict(row) for row in rows or []}


def record_backstage_catalog(
    tenant_id: str,
    repository_id: str,
    branch: str,
    files: Mapping[str, str],
    *,
    label: str,
    fetch_file: Callable[[str], str],
    actor_id: Optional[str] = None,
    importer: Optional[Callable[..., str]] = None,
) -> Optional[Dict[str, int]]:
    """Import and stage a repository branch's ``catalog-info`` files, never raising.

    ``kind: API`` entities with a definition are imported (an unchanged definition is skipped);
    everything else is staged on the branch's report. With no file left, the branch's report and its
    pending suggestions are removed (accepted components stay).

    Args:
        tenant_id: The repository's tenant.
        repository_id: The repository.
        branch: The scanned branch.
        files: Every ``catalog-info`` file on the branch, with its text.
        label: The report's label (``owner/repo · branch``).
        fetch_file: Reads another file of the branch (a ``$text`` definition).
        actor_id: Who registered the repository (the API import's user).
        importer: Replaces :func:`import_backstage_api` (tests).

    Returns:
        The report's counts, or ``None`` when there was nothing to do or it failed (logged).
    """
    source_ref = backstage_run_ref(repository_id, branch)
    try:
        if not files:
            db._guarded_tx(lambda cursor: _drop_run(cursor, tenant_id, source_ref))
            return None
        parsed = ParsedCatalog()
        for path, text in sorted(files.items()):
            parsed.extend(parse_backstage_file(path, text))
        imply_backstage_teams(parsed)

        previous = _previous_apis(tenant_id, source_ref)
        entity_refs: List[Dict[str, Any]] = []
        imported = 0
        for api in parsed.apis:
            try:
                text = api.definition if api.definition is not None else fetch_file(str(api.definition_path))
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                prior = previous.get(api.external_ref)
                if prior and prior.get("digest") == digest:
                    project_id = str(prior["entity_id"])
                else:
                    project_id = (importer or import_backstage_api)(
                        tenant_id,
                        repository_id,
                        branch,
                        api,
                        text,
                        existing_project_id=prior.get("entity_id") if prior else None,
                        actor_id=actor_id,
                    )
                imported += 1
                entity_refs.append(
                    {
                        "entityKind": "catalog_item",
                        "entityId": project_id,
                        "externalRef": api.external_ref,
                        "ownerRef": api.owner_ref,
                        "digest": digest,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - one bad definition must not stop the rest
                parsed.unmapped.append(
                    UnmappedField(api.external_ref, "spec.definition", f"not imported: {str(exc)[:160]}")
                )

        def work(cursor: Any) -> Dict[str, int]:
            run_id = stage_catalog(
                cursor,
                tenant_id,
                source=SOURCE_BACKSTAGE,
                source_ref=source_ref,
                label=label,
                parsed=parsed,
                repository_id=repository_id,
                branch=branch,
                files=len(files),
                entity_refs=entity_refs,
                apis_imported=imported,
            )
            cursor.execute("SELECT counts FROM apiome.catalog_import_runs WHERE id = %s::uuid", (run_id,))
            return dict(cursor.fetchone()["counts"])

        return db._guarded_tx(work)
    except Exception as exc:  # noqa: BLE001 - the import is advisory; never fail a finished scan
        _logger.warning(
            "Backstage catalog import skipped repository_id=%s branch=%s error=%s",
            repository_id,
            branch,
            f"{type(exc).__name__}: {exc}"[:300],
        )
        return None


def _drop_run(cursor: Any, tenant_id: str, source_ref: str) -> bool:
    """Remove a branch's report (its suggestions cascade; accepted components stay)."""
    cursor.execute(
        "DELETE FROM apiome.catalog_import_runs WHERE tenant_id = %s::uuid AND source_ref = %s", (tenant_id, source_ref)
    )
    return True


# ---------------------------------------------------------------------------------------------
# Compass (uploads)
# ---------------------------------------------------------------------------------------------


def import_compass_export(tenant_id: str, filename: str, raw: bytes, *, actor: ConsumerActor) -> MigrationRun:
    """Stage an uploaded Compass export as one report.

    Args:
        tenant_id: The tenant.
        filename: The uploaded file's name (the report's label).
        raw: The file's bytes.
        actor: Who uploaded it.

    Returns:
        The report, with its suggestions.

    Raises:
        MigrationError: ``migration-invalid`` / ``migration-too-large``.
    """
    try:
        parsed = parse_compass_export(raw)
    except CatalogParseError as exc:
        raise MigrationError(exc.code, str(exc)) from exc
    source_ref = f"compass:{uuid.uuid4()}"

    def work(cursor: Any) -> str:
        run_id = stage_catalog(
            cursor,
            tenant_id,
            source=SOURCE_COMPASS,
            source_ref=source_ref,
            label=filename.strip() or "Compass export",
            parsed=parsed,
            actor_id=actor.user_id,
            files=1,
        )
        db._append_access_audit(
            cursor,
            tenant_id=tenant_id,
            action="catalog.migration.import",
            actor_id=actor.user_id,
            actor_label=actor.label,
            target=f"catalog-migration:{run_id}",
            source="api_key" if actor.kind == "api_key" else "web",
            detail={
                "source": SOURCE_COMPASS,
                "filename": filename[:255],
                "components": len(parsed.components),
                "teams": len(parsed.teams),
                "unmapped": len(parsed.unmapped),
            },
        )
        return run_id

    return read_run(tenant_id, db._guarded_tx(work))


# ---------------------------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------------------------


def _suggestion(row: Mapping[str, Any]) -> MigrationSuggestion:
    """A suggestion row on the wire."""
    match = None
    if row.get("match_id"):
        match = {
            "kind": row["match_kind"],
            "id": row["match_id"],
            "name": row.get("match_name"),
            "slug": row.get("match_slug"),
        }
    entity = None
    if row.get("entity_id"):
        entity = {"kind": row["entity_kind"], "id": row["entity_id"], "slug": row.get("entity_slug")}
    return MigrationSuggestion(
        id=row["id"],
        kind=row["suggestion_kind"],
        source=row["source"],
        external_ref=row["external_ref"],
        name=row["name"],
        slug=row["slug"],
        status=row["status"],
        payload=dict(row.get("payload") or {}),
        match=match,
        entity=entity,
        decided_at=_iso(row.get("decided_at")),
    )


def _run(row: Mapping[str, Any], suggestions: Optional[List[MigrationSuggestion]] = None) -> MigrationRun:
    """A report row on the wire."""
    return MigrationRun(
        id=row["id"],
        source=row["source"],
        label=row["label"],
        repository_id=row.get("repository_id"),
        branch=row.get("branch"),
        counts={k: int(v) for k, v in dict(row.get("counts") or {}).items()},
        unmapped=[UnmappedFieldOut(**item) for item in row.get("unmapped") or []],
        unmapped_total=int(row.get("unmapped_total") or 0),
        pending=int(row.get("pending") or 0),
        suggestions=suggestions,
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
    )


def list_runs(tenant_id: str) -> List[MigrationRun]:
    """The tenant's import reports, most recently updated first (without their suggestions)."""
    rows = db.execute_query(
        f"SELECT {_RUN_COLUMNS} FROM apiome.catalog_import_runs r WHERE r.tenant_id = %s::uuid "
        f"ORDER BY r.updated_at DESC, r.id LIMIT {_RUN_LIST_LIMIT}",
        (tenant_id,),
    )
    return [_run(row) for row in rows or []]


def read_run(tenant_id: str, run_id: str) -> MigrationRun:
    """One import report with its suggestions (teams first, then components, by name).

    Raises:
        MigrationError: ``migration-not-found``.
    """
    if not is_uuid_string(run_id or ""):
        raise MigrationError(CODE_RUN_NOT_FOUND, "No such import report.")
    rows = db.execute_query(
        f"SELECT {_RUN_COLUMNS} FROM apiome.catalog_import_runs r WHERE r.tenant_id = %s::uuid AND r.id = %s::uuid",
        (tenant_id, run_id),
    )
    if not rows:
        raise MigrationError(CODE_RUN_NOT_FOUND, "No such import report.")
    suggestions = db.execute_query(
        f"SELECT {_SUGGESTION_COLUMNS} FROM apiome.catalog_import_suggestions s {_SUGGESTION_JOINS} "
        "WHERE s.tenant_id = %s::uuid AND s.run_id = %s::uuid "
        "ORDER BY CASE s.suggestion_kind WHEN 'team' THEN 0 ELSE 1 END, lower(s.name), s.id",
        (tenant_id, run_id),
    )
    return _run(rows[0], [_suggestion(row) for row in suggestions or []])


def read_component(tenant_id: str, slug: str) -> ComponentOut:
    """An accepted component by slug (or id, as a team page links it), with its owner.

    Raises:
        MigrationError: ``component-not-found``.
    """
    rows = db.execute_query(
        f"""
        SELECT c.id::text AS id, c.slug, c.name, c.description, c.category, c.component_type, c.lifecycle,
               c.parent_ref, c.links, c.source, c.external_ref, c.created_at, c.updated_at, own.entity_owner
          FROM apiome.catalog_components c
          {owner_envelope_join(("component",), "c.id", "c.tenant_id")}
         WHERE c.tenant_id = %s::uuid AND c.deleted_at IS NULL AND (c.slug = %s OR c.id::text = %s)
         ORDER BY (c.slug = %s) DESC
         LIMIT 1
        """,
        (tenant_id, str(slug or "").lower(), slug, str(slug or "").lower()),
    )
    if not rows:
        raise MigrationError(CODE_COMPONENT_NOT_FOUND, f"No component '{slug}'.")
    row = dict(rows[0])
    row["created_at"], row["updated_at"] = _iso(row.get("created_at")), _iso(row.get("updated_at"))
    row["links"] = list(row.get("links") or [])
    row["owner"] = owner_ref_from_value(row.pop("entity_owner", None))
    return ComponentOut(**row)


# ---------------------------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------------------------


def _locked_suggestion(cursor: Any, tenant_id: str, suggestion_id: str) -> Dict[str, Any]:
    """The suggestion, locked, still waiting for a decision."""
    if not is_uuid_string(suggestion_id or ""):
        raise MigrationError(CODE_SUGGESTION_NOT_FOUND, "No such suggestion.")
    cursor.execute(
        "SELECT id::text AS id, run_id::text AS run_id, source, suggestion_kind, external_ref, name, slug, payload, "
        "status, match_kind, match_id::text AS match_id FROM apiome.catalog_import_suggestions "
        "WHERE tenant_id = %s::uuid AND id = %s::uuid FOR UPDATE",
        (tenant_id, suggestion_id),
    )
    row = cursor.fetchone()
    if not row:
        raise MigrationError(CODE_SUGGESTION_NOT_FOUND, "No such suggestion.")
    if row["status"] != "suggested":
        raise MigrationError(CODE_DECIDED, f"This suggestion was already {row['status']}.")
    return dict(row)


def _decide(
    cursor: Any,
    tenant_id: str,
    row: Mapping[str, Any],
    status: str,
    actor: ConsumerActor,
    entity: Optional[Tuple[str, str]],
    detail: Mapping[str, Any],
) -> None:
    """Stamp a decision on a suggestion and audit it."""
    cursor.execute(
        """
        UPDATE apiome.catalog_import_suggestions
           SET status = %s, entity_kind = %s, entity_id = %s::uuid, decided_by = %s::uuid,
               decided_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
         WHERE id = %s::uuid
        """,
        (
            status,
            entity[0] if entity else None,
            entity[1] if entity else None,
            actor.user_id if is_uuid_string(actor.user_id or "") else None,
            row["id"],
        ),
    )
    db._append_access_audit(
        cursor,
        tenant_id=tenant_id,
        action=f"catalog.migration.{'accept' if status == 'accepted' else 'dismiss'}",
        actor_id=actor.user_id,
        actor_label=actor.label,
        target=f"catalog-migration-suggestion:{row['id']}",
        source="api_key" if actor.kind == "api_key" else "web",
        detail={
            "kind": row["suggestion_kind"],
            "source": row["source"],
            "externalRef": row["external_ref"],
            **({"entityKind": entity[0], "entityId": entity[1]} if entity else {}),
            **detail,
        },
    )


def _accept_team(
    cursor: Any, tenant_id: str, row: Mapping[str, Any], body: AcceptInput, actor: ConsumerActor
) -> Tuple[str, str]:
    """Create the team a suggestion describes (or link the live team that has its slug), then
    suggest it to every entity it owns."""
    payload = row.get("payload") or {}
    slug = (body.slug or row["slug"]).strip().lower()
    cursor.execute(
        "SELECT id::text AS id FROM apiome.teams WHERE tenant_id = %s::uuid AND slug = %s AND deleted_at IS NULL",
        (tenant_id, slug),
    )
    existing = cursor.fetchone()
    if existing:
        _decide(
            cursor, tenant_id, row, "accepted", actor, ("team", str(existing["id"])), {"slug": slug, "linked": True}
        )
        _apply_waiting_owners(cursor, tenant_id, row["source"], row["external_ref"])
        return ("team", str(existing["id"]))
    team = insert_team(
        cursor,
        tenant_id,
        TeamInput(
            name=body.name or row["name"],
            slug=slug,
            description=payload.get("description"),
            contact_email=payload.get("contactEmail"),
            chat_url=payload.get("chatUrl"),
            oncall_url=payload.get("oncallUrl"),
            docs_url=payload.get("docsUrl"),
        ),
        actor=actor,
    )
    # Stamp it first, so the owner lookups below find the new team through this suggestion.
    _decide(cursor, tenant_id, row, "accepted", actor, ("team", team.id), {"slug": team.slug})
    _apply_waiting_owners(cursor, tenant_id, row["source"], row["external_ref"])
    return ("team", team.id)


def _accept_component(
    cursor: Any, tenant_id: str, row: Mapping[str, Any], body: AcceptInput, actor: ConsumerActor
) -> Tuple[str, str]:
    """Apply a component to its match, or register it as a component of its own."""
    payload = row.get("payload") or {}
    references = _references(payload)
    source_ref = str(payload.get("sourceRef") or f"{row['source']}:{row['external_ref']}")[:600]
    if row.get("match_id") and not body.as_component:
        entity = (str(row["match_kind"]), str(row["match_id"]))
        if row["source"] == SOURCE_COMPASS:
            # Backstage declarations on the repository's APIs are written by every scan (CDG-3.2).
            replace_declared(cursor, tenant_id, entity[0], entity[1], source_ref, references)
        _apply_owner(cursor, tenant_id, row["source"], entity[0], entity[1], payload.get("ownerRef"))
        _decide(cursor, tenant_id, row, "accepted", actor, entity, {"appliedTo": "match"})
        return entity
    slug = (body.slug or row["slug"]).strip().lower()
    cursor.execute(
        """
        INSERT INTO apiome.catalog_components
            (tenant_id, slug, name, description, category, component_type, lifecycle, parent_ref, links, source,
             source_ref, external_ref, created_by)
        VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s::uuid)
        RETURNING id::text AS id
        """,
        (
            tenant_id,
            slug,
            (body.name or row["name"]).strip(),
            payload.get("description"),
            payload.get("category") or "component",
            payload.get("componentType"),
            payload.get("lifecycle"),
            payload.get("parentRef"),
            json.dumps(payload.get("links") or []),
            row["source"],
            source_ref,
            row["external_ref"],
            actor.user_id if is_uuid_string(actor.user_id or "") else None,
        ),
    )
    component_id = str(cursor.fetchone()["id"])
    replace_declared(cursor, tenant_id, "component", component_id, source_ref, references)
    _apply_owner(cursor, tenant_id, row["source"], "component", component_id, payload.get("ownerRef"))
    promoted = promote_unresolved(cursor, tenant_id, "component", component_id, slug)
    _decide(
        cursor, tenant_id, row, "accepted", actor, ("component", component_id), {"slug": slug, "resolved": promoted}
    )
    return ("component", component_id)


def accept_suggestion(
    tenant_id: str, suggestion_id: str, body: AcceptInput, *, actor: ConsumerActor
) -> MigrationSuggestion:
    """Accept a suggestion: create the team, register the component, or apply it to its match.

    Args:
        tenant_id: The tenant.
        suggestion_id: The suggestion.
        body: Name and slug overrides; ``as_component`` for a matched component.
        actor: Who accepted it.

    Returns:
        The decided suggestion.

    Raises:
        MigrationError: ``migration-suggestion-not-found``, ``migration-suggestion-decided``,
            ``migration-slug-taken`` (another team or component has the slug) or ``migration-invalid``.
    """

    def work(cursor: Any) -> str:
        row = _locked_suggestion(cursor, tenant_id, suggestion_id)
        if row["suggestion_kind"] == "team":
            _accept_team(cursor, tenant_id, row, body, actor)
        else:
            _accept_component(cursor, tenant_id, row, body, actor)
        return row["id"]

    try:
        decided = db._guarded_tx(work)
    except psycopg2.errors.UniqueViolation as exc:
        raise MigrationError(
            CODE_SLUG_TAKEN, "Another team or component already has that slug; choose another."
        ) from exc
    except psycopg2.errors.CheckViolation as exc:
        raise MigrationError(CODE_INVALID, "That name or slug is not valid.") from exc
    except TeamValidationError as exc:
        raise MigrationError(CODE_INVALID, str(exc)) from exc
    return read_suggestion(tenant_id, decided)


def dismiss_suggestion(tenant_id: str, suggestion_id: str, *, actor: ConsumerActor) -> MigrationSuggestion:
    """Dismiss a suggestion; later runs keep it dismissed.

    Raises:
        MigrationError: ``migration-suggestion-not-found`` or ``migration-suggestion-decided``.
    """

    def work(cursor: Any) -> str:
        row = _locked_suggestion(cursor, tenant_id, suggestion_id)
        _decide(cursor, tenant_id, row, "dismissed", actor, None, {})
        return row["id"]

    return read_suggestion(tenant_id, db._guarded_tx(work))


def read_suggestion(tenant_id: str, suggestion_id: str) -> MigrationSuggestion:
    """One suggestion as it is now."""
    rows = db.execute_query(
        f"SELECT {_SUGGESTION_COLUMNS} FROM apiome.catalog_import_suggestions s {_SUGGESTION_JOINS} "
        "WHERE s.tenant_id = %s::uuid AND s.id = %s::uuid",
        (tenant_id, suggestion_id),
    )
    if not rows:
        raise MigrationError(CODE_SUGGESTION_NOT_FOUND, "No such suggestion.")
    return _suggestion(rows[0])
