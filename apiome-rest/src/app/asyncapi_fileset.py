"""AsyncAPI multi-document fileset bundling — MFI-29.2 (#4389).

Resolves cross-file ``$ref``\\s among :class:`~app.fileset.IntakeFileset` members (no network)
into a single document suitable for :func:`app.asyncapi_parser.parse_asyncapi`.
"""

from __future__ import annotations

import copy
import json
from pathlib import PurePosixPath
from typing import Any, Dict, Set, Tuple

from .fileset import IntakeFileset
from .import_ingestion import IngestionError, parse_document
from .import_source import ImportSourceError

__all__ = ["bundle_asyncapi_fileset"]


def _split_ref(ref: str) -> Tuple[str, str]:
    """Split a JSON Reference into ``(file_part, fragment)``."""
    if "#" in ref:
        file_part, fragment = ref.split("#", 1)
        return file_part, f"#{fragment}" if fragment else ""
    return ref, ""


def _resolve_member_path(base_path: str, ref_path: str) -> str:
    """Resolve *ref_path* relative to *base_path* inside the fileset."""
    base_dir = PurePosixPath(base_path.replace("\\", "/")).parent
    combined = base_dir / ref_path.replace("\\", "/")
    parts: list[str] = []
    for part in combined.parts:
        if part == "..":
            if parts:
                parts.pop()
            else:
                raise ImportSourceError(
                    f"Unresolved $ref {ref_path!r}: path escapes the fileset root"
                )
        elif part != ".":
            parts.append(part)
    return "/".join(parts)


def _json_pointer_get(document: Any, pointer: str) -> Any:
    """Follow an RFC 6901 JSON Pointer (``#/components/...``) into *document*."""
    if not pointer or pointer == "#":
        return document
    if not pointer.startswith("#/"):
        raise ImportSourceError(f"Unsupported JSON pointer {pointer!r}")
    current = document
    for raw_part in pointer[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if part not in current:
                raise ImportSourceError(
                    f"JSON pointer {pointer!r} not found (missing key {part!r})"
                )
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise ImportSourceError(
                    f"JSON pointer {pointer!r} not found (invalid index {part!r})"
                ) from exc
        else:
            raise ImportSourceError(f"JSON pointer {pointer!r} not found")
    return current


def _load_member(path: str, members: Dict[str, str]) -> Dict[str, Any]:
    """Parse one fileset member as JSON/YAML."""
    if path not in members:
        raise ImportSourceError(
            f"Fileset has no member {path!r} required to resolve a cross-file $ref"
        )
    try:
        return parse_document(members[path], source_label=path)
    except IngestionError as exc:
        raise ImportSourceError(str(exc)) from exc


def _resolve_external_ref(
    ref: str,
    base_path: str,
    members: Dict[str, str],
) -> Tuple[Any, str]:
    """Resolve a cross-file ``$ref`` to its target value and the member path it lives in."""
    file_part, fragment = _split_ref(ref)
    if not file_part:
        raise ImportSourceError(f"Internal $ref {ref!r} cannot be resolved across files")

    member_path = _resolve_member_path(base_path, file_part)
    document = _load_member(member_path, members)
    if fragment:
        try:
            target = _json_pointer_get(document, fragment)
        except ImportSourceError as exc:
            raise ImportSourceError(
                f"Unresolved $ref {ref!r}: {exc}"
            ) from exc
    else:
        target = document
    return target, member_path


def _deref_node(
    value: Any,
    *,
    base_path: str,
    members: Dict[str, str],
    stack: Set[Tuple[str, str]],
) -> Any:
    """Recursively inline cross-file ``$ref``\\s among fileset members."""
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref and not ref.startswith("#"):
            key = (base_path, ref)
            if key in stack:
                raise ImportSourceError(f"Circular cross-file $ref detected at {ref!r}")
            stack.add(key)
            try:
                target, member_path = _resolve_external_ref(ref, base_path, members)
            finally:
                stack.discard(key)
            return _deref_node(
                copy.deepcopy(target),
                base_path=member_path,
                members=members,
                stack=stack,
            )
        return {
            key: _deref_node(item, base_path=base_path, members=members, stack=stack)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _deref_node(item, base_path=base_path, members=members, stack=stack)
            for item in value
        ]
    return value


def bundle_asyncapi_fileset(fileset: IntakeFileset) -> str:
    """Bundle a multi-file AsyncAPI fileset into canonical JSON text.

    Cross-file ``$ref``\\s are resolved only among ``fileset.members``; a reference to a
    missing member raises :class:`~app.import_source.ImportSourceError` naming the ref.

    Args:
        fileset: The root document plus sibling members.

    Returns:
        UTF-8 JSON text of the bundled, dereferenced-at-file-boundaries document ready for
        :func:`app.asyncapi_parser.parse_asyncapi`.
    """
    root_path = fileset.root
    root_doc = _load_member(root_path, fileset.members)
    bundled = _deref_node(
        copy.deepcopy(root_doc),
        base_path=root_path,
        members=fileset.members,
        stack=set(),
    )
    if not isinstance(bundled, dict):
        raise ImportSourceError("AsyncAPI root document must be a mapping after bundling")
    return json.dumps(bundled, sort_keys=True, separators=(",", ":"))
