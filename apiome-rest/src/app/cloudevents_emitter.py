"""CloudEvents emitter: canonical model → CloudEvents 1.0 structured JSON.

The inverse of :class:`app.cloudevents_normalizer.CloudEventsNormalizer` and an
implementation of the :class:`app.emitter.Emitter` SPI.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional, Union

from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    MessageRole,
    Operation,
    OperationKind,
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

__all__ = ["CloudEventsEmitOptions", "CloudEventsEmitter", "CloudEventsFidelityRulePack"]

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
_REST_OPERATION_KINDS = frozenset(
    {OperationKind.REQUEST_RESPONSE, OperationKind.QUERY, OperationKind.MUTATION}
)


class CloudEventsFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for CloudEvents export."""

    target_label = "CloudEvents"

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        if operation.kind in _REST_OPERATION_KINDS:
            return FidelityVerdict.drop(
                message=f"{self.target_label} has no HTTP/RPC operation vocabulary; "
                f"operation {operation.key!r} is dropped",
                target_mapping="REST/RPC operation → dropped",
            )
        if operation.kind in _EVENT_OPERATION_KINDS:
            return FidelityVerdict.ok(message=f"operation carried to {self.target_label}")
        return FidelityVerdict.drop(
            message=f"{self.target_label} only supports event operations; "
            f"operation {operation.key!r} is dropped",
            target_mapping="unsupported operation → dropped",
        )


class CloudEventsEmitOptions(EmitOptions):
    """Per-target options for :class:`CloudEventsEmitter`."""

    indent: int = Field(default=2, description="JSON indentation width (0 for compact output).")
    specversion: str = Field(default="1.0", description="CloudEvents `specversion` attribute.")


class CloudEventsEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as CloudEvents 1.0 structured JSON."""

    key = "cloudevents"
    format = "cloudevents"
    label = "CloudEvents"
    description = "Export as a CloudEvents 1.0 structured-mode JSON event envelope."
    icon = "cloud"
    paradigm = ApiParadigm.EVENT
    multi_file = False
    options_model = CloudEventsEmitOptions

    OUTPUT_MEDIA_TYPE = "application/json"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=False,
            events=True,
            unions=False,
            nullability=True,
            field_identity=False,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return CloudEventsFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[CloudEventsEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, CloudEventsEmitOptions)
            else CloudEventsEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _CloudEventsWriter(api, options)
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


class _CloudEventsWriter:
    def __init__(self, api: CanonicalApi, options: CloudEventsEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._schema = SchemaEmitter()
        self.output_path = _output_path(api)

    def render(self) -> str:
        events = self._events()
        if not events:
            self.losses.record(
                LossKind.NA,
                "no-events",
                "CloudEvents export found no publish/subscribe operations to emit",
                pointer="operations",
            )
            events = [self._fallback_event()]
        document: Any = events[0] if len(events) == 1 else events
        indent = self._options.indent if self._options.indent > 0 else None
        return json.dumps(document, indent=indent, ensure_ascii=False) + "\n"

    def _events(self) -> List[Dict[str, Any]]:
        channel_by_key = {channel.key: channel for channel in self._api.channels}
        events: List[Dict[str, Any]] = []
        for service in self._api.services:
            for operation in service.operations:
                if operation.kind not in _EVENT_OPERATION_KINDS:
                    self.losses.record(
                        LossKind.DROP,
                        operation.key,
                        "Non-event operation omitted from CloudEvents export",
                        pointer=operation.key,
                    )
                    continue
                events.append(self._event_from_operation(operation, channel_by_key))
                self.tracker.record(operation.key, Provenance.SOURCE)
        return events

    def _event_from_operation(
        self,
        operation: Operation,
        channel_by_key: Dict[str, Any],
    ) -> Dict[str, Any]:
        extras = operation.extras
        channel = channel_by_key.get(operation.channel_ref or "")
        event_type = extras.get("cloudevents_type")
        if not isinstance(event_type, str) or not event_type:
            if channel is not None and isinstance(channel.address, str):
                event_type = channel.address
            else:
                event_type = operation.name or "com.example.event"

        source = extras.get("cloudevents_source")
        if not isinstance(source, str) or not source:
            if channel is not None and isinstance(channel.extras.get("cloudevents_source"), str):
                source = channel.extras["cloudevents_source"]
            else:
                source = "/unknown/source"

        event: Dict[str, Any] = {
            "specversion": extras.get("cloudevents_specversion") or self._options.specversion,
            "type": event_type,
            "source": source,
            "id": extras.get("cloudevents_id") or str(uuid.uuid4()),
        }
        for attr, key in (
            ("subject", "cloudevents_subject"),
            ("time", "cloudevents_time"),
            ("datacontenttype", "cloudevents_datacontenttype"),
            ("datacontentencoding", "cloudevents_datacontentencoding"),
            ("dataschema", "cloudevents_dataschema"),
        ):
            value = extras.get(key)
            if isinstance(value, str) and value:
                event[attr] = value
        if channel is not None and "subject" not in event:
            subject = channel.extras.get("cloudevents_subject")
            if isinstance(subject, str) and subject:
                event["subject"] = subject

        extensions = extras.get("cloudevents_extensions")
        if isinstance(extensions, dict):
            for key, value in extensions.items():
                if key not in event:
                    event[key] = value

        data_base64 = extras.get("cloudevents_data_base64")
        if isinstance(data_base64, str) and data_base64:
            event["data_base64"] = data_base64
        else:
            data = self._payload_data(operation)
            if data is not None:
                event["data"] = data
        return event

    def _payload_data(self, operation: Operation) -> Any:
        message = next(
            (item for item in operation.messages if item.role is MessageRole.EVENT),
            None,
        )
        if message is None:
            return None
        sample = message.extras.get("cloudevents_data_sample")
        if sample is not None:
            return sample
        if message.payload is not None:
            schema = self._schema.type_ref(message.payload)
            if isinstance(schema, dict) and schema.get("type") == "object":
                properties = schema.get("properties") or {}
                return {name: _schema_placeholder(value) for name, value in properties.items()}
        return None

    def _fallback_event(self) -> Dict[str, Any]:
        title = self._api.title or self._api.identity.name or "Exported Event"
        return {
            "specversion": self._options.specversion,
            "id": str(uuid.uuid4()),
            "type": f"com.example.{_slug(title)}",
            "source": "/exported/api",
        }


def _schema_placeholder(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return None
    schema_type = schema.get("type")
    if schema_type == "string":
        return ""
    if schema_type == "integer":
        return 0
    if schema_type == "number":
        return 0.0
    if schema_type == "boolean":
        return False
    if schema_type == "array":
        return []
    if schema_type == "object":
        properties = schema.get("properties") or {}
        return {name: _schema_placeholder(value) for name, value in properties.items()}
    return None


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", ".", value).strip(".")
    return cleaned.lower() or "event"


def _output_path(api: CanonicalApi) -> str:
    base = api.identity.name or api.title or "event"
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "event"
    return f"{safe}.cloudevents.json"
