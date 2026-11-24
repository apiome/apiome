"""``/v1/tenants/{tenant_slug}/pact-broker`` — the matrix and can-i-deploy, PFX-1.6 (#6919).

* ``GET …/matrix`` — the Pact Broker's matrix query: ``q[][pacticipant]`` selectors with
  ``latestby``, a destination (``tag``, ``environment``, ``latest``, ``mainBranch``) and
  ``ignore[][pacticipant]``. This is what ``pact-broker can-i-deploy`` calls, unmodified: it asks
  for ``<base URL>/matrix`` and exits ``0`` when ``summary.deployable`` is true, ``1`` otherwise.
* ``GET …/can-i-deploy`` — the same question in one line: ``pacticipant``, ``version`` and ``to``
  (a tag) or ``toEnvironment``, with ``ignore``. The index's
  ``pb:can-i-deploy-pacticipant-version-to-environment`` and ``…-to-tag`` templates.

Both answer ``200`` with the Pact Broker's document — ``summary`` (``deployable``, ``reason`` and
the ``success`` / ``failed`` / ``unknown`` counts), ``notices`` and ``matrix`` rows — whatever the
verdict is. Apiome adds a ``code`` to each notice and a ``reason`` to each row.

**Retry while unknown.** When ``summary.deployable`` is ``null`` a verification result is still
missing; the response carries ``Retry-After`` (seconds) to say when asking again is worthwhile.
``pact-broker can-i-deploy --retry-while-unknown`` keeps asking while ``summary.unknown`` is above
zero.

Both need ``pacts:view``. A workspace API key is accepted as a bearer token, as on every broker
route. Refusals keep Apiome's ``{"detail": {"code", "message", "pointer"}}``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request

from .database import db
from .pact_broker_auth import validate_broker_authentication
from .pact_broker_routes import (
    HalJSONResponse,
    _base_url,
    _http_error,
    _pacticipant_url,
    _pair_url,
    _tenant_id,
    _version_url,
)
from .pact_matrix import (
    RETRY_AFTER_SECONDS,
    MatrixOptions,
    MatrixResult,
    MatrixRow,
    UnresolvedSelector,
    Verdict,
    deployment_verdict,
    parse_can_i_deploy_query,
    parse_matrix_query,
    row_reason,
)
from .pact_matrix_store import query_matrix, read_version_details
from .pact_publication import PactPublicationError
from .permissions import Action, Resource, enforce_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

_PREFIX = "/{tenant_slug}/pact-broker"


def _query_parameter(name: str, description: str, **schema: Any) -> Dict[str, Any]:
    """One query parameter of the OpenAPI operation."""
    return {
        "name": name,
        "in": "query",
        "required": False,
        "description": description,
        "schema": schema or {"type": "string"},
    }


_MATRIX_PARAMETERS = [
    _query_parameter(
        "q[][pacticipant]",
        "A pacticipant to put in the matrix. Repeat `q[][pacticipant]` (each followed by its own `q[][version]`, "
        "`q[][latest]`, `q[][tag]`, `q[][branch]`, `q[][environment]` or `q[][mainBranch]`) for several.",
        type="array",
        items={"type": "string"},
    ),
    _query_parameter(
        "q[][version]", "Exactly this version of the pacticipant.", type="array", items={"type": "string"}
    ),
    _query_parameter(
        "q[][latest]", "`true`: only the latest of the versions described.", type="array", items={"type": "string"}
    ),
    _query_parameter("q[][tag]", "Versions with this tag.", type="array", items={"type": "string"}),
    _query_parameter("q[][branch]", "Versions recorded on this branch.", type="array", items={"type": "string"}),
    _query_parameter(
        "q[][environment]",
        "Versions currently deployed to, or released and supported in, this environment.",
        type="array",
        items={"type": "string"},
    ),
    _query_parameter(
        "q[][mainBranch]", "`true`: versions on the pacticipant's main branch.", type="array", items={"type": "string"}
    ),
    _query_parameter(
        "latestby",
        "Collapse rows to the latest result per consumer version and provider (`cvp`), per consumer version and "
        "provider version (`cvpv`), or per consumer and provider (`cp`). Without it every result is a row.",
        type="string",
        enum=["cvp", "cvpv", "cp"],
    ),
    _query_parameter("limit", "The most rows to return.", type="integer", minimum=1, maximum=1000, default=100),
    _query_parameter(
        "environment",
        "The destination: check against every version currently in this environment (`can-i-deploy --to-environment`).",
    ),
    _query_parameter(
        "tag", "The destination: check against versions with this tag (`can-i-deploy --to`, with `latest=true`)."
    ),
    _query_parameter("latest", "`true`: check against the latest version of each other pacticipant.", type="boolean"),
    _query_parameter("mainBranch", "`true`: check against each other pacticipant's main branch.", type="boolean"),
    _query_parameter(
        "ignore[][pacticipant]",
        "A pacticipant whose rows do not count towards the verdict; `ignore[][version]` narrows it to one version.",
        type="array",
        items={"type": "string"},
    ),
    _query_parameter(
        "success[]",
        "Keep only rows with this result: `true`, `false`, or empty for rows without a result.",
        type="array",
        items={"type": "string"},
    ),
]

_CAN_I_DEPLOY_PARAMETERS = [
    {**_query_parameter("pacticipant", "The pacticipant being deployed: its name or handle."), "required": True},
    {**_query_parameter("version", "The version being deployed."), "required": True},
    _query_parameter("toEnvironment", "The environment being deployed to. `environment` is accepted too."),
    _query_parameter(
        "to", "A tag instead of an environment: check against the latest version of each other pacticipant with it."
    ),
    _query_parameter(
        "ignore",
        "A pacticipant whose rows do not count towards the verdict. Repeat for several; "
        "`ignore[][pacticipant]` with `ignore[][version]` ignores one version.",
        type="array",
        items={"type": "string"},
    ),
]

_MATRIX_EXAMPLE = {
    "summary": {
        "deployable": False,
        "reason": (
            "The verification for the pact between version 2.0.0 of Billing Service and the version of "
            "Ledger API currently in production (5.1.0) failed"
        ),
        "success": 0,
        "failed": 1,
        "unknown": 0,
    },
    "notices": [
        {
            "type": "error",
            "code": "verification-failed",
            "text": (
                "The verification for the pact between version 2.0.0 of Billing Service and the version of "
                "Ledger API currently in production (5.1.0) failed"
            ),
        }
    ],
    "matrix": [
        {
            "consumer": {"name": "Billing Service", "version": {"number": "2.0.0", "branch": "main"}},
            "provider": {"name": "Ledger API", "version": {"number": "5.1.0", "branch": "main"}},
            "pact": {"createdAt": "2026-11-24T10:00:00+00:00"},
            "verificationResult": {"success": False, "verifiedAt": "2026-11-24T10:05:00+00:00"},
            "reason": {"code": "verification-failed", "text": "verification failed"},
        }
    ],
}

_RESPONSES: Dict[Any, Any] = {
    200: {
        "description": (
            "The verdict and the rows it was reached from. `summary.deployable` is `true`, `false`, or `null` "
            "when a verification result is missing — then `Retry-After` says when to ask again."
        ),
        "headers": {
            "Retry-After": {
                "description": "Seconds to wait before asking again. Sent only while the verdict is unknown.",
                "schema": {"type": "integer"},
            }
        },
        "content": {"application/hal+json": {"example": _MATRIX_EXAMPLE}},
    },
    400: {
        "description": (
            "`pact-matrix-invalid`: the query is malformed, or names a pacticipant or an environment that "
            "does not exist. `detail.pointer` names the parameter."
        )
    },
}

# ---------------------------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------------------------


def _version(base: str, slug: str, number: str, details: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Render one side's version of a matrix row, as the Pact Broker's ``MatrixDecorator`` does.

    Args:
        base: The broker base URL.
        slug: The pacticipant's handle.
        number: The version number.
        details: The version's ``branches``, ``tags`` and ``environments``.

    Returns:
        ``number``, ``branch`` (the last branch it was recorded on), ``branchVersions`` (and the
        deprecated ``branches``), ``environments`` it is currently in, ``tags`` and a ``self`` link.
    """
    details = details or {}
    url = _version_url(base, slug, number)
    pacticipant = _pacticipant_url(base, slug)
    version = quote(number, safe="")
    branches = [
        {
            "name": branch["name"],
            "latest": bool(branch["latest"]),
            "_links": {
                "self": {
                    "title": "Version",
                    "name": number,
                    "href": f"{pacticipant}/branches/{quote(branch['name'], safe='')}/versions/{version}",
                }
            },
        }
        for branch in details.get("branches") or []
    ]
    return {
        "number": number,
        "branch": branches[-1]["name"] if branches else None,
        "branches": branches,
        "branchVersions": branches,
        "environments": [
            {
                "uuid": environment["uuid"],
                "name": environment["name"],
                "displayName": environment["displayName"],
                "production": bool(environment["production"]),
                "_links": {"self": {"href": f"{base}/environments/{environment['uuid']}"}},
            }
            for environment in details.get("environments") or []
        ],
        "_links": {"self": {"href": url}},
        "tags": [
            {
                "name": tag["name"],
                "latest": bool(tag["latest"]),
                "_links": {"self": {"href": f"{url}/tags/{quote(tag['name'], safe='')}"}},
            }
            for tag in details.get("tags") or []
        ],
    }


