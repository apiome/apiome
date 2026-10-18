"""A fake Google (OAuth token endpoint + Apigee Management API) for the Apigee connector (CDG-1.5).

Serves the recorded responses under ``tests/fixtures/apigee/`` through an httpx ``MockTransport``.
The organization ``acme-prod`` has:

* ``orders-v2`` — deployed to ``prod`` at revision **3** and to ``test`` at revision **5** (the corpus
  bundle ``02-typical-proxy-bundle.zip``; revision 5 adds a flow);
* ``store-v1`` — deployed to ``test`` at revision 1 (the corpus bundle
  ``03-composition-multi-target-bundle.zip``, whose ``no-route`` rule has no target endpoint);
* ``legacy-billing`` — deployed nowhere (revisions 1 and 2).

Every request is recorded on :attr:`FakeGoogle.requests`.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import unquote

import httpx

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "apigee"
EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "apigee"
ORG = "acme-prod"
ORG_PATH = f"/v1/organizations/{ORG}"
TOKEN = "fake-google-access-token"


def body(name: str):
    """One recorded response body (``fixtures/apigee/{name}.json``)."""
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _with_extra_flow(bundle: bytes) -> bytes:
    """The orders bundle at a later revision: one more flow, manifest revision 5."""
    source = zipfile.ZipFile(io.BytesIO(bundle))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for name in source.namelist():
            text = source.read(name).decode("utf-8")
            if name == "apiproxy/orders-v2.xml":
                text = text.replace('revision="7"', 'revision="5"')
            if name == "apiproxy/proxies/default.xml":
                text = text.replace(
                    "</Flows>",
                    '<Flow name="CancelOrder"><Request/><Response/>'
                    '<Condition>(proxy.pathsuffix MatchesPath "/orders/*") and (request.verb = "DELETE")'
                    "</Condition></Flow></Flows>",
                )
            target.writestr(name, text)
    return out.getvalue()


ORDERS_REV3 = (EXAMPLES / "02-typical-proxy-bundle.zip").read_bytes()
ORDERS_REV5 = _with_extra_flow(ORDERS_REV3)
STORE_REV1 = (EXAMPLES / "03-composition-multi-target-bundle.zip").read_bytes()
BUNDLES = {("orders-v2", "3"): ORDERS_REV3, ("orders-v2", "5"): ORDERS_REV5, ("store-v1", "1"): STORE_REV1}


class FakeGoogle:
    """The fake Google endpoints.

    Args:
        token_status: The token endpoint's status (``400`` serves ``invalid_grant``).
        deny: Apigee paths (relative to the organization) answered with a 403; the value names the
            recorded body (``permission-denied`` or ``scope-insufficient``).
    """

    def __init__(self, *, token_status: int = 200, deny: Optional[Dict[str, str]] = None) -> None:
        self.token_status = token_status
        self.deny = dict(deny or {})
        self.requests: List[httpx.Request] = []
        self.overrides: Dict[str, object] = {}

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host in ("oauth2.googleapis.com", "sts.googleapis.com"):
            if self.token_status != 200:
                return httpx.Response(self.token_status, json=body("token-invalid-grant"))
            return httpx.Response(200, json=body("token"))
        if request.url.host != "apigee.googleapis.com":
            return httpx.Response(404)
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(
                401, json={"error": {"code": 401, "status": "UNAUTHENTICATED", "message": "bad token"}}
            )
        path = unquote(request.url.path)
        if not path.startswith(ORG_PATH):
            return httpx.Response(404, json={"error": {"code": 404, "status": "NOT_FOUND", "message": path}})
        rel = path[len(ORG_PATH) :]
        if rel in self.deny:
            return httpx.Response(403, json=body(self.deny[rel]))
        if rel in self.overrides:
            return httpx.Response(200, json=self.overrides[rel])
        parts = [p for p in rel.split("/") if p]
        if parts == ["apis"]:
            return httpx.Response(200, json=body("apis"))
        if parts == ["environments"]:
            return httpx.Response(200, json=body("environments"))
        if len(parts) == 3 and parts[0] == "environments" and parts[2] == "deployments":
            return httpx.Response(200, json=body(f"deployments-{parts[1]}"))
        if len(parts) == 3 and parts[0] == "apis" and parts[2] == "revisions":
            return httpx.Response(200, json=body(f"revisions-{parts[1]}"))
        if len(parts) == 4 and parts[0] == "apis" and parts[2] == "revisions":
            bundle = BUNDLES.get((parts[1], parts[3]))
            if bundle is None or request.url.params.get("format") != "bundle":
                return httpx.Response(404, json={"error": {"code": 404, "status": "NOT_FOUND", "message": rel}})
            return httpx.Response(200, content=bundle, headers={"content-type": "application/octet-stream"})
        return httpx.Response(404, json={"error": {"code": 404, "status": "NOT_FOUND", "message": rel}})
