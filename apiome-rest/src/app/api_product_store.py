"""Persistence for API products and their members — APX-1.1 (#6098).

:mod:`app.api_products` says what a product *is*; this module is the only place one is read or
written, so the rules below are applied once rather than at each route.

**Every write is one transaction** that also:

* appends an ``api_product.*`` row to the tenant's hash-chained ``access_audit`` ledger
  (:meth:`Database._append_access_audit`) — ``create``, ``update``, ``delete``, ``member.add`` and
  ``member.remove`` — so a product never changes without the row that says who changed it;
* re-derives the graph's ``includes`` family (:meth:`Database._materialize_graph`, under a
  savepoint, so a graph fault never fails the write — the nightly sweep repairs it), so the
  dependency graph and the blast radius see the product's members the moment they change;
* re-checks the **portal rule** when it makes the product ``portal`` or adds members: a ``portal``
  product whose members are not all published is refused (``api-product-portal-unpublished``, with
  the blockers) and nothing is written. Reads report the rule as ``portal_ready``.

**Members resolve at read time.** A ``project_latest`` member stores only the Project; which version
it means is read from ``versions`` on every read (:func:`app.api_products.pick_version`), so the
product follows each new publish with no write.

**A delete is soft**, freeing the slug; the product's ``includes`` edges turn stale and drop out of
the blast radius.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence

import psycopg2

from .api_products import (
    CODE_INVALID,
    CODE_MEMBER_DUPLICATE,
    CODE_MEMBER_NOT_FOUND,
    CODE_MEMBER_REF_NOT_FOUND,
    CODE_NOT_FOUND,
    CODE_PORTAL_UNPUBLISHED,
    CODE_SLUG_TAKEN,
    CODE_TEAM_NOT_FOUND,
    MAX_MEMBERS,
    PROJECT_MEMBER_KINDS,
    ApiProductInput,
    ApiProductMember,
    ApiProductMemberInput,
    ApiProductPatch,
    ApiProductRecord,
    ApiProductValidationError,
    MemberVersion,
    OwnerTeam,
    normalize_environment,
    normalize_name,
    normalize_selector,
    pick_version,
    portal_blockers,
    resolve_slug,
)
from .consumer_contract_store import ConsumerActor
from .database import db
from .revision_deprecation import is_uuid_string

__all__ = [
    "add_member",
    "create_product",
    "delete_product",
    "get_product",
    "list_members",
    "list_products",
    "remove_member",
    "update_product",
]

#: The graph family a product write re-derives.
_GRAPH_FAMILY = "includes"

#: The unique index whose violation means "slug taken" (V387); the member identity key means "duplicate".
_SLUG_INDEX = "idx_api_products_tenant_slug"
_MEMBER_KEY = "api_product_members_identity_key"

#: The product columns every read selects, with the owner team and live member count beside them.
_PRODUCT_COLUMNS = """
    ap.id::text AS id, ap.slug, ap.name, ap.summary, ap.visibility, ap.state,
    ap.created_by::text AS created_by, ap.created_at, ap.updated_at,
    t.slug AS team_slug, t.name AS team_name,
    (SELECT count(*) FROM apiome.api_product_members m WHERE m.product_id = ap.id)::int AS member_count
"""

_PRODUCT_FROM = """
    FROM apiome.api_products ap
    LEFT JOIN apiome.teams t ON t.id = ap.owner_team_id AND t.deleted_at IS NULL
"""


def _iso(value: Any) -> Optional[str]:
    """Render a timestamp as ISO-8601, passing ``None`` and strings through.

    Args:
        value: A ``datetime``, a string, or ``None``.

    Returns:
        The ISO string, or ``None``.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else None


def _rows(cursor: Any, sql: str, params: Sequence[Any]) -> List[Dict[str, Any]]:
    """Run one statement on ``cursor`` and return its rows as dicts.

    Args:
        cursor: An open cursor.
        sql: The statement.
        params: Its parameters.

    Returns:
        The rows (empty for a statement that returns none).
    """
    cursor.execute(sql, tuple(params))
    return [dict(row) for row in (cursor.fetchall() or [])]


