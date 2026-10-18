"""Azure API Management connector source — CDG-1.4 (#5955).

FMT-7.2 (:mod:`app.azure_apim_import_source`) reads an APIM API definition together with its
policy documents, but someone has to export each one by hand and the catalog goes stale. This
source reads them live from Azure Resource Manager (ARM).

**Access: a service principal with a read-only role.** The connector's scope names the Entra ID
(Azure AD) application and the APIM instance; none of it is secret::

    {"tenantId": "<directory id>", "clientId": "<application id>",
     "subscriptionId": "<subscription id>", "resourceGroup": "rg-apis",
     "serviceName": "contoso-apim", "authMethod": "client-secret",
     "includeNonCurrentRevisions": false}

* ``authMethod: "client-secret"`` (the default) — the application's client secret is stored with
  ``PUT …/credentials`` as ``{"clientSecret": "…"}``, sealed and never returned.
* ``authMethod: "federated"`` — no secret is stored: Apiome presents its own workload-identity
  token (the file named by ``AZURE_FEDERATED_TOKEN_FILE``) as a client assertion, which the
  application trusts through a federated credential.

Either way Apiome asks ``login.microsoftonline.com`` for an ARM token (client-credentials grant,
scope ``https://management.azure.com/.default``). Grant the application the built-in
**API Management Service Reader Role** on the APIM instance; the connector only reads.

**Inventory** (``api-version=2024-05-01``): ``GET …/service/{svc}`` for the gateway URL, then
``…/apis`` and, per API, ``…/apis/{api}/revisions``; ``…/products`` with ``…/products/{p}/apis``;
``…/namedValues`` (names only — a value may be a secret) and ``…/backends``. **The current revision
of each API is one catalog item**, served on the gateway URL; its environment is the APIM instance.
A non-current revision is recorded as an item with status ``discovered`` and is not imported unless
the scope sets ``includeNonCurrentRevisions``. An API type APIM cannot export as OpenAPI
(WebSocket, GraphQL, gRPC) is reported as a finding.

**Definitions.** ``GET …/apis/{api}?export=true&format=openapi+json-link`` returns a short-lived
link; the definition is downloaded from it. The API's policy (``…/policies/policy``) and each
operation's (``…/operations/{op}/policies/policy``) are read as raw XML. The definition, the policy
files and a ``service.json`` ARM template naming the named values and backends are packed into one
archive and imported by the FMT-7.2 adapter as a fileset — the same input a hand-made upload of the
same files is, so the item is identical to a direct import.

**Products become tags** on the catalog item (the project's tag list), named after the product's
display name; a tag this connector added for a product the API has left is removed.

**Freshness.** APIM does not change an API's revision number when a policy changes, so every sync
fetches each API and the engine compares the archive's digest: identical content is re-anchored,
not re-imported. The catalog revision label is ``rev{n}-{digest}``.

**Failures.** A refused token request fails the run as ``auth`` with Entra ID's error code in the
message (``AADSTS7000222`` for an expired client secret), and the connector turns ``failing``. An
ARM refusal names ARM's error code (``AuthorizationFailed`` …) and the HTTP status.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import zipfile
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional
from urllib.parse import quote

import httpx

from .catalog_connector_sync import ConnectorRefreshSource, register_connector_source
from .catalog_connectors import CODE_INVALID, ConnectorError, build_connector_http_client
from .refresh_source import (
    ERROR_CLASS_AUTH,
    FetchedDocument,
    RefreshCandidate,
    RefreshSourceError,
)

__all__ = [
    "API_VERSION",
    "AzureApimSource",
    "ERROR_CLASS_INVALID_CONFIGURATION",
    "KIND",
    "PRODUCT_TAG_MARKER",
    "build_policy_archive",
    "federated_token_reader",
    "validate_azure_scope",
]

KIND = "azure-apim"

#: The ARM API version every management call uses.
API_VERSION = "2024-05-01"
#: Entra ID token endpoint (``{tenant}`` filled in) and the ARM scope a token is asked for.
TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
ARM_SCOPE = "https://management.azure.com/.default"
ARM_BASE = "https://management.azure.com"

#: Error class for a connector or deployment that cannot address Azure at all.
ERROR_CLASS_INVALID_CONFIGURATION = "invalid-configuration"

#: Finding codes (``summary.findings[].code``).
FINDING_SERVICE_EMPTY = "service-empty"
FINDING_API_TYPE_NOT_EXPORTED = "api-type-not-exported"

#: Description prefix of the tags this connector manages on a catalog item (one per product).
PRODUCT_TAG_MARKER = "Azure API Management product"

#: API types APIM exports as OpenAPI (``None`` is a plain HTTP API).
_EXPORTABLE_TYPES = frozenset({"", "http", "soap"})
_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_RESOURCE_GROUP = re.compile(r"^[-\w._()]{1,90}$")
_SERVICE_NAME = re.compile(r"^[a-zA-Z](?:[a-zA-Z0-9-]{0,48}[a-zA-Z0-9])?$")
_AADSTS = re.compile(r"\bAADSTS\d+\b")
_SCOPE_KEYS = frozenset(
    {
        "tenantId",
        "clientId",
        "subscriptionId",
        "resourceGroup",
        "serviceName",
        "authMethod",
        "includeNonCurrentRevisions",
    }
)
_AUTH_METHODS = ("client-secret", "federated")
_MAX_PAGES = 200
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _read_federated_token() -> Optional[str]:
    """The deployment's workload-identity token (``AZURE_FEDERATED_TOKEN_FILE``), or ``None``."""
    path = os.environ.get("AZURE_FEDERATED_TOKEN_FILE")
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip() or None
    except OSError:
        return None


