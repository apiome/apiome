"""Postman Collection v2.1 parser.

Parses Postman Collection JSON into a typed :class:`PostmanDocument` AST.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .import_ingestion import IngestionError, parse_document

__all__ = [
    "PostmanParseError",
    "PostmanQueryParam",
    "PostmanPathVariable",
    "PostmanUrl",
    "PostmanBody",
    "PostmanHeader",
    "PostmanRequest",
    "PostmanResponse",
    "PostmanOperation",
    "PostmanVariable",
    "PostmanDocument",
    "is_postman",
    "is_postman_document",
    "parse_postman",
]

_API_MARKERS = ("openapi", "swagger", "asyncapi", "arazzo", "openrpc", "avro")
_ALLOWED_METHODS = frozenset({"GET", "PUT", "POST", "DELETE", "PATCH", "HEAD", "OPTIONS"})


class PostmanParseError(ValueError):
    """Raised when Postman collection text cannot be parsed."""


@dataclass(frozen=True)
class PostmanQueryParam:
    name: str
    value: Optional[str]
    disabled: bool = False


@dataclass(frozen=True)
class PostmanPathVariable:
    key: str
    value: Optional[str]


@dataclass(frozen=True)
class PostmanUrl:
    raw: Optional[str]
    path: Tuple[str, ...]
    query: Tuple[PostmanQueryParam, ...]
    variables: Tuple[PostmanPathVariable, ...]


@dataclass(frozen=True)
class PostmanBody:
    mode: Optional[str]
    raw: Optional[str]
    language: Optional[str]


@dataclass(frozen=True)
class PostmanHeader:
    key: str
    value: Optional[str]
    disabled: bool = False


@dataclass(frozen=True)
class PostmanRequest:
    method: str
    url: PostmanUrl
    headers: Tuple[PostmanHeader, ...]
    body: Optional[PostmanBody]
    description: Optional[str]


@dataclass(frozen=True)
class PostmanResponse:
    name: str
    status: Optional[str]
    code: Optional[int]
    body: Optional[PostmanBody]


@dataclass(frozen=True)
class PostmanOperation:
    name: str
    folder_path: Tuple[str, ...]
    request: PostmanRequest
    responses: Tuple[PostmanResponse, ...]


@dataclass(frozen=True)
class PostmanVariable:
    key: str
    value: Optional[str]


@dataclass(frozen=True)
class PostmanDocument:
    name: str
    description: Optional[str]
    schema_url: Optional[str]
    variables: Tuple[PostmanVariable, ...]
    operations: Tuple[PostmanOperation, ...]
    raw: str


def _is_postman_mapping(document: Any) -> bool:
    if not isinstance(document, Mapping):
        return False
    if any(marker in document for marker in _API_MARKERS):
        return False
    info = document.get("info")
    if isinstance(info, Mapping):
        schema = info.get("schema")
        if isinstance(schema, str):
            lowered = schema.lower()
            if "postman.com" in lowered and "collection" in lowered:
                return True
    if isinstance(document.get("item"), list) and (
        isinstance(info, Mapping) or len(document.get("item") or []) > 0
    ):
        return "item" in document and "info" in document
    return False


def is_postman_document(document: Any) -> bool:
    """Return ``True`` when a parsed mapping looks like a Postman collection."""
    return _is_postman_mapping(document)


def is_postman(content: str) -> bool:
    """Return ``True`` when ``content`` looks like a Postman collection."""
    if not content or not isinstance(content, str):
        return False
    if not content.strip():
        return False
    try:
        document = parse_document(content)
    except IngestionError:
        return False
    return _is_postman_mapping(document)


def _normalize_method(method: Any) -> str:
    value = str(method or "GET").upper()
    return value if value in _ALLOWED_METHODS else "GET"


def _clean_path_segment(segment: str) -> str:
    cleaned = segment.strip()
    if cleaned.startswith("{{") and cleaned.endswith("}}"):
        return ""
    if cleaned.startswith(":"):
        return "{" + cleaned[1:] + "}"
    return cleaned


def _parse_url(url_value: Any) -> PostmanUrl:
    if isinstance(url_value, str):
        raw = url_value.strip()
        try:
            from urllib.parse import urlparse

            parsed = urlparse(raw if "://" in raw else f"https://host{raw}")
            path = tuple(
                segment
                for segment in (parsed.path or "/").strip("/").split("/")
                if segment
            )
            return PostmanUrl(raw=raw, path=path, query=(), variables=())
        except ValueError:
            path = tuple(segment for segment in raw.strip("/").split("/") if segment)
            return PostmanUrl(raw=raw, path=path, query=(), variables=())

    if not isinstance(url_value, Mapping):
        return PostmanUrl(raw=None, path=(), query=(), variables=())

    raw = url_value.get("raw")
    path_value = url_value.get("path")
    path: Tuple[str, ...]
    if isinstance(path_value, list):
        path = tuple(
            cleaned
            for segment in path_value
            if isinstance(segment, str)
            for cleaned in [_clean_path_segment(segment)]
            if cleaned
        )
    elif isinstance(path_value, str):
        path = tuple(segment for segment in path_value.strip("/").split("/") if segment)
    else:
        path = ()

    query: List[PostmanQueryParam] = []
    raw_query = url_value.get("query")
    if isinstance(raw_query, list):
        for entry in raw_query:
            if not isinstance(entry, Mapping):
                continue
            name = entry.get("key")
            if not isinstance(name, str) or not name.strip():
                continue
            query.append(
                PostmanQueryParam(
                    name=name.strip(),
                    value=entry.get("value") if isinstance(entry.get("value"), str) else None,
                    disabled=entry.get("disabled") is True,
                )
            )

    variables: List[PostmanPathVariable] = []
    raw_variables = url_value.get("variable")
    if isinstance(raw_variables, list):
        for entry in raw_variables:
            if not isinstance(entry, Mapping):
                continue
            key = entry.get("key")
            if not isinstance(key, str) or not key.strip():
                continue
            variables.append(
                PostmanPathVariable(
                    key=key.strip(),
                    value=entry.get("value") if isinstance(entry.get("value"), str) else None,
                )
            )

    return PostmanUrl(
        raw=raw if isinstance(raw, str) else None,
        path=path,
        query=tuple(query),
        variables=tuple(variables),
    )


def _http_path(url: PostmanUrl) -> str:
    if not url.path:
        return "/"
    segments: List[str] = []
    for segment in url.path:
        if segment.startswith("{") and segment.endswith("}"):
            segments.append(segment)
        elif segment.startswith(":"):
            segments.append("{" + segment[1:] + "}")
        else:
            segments.append(segment)
    return "/" + "/".join(segments)


def _parse_body(body_value: Any) -> Optional[PostmanBody]:
    if not isinstance(body_value, Mapping):
        return None
    mode = body_value.get("mode")
    raw = body_value.get("raw")
    language = None
    options = body_value.get("options")
    if isinstance(options, Mapping):
        raw_opts = options.get("raw")
        if isinstance(raw_opts, Mapping) and isinstance(raw_opts.get("language"), str):
            language = raw_opts["language"]
    return PostmanBody(
        mode=mode if isinstance(mode, str) else None,
        raw=raw if isinstance(raw, str) else None,
        language=language,
    )


def _parse_headers(headers_value: Any) -> Tuple[PostmanHeader, ...]:
    if not isinstance(headers_value, list):
        return ()
    headers: List[PostmanHeader] = []
    for entry in headers_value:
        if not isinstance(entry, Mapping):
            continue
        key = entry.get("key")
        if not isinstance(key, str) or not key.strip():
            continue
        headers.append(
            PostmanHeader(
                key=key.strip(),
                value=entry.get("value") if isinstance(entry.get("value"), str) else None,
                disabled=entry.get("disabled") is True,
            )
        )
    return tuple(headers)


def _parse_responses(responses_value: Any) -> Tuple[PostmanResponse, ...]:
    if not isinstance(responses_value, list):
        return ()
    responses: List[PostmanResponse] = []
    for entry in responses_value:
        if not isinstance(entry, Mapping):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        code = entry.get("code")
        responses.append(
            PostmanResponse(
                name=name.strip(),
                status=entry.get("status") if isinstance(entry.get("status"), str) else None,
                code=int(code) if isinstance(code, int) else None,
                body=_parse_body(entry.get("body")),
            )
        )
    return tuple(responses)


def _parse_operations(
    items: Any,
    *,
    folder_path: Tuple[str, ...] = (),
) -> List[PostmanOperation]:
    if not isinstance(items, list):
        return []
    operations: List[PostmanOperation] = []
    for entry in items:
        if not isinstance(entry, Mapping):
            continue
        request_value = entry.get("request")
        if isinstance(request_value, Mapping):
            name = entry.get("name")
            if not isinstance(name, str) or not name.strip():
                name = "Request"
            url = _parse_url(request_value.get("url"))
            operations.append(
                PostmanOperation(
                    name=name.strip(),
                    folder_path=folder_path,
                    request=PostmanRequest(
                        method=_normalize_method(request_value.get("method")),
                        url=url,
                        headers=_parse_headers(request_value.get("header")),
                        body=_parse_body(request_value.get("body")),
                        description=(
                            request_value.get("description")
                            if isinstance(request_value.get("description"), str)
                            else (
                                entry.get("description")
                                if isinstance(entry.get("description"), str)
                                else None
                            )
                        ),
                    ),
                    responses=_parse_responses(entry.get("response")),
                )
            )
            continue
        nested = entry.get("item")
        if isinstance(nested, list):
            nested_name = entry.get("name")
            next_folder = (
                (*folder_path, str(nested_name).strip())
                if isinstance(nested_name, str) and nested_name.strip()
                else folder_path
            )
            operations.extend(_parse_operations(nested, folder_path=next_folder))
    return operations


def _parse_variables(raw_variables: Any) -> Tuple[PostmanVariable, ...]:
    if not isinstance(raw_variables, list):
        return ()
    variables: List[PostmanVariable] = []
    for entry in raw_variables:
        if not isinstance(entry, Mapping):
            continue
        key = entry.get("key")
        if not isinstance(key, str) or not key.strip():
            continue
        variables.append(
            PostmanVariable(
                key=key.strip(),
                value=entry.get("value") if isinstance(entry.get("value"), str) else None,
            )
        )
    return tuple(variables)


def parse_postman(content: str, *, source_label: Optional[str] = None) -> PostmanDocument:
    """Parse Postman collection JSON into a :class:`PostmanDocument`."""
    if not content or not content.strip():
        raise PostmanParseError("Invalid or empty Postman collection")
    try:
        document = parse_document(content, source_label=source_label)
    except IngestionError as exc:
        raise PostmanParseError(str(exc)) from exc

    if not _is_postman_mapping(document):
        raise PostmanParseError("Content does not appear to be a Postman collection")

    info = document.get("info") or {}
    if not isinstance(info, Mapping):
        info = {}
    name = info.get("name")
    if not isinstance(name, str) or not name.strip():
        name = source_label or "Postman Collection"

    operations = tuple(_parse_operations(document.get("item")))
    if not operations:
        label = f" ({source_label})" if source_label else ""
        raise PostmanParseError(f"No Postman requests found in collection{label}")

    return PostmanDocument(
        name=name.strip(),
        description=info.get("description") if isinstance(info.get("description"), str) else None,
        schema_url=info.get("schema") if isinstance(info.get("schema"), str) else None,
        variables=_parse_variables(document.get("variable")),
        operations=operations,
        raw=content,
    )


def postman_http_path(url: PostmanUrl) -> str:
    """Return the canonical HTTP path for a Postman URL."""
    return _http_path(url)
