"""``/v1/tenants/{tenant_slug}/pact-broker`` — environments and deployments, PFX-1.5 (#6918).

What ``pact-broker create-environment``, ``list-environments``, ``describe-environment``,
``update-environment``, ``delete-environment``, ``record-deployment``, ``record-undeployment``,
``record-release`` and ``record-support-ended`` call, unmodified:

* ``GET|POST …/environments`` — list (``?name=``) or create environments; the index's
  ``pb:environments`` link;
* ``GET|PUT|DELETE …/environments/{uuid}`` — one environment; the index's ``pb:environment``;
* ``GET …/environments/{uuid}/deployed-versions/currently-deployed`` (``?pacticipant=``,
  ``?applicationInstance=``) and ``…/released-versions/currently-supported`` (``?pacticipant=``,
  ``?version=``) — what runs there now;
* ``POST …/pacticipants/{p}/versions/{v}/deployed-versions/environment/{uuid}`` — record a
  deployment (a version's ``pb:record-deployment`` link, one per environment); ``…/released-versions/
  environment/{uuid}`` — record a release (``pb:record-release``);
* ``GET|PATCH …/deployed-versions/{uuid}`` and ``…/released-versions/{uuid}`` — one record;
  ``PATCH {"currentlyDeployed": false}`` records an undeployment and ``{"currentlySupported": false}``
  the end of support.

How the CLI finds these: ``record-deployment`` reads the version (``pb:pacticipant-version``) and
posts to the ``pb:record-deployment`` link whose ``name`` is the environment; ``record-undeployment``
follows ``pb:environments`` to the environment, reads its ``pb:currently-deployed-deployed-versions``
for the pacticipant and patches each match's ``self``.

Reading needs ``pacts:view``; creating an environment or recording a deployment or release
``pacts:create``; replacing an environment, undeploying and ending support ``pacts:edit``; deleting
an environment ``pacts:delete``. A workspace API key is accepted as a bearer token here as on every
broker route. Responses are ``application/hal+json`` in the Pact Broker's shape; refusals keep
Apiome's ``{"detail": {"code", "message", "pointer"}}``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from fastapi import APIRouter, Depends, Path, Query, Request, Response

from .consumer_contract_store import actor_from_auth
from .database import db
from .pact_audit import audited_write
from .pact_broker_auth import validate_broker_authentication
from .pact_broker_routes import (
    HalJSONResponse,
    _base_url,
    _http_error,
    _pacticipant_url,
    _read_pact_body,
    _tenant_id,
    _version_url,
)
from .pact_environment import (
    DeployedVersionRecord,
    EnvironmentRecord,
    ReleasedVersionRecord,
    parse_application_instance,
    parse_environment_request,
    parse_flag_patch,
)
from .pact_environment_store import (
    UNSPECIFIED,
    create_environment,
    delete_environment,
    get_deployed_version,
    get_environment,
    get_released_version,
    list_currently_deployed,
    list_currently_supported,
    list_deployments_of_version,
    list_environments,
    list_releases_of_version,
    record_deployment,
    record_release,
    record_support_ended,
    record_undeployment,
    replace_environment,
)
from .pact_publication import PactPublicationError
from .pacticipant import PacticipantValidationError
from .permissions import Action, Resource, enforce_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

_PREFIX = "/{tenant_slug}/pact-broker"
_VERSION_PATH = _PREFIX + "/pacticipants/{pacticipant}/versions/{version}"

_REFUSALS = (PactPublicationError, PacticipantValidationError)

_ENVIRONMENT_EXAMPLE = {
    "name": "production",
    "displayName": "Production",
    "production": True,
    "contractRequired": True,
    "contacts": [{"name": "Team Ledger", "details": {"emailAddress": "ledger@example.com"}}],
}

_ENVIRONMENT_BODY = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "description": "The name tooling uses: one word, no spaces."},
                    "displayName": {"type": "string", "description": "The name people read; the name when omitted."},
                    "production": {"type": "boolean", "default": False},
                    "contractRequired": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Apiome only: can-i-deploy to this environment refuses a pacticipant that has no contract."
                        ),
                    },
                    "contacts": {
                        "type": "array",
                        "maxItems": 50,
                        "items": {
                            "type": "object",
                            "required": ["name"],
                            "properties": {
                                "name": {"type": "string"},
                                "details": {"type": "object", "additionalProperties": True},
                            },
                        },
                    },
                },
            },
            "example": _ENVIRONMENT_EXAMPLE,
        }
    },
}

_DEPLOYMENT_BODY = {
    "required": False,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {
                    "applicationInstance": {
                        "type": "string",
                        "description": (
                            "The instance of the environment deployed to (a region, a customer). Omit it "
                            "when the environment has one instance."
                        ),
                    },
                    "target": {"type": "string", "description": "Deprecated name of `applicationInstance`."},
                },
            },
            "example": {"applicationInstance": "eu-1"},
        }
    },
}


def _patch_body(field: str) -> Dict[str, Any]:
    """The OpenAPI body of a merge patch that sets ``field`` to false."""
    return {
        "required": True,
        "content": {
            media: {
                "schema": {"type": "object", "properties": {field: {"type": "boolean", "enum": [False]}}},
                "example": {field: False},
            }
            for media in ("application/merge-patch+json", "application/json")
        },
    }


# ---------------------------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------------------------


def _environments_url(base: str) -> str:
    """The URL of the environment collection."""
    return f"{base}/environments"


def _environment_url(base: str, environment: EnvironmentRecord) -> str:
    """The URL of one environment."""
    return f"{_environments_url(base)}/{environment.id}"


def _timestamps(body: Dict[str, Any], created_at: Optional[str], updated_at: Optional[str]) -> None:
    """Add ``createdAt``, and ``updatedAt`` when it differs, as the broker's ``Timestamps`` do."""
    body["createdAt"] = created_at
    if updated_at and updated_at != created_at:
        body["updatedAt"] = updated_at