#: Reads the client assertion for ``authMethod: "federated"``. Module-level so tests substitute it.
federated_token_reader: Callable[[], Optional[str]] = _read_federated_token


# ---------------------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------------------


def validate_azure_scope(scope: Mapping[str, Any], base_url: Optional[str]) -> None:
    """Check an ``azure-apim`` scope (see the module docstring for its keys).

    Raises:
        ConnectorError: ``connector-invalid`` for a base URL (Azure endpoints are fixed), an unknown
            key, a malformed id, resource group or service name, or an unknown ``authMethod``.
    """
    if base_url:
        raise ConnectorError(CODE_INVALID, "An azure-apim connector takes no base URL; Azure endpoints are fixed.")
    unknown = sorted(set(scope) - _SCOPE_KEYS)
    if unknown:
        raise ConnectorError(CODE_INVALID, f"Unknown azure-apim scope key(s): {', '.join(unknown)}.")
    for key, label in (
        ("tenantId", "directory (tenant) id"),
        ("clientId", "application (client) id"),
        ("subscriptionId", "subscription id"),
    ):
        if not isinstance(scope.get(key), str) or not _GUID.fullmatch(scope[key]):
            raise ConnectorError(CODE_INVALID, f"{key} must be the {label}, a GUID.")
    if not isinstance(scope.get("resourceGroup"), str) or not _RESOURCE_GROUP.fullmatch(scope["resourceGroup"]):
        raise ConnectorError(CODE_INVALID, "resourceGroup must be a resource group name (1-90 characters).")
    if not isinstance(scope.get("serviceName"), str) or not _SERVICE_NAME.fullmatch(scope["serviceName"]):
        raise ConnectorError(CODE_INVALID, "serviceName must be the API Management instance name.")
    if scope.get("authMethod", "client-secret") not in _AUTH_METHODS:
        raise ConnectorError(CODE_INVALID, f"authMethod must be one of: {', '.join(_AUTH_METHODS)}.")
    if not isinstance(scope.get("includeNonCurrentRevisions", False), bool):
        raise ConnectorError(CODE_INVALID, "includeNonCurrentRevisions must be true or false.")


# ---------------------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------------------


