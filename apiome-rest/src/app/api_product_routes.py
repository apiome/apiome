"""``/v1/tenants/{tenant_slug}/products`` — APX-1.1 (#6098).

The HTTP surface of API products: list and create a tenant's products, read, update and delete
one, and list, add and remove its members. A product bundles Projects (at a version, a range or
latest), MCP servers and catalog items under one name, owner team, visibility and state; later APX
tickets attach plans and access requests to it.

**Authorization.** Products bundle Projects, so they use the ``projects`` RBAC resource:
``projects:view`` to read, ``projects:create`` to create, ``projects:edit`` to update or change
members and ``projects:delete`` to delete.

**A refusal carries a stable code.** Every error detail is ``{"code", "message"}``; a portal refusal
(``api-product-portal-unpublished``, 422) also carries ``blockers`` — the members that are not
published — so a client can say what to publish first.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .api_lifecycle import CODE_RETIRE_EARLY, CODE_TRANSITION
from .api_product_store import (
    PRODUCTS_ORDER,
    add_member,
    create_product,
    delete_product,
    get_product,
    list_members,
    page_products,
    remove_member,
    update_product,
)
from .api_products import (
    CODE_MEMBER_DUPLICATE,
    CODE_MEMBER_NOT_FOUND,
    CODE_MEMBER_REF_NOT_FOUND,
    CODE_NOT_FOUND,
    CODE_PLANS_LIVE,
    CODE_PORTAL_UNPUBLISHED,
    CODE_SLUG_TAKEN,
    CODE_TEAM_NOT_FOUND,
    ApiProductInput,
    ApiProductMember,
    ApiProductMemberInput,
    ApiProductPatch,
    ApiProductRecord,
    ApiProductValidationError,
)
from .auth import validate_authentication
from .consumer_contract_store import actor_from_auth
from .database import db
from .keyset_pagination import MAX_REVISION_PAGE_LIMIT, cursor_query, limit_query
from .permissions import Action, Resource, enforce_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["api-products"])

#: A refusal maps onto the status that matches what kind of refusal it is; anything else is 400.
_STATUS_BY_CODE = {
    CODE_NOT_FOUND: 404,
    CODE_MEMBER_NOT_FOUND: 404,
    CODE_SLUG_TAKEN: 409,
    CODE_MEMBER_DUPLICATE: 409,
    CODE_TEAM_NOT_FOUND: 422,
    CODE_MEMBER_REF_NOT_FOUND: 422,
    CODE_PORTAL_UNPUBLISHED: 422,
    CODE_TRANSITION: 409,
    CODE_RETIRE_EARLY: 409,
    CODE_PLANS_LIVE: 409,
}


class ApiProductListResponse(BaseModel):
    """Every live product of the tenant."""

    model_config = ConfigDict(extra="forbid")

    products: List[ApiProductRecord] = Field(default_factory=list, description="The products, by name.")
    count: int = Field(description="How many products were returned.")
    has_more: bool = Field(default=False, description="Whether another page exists.")
    next_cursor: Optional[str] = Field(
        default=None, description="Pass as `cursor` to read the next page; null on the last page."
    )


class ApiProductMemberListResponse(BaseModel):
    """A product's members."""

    model_config = ConfigDict(extra="forbid")

    members: List[ApiProductMember] = Field(default_factory=list)
    count: int


