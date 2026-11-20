"""Apply lint-fix JSON Patch operations to a document's text, keeping its serialization (GVM-3.3).

The round-trip engine behind ``apiome lint <file> --fix``: the GVM-3.2 plan
(``POST /v1/lint/fixes/plan``) gives RFC 6902 operations against the parsed document, and this
module applies them to the **original text** so the rewritten file differs from it only where a
fix changed something:

* **YAML** is loaded with the ``ruamel.yaml`` round-trip loader, so comments, key order and
  quoting survive; the operations edit the loaded tree in place and it is dumped back.
* **JSON** keeps its key order and the indentation it was found with (two spaces, four, a tab,
  or a single line), and its trailing newline.

File mode itself is wired once GOV-3.5 (#4442) adds ``apiome lint <file>``; until then the module
is the shared engine (GVM-5.1's language server reuses it) and is exercised by its tests.

Only ``add``, ``remove``, ``replace`` and ``move`` are supported — the operations a lint fix may
use. Anything else, or a pointer that does not resolve, raises :class:`FixApplyError` and the
text is not rewritten.
"""

from __future__ import annotations

import copy
import io
import json
import re
from typing import Any

from ruamel.yaml import YAML

#: The operations a lint fix may carry (GVM-3.1).
SUPPORTED_OPS = ("add", "remove", "replace", "move")


class FixApplyError(ValueError):
    """An operation could not be applied; the document is left unchanged."""


def _yaml() -> YAML:
    """A round-trip YAML instance that keeps quotes and does not re-wrap long lines."""
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.width = 4096
    return yaml


def _yaml_indent(text: str) -> tuple[int, int, int]:
    """The ``(mapping, sequence, offset)`` indentation a YAML document was written with.

    ruamel writes every block sequence with one style, so the style the file uses is detected
    from its first nested mapping and its first block sequence (``key:`` then ``- item``):
    ``offset`` is how far the dash sits right of its key, ``sequence`` how far the item does.
    Defaults to two-space mappings and dashes flush with their key.
    """
    mapping = 2
    nested = re.search(r"^( *)[^\s#-][^\n]*:[ \t]*(?:#[^\n]*)?\n\1( +)[^\s#-]", text, re.M)
    if nested:
        mapping = len(nested.group(2))
    offset = 0
    sequence = mapping
    block = re.search(r"^( *)[^\s#-][^\n]*:[ \t]*(?:#[^\n]*)?\n\1( *)-( +)\S", text, re.M)
    if block:
        offset = len(block.group(2))
        sequence = offset + 1 + len(block.group(3))
    return mapping, max(sequence, offset + 2), offset


def is_json_text(text: str) -> bool:
    """Whether ``text`` is a JSON document (its first non-blank character opens an object).

    Args:
        text: The document text.

    Returns:
        ``True`` for JSON, ``False`` for YAML.
    """
    stripped = text.lstrip()
    return stripped.startswith("{") or stripped.startswith("[")


def _json_indent(text: str) -> int | str | None:
    """The indentation a JSON document was written with: spaces, ``"\\t"``, or ``None`` (one line)."""
    match = re.search(r"\n([ \t]+)\S", text)
    if match is None:
        return None
    indent = match.group(1)
    return "\t" if indent.startswith("\t") else len(indent)


def _tokens(pointer: str) -> list[str]:
    """Split an RFC 6901 pointer into its unescaped tokens (``""`` is the whole document)."""
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise FixApplyError(f"not a JSON pointer: {pointer!r}")
    return [t.replace("~1", "/").replace("~0", "~") for t in pointer[1:].split("/")]


def _index(container: list, token: str, *, allow_end: bool) -> int:
    """The list index ``token`` names; ``-`` (or ``len``) only when ``allow_end``."""
    if token == "-" and allow_end:
        return len(container)
    if not token.isdigit():
        raise FixApplyError(f"not an array index: {token!r}")
    index = int(token)
    limit = len(container) if allow_end else len(container) - 1
    if index > limit:
        raise FixApplyError(f"array index {index} out of range")
    return index


