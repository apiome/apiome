"""Persistence for API plans — APX-1.2 (#6099).

:mod:`app.api_plans` says what a plan *is*; this module is the only place one is read or written.
A plan belongs to one live API product (:mod:`app.api_product_store`) and is addressed by the
product's slug and its own.

**Every write is one transaction** that locks the product, appends an ``api_product.plan.*`` row
(``create``, ``update``, ``delete``) to the tenant's hash-chained ``access_audit`` ledger and
re-derives ``declared_only`` from the plan's environments, so the provisioner (APX-4.x) can select
the plans it owns.

**Reads explain the plan.** Each plan comes back with its environments resolved to gateway configs
(and whether each can provision), the ``api-plan-declared-only`` notice when nothing can be
provisioned, and one ``api-plan-auth-mismatch`` warning per member whose resolved version declares
no security scheme the plan's auth strategy can use. Members resolve at read time, so the warnings
follow every publish.

**Export.** :func:`plans_for_revision` returns the ``x-apiome-plans`` entries of every product that
includes a revision, for :func:`app.export_source.load_export_source`.

**A delete is soft**, freeing the slug.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import psycopg2
from psycopg2.extras import Json

from .api_plans import (
    CODE_ENVIRONMENT_NOT_FOUND,
    CODE_INVALID,
    CODE_NOT_FOUND,
    CODE_SLUG_TAKEN,
    MAX_PLANS,
    ApiPlanInput,
    ApiPlanPatch,
    ApiPlanRecord,
    ApiPlanValidationError,
    PlanAuthConfig,
    PlanEnvironment,
    PlanLimit,
    auth_mismatch_warnings,
    connector_can_provision,
    declared_only_notice,
    is_declared_only,
    normalize_auth_config,
    normalize_limits,
    normalize_plan_name,
    normalize_terms_url,
    plan_extension_entry,
    resolve_plan_slug,
)
from .api_product_store import _audit, _iso, _read_members, _rows, _select_product, _touch
from .api_products import ApiProductMember
from .consumer_contract_store import ConsumerActor
from .database import db
from .revision_deprecation import is_uuid_string

__all__ = [
    "create_plan",
    "delete_plan",
    "get_plan",
    "list_plans",
    "plans_for_revision",
    "update_plan",
]

#: The plan columns every read selects.
_PLAN_COLUMNS = """
    pl.id::text AS id, pl.slug, pl.name, pl.description, pl.auth_strategy, pl.auth_config, pl.limits,
    pl.concurrency, pl.approval, pl.environments::text[] AS environments, pl.credential_ttl_days,
    pl.terms_url, pl.pricing_note, pl.billing_ref, pl.state,
    pl.created_by::text AS created_by, pl.created_at, pl.updated_at