def _environment_document(base: str, environment: EnvironmentRecord) -> Dict[str, Any]:
    """Render an environment the way a Pact Broker returns one, plus Apiome's ``contractRequired``.

    Args:
        base: The broker base URL.
        environment: The environment.

    Returns:
        The response body, with links to itself, what is deployed and released there, and the
        collection.
    """
    url = _environment_url(base, environment)
    body: Dict[str, Any] = {
        "uuid": environment.id,
        "name": environment.name,
        "displayName": environment.display_name,
        "production": environment.production,
        "contractRequired": environment.contract_required,
        "contacts": environment.contacts,
    }
    _timestamps(body, environment.created_at, environment.updated_at)
    body["_links"] = {
        "self": {"title": "Environment", "name": environment.name, "href": url},
        "pb:currently-deployed-deployed-versions": {
            "title": f"Versions currently deployed to {environment.display_name} environment",
            "href": f"{url}/deployed-versions/currently-deployed",
        },
        "pb:currently-supported-released-versions": {
            "title": f"Versions released and supported in {environment.display_name} environment",
            "href": f"{url}/released-versions/currently-supported",
        },
        "pb:environments": {"title": "Environments", "href": _environments_url(base)},
    }
    return body


def _embedded(base: str, slug: str, name: str, number: str, environment: EnvironmentRecord) -> Dict[str, Any]:
    """The ``_embedded`` pacticipant, version and environment of a deployment or release."""
    return {
        "pacticipant": {
            "name": name,
            "_links": {"self": {"title": "Pacticipant", "name": name, "href": _pacticipant_url(base, slug)}},
        },
        "version": {
            "number": number,
            "_links": {"self": {"title": "Version", "name": number, "href": _version_url(base, slug, number)}},
        },
        "environment": _environment_document(base, environment),
    }


def _deployed_url(base: str, deployed: DeployedVersionRecord) -> str:
    """The URL of one deployment."""
    return f"{base}/deployed-versions/{deployed.id}"


