"""Validate emitted COBOL copybooks with cb2xml — MFX-23.4 (#4142).

Apiome reads copybooks with its own line parser (:mod:`app.cobolcopybook_parser`), so re-parsing an
export with it only proves Apiome agrees with itself. **cb2xml** (``net.sf.cb2xml``, a SableCC COBOL
grammar on the JVM) is an independent reader: the toolchain tool ``cb2xml`` (:data:`CB2XML_TOOL_KEY`,
a ``java -cp cb2xml.jar net.sf.cb2xml.Cb2Xml`` wrapper) turns a copybook into XML, one ``<item>`` per
data item with its ``level``, ``name``, ``picture``, ``usage``, ``occurs`` / ``occurs-min`` /
``depending-on`` and ``redefines``, and one ``<condition>`` per ``88`` level.

:func:`check_with_cb2xml` runs it over an emitted copybook and checks two things:

1. **It parses.** cb2xml reports a syntax error on standard error (``*** fatal parse error ***``) and
   still exits 0, so the error text is what decides; it becomes one ``cb2xml.parse`` problem carrying
   cb2xml's message (and its line and column for a fixed-format file).
2. **It parses to the emit plan.** The layout cb2xml read must match the trees the emitter rendered
   (:func:`app.cobolcopybook_emitter.copybook_emit_plan`): the same records and items in the same
   order, each with the same level, name, picture, usage, ``OCCURS`` bounds, ``DEPENDING ON``,
   ``REDEFINES`` and ``88`` conditions. Each difference is one ``cb2xml.layout`` problem at the item's
   dotted path (``PURCHASE.LINES-X``). Spellings COBOL treats as one are compared as one: ``X(3)`` and
   ``XXX``, ``COMP`` / ``BINARY`` / ``COMP-4``, ``COMP-3`` / ``PACKED-DECIMAL``, a quoted value with or
   without its quotes; a usage cb2xml marks as inherited from a group is not the item's own.

cb2xml's command line reads fixed format only (columns 8-72), so a free-format export is laid out in
fixed format first (:func:`fixed_format_text`): the same entries, wrapped inside the code area with
quoted literals kept whole.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence, Tuple
from xml.etree.ElementTree import Element

from .cobolcopybook_emitter import _fixed_format_entry
from .secure_xml import SecureXmlError, parse_xml
from .toolchain_runner import ToolchainError, ToolExecutionError, ToolNotAvailableError, run_tool_blocking

__all__ = [
    "CB2XML_TOOL_KEY",
    "Cb2xmlError",
    "Cb2xmlProblem",
    "LayoutItem",
    "cb2xml_available",
    "check_with_cb2xml",
    "fixed_format_text",
    "layout_differences",
    "parse_cb2xml_layout",
    "plan_layout",
    "run_cb2xml",
]

CB2XML_TOOL_KEY = "cb2xml"
_TIMEOUT_SECONDS = 120.0
#: What cb2xml prints on standard error when the grammar rejects the copybook (it still exits 0).
_FATAL_MARKER = "*** fatal parse error ***"
#: Where cb2xml's error message ends and its dump of the lexer buffer begins.
_DUMP_MARKER = "=== buffer dump start ==="
#: SableCC's ``[line,column]`` prefix on a parser or lexer error.
_POSITION_RE = re.compile(r"\[(\d+),(\d+)\]")
#: A PICTURE symbol with a repeat count: ``X(3)`` is ``XXX``.
_REPEAT_RE = re.compile(r"(.)\((\d+)\)")
#: One token of a free-format entry: a quoted literal (doubled quotes inside) or a run of non-blanks.
_TOKEN_RE = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|\S+")
#: USAGE spellings COBOL treats as the same storage.
_USAGE_ALIASES = {
    "COMP": "BINARY", "COMPUTATIONAL": "BINARY", "COMP-4": "BINARY", "COMPUTATIONAL-4": "BINARY",
    "COMP-3": "PACKED-DECIMAL", "COMPUTATIONAL-3": "PACKED-DECIMAL",
    "DISPLAY": None,
}


class Cb2xmlError(Exception):
    """cb2xml did not produce a layout.

    Attributes:
        message: cb2xml's error text (or why it could not run).
        line: The 1-based line of a syntax error, when cb2xml gives one.
        column: The 1-based column of a syntax error, when cb2xml gives one.
        unavailable: ``True`` when the tool is not installed — the caller falls back, it does not reject.
    """

    def __init__(self, message: str, *, line: Optional[int] = None, column: Optional[int] = None,
                 unavailable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.column = column
        self.unavailable = unavailable


@dataclass(frozen=True)
class Cb2xmlProblem:
    """One way an emitted copybook fails the cb2xml check.

    Attributes:
        rule: ``cb2xml.parse`` (cb2xml rejected the copybook) or ``cb2xml.layout`` (it read a layout
            other than the emit plan).
        message: What is wrong, in a sentence.
        file: The emitted file's path.
        path: The dotted path of the item concerned (``PURCHASE.LINES-X``), for a layout problem.
        line: The source line of a syntax error, when known.
        column: The source column of a syntax error, when known.
    """

    rule: str
    message: str
    file: str
    path: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None


@dataclass(frozen=True)
class LayoutItem:
    """One data item of a copybook layout, as planned or as cb2xml read it.

    Attributes:
        level: The level number (``1``, ``5`` …).
        name: The data name.
        picture: The PICTURE string as written, or ``None`` for a group or a float.
        usage: The USAGE as written, or ``None`` for display.
        occurs: ``(min, max)`` occurrences of a table, or ``None``; a fixed table's are equal.
        depending_on: The ``DEPENDING ON`` counter of a variable table.
        redefines: The item whose storage this one ``REDEFINES``.
        conditions: The ``88`` levels: ``(name, value)`` with the value as written.
        children: The subordinate items, in order.
    """

    level: int
    name: str
    picture: Optional[str] = None
    usage: Optional[str] = None
    occurs: Optional[Tuple[int, int]] = None
    depending_on: Optional[str] = None
    redefines: Optional[str] = None
    conditions: Tuple[Tuple[str, str], ...] = ()
    children: Tuple["LayoutItem", ...] = ()


# ===========================================================================
# Running cb2xml
# ===========================================================================


def cb2xml_available() -> bool:
    """Whether the ``cb2xml`` tool resolves in this runtime."""
    from .toolchain_packaging import probe_tool, register_bundled_tools

    register_bundled_tools()
    probe = probe_tool(CB2XML_TOOL_KEY)
    return bool(probe and probe.available)


def run_cb2xml(text: str, *, name: str = "copybook.cpy") -> str:
    """Parse a fixed-format copybook with cb2xml.

    Args:
        text: The copybook source (columns 8-72 are read).
        name: The file name cb2xml records in its output.

    Returns:
        cb2xml's XML document.

    Raises:
        Cb2xmlError: cb2xml rejected the copybook (its message, with line and column when given),
            failed or timed out; ``unavailable`` when the tool is not installed.
    """
    work = Path(tempfile.mkdtemp(prefix="apiome-cb2xml-"))
    try:
        source = work / (Path(name).name or "copybook.cpy")
        source.write_text(text, encoding="utf-8")
        output = work / "layout.xml"
        args = ["-cobol", str(source), "-xml", str(output)]
        try:
            result = run_tool_blocking(CB2XML_TOOL_KEY, args, timeout=_TIMEOUT_SECONDS, thread_name="cb2xml",
                                       cwd=str(work), extra_env={"HOME": str(work)})
            stderr = result.stderr
        except ToolNotAvailableError as exc:
            raise Cb2xmlError("cb2xml is not installed on this server.", unavailable=True) from exc
        except ToolExecutionError as exc:
            raise _error_from(exc.stderr or exc.stdout or str(exc)) from exc
        except ToolchainError as exc:
            raise Cb2xmlError(f"cb2xml failed: {exc}") from exc
        if _FATAL_MARKER in stderr or "Exception" in stderr:
            raise _error_from(stderr)
        xml = output.read_text(encoding="utf-8") if output.is_file() else ""
        if not xml.strip():
            raise _error_from(stderr or "cb2xml wrote no layout.")
        return xml
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _error_from(stderr: str) -> Cb2xmlError:
    """The :class:`Cb2xmlError` for cb2xml's standard error: its message, without the buffer dump."""
    text = stderr.split(_DUMP_MARKER, 1)[0].replace(_FATAL_MARKER, "")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    message = " ".join(lines[:3]) or "cb2xml rejected the copybook."
    position = _POSITION_RE.search(message)
    if position is None:
        return Cb2xmlError(message)
    return Cb2xmlError(message, line=int(position.group(1)), column=int(position.group(2)))


