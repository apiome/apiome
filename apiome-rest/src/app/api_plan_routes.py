"""``/v1/tenants/{tenant_slug}/products/{product_slug}/plans`` — APX-1.2 (#6099).

The HTTP surface of API plans: list and create a product's plans, and read, update and delete one.
A plan is a tier of the product — its auth strategy, declared limits, approval mode, the gateway
configs it is provisioned to and its terms.

**Authorization.** Plans belong to products, which use the ``projects`` RBAC resource:
``projects:view`` to read and ``projects:edit`` to create, update or delete a plan.

**A refusal carries a stable code.** Every error detail is ``{"code", "message"}``. A plan whose
environments cannot be provisioned is *not* refused: it is saved with ``declared_only: true`` and an
``api-plan-declared-only`` notice. A member whose security schemes do not fit the auth strategy is
reported as an ``api-plan-auth-mismatch`` warning.

**Lifecycle** (APX-1.4). ``PATCH`` moves ``state`` along the lifecycle — deprecating blocks new
subscriptions and notifies subscribed application owners once, retiring (on or after
``retire_at``) revokes provisioning — and ``POST …/plans/{plan}/migrate`` moves a deprecated plan's
subscriptions to another plan without changing any credential.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .api_lifecycle import CODE_RETIRE_EARLY, CODE_SUCCESSOR_INVALID, CODE_TRANSITION
from .api_plan_store import create_plan, delete_plan, get_plan, list_plans, migrate_plan, update_plan
from .api_plans import (
    CODE_ENVIRONMENT_NOT_FOUND,
    CODE_NOT_FOUND,
    CODE_SLUG_TAKEN,
    ApiPlanInput,
    ApiPlanMigrateInput,
    ApiPlanMigration,
    ApiPlanPatch,
    ApiPlanRecord,
    ApiPlanValidationError,
)
from .api_product_routes import _http_error as _product_http_error
from .api_product_routes import _tenant_id
from .api_products import ApiProductValidationError
from .auth import validate_authentication
from .consumer_contract_store import actor_from_auth
from .database import db
from .permissions import Action, Resource, enforce_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["api-products"])

#: A refusal maps onto the status that matches what kind of refusal it is; anything else is 400.
_STATUS_BY_CODE = {
    CODE_NOT_FOUND: 404,
    CODE_SLUG_TAKEN: 409,
    CODE_ENVIRONMENT_NOT_FOUND: 422,
    CODE_TRANSITION: 409,
    CODE_RETIRE_EARLY: 409,
    CODE_SUCCESSOR_INVALID: 422,
}


class ApiPlanListResponse(BaseModel):
    """A product's live plans."""

    model_config = ConfigDict(extra="forbid")

    plans: List[ApiPlanRecord] = Field(default_factory=list, description="The plans, oldest first.")
    count: int = Field(description="How many plans were returned.")


class ApiPlanDeleteResponse(BaseModel):
    """What a delete did."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(description="The deleted plan's slug (now free for reuse in this product).")


def _http_error(exc: ValueError) -> HTTPException:
    """Translate a plan or product refusal into the HTTP error a client sees.

    Args:
        exc: An :class:`ApiPlanValidationError` or :class:`ApiProductValidationError`.

    Returns:
        The ``HTTPException`` (404 unknown product or plan, 409 slug taken or a lifecycle step that
        is not allowed yet, 422 unknown environment or unusable replacement plan, 400 otherwise),
        always ``{"code", "message"}``.
    """
    if isinstance(exc, ApiProductValidationError):
        return _product_http_error(exc)
    code = getattr(exc, "code", "api-plan-invalid")
    return HTTPException(status_code=_STATUS_BY_CODE.get(code, 400), detail={"code": code, "message": str(exc)})


@router.get(
    "/{tenant_slug}/products/{product_slug}/plans",
    response_model=ApiPlanListResponse,
    summary="List an API product's plans",
    description=(
        "Every live plan of the product, oldest first, each with its environments resolved to "
        "gateway configs, `declared_only` and its notices, and an `api-plan-auth-mismatch` warning "
        "per member whose security schemes do not fit the plan's auth strategy.\n\n"
        "Requires `projects:view`."
    ),
)
def list_product_plans(
    tenant_slug: str, product_slug: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> ApiPlanListResponse:
    """List a product's plans.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is what scopes the read).
        product_slug: The product's slug.
        auth_data: The authenticated principal.

    Returns:
        The plans.

    Raises:
        HTTPException: 404 for an unknown product, 403 without ``projects:view``.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    _ = tenant_slug
    try:
        plans = list_plans(_tenant_id(auth_data), product_slug)
    except (ApiPlanValidationError, ApiProductValidationError) as exc:
        raise _http_error(exc) from exc
    return ApiPlanListResponse(plans=plans, count=len(plans))


