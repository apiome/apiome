"""The patch model of suggested changes — COL-4.2 (#4526).

A suggestion is an RFC 6902 JSON patch over one model element's canonical JSON. This module holds
the two pure halves of it:

* :func:`apply_patch` — a small, bounded RFC 6902 applier (``add``, ``remove``, ``replace``,
  ``test``), used when a suggestion is made to compute ``proposed`` from ``base``.
* :func:`rebase_suggestion` — what applying does later. It is the **merge-session engine**
  (:func:`app.schema_merge.merge_json_three_way`) with ``base`` as the merge base, the element as
  it is now as "ours", and ``proposed`` as "theirs": an untouched element takes the proposal, an
  edit elsewhere in the element is merged around, and an overlapping edit is a conflict. There is
  deliberately no second merge path.
"""

from __future__ import annotations

import copy
from typing import Any, List, Mapping, Sequence, Tuple

from .schema_merge import _MISSING, json_equal, merge_json_three_way

__all__ = [
    "MAX_PATCH_OPS",
    "PatchError",
    "apply_patch",
    "parse_pointer",
    "rebase_suggestion",
]

#: The most operations one suggestion may carry.
MAX_PATCH_OPS = 50
#: The deepest pointer accepted.
MAX_POINTER_DEPTH = 32

_OPS = {"add", "remove", "replace", "test"}


class PatchError(ValueError):
    """A patch that is malformed or does not apply to its document."""


def parse_pointer(pointer: str) -> List[str]:
    """Split an RFC 6901 JSON pointer into unescaped tokens.

    Args:
        pointer: e.g. ``/data/enum/0`` or ``/description``.

    Returns:
        The tokens.

    Raises:
        PatchError: for an empty pointer (the whole element cannot be replaced), one that does not
            start with ``/``, or one deeper than :data:`MAX_POINTER_DEPTH`.
    """
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise PatchError(f"path must be a JSON pointer starting with '/': {pointer!r}")
    tokens = [t.replace("~1", "/").replace("~0", "~") for t in pointer[1:].split("/")]
    if len(tokens) > MAX_POINTER_DEPTH:
        raise PatchError("path is too deep")
    return tokens


def _child(container: Any, token: str, *, for_add: bool = False) -> Tuple[Any, Any]:
    """Resolve one token against a container.

    Returns:
        ``(container, key)`` where ``key`` is a dict key or a list index.

    Raises:
        PatchError: when the token does not address the container.
    """
    if isinstance(container, dict):
        return container, token
    if isinstance(container, list):
        if for_add and token == "-":
            return container, len(container)
        if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
            raise PatchError(f"'{token}' is not an array index")
        index = int(token)
        limit = len(container) if for_add else len(container) - 1
        if index > limit:
            raise PatchError(f"index {index} is out of range")
        return container, index
    raise PatchError(f"cannot descend into a {type(container).__name__}")


def _walk(doc: Any, tokens: Sequence[str]) -> Any:
    """Return the value at ``tokens`` (all but the last are walked by the caller's op)."""
    node = doc
    for token in tokens:
        parent, key = _child(node, token)
        if isinstance(parent, dict) and key not in parent:
            raise PatchError(f"'{token}' does not exist")
        node = parent[key]
    return node


def apply_patch(document: Mapping[str, Any], patch: Sequence[Mapping[str, Any]]) -> Any:
    """Apply an RFC 6902 patch to a copy of ``document``.

    Only ``add``, ``remove``, ``replace``, and ``test`` are supported — ``move`` and ``copy`` are
    expressible as those and keep the rendered diff honest. The root cannot be replaced.

    Args:
        document: The element's canonical JSON.
        patch: The operations.

    Returns:
        The patched copy.

    Raises:
        PatchError: for a malformed patch, a path that does not resolve, or a failed ``test``.
    """
    if not isinstance(patch, (list, tuple)) or not patch:
        raise PatchError("a patch is a non-empty list of operations")
    if len(patch) > MAX_PATCH_OPS:
        raise PatchError(f"a patch may hold at most {MAX_PATCH_OPS} operations")
    doc = copy.deepcopy(dict(document))
    for index, op in enumerate(patch):
        if not isinstance(op, Mapping) or op.get("op") not in _OPS:
            raise PatchError(f"operation {index}: op must be one of {sorted(_OPS)}")
        tokens = parse_pointer(op.get("path"))
        kind = op["op"]
        if kind in ("add", "replace", "test") and "value" not in op:
            raise PatchError(f"operation {index}: '{kind}' needs a value")
        parent = _walk(doc, tokens[:-1])
        container, key = _child(parent, tokens[-1], for_add=(kind == "add"))
        exists = key in container if isinstance(container, dict) else key < len(container)
        if kind == "test":
            if not exists or not json_equal(container[key], op["value"]):
                raise PatchError(f"operation {index}: test failed at {op['path']}")
        elif kind == "add":
            if isinstance(container, list):
                container.insert(key, copy.deepcopy(op["value"]))
            else:
                container[key] = copy.deepcopy(op["value"])
        elif not exists:
            raise PatchError(f"operation {index}: nothing at {op['path']} to {kind}")
        elif kind == "remove":
            del container[key]
        else:
            container[key] = copy.deepcopy(op["value"])
    return doc


def rebase_suggestion(base: Any, current: Any, proposed: Any) -> Tuple[Any, List[str]]:
    """Merge a suggestion onto the element as it is now, with the merge-session engine.

    Args:
        base: The element when the suggestion was made.
        current: The element now, or ``None`` when it has been deleted.
        proposed: ``base`` with the suggestion's patch applied.

    Returns:
        ``(merged, conflict_paths)``. ``merged`` is the element to write when there are no
        conflicts; ``conflict_paths`` (dotted, like merge-session conflicts) is non-empty when an
        edit made since the suggestion overlaps it, and ``["<deleted>"]`` when the element is gone.
    """
    if current is None:
        return None, ["<deleted>"]
    merged, conflicts = merge_json_three_way(base, current, proposed, "")
    if conflicts or merged is _MISSING:
        return None, sorted(set(conflicts)) or ["<root>"]
    return merged, []
