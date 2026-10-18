"""A fake Kong (Konnect API and Admin API) behind an httpx transport (CDG-1.2, #5953).

:class:`FakeKong` serves the entities in ``tests/fixtures/connectors/kong/konnect_entities.json``
the way Kong does: ``{"data": [...], "offset": "<token>"}`` pages (deliberately small, so every
collection spans several pages), foreign references as ``{"id": …}``, and Kong's error bodies —
Konnect's problem JSON on the Konnect paths and ``{"message": …}`` on the Admin API. A token that
does not match (or was revoked) is a 401.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

FIXTURES = Path(__file__).parent / "fixtures" / "connectors" / "kong"
KONNECT_TOKEN = "kpat_FAKEKONNECTTOKEN0123456789abcdef"
ADMIN_TOKEN = "admin-rbac-token-0123456789"


def load_entities() -> Dict[str, List[Dict[str, Any]]]:
    """A fresh copy of the fixture entities."""
    return json.loads((FIXTURES / "konnect_entities.json").read_text())


def load_control_plane() -> Dict[str, Any]:
    """A fresh copy of the fixture control plane."""
    return json.loads((FIXTURES / "konnect_control_plane.json").read_text())


class FakeKong:
    """One control plane (Konnect) / one workspace (Admin API) over an httpx MockTransport.

    Attributes:
        entities: The collections served (edit them between syncs to simulate Kong changes).
        control_plane: The control plane served on the Konnect paths.
        token: The token Kong accepts; set it to something else to simulate revocation.
        page_size: The largest page served, whatever ``size`` asks for.
        requests: Every request served, as ``(method, path, params)``.
        auth_headers: The auth header value of every request.
    """

    def __init__(self, *, token: str = KONNECT_TOKEN, page_size: int = 2, workspace: Optional[str] = None) -> None:
        self.entities = load_entities()
        self.control_plane = load_control_plane()
        self.token = token
        self.page_size = page_size
        self.workspace = workspace
        self.requests: List[tuple] = []
        self.auth_headers: List[Optional[str]] = []

    def transport(self) -> httpx.MockTransport:
        """The transport to hand the source."""
        return httpx.MockTransport(self._handle)

    # --- serving ---------------------------------------------------------------------

    def _page(self, collection: str, request: httpx.Request) -> httpx.Response:
        rows = self.entities.get(collection, [])
        size = min(int(request.url.params.get("size", 100)), self.page_size)
        start = int(request.url.params.get("offset") or 0)
        body: Dict[str, Any] = {"data": copy.deepcopy(rows[start : start + size])}
        if start + size < len(rows):
            body["offset"] = str(start + size)
            body["next"] = f"/{collection}?offset={start + size}"
        else:
            body["offset"] = None
            body["next"] = None
        return httpx.Response(200, json=body)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append((request.method, path, dict(request.url.params)))
        konnect = path.startswith("/v2/")
        presented = request.headers.get("authorization") if konnect else request.headers.get("kong-admin-token")
        self.auth_headers.append(presented)
        expected = f"Bearer {self.token}" if konnect else self.token
        if presented != expected:
            if konnect:
                return httpx.Response(
                    401,
                    json={
                        "status": 401,
                        "title": "Unauthorized",
                        "type": "https://httpstatuses.com/401",
                        "instance": "kong:trace:1234567890",
                        "detail": "Invalid credentials",
                    },
                )
            return httpx.Response(401, json={"message": "Invalid RBAC Token"})

        plane = self.control_plane
        if path == "/v2/control-planes":
            page = {"number": 1, "size": 100, "total": 1}
            return httpx.Response(200, json={"data": [copy.deepcopy(plane)], "meta": {"page": page}})
        if path == f"/v2/control-planes/{plane['id']}":
            return httpx.Response(200, json=copy.deepcopy(plane))
        prefix = f"/v2/control-planes/{plane['id']}/core-entities/"
        if path.startswith(prefix) and path[len(prefix):] in self.entities:
            return self._page(path[len(prefix):], request)
        admin_prefix = f"/{self.workspace}/" if self.workspace else "/"
        if path.startswith(admin_prefix) and path[len(admin_prefix):] in self.entities:
            return self._page(path[len(admin_prefix):], request)
        if konnect:
            return httpx.Response(404, json={"status": 404, "title": "Not Found", "detail": "control plane not found"})
        return httpx.Response(404, json={"message": "Not found"})