def _record(row: Dict[str, Any], members: Optional[List[ApiProductMember]] = None) -> ApiProductRecord:
    """Build an :class:`ApiProductRecord` from a product row.

    Args:
        row: A row selected with ``_PRODUCT_COLUMNS``.
        members: The resolved members, for a read that includes them.

    Returns:
        The record; ``portal_ready`` is set when ``members`` is.
    """
    team = OwnerTeam(slug=row["team_slug"], name=row["team_name"]) if row.get("team_slug") else None
    return ApiProductRecord(
        id=str(row["id"]),
        slug=row["slug"],
        name=row["name"],
        summary=row.get("summary"),
        owner_team=team,
        visibility=row["visibility"],
        state=row["state"],
        member_count=int(row.get("member_count") or 0),
        created_by=row.get("created_by"),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
        members=members,
        portal_ready=None if members is None else not portal_blockers(members),
    )


def _audit(
    cursor: Any, tenant_id: str, actor: ConsumerActor, action: str, slug: str, detail: Dict[str, Any]
) -> None:
    """Append an ``api_product.*`` row to the tenant's access audit inside the open transaction.

    Args:
        cursor: The transaction's cursor.
        tenant_id: The tenant whose chain the row extends.
        actor: Who acted.
        action: ``api_product.create``, ``.update``, ``.delete``, ``.member.add`` or ``.member.remove``.
        slug: The product's slug (the audit *target*).
        detail: Structured context.
    """
    db._append_access_audit(
        cursor,
        tenant_id=tenant_id,
        action=action,
        actor_id=actor.user_id,
        actor_label=actor.label,
        target=f"api_product:{slug}",
        source="api_key" if actor.kind == "api_key" else "web",
        detail=detail,
    )


def _run(work: Callable[[Any], Any]) -> Any:
    """Run ``work`` in one transaction, translating a unique violation into a refusal.

    Args:
        work: A callable taking the cursor; whatever it returns is committed.

    Returns:
        Whatever ``work`` returned.

    Raises:
        ApiProductValidationError: ``api-product-slug-taken`` or ``api-product-member-duplicate``
            when V387's unique keys refused a write, plus whatever ``work`` raised (everything it
            wrote is rolled back).
    """
    try:
        return db._guarded_tx(work)
    except psycopg2.errors.UniqueViolation as exc:
        constraint = getattr(getattr(exc, "diag", None), "constraint_name", None) or ""
        if constraint == _MEMBER_KEY:
            raise ApiProductValidationError(
                CODE_MEMBER_DUPLICATE, "the product already includes that member"
            ) from exc
        raise ApiProductValidationError(
            CODE_SLUG_TAKEN, "another product in this tenant already has that slug"
        ) from exc


def _not_found(slug: str) -> ApiProductValidationError:
    """The refusal for an unknown product slug."""
    return ApiProductValidationError(CODE_NOT_FOUND, f"no product '{slug}' in this tenant")


def _select_product(cursor: Any, tenant_id: str, slug: str, *, lock: bool) -> Dict[str, Any]:
    """Select a live product by slug, optionally locking it for the open transaction.

    Args:
        cursor: The transaction's cursor.
        tenant_id: The caller's tenant.
        slug: The product's slug.
        lock: True to take ``FOR UPDATE`` on the product row.

    Returns:
        The product row.

    Raises:
        ApiProductValidationError: ``api-product-not-found`` when no live product has that slug.
    """
    if not is_uuid_string(tenant_id):
        raise _not_found(slug)
    rows = _rows(
        cursor,
        f"""
        SELECT {_PRODUCT_COLUMNS}
        {_PRODUCT_FROM}
        WHERE ap.tenant_id = %s::uuid AND ap.slug = %s AND ap.deleted_at IS NULL
        {"FOR UPDATE OF ap" if lock else ""}
        """,
        (tenant_id, (slug or "").strip().lower()),
    )
    if not rows:
        raise _not_found(slug)
    return rows[0]


def _owner_team_id(cursor: Any, tenant_id: str, team_slug: Optional[str]) -> Optional[str]:
    """Resolve an owner team slug to its id (``None`` for no owner).

    Args:
        cursor: The transaction's cursor.
        tenant_id: The caller's tenant.
        team_slug: The team's slug, or empty for no owner.

    Returns:
        The team id, or ``None``.

    Raises:
        ApiProductValidationError: ``api-product-team-not-found`` when no live team has the slug.
    """
    wanted = (team_slug or "").strip().lower()
    if not wanted:
        return None
    rows = _rows(
        cursor,
        "SELECT id::text AS id FROM apiome.teams WHERE tenant_id = %s::uuid AND slug = %s AND deleted_at IS NULL",
        (tenant_id, wanted),
    )
    if not rows:
        raise ApiProductValidationError(CODE_TEAM_NOT_FOUND, f"no team '{wanted}' in this tenant")
    return str(rows[0]["id"])