def _released_url(base: str, released: ReleasedVersionRecord) -> str:
    """The URL of one release."""
    return f"{base}/released-versions/{released.id}"


def _deployed_document(base: str, deployed: DeployedVersionRecord) -> Dict[str, Any]:
    """Render a deployment the way a Pact Broker returns one.

    ``record-undeployment`` matches ``applicationInstance`` (or the deprecated ``target``) and reads
    the version number from ``_embedded.version`` for its message.
    """
    body: Dict[str, Any] = {
        "uuid": deployed.id,
        "currentlyDeployed": deployed.currently_deployed,
        "target": deployed.application_instance,
        "applicationInstance": deployed.application_instance,
        "undeployedAt": deployed.undeployed_at,
        "createdAt": deployed.created_at,
        "_embedded": _embedded(
            base, deployed.pacticipant_slug, deployed.pacticipant_name, deployed.version_number, deployed.environment
        ),
        "_links": {"self": {"href": _deployed_url(base, deployed)}},
    }
    return body


def _released_document(base: str, released: ReleasedVersionRecord) -> Dict[str, Any]:
    """Render a release the way a Pact Broker returns one."""
    body: Dict[str, Any] = {"uuid": released.id, "currentlySupported": released.currently_supported}
    _timestamps(body, released.created_at, released.updated_at)
    body["supportEndedAt"] = released.support_ended_at
    body["_embedded"] = _embedded(
        base, released.pacticipant_slug, released.pacticipant_name, released.version_number, released.environment
    )
    body["_links"] = {"self": {"href": _released_url(base, released)}}
    return body


def _list_document(
    base: str, key: str, records: Sequence[Any], render: Any, self_href: str, title: str
) -> Dict[str, Any]:
    """A collection of deployments or releases: ``_embedded.<key>`` and a titled ``self`` link."""
    return {
        "_embedded": {key: [render(base, record) for record in records]},
        "_links": {"self": {"href": self_href, "title": title}},
    }


def _self_href(request: Request) -> str:
    """The URL of this request on the broker surface, with its query string."""
    base_path = request.url.path
    query = request.url.query
    root = _base_url(request, request.path_params["tenant_slug"])
    # The path after `/pact-broker` is the same on the path form and on the tenant-host alias.
    suffix = base_path.split("/pact-broker", 1)[1] if "/pact-broker" in base_path else base_path
    return f"{root}{suffix}" + (f"?{query}" if query else "")


# ---------------------------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------------------------