def _parent(document: Any, pointer: str) -> tuple[Any, str]:
    """The container holding the node at ``pointer``, and the node's key or index token."""
    tokens = _tokens(pointer)
    if not tokens:
        raise FixApplyError("an operation may not replace the whole document")
    node = document
    for token in tokens[:-1]:
        if isinstance(node, dict) and token in node:
            node = node[token]
        elif isinstance(node, list):
            node = node[_index(node, token, allow_end=False)]
        else:
            raise FixApplyError(f"path does not exist: {pointer}")
    return node, tokens[-1]


def _remove(document: Any, pointer: str) -> Any:
    """Remove and return the node at ``pointer``."""
    parent, token = _parent(document, pointer)
    if isinstance(parent, dict):
        if token not in parent:
            raise FixApplyError(f"path does not exist: {pointer}")
        return parent.pop(token)
    if isinstance(parent, list):
        return parent.pop(_index(parent, token, allow_end=False))
    raise FixApplyError(f"path does not exist: {pointer}")


def _add(document: Any, pointer: str, value: Any) -> None:
    """Add ``value`` at ``pointer`` (an object member is set; an array item is inserted)."""
    parent, token = _parent(document, pointer)
    if isinstance(parent, dict):
        parent[token] = value
    elif isinstance(parent, list):
        parent.insert(_index(parent, token, allow_end=True), value)
    else:
        raise FixApplyError(f"path does not exist: {pointer}")


def _replace(document: Any, pointer: str, value: Any) -> None:
    """Replace the existing node at ``pointer`` with ``value``, keeping its position."""
    parent, token = _parent(document, pointer)
    if isinstance(parent, dict) and token in parent:
        parent[token] = value
    elif isinstance(parent, list):
        parent[_index(parent, token, allow_end=False)] = value
    else:
        raise FixApplyError(f"path does not exist: {pointer}")


def apply_ops(document: Any, ops: list[dict[str, Any]]) -> None:
    """Apply RFC 6902 ``ops`` to ``document`` in place, in order.

    Args:
        document: The parsed document (plain or ruamel round-trip containers).
        ops: The operations, each ``{"op", "path", "value"?, "from"?}``.

    Raises:
        FixApplyError: An unsupported operation, or a pointer that does not resolve.
    """
    for op in ops:
        kind = op.get("op")
        path = str(op.get("path", ""))
        if kind not in SUPPORTED_OPS:
            raise FixApplyError(f"unsupported operation {kind!r}")
        if kind == "remove":
            _remove(document, path)
        elif kind == "add":
            _add(document, path, copy.deepcopy(op.get("value")))
        elif kind == "replace":
            _replace(document, path, copy.deepcopy(op.get("value")))
        else:
            _add(document, path, _remove(document, str(op.get("from", ""))))


def rewrite_document_text(text: str, ops: list[dict[str, Any]]) -> str:
    """Apply ``ops`` to the document in ``text`` and return the new text, serialized as found.

    Args:
        text: The original YAML or JSON document text.
        ops: The ready fixes' operations, in the order the plan applies them
            (the plan's ``format=patch`` rendering).

    Returns:
        The rewritten text. Unchanged when ``ops`` is empty.

    Raises:
        FixApplyError: An operation could not be applied, or the text is not a mapping document.
    """
    if not ops:
        return text
    if is_json_text(text):
        document = json.loads(text)
        apply_ops(document, ops)
        body = json.dumps(document, indent=_json_indent(text), ensure_ascii=False)
        return body + ("\n" if text.endswith("\n") else "")
    yaml = _yaml()
    # ruamel drops a leading ``---`` unless asked to write one.
    yaml.explicit_start = text.lstrip().startswith("---")
    mapping, sequence, offset = _yaml_indent(text)
    yaml.indent(mapping=mapping, sequence=sequence, offset=offset)
    document = yaml.load(text)
    if not isinstance(document, dict):
        raise FixApplyError("the document is not a YAML mapping")
    apply_ops(document, ops)
    out = io.StringIO()
    yaml.dump(document, out)
    return out.getvalue()
