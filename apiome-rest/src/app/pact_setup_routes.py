"""``/v1/tenants/{tenant_slug}/pact-setup`` — the Contracts guided set-up, PFX-8.20 (#7317).

The HTTP face of :mod:`app.pact_setup`, for the **Set up contracts** page and ``apiome pact setup``:

* ``GET …/pact-setup`` — the six sections with their state, the facts they are derived from, the
  pacticipants proposed from projects and repositories, and the GitHub repositories the secret and
  pull-request actions can reach (``pacts:view``);
* ``PUT …/pact-setup`` — mark a section, choose the first-pact path, record the CI key just created
  (``pacts:delete``);
* ``POST …/pact-setup/github/secrets`` — write ``PACT_BROKER_BASE_URL`` and ``PACT_BROKER_TOKEN`` as
  Actions secrets into registered repositories (``pacts:delete``);
* ``POST …/pact-setup/github/pull-requests`` — open a pull request adding the can-i-deploy /
  record-deployment workflow, or with ``preview`` only answer with the file (``pacts:delete``).

The sections themselves are set up through the routes that already exist (pacticipants,
environments, publishing, contract sources, verification, commit statuses, webhooks); these routes
only add what had no route. The two GitHub actions answer per repository and never fail as a whole:
a repository that cannot be written is ``skipped`` with the reason. An unknown field is refused
(422) with its name. The tenant is always the authenticated one, never the URL's.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from .auth import validate_authentication
from .consumer_contract_store import actor_from_auth
from .database import db
from .pact_setup import (
    PactSetupPullRequestsRequest,
    PactSetupPullRequestsResponse,
    PactSetupSave,
    PactSetupSecretsRequest,
    PactSetupSecretsResponse,
    PactSetupState,
    check_broker_base_url,
)
from .pact_setup_github import open_pull_requests, write_secrets
from .pact_setup_store import read_state, record_github, save_progress
from .permissions import Action, Resource, enforce_permission, has_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pacticipants"])

_BASE = "/{tenant_slug}/pact-setup"


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _refuse(code: str, exc: ValueError) -> HTTPException:
    """A 422 carrying a stable code and the reason."""
    return HTTPException(status_code=422, detail={"code": code, "message": str(exc)})


@router.get(
    _BASE,
    response_model=PactSetupState,
    summary="Read the Contracts guided set-up",
    description=(
        "The six sections of the set-up — who talks to whom, where things run, pipelines, the first pact, the "
        "provider's side, gates — each `done`, `next` or `todo`. A section is done when what it sets up exists, "
        "whoever made it, or (pipelines, provider's side, gates) when a Contracts admin marked it; a workspace "
        "with a completed broker migration has the first two done. Also: the pacticipants proposed from "
        "projects (providers) and from registered repositories no project is read from (consumers), each with "
        "its main branch, owner team and the pacticipant that already exists for it; and the registered GitHub "
        "repositories with whether a linked account can write to them. Counts that could grow without bound "
        "stop at 100.\n\nRequires `pacts:view`. `can_edit` is `pacts:delete`."
    ),
)
def read_pact_setup(tenant_slug: str, auth_data: Dict[str, Any] = Depends(validate_authentication)) -> PactSetupState:
    """Read the set-up.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is used).
        auth_data: The authenticated principal.

    Returns:
        The set-up state.

    Raises:
        HTTPException: 403 without ``pacts:view``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    _ = tenant_slug
    can_edit = bool(has_permission(db, auth_data, Resource.PACTS, Action.DELETE))
    return read_state(db.execute_query, _tenant_id(auth_data), can_edit=can_edit)


