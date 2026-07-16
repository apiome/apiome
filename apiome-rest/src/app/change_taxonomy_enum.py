"""OpenAPI document change enumerator for CTG-1.1 (#4467).

Walks two OpenAPI 3.x documents and emits an ordered list of :class:`RawChange`
records (kind + JSON pointer + before/after). Documentation fields are included
so the taxonomy can grade docs-only edits — unlike the canonical ModelDiff, which
scrubs descriptions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List

__all__ = [
    "RawChange",
    "enumerate_openapi_changes",
    "json_pointer_escape",
    "json_pointer_join",
]


@dataclass(frozen=True)
class RawChange:
    """One structural or documentary difference between two OpenAPI documents.

    Attributes:
        kind: Stable change-kind token matched by the taxonomy rule registry.
        pointer: JSON Pointer to the changed node in the document tree.
        before: Value in the base document (``None`` when the node was added).
        after: Value in the head document (``None`` when the node was removed).
    """

    kind: str
    pointer: str
    before: Any = None
    after: Any = None


_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "trace")
_DOC_FIELDS = ("description", "summary", "example", "examples", "externalDocs")


def json_pointer_escape(token: str) -> str:
    """Escape a JSON Pointer reference token (RFC 6901).

    Args:
        token: Unescaped path segment.

    Returns:
        Escaped token (``~`` → ``~0``, ``/`` → ``~1``).
    """
    return token.replace("~", "~0").replace("/", "~1")


def json_pointer_join(*parts: str) -> str:
    """Build a JSON Pointer from unescaped segments.

    Args:
        *parts: Path segments (unescaped).

    Returns:
        A JSON Pointer string, or ``""`` when no parts are given.
    """
    if not parts:
        return ""
    return "/" + "/".join(json_pointer_escape(p) for p in parts)


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _stable_key(obj: Any) -> str:
    """Deterministic string key for set membership (servers, tags, security)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def enumerate_openapi_changes(
    base: Dict[str, Any],
    head: Dict[str, Any],
) -> List[RawChange]:
    """Enumerate ordered raw changes between two OpenAPI documents.

    Args:
        base: Older / baseline OpenAPI document.
        head: Newer / candidate OpenAPI document.

    Returns:
        Stable-ordered list of :class:`RawChange` (sorted by pointer, then kind).
    """
    changes: List[RawChange] = []
    changes.extend(_diff_servers(base, head))
    changes.extend(_diff_security_top(base, head))
    changes.extend(_diff_tags(base, head))
    changes.extend(_diff_info_docs(base, head))
    changes.extend(_diff_paths(base, head))
    changes.extend(_diff_component_schemas(base, head))
    changes.extend(_diff_component_security_schemes(base, head))

    changes.sort(key=lambda c: (c.pointer, c.kind))
    return changes


def _emit(
    changes: List[RawChange],
    kind: str,
    pointer: str,
    before: Any = None,
    after: Any = None,
) -> None:
    changes.append(RawChange(kind=kind, pointer=pointer, before=before, after=after))


def _diff_info_docs(base: Dict[str, Any], head: Dict[str, Any]) -> List[RawChange]:
    changes: List[RawChange] = []
    _diff_doc_fields(changes, _as_dict(base.get("info")), _as_dict(head.get("info")), json_pointer_join("info"))
    return changes


def _diff_doc_fields(
    changes: List[RawChange],
    base_obj: Dict[str, Any],
    head_obj: Dict[str, Any],
    parent_pointer: str,
) -> None:
    """Emit docs-only changes for known documentation fields on an object."""
    for field in _DOC_FIELDS:
        bv = base_obj.get(field)
        hv = head_obj.get(field)
        if bv == hv:
            continue
        if field == "description":
            kind = "docs_description"
        elif field == "summary":
            kind = "docs_summary"
        elif field in ("example", "examples"):
            kind = "docs_example"
        else:
            kind = "docs_external_docs"
        _emit(
            changes,
            kind,
            f"{parent_pointer}/{json_pointer_escape(field)}",
            before=bv,
            after=hv,
        )


def _diff_servers(base: Dict[str, Any], head: Dict[str, Any]) -> List[RawChange]:
    changes: List[RawChange] = []
    base_servers = _as_list(base.get("servers"))
    head_servers = _as_list(head.get("servers"))
    base_by_url = {_server_url(s): s for s in base_servers if isinstance(s, dict)}
    head_by_url = {_server_url(s): s for s in head_servers if isinstance(s, dict)}

    for url in sorted(set(base_by_url) - set(head_by_url)):
        _emit(changes, "server_removed", json_pointer_join("servers", url), before=base_by_url[url])
    for url in sorted(set(head_by_url) - set(base_by_url)):
        _emit(changes, "server_added", json_pointer_join("servers", url), after=head_by_url[url])
    for url in sorted(set(base_by_url) & set(head_by_url)):
        _diff_doc_fields(
            changes,
            base_by_url[url],
            head_by_url[url],
            json_pointer_join("servers", url),
        )
    return changes


