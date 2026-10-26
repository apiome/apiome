"""Lexer for Bruno's ``.bru`` files ("Bru lang") — MFI-32.4 (#4406).

A ``.bru`` file is a sequence of named blocks, each opened on its own line at column 0 and closed
by a line holding only the closing bracket::

    meta {
      name: Get user
      type: http
      seq: 1
    }

    get {
      url: {{baseUrl}}/users/:id
      body: none
      auth: inherit
    }

    body:json {
      {
        "name": "Ada"
      }
    }

    vars:secret [
      apiKey
    ]

There are three kinds of block:

* **dictionary** blocks (``meta``, ``get``, ``headers``, ``params:query``, ``auth:bearer``,
  ``vars:pre-request``, ``body:form-urlencoded`` …) hold one ``key: value`` per line. A key
  prefixed ``~`` is disabled; a key may be double-quoted; a value written ``'''`` continues on the
  following lines up to a closing ``'''``;
* **text** blocks (``body:json``, ``body:xml``, ``script:pre-request``, ``tests``, ``docs`` …) hold
  verbatim text indented two spaces;
* **list** blocks (``vars:secret [ … ]``) hold one name per line.

This module only tokenises; :mod:`app.bruno_parser` gives the blocks their meaning. It never
evaluates a script.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

__all__ = ["BruBlock", "BruEntry", "BruSyntaxError", "DICT_BLOCKS", "TEXT_BLOCKS", "looks_like_bru", "parse_bru"]

#: Blocks whose body is verbatim text rather than ``key: value`` lines.
TEXT_BLOCKS = frozenset(
    {
        "body:json",
        "body:text",
        "body:xml",
        "body:sparql",
        "body:graphql",
        "body:graphql:vars",
        "script:pre-request",
        "script:post-response",
        "tests",
        "docs",
    }
)

#: Blocks this reader relies on as ``key: value`` dictionaries; a line without ``:`` in one of these is
#: a syntax error. Any other block a newer Bruno writes is read as a dictionary when it parses as one
#: and kept as text otherwise, so a new block name never breaks an import.
DICT_BLOCKS = frozenset(
    {
        "meta",
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "options",
        "head",
        "connect",
        "trace",
        "headers",
        "params:query",
        "params:path",
        "auth",
        "vars",
        "vars:pre-request",
        "vars:post-response",
        "body:form-urlencoded",
        "body:multipart-form",
        "assert",
        "settings",
    }
)

_HEADER_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_:.\-]*)[ \t]*([{\[])[ \t]*$")
_MULTILINE_MARK = "'''"


class BruSyntaxError(ValueError):
    """Raised when a ``.bru`` file breaks the block grammar.

    Attributes:
        code: ``INPUT_TRUNCATED`` when the file ends inside a block, else ``INPUT_MALFORMED``.
    """

    def __init__(self, message: str, *, code: str = "INPUT_MALFORMED") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BruEntry:
    """One ``key: value`` line of a dictionary block (or one name of a list block).

    Attributes:
        key: The key (unquoted), or the list item.
        value: The value (``""`` for a list item).
        enabled: ``False`` when the line was written with a leading ``~``.
    """

    key: str
    value: str = ""
    enabled: bool = True


@dataclass
class BruBlock:
    """One block of a ``.bru`` file.

    Attributes:
        name: The block name (``get``, ``body:json``, ``vars:secret``).
        kind: ``dict``, ``text`` or ``list``.
        entries: The lines of a dictionary or list block, in order.
        text: The dedented body of a text block.
        line: The 1-based line the block opens on.
    """

    name: str
    kind: str
    entries: List[BruEntry] = field(default_factory=list)
    text: str = ""
    line: int = 0

    def values(self, *, enabled_only: bool = True) -> Dict[str, str]:
        """The block's entries as a mapping (the last spelling of a repeated key wins)."""
        return {entry.key: entry.value for entry in self.entries if entry.enabled or not enabled_only}


def _where(label: Optional[str], line: int) -> str:
    return f" ({label}, line {line})" if label else f" (line {line})"


def _dedent(lines: List[str]) -> str:
    """Remove the two-space block indentation (and nothing more) from text block lines."""
    return "\n".join(line[2:] if line.startswith("  ") else line.lstrip() for line in lines).strip("\n")


