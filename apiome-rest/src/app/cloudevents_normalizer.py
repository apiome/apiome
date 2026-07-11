"""CloudEvents → canonical model normalizer.

Maps a parsed :class:`~app.cloudevents_parser.CloudEventsDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.EVENT`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Channel,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Service,
    TypeRef,
)
from .cloudevents_parser import CloudEvent, CloudEventsDocument
from .normalizer import Keys, Normalizer, SchemaCoercer, normalize_ordering

__all__ = ["CloudEventsNormalizer"]

_FORMAT_KEY = "cloudevents"
_REF_PREFIX = "#/components/schemas/"


def _infer_schema_from_json(value: Any) -> Dict[str, Any]:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, list):
        if not value:
            return {"type": "array", "items": {}}
        return {"type": "array", "items": _infer_schema_from_json(value[0])}
    if isinstance(value, dict):
        properties = {
            str(key): _infer_schema_from_json(item) for key, item in value.items()
        }
        return {
            "type": "object",
            "properties": properties,
            "required": list(value.keys()),
        }
    return {"type": "string"}


def _type_name_from_event_type(event_type: str) -> str:
    parts = [part for part in event_type.split(".") if part]
    if len(parts) >= 2:
        left, right = parts[-2], parts[-1]
        return (left[:1].upper() + left[1:] + right[:1].upper() + right[1:]).replace("-", "")
    if parts:
        segment = parts[-1]
        return segment[:1].upper() + segment[1:]
    return "EventData"


def _merge_object_schemas(
    existing: Dict[str, Any],
    incoming: Dict[str, Any],
) -> Dict[str, Any]:
    if existing.get("type") != "object" or incoming.get("type") != "object":
        return incoming
    properties = dict(existing.get("properties") or {})
    properties.update(incoming.get("properties") or {})
    required: Set[str] = set(existing.get("required") or [])
    required.update(incoming.get("required") or [])
    return {
        "type": "object",
        "properties": properties,
        "required": sorted(required),
    }


def _collect_components(document: CloudEventsDocument) -> Dict[str, Any]:
    components: Dict[str, Any] = {}
    for event in document.events:
        if not isinstance(event.data, dict):
            continue
        schema = _infer_schema_from_json(event.data)
        type_name = _type_name_from_event_type(event.type)
        if type_name in components:
            components[type_name] = _merge_object_schemas(components[type_name], schema)
        else:
            components[type_name] = schema
    return components


def _title_for_document(document: CloudEventsDocument) -> str:
    if len(document.events) == 1:
        return document.events[0].type
    domains = {event.type.rsplit(".", 1)[0] for event in document.events if event.type}
    if len(domains) == 1:
        return next(iter(domains))
    return "CloudEvents"


def _event_message(
    event: CloudEvent,
    *,
    op_key: str,
    coercer: SchemaCoercer,
    components: Dict[str, Any],
) -> Message:
    message_name = _type_name_from_event_type(event.type)
    schema: Dict[str, Any]
    payload_ref: Optional[TypeRef] = None
    if isinstance(event.data, dict) and message_name in components:
        schema = {"$ref": f"{_REF_PREFIX}{message_name}"}
        payload_ref = coercer.type_ref(schema, required=True)
    elif event.data is not None:
        schema = _infer_schema_from_json(event.data)
        payload_ref = coercer.type_ref(schema, required=True)
    else:
        schema = {}
    return Message(
        key=Keys.event_message(op_key, message_name),
        role=MessageRole.EVENT,
        name=message_name,
        payload=payload_ref,
        content_types=[event.datacontenttype] if event.datacontenttype else [],
        required=True,
        extras={
            "cloudevents_data_sample": event.data,
            "cloudevents_payload_schema": schema,
        },
    )


def _operation_extras(event: CloudEvent) -> Dict[str, Any]:
    extras: Dict[str, Any] = {
        "cloudevents_specversion": event.specversion,
        "cloudevents_type": event.type,
        "cloudevents_source": event.source,
    }
    if event.id is not None:
        extras["cloudevents_id"] = event.id
    if event.subject is not None:
        extras["cloudevents_subject"] = event.subject
    if event.time is not None:
        extras["cloudevents_time"] = event.time
    if event.datacontenttype is not None:
        extras["cloudevents_datacontenttype"] = event.datacontenttype
    if event.datacontentencoding is not None:
        extras["cloudevents_datacontentencoding"] = event.datacontentencoding
    if event.dataschema is not None:
        extras["cloudevents_dataschema"] = event.dataschema
    if event.data_base64 is not None:
        extras["cloudevents_data_base64"] = event.data_base64
    if event.extensions:
        extras["cloudevents_extensions"] = dict(event.extensions)
    return extras


class CloudEventsNormalizer(Normalizer, register=True):
    """Normalize parsed CloudEvents JSON into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.EVENT

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, CloudEventsDocument):
            raise ValueError(
                "CloudEvents source must be a CloudEventsDocument "
                "(see app.cloudevents_parser.parse_cloudevents)"
            )

        components = _collect_components(source)
        coercer = SchemaCoercer(components=components, ref_prefix=_REF_PREFIX)
        title = _title_for_document(source)
        service_key = Keys.type(title, None)

        channels: List[Channel] = []
        operations: List[Operation] = []
        channel_by_type: Dict[str, Channel] = {}

        for event in source.events:
            channel_key = Keys.channel(event.type)
            channel = channel_by_type.get(event.type)
            if channel is None:
                channel = Channel(
                    key=channel_key,
                    address=event.type,
                    name=event.type,
                    description=f"CloudEvents channel for `{event.type}`",
                    protocol="cloudevents",
                    extras={
                        "cloudevents_source": event.source,
                        "cloudevents_subject": event.subject,
                    },
                )
                channel_by_type[event.type] = channel
                channels.append(channel)

            op_name = event.id or event.type.rsplit(".", 1)[-1]
            op_key = Keys.operation_event("publish", channel_key, op_name)
            operations.append(
                Operation(
                    key=op_key,
                    name=op_name,
                    kind=OperationKind.PUBLISH,
                    channel_ref=channel_key,
                    messages=[
                        _event_message(
                            event,
                            op_key=op_key,
                            coercer=coercer,
                            components=components,
                        )
                    ],
                    extras=_operation_extras(event),
                )
            )

        types = coercer.named_types_from_components()
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol="cloudevents",
            identity=ApiIdentity(name=title),
            title=title,
            channels=channels,
            services=[Service(key=service_key, name=title, operations=operations)],
            types=types,
            raw={"cloudevents": source.raw} if include_raw else None,
            extras={"cloudevents_event_count": len(source.events)},
        )
        return normalize_ordering(api)