def fixed_format_text(text: str) -> str:
    """Lay a free-format copybook out in fixed format, for cb2xml's fixed-format reader.

    Each entry (one line ending in a period, as the emitter writes free format) is wrapped inside
    columns 8-72 the way the emitter wraps a fixed-format entry; a quoted literal is never split. A
    ``*>`` comment becomes a ``*`` comment in column 7.

    Args:
        text: The free-format copybook.

    Returns:
        The same entries in fixed format.
    """
    lines: List[str] = []
    for line in text.splitlines():
        entry = line.strip()
        if not entry:
            lines.append("")
        elif entry.startswith("*>"):
            lines.append(f"      * {entry[2:].strip()}"[:72].rstrip())
        else:
            tokens = _TOKEN_RE.findall(entry[:-1] if entry.endswith(".") else entry)
            head = "  ".join(tokens[:2])
            lines.extend(_fixed_format_entry(" " * 7, head, tokens[2:]))
    return "\n".join(lines) + "\n"


# ===========================================================================
# Layouts
# ===========================================================================


def parse_cb2xml_layout(xml: str) -> List[LayoutItem]:
    """The records cb2xml read, from its XML (``<copybook>`` of ``<item>`` / ``<condition>``).

    Args:
        xml: cb2xml's output.

    Returns:
        One :class:`LayoutItem` per top-level item (each ``01`` record), in order.

    Raises:
        Cb2xmlError: The output is not cb2xml XML.
    """
    try:
        root = parse_xml(xml)
    except SecureXmlError as exc:
        raise Cb2xmlError(f"cb2xml wrote unreadable XML: {exc}") from exc
    if root.tag != "copybook":
        raise Cb2xmlError(f"cb2xml wrote <{root.tag}>, not a <copybook>.")
    return [_cb2xml_item(item) for item in root if item.tag == "item"]


