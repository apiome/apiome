"""Apigee connector source — CDG-1.5 (#5956).

FMT-7.3 (:mod:`app.apigee_import_source`) reads an Apigee proxy bundle, but someone has to download
each revision by hand and the catalog goes stale. This source reads the Apigee Management API live.

**Access: a Google credential, stored sealed.** The connector's scope names the Apigee organization
and, optionally, the environments to read (all of them when omitted)::

    {"organization": "acme-prod", "environments": ["test", "prod"]}

The credential is stored with ``PUT …/credentials`` as ``{"credentialJson": "<JSON>"}``: either a
**service-account key** (``"type": "service_account"``) or a **workload identity federation**
configuration (``"type": "external_account"``), so no long-lived key is needed where the deployment
has an external identity. ``google-auth`` turns either into an access token for the
``https://www.googleapis.com/auth/cloud-platform`` scope. Grant the principal the **Apigee
Read-only Admin** role (``roles/apigee.readOnlyAdmin``) on the organization.

**Inventory**: ``GET https://apigee.googleapis.com/v1/organizations/{org}/apis`` (the proxies),
``…/apis/{api}/revisions`` and ``…/environments/{env}/deployments``. **One API is one catalog item**:
each environment it is deployed to is its own inventory row — environment, deployed revision as the
remote revision, deployment start time as the update time — and all of an API's rows share the item,
so a proxy deployed to ``test`` and ``prod`` at different revisions is one item with both revisions.
A proxy deployed nowhere is recorded as ``discovered`` (its latest revision) and is not imported.

**Definitions**: ``…/apis/{api}/revisions/{rev}?format=bundle`` (the bundle zip) is imported by the
FMT-7.3 adapter through archive intake, exactly as an uploaded bundle is — so a bundle's declared
conditions (a route rule with no target endpoint, an unreducible flow condition) are on the item.

**Failures** name the cause: a refused credential (``invalid_grant`` …), a missing IAM permission
(``apigee.deployments.list``), or an access token without the ``cloud-platform`` OAuth scope.
Hub-declared owners from Apigee API hub are not read yet.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import quote

import httpx

from .catalog_connector_sync import ConnectorRefreshSource, register_connector_source
from .catalog_connectors import CODE_INVALID, ConnectorError, build_connector_http_client
from .refresh_source import ERROR_CLASS_AUTH, FetchedDocument, RefreshCandidate, RefreshSourceError

__all__ = [
    "APIGEE_BASE",
    "ApigeeSource",
    "CLOUD_PLATFORM_SCOPE",
    "ERROR_CLASS_INVALID_CONFIGURATION",
    "KIND",
    "validate_apigee_scope",
]

KIND = "apigee"

#: The Apigee Management API.
APIGEE_BASE = "https://apigee.googleapis.com/v1"
#: The OAuth scope every Apigee Management API call needs.
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

#: Error class for a connector that cannot authenticate at all (no or an unusable credential).
ERROR_CLASS_INVALID_CONFIGURATION = "invalid-configuration"

#: Finding codes (``summary.findings[].code``).
FINDING_ORGANIZATION_EMPTY = "organization-empty"

_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_SCOPE_KEYS = frozenset({"organization", "environments"})
_MAX_ENVIRONMENTS = 64
_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_CREDENTIAL_TYPES = ("service_account", "external_account")


# ---------------------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------------------


def validate_apigee_scope(scope: Mapping[str, Any], base_url: Optional[str]) -> None:
    """Check an ``apigee`` scope: ``organization`` and an optional ``environments`` list.

    Raises:
        ConnectorError: ``connector-invalid`` for a base URL (the API endpoint is fixed), an unknown
            key, or a malformed organization or environment name.
    """
    if base_url:
        raise ConnectorError(CODE_INVALID, "An apigee connector takes no base URL; the Apigee API endpoint is fixed.")
    unknown = sorted(set(scope) - _SCOPE_KEYS)
    if unknown:
        raise ConnectorError(CODE_INVALID, f"Unknown apigee scope key(s): {', '.join(unknown)}.")
    if not isinstance(scope.get("organization"), str) or not _NAME.fullmatch(scope["organization"]):
        raise ConnectorError(
            CODE_INVALID, "organization must be the Apigee organization name (lower-case, digits, '-')."
        )
    environments = scope.get("environments")
    if environments is not None and (
        not isinstance(environments, list)
        or len(environments) > _MAX_ENVIRONMENTS
        or not all(isinstance(e, str) and _NAME.fullmatch(e) for e in environments)
        or len(set(environments)) != len(environments)
    ):
        raise ConnectorError(
            CODE_INVALID, f"environments must list up to {_MAX_ENVIRONMENTS} distinct Apigee environment names."
        )


# ---------------------------------------------------------------------------------------
# google-auth over the connector's guarded HTTP client
# ---------------------------------------------------------------------------------------


def _auth_request_class():
    """A ``google.auth.transport.Request`` that sends through an httpx client (lazy import)."""
    from google.auth.transport import Request, Response

    class _Response(Response):
        def __init__(self, response: httpx.Response) -> None:
            self._response = response

        @property
        def status(self) -> int:
            return self._response.status_code

        @property
        def headers(self) -> Mapping[str, str]:
            return self._response.headers

        @property
        def data(self) -> bytes:
            return self._response.content

    class _HttpxRequest(Request):
        def __init__(self, client: httpx.Client) -> None:
            self._client = client

        def __call__(self, url, method="GET", body=None, headers=None, timeout=None, **kwargs):  # noqa: ANN001
            from google.auth import exceptions

            try:
                response = self._client.request(method, url, content=body, headers=headers, timeout=timeout or 30)
            except httpx.HTTPError as exc:
                raise exceptions.TransportError(f"{type(exc).__name__}") from exc
            return _Response(response)

    return _HttpxRequest


def _google_error(response: httpx.Response, what: str) -> RefreshSourceError:
    """An Apigee/Google API refusal, naming the missing permission or OAuth scope when Google says."""
    try:
        error = (response.json() or {}).get("error") or {}
    except ValueError:
        error = {}
    message = str(error.get("message") or response.text or "")[:400]
    status = str(error.get("status") or f"HTTP {response.status_code}")
    reason, permission = None, None
    for detail in error.get("details") or []:
        if isinstance(detail, Mapping) and str(detail.get("@type", "")).endswith("ErrorInfo"):
            reason = detail.get("reason")
            permission = (detail.get("metadata") or {}).get("permission")
    if reason == "ACCESS_TOKEN_SCOPE_INSUFFICIENT":
        text = (
            f"The access token lacks the required OAuth scope {CLOUD_PLATFORM_SCOPE} for {what} "
            f"(ACCESS_TOKEN_SCOPE_INSUFFICIENT): {message}"
        )
    elif permission:
        text = f"Missing permission {permission} for {what} ({reason or status}): {message}"
    else:
        text = f"Apigee refused {what} ({status}): {message}"
    auth = response.status_code in (401, 403)
    return RefreshSourceError(text, http_status=response.status_code, error_class=ERROR_CLASS_AUTH if auth else None)


class _Apigee:
    """An authenticated Apigee Management API client for one organization.

    Args:
        organization: The Apigee organization.
        credentials: ``{"credentialJson": "…"}``.
        transport: An httpx transport override (tests drive a fake Google through it).
    """

    def __init__(
        self, organization: str, credentials: Optional[Mapping[str, str]], transport: Optional[httpx.BaseTransport]
    ) -> None:
        self.organization = organization
        self._credentials = credentials or {}
        kwargs: Dict[str, Any] = {"timeout": _TIMEOUT, "follow_redirects": False}
        if transport is not None:
            kwargs["transport"] = transport
        self._client = build_connector_http_client(**kwargs)
        self._google: Any = None

    def token(self) -> str:
        """A ``cloud-platform`` access token from the stored credential (refreshed when expired)."""
        from google.auth import exceptions, load_credentials_from_dict

        if self._google is None:
            raw = self._credentials.get("credentialJson")
            if not raw:
                raise RefreshSourceError(
                    "No credential is stored for this connector; set it with PUT …/credentials "
                    '({"credentialJson": "…"}).',
                    error_class=ERROR_CLASS_INVALID_CONFIGURATION,
                )
            try:
                info = json.loads(raw)
            except ValueError as exc:
                raise RefreshSourceError(
                    "The stored credential is not JSON (a service-account key or an external-account configuration).",
                    error_class=ERROR_CLASS_INVALID_CONFIGURATION,
                ) from exc
            if not isinstance(info, dict) or info.get("type") not in _CREDENTIAL_TYPES:
                raise RefreshSourceError(
                    f"The stored credential's type must be one of {', '.join(_CREDENTIAL_TYPES)}.",
                    error_class=ERROR_CLASS_INVALID_CONFIGURATION,
                )
            try:
                self._google, _ = load_credentials_from_dict(info, scopes=[CLOUD_PLATFORM_SCOPE])
            except exceptions.GoogleAuthError as exc:
                raise RefreshSourceError(
                    f"The stored credential cannot be used: {exc}", error_class=ERROR_CLASS_INVALID_CONFIGURATION
                ) from exc
        if not self._google.valid:
            try:
                self._google.refresh(_auth_request_class()(self._client))
            except exceptions.RefreshError as exc:
                raise RefreshSourceError(
                    f"Google refused the connector's credential: {exc}", http_status=401, error_class=ERROR_CLASS_AUTH
                ) from exc
            except exceptions.TransportError as exc:
                raise RefreshSourceError(f"Google's token endpoint did not answer: {exc}") from exc
        return str(self._google.token)

    def get(self, path: str, what: str, *, params: Optional[Dict[str, str]] = None) -> httpx.Response:
        """GET one path below ``/organizations/{org}`` with the access token."""
        url = f"{APIGEE_BASE}/organizations/{quote(self.organization)}{path}"
        try:
            response = self._client.get(url, params=params, headers={"Authorization": f"Bearer {self.token()}"})
        except httpx.HTTPError as exc:
            raise RefreshSourceError(f"Apigee did not answer {what}: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise _google_error(response, what)
        return response

    def json(self, path: str, what: str) -> Any:
        try:
            return self.get(path, what).json()
        except ValueError as exc:
            raise RefreshSourceError(f"Apigee answered {what} with something that is not JSON.") from exc


# ---------------------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------------------


def _millis(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(int(str(value)) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _latest(revisions: List[Any]) -> Optional[str]:
    numeric = [str(r) for r in revisions if str(r).isdigit()]
    return max(numeric, key=int) if numeric else (str(revisions[-1]) if revisions else None)


class ApigeeSource(ConnectorRefreshSource):
    """``apigee``: every proxy of one organization, one inventory row per environment it is deployed to.

    Args:
        connector: The connector row (scope: ``organization``, optional ``environments``).
        credentials: ``{"credentialJson": "…"}`` — a service-account key or an external-account config.
        transport: An httpx transport override (tests).
    """

    def __init__(
        self,
        connector: Mapping[str, Any],
        credentials: Optional[Dict[str, str]] = None,
        *,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        super().__init__(connector, credentials)
        self.findings: List[Dict[str, Any]] = []
        self._transport = transport
        self._api: Optional[_Apigee] = None

    @property
    def scope(self) -> Mapping[str, Any]:
        value = self.connector.get("scope")
        return value if isinstance(value, Mapping) else {}

    @property
    def organization(self) -> str:
        return str(self.scope.get("organization"))

    def api(self) -> _Apigee:
        if self._api is None:
            self._api = _Apigee(self.organization, self.credentials, self._transport)
        return self._api

    def _environments(self) -> List[str]:
        configured = self.scope.get("environments")
        if configured:
            return list(configured)
        listed = self.api().json("/environments", "the environment list")
        return [str(e) for e in listed] if isinstance(listed, list) else []

    def list_candidates(self) -> List[RefreshCandidate]:
        """List the proxies and every environment deployment of each (see the module docstring)."""
        self.findings = []
        api = self.api()
        body = api.json("/apis", "the API proxy list")
        proxies = [
            str(p.get("name")) for p in (body or {}).get("proxies") or [] if isinstance(p, Mapping) and p.get("name")
        ]
        deployments: Dict[str, List[Dict[str, Any]]] = {}
        for environment in self._environments():
            listed = api.json(f"/environments/{quote(environment)}/deployments", f"the deployments of {environment}")
            for deployment in (listed or {}).get("deployments") or []:
                if isinstance(deployment, Mapping) and deployment.get("apiProxy"):
                    deployments.setdefault(str(deployment["apiProxy"]), []).append(
                        {**dict(deployment), "environment": deployment.get("environment") or environment}
                    )
        candidates: List[RefreshCandidate] = []
        for proxy in sorted(proxies):
            catalog_key = f"{self.organization}/{proxy}"
            deployed = sorted(deployments.get(proxy, []), key=lambda d: str(d.get("environment")))
            if not deployed:
                revisions = api.json(f"/apis/{quote(proxy)}/revisions", f"the revisions of {proxy}")
                latest = _latest(revisions if isinstance(revisions, list) else [])
                candidates.append(
                    RefreshCandidate(
                        remote_id=catalog_key,
                        name=proxy,
                        revision=latest,
                        raw={"apiProxy": proxy, "revision": latest, "deployed": False},
                        deployment={
                            "organization": self.organization,
                            "apiProxy": proxy,
                            "deployed": False,
                            "latestRevision": latest,
                            "catalogKey": catalog_key,
                        },
                    )
                )
                continue
            for deployment in deployed:
                environment = str(deployment.get("environment"))
                revision = str(deployment.get("revision"))
                candidates.append(
                    RefreshCandidate(
                        remote_id=f"{catalog_key}/{environment}",
                        name=proxy,
                        revision=revision,
                        updated_at=_millis(deployment.get("deployStartTime")),
                        environment=environment,
                        raw={"apiProxy": proxy, "revision": revision, "environment": environment, "deployed": True},
                        deployment={
                            "organization": self.organization,
                            "apiProxy": proxy,
                            "environment": environment,
                            "revision": revision,
                            "deployStartTime": deployment.get("deployStartTime"),
                            "deployed": True,
                            "catalogKey": catalog_key,
                        },
                    )
                )
        if not candidates:
            self.findings.append(
                {
                    "code": FINDING_ORGANIZATION_EMPTY,
                    "severity": "info",
                    "organization": self.organization,
                    "message": "The organization has no API proxies.",
                }
            )
        return candidates

    def should_import(self, candidate: RefreshCandidate) -> bool:
        """Only deployed revisions are imported; a proxy deployed nowhere stays ``discovered``."""
        return bool(candidate.raw.get("deployed"))

    def fetch(self, candidate: RefreshCandidate) -> FetchedDocument:
        """Download the deployed revision's bundle (``?format=bundle``) for the FMT-7.3 adapter."""
        proxy, revision = str(candidate.raw["apiProxy"]), str(candidate.raw["revision"])
        response = self.api().get(
            f"/apis/{quote(proxy)}/revisions/{quote(revision)}",
            f"the bundle of {proxy} revision {revision}",
            params={"format": "bundle"},
        )
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", proxy).strip("-") or "proxy"
        return FetchedDocument(
            content=response.content,
            filename=f"{slug}-rev{revision}.zip",
            import_kind=KIND,
            revision=revision,
            source_uri=(
                f"https://console.cloud.google.com/apigee/proxies/{quote(proxy)}/overview"
                f"?project={quote(self.organization)}"
            ),
        )

    def explain_unchanged(self, candidate: RefreshCandidate) -> str:
        """Why a deployment was not re-imported: the deployed revision has not changed."""
        return (
            f"Revision {candidate.revision} of {candidate.name} deployed to {candidate.environment} is unchanged "
            "since the last import, so it was not re-imported."
        )

    def describe(self) -> Dict[str, Any]:
        """``{kind, connectorId, organization, environments}`` (no credentials)."""
        return {
            **super().describe(),
            "organization": self.scope.get("organization"),
            "environments": list(self.scope.get("environments") or []),
        }


register_connector_source(KIND, ApigeeSource, scope_validator=validate_apigee_scope)