def _split_entry(content: str, *, block: str, label: Optional[str], line: int) -> Tuple[str, str, bool]:
    """Split a dictionary line into ``(key, value, enabled)``."""
    enabled = not content.startswith("~")
    body = content[1:] if not enabled else content
    if body.startswith('"'):
        end = body.find('"', 1)
        while end != -1 and body[end - 1] == "\\":
            end = body.find('"', end + 1)
        if end == -1 or not body[end + 1 :].lstrip().startswith(":"):
            raise BruSyntaxError(f"Unterminated quoted key in `{block}`{_where(label, line)}")
        key = body[1:end].replace('\\"', '"')
        value = body[end + 1 :].lstrip()[1:]
    else:
        if ":" not in body:
            raise BruSyntaxError(f"Expected `key: value` in `{block}`{_where(label, line)}: {content!r}")
        key, value = body.split(":", 1)
    return key.strip(), value.strip(), enabled


def parse_bru(text: str, *, label: Optional[str] = None) -> List[BruBlock]:
    """Tokenise a ``.bru`` file into its blocks.

    Args:
        text: The file's text.
        label: The member path, for messages.

    Returns:
        The blocks in file order.

    Raises:
        BruSyntaxError: ``INPUT_TRUNCATED`` when the text ends inside a block or a ``'''`` value;
            ``INPUT_MALFORMED`` for a line outside any block or a dictionary line with no ``:``.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: List[BruBlock] = []
    index = 0
    while index < len(lines):
        raw = lines[index]
        if not raw.strip():
            index += 1
            continue
        header = _HEADER_RE.match(raw.rstrip())
        if header is None:
            raise BruSyntaxError(f"Expected a block such as `meta {{`{_where(label, index + 1)}: {raw.strip()!r}")
        name, bracket = header.group(1), header.group(2)
        closing = "]" if bracket == "[" else "}"
        kind = "list" if bracket == "[" else ("text" if name in TEXT_BLOCKS else "dict")
        block = BruBlock(name=name, kind=kind, line=index + 1)
        body: List[str] = []
        index += 1
        while True:
            if index >= len(lines):
                raise BruSyntaxError(
                    f"`{name}` is never closed{_where(label, block.line)} — the file is truncated",
                    code="INPUT_TRUNCATED",
                )
            line = lines[index]
            if line.rstrip() == closing:
                index += 1
                break
            body.append(line)
            index += 1
        if kind == "text":
            block.text = _dedent(body)
        elif kind == "dict" and block.name not in DICT_BLOCKS and not block.name.startswith("auth:"):
            try:
                _read_entries(block, body, label=label)
            except BruSyntaxError as exc:
                if exc.code == "INPUT_TRUNCATED":
                    raise
                block.kind, block.entries, block.text = "text", [], _dedent(body)
        else:
            _read_entries(block, body, label=label)
        blocks.append(block)
    return blocks


def _read_entries(block: BruBlock, body: List[str], *, label: Optional[str]) -> None:
    """Fill a dictionary or list block's entries from its body lines."""
    position = 0
    while position < len(body):
        line_no = block.line + 1 + position
        content = body[position].strip()
        position += 1
        if not content:
            continue
        if block.kind == "list":
            item = content.rstrip(",").strip()
            enabled = not item.startswith("~")
            block.entries.append(BruEntry(key=item.lstrip("~").strip(), enabled=enabled))
            continue
        key, value, enabled = _split_entry(content, block=block.name, label=label, line=line_no)
        if value == _MULTILINE_MARK:
            gathered: List[str] = []
            while True:
                if position >= len(body):
                    raise BruSyntaxError(
                        f"The `'''` value of `{key}` in `{block.name}` is never closed{_where(label, line_no)}",
                        code="INPUT_TRUNCATED",
                    )
                current = body[position]
                position += 1
                if current.strip() == _MULTILINE_MARK:
                    break
                gathered.append(current)
            value = _dedent([line[2:] if line.startswith("  ") else line for line in gathered])
        block.entries.append(BruEntry(key=key, value=value, enabled=enabled))


_BLOCK_LINE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_:.\-]*[ \t]*[{\[][ \t]*$", re.MULTILINE)


def looks_like_bru(text: str) -> bool:
    """Cheap pre-check: the text opens a ``.bru`` block and closes one at column 0."""
    return bool(_BLOCK_LINE_RE.search(text)) and bool(re.search(r"^[}\]][ \t]*$", text, re.MULTILINE))
