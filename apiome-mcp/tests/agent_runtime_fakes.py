"""Fixtures for the AGX-2.1 invocation proxy tests (#4533).

* :data:`PETSTORE` — an OpenAPI 3.0 Petstore with list / create / get / delete, path and query
  parameters, a header parameter and a JSON body: the version a toolset exposes.
* :func:`source_item` / :func:`manifest_row` — the rows ``agent_toolset_source`` reads, shaped as the
  real SQL returns them.
* :class:`AgentDb` — a :class:`~agent_invocation_fakes.RecordingPool` responder answering the manifest,
  source, vault, quota and audit statements, so the whole agent runtime runs without Postgres.
* :class:`PetstoreUpstream` — an in-memory Petstore (or SIM mock) behind ``httpx.MockTransport`` that
  records every request it receives and can be told to fail.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from agent_invocation_fakes import RecordingPool

TENANT_ID = "11111111-1111-4111-8111-111111111111"
TOOLSET_ID = "22222222-2222-4222-8222-222222222222"
VERSION_ID = "33333333-3333-4333-8333-333333333333"
KEY_ID = "44444444-4444-4444-8444-444444444444"

PETSTORE: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Petstore", "version": "1.0.0"},
    "servers": [{"url": "https://{env}.petstore.example/v1", "variables": {"env": {"default": "api"}}}],
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "summary": "List pets.",
                "parameters": [
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 100}},
                    {
                        "name": "tags",
                        "in": "query",
                        "style": "form",
                        "explode": False,
                        "schema": {"type": "array", "items": {"type": "string"}},
                    },
                ],
                "responses": {
                    "200": {
                        "description": "A page of pets.",
                        "content": {"application/json": {"schema": {"type": "array", "items": {"type": "object"}}}},
                    }
                },
            },
            "post": {
                "operationId": "createPet",
                "summary": "Create a pet.",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["name"],
                                "properties": {"name": {"type": "string", "minLength": 1}, "tag": {"type": "string"}},
                            }
                        }
                    },
                },
                "responses": {"201": {"description": "Created.", "content": {"application/json": {"schema": {}}}}},
            },
        },
        "/pets/{petId}": {
            "parameters": [{"name": "petId", "in": "path", "required": True, "schema": {"type": "string"}}],
            "get": {
                "operationId": "showPetById",
                "summary": "Show one pet.",
                "parameters": [{"name": "X-Request-Id", "in": "header", "schema": {"type": "string"}}],
                "responses": {"200": {"description": "The pet.", "content": {"application/json": {"schema": {}}}}},
            },
            "delete": {
                "operationId": "deletePet",
                "summary": "Delete a pet.",
                "responses": {"204": {"description": "Deleted."}},
            },
        },
    },
}

#: Every Petstore operation key, and the tools they compile to.
ALL_OPERATIONS = ("DELETE /pets/{petId}", "GET /pets", "GET /pets/{petId}", "POST /pets")
ALL_TOOLS = frozenset({"listPets", "createPet", "showPetById", "deletePet"})


def source_item(document: dict[str, Any] | None = None) -> dict[str, Any]:
    """The version's source projection row (``agent_toolset_source._SOURCE``)."""
    return {
        "id": str(uuid.UUID(int=7)),
        "project_slug": "petstore",
        "version_label": "1.0.0",
        "source_format": "openapi-3.0",
        "protocol": None,
        "format_metadata": {"sourceContent": json.dumps(document or PETSTORE)},
        "tool_versions": None,
        "metadata": None,
    }


def manifest_row(**overrides: Any) -> dict[str, Any]:
    """The toolset manifest row (``agent_toolset_source._MANIFEST``)."""
    row: dict[str, Any] = {
        "toolset_id": TOOLSET_ID,
        "tenant_id": TENANT_ID,
        "version_id": VERSION_ID,
        "target": "mock",
        "body_capture_rate": 0,
        "body_capture_until": None,
        "tenant_slug": "acme",
        "project_slug": "petstore",
        "version_label": "1.0.0",
        "available": True,
        "exposed": list(ALL_OPERATIONS),
        "accepted": [],
    }
    row.update(overrides)
    return row