def _pending_fields(row: MatrixRow) -> Dict[str, Any]:
    """What the verifier was told about the pact when it verified (PFX-1.7, #6920).

    Args:
        row: A row with a verification result.

    Returns:
        ``pending`` (when the verifier's link carried it) and ``wip: true`` for a work-in-progress
        pact; empty when neither is known.
    """
    fields: Dict[str, Any] = {}
    if row.pact_pending is not None:
        fields["pending"] = row.pact_pending
    if row.wip:
        fields["wip"] = True
    return fields


def _row_document(base: str, row: MatrixRow, details: Dict[str, Dict[str, Any]], ignored: bool) -> Dict[str, Any]:
    """Render one matrix row.

    Args:
        base: The broker base URL.
        row: The row.
        details: Version details by version id.
        ignored: Whether an ``ignore`` selector covered the row.

    Returns:
        ``consumer``, ``provider`` (its ``version`` ``null`` without a result), ``pact``,
        ``verificationResult`` (``null`` without one; with ``pending`` and ``wip`` when known),
        Apiome's ``reason``, and ``ignored`` when set.
    """
    pair = _pair_url(base, row.provider_slug, row.consumer_slug)
    provider_version = None
    if row.provider_version_number is not None:
        provider_version = _version(
            base, row.provider_slug, row.provider_version_number, details.get(row.provider_version_id or "")
        )
    verification = None
    if row.success is not None:
        verification = {
            "success": row.success,
            "verifiedAt": row.verified_at,
            **_pending_fields(row),
            "_links": {
                "self": {"href": f"{pair}/pact-version/{row.pact_sha}/verification-results/{row.verification_number}"}
            },
        }
    document: Dict[str, Any] = {
        "consumer": {
            "name": row.consumer_name,
            "version": _version(
                base, row.consumer_slug, row.consumer_version_number, details.get(row.consumer_version_id)
            ),
            "_links": {"self": {"href": _pacticipant_url(base, row.consumer_slug)}},
        },
        "provider": {
            "name": row.provider_name,
            "version": provider_version,
            "_links": {"self": {"href": _pacticipant_url(base, row.provider_slug)}},
        },
        "pact": {
            "createdAt": row.pact_created_at,
            "_links": {"self": {"href": f"{pair}/version/{quote(row.consumer_version_number, safe='')}"}},
        },
        "verificationResult": verification,
        "reason": row_reason(row),
    }
    if ignored:
        document["ignored"] = True
    return document


