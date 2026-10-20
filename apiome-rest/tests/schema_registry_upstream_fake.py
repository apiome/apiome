"""A fake upstream schema registry for the ``schema-registry`` connector tests (MFI-12.3, #3784).

:class:`FakeUpstreamRegistry` is an ``httpx.MockTransport`` handler that speaks the Confluent Schema
Registry REST API in three flavours, matching what each product answers:

* ``confluent`` — Confluent Platform / Cloud: ``GET /config/{s}?defaultToGlobal=true`` falls back to
  the global level; AVRO versions carry no ``schemaType``.
* ``karapace`` — Aiven Karapace: like Confluent, but every version names its ``schemaType``.
* ``apicurio`` — Apicurio Registry's compatibility API under ``/apis/ccompat/v7``: ``GET /config/{s}``
  answers ``404`` (error code 40408) for a subject with no level of its own, whatever
  ``defaultToGlobal`` says, so the client must read ``GET /config``.

Errors use Confluent's ``{"error_code", "message"}`` body. Every request is recorded.
"""

from __future__ import annotations

import base64
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import unquote

import httpx

CONFLUENT = "confluent"
KARAPACE = "karapace"
APICURIO = "apicurio"

#: The path prefix of each flavour (Apicurio serves the Confluent API under its ccompat path).
PREFIX = {CONFLUENT: "", KARAPACE: "", APICURIO: "/apis/ccompat/v7"}


class FakeUpstreamRegistry:
    """An in-memory upstream registry.

    Args:
        subjects: ``{subject: {version: {"id": int, "schema": str, "schemaType"?: str, "references"?: list}}}``.
        flavor: ``confluent``, ``karapace`` or ``apicurio``.
        global_level: The registry default compatibility level.
        subject_levels: Levels set on individual subjects.
        basic: ``(username, password)`` the registry requires, if any.
        token: A bearer token the registry requires, if any.
        omit_schema_text: Leave ``schema`` out of version bodies (the client must use ``/schemas/ids``).
        status: Answer every request with this status instead (an outage or refusal).
    """

    def __init__(
        self,
        subjects: Dict[str, Dict[int, Dict[str, Any]]],
        *,
        flavor: str = CONFLUENT,
        global_level: str = "BACKWARD",
        subject_levels: Optional[Dict[str, str]] = None,
        basic: Optional[tuple] = None,
        token: Optional[str] = None,
        omit_schema_text: bool = False,
        status: Optional[int] = None,
    ) -> None:
        self.subjects = subjects
        self.flavor = flavor
        self.global_level = global_level
        self.subject_levels = dict(subject_levels or {})
        self.basic = basic
        self.token = token
        self.omit_schema_text = omit_schema_text
        self.status = status
        self.requests: List[httpx.Request] = []

    @property
    def base_url(self) -> str:
        return "https://sr.example.test" + PREFIX[self.flavor]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def paths(self) -> List[str]:
        """The decoded paths requested, relative to the flavour prefix, with their query."""
        prefix = PREFIX[self.flavor]
        out = []
        for request in self.requests:
            path = unquote(request.url.raw_path.decode().split("?", 1)[0])
            path = path[len(prefix):] if prefix and path.startswith(prefix) else path
            query = request.url.query.decode() if isinstance(request.url.query, bytes) else str(request.url.query)
            out.append(path + (f"?{query}" if query else ""))
        return out

    # --- handler ---------------------------------------------------------------------

    @staticmethod
    def _error(status: int, code: int, message: str) -> httpx.Response:
        return httpx.Response(status, json={"error_code": code, "message": message})

    def _authorized(self, request: httpx.Request) -> bool:
        header = request.headers.get("authorization", "")
        if self.basic is not None:
            expected = base64.b64encode(f"{self.basic[0]}:{self.basic[1]}".encode()).decode()
            return header == f"Basic {expected}"
        if self.token is not None:
            return header == f"Bearer {self.token}"
        return True

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status is not None:
            return self._error(self.status, self.status * 100 + 1, "Registry refused the request")
        if not self._authorized(request):
            return self._error(401, 40101, "Unauthorized")
        prefix = PREFIX[self.flavor]
        raw = request.url.raw_path.decode().split("?", 1)[0]
        if prefix:
            if not raw.startswith(prefix):
                return self._error(404, 404, "HTTP 404 Not Found")
            raw = raw[len(prefix):]
        parts = [unquote(p) for p in raw.strip("/").split("/")]
        params = request.url.params

        if parts == ["subjects"]:
            return httpx.Response(200, json=sorted(self.subjects))
        if len(parts) >= 3 and parts[0] == "subjects" and parts[2] == "versions":
            versions = self.subjects.get(parts[1])
            if versions is None:
                return self._error(404, 40401, f"Subject '{parts[1]}' not found.")
            if len(parts) == 3:
                return httpx.Response(200, json=sorted(versions))
            entry = versions.get(int(parts[3])) if parts[3].isdigit() else None
            if entry is None:
                return self._error(404, 40402, f"Version {parts[3]} not found.")
            return httpx.Response(200, json=self._version_body(parts[1], int(parts[3]), entry))
        if len(parts) == 3 and parts[:2] == ["schemas", "ids"]:
            for versions in self.subjects.values():
                for entry in versions.values():
                    if entry["id"] == int(parts[2]):
                        body: Dict[str, Any] = {"schema": entry["schema"]}
                        if entry.get("schemaType", "AVRO") != "AVRO":
                            body["schemaType"] = entry["schemaType"]
                        return httpx.Response(200, json=body)
            return self._error(404, 40403, f"Schema {parts[2]} not found")
        if parts == ["config"]:
            return httpx.Response(200, json={"compatibilityLevel": self.global_level})
        if len(parts) == 2 and parts[0] == "config":
            level = self.subject_levels.get(parts[1])
            if level is None:
                if self.flavor == APICURIO or params.get("defaultToGlobal") != "true":
                    return self._error(
                        404, 40408, f"Subject '{parts[1]}' does not have subject-level compatibility configured"
                    )
                level = self.global_level
            return httpx.Response(200, json={"compatibilityLevel": level})
        return self._error(404, 404, "HTTP 404 Not Found")

    def _version_body(self, subject: str, version: int, entry: Mapping[str, Any]) -> Dict[str, Any]:
        body: Dict[str, Any] = {"subject": subject, "version": version, "id": entry["id"]}
        schema_type = entry.get("schemaType", "AVRO")
        if schema_type != "AVRO" or self.flavor == KARAPACE:
            body["schemaType"] = schema_type
        if entry.get("references"):
            body["references"] = entry["references"]
        if not self.omit_schema_text:
            body["schema"] = entry["schema"]
        return body
