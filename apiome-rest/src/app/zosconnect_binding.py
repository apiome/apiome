"""z/OS Connect API requester / provider binding — MFI-21.2 (#3992).

A z/OS Connect descriptor (:mod:`app.zosconnect_parser`) binds each REST operation to the COBOL
(or PL/I) data structures a CICS / IMS program passes: ``requestStructure`` and
``responseStructure`` are the 01-level records of the copybooks the program was compiled with. The
REST face is an OpenAPI document; the mainframe face is those copybooks. This module keeps the
three linked in the catalog:

* **Recorded on import** (:func:`binding_metadata`) — a descriptor revision's
  ``format_metadata.zosConnectBinding`` (its operations and the structures each binds), and a
  copybook revision's ``format_metadata.cobolRecords`` (every 01-level record it declares, not only
  the first, which is all the copybook model keeps).
* **Suggested as links** (:func:`shared_cobol_structures`, :func:`matches_api_title`) — the
  cross-format identity suggestions (:mod:`app.api_identity_service`) pair a descriptor with the
  copybooks that declare its structures and with the OpenAPI whose title it names; a user
  confirms each link.
* **Browsed** (:func:`resolve_binding`) — each operation with the copybook items that hold its
  structures and the OpenAPI items that define it, linked ones first.

The binding is also on the descriptor's canonical model (each operation's
``zosconnect_request_structure`` / ``zosconnect_response_structure`` extras), so a version diff
shows a structure that changed.

Pure: models and rows in, plain dicts out.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

from .canonical_model import CanonicalApi

__all__ = [
    "BINDING_KEY",
    "COBOL_RECORDS_KEY",
    "cobol_record_names",
    "zosconnect_binding",
    "binding_metadata",
    "shared_cobol_structures",
    "matches_api_title",
    "resolve_binding",
]

#: ``format_metadata`` key of a descriptor's binding.
BINDING_KEY = "zosConnectBinding"
#: ``format_metadata`` key of a copybook's 01-level record names.
COBOL_RECORDS_KEY = "cobolRecords"


def _upper(value: Any) -> Optional[str]:
    """A COBOL name as compared: trimmed and upper-cased (COBOL names are case-insensitive)."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().upper()


def cobol_record_names(model: CanonicalApi) -> List[str]:
    """Return every 01-level record name a copybook declares, in source order.

    Args:
        model: A ``cobolcopybook`` canonical model.

    Returns:
        The names (upper case, de-duplicated). Read from the retained source so every 01 record
        counts; the recorded root alone when the source was not kept; empty for another format.
    """
    if model.format != "cobolcopybook":
        return []
    from .cobolcopybook_parser import iter_definition_lines

    raw = model.raw if isinstance(model.raw, Mapping) else {}
    text = raw.get("cobolcopybook")
    names: List[str] = []
    if isinstance(text, str):
        names = [line.name for line in iter_definition_lines(text) if line.level == 1 and not line.is_condition]
    if not names:
        names = [model.extras.get("cobolcopybook_root")]
    out: List[str] = []
    for name in names:
        upper = _upper(name)
        if upper and upper not in out:
            out.append(upper)
    return out


def zosconnect_binding(model: CanonicalApi) -> Optional[Dict[str, Any]]:
    """Return a z/OS Connect descriptor's binding, or ``None`` for another format.

    Args:
        model: A ``zosconnect`` canonical model.

    Returns:
        ``{"kind", "api": {"title", "specification", "basePath"}, "operations": [...],
        "structures": [...]}`` — each operation's ``operation`` key (``GET /items/{sku}/stock``,
        the key an OpenAPI operation has), ``operationId``, ``method``, ``path``,
        ``requestStructure``, ``responseStructure`` and ``program``; ``structures`` every bound
        structure, sorted.
    """
    if model.format != "zosconnect":
        return None
    extras = model.extras or {}
    operations: List[Dict[str, Any]] = []
    structures: Set[str] = set()
    for entry in extras.get("zosconnect_operations") or []:
        if not isinstance(entry, Mapping):
            continue
        method = str(entry.get("method") or "").upper()
        path = str(entry.get("path") or "")
        request, response = _upper(entry.get("requestStructure")), _upper(entry.get("responseStructure"))
        structures.update(s for s in (request, response) if s)
        operations.append(
            {
                "operation": f"{method} {path}",
                "operationId": entry.get("operationId"),
                "method": method,
                "path": path,
                "requestStructure": request,
                "responseStructure": response,
                "program": entry.get("program"),
            }
        )
    api = extras.get("zosconnect_api") if isinstance(extras.get("zosconnect_api"), Mapping) else {}
    return {
        "kind": extras.get("zosconnect_kind"),
        "api": {key: api.get(key) for key in ("title", "specification", "basePath")},
        "operations": operations,
        "structures": sorted(structures),
    }