def build_policy_archive(
    definition_name: str,
    definition: bytes,
    *,
    api_policy: Optional[str],
    operation_policies: Mapping[str, str],
    named_values: List[Mapping[str, str]],
    backends: Mapping[str, Mapping[str, Any]],
    service_name: str,
) -> bytes:
    """Pack one API for the FMT-7.2 adapter: definition, policy files and ``service.json``.

    Member names follow :func:`app.azure_apim_import_source.policy_member_scope`: ``policy.xml`` for
    the API scope and ``operations/{operation}.xml`` per operation. The archive is deterministic
    (sorted members, fixed timestamps), so identical content always has the same digest.

    Args:
        definition_name: The definition's member name (``orders-api.openapi.json``).
        definition: The exported OpenAPI bytes.
        api_policy: The API-scope policy XML, or ``None``.
        operation_policies: Operation name → policy XML.
        named_values: ``{"name", "displayName"}`` per named value (never values).
        backends: Backend id → ``{"url", "protocol"}``.
        service_name: The APIM instance, used in the ARM resource names.

    Returns:
        The ``.zip`` bytes.
    """
    members: Dict[str, bytes] = {definition_name: definition}
    if api_policy:
        members["policy.xml"] = api_policy.encode("utf-8")
    for name, xml in operation_policies.items():
        members[f"operations/{name}.xml"] = xml.encode("utf-8")
    resources = [
        {
            "type": "Microsoft.ApiManagement/service/namedValues",
            "name": f"{service_name}/{nv['name']}",
            "properties": {"displayName": nv.get("displayName") or nv["name"]},
        }
        for nv in sorted(named_values, key=lambda n: n["name"])
    ] + [
        {
            "type": "Microsoft.ApiManagement/service/backends",
            "name": f"{service_name}/{backend_id}",
            "properties": {"url": backend.get("url"), "protocol": backend.get("protocol")},
        }
        for backend_id, backend in sorted(backends.items())
    ]
    if resources:
        template = {
            "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
            "contentVersion": "1.0.0.0",
            "resources": resources,
        }
        members["service.json"] = json.dumps(template, indent=2, sort_keys=True).encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(members):
            archive.writestr(zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)), members[name])
    return buffer.getvalue()


# ---------------------------------------------------------------------------------------
# HTTP and error mapping
# ---------------------------------------------------------------------------------------


def _json(response: httpx.Response) -> Dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _token_error(response: httpx.Response) -> RefreshSourceError:
    """An Entra ID token refusal, with its ``AADSTS`` code first in the message."""
    body = _json(response)
    description = str(body.get("error_description") or body.get("error") or response.text or "")[:400]
    match = _AADSTS.search(description)
    code = match.group(0) if match else str(body.get("error") or f"HTTP {response.status_code}")
    return RefreshSourceError(
        f"Microsoft Entra ID refused the connector's credentials ({code}): {description}",
        http_status=response.status_code,
        error_class=ERROR_CLASS_AUTH,
    )


def _arm_error(response: httpx.Response, what: str) -> RefreshSourceError:
    """An ARM refusal, naming ARM's error code."""
    error = _json(response).get("error")
    error = error if isinstance(error, dict) else {}
    code = str(error.get("code") or f"HTTP {response.status_code}")
    message = str(error.get("message") or response.text or "")[:400]
    auth = response.status_code in (401, 403)
    return RefreshSourceError(
        f"Azure Resource Manager refused {what} ({code}): {message}",
        http_status=response.status_code,
        error_class=ERROR_CLASS_AUTH if auth else None,
    )