@dataclass
class AgentDb:
    """Answers the agent runtime's SQL. Mutate the attributes to change what the next request sees.

    Attributes:
        manifest: The manifest row, or ``None`` for "no such toolset".
        source: The source row, or ``None`` for "no readable source".
        bindings: Upstream credential rows (``agent_upstream_auth._BINDINGS``).
    """

    manifest: dict[str, Any] | None = field(default_factory=manifest_row)
    source: dict[str, Any] | None = field(default_factory=source_item)
    bindings: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, sql: str, params: Any) -> Any:
        if "FROM apiome.agent_toolsets ts" in sql and "exposed" in sql:
            return self.manifest
        if "source_tool_versions" in sql:
            return self.source
        if "FROM apiome.upstream_credentials" in sql:
            return self.bindings
        if "agent_key_quota" in sql:
            return {"license_type": "free", "rps": None, "daily_calls": None}
        if "agent_key_call_count" in sql:
            return {"calls": 0}
        if "INSERT INTO apiome.agent_invocations" in sql:
            return (str(uuid.uuid4()),)
        return None

    def pool(self) -> RecordingPool:
        """A recording pool answered by this database."""
        return RecordingPool(self)


def invocation_rows(pool: RecordingPool) -> list[dict[str, Any]]:
    """The ``agent_invocations`` rows the pool recorded, as dictionaries of the INSERT columns."""
    columns = (
        "tenant_id",
        "key_id",
        "toolset_id",
        "tool_name",
        "target",
        "invoked_at",
        "latency_ms",
        "outcome",
        "error_code",
        "http_status",
        "request_bytes",
        "response_bytes",
        "sampled",
    )
    return [
        dict(zip(columns, params, strict=True))
        for sql, params in pool.statements
        if "INSERT INTO apiome.agent_invocations" in sql
    ]


#: Given a request, return a response to answer it instead of the Petstore (or ``None``).
Override = Callable[[httpx.Request], httpx.Response | None]


class PetstoreUpstream:
    """An in-memory Petstore behind ``httpx.MockTransport``; records what it receives.

    Attributes:
        requests: Every request received, in order.
        pets: The store, by id.
        override: When set, answers requests first (to simulate failures).
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.pets: dict[str, dict[str, Any]] = {"1": {"id": "1", "name": "Rex", "tag": "dog"}}
        self.override: Override | None = None

    def transport(self) -> httpx.MockTransport:
        """The transport to build an ``httpx.AsyncClient`` with."""
        return httpx.MockTransport(self.handle)

    def client(self) -> httpx.AsyncClient:
        """An ``httpx.AsyncClient`` that talks to this upstream (redirects off, like the runtime's)."""
        return httpx.AsyncClient(transport=self.transport(), follow_redirects=False)

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Serve one request."""
        self.requests.append(request)
        if self.override is not None:
            answer = self.override(request)
            if answer is not None:
                return answer
        path = request.url.path
        segments = [part for part in path.split("/") if part]
        if segments[-1:] == ["pets"] and request.method == "GET":
            return httpx.Response(200, json=list(self.pets.values()))
        if segments[-1:] == ["pets"] and request.method == "POST":
            body = json.loads(request.content or b"{}")
            pet = {"id": str(len(self.pets) + 1), **body}
            self.pets[pet["id"]] = pet
            return httpx.Response(201, json=pet)
        if len(segments) >= 2 and segments[-2] == "pets":
            pet_id = segments[-1]
            if pet_id not in self.pets:
                return httpx.Response(404, json={"detail": f"pet {pet_id} not found"})
            if request.method == "DELETE":
                del self.pets[pet_id]
                return httpx.Response(204)
            return httpx.Response(200, json=self.pets[pet_id])
        return httpx.Response(404, json={"detail": "no route"})