@router.get(
    _PREFIX + "/environments",
    response_class=HalJSONResponse,
    summary="List environments",
    description=(
        "The workspace's environments — what `pact-broker list-environments` prints and what "
        "`record-deployment`, `record-undeployment` and `record-support-ended` look an environment "
        "up in (`_links.pb:environments`, each named after its environment). `?name=` narrows the "
        "list to the environment with exactly that name.\n\nRequires `pacts:view`."
    ),
)
def read_environments(
    tenant_slug: str,
    request: Request,
    name: Optional[str] = Query(default=None, description="Only the environment with exactly this name."),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """List the workspace's environments.

    Args:
        tenant_slug: The tenant in the URL.
        request: The request.
        name: Only the environment with this name.
        auth_data: The authenticated principal.

    Returns:
        The environments, by name.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    environments = list_environments(db, _tenant_id(auth_data), name=name)
    base = _base_url(request, tenant_slug)
    return HalJSONResponse(
        {
            "_embedded": {"environments": [_environment_document(base, e) for e in environments]},
            "_links": {
                "self": {"title": "Environments", "href": _self_href(request)},
                "pb:environments": [
                    {"title": "Environment", "name": e.name, "href": _environment_url(base, e)} for e in environments
                ],
            },
        }
    )


@router.post(
    _PREFIX + "/environments",
    response_class=HalJSONResponse,
    status_code=201,
    summary="Create an environment",
    description=(
        "Create an environment — what `pact-broker create-environment --name production "
        "--production` posts. `name` is one word (no spaces) and unique in the workspace; "
        "`displayName` defaults to the name; `production` defaults to `false`. Apiome adds "
        "`contractRequired`: can-i-deploy to the environment refuses a pacticipant without a "
        "contract.\n\nAnswers `201` with the environment and its URL in `Location`. Requires "
        "`pacts:create`."
    ),
    openapi_extra={"requestBody": _ENVIRONMENT_BODY},
    responses={
        409: {"description": "`pact-environment-name-taken`: another environment has this name."},
        422: {"description": "`pact-environment-invalid`: the body is malformed; `detail.pointer` names the field."},
    },
)
@audited_write("pacts.environment.create", "pact-environments")
def post_environment(
    tenant_slug: str,
    request: Request,
    raw: bytes = Depends(_read_pact_body),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Create an environment.

    Args:
        tenant_slug: The tenant in the URL.
        request: The request.
        raw: The body, already size-limited.
        auth_data: The authenticated principal.

    Returns:
        The environment, ``201``.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE)
    try:
        environment = create_environment(
            db, _tenant_id(auth_data), parse_environment_request(raw), actor=actor_from_auth(auth_data, user_id)
        )
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    base = _base_url(request, tenant_slug)
    return HalJSONResponse(
        _environment_document(base, environment),
        status_code=201,
        headers={"Location": _environment_url(base, environment)},
    )


_NOT_FOUND = {404: {"description": "`pact-environment-not-found`: no such environment in this workspace."}}


@router.get(
    _PREFIX + "/environments/{uuid}",
    response_class=HalJSONResponse,
    summary="Read an environment",
    description=(
        "One environment by its `uuid` — the index's `pb:environment` template, and what "
        "`pact-broker describe-environment` reads. Requires `pacts:view`."
    ),
    responses=_NOT_FOUND,
)
def read_environment(
    tenant_slug: str,
    request: Request,
    uuid: str = Path(description="The environment's `uuid`, as `GET …/environments` lists it."),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Read one environment.

    Args:
        tenant_slug: The tenant in the URL.
        uuid: The environment's id.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The environment.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        environment = get_environment(db, _tenant_id(auth_data), uuid)
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    return HalJSONResponse(_environment_document(_base_url(request, tenant_slug), environment))


@router.put(
    _PREFIX + "/environments/{uuid}",
    response_class=HalJSONResponse,
    summary="Replace an environment",
    description=(
        "Replace every field of an environment — what `pact-broker update-environment` sends. "
        "The body is the same as for creating one; a field left out returns to its default. "
        "Renaming is allowed: deployments refer to the environment by `uuid`.\n\nRequires `pacts:edit`."
    ),
    openapi_extra={"requestBody": _ENVIRONMENT_BODY},
    responses={
        **_NOT_FOUND,
        409: {"description": "`pact-environment-name-taken`: another environment has this name."},
        422: {"description": "`pact-environment-invalid`: the body is malformed."},
    },
)
@audited_write("pacts.environment.update", "pact-environment/{uuid}")
def put_environment(
    tenant_slug: str,
    request: Request,
    uuid: str = Path(description="The environment's `uuid`, as `GET …/environments` lists it."),
    raw: bytes = Depends(_read_pact_body),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Replace an environment.

    Args:
        tenant_slug: The tenant in the URL.
        uuid: The environment's id.
        request: The request.
        raw: The body, already size-limited.
        auth_data: The authenticated principal.

    Returns:
        The environment as stored.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT)
    try:
        environment = replace_environment(
            db,
            _tenant_id(auth_data),
            uuid,
            parse_environment_request(raw),
            actor=actor_from_auth(auth_data, user_id),
        )
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    return HalJSONResponse(_environment_document(_base_url(request, tenant_slug), environment))


@router.delete(
    _PREFIX + "/environments/{uuid}",
    status_code=204,
    summary="Delete an environment",
    description=(
        "Delete an environment and every deployment and release recorded to it — what "
        "`pact-broker delete-environment` calls. can-i-deploy can no longer be asked about it. "
        "Answers `204`. Requires `pacts:delete`."
    ),
    responses=_NOT_FOUND,
)
@audited_write("pacts.environment.delete", "pact-environment/{uuid}")
def remove_environment(
    uuid: str = Path(description="The environment's `uuid`, as `GET …/environments` lists it."),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> Response:
    """Delete an environment.

    Args:
        uuid: The environment's id.
        auth_data: The authenticated principal.

    Returns:
        An empty ``204``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.DELETE)
    try:
        delete_environment(db, _tenant_id(auth_data), uuid)
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    return Response(status_code=204)