@router.post(
    "/{tenant_slug}/products/{product_slug}/plans",
    response_model=ApiPlanRecord,
    status_code=201,
    summary="Create an API plan",
    description=(
        "Add a plan to the product. The `slug` is derived from `name` when omitted and cannot be "
        "changed afterwards. `auth_strategy` is `key_auth` (default; `auth_config.header_name`), "
        "`oauth2_client_credentials` (`auth_config.idp_config_id`, `auth_config.scopes`), `mtls` or "
        "`none`. `limits` is `[{window, requests}]` with `window` one of `second`, `minute`, `hour`, "
        "`day`, `month` — every count positive, every window once. `approval` is `manual` (default) "
        "or `auto`. `environments` are gateway config slugs or ids; a plan with none, or with one "
        "whose connector cannot provision, is saved with `declared_only: true` and an "
        "`api-plan-declared-only` notice. `billing_ref` is internal and never exported. A new plan "
        "starts as `draft` (default) or `published`; anything else is `api-lifecycle-invalid-state`.\n\n"
        "Audited as `api_product.plan.create`. Requires `projects:edit`."
    ),
)
def create_product_plan(
    tenant_slug: str,
    product_slug: str,
    body: ApiPlanInput,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ApiPlanRecord:
    """Create a plan.

    Args:
        tenant_slug: The tenant in the URL.
        product_slug: The product's slug.
        body: The plan.
        auth_data: The authenticated principal.

    Returns:
        The stored plan.

    Raises:
        HTTPException: 404 for an unknown product, 400 for a malformed field, 409 when the slug is
            taken, 422 for an unknown environment, 403 without ``projects:edit``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT, target=product_slug)
    _ = tenant_slug
    try:
        return create_plan(_tenant_id(auth_data), product_slug, body, actor=actor_from_auth(auth_data, user_id))
    except (ApiPlanValidationError, ApiProductValidationError) as exc:
        raise _http_error(exc) from exc


@router.get(
    "/{tenant_slug}/products/{product_slug}/plans/{plan_slug}",
    response_model=ApiPlanRecord,
    summary="Read an API plan",
    description=(
        "One live plan with its environments, `declared_only`, notices and auth warnings.\n\n"
        "Requires `projects:view`."
    ),
)
def read_product_plan(
    tenant_slug: str,
    product_slug: str,
    plan_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ApiPlanRecord:
    """Read one plan.

    Args:
        tenant_slug: The tenant in the URL.
        product_slug: The product's slug.
        plan_slug: The plan's slug.
        auth_data: The authenticated principal.

    Returns:
        The plan.

    Raises:
        HTTPException: 404 for an unknown product or plan, 403 without ``projects:view``.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    _ = tenant_slug
    try:
        return get_plan(_tenant_id(auth_data), product_slug, plan_slug)
    except (ApiPlanValidationError, ApiProductValidationError) as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/{tenant_slug}/products/{product_slug}/plans/{plan_slug}",
    response_model=ApiPlanRecord,
    summary="Update an API plan",
    description=(
        "Change any of a plan's fields but its slug. Omitted fields are left alone; `null` clears "
        "an optional one. `limits` and `environments` are replaced as a whole; changing "
        "`environments` re-derives `declared_only`. Changing `auth_strategy` without `auth_config` "
        "re-checks the stored config against the new strategy.\n\n"
        "**Lifecycle.** `state` moves draft ⇄ published → deprecated → retired, and deprecated → "
        "published reinstates (clearing the deprecation). Deprecating stamps `deprecated_at`, blocks "
        "new subscriptions (`accepts_subscriptions: false`) and notifies subscribed application owners "
        "once. `retire_at`, `deprecation_message` and `successor` (a published plan of the product "
        "with the same auth strategy) describe a deprecation and are refused on any other state. "
        "Retiring is refused with `api-lifecycle-retire-early` (409) before `retire_at`, and revokes "
        "the plan's provisioning. Any other step is `api-lifecycle-transition` (409); an unusable "
        "successor is `api-lifecycle-successor-invalid` (422).\n\n"
        "Audited as `api_product.plan.deprecate`, `.reinstate`, `.retire` or `.update`. Requires "
        "`projects:edit`."
    ),
)
def patch_product_plan(
    tenant_slug: str,
    product_slug: str,
    plan_slug: str,
    body: ApiPlanPatch,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ApiPlanRecord:
    """Update a plan.

    Args:
        tenant_slug: The tenant in the URL.
        product_slug: The product's slug.
        plan_slug: The plan's slug.
        body: The fields to change.
        auth_data: The authenticated principal.

    Returns:
        The updated plan.

    Raises:
        HTTPException: 404 for an unknown product or plan, 400 for a malformed field, 422 for an
            unknown environment, 403 without ``projects:edit``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT, target=product_slug)
    _ = tenant_slug
    try:
        return update_plan(
            _tenant_id(auth_data), product_slug, plan_slug, body, actor=actor_from_auth(auth_data, user_id)
        )
    except (ApiPlanValidationError, ApiProductValidationError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{tenant_slug}/products/{product_slug}/plans/{plan_slug}/migrate",
    response_model=ApiPlanMigration,
    summary="Migrate a deprecated plan's subscriptions",
    description=(
        "**Migrate to plan.** Moves every subscription of a deprecated plan to `to` — a published "
        "plan of the same product with the same auth strategy — re-provisioning each consumer into "
        "the target's consumer group (`plan:<product>-<plan>`) with the credential it already holds: "
        "`credentials_changed` is always false. The target becomes the plan's `successor`. "
        "`dry_run: true` reports what would move and changes nothing.\n\n"
        "A plan that is not deprecated is `api-lifecycle-transition` (409); an unknown, unpublished "
        "or differently-authenticated target is `api-lifecycle-successor-invalid` (422).\n\n"
        "Audited as `api_product.plan.migrate` (not on a dry run). Requires `projects:edit`."
    ),
)
def migrate_product_plan(
    tenant_slug: str,
    product_slug: str,
    plan_slug: str,
    body: ApiPlanMigrateInput,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ApiPlanMigration:
    """Migrate a deprecated plan's subscriptions to another plan.

    Args:
        tenant_slug: The tenant in the URL.
        product_slug: The product's slug.
        plan_slug: The deprecated plan's slug.
        body: The target plan and whether this is a dry run.
        auth_data: The authenticated principal.

    Returns:
        What moved (or would move).

    Raises:
        HTTPException: 404 for an unknown product or plan, 409 when the plan is not deprecated,
            422 for an unusable target, 403 without ``projects:edit``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT, target=product_slug)
    _ = tenant_slug
    try:
        return migrate_plan(
            _tenant_id(auth_data), product_slug, plan_slug, body, actor=actor_from_auth(auth_data, user_id)
        )
    except (ApiPlanValidationError, ApiProductValidationError) as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{tenant_slug}/products/{product_slug}/plans/{plan_slug}",
    response_model=ApiPlanDeleteResponse,
    summary="Delete an API plan",
    description=(
        "Soft-delete a plan; its slug is free again in this product.\n\n"
        "Audited as `api_product.plan.delete`. Requires `projects:edit`."
    ),
)
def delete_product_plan(
    tenant_slug: str,
    product_slug: str,
    plan_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ApiPlanDeleteResponse:
    """Delete a plan.

    Args:
        tenant_slug: The tenant in the URL.
        product_slug: The product's slug.
        plan_slug: The plan's slug.
        auth_data: The authenticated principal.

    Returns:
        The deleted plan's slug.

    Raises:
        HTTPException: 404 for an unknown product or plan, 403 without ``projects:edit``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT, target=product_slug)
    _ = tenant_slug
    try:
        slug = delete_plan(_tenant_id(auth_data), product_slug, plan_slug, actor=actor_from_auth(auth_data, user_id))
    except (ApiPlanValidationError, ApiProductValidationError) as exc:
        raise _http_error(exc) from exc
    return ApiPlanDeleteResponse(slug=slug)