def _matrix_document(
    base: str, result: MatrixResult, verdict: Verdict, details: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """Render a matrix query's answer the way a Pact Broker returns it.

    Args:
        base: The broker base URL.
        result: The query's rows.
        verdict: The verdict reached from them.
        details: Version details by version id.

    Returns:
        ``summary``, ``notices`` and ``matrix`` (considered rows, then ignored rows).
    """
    return {
        "summary": {"deployable": verdict.deployable, "reason": verdict.reason, **verdict.counts},
        "notices": [{"type": reason.type, "code": reason.code, "text": reason.text} for reason in verdict.reasons],
        "matrix": [_row_document(base, row, details, False) for row in result.considered_rows]
        + [_row_document(base, row, details, True) for row in result.ignored_rows],
    }


def _answer(
    request: Request,
    tenant_slug: str,
    auth_data: Dict[str, Any],
    parse: Any,
) -> HalJSONResponse:
    """Run one matrix query and render it; shared by both routes.

    Args:
        request: The request (its raw query string is what is parsed).
        tenant_slug: The tenant in the URL.
        auth_data: The authenticated principal.
        parse: :func:`parse_matrix_query` or :func:`parse_can_i_deploy_query`.

    Returns:
        ``200`` with the matrix document, and ``Retry-After`` while the verdict is unknown.

    Raises:
        HTTPException: 403 without ``pacts:view``; 400 ``pact-matrix-invalid``.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    tenant_id = _tenant_id(auth_data)
    try:
        parsed: Tuple[Sequence[UnresolvedSelector], MatrixOptions] = parse(request.url.query)
        result = query_matrix(db, tenant_id, parsed[0], parsed[1])
    except PactPublicationError as exc:
        raise _http_error(exc) from exc
    verdict = deployment_verdict(result)
    rows: List[MatrixRow] = list(result.considered_rows) + list(result.ignored_rows)
    details = read_version_details(
        db, [row.consumer_version_id for row in rows] + [row.provider_version_id for row in rows]
    )
    headers = {"Retry-After": str(RETRY_AFTER_SECONDS)} if verdict.unknown else None
    return HalJSONResponse(_matrix_document(_base_url(request, tenant_slug), result, verdict, details), headers=headers)


# ---------------------------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------------------------


@router.get(
    _PREFIX + "/matrix",
    response_class=HalJSONResponse,
    summary="Query the matrix",
    description=(
        "The matrix: which consumer versions were verified against which provider versions, and the verdict "
        "on deploying the versions asked about. This is the Pact Broker's `GET /matrix`, and what "
        "`pact-broker can-i-deploy` calls.\n\n"
        "- **Selectors** (`q[][pacticipant]` …) name the versions in question. One selector with a "
        "destination asks *can I deploy this?*; two or more ask *do these work together?*\n"
        "- **Destination**: `environment` checks against every version currently deployed to or released in "
        "that environment; `tag` with `latest=true` against the latest version with that tag; `latest=true` "
        "alone against the latest version of each other pacticipant; `mainBranch=true` (with `latest=true`) "
        "against main branches. The other pacticipants are worked out from the pacts.\n"
        "- **Verdict** (`summary.deployable`): `true` when every row that counts succeeded (or nothing "
        "depends on the version); `false` when a verification failed or a named version does not exist; "
        "`null` when a result is missing. A consumer needs its providers to be there; a provider does not "
        "need its consumers.\n"
        "- **Reasons**: `summary.reason` and `notices` use the Pact Broker's wording. Each notice has a "
        "`code` and each row a `reason` (`verified`, `verification-failed`, `pact-pending`, "
        "`no-verification-result`); `no-pact` is the notice when the environment requires a contract and "
        "the version has none.\n"
        "- **Ignore**: rows of an `ignore[][pacticipant]` are returned with `ignored: true` and do not count.\n"
        "- **Retry while unknown**: a `null` verdict comes with `Retry-After`.\n\n"
        "Always `200` when the query is valid — read `summary.deployable`, not the status. Requires `pacts:view`."
    ),
    openapi_extra={"parameters": _MATRIX_PARAMETERS},
    responses=_RESPONSES,
)
def read_matrix(
    tenant_slug: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Answer a Pact Broker matrix query.

    Args:
        tenant_slug: The tenant in the URL.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The matrix document.
    """
    return _answer(request, tenant_slug, auth_data, parse_matrix_query)


@router.get(
    _PREFIX + "/can-i-deploy",
    response_class=HalJSONResponse,
    summary="Can I deploy?",
    description=(
        "Whether one version of a pacticipant can be deployed — the index's "
        "`pb:can-i-deploy-pacticipant-version-to-environment` and `…-to-tag` links.\n\n"
        "`pacticipant` and `version` name what is being deployed. `toEnvironment` names where: the version is "
        "checked against every version of its providers and consumers currently deployed to or released in "
        "that environment. `to` names a tag instead: it is checked against the latest version of each with "
        "that tag. Give exactly one of the two. `ignore` leaves a pacticipant out of the verdict.\n\n"
        "The answer is the matrix document of `GET …/matrix`: `summary.deployable` is `true`, `false`, or "
        "`null` (a verification result is missing; `Retry-After` says when to ask again). An environment "
        "marked `contractRequired` refuses a version that has no pact at all (`no-pact`).\n\n"
        "Always `200` when the query is valid. Requires `pacts:view`."
    ),
    openapi_extra={"parameters": _CAN_I_DEPLOY_PARAMETERS},
    responses=_RESPONSES,
)
def read_can_i_deploy(
    tenant_slug: str,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_broker_authentication),
) -> HalJSONResponse:
    """Answer "can this version be deployed there?".

    Args:
        tenant_slug: The tenant in the URL.
        request: The request.
        auth_data: The authenticated principal.

    Returns:
        The matrix document.
    """
    return _answer(request, tenant_slug, auth_data, parse_can_i_deploy_query)