class ApiProductDeleteResponse(BaseModel):
    """What a delete did."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(description="The deleted product's slug (now free for reuse).")


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """Return the authenticated tenant id, or refuse.

    Args:
        auth_data: The resolved auth context.

    Returns:
        The tenant id.

    Raises:
        HTTPException: 403 when the credential carries no tenant.
    """
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _http_error(exc: ApiProductValidationError) -> HTTPException:
    """Translate a product refusal into the HTTP error a client sees.

    Args:
        exc: The refusal.

    Returns:
        The ``HTTPException`` (404 unknown product or member, 409 slug taken or duplicate member,
        422 unknown team or member ref or a portal refusal, 400 otherwise) — always
        ``{"code", "message"}``, plus ``blockers`` for ``api-product-portal-unpublished``.
    """
    detail: Dict[str, Any] = {"code": exc.code, "message": str(exc)}
    if exc.blockers is not None:
        detail["blockers"] = exc.blockers
    return HTTPException(status_code=_STATUS_BY_CODE.get(exc.code, 400), detail=detail)


@router.get(
    "/{tenant_slug}/products",
    response_model=ApiProductListResponse,
    summary="List API products",
    description=(
        "Every live API product of the tenant, by name, with its owner team, visibility, state and "
        "member count. Deleted products are not listed.\n\n"
        "At most 1,000 a page: pass the previous page's `next_cursor` as `cursor` until `has_more` "
        "is false.\n\nRequires `projects:view`."
    ),
)
def list_tenant_products(
    tenant_slug: str,
    limit: int = limit_query(MAX_REVISION_PAGE_LIMIT, maximum=MAX_REVISION_PAGE_LIMIT),
    cursor: Optional[str] = cursor_query(),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ApiProductListResponse:
    """List one page of the tenant's products.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is what scopes the read).
        limit: Page size.
        cursor: Where the page starts (the previous page's ``next_cursor``).
        auth_data: The authenticated principal.

    Returns:
        The products of the page and whether another follows.

    Raises:
        HTTPException: 400 for a malformed cursor; 403 without ``projects:view``.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    after = PRODUCTS_ORDER.parse(cursor)
    _ = tenant_slug
    page = page_products(_tenant_id(auth_data), limit=limit, cursor=after)
    return ApiProductListResponse(
        products=page.items, count=len(page.items), has_more=page.has_more, next_cursor=page.next_cursor
    )


@router.post(
    "/{tenant_slug}/products",
    response_model=ApiProductRecord,
    status_code=201,
    summary="Create an API product",
    description=(
        "Create an API product, optionally with its first members. The `slug` is derived from "
        "`name` when omitted and cannot be changed afterwards. `owner_team` is a team slug. "
        "`visibility` is `private` (default), `workspace` or `portal`; a `portal` product needs "
        "every member published (`api-product-portal-unpublished`, 422, with `blockers`). "
        "`state` is `draft` (default) or `published`; anything else is `api-lifecycle-invalid-state` "
        "— deprecate and retire with an update.\n\n"
        "Audited as `api_product.create`. Requires `projects:create`."
    ),
)
def create_tenant_product(
    tenant_slug: str,
    body: ApiProductInput,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ApiProductRecord:
    """Create a product.

    Args:
        tenant_slug: The tenant in the URL.
        body: The product.
        auth_data: The authenticated principal.

    Returns:
        The stored product with its resolved members.

    Raises:
        HTTPException: 400 for a malformed field, 409 when the slug is taken or a member repeats,
            422 for an unknown team or member or a portal refusal, 403 without ``projects:create``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PROJECTS, Action.CREATE, target=body.slug or body.name)
    _ = tenant_slug
    try:
        return create_product(_tenant_id(auth_data), body, actor=actor_from_auth(auth_data, user_id))
    except ApiProductValidationError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/{tenant_slug}/products/{product_slug}",
    response_model=ApiProductRecord,
    summary="Read an API product",
    description=(
        "One live API product with its members, each resolved to its entity and — for a Project "
        "member — the version it means today: a `project_latest` member follows every new publish. "
        "`portal_ready` is true when every member is published.\n\nRequires `projects:view`."
    ),
)
def read_tenant_product(
    tenant_slug: str,
    product_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ApiProductRecord:
    """Read one product with its members.

    Args:
        tenant_slug: The tenant in the URL.
        product_slug: The product's slug.
        auth_data: The authenticated principal.

    Returns:
        The product.

    Raises:
        HTTPException: 404 for an unknown product, 403 without ``projects:view``.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    _ = tenant_slug
    try:
        return get_product(_tenant_id(auth_data), product_slug)
    except ApiProductValidationError as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/{tenant_slug}/products/{product_slug}",
    response_model=ApiProductRecord,
    summary="Update an API product",
    description=(
        "Change a product's name, summary, owner team, visibility or state. Omitted fields are left "
        "alone; `null` clears `summary` or `owner_team`. The slug is not updatable. Setting "
        "`visibility` to `portal` is refused while a member is unpublished.\n\n"
        "**Lifecycle.** `state` moves draft ⇄ published → deprecated → retired, and deprecated → "
        "published reinstates. `retire_at` and `deprecation_message` describe a deprecation and are "
        "refused on any other state; a deprecated product appears on the sunset timeline. Retiring "
        "is refused before `retire_at` (`api-lifecycle-retire-early`, 409) and while any plan of the "
        "product is not retired (`api-product-plans-live`, 409); any other step is "
        "`api-lifecycle-transition` (409).\n\n"
        "Audited as `api_product.deprecate`, `.reinstate`, `.retire` or `.update`. Requires "
        "`projects:edit`."
    ),
)
def patch_tenant_product(
    tenant_slug: str,
    product_slug: str,
    body: ApiProductPatch,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ApiProductRecord:
    """Update a product.

    Args:
        tenant_slug: The tenant in the URL.
        product_slug: The product's slug.
        body: The fields to change.
        auth_data: The authenticated principal.

    Returns:
        The updated product with its members.

    Raises:
        HTTPException: 404 for an unknown product, 400 for a malformed field, 422 for an unknown
            team or a portal refusal, 403 without ``projects:edit``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT, target=product_slug)
    _ = tenant_slug
    try:
        return update_product(_tenant_id(auth_data), product_slug, body, actor=actor_from_auth(auth_data, user_id))
    except ApiProductValidationError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{tenant_slug}/products/{product_slug}",
    response_model=ApiProductDeleteResponse,
    summary="Delete an API product",
    description=(
        "Soft-delete a product; its slug is free again and its `includes` edges leave the "
        "dependency graph. The Projects and MCP servers it bundled are untouched.\n\n"
        "Audited as `api_product.delete`. Requires `projects:delete`."
    ),
)
def delete_tenant_product(
    tenant_slug: str,
    product_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ApiProductDeleteResponse:
    """Delete a product.

    Args:
        tenant_slug: The tenant in the URL.
        product_slug: The product's slug.
        auth_data: The authenticated principal.

    Returns:
        The deleted product's slug.

    Raises:
        HTTPException: 404 for an unknown product, 403 without ``projects:delete``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PROJECTS, Action.DELETE, target=product_slug)
    _ = tenant_slug
    try:
        slug = delete_product(_tenant_id(auth_data), product_slug, actor=actor_from_auth(auth_data, user_id))
    except ApiProductValidationError as exc:
        raise _http_error(exc) from exc
    return ApiProductDeleteResponse(slug=slug)


@router.get(
    "/{tenant_slug}/products/{product_slug}/members",
    response_model=ApiProductMemberListResponse,
    summary="List an API product's members",
    description=(
        "The product's members, each resolved to its entity and (for a Project) the version it "
        "means today, with whether it is published.\n\nRequires `projects:view`."
    ),
)
def list_tenant_product_members(
    tenant_slug: str,
    product_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ApiProductMemberListResponse:
    """List a product's members.

    Args:
        tenant_slug: The tenant in the URL.
        product_slug: The product's slug.
        auth_data: The authenticated principal.

    Returns:
        The members.

    Raises:
        HTTPException: 404 for an unknown product, 403 without ``projects:view``.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    _ = tenant_slug
    try:
        members = list_members(_tenant_id(auth_data), product_slug)
    except ApiProductValidationError as exc:
        raise _http_error(exc) from exc
    return ApiProductMemberListResponse(members=members, count=len(members))


@router.post(
    "/{tenant_slug}/products/{product_slug}/members",
    response_model=ApiProductRecord,
    status_code=201,
    summary="Add a member to an API product",
    description=(
        "Include a Project (`project_latest`, or `project_version` with a `version` label or a "
        "`2.x` range), an MCP server (`mcp_server`) or a catalog item (`catalog_item`), by id or "
        "slug, optionally in one `environment`. Adding an unpublished member to a `portal` product "
        "is refused (422, with `blockers`).\n\n"
        "Audited as `api_product.member.add`. Requires `projects:edit`."
    ),
)
def add_tenant_product_member(
    tenant_slug: str,
    product_slug: str,
    body: ApiProductMemberInput,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ApiProductRecord:
    """Add a member.

    Args:
        tenant_slug: The tenant in the URL.
        product_slug: The product's slug.
        body: The member.
        auth_data: The authenticated principal.

    Returns:
        The product with its members.

    Raises:
        HTTPException: 404 for an unknown product, 400 for a malformed member, 409 for a duplicate,
            422 for an unknown ref or a portal refusal, 403 without ``projects:edit``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT, target=product_slug)
    _ = tenant_slug
    try:
        return add_member(_tenant_id(auth_data), product_slug, body, actor=actor_from_auth(auth_data, user_id))
    except ApiProductValidationError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{tenant_slug}/products/{product_slug}/members/{member_id}",
    response_model=ApiProductRecord,
    summary="Remove a member from an API product",
    description=(
        "Remove one member by its id (from the product's `members`). The entity itself is "
        "untouched.\n\nAudited as `api_product.member.remove`. Requires `projects:edit`."
    ),
)
def remove_tenant_product_member(
    tenant_slug: str,
    product_slug: str,
    member_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ApiProductRecord:
    """Remove a member.

    Args:
        tenant_slug: The tenant in the URL.
        product_slug: The product's slug.
        member_id: The member's id.
        auth_data: The authenticated principal.

    Returns:
        The product with its remaining members.

    Raises:
        HTTPException: 404 for an unknown product or member, 403 without ``projects:edit``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT, target=product_slug)
    _ = tenant_slug
    try:
        return remove_member(
            _tenant_id(auth_data), product_slug, member_id, actor=actor_from_auth(auth_data, user_id)
        )
    except ApiProductValidationError as exc:
        raise _http_error(exc) from exc