"""


def _run(work: Callable[[Any], Any]) -> Any:
    """Run ``work`` in one transaction, translating a slug collision into a refusal.

    Args:
        work: A callable taking the cursor; whatever it returns is committed.

    Returns:
        Whatever ``work`` returned.

    Raises:
        ApiPlanValidationError: ``api-plan-slug-taken`` when V388's unique index refused the write,
            plus whatever ``work`` raised (everything it wrote is rolled back).
    """
    try:
        return db._guarded_tx(work)
    except psycopg2.errors.UniqueViolation as exc:
        raise ApiPlanValidationError(CODE_SLUG_TAKEN, "another plan of this product already has that slug") from exc


def _optional_text(value: Optional[str]) -> Optional[str]:
    """Trim a free-text field, mapping blank to ``None``."""
    return (value or "").strip() or None


def _resolve_environments(cursor: Any, tenant_id: str, refs: Sequence[str]) -> List[str]:
    """Resolve gateway config slugs or ids to the ids of live gateway configs, in order, once each.

    Args:
        cursor: The transaction's cursor.
        tenant_id: The caller's tenant.
        refs: Gateway config slugs or ids.

    Returns:
        The ids.

    Raises:
        ApiPlanValidationError: ``api-plan-environment-not-found`` naming the first unknown ref.
    """
    wanted = [ref.strip() for ref in refs if ref and ref.strip()]
    if not wanted:
        return []
    rows = _rows(
        cursor,
        """
        SELECT g.id::text AS id, g.slug
        FROM apiome.catalog_gateway_configs g
        WHERE g.tenant_id = %s::uuid AND g.deleted_at IS NULL
          AND (g.slug = ANY(%s::text[]) OR g.id::text = ANY(%s::text[]))
        """,
        (tenant_id, [ref.lower() for ref in wanted], [ref.lower() for ref in wanted]),
    )
    by_ref: Dict[str, str] = {}
    for row in rows:
        by_ref[row["slug"]] = row["id"]
        by_ref[row["id"]] = row["id"]
    ids: List[str] = []
    for ref in wanted:
        found = by_ref.get(ref.lower())
        if found is None:
            raise ApiPlanValidationError(CODE_ENVIRONMENT_NOT_FOUND, f"no gateway config '{ref}' in this tenant")
        if found not in ids:
            ids.append(found)
    return ids


def _read_environments(cursor: Any, tenant_id: str, ids: Sequence[str]) -> Dict[str, PlanEnvironment]:
    """Resolve gateway config ids to :class:`PlanEnvironment` (a deleted one reads back as missing).

    Args:
        cursor: An open cursor.
        tenant_id: The caller's tenant.
        ids: Gateway config ids.

    Returns:
        ``{id: environment}`` for every id asked for.
    """
    unique = sorted({str(i) for i in ids})
    found: Dict[str, PlanEnvironment] = {}
    if unique:
        for row in _rows(
            cursor,
            """
            SELECT g.id::text AS id, g.slug, g.name, g.environment, c.kind AS connector_kind
            FROM apiome.catalog_gateway_configs g
            JOIN apiome.catalog_connectors c ON c.id = g.connector_id AND c.deleted_at IS NULL
            WHERE g.tenant_id = %s::uuid AND g.deleted_at IS NULL AND g.id = ANY(%s::uuid[])
            """,
            (tenant_id, unique),
        ):
            found[row["id"]] = PlanEnvironment(
                id=row["id"],
                slug=row["slug"],
                name=row.get("name"),
                environment=row.get("environment") or None,
                connector_kind=row.get("connector_kind"),
                can_provision=connector_can_provision(row.get("connector_kind")),
            )
    return {
        i: found.get(i) or PlanEnvironment(id=i, can_provision=False, missing=True) for i in unique
    }


def _member_schemes(cursor: Any, members: Sequence[ApiProductMember]) -> List[Dict[str, Any]]:
    """The members whose auth can be checked, each with its resolved version's security schemes.

    MCP servers, deleted members and members with no version are left out — there is nothing to
    check them against.

    Args:
        cursor: An open cursor.
        members: The product's resolved members.

    Returns:
        ``{kind, ref, name, schemes}`` per checkable member, in member order.
    """
    checkable = [m for m in members if m.kind != "mcp_server" and not m.missing and m.resolved_version]
    if not checkable:
        return []
    version_ids = sorted({m.resolved_version.id for m in checkable if m.resolved_version})
    schemes: Dict[str, List[Dict[str, Any]]] = {}
    for row in _rows(
        cursor,
        """
        SELECT s.version_id::text AS version_id, s.scheme_name, s.scheme_type
        FROM apiome.version_security_scheme s
        WHERE s.version_id = ANY(%s::uuid[])
        """,
        (version_ids,),
    ):
        schemes.setdefault(row["version_id"], []).append(row)
    return [
        {
            "kind": m.kind,
            "ref": m.ref,
            "name": m.name or m.slug,
            "schemes": schemes.get(m.resolved_version.id, []) if m.resolved_version else [],
        }
        for m in checkable
    ]


def _record(
    row: Mapping[str, Any],
    product_slug: str,
    environments: Mapping[str, PlanEnvironment],
    member_schemes: Sequence[Mapping[str, Any]],
) -> ApiPlanRecord:
    """Build an :class:`ApiPlanRecord` with its environments, notices and warnings.

    Args:
        row: A row selected with ``_PLAN_COLUMNS``.
        product_slug: The product's slug.
        environments: Resolved gateway configs, by id (from :func:`_read_environments`).
        member_schemes: The product's checkable members (from :func:`_member_schemes`).

    Returns:
        The record.
    """
    envs = [environments[str(i)] for i in row.get("environments") or [] if str(i) in environments]
    notice = declared_only_notice(envs)
    return ApiPlanRecord(
        id=str(row["id"]),
        product=product_slug,
        slug=row["slug"],
        name=row["name"],
        description=row.get("description"),
        auth_strategy=row["auth_strategy"],
        auth_config=PlanAuthConfig(**(row.get("auth_config") or {})),
        limits=[PlanLimit(**limit) for limit in row.get("limits") or []],
        concurrency=row.get("concurrency"),
        approval=row["approval"],
        environments=envs,
        declared_only=is_declared_only(envs),
        credential_ttl_days=row.get("credential_ttl_days"),
        terms_url=row.get("terms_url"),
        pricing_note=row.get("pricing_note"),
        billing_ref=row.get("billing_ref"),
        state=row["state"],
        notices=[notice] if notice else [],
        warnings=auth_mismatch_warnings(row["auth_strategy"], member_schemes),
        created_by=row.get("created_by"),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
    )


def _read_plans(
    cursor: Any, tenant_id: str, product: Mapping[str, Any], *, slug: Optional[str] = None
) -> List[ApiPlanRecord]:
    """A product's live plans (or the one with ``slug``), oldest first, fully explained.

    Args:
        cursor: An open cursor.
        tenant_id: The caller's tenant.
        product: The product row (from ``_select_product``).
        slug: Only this plan.

    Returns:
        The plans.
    """
    rows = _rows(
        cursor,
        f"""
        SELECT {_PLAN_COLUMNS}
        FROM apiome.api_plans pl
        WHERE pl.tenant_id = %s::uuid AND pl.product_id = %s::uuid AND pl.deleted_at IS NULL
          AND (%s::text IS NULL OR pl.slug = %s::text)
        ORDER BY pl.created_at, pl.slug
        """,
        (tenant_id, product["id"], slug, slug),
    )
    if not rows:
        return []
    environment_ids = [str(i) for row in rows for i in row.get("environments") or []]
    environments = _read_environments(cursor, tenant_id, environment_ids)
    member_schemes = _member_schemes(cursor, _read_members(cursor, tenant_id, product["id"]))
    return [_record(row, product["slug"], environments, member_schemes) for row in rows]


def _select_plan(cursor: Any, tenant_id: str, product: Mapping[str, Any], slug: str, *, lock: bool) -> Dict[str, Any]:
    """Select a product's live plan by slug, optionally locking it.

    Args:
        cursor: The transaction's cursor.
        tenant_id: The caller's tenant.
        product: The product row.
        slug: The plan's slug.
        lock: True to take ``FOR UPDATE`` on the plan row.

    Returns:
        The plan row.

    Raises:
        ApiPlanValidationError: ``api-plan-not-found``.
    """
    wanted = (slug or "").strip().lower()
    rows = _rows(
        cursor,
        f"""
        SELECT {_PLAN_COLUMNS}
        FROM apiome.api_plans pl
        WHERE pl.tenant_id = %s::uuid AND pl.product_id = %s::uuid AND pl.slug = %s AND pl.deleted_at IS NULL
        {"FOR UPDATE OF pl" if lock else ""}
        """,
        (tenant_id, product["id"], wanted),
    )
    if not rows:
        raise ApiPlanValidationError(CODE_NOT_FOUND, f"no plan '{wanted}' in product '{product['slug']}'")
    return rows[0]


def _finish(cursor: Any, tenant_id: str, product: Mapping[str, Any], slug: str) -> ApiPlanRecord:
    """Re-read one plan after a write.

    Args:
        cursor: The transaction's cursor.
        tenant_id: The caller's tenant.
        product: The product row.
        slug: The plan's slug.

    Returns:
        The plan as stored.
    """
    return _read_plans(cursor, tenant_id, product, slug=slug)[0]


def _declared_only(cursor: Any, tenant_id: str, environment_ids: Sequence[str]) -> bool:
    """Whether a plan with these environments is declared only (for the stored column)."""
    resolved = _read_environments(cursor, tenant_id, environment_ids)
    return is_declared_only([resolved[str(i)] for i in environment_ids])


# ---------------------------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------------------------


def list_plans(tenant_id: str, product_slug: str) -> List[ApiPlanRecord]:
    """Every live plan of a live product, oldest first.

    Args:
        tenant_id: The caller's tenant.
        product_slug: The product's slug.

    Returns:
        The plans, each with environments, notices and warnings.

    Raises:
        ApiProductValidationError: ``api-product-not-found``.
    """

    def work(cursor: Any) -> List[ApiPlanRecord]:
        product = _select_product(cursor, tenant_id, product_slug, lock=False)
        return _read_plans(cursor, tenant_id, product)

    return db._guarded_tx(work)


def get_plan(tenant_id: str, product_slug: str, plan_slug: str) -> ApiPlanRecord:
    """One live plan of a live product.

    Args:
        tenant_id: The caller's tenant.
        product_slug: The product's slug.
        plan_slug: The plan's slug.

    Returns:
        The plan.

    Raises:
        ApiProductValidationError: ``api-product-not-found``.
        ApiPlanValidationError: ``api-plan-not-found``.
    """

    def work(cursor: Any) -> ApiPlanRecord:
        product = _select_product(cursor, tenant_id, product_slug, lock=False)
        row = _select_plan(cursor, tenant_id, product, plan_slug, lock=False)
        return _finish(cursor, tenant_id, product, row["slug"])

    return db._guarded_tx(work)


def plans_for_revision(tenant_id: str, artifact_id: str, revision_id: str) -> List[Dict[str, Any]]:
    """The ``x-apiome-plans`` entries for one revision: the plans of every product that includes it.

    A product includes a revision when one of its members resolves to it today — a project at latest
    (or a catalog item) to its newest version, a project at a version or range to the newest version
    in range (:func:`app.api_products.pick_version`). Retired plans are left out.

    Args:
        tenant_id: The revision's tenant.
        artifact_id: The revision's project.
        revision_id: The revision (``versions.id``).

    Returns:
        The entries, by product slug then plan age; empty when no product includes the revision.
    """
    if not (is_uuid_string(tenant_id) and is_uuid_string(artifact_id) and is_uuid_string(revision_id)):
        return []

    def work(cursor: Any) -> List[Dict[str, Any]]:
        products = _rows(
            cursor,
            """
            SELECT DISTINCT ap.slug
            FROM apiome.api_products ap
            JOIN apiome.api_product_members m ON m.product_id = ap.id AND m.tenant_id = ap.tenant_id
            WHERE ap.tenant_id = %s::uuid AND ap.deleted_at IS NULL
              AND m.member_kind <> 'mcp_server' AND m.member_ref = %s::uuid
              AND EXISTS (SELECT 1 FROM apiome.api_plans pl
                          WHERE pl.product_id = ap.id AND pl.deleted_at IS NULL AND pl.state <> 'retired')
            ORDER BY ap.slug
            """,
            (tenant_id, artifact_id),
        )
        entries: List[Dict[str, Any]] = []
        for listed in products:
            product = _select_product(cursor, tenant_id, listed["slug"], lock=False)
            members = _read_members(cursor, tenant_id, product["id"])
            includes = any(
                m.ref == str(artifact_id) and m.resolved_version and m.resolved_version.id == str(revision_id)
                for m in members
            )
            if not includes:
                continue
            for plan in _read_plans(cursor, tenant_id, product):
                if plan.state != "retired":
                    entries.append(plan_extension_entry(product["slug"], product["name"], plan))
        return entries

    return db._guarded_tx(work)


# ---------------------------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------------------------


def create_plan(
    tenant_id: str, product_slug: str, body: ApiPlanInput, *, actor: ConsumerActor
) -> ApiPlanRecord:
    """Create a plan on a product, audited as ``api_product.plan.create``.

    Args:
        tenant_id: The caller's tenant.
        product_slug: The product's slug.
        body: The plan.
        actor: Who is creating it.

    Returns:
        The stored plan; ``declared_only`` with its notice when no environment can provision.

    Raises:
        ApiProductValidationError: ``api-product-not-found``.
        ApiPlanValidationError: ``api-plan-invalid`` (a malformed field, a repeated limit window, a
            setting on the wrong strategy, the product is full), ``api-plan-slug-taken`` or
            ``api-plan-environment-not-found``.
    """
    name = normalize_plan_name(body.name)
    slug = resolve_plan_slug(body.slug, name)
    limits = normalize_limits(body.limits)
    auth_config = normalize_auth_config(body.auth_strategy, body.auth_config)
    terms_url = normalize_terms_url(body.terms_url)

    def work(cursor: Any) -> ApiPlanRecord:
        product = _select_product(cursor, tenant_id, product_slug, lock=True)
        count = _rows(
            cursor,
            "SELECT count(*)::int AS n FROM apiome.api_plans WHERE product_id = %s::uuid AND deleted_at IS NULL",
            (product["id"],),
        )[0]["n"]
        if count >= MAX_PLANS:
            raise ApiPlanValidationError(CODE_INVALID, f"a product has at most {MAX_PLANS} plans")
        environments = _resolve_environments(cursor, tenant_id, body.environments)
        declared_only = _declared_only(cursor, tenant_id, environments)
        plan_id = _rows(
            cursor,
            """
            INSERT INTO apiome.api_plans
                (tenant_id, product_id, slug, name, description, auth_strategy, auth_config, limits,
                 concurrency, approval, environments, declared_only, credential_ttl_days, terms_url,
                 pricing_note, billing_ref, state, created_by)
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s::uuid[], %s, %s, %s, %s, %s, %s, %s::uuid)
            RETURNING id::text AS id
            """,
            (tenant_id, product["id"], slug, name, _optional_text(body.description), body.auth_strategy,
             Json(auth_config), Json(limits), body.concurrency, body.approval, environments, declared_only,
             body.credential_ttl_days, terms_url, _optional_text(body.pricing_note),
             _optional_text(body.billing_ref), body.state,
             actor.user_id if is_uuid_string(actor.user_id or "") else None),
        )[0]["id"]
        _touch(cursor, product["id"])
        _audit(cursor, tenant_id, actor, "api_product.plan.create", product["slug"], {
            "product_id": product["id"], "plan_id": plan_id, "plan": slug, "name": name,
            "auth_strategy": body.auth_strategy, "limits": limits, "concurrency": body.concurrency,
            "approval": body.approval, "environments": environments, "declared_only": declared_only,
            "state": body.state,
        })
        return _finish(cursor, tenant_id, product, slug)

    return _run(work)


def update_plan(
    tenant_id: str, product_slug: str, plan_slug: str, patch: ApiPlanPatch, *, actor: ConsumerActor
) -> ApiPlanRecord:
    """Apply a partial update, audited as ``api_product.plan.update`` with the fields that changed.

    Changing ``auth_strategy`` without sending ``auth_config`` re-checks the stored config against the
    new strategy (a header name does not carry over to an OAuth2 plan). Sending ``environments``
    re-derives ``declared_only``.

    Args:
        tenant_id: The caller's tenant.
        product_slug: The product's slug.
        plan_slug: The plan's slug.
        patch: The fields to change; ``null`` clears an optional field.
        actor: Who is changing it.

    Returns:
        The stored plan.

    Raises:
        ApiProductValidationError: ``api-product-not-found``.
        ApiPlanValidationError: ``api-plan-not-found``, ``api-plan-invalid`` or
            ``api-plan-environment-not-found``.
    """
    sent = patch.model_fields_set

    def work(cursor: Any) -> ApiPlanRecord:
        product = _select_product(cursor, tenant_id, product_slug, lock=True)
        row = _select_plan(cursor, tenant_id, product, plan_slug, lock=True)
        changes: Dict[str, Any] = {}
        if "name" in sent and patch.name is not None:
            changes["name"] = normalize_plan_name(patch.name)
        for field in ("description", "pricing_note", "billing_ref"):
            if field in sent:
                changes[field] = _optional_text(getattr(patch, field))
        if "terms_url" in sent:
            changes["terms_url"] = normalize_terms_url(patch.terms_url)
        for field in ("concurrency", "credential_ttl_days"):
            if field in sent:
                changes[field] = getattr(patch, field)
        for field in ("approval", "state"):
            if field in sent and getattr(patch, field) is not None:
                changes[field] = getattr(patch, field)
        strategy = patch.auth_strategy if "auth_strategy" in sent and patch.auth_strategy else row["auth_strategy"]
        if strategy != row["auth_strategy"]:
            changes["auth_strategy"] = strategy
        if "auth_config" in sent or "auth_strategy" in changes:
            config = patch.auth_config if "auth_config" in sent else PlanAuthConfig(**(row.get("auth_config") or {}))
            changes["auth_config"] = normalize_auth_config(strategy, config)
        if "limits" in sent and patch.limits is not None:
            changes["limits"] = normalize_limits(patch.limits)
        if "environments" in sent and patch.environments is not None:
            changes["environments"] = _resolve_environments(cursor, tenant_id, patch.environments)
            changes["declared_only"] = _declared_only(cursor, tenant_id, changes["environments"])
        if changes:
            assignments = []
            values: List[Any] = []
            for column, value in changes.items():
                if column in ("auth_config", "limits"):
                    assignments.append(f"{column} = %s")
                    values.append(Json(value))
                elif column == "environments":
                    assignments.append(f"{column} = %s::uuid[]")
                    values.append(value)
                else:
                    assignments.append(f"{column} = %s")
                    values.append(value)
            cursor.execute(
                f"UPDATE apiome.api_plans SET {', '.join(assignments)}, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = %s::uuid",
                (*values, row["id"]),
            )
            _touch(cursor, product["id"])
            _audit(cursor, tenant_id, actor, "api_product.plan.update", product["slug"], {
                "product_id": product["id"], "plan_id": row["id"], "plan": row["slug"], **changes,
            })
        return _finish(cursor, tenant_id, product, row["slug"])

    return _run(work)


def delete_plan(tenant_id: str, product_slug: str, plan_slug: str, *, actor: ConsumerActor) -> str:
    """Soft-delete a plan, audited as ``api_product.plan.delete``. Its slug is free again.

    Args:
        tenant_id: The caller's tenant.
        product_slug: The product's slug.
        plan_slug: The plan's slug.
        actor: Who is deleting it.

    Returns:
        The deleted plan's slug.

    Raises:
        ApiProductValidationError: ``api-product-not-found``.
        ApiPlanValidationError: ``api-plan-not-found``.
    """

    def work(cursor: Any) -> str:
        product = _select_product(cursor, tenant_id, product_slug, lock=True)
        row = _select_plan(cursor, tenant_id, product, plan_slug, lock=True)
        cursor.execute(
            "UPDATE apiome.api_plans SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = %s::uuid",
            (row["id"],),
        )
        _touch(cursor, product["id"])
        _audit(cursor, tenant_id, actor, "api_product.plan.delete", product["slug"], {
            "product_id": product["id"], "plan_id": row["id"], "plan": row["slug"],
        })
        return str(row["slug"])

    return _run(work)
