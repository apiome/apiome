"""CloudEvents 1.0 structured-mode parser.

Parses CloudEvents JSON (single event or batch array) into a typed
:class:`CloudEventsDocument` AST.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .import_ingestion import IngestionError, parse_document

__all__ = [
    "CloudEventParseError",
    "CloudEvent",
    "CloudEventsDocument",
    "is_cloudevents",
    "is_cloudevents_document",
    "parse_cloudevents",
]

_API_MARKERS = ("openapi", "swagger", "asyncapi", "arazzo", "openrpc", "avro")
_STANDARD_ATTRS = frozenset(
    {
        "specversion",
        "type",
        "source",
        "id",
        "datacontenttype",
        "datacontentencoding",
        "dataschema",
        "subject",
        "time",
        "data",
        "data_base64",
        "_comment",
    }
)


class CloudEventParseError(ValueError):
    """Raised when CloudEvents JSON cannot be parsed."""


@dataclass(frozen=True)
class CloudEvent:
    specversion: str
    type: str
    source: str
    id: Optional[str]
    subject: Optional[str]
    time: Optional[str]
    datacontenttype: Optional[str]
    datacontentencoding: Optional[str]
    dataschema: Optional[str]
    data: Any
    data_base64: Optional[str]
    extensions: Tuple[Tuple[str, Any], ...]


@dataclass(frozen=True)
class CloudEventsDocument:
    events: Tuple[CloudEvent, ...]
    raw: str


def _is_cloudevents_event_mapping(document: Any) -> bool:
    if not isinstance(document, Mapping):
        return False
    if any(marker in document for marker in _API_MARKERS):
        return False
    if "info" in document and "item" in document:
        return False
    specversion = document.get("specversion")
    if not isinstance(specversion, str) or not specversion.strip():
        return False
    event_type = document.get("type")
    source = document.get("source")
    if not isinstance(event_type, str) or not event_type.strip():
        return False
    if not isinstance(source, str) or not source.strip():
        return False
    return True


def is_cloudevents_document(document: Any) -> bool:
    """Return ``True`` when a parsed value looks like CloudEvents JSON."""
    if _is_cloudevents_event_mapping(document):
        return True
    if isinstance(document, list) and document:
        return all(_is_cloudevents_event_mapping(item) for item in document)
    return False


def is_cloudevents(content: str) -> bool:
    """Return ``True`` when ``content`` looks like CloudEvents JSON."""
    if not content or not isinstance(content, str) or not content.strip():
        return False
    try:
        document = parse_document(content)
    except IngestionError:
        return False
    return is_cloudevents_document(document)


def _parse_event(mapping: Mapping[str, Any]) -> CloudEvent:
    specversion = mapping.get("specversion")
    event_type = mapping.get("type")
    source = mapping.get("source")
    if not isinstance(specversion, str) or not specversion.strip():
        raise CloudEventParseError("CloudEvent is missing required `specversion`")
    if not isinstance(event_type, str) or not event_type.strip():
        raise CloudEventParseError("CloudEvent is missing required `type`")
    if not isinstance(source, str) or not source.strip():
        raise CloudEventParseError("CloudEvent is missing required `source`")

    extensions: List[Tuple[str, Any]] = []
    for key, value in mapping.items():
        if key not in _STANDARD_ATTRS:
            extensions.append((str(key), value))

    return CloudEvent(
        specversion=specversion.strip(),
        type=event_type.strip(),
        source=source.strip(),
        id=mapping.get("id") if isinstance(mapping.get("id"), str) else None,
        subject=mapping.get("subject") if isinstance(mapping.get("subject"), str) else None,
        time=mapping.get("time") if isinstance(mapping.get("time"), str) else None,
        datacontenttype=(
            mapping.get("datacontenttype")
            if isinstance(mapping.get("datacontenttype"), str)
            else None
        ),
        datacontentencoding=(
            mapping.get("datacontentencoding")
            if isinstance(mapping.get("datacontentencoding"), str)
            else None
        ),
        dataschema=mapping.get("dataschema") if isinstance(mapping.get("dataschema"), str) else None,
        data=mapping.get("data"),
        data_base64=(
            mapping.get("data_base64") if isinstance(mapping.get("data_base64"), str) else None
        ),
        extensions=tuple(extensions),
    )


def parse_cloudevents(content: str, *, source_label: Optional[str] = None) -> CloudEventsDocument:
    """Parse CloudEvents JSON into a :class:`CloudEventsDocument`."""
    if not content or not content.strip():
        raise CloudEventParseError("Invalid or empty CloudEvents document")
    try:
        document = parse_document(content, source_label=source_label)
    except IngestionError as exc:
        raise CloudEventParseError(str(exc)) from exc

    events: List[CloudEvent] = []
    if isinstance(document, list):
        if not document:
            label = f" ({source_label})" if source_label else ""
            raise CloudEventParseError(f"No CloudEvents found in batch document{label}")
        for index, item in enumerate(document):
            if not isinstance(item, Mapping):
                raise CloudEventParseError(f"Batch entry {index} is not a CloudEvent object")
            events.append(_parse_event(item))
    elif isinstance(document, Mapping):
        if not _is_cloudevents_event_mapping(document):
            raise CloudEventParseError("Content does not appear to be a CloudEvents document")
        events.append(_parse_event(document))
    else:
        raise CloudEventParseError("CloudEvents document must be an object or array of objects")

    return CloudEventsDocument(events=tuple(events), raw=content)