def _server_url(server: Dict[str, Any]) -> str:
    url = server.get("url")
    return str(url) if url is not None else _stable_key(server)


def _diff_tags(base: Dict[str, Any], head: Dict[str, Any]) -> List[RawChange]:
    changes: List[RawChange] = []
    base_tags = {
        str(t.get("name")): t
        for t in _as_list(base.get("tags"))
        if isinstance(t, dict) and t.get("name")
    }
    head_tags = {
        str(t.get("name")): t
        for t in _as_list(head.get("tags"))
        if isinstance(t, dict) and t.get("name")
    }
    for name in sorted(set(base_tags) | set(head_tags)):
        bt = base_tags.get(name)
        ht = head_tags.get(name)
        pointer = json_pointer_join("tags", name)
        if bt is None and ht is not None:
            _emit(changes, "docs_tag", pointer, after=ht)
        elif bt is not None and ht is None:
            _emit(changes, "docs_tag", pointer, before=bt)
        elif bt != ht:
            _emit(changes, "docs_tag", pointer, before=bt, after=ht)
    return changes


def _diff_security_top(base: Dict[str, Any], head: Dict[str, Any]) -> List[RawChange]:
    return _diff_security_arrays(
        _as_list(base.get("security")),
        _as_list(head.get("security")),
        json_pointer_join("security"),
    )


def _diff_security_arrays(
    base_sec: List[Any],
    head_sec: List[Any],
    pointer: str,
) -> List[RawChange]:
    changes: List[RawChange] = []
    base_keys = {_stable_key(s) for s in base_sec}
    head_keys = {_stable_key(s) for s in head_sec}
    if base_keys == head_keys:
        return changes

    added = head_keys - base_keys
    removed = base_keys - head_keys
    base_open = len(base_sec) == 0 or any(s == {} for s in base_sec if isinstance(s, dict))
    head_open = len(head_sec) == 0 or any(s == {} for s in head_sec if isinstance(s, dict))

    if added and not removed:
        _emit(changes, "security_tightened", pointer, before=base_sec, after=head_sec)
    elif removed and not added:
        _emit(changes, "security_relaxed", pointer, before=base_sec, after=head_sec)
    elif base_open and not head_open:
        _emit(changes, "security_tightened", pointer, before=base_sec, after=head_sec)
    elif head_open and not base_open:
        _emit(changes, "security_relaxed", pointer, before=base_sec, after=head_sec)
    elif added or removed:
        _emit(changes, "security_tightened", pointer, before=base_sec, after=head_sec)
    return changes


def _diff_component_security_schemes(
    base: Dict[str, Any], head: Dict[str, Any]
) -> List[RawChange]:
    """Grade removed security scheme *definitions* as tightened (dependents break).

    Newly added scheme definitions alone are not emitted — tightening is detected
    when a requirement array starts referencing them.
    """
    changes: List[RawChange] = []
    bc = _as_dict(_as_dict(base.get("components")).get("securitySchemes"))
    hc = _as_dict(_as_dict(head.get("components")).get("securitySchemes"))
    for name in sorted(set(bc) - set(hc)):
        _emit(
            changes,
            "security_tightened",
            json_pointer_join("components", "securitySchemes", name),
            before=bc[name],
        )
    return changes


def _diff_paths(base: Dict[str, Any], head: Dict[str, Any]) -> List[RawChange]:
    changes: List[RawChange] = []
    bp = _as_dict(base.get("paths"))
    hp = _as_dict(head.get("paths"))

    for path in sorted(set(bp) - set(hp)):
        _emit(changes, "path_removed", json_pointer_join("paths", path), before=bp[path])
    for path in sorted(set(hp) - set(bp)):
        _emit(changes, "path_added", json_pointer_join("paths", path), after=hp[path])

    for path in sorted(set(bp) & set(hp)):
        changes.extend(
            _diff_path_item(
                _as_dict(bp[path]),
                _as_dict(hp[path]),
                json_pointer_join("paths", path),
            )
        )
    return changes