def _cb2xml_item(element: Element) -> LayoutItem:
    """One cb2xml ``<item>`` and its subordinate items and conditions."""
    attrs = element.attrib
    occurs: Optional[Tuple[int, int]] = None
    if attrs.get("occurs"):
        high = int(attrs["occurs"])
        occurs = (int(attrs["occurs-min"]) if attrs.get("occurs-min") else high, high)
    inherited = attrs.get("inherited-usage") == "true"
    return LayoutItem(
        level=int(attrs.get("level", "0")),
        name=attrs.get("name", ""),
        picture=attrs.get("picture") or None,
        usage=None if inherited else attrs.get("usage") or None,
        occurs=occurs,
        depending_on=attrs.get("depending-on") or None,
        redefines=attrs.get("redefines") or None,
        conditions=tuple((c.get("name", ""), c.get("value", "")) for c in element if c.tag == "condition"),
        children=tuple(_cb2xml_item(child) for child in element if child.tag == "item"),
    )


def plan_layout(trees: Sequence[Mapping[str, Any]]) -> List[LayoutItem]:
    """The emit plan's records as :class:`LayoutItem` trees — what the emitter writes for each node.

    Args:
        trees: :func:`app.cobolcopybook_emitter.copybook_emit_plan` output.

    Returns:
        One :class:`LayoutItem` per ``01`` record.
    """
    return [_plan_item(tree) for tree in trees]


def _plan_item(node: Mapping[str, Any]) -> LayoutItem:
    """One planned node, read the way the emitter renders it."""
    occurs: Optional[Tuple[int, int]] = None
    if node.get("occurs_max") is not None:
        high = int(node["occurs_max"])
        # The emitter writes `OCCURS low TO high … DEPENDING ON` (low defaulting to 1), else `OCCURS high TIMES`.
        low = node.get("occurs_min")
        occurs = (int(low if low is not None else 1), high) if node.get("depending_on") else (high, high)
    conditions = tuple(
        (str(c.get("name", "")), str(c.get("value", "")))
        for c in node.get("conditions") or [] if isinstance(c, Mapping)
    )
    return LayoutItem(
        level=int(node.get("level", 1)),
        name=str(node.get("name", "")),
        picture=node.get("picture") or None,
        usage=node.get("usage") or None,
        occurs=occurs,
        depending_on=node.get("depending_on") or None,
        redefines=node.get("redefines") or None,
        conditions=conditions,
        children=tuple(_plan_item(child) for child in node.get("children") or [] if isinstance(child, Mapping)),
    )


def layout_differences(
    expected: Sequence[LayoutItem], actual: Sequence[LayoutItem], *, parent: str = ""
) -> List[Tuple[str, str]]:
    """Where the layout cb2xml read differs from the emit plan.

    Items are matched by position. An item whose name differs is one difference and its subordinate
    items are not compared (everything below it would differ too).

    Args:
        expected: The planned items (:func:`plan_layout`).
        actual: The items cb2xml read (:func:`parse_cb2xml_layout`).
        parent: The dotted path of the items' parent (empty for records).

    Returns:
        ``(dotted path, message)`` per difference; empty when the layouts match.
    """
    differences: List[Tuple[str, str]] = []
    for planned, read in zip(expected, actual):
        path = f"{parent}.{planned.name}" if parent else planned.name
        if planned.name.upper() != read.name.upper():
            differences.append((path, f"The emit plan has {planned.name} here; cb2xml read {read.name}."))
            continue
        for what, plan_value, read_value in _item_differences(planned, read):
            differences.append((path, f"{what}: the emit plan has {plan_value}; cb2xml read {read_value}."))
        differences.extend(layout_differences(planned.children, read.children, parent=path))
    for planned in expected[len(actual):]:
        differences.append((f"{parent}.{planned.name}" if parent else planned.name,
                            f"cb2xml did not read {planned.name}, which the emit plan has."))
    for read in actual[len(expected):]:
        differences.append((f"{parent}.{read.name}" if parent else read.name,
                            f"cb2xml read {read.name}, which the emit plan does not have."))
    return differences


