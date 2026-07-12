"""Postman emitter: canonical model → Postman Collection v2.1 JSON.

The inverse of :class:`app.postman_normalizer.PostmanNormalizer` and an implementation
of the :class:`app.emitter.Emitter` SPI.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Union

from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    MessageRole,
    Operation,
    OperationKind,
    ParameterLocation,
)
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitResult,
    EmittedFile,
    Emitter,
    LossKind,
    LossTracker,
    Provenance,
    ProvenanceTracker,
    SchemaEmitter,
)
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict

__all__ = ["PostmanEmitOptions", "PostmanEmitter", "PostmanFidelityRulePack"]

_POSTMAN_SCHEMA_URL = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})


class PostmanFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for Postman export."""

    target_label = "Postman"

    def event_verdict(self, event) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no event/channel representation; event {event.key!r} is dropped",
            target_mapping="event → dropped",
        )

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        if operation.kind in _EVENT_OPERATION_KINDS:
            return FidelityVerdict.drop(
                message=f"{self.target_label} has no event vocabulary; "
                f"{operation.kind.value} operation {operation.key!r} is dropped",
                target_mapping="event operation → dropped",
            )
        if not operation.http_method or not operation.http_path:
            return FidelityVerdict.drop(
                message=f"{self.target_label} requires HTTP operations; operation {operation.key!r} is dropped",
                target_mapping="non-HTTP operation → dropped",
            )
        return FidelityVerdict.ok(message=f"operation carried to {self.target_label}")


class PostmanEmitOptions(EmitOptions):
    """Per-target options for :class:`PostmanEmitter`."""

    indent: int = Field(default=2, description="JSON indentation width (0 for compact output).")


class PostmanEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a Postman Collection v2.1 JSON document."""

    key = "postman"
    format = "postman"
    label = "Postman"
    description = "Export as a Postman Collection v2.1 JSON document."
    icon = "file-json"
    paradigm = ApiParadigm.REST
    multi_file = False
    options_model = PostmanEmitOptions

    OUTPUT_MEDIA_TYPE = "application/json"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=True,
            events=False,
            unions=False,
            nullability=True,
            field_identity=False,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return PostmanFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[PostmanEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, PostmanEmitOptions)
            else PostmanEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _PostmanWriter(api, options)
        content = writer.render()
        return EmitResult(
            files=[
                EmittedFile(
                    path=writer.output_path,
                    content=content,
                    media_type=self.OUTPUT_MEDIA_TYPE,
                )
            ],
            media_type=self.OUTPUT_MEDIA_TYPE,
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
        )


class _PostmanWriter:
    def __init__(self, api: CanonicalApi, options: PostmanEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._schema = SchemaEmitter()
        self.output_path = _output_path(api)

    def render(self) -> str:
        document: Dict[str, Any] = {
            "info": self._info(),
            "item": self._items(),
        }
        variables = self._api.extras.get("postman_variables")
        if isinstance(variables, list) and variables:
            document["variable"] = variables
        elif self._api.servers:
            document["variable"] = [{"key": "baseUrl", "value": self._api.servers[0].url}]
        if self._api.channels:
            self.losses.record(
                LossKind.NA,
                "channels-dropped",
                "Postman export omits event/channel constructs",
                pointer="channels",
            )
        indent = self._options.indent if self._options.indent > 0 else None
        return json.dumps(document, indent=indent, ensure_ascii=False) + "\n"

    def _info(self) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "name": self._api.title or self._api.identity.name or "Exported API",
            "schema": self._api.extras.get("postman_schema_url") or _POSTMAN_SCHEMA_URL,
        }
        if self._api.description:
            info["description"] = self._api.description
        return info

    def _items(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for service in self._api.services:
            for operation in service.operations:
                if operation.kind in _EVENT_OPERATION_KINDS:
                    continue
                if not operation.http_method or not operation.http_path:
                    continue
                items.append(self._operation_item(operation))
                self.tracker.record(operation.key, Provenance.SOURCE)
        return items

    def _operation_item(self, operation: Operation) -> Dict[str, Any]:
        item: Dict[str, Any] = {
            "name": operation.name,
            "request": self._request(operation),
            "response": [],
        }
        if operation.description:
            item["description"] = operation.description
        folder_path = operation.extras.get("postman_folder_path")
        if isinstance(folder_path, list) and folder_path:
            item["name"] = folder_path[-1] if len(folder_path) == 1 else operation.name
        return item

    def _request(self, operation: Operation) -> Dict[str, Any]:
        request: Dict[str, Any] = {
            "method": operation.http_method,
            "url": self._url(operation),
            "header": self._headers(operation),
        }
        if operation.description:
            request["description"] = operation.description
        request_message = next(
            (message for message in operation.messages if message.role is MessageRole.REQUEST),
            None,
        )
        if request_message is not None:
            raw_body = request_message.extras.get("postman_body_raw")
            if isinstance(raw_body, str) and raw_body:
                request["body"] = {
                    "mode": request_message.extras.get("postman_body_mode") or "raw",
                    "raw": raw_body,
                    "options": {
                        "raw": {
                            "language": request_message.extras.get("postman_body_language") or "json",
                        }
                    },
                }
            elif request_message.payload is not None:
                schema = self._schema.type_ref(request_message.payload)
                request["body"] = {
                    "mode": "raw",
                    "raw": json.dumps(schema, indent=2),
                    "options": {"raw": {"language": "json"}},
                }
        return request

    def _headers(self, operation: Operation) -> List[Dict[str, Any]]:
        headers = operation.extras.get("postman_headers")
        if isinstance(headers, list) and headers:
            return [
                entry
                for entry in headers
                if isinstance(entry, dict) and isinstance(entry.get("key"), str)
            ]
        return [{"key": "Accept", "value": "application/json"}]

    def _url(self, operation: Operation) -> Dict[str, Any]:
        path_segments = [
            segment for segment in operation.http_path.strip("/").split("/") if segment
        ]
        postman_path: List[str] = []
        variables: List[Dict[str, Any]] = []
        query: List[Dict[str, Any]] = []
        for segment in path_segments:
            if segment.startswith("{") and segment.endswith("}"):
                key = segment[1:-1]
                postman_path.append(f":{key}")
                sample = next(
                    (
                        param.extras.get("postman_sample")
                        for param in operation.parameters
                        if param.location is ParameterLocation.PATH and param.name == key
                    ),
                    None,
                )
                variables.append({"key": key, "value": sample or ""})
            else:
                postman_path.append(segment)
        for param in operation.parameters:
            if param.location is ParameterLocation.QUERY:
                query.append(
                    {
                        "key": param.name,
                        "value": param.extras.get("postman_sample") or "",
                        "disabled": False,
                    }
                )
        raw = "{{baseUrl}}/" + "/".join(postman_path) if postman_path else "{{baseUrl}}"
        return {
            "raw": raw,
            "host": ["{{baseUrl}}"],
            "path": postman_path,
            "query": query,
            "variable": variables,
        }


def _output_path(api: CanonicalApi) -> str:
    base = api.identity.name or api.title or "collection"
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "collection"
    return f"{safe}.postman_collection.json"