def _diff_path_item(
    base_item: Dict[str, Any],
    head_item: Dict[str, Any],
    path_pointer: str,
) -> List[RawChange]:
    changes: List[RawChange] = []
    _diff_doc_fields(changes, base_item, head_item, path_pointer)

    for method in _HTTP_METHODS:
        b_op = base_item.get(method)
        h_op = head_item.get(method)
        op_pointer = f"{path_pointer}/{method}"
        if isinstance(b_op, dict) and not isinstance(h_op, dict):
            _emit(changes, "operation_removed", op_pointer, before=b_op)
        elif isinstance(h_op, dict) and not isinstance(b_op, dict):
            _emit(changes, "operation_added", op_pointer, after=h_op)
        elif isinstance(b_op, dict) and isinstance(h_op, dict):
            changes.extend(_diff_operation(b_op, h_op, op_pointer))
    return changes


def _diff_operation(
    base_op: Dict[str, Any],
    head_op: Dict[str, Any],
    op_pointer: str,
) -> List[RawChange]:
    changes: List[RawChange] = []
    _diff_doc_fields(changes, base_op, head_op, op_pointer)

    if "security" in base_op or "security" in head_op:
        base_sec = _as_list(base_op.get("security")) if "security" in base_op else []
        head_sec = _as_list(head_op.get("security")) if "security" in head_op else []
        if "security" not in base_op and head_sec:
            _emit(
                changes,
                "security_tightened",
                f"{op_pointer}/security",
                before=None,
                after=head_op.get("security"),
            )
        elif "security" not in head_op and base_sec:
            _emit(
                changes,
                "security_relaxed",
                f"{op_pointer}/security",
                before=base_op.get("security"),
                after=None,
            )
        else:
            changes.extend(_diff_security_arrays(base_sec, head_sec, f"{op_pointer}/security"))

    changes.extend(
        _diff_parameters(
            _as_list(base_op.get("parameters")),
            _as_list(head_op.get("parameters")),
            op_pointer,
        )
    )
    changes.extend(
        _diff_responses(
            _as_dict(base_op.get("responses")),
            _as_dict(head_op.get("responses")),
            f"{op_pointer}/responses",
        )
    )

    bb = _as_dict(base_op.get("requestBody"))
    hb = _as_dict(head_op.get("requestBody"))
    if bb or hb:
        _diff_doc_fields(changes, bb, hb, f"{op_pointer}/requestBody")
        changes.extend(
            _diff_media_schemas(
                _as_dict(bb.get("content")),
                _as_dict(hb.get("content")),
                f"{op_pointer}/requestBody/content",
            )
        )
    return changes


def _param_identity(param: Dict[str, Any]) -> str:
    name = str(param.get("name", ""))
    loc = str(param.get("in", ""))
    return f"{loc}:{name}"


def _diff_parameters(
    base_params: List[Any],
    head_params: List[Any],
    op_pointer: str,
) -> List[RawChange]:
    """Diff operation parameters.

    Parameter *removal* is intentionally silent (clients can stop sending the
    query/header). Adds and optional→required flips are classified.
    """
    changes: List[RawChange] = []
    bp = {_param_identity(p): p for p in base_params if isinstance(p, dict)}
    hp = {_param_identity(p): p for p in head_params if isinstance(p, dict)}

    for key in sorted(set(hp) - set(bp)):
        p = hp[key]
        kind = "required_param_added" if p.get("required") is True else "optional_param_added"
        _emit(changes, kind, f"{op_pointer}/parameters/{json_pointer_escape(key)}", after=p)

    for key in sorted(set(bp) & set(hp)):
        b = bp[key]
        h = hp[key]
        ptr = f"{op_pointer}/parameters/{json_pointer_escape(key)}"
        _diff_doc_fields(changes, b, h, ptr)
        if b.get("required") is not True and h.get("required") is True:
            _emit(changes, "required_param_added", f"{ptr}/required", before=False, after=True)
        changes.extend(
            _diff_schema(_as_dict(b.get("schema")), _as_dict(h.get("schema")), f"{ptr}/schema")
        )
    return changes


def _diff_responses(
    base_resp: Dict[str, Any],
    head_resp: Dict[str, Any],
    responses_pointer: str,
) -> List[RawChange]:
    changes: List[RawChange] = []
    for code in sorted(set(base_resp) - set(head_resp), key=str):
        _emit(
            changes,
            "response_removed",
            f"{responses_pointer}/{json_pointer_escape(str(code))}",
            before=base_resp[code],
        )
    for code in sorted(set(head_resp) - set(base_resp), key=str):
        _emit(
            changes,
            "response_added",
            f"{responses_pointer}/{json_pointer_escape(str(code))}",
            after=head_resp[code],
        )
    for code in sorted(set(base_resp) & set(head_resp), key=str):
        b = _as_dict(base_resp[code])
        h = _as_dict(head_resp[code])
        ptr = f"{responses_pointer}/{json_pointer_escape(str(code))}"
        _diff_doc_fields(changes, b, h, ptr)
        changes.extend(
            _diff_media_schemas(
                _as_dict(b.get("content")),
                _as_dict(h.get("content")),
                f"{ptr}/content",
            )
        )
    return changes


