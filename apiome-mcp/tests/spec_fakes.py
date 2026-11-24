"""An in-memory spec that answers the SQL of the DBP-1.22 (#7205) set-based loader.

:class:`FakeSpecDb` is a :class:`~agent_invocation_fakes.RecordingPool` responder: it recognizes
each statement the spec tools run for one revision — the resolve statement and the eleven loader
statements — and returns rows for a spec with ``operations`` operations (two per path), shaped as
the V-series schema would return them. The pool records every statement, so a test can count them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

__all__ = ["DOCUMENT_STATEMENTS", "FakeSpecDb"]

_NS = UUID("7205dbb1-0000-4000-8000-000000000000")

#: Substrings that identify the loader's statements, most specific first (the operations
#: statement's ``FROM apiome.path_operation po`` also appears as a join in the detail statements).
_LOADER = (
    ("FROM apiome.class_properties cp", "properties"),
    ("FROM apiome.classes\n", "classes"),
    ("FROM apiome.version_path\n", "paths"),
    ("FROM apiome.path_operation_description pod", "descriptions"),
    ("FROM apiome.shared_path_parameter spp", "parameters"),
    ("FROM apiome.shared_path_request_body rb", "request_bodies"),
    ("FROM apiome.shared_path_response spr", "responses"),
    ("FROM apiome.path_operation po", "operations"),
    ("FROM apiome.version_security_scheme", "security"),
    ("FROM apiome.version_server", "servers"),
    ("FROM apiome.version_component_pins p", "pins"),
)

#: The statement kinds a full document load runs, in order.
DOCUMENT_STATEMENTS = (
    "classes",
    "properties",
    "paths",
    "operations",
    "descriptions",
    "parameters",
    "request_bodies",
    "responses",
    "security",
    "pins",
    "servers",
)


class FakeSpecDb:
    """One published revision with ``operations`` operations.

    Attributes:
        spec_id: The revision id the resolve statement answers for.
        row: The resolve row; change ``content_stamp`` or ``version_updated_at`` to simulate an edit.
        kinds: The kind of every statement answered, in order (``resolve`` or a loader kind).
    """

    def __init__(self, *, operations: int, visibility: str = "public") -> None:
        if operations % 2:
            raise ValueError("operations must be even (two per path)")
        self.operations = operations
        self.spec_id = uuid5(_NS, f"spec:{operations}")
        self.row: dict[str, Any] = {
            "id": self.spec_id,
            "tenant_slug": "acme",
            "project_slug": "payments",
            "version_label": "2.1.0",
            "project_description": "Payments service",
            "metadata": None,
            "version_updated_at": datetime(2026, 11, 1, 12, 0, tzinfo=UTC),
            "content_stamp": 7,
            "spec_visibility": visibility,
        }
        self.kinds: list[str] = []

    def _id(self, kind: str, n: int) -> UUID:
        return uuid5(_NS, f"{self.operations}:{kind}:{n}")

    def __call__(self, sql: str, params: Any) -> Any:
        if "tenant_slug" in sql:
            self.kinds.append("resolve")
            asked = params["spec_id"] if isinstance(params, dict) else params[0]
            return [dict(self.row)] if asked == self.spec_id else []
        for needle, kind in _LOADER:
            if needle in sql:
                self.kinds.append(kind)
                assert tuple(params) == (self.spec_id,), f"{kind} must be keyed by the revision id alone"
                return getattr(self, f"_{kind}")()
        raise AssertionError(f"unexpected statement: {sql[:120]}")

    # ── rows ────────────────────────────────────────────────────────────────────────────────
    def _classes(self) -> list[dict[str, Any]]:
        return [
            {
                "id": self._id("class", n),
                "version_id": self.spec_id,
                "name": f"Model{n:05d}",
                "description": f"Model {n}",
                "schema": {"type": "object"},
                "enabled": True,
            }
            for n in range(max(1, self.operations // 5))
        ]

    def _properties(self) -> list[dict[str, Any]]:
        return [
            {
                "id": self._id("prop", n * 3 + k),
                "class_id": self._id("class", n),
                "property_id": None,
                "name": f"field{k}",
                "description": None,
                "data": {"type": "string"},
                "parent_id": None,
                "property_source_id": None,
                "property_source_name": None,
                "property_source_data": None,
            }
            for n in range(max(1, self.operations // 5))
            for k in range(3)
        ]

    def _paths(self) -> list[dict[str, Any]]:
        return [
            {
                "id": self._id("path", n),
                "pathname": f"/resources{n:05d}/{{id}}",
                "summary": f"Resource {n}",
                "description": None,
            }
            for n in range(self.operations // 2)
        ]

    def _operations(self) -> list[dict[str, Any]]:
        return [
            {
                "id": self._id("op", n),
                "version_path_id": self._id("path", n // 2),
                "operation": "GET" if n % 2 == 0 else "POST",
            }
            for n in range(self.operations)
        ]

    def _descriptions(self) -> list[dict[str, Any]]:
        return [
            {
                "loader_path_operation_id": self._id("op", n),
                "id": self._id("desc", n),
                "summary": f"Operation {n}",
                "description": None,
                "operation_id": f"op{n}",
                "tags": [f"tag{n % 7}"],
                "deprecated": None,
                "x_private": None,
                "external_docs": None,
                "metadata": {"tags": [f"tag{n % 7}"]},
            }
            for n in range(self.operations)
        ]

    def _parameters(self) -> list[dict[str, Any]]:
        return [
            {
                "loader_path_operation_id": self._id("op", n),
                "id": self._id("param", (n // 2) * 2 + k),
                "name": "id" if k == 0 else "expand",
                "in_location": "path" if k == 0 else "query",
                "summary": None,
                "description": None,
                "data": {"type": "string", "required": k == 0},
            }
            for n in range(self.operations)
            for k in range(2)
        ]

    def _request_bodies(self) -> list[dict[str, Any]]:
        return [
            {
                "loader_path_operation_id": self._id("op", n),
                "id": self._id("body", n // 2),
                "name": f"Body{n // 2}",
                "description": None,
                "required": True,
                # json_agg may arrive as text: the loader parses it.
                "content_types": '[{"id": "c", "media_type": "application/json", "class_id": null, '
                '"class_name": null, "inline_schema": {"type": "string"}, "encoding": null, "examples": null}]',
            }
            for n in range(self.operations)
            if n % 2 == 1
        ]

    def _responses(self) -> list[dict[str, Any]]:
        return [
            {
                "loader_path_operation_id": self._id("op", n),
                "id": self._id("response", (n // 2) * 2 + k),
                "status_code": "200" if k == 0 else "404",
                "description": "OK" if k == 0 else "Not found",
                "data": None,
                "class_id": None,
                "class_name": None,
                "inline_schema": {"type": "object"},
                "content_types": [],
            }
            for n in range(self.operations)
            for k in range(2)
        ]

    def _security(self) -> list[dict[str, Any]]:
        return [
            {
                "version_id": self.spec_id,
                "scheme_name": "ApiKeyHeader",
                "scheme_type": "apiKey",
                "param_name": "X-Api-Key",
                "in_location": "header",
                "description": None,
            }
        ]

    def _servers(self) -> list[dict[str, Any]]:
        return [
            {
                "id": self._id("server", 0),
                "version_id": self.spec_id,
                "name": "Production",
                "url": "https://api.example.com",
                "description": None,
                "sort_order": 0,
                "variables": None,
                "environment": None,
                "created_at": None,
                "updated_at": None,
            }
        ]

    def _pins(self) -> list[dict[str, Any]]:
        return []
