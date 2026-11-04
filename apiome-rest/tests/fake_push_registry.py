"""An in-memory Confluent Schema Registry that accepts writes — for the registry push tests (MFX-19.4, MFX-19.6).

It answers the calls a push makes — lookup (``POST /subjects/{s}``), compatibility level
(``PUT /config/{s}``), compatibility check and register — and keeps each schema's ``schemaType``
and ``references``, so an Avro, JSON Schema or Protobuf push can be asserted on what the registry holds.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict, List, Optional, Set
from urllib.parse import unquote

import httpx

#: The credentials every call carries by default.
DEFAULT_BASIC = ("svc-apiome", "s3cret-pass")


class PushRegistry:
    """An in-memory Confluent registry: lookup, compatibility level, compatibility check and register.

    Args:
        subjects: ``{subject: [schema text, …]}`` already registered as Avro (version = index + 1).
        incompatible: Subjects whose compatibility check answers ``is_compatible: false``.
        conflict: Subjects whose register answers ``409`` (Confluent's incompatible-schema error).
        refuse: Subjects whose register answers ``422`` (invalid schema).
        refuse_config: Subjects whose ``PUT /config`` answers ``422``.
        basic: ``(username, password)`` every call must carry.
        version_on_register: Include ``version`` in the register answer (newer registries do).
    """

    def __init__(
        self,
        subjects: Optional[Dict[str, List[str]]] = None,
        *,
        incompatible: Set[str] = frozenset(),
        conflict: Set[str] = frozenset(),
        refuse: Set[str] = frozenset(),
        refuse_config: Set[str] = frozenset(),
        basic: Optional[tuple] = DEFAULT_BASIC,
        version_on_register: bool = False,
    ) -> None:
        self.subjects: Dict[str, List[Dict[str, Any]]] = {
            s: [{"schema": text, "references": [], "schemaType": "AVRO"} for text in texts]
            for s, texts in (subjects or {}).items()
        }
        self.levels: Dict[str, str] = {}
        self.ids: Dict[str, int] = {}
        self.incompatible = set(incompatible)
        self.conflict = set(conflict)
        self.refuse = set(refuse)
        self.refuse_config = set(refuse_config)
        self.basic = basic
        self.version_on_register = version_on_register
        self.requests: List[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def calls(self) -> List[str]:
        """``METHOD path`` of every request, decoded."""
        return [f"{r.method} {unquote(r.url.raw_path.decode().split('?', 1)[0])}" for r in self.requests]

    def writes(self) -> List[str]:
        """The register calls."""
        return [c for c in self.calls() if c.endswith("/versions")]

    def bodies(self, call: str) -> List[Dict[str, Any]]:
        """The JSON bodies sent with ``METHOD path``."""
        return [json.loads(r.content or b"{}") for r, c in zip(self.requests, self.calls()) if c == call]

    def _id(self, text: str) -> int:
        return self.ids.setdefault(text, 100 + len(self.ids))

    @staticmethod
    def _error(status: int, code: int, message: str) -> httpx.Response:
        return httpx.Response(status, json={"error_code": code, "message": message})

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.basic is not None:
            expected = base64.b64encode(f"{self.basic[0]}:{self.basic[1]}".encode()).decode()
            if request.headers.get("authorization") != f"Basic {expected}":
                return self._error(401, 40101, f"Unauthorized: bad password {self.basic[1]}")
        parts = [unquote(p) for p in request.url.raw_path.decode().split("?", 1)[0].strip("/").split("/")]
        body = json.loads(request.content or b"{}")
        if request.method == "PUT" and parts[0] == "config" and len(parts) == 2:
            if parts[1] in self.refuse_config:
                return self._error(422, 42203, "Invalid compatibility level")
            self.levels[parts[1]] = body["compatibility"]
            return httpx.Response(200, json={"compatibility": body["compatibility"]})
        if request.method != "POST":
            return self._error(405, 405, "Method not allowed")
        text, references = body.get("schema"), body.get("references") or []
        schema_type = body.get("schemaType", "AVRO")
        if parts[0] == "compatibility" and parts[1] == "subjects":
            subject = parts[2]
            if subject not in self.subjects:
                return self._error(404, 40401, f"Subject '{subject}' not found.")
            if subject in self.incompatible:
                return httpx.Response(200, json={"is_compatible": False,
                                                 "messages": ["READER_FIELD_MISSING_DEFAULT_VALUE: id"]})
            return httpx.Response(200, json={"is_compatible": True})
        if parts[0] == "subjects" and len(parts) == 2:
            versions = self.subjects.get(parts[1])
            if versions is None:
                return self._error(404, 40401, f"Subject '{parts[1]}' not found.")
            for index, entry in enumerate(versions):
                if (entry["schema"], entry["references"], entry["schemaType"]) == (text, references, schema_type):
                    return httpx.Response(200, json={"subject": parts[1], "id": self._id(text),
                                                     "version": index + 1, "schema": text})
            return self._error(404, 40403, "Schema not found")
        if parts[0] == "subjects" and len(parts) == 3 and parts[2] == "versions":
            subject = parts[1]
            if subject in self.conflict:
                return self._error(409, 409, "Schema being registered is incompatible with an earlier schema")
            if subject in self.refuse:
                return self._error(422, 42201, "Invalid schema")
            for ref in references:
                held = self.subjects.get(ref["subject"]) or []
                if not 1 <= ref["version"] <= len(held):
                    return self._error(422, 42201, f"Invalid reference {ref}")
            self.subjects.setdefault(subject, []).append(
                {"schema": text, "references": references, "schemaType": schema_type}
            )
            answer: Dict[str, Any] = {"id": self._id(text)}
            if self.version_on_register:
                answer["version"] = len(self.subjects[subject])
            return httpx.Response(200, json=answer)
        return self._error(404, 404, "HTTP 404 Not Found")