def binding_metadata(model: CanonicalApi) -> Dict[str, Any]:
    """Return what a revision records for the binding (empty for an unrelated format).

    Args:
        model: The normalized model.

    Returns:
        ``{"zosConnectBinding": …}`` for a descriptor, ``{"cobolRecords": [...]}`` for a copybook.
    """
    binding = zosconnect_binding(model)
    if binding is not None:
        return {BINDING_KEY: binding}
    records = cobol_record_names(model)
    return {COBOL_RECORDS_KEY: records} if records else {}


def _structures(metadata: Optional[Mapping[str, Any]]) -> Set[str]:
    binding = metadata.get(BINDING_KEY) if isinstance(metadata, Mapping) else None
    if not isinstance(binding, Mapping):
        return set()
    return {s for s in (_upper(v) for v in binding.get("structures") or []) if s}


def _records(metadata: Optional[Mapping[str, Any]]) -> Set[str]:
    records = metadata.get(COBOL_RECORDS_KEY) if isinstance(metadata, Mapping) else None
    if not isinstance(records, list):
        return set()
    return {s for s in (_upper(v) for v in records) if s}


def shared_cobol_structures(left: Optional[Mapping[str, Any]], right: Optional[Mapping[str, Any]]) -> List[str]:
    """The structures one artifact's binding names and the other's copybook declares (either way).

    Args:
        left: One artifact's ``format_metadata``.
        right: The other's.

    Returns:
        The shared structure names, sorted; empty unless one is a descriptor and the other a copybook.
    """
    return sorted((_structures(left) & _records(right)) | (_structures(right) & _records(left)))


def _squash(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def matches_api_title(metadata: Optional[Mapping[str, Any]], row: Mapping[str, Any]) -> bool:
    """Whether a descriptor's target API title names ``row`` (by its title or API identity name).

    Args:
        metadata: The descriptor's ``format_metadata``.
        row: A candidate project row (``name``, ``identity_name``, ``source_format``).

    Returns:
        ``True`` when the titles match, ignoring case and punctuation, and the row is not itself a
        z/OS Connect descriptor.
    """
    binding = metadata.get(BINDING_KEY) if isinstance(metadata, Mapping) else None
    api = binding.get("api") if isinstance(binding, Mapping) else None
    title = _squash(api.get("title")) if isinstance(api, Mapping) else ""
    if not title or row.get("source_format") == "zosconnect":
        return False
    return title in (_squash(row.get("name")), _squash(row.get("identity_name")))


def _ref(peer: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "project_id": str(peer["project_id"]),
        "name": peer.get("name") or "",
        "source_format": peer.get("source_format"),
        "publishable": bool(peer.get("publishable")),
        "linked": bool(peer.get("linked")),
    }


def _ordered(refs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Linked items first, then by name."""
    return sorted(refs, key=lambda ref: (not ref["linked"], ref["name"].lower()))


def resolve_binding(binding: Mapping[str, Any], peers: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Join a descriptor's binding to the catalog items that hold each side of it.

    Args:
        binding: The descriptor's ``zosConnectBinding``.
        peers: Other tenant items: ``project_id``, ``name``, ``source_format``, ``publishable``,
            ``format_metadata``, ``linked`` (in the descriptor's identity group) and
            ``operations`` (their canonical operation keys).

    Returns:
        ``{"api", "kind", "operations": [{…, "request": {"structure", "copybooks"},
        "response": {…}, "openapi": [...]}], "summary": {…}}``. Each list holds item refs
        (``project_id``, ``name``, ``source_format``, ``publishable``, ``linked``), linked first;
        the route serializes them in camelCase (:class:`app.models.ZosConnectBindingResponse`).
    """
    peers = [p for p in peers if p.get("source_format") != "zosconnect"]
    holders: Dict[str, List[Dict[str, Any]]] = {}
    for peer in peers:
        for record in _records(peer.get("format_metadata")):
            holders.setdefault(record, []).append(_ref(peer))

    def side(structure: Optional[str]) -> Optional[Dict[str, Any]]:
        if not structure:
            return None
        return {"structure": structure, "copybooks": _ordered(holders.get(structure, []))}

    operations: List[Dict[str, Any]] = []
    for entry in binding.get("operations") or []:
        key = entry.get("operation")
        openapi = [_ref(p) for p in peers if key in set(p.get("operations") or ())]
        operations.append(
            {
                "operation": entry.get("operation"),
                "operation_id": entry.get("operationId"),
                "method": entry.get("method"),
                "path": entry.get("path"),
                "program": entry.get("program"),
                "request": side(entry.get("requestStructure")),
                "response": side(entry.get("responseStructure")),
                "openapi": _ordered(openapi),
            }
        )
    structures = list(binding.get("structures") or [])
    return {
        "kind": binding.get("kind"),
        "api": binding.get("api") or {},
        "operations": operations,
        "summary": {
            "operations": len(operations),
            "structures": len(structures),
            "structures_with_copybook": sum(1 for s in structures if holders.get(s)),
            "structures_linked": sum(1 for s in structures if any(r["linked"] for r in holders.get(s, []))),
            "operations_with_openapi": sum(1 for op in operations if op["openapi"]),
        },
    }