def _diff_media_schemas(
    base_content: Dict[str, Any],
    head_content: Dict[str, Any],
    content_pointer: str,
) -> List[RawChange]:
    changes: List[RawChange] = []
    for mt in sorted(set(base_content) | set(head_content)):
        b = _as_dict(_as_dict(base_content.get(mt)).get("schema"))
        h = _as_dict(_as_dict(head_content.get(mt)).get("schema"))
        schema_ptr = f"{content_pointer}/{json_pointer_escape(mt)}/schema"
        if mt not in base_content and mt in head_content:
            changes.extend(_diff_schema({}, h, schema_ptr))
        elif mt in base_content and mt not in head_content:
            changes.extend(_diff_schema(b, {}, schema_ptr))
        else:
            changes.extend(_diff_schema(b, h, schema_ptr))
        bm = _as_dict(base_content.get(mt))
        hm = _as_dict(head_content.get(mt))
        _diff_doc_fields(changes, bm, hm, f"{content_pointer}/{json_pointer_escape(mt)}")
    return changes


def _diff_component_schemas(base: Dict[str, Any], head: Dict[str, Any]) -> List[RawChange]:
    changes: List[RawChange] = []
    bs = _as_dict(_as_dict(base.get("components")).get("schemas"))
    hs = _as_dict(_as_dict(head.get("components")).get("schemas"))

    for name in sorted(set(bs) - set(hs)):
        changes.extend(
            _diff_schema(_as_dict(bs[name]), {}, json_pointer_join("components", "schemas", name))
        )
    for name in sorted(set(hs) - set(bs)):
        changes.extend(
            _diff_schema({}, _as_dict(hs[name]), json_pointer_join("components", "schemas", name))
        )
    for name in sorted(set(bs) & set(hs)):
        changes.extend(
            _diff_schema(
                _as_dict(bs[name]),
                _as_dict(hs[name]),
                json_pointer_join("components", "schemas", name),
            )
        )
    return changes


def _diff_schema(
    base: Dict[str, Any],
    head: Dict[str, Any],
    pointer: str,
) -> List[RawChange]:
    """Recursively compare two JSON Schema objects under an OpenAPI document."""
    changes: List[RawChange] = []
    if not base and not head:
        return changes
    if base == head:
        return changes

    _diff_doc_fields(changes, base, head, pointer)

    bt = base.get("type")
    ht = head.get("type")
    if bt != ht and (bt is not None or ht is not None) and base and head:
        _emit(changes, "type_narrowed", f"{pointer}/type", before=bt, after=ht)

    if "enum" in base or "enum" in head:
        be = set(_as_list(base.get("enum")))
        he = set(_as_list(head.get("enum")))
        if be or he:
            for lost in sorted(be - he, key=lambda x: str(x)):
                _emit(changes, "enum_value_removed", f"{pointer}/enum", before=lost, after=None)
            for gained in sorted(he - be, key=lambda x: str(x)):
                _emit(changes, "enum_value_added", f"{pointer}/enum", before=None, after=gained)

    br = set(_as_list(base.get("required")))
    hr = set(_as_list(head.get("required")))
    for name in sorted(hr - br):
        _emit(
            changes,
            "optional_to_required",
            f"{pointer}/required/{json_pointer_escape(str(name))}",
            before=False,
            after=True,
        )

    bprops = _as_dict(base.get("properties"))
    hprops = _as_dict(head.get("properties"))
    for name in sorted(set(bprops) - set(hprops)):
        _emit(
            changes,
            "property_removed",
            f"{pointer}/properties/{json_pointer_escape(name)}",
            before=bprops[name],
        )
    for name in sorted(set(hprops) - set(bprops)):
        _emit(
            changes,
            "property_added",
            f"{pointer}/properties/{json_pointer_escape(name)}",
            after=hprops[name],
        )
    for name in sorted(set(bprops) & set(hprops)):
        changes.extend(
            _diff_schema(
                _as_dict(bprops[name]),
                _as_dict(hprops[name]),
                f"{pointer}/properties/{json_pointer_escape(name)}",
            )
        )

    if "items" in base or "items" in head:
        changes.extend(
            _diff_schema(
                _as_dict(base.get("items")),
                _as_dict(head.get("items")),
                f"{pointer}/items",
            )
        )

    bref = base.get("$ref")
    href = head.get("$ref")
    if (isinstance(bref, str) or isinstance(href, str)) and base and head and bref != href:
        _emit(changes, "type_narrowed", f"{pointer}/$ref", before=bref, after=href)

    return changes