def _item_differences(planned: LayoutItem, read: LayoutItem) -> List[Tuple[str, str, str]]:
    """``(what, planned, read)`` for each attribute of one item that differs."""
    out: List[Tuple[str, str, str]] = []
    if planned.level != read.level:
        out.append(("Level", f"{planned.level:02d}", f"{read.level:02d}"))
    if _picture_key(planned.picture) != _picture_key(read.picture):
        out.append(("PICTURE", _shown(planned.picture), _shown(read.picture)))
    if _usage_key(planned.usage) != _usage_key(read.usage):
        out.append(("USAGE", _shown(planned.usage, "DISPLAY"), _shown(read.usage, "DISPLAY")))
    if planned.occurs != read.occurs or _name_key(planned.depending_on) != _name_key(read.depending_on):
        out.append(("OCCURS", _occurs_shown(planned), _occurs_shown(read)))
    if _name_key(planned.redefines) != _name_key(read.redefines):
        out.append(("REDEFINES", _shown(planned.redefines), _shown(read.redefines)))
    planned_88 = [(name.upper(), _literal_key(value)) for name, value in planned.conditions]
    read_88 = [(name.upper(), _literal_key(value)) for name, value in read.conditions]
    if planned_88 != read_88:
        out.append(("88 levels", _conditions_shown(planned.conditions), _conditions_shown(read.conditions)))
    return out


def _picture_key(picture: Optional[str]) -> Optional[str]:
    """A PICTURE with repeat counts expanded and case folded: ``s9(3)v9(2)`` → ``S999V99``."""
    if not picture:
        return None
    return _REPEAT_RE.sub(lambda m: m.group(1) * int(m.group(2)), picture.upper().replace(" ", ""))


def _usage_key(usage: Optional[str]) -> Optional[str]:
    """A USAGE as the storage it means: ``COMP`` and ``BINARY`` alike, ``COMP-3`` and ``PACKED-DECIMAL``."""
    if not usage:
        return None
    key = usage.upper().strip()
    if key in _USAGE_ALIASES:
        return _USAGE_ALIASES[key]
    return key.replace("COMPUTATIONAL", "COMP")


def _name_key(name: Optional[str]) -> Optional[str]:
    return name.upper() if name else None


def _literal_key(value: str) -> str:
    """An ``88`` value without its quotes (a doubled quote inside undoubled), as the plan holds it."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1].replace(value[0] * 2, value[0])
    return value


def _shown(value: Optional[str], none: str = "none") -> str:
    return value if value else none


def _occurs_shown(item: LayoutItem) -> str:
    if item.occurs is None:
        return "no OCCURS"
    low, high = item.occurs
    if item.depending_on:
        return f"OCCURS {low} TO {high} DEPENDING ON {item.depending_on}"
    return f"OCCURS {high}" if low == high else f"OCCURS {low} TO {high}"


def _conditions_shown(conditions: Sequence[Tuple[str, str]]) -> str:
    return ", ".join(f"{name} {value}" for name, value in conditions) or "none"


# ===========================================================================
# The check
# ===========================================================================


def check_with_cb2xml(
    path: str, text: str, plan: Sequence[Mapping[str, Any]], *, fixed_format: bool = True
) -> List[Cb2xmlProblem]:
    """Check one emitted copybook with cb2xml: it parses, to the emit plan.

    Args:
        path: The emitted file's path.
        text: Its content.
        plan: The trees the emitter rendered (:func:`app.cobolcopybook_emitter.copybook_emit_plan`).
        fixed_format: Whether the copybook was written in fixed format; a free-format one is laid out
            in fixed format for cb2xml (:func:`fixed_format_text`), and its errors carry no line.

    Returns:
        One problem per failure: ``cb2xml.parse`` with cb2xml's error, or one ``cb2xml.layout`` per
        difference from the plan. Empty when the copybook passes.

    Raises:
        Cb2xmlError: Only with ``unavailable`` set — the tool is not installed.
    """
    source = text if fixed_format else fixed_format_text(text)
    try:
        actual = parse_cb2xml_layout(run_cb2xml(source, name=path))
    except Cb2xmlError as exc:
        if exc.unavailable:
            raise
        return [Cb2xmlProblem(
            rule="cb2xml.parse",
            message=f"cb2xml cannot parse the copybook: {exc.message}",
            file=path,
            line=exc.line if fixed_format else None,
            column=exc.column if fixed_format else None,
        )]
    return [
        Cb2xmlProblem(rule="cb2xml.layout", message=message, file=path, path=item_path)
        for item_path, message in layout_differences(plan_layout(plan), actual)
    ]