def _member_ref_id(cursor: Any, tenant_id: str, kind: str, ref: str) -> str:
    """Resolve a member's ``ref`` (id or slug) to the id of a live entity of its kind.

    ``project_latest`` / ``project_version`` need a publishable Project, ``catalog_item`` a catalog
    item (a non-publishable ``projects`` row) and ``mcp_server`` an MCP server.

    Args:
        cursor: The transaction's cursor.
        tenant_id: The caller's tenant.
        kind: The member kind.
        ref: The member's id or slug.

    Returns:
        The entity id.

    Raises:
        ApiProductValidationError: ``api-product-member-ref-not-found`` when nothing matches.
    """
    value = (ref or "").strip()
    by_id = is_uuid_string(value)
    if kind == "mcp_server":
        table, extra = "apiome.mcp_endpoints", ""
    else:
        table = "apiome.projects"
        extra = " AND publishable" if kind in PROJECT_MEMBER_KINDS else " AND NOT publishable"
    match = "id = %s::uuid" if by_id else "lower(slug) = %s"
    rows = _rows(
        cursor,
        f"SELECT id::text AS id FROM {table} WHERE tenant_id = %s::uuid AND {match} AND deleted_at IS NULL{extra}",
        (tenant_id, value if by_id else value.lower()),
    )
    if not rows:
        noun = {"mcp_server": "MCP server", "catalog_item": "catalog item"}.get(kind, "project")
        raise ApiProductValidationError(CODE_MEMBER_REF_NOT_FOUND, f"no {noun} '{value}' in this tenant")
    return str(rows[0]["id"])


def _read_members(cursor: Any, tenant_id: str, product_id: str) -> List[ApiProductMember]:
    """A product's members, each resolved to its entity and (for a Project) its version today.

    Two statements: the members with their entities' names, then the versions of every Project
    they name, newest publish first.

    Args:
        cursor: An open cursor.
        tenant_id: The caller's tenant.
        product_id: The product.

    Returns:
        The members, Project members first by name, then the rest.
    """
    rows = _rows(
        cursor,
        """
        SELECT m.id::text AS id, m.member_kind AS kind, m.member_ref::text AS ref, m.version_selector,
               m.environment, m.created_at,
               COALESCE(p.name, e.name) AS name, COALESCE(p.slug, e.slug) AS slug,
               (p.id IS NOT NULL OR e.id IS NOT NULL) AS present, COALESCE(e.published, FALSE) AS mcp_published
        FROM apiome.api_product_members m
        LEFT JOIN apiome.projects p
               ON m.member_kind <> 'mcp_server' AND p.id = m.member_ref AND p.tenant_id = m.tenant_id
              AND p.deleted_at IS NULL
        LEFT JOIN apiome.mcp_endpoints e
               ON m.member_kind = 'mcp_server' AND e.id = m.member_ref AND e.tenant_id = m.tenant_id
              AND e.deleted_at IS NULL
        WHERE m.tenant_id = %s::uuid AND m.product_id = %s::uuid
        ORDER BY (m.member_kind = 'mcp_server'), lower(COALESCE(p.name, e.name, '')), m.created_at, m.id
        """,
        (tenant_id, product_id),
    )
    project_ids = sorted({row["ref"] for row in rows if row["kind"] != "mcp_server" and row["present"]})
    versions: Dict[str, List[Dict[str, Any]]] = {}
    if project_ids:
        for version in _rows(
            cursor,
            """
            SELECT v.id::text AS id, v.project_id::text AS project_id, v.version_id AS label, v.published
            FROM apiome.versions v
            WHERE v.project_id = ANY(%s::uuid[]) AND v.deleted_at IS NULL
            ORDER BY v.project_id, v.published DESC, COALESCE(v.published_at, v.created_at) DESC,
                     v.created_at DESC
            """,
            (project_ids,),
        ):
            versions.setdefault(version["project_id"], []).append(version)

    members: List[ApiProductMember] = []
    for row in rows:
        resolved: Optional[MemberVersion] = None
        if row["kind"] == "mcp_server":
            published = bool(row["present"] and row["mcp_published"])
        else:
            chosen = pick_version(row["kind"], row.get("version_selector"), versions.get(row["ref"], []))
            if chosen:
                resolved = MemberVersion(id=chosen["id"], label=chosen.get("label"), published=bool(chosen.get("published")))
            published = bool(resolved and resolved.published)
        members.append(
            ApiProductMember(
                id=row["id"],
                kind=row["kind"],
                ref=row["ref"],
                slug=row.get("slug"),
                name=row.get("name"),
                version_selector=row.get("version_selector"),
                environment=row.get("environment"),
                resolved_version=resolved,
                published=published,
                missing=not row["present"],
                created_at=_iso(row.get("created_at")),
            )
        )
    return members