@router.put(
    _BASE,
    response_model=PactSetupState,
    summary="Save progress of the Contracts guided set-up",
    description=(
        "Change only what is sent: `mark` sets or clears a section's by-hand mark, `first_pact_path` records "
        "the chosen way to the first pact, `ci_key` records the API key just created for CI (its id and "
        "prefix, never its secret) so a resume does not create a second one, and `forget_ci_key` clears it "
        "without revoking the key. Audited as `pacts.setup.update`.\n\nRequires `pacts:delete`."
    ),
)
def save_pact_setup(
    tenant_slug: str,
    body: PactSetupSave,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PactSetupState:
    """Save progress.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is used).
        body: The change.
        auth_data: The authenticated principal.

    Returns:
        The set-up state after the change.

    Raises:
        HTTPException: 403 without ``pacts:delete``; 422 for an unknown field or section, a CI key
            id that is not a UUID, or ``ci_key`` together with ``forget_ci_key``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.DELETE, target="pact-setup")
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        save_progress(db, tenant_id, body, actor=actor_from_auth(auth_data, user_id))
    except ValueError as exc:
        raise _refuse("pact-setup-invalid", exc) from exc
    return read_state(db.execute_query, tenant_id, can_edit=True)


@router.post(
    f"{_BASE}/github/secrets",
    response_model=PactSetupSecretsResponse,
    summary="Write the broker address and key into repositories as Actions secrets",
    description=(
        "Write `PACT_BROKER_BASE_URL` and `PACT_BROKER_TOKEN` as GitHub Actions secrets into each registered "
        "repository, with the GitHub account the repository was registered with. The token is sealed to the "
        "repository's key and sent on; it is never stored, logged or audited. Each repository answers "
        "`written`, or `skipped` with the reason (not this workspace's, not github.com, no linked account, the "
        "account may not manage secrets): nothing fails as a whole. Writing again replaces the values. "
        "Audited as `pacts.setup.github.secrets`.\n\nRequires `pacts:delete`."
    ),
)
def write_pact_setup_secrets(
    tenant_slug: str,
    body: PactSetupSecretsRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PactSetupSecretsResponse:
    """Write the two secrets.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is used).
        body: The repositories, the broker address and the key.
        auth_data: The authenticated principal.

    Returns:
        One result per repository.

    Raises:
        HTTPException: 403 without ``pacts:delete``; 422 for a broker address that is not a plain
            http(s) URL.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.DELETE, target="pact-setup/github/secrets")
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        address = check_broker_base_url(body.broker_base_url)
    except ValueError as exc:
        raise _refuse("pact-setup-invalid-broker-url", exc) from exc
    results, updates = write_secrets(db, tenant_id, body.repository_ids, broker_base_url=address, token=body.token)
    record_github(
        db,
        tenant_id,
        actor=actor_from_auth(auth_data, user_id),
        action="pacts.setup.github.secrets",
        updates=updates,
        detail={"repositories": [{"id": item.repository_id, "status": item.status} for item in results]},
    )
    return PactSetupSecretsResponse(results=results)


@router.post(
    f"{_BASE}/github/pull-requests",
    response_model=PactSetupPullRequestsResponse,
    summary="Open pull requests adding can-i-deploy and record-deployment",
    description=(
        "For each registered repository, open a pull request from the branch `apiome/contracts-setup` adding "
        "`.github/workflows/apiome-contracts.yml`: can-i-deploy for the given pacticipant and environment on "
        "every pull request and push, and record-deployment after a push to the default branch. Each "
        "repository answers `opened`, `exists` (a pull request from the set-up is already open; its branch is "
        "brought up to date), or `skipped` with the reason (the same file is already on the default branch, no "
        "linked account, a branch rule) — and always the workflow's text, so it can be added by hand. With "
        "`preview: true` GitHub is not called and every repository answers `preview`. Audited as "
        "`pacts.setup.github.pull_requests` (a preview is not).\n\nRequires `pacts:delete`."
    ),
)
def open_pact_setup_pull_requests(
    tenant_slug: str,
    body: PactSetupPullRequestsRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PactSetupPullRequestsResponse:
    """Open the pull requests.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is used).
        body: The repositories and what the workflow does.
        auth_data: The authenticated principal.

    Returns:
        One result per repository.

    Raises:
        HTTPException: 403 without ``pacts:delete``; 422 when no step is chosen or a name cannot be
            written into a workflow.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.DELETE, target="pact-setup/github/pull-requests")
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        results, updates = open_pull_requests(db, tenant_id, body)
    except ValueError as exc:
        raise _refuse("pact-setup-invalid-workflow", exc) from exc
    if not body.preview:
        record_github(
            db,
            tenant_id,
            actor=actor_from_auth(auth_data, user_id),
            action="pacts.setup.github.pull_requests",
            updates=updates,
            detail={
                "environment": body.environment,
                "repositories": [
                    {"id": item.repository_id, "status": item.status, "number": item.number} for item in results
                ],
            },
        )
    return PactSetupPullRequestsResponse(results=results)
