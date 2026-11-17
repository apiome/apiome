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

**Lifecycle** (APX-1.4, :mod:`app.api_lifecycle`). An update moves ``state`` one step at a time and
is audited by what it did — ``api_product.plan.deprecate``, ``.reinstate``, ``.retire`` or ``.update``:

* **deprecate** stamps ``deprecated_at`` (new subscriptions are blocked from then) and tells the
  owners of subscribed applications once (:func:`_notify_owners_once`, marked by
  ``owners_notified_at``);
* **retire** waits for ``retire_at`` and revokes the plan's provisioning (:func:`_revoke_provisioning`);
* **migrate** (:func:`migrate_plan`) moves a deprecated plan's subscriptions to its successor's
  consumer group, keeping every credential (:func:`_move_subscriptions`).

Applications and subscriptions (APX-2.1/2.2) and gateway provisioning (APX-4.1) are not built yet, so
those three hooks find nobody to notify, nothing to revoke and nothing to move: they return ``0`` and
each transition is still checked and audited. They are the only places those epics change.

**A delete is soft**, freeing the slug.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import psycopg2
from psycopg2.extras import Json

from .api_lifecycle import (
    CODE_SUCCESSOR_INVALID,
    CODE_TRANSITION,
    LifecycleError,
    accepts_new_subscriptions,
    check_initial_state,
    lifecycle_changes,
    plan_group_name,
    successor_problem,
)
from .api_plans import (
    CODE_ENVIRONMENT_NOT_FOUND,
    CODE_INVALID,
    CODE_NOT_FOUND,
    CODE_SLUG_TAKEN,
    MAX_PLANS,
    ApiPlanInput,
    ApiPlanMigrateInput,
    ApiPlanMigration,
    ApiPlanPatch,
    ApiPlanRecord,
    ApiPlanValidationError,
    PlanAuthConfig,
    PlanEnvironment,
    PlanLimit,
    PlanRef,
    auth_mismatch_warnings,
    connector_can_provision,
    declared_only_notice,
    deprecated_notice,
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
    "migrate_plan",
    "plans_for_revision",
    "update_plan",
]