def _check_portal(visibility: str, members: List[ApiProductMember]) -> None:
    """Refuse a ``portal`` product that has an unpublished member.

    Args:
        visibility: The product's visibility after the write.
        members: Its members after the write.

    Raises:
        ApiProductValidationError: ``api-product-portal-unpublished``, with the blockers.
    """
    if visibility != "portal":
        return
    blockers = portal_blockers(members)
    if blockers:
        names = ", ".join(str(b["name"] or b["ref"]) for b in blockers[:5])
        raise ApiProductValidationError(
            CODE_PORTAL_UNPUBLISHED,
            f"a portal product needs every member published; not published: {names}",
            blockers=blockers,
        )


def _insert_member(
    cursor: Any, tenant_id: str, product_id: str, body: ApiProductMemberInput, actor: ConsumerActor
) -> Dict[str, Any]:
    """Validate and insert one member on the open transaction.

    Args:
        cursor: The transaction's cursor.
        tenant_id: The caller's tenant.
        product_id: The product.
        body: The member.
        actor: Who is adding it.

    Returns:
        The audit detail of the stored member (``{id, kind, ref, version_selector, environment}``).

    Raises:
        ApiProductValidationError: ``api-product-invalid`` for a bad selector or environment,
            ``api-product-member-ref-not-found`` for an unknown ref.
    """
    selector = normalize_selector(body.kind, body.version)
    environment = normalize_environment(body.environment)
    ref_id = _member_ref_id(cursor, tenant_id, body.kind, body.ref)
    inserted = _rows(
        cursor,
        """
        INSERT INTO apiome.api_product_members
            (tenant_id, product_id, member_kind, member_ref, version_selector, environment, created_by)
        VALUES (%s::uuid, %s::uuid, %s, %s::uuid, %s, %s, %s::uuid)
        RETURNING id::text AS id
        """,
        (tenant_id, product_id, body.kind, ref_id, selector, environment,
         actor.user_id if is_uuid_string(actor.user_id or "") else None),
    )
    return {"id": inserted[0]["id"], "kind": body.kind, "ref": ref_id,
            "version_selector": selector, "environment": environment}


def _touch(cursor: Any, product_id: str) -> None:
    """Stamp a product's ``updated_at`` (a member change is a change to the product)."""
    cursor.execute(
        "UPDATE apiome.api_products SET updated_at = CURRENT_TIMESTAMP WHERE id = %s::uuid", (product_id,)
    )


def _finish(cursor: Any, tenant_id: str, slug: str, *, check_portal: bool) -> ApiProductRecord:
    """Re-read a product with its members after a write, and re-derive its graph edges.

    Args:
        cursor: The transaction's cursor.
        tenant_id: The caller's tenant.
        slug: The product's slug.
        check_portal: True when the write could break the portal rule — it made the product
            ``portal`` or added members. An unrelated edit is not refused because a member was
            unpublished elsewhere since; ``portal_ready`` reports that instead.

    Returns:
        The product as stored.

    Raises:
        ApiProductValidationError: ``api-product-portal-unpublished`` (rolling the write back).
    """
    row = _select_product(cursor, tenant_id, slug, lock=False)
    members = _read_members(cursor, tenant_id, row["id"])
    if check_portal:
        _check_portal(row["visibility"], members)
    db._materialize_graph(cursor, tenant_id, (_GRAPH_FAMILY,))
    return _record(row, members)


# ---------------------------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------------------------


def list_products(tenant_id: str) -> List[ApiProductRecord]:
    """Every live product of the tenant, by name.

    Args:
        tenant_id: The caller's tenant.

    Returns:
        The products with their owner teams and member counts (no member lists); empty for a
        non-UUID tenant.
    """
    if not is_uuid_string(tenant_id):
        return []
    rows = db.execute_query(
        f"""
        SELECT {_PRODUCT_COLUMNS}
        {_PRODUCT_FROM}
        WHERE ap.tenant_id = %s::uuid AND ap.deleted_at IS NULL
        ORDER BY lower(ap.name), ap.slug
        """,
        (tenant_id,),
    )
    return [_record(dict(row)) for row in rows]


