"""A fake Azure (Entra ID + ARM + export blobs) for the APIM connector (CDG-1.4, #5955).

Serves the recorded responses under ``tests/fixtures/azure_apim/`` through an httpx
``MockTransport``, routed by method and path exactly as Azure would answer them. The estate:

* APIM instance ``contoso-apim`` in resource group ``rg-apis``;
* ``orders-api`` — current revision 2, plus non-current revision 1; an API-level policy (the FMT-7.2
  corpus' ``03-api-with-policy-set/policy.xml``) and an **operation-level** policy on ``get-order``;
* ``billing-api`` — revision 1, no policy (ARM answers 404);
* ``events-ws`` — a WebSocket API, which cannot be exported;
* products ``Starter`` (both HTTP APIs) and ``Unlimited`` (orders only), named values
  ``tenant-header`` and ``billing-key`` (secret), and one backend.

The API list is split across two pages (``nextLink``). Every request is recorded on
:attr:`FakeAzure.requests`, so tests can assert what was (and was not) sent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import unquote

import httpx

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "azure_apim"
RESPONSES = FIXTURES / "responses"
EXPORTS = FIXTURES / "exports"

TENANT_ID = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
CLIENT_ID = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
SUBSCRIPTION_ID = "5f1c3a2e-8d4b-4e6f-9a7c-2b1d0e3f4a5b"
RESOURCE_GROUP = "rg-apis"
SERVICE = "contoso-apim"
CLIENT_SECRET = "fake-client-secret-value"
SERVICE_PATH = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}"
    f"/providers/Microsoft.ApiManagement/service/{SERVICE}"
)

SCOPE = {
    "tenantId": TENANT_ID,
    "clientId": CLIENT_ID,
    "subscriptionId": SUBSCRIPTION_ID,
    "resourceGroup": RESOURCE_GROUP,
    "serviceName": SERVICE,
}


def response_body(name: str) -> Dict:
    """One recorded response body (``responses/{name}.json``)."""
    return json.loads((RESPONSES / f"{name}.json").read_text())


class FakeAzure:
    """The fake Azure endpoints.

    Args:
        token_status: The token endpoint's status (``401`` serves the expired-secret refusal).
        deny: ARM paths (relative to the service) answered with ``403 AuthorizationFailed``.
    """

    def __init__(self, *, token_status: int = 200, deny: Optional[List[str]] = None) -> None:
        self.token_status = token_status
        self.deny = set(deny or [])
        self.requests: List[httpx.Request] = []
        #: Response name → body served instead of the recorded one (a changed estate).
        self.overrides: Dict[str, Dict] = {}

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.url.host
        if host == "login.microsoftonline.com":
            return self._token(request)
        if host == "apimexports.blob.core.windows.net":
            name = request.url.path.rsplit("/", 1)[-1]
            path = EXPORTS / name
            if "authorization" in request.headers:
                return httpx.Response(400, text="A signed export link takes no Authorization header.")
            return httpx.Response(200, content=path.read_bytes()) if path.exists() else httpx.Response(404)
        if host == "management.azure.com":
            return self._arm(request)
        return httpx.Response(404)

    def _token(self, request: httpx.Request) -> httpx.Response:
        form = dict(httpx.QueryParams(request.content.decode()))
        if self.token_status != 200:
            return httpx.Response(self.token_status, json=response_body("token-expired-secret"))
        if form.get("grant_type") != "client_credentials" or form.get("client_id") != CLIENT_ID:
            return httpx.Response(400, json={"error": "invalid_request", "error_description": "AADSTS900144: bad form"})
        if form.get("client_secret") != CLIENT_SECRET and "client_assertion" not in form:
            return httpx.Response(
                401,
                json={"error": "invalid_client", "error_description": "AADSTS7000215: Invalid client secret provided."},
            )
        return httpx.Response(200, json=response_body("token"))

    def _arm(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") != f"Bearer {response_body('token')['access_token']}":
            return httpx.Response(401, json={"error": {"code": "InvalidAuthenticationToken", "message": "bad token"}})
        if request.url.params.get("api-version") != "2024-05-01":
            return httpx.Response(400, json={"error": {"code": "InvalidApiVersionParameter", "message": "api-version"}})
        path = unquote(request.url.path)
        if not path.startswith(SERVICE_PATH):
            return httpx.Response(404, json={"error": {"code": "ResourceNotFound", "message": path}})
        rel = path[len(SERVICE_PATH) :]
        if rel in self.deny:
            return httpx.Response(403, json=response_body("arm-authorization-failed"))
        name = self._route(rel, request.url.params)
        if name is None:
            return httpx.Response(404, json=response_body("policy-not-found"))
        return httpx.Response(200, json=self.overrides.get(name) or response_body(name))

    @staticmethod
    def _route(rel: str, params: httpx.QueryParams) -> Optional[str]:
        """The recorded response for one service-relative path, or ``None`` (404)."""
        parts = [p for p in rel.split("/") if p]
        if not parts:
            return "service"
        if parts == ["apis"]:
            return "apis-page2" if params.get("$skiptoken") == "page2" else "apis"
        if parts in (["products"], ["namedValues"], ["backends"]):
            return parts[0]
        if len(parts) == 3 and parts[0] == "products" and parts[2] == "apis":
            return f"products-{parts[1]}-apis"
        if parts[0] != "apis" or len(parts) < 2:
            return None
        api = parts[1]
        slug = api.replace(";rev=", "-rev")
        tail = parts[2:]
        if not tail:
            return (
                f"export-{slug}"
                if params.get("export") == "true" and params.get("format") == "openapi+json-link"
                else None
            )
        if tail == ["revisions"]:
            return f"revisions-{slug}" if (RESPONSES / f"revisions-{slug}.json").exists() else None
        if tail == ["operations"]:
            return f"operations-{slug}" if (RESPONSES / f"operations-{slug}.json").exists() else None
        if tail == ["policies", "policy"]:
            name = f"policy-{slug}"
        elif len(tail) == 4 and tail[0] == "operations" and tail[2:] == ["policies", "policy"]:
            name = f"policy-{slug}-{tail[1]}"
        else:
            return None
        if params.get("format") != "rawxml":
            return None
        return name if (RESPONSES / f"{name}.json").exists() else None