class _Arm:
    """A token-authenticated ARM client for one APIM instance.

    Args:
        scope: The connector scope.
        credentials: The unsealed credentials (``clientSecret`` for ``client-secret``).
        transport: An httpx transport override (tests drive a fake Azure through it).
    """

    def __init__(
        self,
        scope: Mapping[str, Any],
        credentials: Optional[Mapping[str, str]],
        transport: Optional[httpx.BaseTransport],
    ) -> None:
        self.scope = scope
        self.credentials = credentials or {}
        kwargs: Dict[str, Any] = {"timeout": _TIMEOUT, "follow_redirects": False}
        if transport is not None:
            kwargs["transport"] = transport
        self._client = build_connector_http_client(**kwargs)
        self._token: Optional[str] = None
        self.service_path = (
            f"/subscriptions/{scope['subscriptionId']}/resourceGroups/{quote(str(scope['resourceGroup']))}"
            f"/providers/Microsoft.ApiManagement/service/{quote(str(scope['serviceName']))}"
        )

    def close(self) -> None:
        self._client.close()

    def token(self) -> str:
        """An ARM access token (client credentials; asked for once per sync)."""
        if self._token:
            return self._token
        form = {
            "grant_type": "client_credentials",
            "client_id": str(self.scope["clientId"]),
            "scope": ARM_SCOPE,
        }
        if self.scope.get("authMethod", "client-secret") == "federated":
            assertion = federated_token_reader()
            if not assertion:
                raise RefreshSourceError(
                    "authMethod is federated but this Apiome deployment has no workload-identity token "
                    "(AZURE_FEDERATED_TOKEN_FILE); give it one or use a client secret.",
                    error_class=ERROR_CLASS_INVALID_CONFIGURATION,
                )
            form["client_assertion_type"] = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            form["client_assertion"] = assertion
        else:
            secret = self.credentials.get("clientSecret")
            if not secret:
                raise RefreshSourceError(
                    "No client secret is stored for this connector; set it with PUT …/credentials "
                    '({"clientSecret": "…"}).',
                    error_class=ERROR_CLASS_INVALID_CONFIGURATION,
                )
            form["client_secret"] = secret
        try:
            response = self._client.post(TOKEN_URL.format(tenant=quote(str(self.scope["tenantId"]))), data=form)
        except httpx.HTTPError as exc:
            raise RefreshSourceError(f"Microsoft Entra ID did not answer: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise _token_error(response)
        token = _json(response).get("access_token")
        if not isinstance(token, str) or not token:
            raise RefreshSourceError(
                "Microsoft Entra ID answered without an access token.", error_class=ERROR_CLASS_AUTH
            )
        self._token = token
        return token

    def get(
        self, url: str, what: str, *, params: Optional[Dict[str, str]] = None, allow_404: bool = False
    ) -> Optional[Dict[str, Any]]:
        """GET one ARM resource (``url`` relative to the service, or absolute for ``nextLink``)."""
        absolute = url if url.startswith("https://") else f"{ARM_BASE}{self.service_path}{url}"
        query = None if url.startswith("https://") else {"api-version": API_VERSION, **(params or {})}
        try:
            response = self._client.get(absolute, params=query, headers={"Authorization": f"Bearer {self.token()}"})
        except httpx.HTTPError as exc:
            raise RefreshSourceError(f"Azure Resource Manager did not answer {what}: {type(exc).__name__}") from exc
        if response.status_code == 404 and allow_404:
            return None
        if response.status_code != 200:
            raise _arm_error(response, what)
        return _json(response)

    def list(self, url: str, what: str) -> Iterator[Dict[str, Any]]:
        """Every item of a paged ARM collection, following ``nextLink``."""
        next_url: Optional[str] = url
        for _ in range(_MAX_PAGES):
            if not next_url:
                return
            body = self.get(next_url, what) or {}
            for item in body.get("value") or []:
                if isinstance(item, dict):
                    yield item
            next_url = body.get("nextLink") if isinstance(body.get("nextLink"), str) else None

    def download(self, link: str, what: str) -> bytes:
        """Download an export link (a short-lived signed URL: no ARM token is sent)."""
        try:
            response = self._client.get(link)
        except httpx.HTTPError as exc:
            raise RefreshSourceError(f"The export link for {what} did not answer: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise RefreshSourceError(
                f"The export link for {what} answered HTTP {response.status_code}.", http_status=response.status_code
            )
        return response.content


# ---------------------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------------------


def _name(item: Mapping[str, Any]) -> str:
    return str(item.get("name") or str(item.get("id") or "").rsplit("/", 1)[-1])


def _props(item: Mapping[str, Any]) -> Dict[str, Any]:
    props = item.get("properties")
    return dict(props) if isinstance(props, Mapping) else {}


class AzureApimSource(ConnectorRefreshSource):
    """``azure-apim``: the current revision of every API in one APIM instance (plus, on request,
    its other revisions).

    Args:
        connector: The connector row (scope: see :func:`validate_azure_scope`).
        credentials: ``{"clientSecret": …}`` for ``client-secret``; ignored for ``federated``.
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
        self._arm: Optional[_Arm] = None
        self._named_values: List[Dict[str, str]] = []
        self._backends: Dict[str, Dict[str, Any]] = {}

    @property
    def scope(self) -> Mapping[str, Any]:
        value = self.connector.get("scope")
        return value if isinstance(value, Mapping) else {}

    def arm(self) -> _Arm:
        if self._arm is None:
            self._arm = _Arm(self.scope, self.credentials, self._transport)
        return self._arm

    # --- inventory -------------------------------------------------------------------

    def _products_by_api(self) -> Dict[str, List[str]]:
        arm = self.arm()
        by_api: Dict[str, List[str]] = {}
        for product in arm.list("/products", "the product list"):
            product_name = _name(product)
            display = str(_props(product).get("displayName") or product_name)
            for api in arm.list(f"/products/{quote(product_name)}/apis", f"product {product_name}'s APIs"):
                by_api.setdefault(_name(api), []).append(display)
        return {api: sorted(set(names)) for api, names in by_api.items()}

    def list_candidates(self) -> List[RefreshCandidate]:
        """List every API's revisions, with the instance's products, named values and backends."""
        self.findings = []
        arm = self.arm()
        service = arm.get("", "the API Management instance") or {}
        service_name = str(self.scope.get("serviceName"))
        gateway = str(_props(service).get("gatewayUrl") or f"https://{service_name}.azure-api.net")
        products = self._products_by_api()
        self._named_values = [
            {"name": _name(nv), "displayName": str(_props(nv).get("displayName") or _name(nv))}
            for nv in arm.list("/namedValues", "the named values")
        ]
        self._backends = {
            _name(b): {"url": _props(b).get("url"), "protocol": _props(b).get("protocol")}
            for b in arm.list("/backends", "the backends")
        }
        candidates: List[RefreshCandidate] = []
        for api in arm.list("/apis", "the API list"):
            api_name = _name(api)
            props = _props(api)
            if ";rev=" in api_name or props.get("isCurrent") is False:
                continue  # revisions are listed below, per API
            api_type = str(props.get("apiType") or props.get("type") or "").lower()
            if api_type not in _EXPORTABLE_TYPES:
                self.findings.append(
                    {
                        "code": FINDING_API_TYPE_NOT_EXPORTED,
                        "severity": "info",
                        "apiName": api_name,
                        "apiType": api_type,
                        "message": f"{api_type} APIs cannot be exported as OpenAPI by API Management; not imported.",
                    }
                )
                continue
            revisions = list(arm.list(f"/apis/{quote(api_name)}/revisions", f"API {api_name}'s revisions"))
            if not revisions:
                revisions = [{"apiRevision": props.get("apiRevision") or "1", "isCurrent": True}]
            for revision in revisions:
                candidates.append(self._candidate(api_name, props, revision, gateway, products.get(api_name, [])))
        if not candidates:
            self.findings.append(
                {
                    "code": FINDING_SERVICE_EMPTY,
                    "severity": "info",
                    "serviceName": service_name,
                    "message": "No API in this API Management instance can be imported.",
                }
            )
        return candidates

    def _candidate(
        self, api_name: str, props: Mapping[str, Any], revision: Mapping[str, Any], gateway: str, products: List[str]
    ) -> RefreshCandidate:
        service_name = str(self.scope.get("serviceName"))
        number = str(revision.get("apiRevision") or props.get("apiRevision") or "1")
        current = revision.get("isCurrent") is not False
        api_id = api_name if current else f"{api_name};rev={number}"
        path = str(props.get("path") or "").strip("/")
        host = f"{gateway.rstrip('/')}/{path}" if path else gateway.rstrip("/")
        display = str(props.get("displayName") or api_name)
        deployment = {
            "subscriptionId": self.scope.get("subscriptionId"),
            "resourceGroup": self.scope.get("resourceGroup"),
            "serviceName": service_name,
            "apiName": api_name,
            "apiId": api_id,
            "apiRevision": number,
            "isCurrent": current,
            "isOnline": revision.get("isOnline"),
            "apiVersion": props.get("apiVersion"),
            "apiVersionSetId": props.get("apiVersionSetId"),
            "path": path,
            "gatewayUrl": gateway,
            "products": products,
            "subscriptionRequired": props.get("subscriptionRequired"),
        }
        return RefreshCandidate(
            remote_id=f"{service_name}/{api_id}",
            name=display if current else f"{display} (revision {number})",
            # No revision marker: a policy edit leaves apiRevision unchanged, so every sync fetches
            # and the engine's digest comparison decides whether anything changed.
            revision=None,
            environment=service_name,
            hosts=(host,),
            base_path=f"/{path}" if path else None,
            raw={"apiName": api_name, "apiId": api_id, "apiRevision": number, "isCurrent": current},
            deployment={k: v for k, v in deployment.items() if v is not None},
        )

    def should_import(self, candidate: RefreshCandidate) -> bool:
        """The current revision always; another revision only with ``includeNonCurrentRevisions``."""
        return bool(candidate.raw.get("isCurrent")) or bool(self.scope.get("includeNonCurrentRevisions"))

    # --- fetch -----------------------------------------------------------------------

    def _policy(self, url: str, what: str) -> Optional[str]:
        body = self.arm().get(url, what, params={"format": "rawxml"}, allow_404=True)
        if not body:
            return None
        value = _props(body).get("value")
        return value if isinstance(value, str) and value.strip() else None

    def fetch(self, candidate: RefreshCandidate) -> FetchedDocument:
        """Export the definition, read every policy, and pack them for the FMT-7.2 adapter."""
        arm = self.arm()
        api_id = str(candidate.raw["apiId"])
        quoted = quote(api_id, safe="")
        export = (
            arm.get(
                f"/apis/{quoted}",
                f"the export of API {api_id}",
                params={"export": "true", "format": "openapi+json-link"},
            )
            or {}
        )
        value = export.get("value") if isinstance(export.get("value"), Mapping) else _props(export).get("value")
        link = value.get("link") if isinstance(value, Mapping) else None
        if not isinstance(link, str) or not link.startswith("https://"):
            raise RefreshSourceError(f"API Management returned no export link for API {api_id}.")
        definition = arm.download(link, f"API {api_id}")
        api_policy = self._policy(f"/apis/{quoted}/policies/policy", f"API {api_id}'s policy")
        operation_policies: Dict[str, str] = {}
        for operation in arm.list(f"/apis/{quoted}/operations", f"API {api_id}'s operations"):
            op_name = _name(operation)
            xml = self._policy(
                f"/apis/{quoted}/operations/{quote(op_name, safe='')}/policies/policy",
                f"operation {op_name}'s policy",
            )
            if xml:
                operation_policies[op_name] = xml
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(candidate.raw["apiName"])).strip("-") or "api"
        content = build_policy_archive(
            f"{slug}.openapi.json",
            definition,
            api_policy=api_policy,
            operation_policies=operation_policies,
            named_values=self._named_values,
            backends=self._backends,
            service_name=str(self.scope.get("serviceName")),
        )
        digest = hashlib.sha256(content).hexdigest()[:12]
        return FetchedDocument(
            content=content,
            filename=f"{slug}.zip",
            import_kind=KIND,
            revision=f"rev{candidate.raw['apiRevision']}-{digest}",
            source_uri=(f"https://portal.azure.com/#resource{arm.service_path}/apim-apis"),
        )

    # --- after import ----------------------------------------------------------------

    def after_import(self, db: Any, candidate: RefreshCandidate, project_id: str) -> None:
        """Make the catalog item's product tags match the API's products.

        A tag is added per product (named after its display name). A tag this connector added
        earlier (its description starts with :data:`PRODUCT_TAG_MARKER`) for a product the API is
        no longer in is removed; tags anyone else added are never touched.
        """
        wanted = list(candidate.deployment.get("products") or [])
        description = f"{PRODUCT_TAG_MARKER} on {self.scope.get('serviceName')}"
        existing = {str(t.get("name")): t for t in db.get_tags_for_project(project_id) or []}
        for product in wanted:
            if product not in existing:
                db.create_tag(project_id, product, "default", description)
        for name, tag in existing.items():
            if name not in wanted and str(tag.get("description") or "").startswith(PRODUCT_TAG_MARKER):
                db.delete_tag(str(tag["id"]))

    def describe(self) -> Dict[str, Any]:
        """``{kind, connectorId, serviceName, resourceGroup, authMethod}`` (no credentials)."""
        return {
            **super().describe(),
            "serviceName": self.scope.get("serviceName"),
            "resourceGroup": self.scope.get("resourceGroup"),
            "authMethod": self.scope.get("authMethod", "client-secret"),
        }


register_connector_source(KIND, AzureApimSource, scope_validator=validate_azure_scope)