#: The plan columns every read selects.
_PLAN_COLUMNS = """
    pl.id::text AS id, pl.slug, pl.name, pl.description, pl.auth_strategy, pl.auth_config, pl.limits,
    pl.concurrency, pl.approval, pl.environments::text[] AS environments, pl.credential_ttl_days,
    pl.terms_url, pl.pricing_note, pl.billing_ref, pl.state,
    pl.deprecated_at, pl.retire_at, pl.retired_at, pl.deprecation_message, pl.owners_notified_at,
    pl.successor_plan_id::text AS successor_plan_id,
    (SELECT json_build_object('slug', s.slug, 'name', s.name, 'state', s.state)
     FROM apiome.api_plans s WHERE s.id = pl.successor_plan_id AND s.deleted_at IS NULL) AS successor,
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


def _now() -> datetime:
    """The current time, aware and in UTC (patched by tests)."""
    return datetime.now(timezone.utc)


def _lifecycle_refusal(exc: LifecycleError) -> ApiPlanValidationError:
    """Re-raise a lifecycle refusal as a plan refusal with the same code."""
    return ApiPlanValidationError(exc.code, str(exc))


def _jsonable(detail: Mapping[str, Any]) -> Dict[str, Any]:
    """An audit detail with every ``datetime`` rendered as ISO-8601, so it serializes."""
    return {key: _iso(value) if isinstance(value, datetime) else value for key, value in detail.items()}


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
    successor = PlanRef(**row["successor"]) if row.get("successor") else None
    retire_at = _iso(row.get("retire_at"))
    notices = [
        notice
        for notice in (declared_only_notice(envs), deprecated_notice(row["state"], retire_at, successor))
        if notice is not None
    ]
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
        accepts_subscriptions=accepts_new_subscriptions(row["state"]),
        deprecated_at=_iso(row.get("deprecated_at")),
        retire_at=retire_at,
        retired_at=_iso(row.get("retired_at")),
        deprecation_message=row.get("deprecation_message"),
        successor=successor,
        owners_notified_at=_iso(row.get("owners_notified_at")),
        notices=notices,
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


def _find_plan(
    cursor: Any, tenant_id: str, product: Mapping[str, Any], *, slug: Optional[str] = None,
    plan_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """A live plan of the product by slug or id, or ``None`` (no lock; for successor checks).

    Args:
        cursor: An open cursor.
        tenant_id: The caller's tenant.
        product: The product row.
        slug: The plan's slug.
        plan_id: The plan's id (used when ``slug`` is ``None``).

    Returns:
        The plan row, or ``None``.
    """
    if slug is None and not is_uuid_string(plan_id or ""):
        return None
    rows = _rows(
        cursor,
        f"""
        SELECT {_PLAN_COLUMNS}
        FROM apiome.api_plans pl
        WHERE pl.tenant_id = %s::uuid AND pl.product_id = %s::uuid AND pl.deleted_at IS NULL
          AND (pl.slug = %s::text OR pl.id::text = %s::text)
        """,
        (tenant_id, product["id"], (slug or "").strip().lower() or None, plan_id if slug is None else None),
    )
    return rows[0] if rows else None


def _check_successor(plan: Mapping[str, Any], candidate: Optional[Mapping[str, Any]]) -> None:
    """Refuse a successor that cannot take the plan's consumers.

    Args:
        plan: The plan being replaced (``id``, ``auth_strategy`` as it will be stored).
        candidate: The successor's row, or ``None`` when the product has no such plan.

    Raises:
        ApiPlanValidationError: ``api-lifecycle-successor-invalid`` naming the problem
            (:func:`app.api_lifecycle.successor_problem`).
    """
    problem = successor_problem(plan, candidate)
    if problem:
        raise ApiPlanValidationError(CODE_SUCCESSOR_INVALID, f"cannot use that replacement plan: {problem}")


# ---------------------------------------------------------------------------------------------
# Lifecycle hooks — where APX-2.x (subscriptions) and APX-4.x (provisioning) plug in
# ---------------------------------------------------------------------------------------------


def _subscribed_owner_ids(cursor: Any, tenant_id: str, plan_id: str) -> List[str]:
    """The user ids of the owners of applications subscribed to a plan.

    Applications and subscriptions arrive with APX-2.1/2.2 (#6103, #6104); until then no
    application can subscribe, so there is nobody to tell.

    Args:
        cursor: The transaction's cursor.
        tenant_id: The plan's tenant.
        plan_id: The plan.

    Returns:
        The owners, once each — empty today.
    """
    _ = cursor, tenant_id, plan_id
    return []


def _notify_owners_once(cursor: Any, tenant_id: str, plan_id: str, now: datetime) -> Optional[int]:
    """Tell subscribed application owners a plan is deprecated — once per deprecation.

    The ``owners_notified_at`` marker is claimed with a conditional update inside the deprecation's
    transaction, so a retried request or a second server never notifies twice; reinstating the plan
    clears the marker, so a later deprecation notifies again.

    Args:
        cursor: The transaction's cursor.
        tenant_id: The plan's tenant.
        plan_id: The plan.
        now: The deprecation's time.

    Returns:
        How many owners were told, or ``None`` when they had already been told.
    """
    claimed = _rows(
        cursor,
        "UPDATE apiome.api_plans SET owners_notified_at = %s "
        "WHERE id = %s::uuid AND owners_notified_at IS NULL RETURNING id::text AS id",
        (now, plan_id),
    )
    if not claimed:
        return None
    # APX-2.2 writes one inbox notification per owner here, in this transaction.
    return len(_subscribed_owner_ids(cursor, tenant_id, plan_id))


def _revoke_provisioning(cursor: Any, tenant_id: str, plan: Mapping[str, Any]) -> int:
    """Revoke what a retired plan provisioned on its gateways.

    Gateway provisioning arrives with APX-4.1 (#6115); until then every plan is declared only and
    nothing was pushed to a gateway, so there is nothing to revoke.

    Args:
        cursor: The transaction's cursor.
        tenant_id: The plan's tenant.
        plan: The plan row.

    Returns:
        How many consumer provisionings were revoked — ``0`` today.
    """
    _ = cursor, tenant_id, plan
    return 0


def _move_subscriptions(
    cursor: Any, tenant_id: str, source: Mapping[str, Any], target: Mapping[str, Any], *, dry_run: bool
) -> int:
    """Move a plan's subscriptions to another plan, re-provisioning each consumer into the target's
    consumer group with the credential it already holds.

    Subscriptions arrive with APX-2.2 (#6104) and provisioning with APX-4.1 (#6115); until then no
    plan has a subscription, so nothing moves.

    Args:
        cursor: The transaction's cursor.
        tenant_id: The plans' tenant.
        source: The deprecated plan.
        target: The plan consumers move to.
        dry_run: True to count without moving.

    Returns:
        How many subscriptions moved (or would) — ``0`` today.
    """
    _ = cursor, tenant_id, source, target, dry_run
    return 0


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
    try:
        check_initial_state(body.state, "plan")
    except LifecycleError as exc:
        raise _lifecycle_refusal(exc) from exc
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
    """Apply a partial update, audited by what it did.

    The audit action is ``api_product.plan.deprecate``, ``.reinstate`` or ``.retire`` when ``state``
    takes that lifecycle step, ``api_product.plan.update`` otherwise; the detail holds the fields
    that changed. Deprecating notifies subscribed application owners once; retiring revokes the
    plan's provisioning (see the module docstring for what those hooks do today).

    Changing ``auth_strategy`` without sending ``auth_config`` re-checks the stored config against the
    new strategy (a header name does not carry over to an OAuth2 plan). Sending ``environments``
    re-derives ``declared_only``. A deprecated plan's successor is re-checked against the auth
    strategy it will have.

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
        ApiPlanValidationError: ``api-plan-not-found``, ``api-plan-invalid``,
            ``api-plan-environment-not-found``, ``api-lifecycle-transition`` (a step that is not
            allowed, or deprecation fields on a plan that is not deprecated),
            ``api-lifecycle-retire-early`` or ``api-lifecycle-successor-invalid``.
    """
    sent = patch.model_fields_set

    def work(cursor: Any) -> ApiPlanRecord:
        product = _select_product(cursor, tenant_id, product_slug, lock=True)
        row = _select_plan(cursor, tenant_id, product, plan_slug, lock=True)
        now = _now()
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
        if "approval" in sent and patch.approval is not None:
            changes["approval"] = patch.approval
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

        target = patch.state if "state" in sent and patch.state is not None else row["state"]
        changes.update(_plan_lifecycle_changes(cursor, tenant_id, product, row, patch, target, strategy, now))
        if target != row["state"]:
            changes["state"] = target

        notified: Optional[int] = None
        revoked: Optional[int] = None
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
                elif column == "successor_plan_id":
                    assignments.append(f"{column} = %s::uuid")
                    values.append(value)
                else:
                    assignments.append(f"{column} = %s")
                    values.append(value)
            cursor.execute(
                f"UPDATE apiome.api_plans SET {', '.join(assignments)}, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = %s::uuid",
                (*values, row["id"]),
            )
            if target == "deprecated" and row["state"] != "deprecated":
                notified = _notify_owners_once(cursor, tenant_id, row["id"], now)
            if target == "retired" and row["state"] != "retired":
                revoked = _revoke_provisioning(cursor, tenant_id, row)
            _touch(cursor, product["id"])
            detail: Dict[str, Any] = {"product_id": product["id"], "plan_id": row["id"], "plan": row["slug"], **changes}
            if notified is not None:
                detail["owners_notified"] = notified
            if revoked is not None:
                detail["provisioning_revoked"] = revoked
            _audit(cursor, tenant_id, actor, _update_action(row["state"], target), product["slug"], _jsonable(detail))
        return _finish(cursor, tenant_id, product, row["slug"])

    return _run(work)


def _update_action(current: str, target: str) -> str:
    """The audit action an update is recorded as: the lifecycle step it took, else ``update``.

    Args:
        current: The stored state.
        target: The state after the update.

    Returns:
        ``api_product.plan.deprecate``, ``.reinstate``, ``.retire`` or ``.update``.
    """
    if current != target:
        if target == "deprecated":
            return "api_product.plan.deprecate"
        if target == "retired":
            return "api_product.plan.retire"
        if current == "deprecated" and target == "published":
            return "api_product.plan.reinstate"
    return "api_product.plan.update"


def _plan_lifecycle_changes(
    cursor: Any,
    tenant_id: str,
    product: Mapping[str, Any],
    row: Mapping[str, Any],
    patch: ApiPlanPatch,
    target: str,
    strategy: str,
    now: datetime,
) -> Dict[str, Any]:
    """The lifecycle columns an update changes: dates, message and successor.

    Args:
        cursor: The transaction's cursor.
        tenant_id: The caller's tenant.
        product: The product row.
        row: The stored plan.
        patch: The update.
        target: The state after the update.
        strategy: The auth strategy after the update.
        now: The update's time.

    Returns:
        ``{column: value}`` for the columns that change (``deprecated_at``, ``retire_at``,
        ``retired_at``, ``deprecation_message``, ``successor_plan_id``, ``owners_notified_at``).

    Raises:
        ApiPlanValidationError: ``api-lifecycle-transition``, ``api-lifecycle-retire-early`` or
            ``api-lifecycle-successor-invalid``.
    """
    sent = patch.model_fields_set
    try:
        changes = lifecycle_changes(
            row, target=target, sent=frozenset(sent), retire_at=patch.retire_at,
            message=patch.deprecation_message, now=now, noun="plan",
        )
    except LifecycleError as exc:
        raise _lifecycle_refusal(exc) from exc

    if "successor" in sent and target != "deprecated":
        raise ApiPlanValidationError(CODE_TRANSITION, "a replacement plan belongs to a deprecated plan")
    if row["state"] == "deprecated" and target == "published":
        changes.update(successor_plan_id=None, owners_notified_at=None)
        return changes

    successor_id = row.get("successor_plan_id")
    if "successor" in sent:
        if patch.successor is None or not patch.successor.strip():
            changes["successor_plan_id"] = None
            return changes
        candidate = _find_plan(cursor, tenant_id, product, slug=patch.successor)
        _check_successor({"id": row["id"], "auth_strategy": strategy}, candidate)
        if candidate and candidate["id"] != successor_id:
            changes["successor_plan_id"] = candidate["id"]
    elif successor_id and target == "deprecated" and strategy != row["auth_strategy"]:
        _check_successor(
            {"id": row["id"], "auth_strategy": strategy}, _find_plan(cursor, tenant_id, product, plan_id=successor_id)
        )
    return changes


def migrate_plan(
    tenant_id: str, product_slug: str, plan_slug: str, body: ApiPlanMigrateInput, *, actor: ConsumerActor
) -> ApiPlanMigration:
    """Move a deprecated plan's subscriptions to another plan of the product — **migrate to plan**.

    Each subscription is re-provisioned into the target plan's consumer group with the credential it
    already holds (:func:`_move_subscriptions`); no key is issued, rotated or revoked, which is why
    the target must use the same auth strategy. A real migration also records the target as the
    plan's successor and is audited as ``api_product.plan.migrate``; a dry run changes nothing.

    Args:
        tenant_id: The caller's tenant.
        product_slug: The product's slug.
        plan_slug: The deprecated plan's slug.
        body: The target plan and whether this is a dry run.
        actor: Who is migrating.

    Returns:
        What moved (or would move).

    Raises:
        ApiProductValidationError: ``api-product-not-found``.
        ApiPlanValidationError: ``api-plan-not-found``, ``api-lifecycle-transition`` (the plan is
            not deprecated) or ``api-lifecycle-successor-invalid`` (the target is unknown, the same
            plan, not published, or uses another auth strategy).
    """

    def work(cursor: Any) -> ApiPlanMigration:
        product = _select_product(cursor, tenant_id, product_slug, lock=True)
        source = _select_plan(cursor, tenant_id, product, plan_slug, lock=True)
        if source["state"] != "deprecated":
            raise ApiPlanValidationError(
                CODE_TRANSITION, f"'{source['slug']}' is {source['state']}; deprecate it before migrating its consumers"
            )
        found = _find_plan(cursor, tenant_id, product, slug=body.to)
        _check_successor(source, found)
        target: Mapping[str, Any] = found or {}
        moved = _move_subscriptions(cursor, tenant_id, source, target, dry_run=body.dry_run)
        from_ref = PlanRef(slug=source["slug"], name=source["name"], state=source["state"])
        to_ref = PlanRef(slug=target["slug"], name=target["name"], state=target["state"])
        noun = "subscription" if moved == 1 else "subscriptions"
        if body.dry_run:
            message = f"Would move {moved} {noun} from {source['name']} to {target['name']}; keys stay the same."
        elif moved:
            message = f"Moved {moved} {noun} from {source['name']} to {target['name']}; keys stay the same."
        else:
            message = (
                f"No application is subscribed to {source['name']}, so nothing moved. "
                f"{target['name']} is recorded as its replacement."
            )
        if not body.dry_run:
            if source.get("successor_plan_id") != target["id"]:
                cursor.execute(
                    "UPDATE apiome.api_plans SET successor_plan_id = %s::uuid, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = %s::uuid",
                    (target["id"], source["id"]),
                )
            _touch(cursor, product["id"])
            _audit(cursor, tenant_id, actor, "api_product.plan.migrate", product["slug"], {
                "product_id": product["id"], "plan_id": source["id"], "plan": source["slug"],
                "to_plan_id": target["id"], "to_plan": target["slug"], "subscriptions": moved,
                "credentials_changed": False,
            })
        return ApiPlanMigration(
            from_plan=from_ref,
            to_plan=to_ref,
            dry_run=body.dry_run,
            from_group=plan_group_name(product["slug"], source["slug"]),
            to_group=plan_group_name(product["slug"], target["slug"]),
            subscriptions=moved,
            credentials_changed=False,
            message=message,
        )

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