def get_product(tenant_id: str, slug: str) -> ApiProductRecord:
    """One live product with its resolved members.

    Args:
        tenant_id: The caller's tenant.
        slug: The product's slug.

    Returns:
        The product, members and ``portal_ready`` included.

    Raises:
        ApiProductValidationError: ``api-product-not-found`` when no live product has that slug.
    """

    def work(cursor: Any) -> ApiProductRecord:
        row = _select_product(cursor, tenant_id, slug, lock=False)
        return _record(row, _read_members(cursor, tenant_id, row["id"]))

    return db._guarded_tx(work)


def list_members(tenant_id: str, slug: str) -> List[ApiProductMember]:
    """A live product's resolved members.

    Args:
        tenant_id: The caller's tenant.
        slug: The product's slug.

    Returns:
        The members.

    Raises:
        ApiProductValidationError: ``api-product-not-found``.
    """
    return list(get_product(tenant_id, slug).members or [])


# ---------------------------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------------------------


def create_product(tenant_id: str, body: ApiProductInput, *, actor: ConsumerActor) -> ApiProductRecord:
    """Create a product (and any members it was sent with), audited as ``api_product.create``.

    Args:
        tenant_id: The caller's tenant.
        body: The product to create.
        actor: Who is creating it.

    Returns:
        The stored product, members resolved.

    Raises:
        ApiProductValidationError: ``api-product-invalid`` for a malformed field,
            ``api-product-slug-taken``, ``api-product-team-not-found``,
            ``api-product-member-ref-not-found``, ``api-product-member-duplicate`` or
            ``api-product-portal-unpublished``.
    """
    if not is_uuid_string(tenant_id):
        raise ApiProductValidationError(CODE_INVALID, "no tenant context")
    name = normalize_name(body.name)
    slug = resolve_slug(body.slug, name)
    summary = (body.summary or "").strip() or None

    def work(cursor: Any) -> ApiProductRecord:
        team_id = _owner_team_id(cursor, tenant_id, body.owner_team)
        product_id = _rows(
            cursor,
            """
            INSERT INTO apiome.api_products
                (tenant_id, slug, name, summary, owner_team_id, visibility, state, created_by)
            VALUES (%s::uuid, %s, %s, %s, %s::uuid, %s, %s, %s::uuid)
            RETURNING id::text AS id
            """,
            (tenant_id, slug, name, summary, team_id, body.visibility, body.state,
             actor.user_id if is_uuid_string(actor.user_id or "") else None),
        )[0]["id"]
        members = [_insert_member(cursor, tenant_id, product_id, member, actor) for member in body.members]
        _audit(cursor, tenant_id, actor, "api_product.create", slug, {
            "product_id": product_id, "name": name, "summary": summary, "owner_team": body.owner_team,
            "visibility": body.visibility, "state": body.state, "members": members,
        })
        return _finish(cursor, tenant_id, slug, check_portal=True)

    return _run(work)


def update_product(tenant_id: str, slug: str, patch: ApiProductPatch, *, actor: ConsumerActor) -> ApiProductRecord:
    """Apply a partial update, audited as ``api_product.update`` with the fields that changed.

    Args:
        tenant_id: The caller's tenant.
        slug: The product's slug.
        patch: The fields to change; ``null`` clears ``summary`` or ``owner_team``.
        actor: Who is changing it.

    Returns:
        The stored product, members resolved.

    Raises:
        ApiProductValidationError: ``api-product-not-found``, ``api-product-invalid``,
            ``api-product-team-not-found`` or ``api-product-portal-unpublished`` (when the patch
            sets ``portal`` and a member is not published).
    """
    sent = patch.model_fields_set

    def work(cursor: Any) -> ApiProductRecord:
        row = _select_product(cursor, tenant_id, slug, lock=True)
        changes: Dict[str, Any] = {}
        if "name" in sent and patch.name is not None:
            changes["name"] = normalize_name(patch.name)
        if "summary" in sent:
            changes["summary"] = (patch.summary or "").strip() or None
        if "owner_team" in sent:
            changes["owner_team_id"] = _owner_team_id(cursor, tenant_id, patch.owner_team)
        if "visibility" in sent and patch.visibility is not None:
            changes["visibility"] = patch.visibility
        if "state" in sent and patch.state is not None:
            changes["state"] = patch.state
        if changes:
            assignments = ", ".join(
                f"{column} = %s::uuid" if column == "owner_team_id" else f"{column} = %s" for column in changes
            )
            cursor.execute(
                f"UPDATE apiome.api_products SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = %s::uuid",
                (*changes.values(), row["id"]),
            )
            detail = {k: v for k, v in changes.items() if k != "owner_team_id"}
            if "owner_team_id" in changes:
                detail["owner_team"] = (patch.owner_team or "").strip().lower() or None
            _audit(cursor, tenant_id, actor, "api_product.update", row["slug"], {"product_id": row["id"], **detail})
        return _finish(cursor, tenant_id, row["slug"], check_portal=changes.get("visibility") == "portal")

    return _run(work)