@router.get(
    _PREFIX + "/environments/{uuid}/deployed-versions/currently-deployed",
    response_class=HalJSONResponse,
    summary="List the versions currently deployed to an environment",
    description=(
        "What is deployed to the environment now, newest first, under `_embedded.deployedVersions` "
        "— what `pact-broker record-undeployment` reads before it patches each match.\n\n"
        "- `pacticipant` narrows to one pacticipant (handle or name; an unknown one lists nothing).\n"
        "- `applicationInstance` narrows to one instance; sent empty, to the unnamed instance. "
        "`target` is its deprecated name.\n\nRequires `pacts:view`."
    ),
    responses=_NOT_FOUND,
)
def read_currently_deployed(
    tenant_slug: str,
    request: Request,
    uuid: str = Path(description="The environment's `uuid`, as `GET …/environments` lists it."),
    pacticipant: Optional[str] = Query(default=None, description="Only this pacticipant (handle or name)."),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """List the current deployments of an environment.

    Args:
        tenant_slug: The tenant in the URL.
        uuid: The environment's id.
        request: The request (its ``applicationInstance`` / ``target`` query, read raw so an empty
            value means the unnamed instance).
        pacticipant: Only this pacticipant.
        auth_data: The authenticated principal.

    Returns:
        The deployments.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    params = request.query_params
    instance: Any = UNSPECIFIED
    for key in ("applicationInstance", "target"):
        if key in params:
            instance = params[key].strip() or None
            break
    try:
        environment, deployed = list_currently_deployed(
            db, _tenant_id(auth_data), uuid, pacticipant_ref=pacticipant, application_instance=instance
        )
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    return HalJSONResponse(
        _list_document(
            _base_url(request, tenant_slug),
            "deployedVersions",
            deployed,
            _deployed_document,
            _self_href(request),
            f"Currently deployed versions for {environment.display_name}",
        )
    )


@router.get(
    _PREFIX + "/environments/{uuid}/released-versions/currently-supported",
    response_class=HalJSONResponse,
    summary="List the versions released and supported in an environment",
    description=(
        "The releases still supported in the environment, newest first, under "
        "`_embedded.releasedVersions` — what `pact-broker record-support-ended` reads. `pacticipant` "
        "and `version` narrow the list.\n\nRequires `pacts:view`."
    ),
    responses=_NOT_FOUND,
)
def read_currently_supported(
    tenant_slug: str,
    request: Request,
    uuid: str = Path(description="The environment's `uuid`, as `GET …/environments` lists it."),
    pacticipant: Optional[str] = Query(default=None, description="Only this pacticipant (handle or name)."),
    version: Optional[str] = Query(default=None, description="Only this version number."),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """List the supported releases of an environment.

    Args:
        tenant_slug: The tenant in the URL.
        uuid: The environment's id.
        request: The request.
        pacticipant: Only this pacticipant.
        version: Only this version number.
        auth_data: The authenticated principal.

    Returns:
        The releases.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        environment, released = list_currently_supported(
            db, _tenant_id(auth_data), uuid, pacticipant_ref=pacticipant, version_number=version
        )
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    return HalJSONResponse(
        _list_document(
            _base_url(request, tenant_slug),
            "releasedVersions",
            released,
            _released_document,
            _self_href(request),
            f"Currently supported versions in {environment.display_name}",
        )
    )


# ---------------------------------------------------------------------------------------------
# Recording deployments and releases
# ---------------------------------------------------------------------------------------------

_RECORD_ERRORS = {
    404: {
        "description": (
            "`pacticipant-not-found`, `pacticipant-version-not-found` or `pact-environment-not-found`: "
            "the version must have been recorded (published a pact, or verified one) first."
        )
    },
    422: {"description": "`pact-deployment-invalid`: the body is malformed; `detail.pointer` names the field."},
}


@router.post(
    _VERSION_PATH + "/deployed-versions/environment/{uuid}",
    response_class=HalJSONResponse,
    status_code=201,
    summary="Record a deployment",
    description=(
        "Record that this version is now deployed to the environment — the version's "
        "`pb:record-deployment` link, which `pact-broker record-deployment --pacticipant Ledger "
        "--version 4f1e2d0 --environment production` posts to.\n\n"
        "- The pacticipant's previous deployment to the same environment and application "
        "instance is marked undeployed; it stays in the history.\n"
        "- Deployments to other application instances are not touched.\n"
        "- Recording the version that is already deployed there returns that deployment, `200`.\n\n"
        "`overrideCanIDeploy=true` says the deployment is recorded although can-i-deploy answered "
        "no (the Environments page's *Record it anyway*, PFX-8.12). It changes nothing about the "
        "deployment; it is written to the audit row, so an override is never silent.\n\n"
        "Answers `201` with the deployment and its URL in `Location`. Requires `pacts:create`."
    ),
    openapi_extra={"requestBody": _DEPLOYMENT_BODY},
    responses={
        200: {"description": "This version was already the current deployment; it is returned."},
        **_RECORD_ERRORS,
    },
)
@audited_write("pacts.deployment.record", "pacticipant/{pacticipant}/version/{version}/environment/{uuid}")
def post_deployment(
    tenant_slug: str,
    request: Request,
    pacticipant: str = Path(description="The pacticipant's handle, id or name."),
    version: str = Path(description="The version number, exactly as recorded."),
    uuid: str = Path(description="The environment's `uuid`, as `GET …/environments` lists it."),
    raw: bytes = Depends(_read_pact_body),
    override_can_i_deploy: bool = Query(
        default=False,
        alias="overrideCanIDeploy",
        description=(
            "The deployment is recorded although can-i-deploy answered no. Audited; changes nothing else."
        ),
    ),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Record a deployment.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant: The pacticipant's handle, id or name.
        version: The version number.
        uuid: The environment's id.
        request: The request.
        raw: The body, already size-limited.
        override_can_i_deploy: Recorded over a "no" from can-i-deploy. Only the audit row reads it
            (``audited_write`` copies every boolean parameter into the row's ``params``).
        auth_data: The authenticated principal.

    Returns:
        The deployment.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE, target=pacticipant)
    try:
        deployed, created = record_deployment(
            db,
            _tenant_id(auth_data),
            pacticipant,
            version,
            uuid,
            parse_application_instance(raw),
            actor=actor_from_auth(auth_data, user_id),
        )
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    base = _base_url(request, tenant_slug)
    return HalJSONResponse(
        _deployed_document(base, deployed),
        status_code=201 if created else 200,
        headers={"Location": _deployed_url(base, deployed)},
    )


@router.get(
    _VERSION_PATH + "/deployed-versions/environment/{uuid}",
    response_class=HalJSONResponse,
    summary="List the deployments of a version to an environment",
    description=(
        "Every deployment of this version to the environment, current or not, newest first. Requires `pacts:view`."
    ),
    responses={404: _RECORD_ERRORS[404]},
)
def read_deployments_of_version(
    tenant_slug: str,
    request: Request,
    pacticipant: str = Path(description="The pacticipant's handle, id or name."),
    version: str = Path(description="The version number, exactly as recorded."),
    uuid: str = Path(description="The environment's `uuid`, as `GET …/environments` lists it."),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """List the deployments of a version to an environment.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant: The pacticipant's handle, id or name.
        version: The version number.
        uuid: The environment's id.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The deployments.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        deployed = list_deployments_of_version(db, _tenant_id(auth_data), pacticipant, version, uuid)
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    return HalJSONResponse(
        _list_document(
            _base_url(request, tenant_slug),
            "deployedVersions",
            deployed,
            _deployed_document,
            _self_href(request),
            f"Deployed versions for {pacticipant} version {version}",
        )
    )


@router.post(
    _VERSION_PATH + "/released-versions/environment/{uuid}",
    response_class=HalJSONResponse,
    status_code=201,
    summary="Record a release",
    description=(
        "Record that this version is released to the environment — the version's "
        "`pb:record-release` link, which `pact-broker record-release` posts to. Releases do not "
        "replace each other: every released version stays supported until "
        "`record-support-ended`. Recording a release again starts supporting it again and "
        "answers `200`.\n\nThe body is ignored. Requires `pacts:create`."
    ),
    responses={
        200: {"description": "The version was already released there; it is supported again."},
        **_RECORD_ERRORS,
    },
)
@audited_write("pacts.release.record", "pacticipant/{pacticipant}/version/{version}/environment/{uuid}")
def post_release(
    tenant_slug: str,
    request: Request,
    pacticipant: str = Path(description="The pacticipant's handle, id or name."),
    version: str = Path(description="The version number, exactly as recorded."),
    uuid: str = Path(description="The environment's `uuid`, as `GET …/environments` lists it."),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Record a release.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant: The pacticipant's handle, id or name.
        version: The version number.
        uuid: The environment's id.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The release.
    """
    user_id = enforce_permission(db, auth_data, Resource.PACTS, Action.CREATE, target=pacticipant)
    try:
        released, created = record_release(
            db, _tenant_id(auth_data), pacticipant, version, uuid, actor=actor_from_auth(auth_data, user_id)
        )
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    base = _base_url(request, tenant_slug)
    return HalJSONResponse(
        _released_document(base, released),
        status_code=201 if created else 200,
        headers={"Location": _released_url(base, released)},
    )


@router.get(
    _VERSION_PATH + "/released-versions/environment/{uuid}",
    response_class=HalJSONResponse,
    summary="Read the release of a version to an environment",
    description=(
        "The release of this version to the environment, if any, under `_embedded.releasedVersions`. "
        "Requires `pacts:view`."
    ),
    responses={404: _RECORD_ERRORS[404]},
)
def read_releases_of_version(
    tenant_slug: str,
    request: Request,
    pacticipant: str = Path(description="The pacticipant's handle, id or name."),
    version: str = Path(description="The version number, exactly as recorded."),
    uuid: str = Path(description="The environment's `uuid`, as `GET …/environments` lists it."),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Read the release of a version to an environment.

    Args:
        tenant_slug: The tenant in the URL.
        pacticipant: The pacticipant's handle, id or name.
        version: The version number.
        uuid: The environment's id.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The release, in a list of none or one.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        released = list_releases_of_version(db, _tenant_id(auth_data), pacticipant, version, uuid)
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    return HalJSONResponse(
        _list_document(
            _base_url(request, tenant_slug),
            "releasedVersions",
            released,
            _released_document,
            _self_href(request),
            f"Released versions for {pacticipant} version {version}",
        )
    )


# ---------------------------------------------------------------------------------------------
# One deployment or release: read, and end it
# ---------------------------------------------------------------------------------------------

_DEPLOYED_404 = {404: {"description": "`pact-deployed-version-not-found`: no such deployment in this workspace."}}
_RELEASED_404 = {404: {"description": "`pact-released-version-not-found`: no such release in this workspace."}}


@router.get(
    _PREFIX + "/deployed-versions/{uuid}",
    response_class=HalJSONResponse,
    summary="Read a deployment",
    description="One deployment, current or not. Requires `pacts:view`.",
    responses=_DEPLOYED_404,
)
def read_deployed_version(
    tenant_slug: str,
    request: Request,
    uuid: str = Path(description="The deployment's `uuid`."),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Read one deployment.

    Args:
        tenant_slug: The tenant in the URL.
        uuid: The deployment's id.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The deployment.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        deployed = get_deployed_version(db, _tenant_id(auth_data), uuid)
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    return HalJSONResponse(_deployed_document(_base_url(request, tenant_slug), deployed))


@router.patch(
    _PREFIX + "/deployed-versions/{uuid}",
    response_class=HalJSONResponse,
    summary="Record an undeployment",
    description=(
        '`{"currentlyDeployed": false}` records that the version is no longer deployed — what '
        "`pact-broker record-undeployment` sends to each matching deployment's `self` link. The "
        "deployment stays in the history. Patching an undeployed deployment changes nothing; "
        "`true` is refused (record the deployment again instead).\n\nRequires `pacts:edit`."
    ),
    openapi_extra={"requestBody": _patch_body("currentlyDeployed")},
    responses={**_DEPLOYED_404, 422: {"description": "`pact-deployment-invalid`: `currentlyDeployed` is not `false`."}},
)
@audited_write("pacts.deployment.update", "deployed-version/{uuid}")
def patch_deployed_version(
    tenant_slug: str,
    request: Request,
    uuid: str = Path(description="The deployment's `uuid`."),
    raw: bytes = Depends(_read_pact_body),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Record an undeployment.

    Args:
        tenant_slug: The tenant in the URL.
        uuid: The deployment's id.
        request: The request.
        raw: The merge patch.
        auth_data: The authenticated principal.

    Returns:
        The deployment.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT)
    tenant_id = _tenant_id(auth_data)
    try:
        ends = parse_flag_patch(raw, "currentlyDeployed")
        deployed = record_undeployment(db, tenant_id, uuid) if ends else get_deployed_version(db, tenant_id, uuid)
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    return HalJSONResponse(_deployed_document(_base_url(request, tenant_slug), deployed))


@router.get(
    _PREFIX + "/released-versions/{uuid}",
    response_class=HalJSONResponse,
    summary="Read a release",
    description="One release, supported or not. Requires `pacts:view`.",
    responses=_RELEASED_404,
)
def read_released_version(
    tenant_slug: str,
    request: Request,
    uuid: str = Path(description="The release's `uuid`."),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Read one release.

    Args:
        tenant_slug: The tenant in the URL.
        uuid: The release's id.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The release.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    try:
        released = get_released_version(db, _tenant_id(auth_data), uuid)
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    return HalJSONResponse(_released_document(_base_url(request, tenant_slug), released))


@router.patch(
    _PREFIX + "/released-versions/{uuid}",
    response_class=HalJSONResponse,
    summary="Record the end of support for a release",
    description=(
        '`{"currentlySupported": false}` records that the release is no longer supported — what '
        "`pact-broker record-support-ended` sends. The release stays in the history; `true` is "
        "refused (record the release again instead).\n\nRequires `pacts:edit`."
    ),
    openapi_extra={"requestBody": _patch_body("currentlySupported")},
    responses={
        **_RELEASED_404,
        422: {"description": "`pact-deployment-invalid`: `currentlySupported` is not `false`."},
    },
)
@audited_write("pacts.release.update", "released-version/{uuid}")
def patch_released_version(
    tenant_slug: str,
    request: Request,
    uuid: str = Path(description="The release's `uuid`."),
    raw: bytes = Depends(_read_pact_body),
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Record the end of support for a release.

    Args:
        tenant_slug: The tenant in the URL.
        uuid: The release's id.
        request: The request.
        raw: The merge patch.
        auth_data: The authenticated principal.

    Returns:
        The release.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.EDIT)
    tenant_id = _tenant_id(auth_data)
    try:
        ends = parse_flag_patch(raw, "currentlySupported")
        released = record_support_ended(db, tenant_id, uuid) if ends else get_released_version(db, tenant_id, uuid)
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    return HalJSONResponse(_released_document(_base_url(request, tenant_slug), released))