def delete_product(tenant_id: str, slug: str, *, actor: ConsumerActor) -> str:
    """Soft-delete a product, audited as ``api_product.delete``. Its slug is free again.

    Args:
        tenant_id: The caller's tenant.
        slug: The product's slug.
        actor: Who is deleting it.

    Returns:
        The deleted product's slug.

    Raises:
        ApiProductValidationError: ``api-product-not-found``.
    """

    def work(cursor: Any) -> str:
        row = _select_product(cursor, tenant_id, slug, lock=True)
        cursor.execute(
            "UPDATE apiome.api_products SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = %s::uuid",
            (row["id"],),
        )
        _audit(cursor, tenant_id, actor, "api_product.delete", row["slug"], {
            "product_id": row["id"], "member_count": int(row.get("member_count") or 0),
        })
        db._materialize_graph(cursor, tenant_id, (_GRAPH_FAMILY,))
        return str(row["slug"])

    return _run(work)


def add_member(
    tenant_id: str, slug: str, body: ApiProductMemberInput, *, actor: ConsumerActor
) -> ApiProductRecord:
    """Add one member, audited as ``api_product.member.add``.

    Args:
        tenant_id: The caller's tenant.
        slug: The product's slug.
        body: The member.
        actor: Who is adding it.

    Returns:
        The product with its members after the add.

    Raises:
        ApiProductValidationError: ``api-product-not-found``, ``api-product-invalid`` (bad
            selector or environment, or the product is full), ``api-product-member-ref-not-found``,
            ``api-product-member-duplicate`` or ``api-product-portal-unpublished``.
    """

    def work(cursor: Any) -> ApiProductRecord:
        row = _select_product(cursor, tenant_id, slug, lock=True)
        if int(row.get("member_count") or 0) >= MAX_MEMBERS:
            raise ApiProductValidationError(CODE_INVALID, f"a product has at most {MAX_MEMBERS} members")
        member = _insert_member(cursor, tenant_id, row["id"], body, actor)
        _touch(cursor, row["id"])
        _audit(cursor, tenant_id, actor, "api_product.member.add", row["slug"], {"product_id": row["id"], **member})
        return _finish(cursor, tenant_id, row["slug"], check_portal=True)

    return _run(work)


def remove_member(tenant_id: str, slug: str, member_id: str, *, actor: ConsumerActor) -> ApiProductRecord:
    """Remove one member, audited as ``api_product.member.remove``.

    Removing a member can only make a ``portal`` product more publishable, so the portal rule is
    not checked.

    Args:
        tenant_id: The caller's tenant.
        slug: The product's slug.
        member_id: The member row's id.
        actor: Who is removing it.

    Returns:
        The product with its members after the removal.

    Raises:
        ApiProductValidationError: ``api-product-not-found`` or ``api-product-member-not-found``.
    """

    def work(cursor: Any) -> ApiProductRecord:
        row = _select_product(cursor, tenant_id, slug, lock=True)
        if not is_uuid_string(member_id or ""):
            raise ApiProductValidationError(CODE_MEMBER_NOT_FOUND, f"no member '{member_id}' in this product")
        removed = _rows(
            cursor,
            """
            DELETE FROM apiome.api_product_members
            WHERE id = %s::uuid AND product_id = %s::uuid AND tenant_id = %s::uuid
            RETURNING member_kind AS kind, member_ref::text AS ref, version_selector, environment
            """,
            (member_id, row["id"], tenant_id),
        )
        if not removed:
            raise ApiProductValidationError(CODE_MEMBER_NOT_FOUND, f"no member '{member_id}' in this product")
        _touch(cursor, row["id"])
        _audit(cursor, tenant_id, actor, "api_product.member.remove", row["slug"], {
            "product_id": row["id"], "id": member_id, **removed[0],
        })
        return _finish(cursor, tenant_id, row["slug"], check_portal=False)

    return _run(work)
