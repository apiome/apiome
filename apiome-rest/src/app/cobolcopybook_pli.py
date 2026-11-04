"""PL/I include structure output mode of the COBOL copybook export — MFX-23.3 (#4141).

PL/I shops read record layouts as ``DECLARE`` structures, not copybooks. With ``mode="pli"`` the copybook
emitter (:mod:`app.cobolcopybook_emitter`) writes the **same record layout** — the trees
:func:`app.cobolcopybook_plan.plan_copybook` plans, or a copybook item's own imported layout — as a PL/I
include member (``<NAME>.pli``), item for item and byte for byte:

=====================================  ==================================================================
Copybook                               PL/I
=====================================  ==================================================================
``01`` / ``05`` / ``10`` …              levels ``1`` / ``2`` / ``3`` … by depth
``CUST-ID``, ``FILLER``                ``CUST_ID``, ``*``
``PIC X(n)``                           ``CHAR(n)`` (``PIC A(n)`` too; ``PIC N(n)`` → ``WIDECHAR(n)``)
``PIC S9(p)V9(s) COMP-3``              ``FIXED DEC(p+s,s)``
``PIC S9(4|9|18) COMP`` / ``BINARY``   ``FIXED BIN(15|31|63)``
``PIC S9(p)V9(s)`` (zoned)             ``PIC'(p)9V(s-1)9T'`` — ``T`` is the overpunched sign
``COMP-1`` / ``COMP-2``                ``FLOAT DEC(6)`` / ``FLOAT DEC(16)``
``OCCURS n TIMES``                     the dimension ``(n)``
``OCCURS a TO b DEPENDING ON C``       ``(b REFER(C))`` — the structure is ``BASED``, as REFER needs
``B REDEFINES A``                      ``A`` and ``B`` as members of a ``UNION``
``88`` condition names                 a comment above the item: PL/I has no condition names
=====================================  ==================================================================

Every structure is ``UNALIGNED`` (inherited by its members), so binary and float items are not moved to a
halfword / word boundary: the offsets are the copybook's. :func:`layout_problems` checks that each item
takes the bytes the copybook item does.

In fixed format (the default, ``fixed_format=True``) the source stays within PL/I's default margins,
columns 2-72; free format has no column limit.

**Losses.** What the copybook plan synthesized or approximated (MFX-23.2) is reported with the same subject
and verdict, restated in PL/I terms (:func:`restate_losses`: ``CHAR(255)``, ``REFER``, ``UNION`` …). What only
PL/I changes is recorded too — ``conditions-as-comment``, ``names-respelled``, ``overlay-union-synthesized``,
``renames-dropped``, ``redefines-unresolved``, ``picture-as-char`` and
``binary-scale-as-comment``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from .cobolcopybook_layout import picture_size
from .emitter import Loss, LossKind, LossTracker

__all__ = [
    "PLI_EXTENSION",
    "PliNamer",
    "PliRenderOptions",
    "layout_problems",
    "pli_name",
    "render_pli",
    "restate_losses",
]

#: The file extension of a PL/I include member.
PLI_EXTENSION = ".pli"
#: PL/I's default source margins on z/OS: column 1 is ignored and nothing past column 72 is read.
_LEFT_MARGIN = " "
_RIGHT_MARGIN = 72
#: Nesting deeper than this is not indented further, so a long name still fits the margins.
_MAX_INDENT_LEVELS = 8
#: COBOL binary digits → PL/I FIXED BINARY precision of the same width (2, 4, 8 bytes).
_BINARY_PRECISION = ((4, 15), (9, 31), (18, 63))
_FLOAT_USAGES = {"COMP-1": "FLOAT DEC(6)", "COMPUTATIONAL-1": "FLOAT DEC(6)",
                 "COMP-2": "FLOAT DEC(16)", "COMPUTATIONAL-2": "FLOAT DEC(16)"}
_PACKED_USAGES = frozenset({"COMP-3", "COMPUTATIONAL-3", "PACKED-DECIMAL"})
_BINARY_USAGES = frozenset({"COMP", "COMPUTATIONAL", "COMP-4", "COMPUTATIONAL-4", "COMP-5", "COMPUTATIONAL-5",
                            "BINARY"})
#: A picture repetition: a symbol (a letter, a digit or an editing character), optionally followed by ``(n)``.
_PICTURE_TOKEN = re.compile(r"([A-Z0-9/,.+*$-])(?:\((\d+)\))?")


@dataclass(frozen=True)
class PliRenderOptions:
    """How the PL/I text is laid out.

    Attributes:
        fixed_format: Keep every line within columns 2-72 (PL/I's default margins).
        include_comments: Write the generated-file banner.
    """

    fixed_format: bool = True
    include_comments: bool = True


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


def pli_name(cobol: str) -> str:
    """A COBOL data name as a PL/I identifier: hyphens become underscores, ``FILLER`` the unnamed ``*``.

    Args:
        cobol: ``CUST-ID``, ``2FA-CODE``, ``FILLER``.

    Returns:
        ``CUST_ID``, ``X_2FA_CODE`` (a PL/I name starts with a letter), ``*``.
    """
    name = (cobol or "").strip().upper()
    if name == "FILLER" or not name:
        return "*"
    name = re.sub(r"[^A-Z0-9_#@$]", "_", name)
    return name if name[0].isalpha() or name[0] in "#@$" else f"X_{name}"


class PliNamer:
    """The PL/I name of each COBOL data name, unique across the member (``_2``, ``_3`` … on a clash)."""

    def __init__(self) -> None:
        self._by_cobol: Dict[str, str] = {}
        self._used: Set[str] = set()

    def name(self, cobol: str) -> str:
        """The PL/I name ``cobol`` is written under (the same name every time it is asked)."""
        if pli_name(cobol) == "*":
            return "*"
        key = cobol.strip().upper()
        if key in self._by_cobol:
            return self._by_cobol[key]
        base = candidate = pli_name(cobol)
        suffix = 2
        while candidate in self._used:
            candidate, suffix = f"{base}_{suffix}", suffix + 1
        self._used.add(candidate)
        self._by_cobol[key] = candidate
        return candidate

    def fresh(self, base: str) -> str:
        """A new name for an item the copybook does not have (``PAYMENT_DETAIL_UNION``)."""
        candidate, suffix = base, 2
        while candidate in self._used:
            candidate, suffix = f"{base}_{suffix}", suffix + 1
        self._used.add(candidate)
        return candidate

    def mapping(self) -> Dict[str, str]:
        """COBOL name → PL/I name, for every name written."""
        return dict(self._by_cobol)


# ---------------------------------------------------------------------------
# Attributes
# ---------------------------------------------------------------------------


def _symbols(picture: str) -> Optional[List[str]]:
    """A COBOL picture expanded to one symbol per position (``S9(3)V99`` → ``S 9 9 9 V 9 9``)."""
    text = picture.strip().upper().rstrip(".")
    symbols: List[str] = []
    index = 0
    while index < len(text):
        match = _PICTURE_TOKEN.match(text, index)
        if not match:
            return None
        symbols.extend([match.group(1)] * int(match.group(2) or 1))
        index = match.end()
    return symbols


def _zoned_picture(digits: int, decimals: int, signed: bool) -> str:
    """A zoned decimal as a PL/I numeric picture; a sign is overpunched on the last digit (``T``)."""
    whole = digits - decimals
    positions = ["9"] * whole + ["V"] + ["9"] * decimals if decimals else ["9"] * whole
    if signed:
        positions[-1] = "T"
    text, index = "", 0
    while index < len(positions):
        run = 1
        while index + run < len(positions) and positions[index + run] == positions[index]:
            run += 1
        text += f"({run}){positions[index]}" if run > 2 else positions[index] * run
        index += run
    return text


def _attributes(node: Mapping[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """The PL/I data attributes of an elementary copybook item.

    Args:
        node: The plan or layout node (``picture`` and ``usage``).

    Returns:
        ``(attributes, loss subject, loss detail)``. The subject is set when the item had to be written
        less exactly than the copybook says (an edited picture as ``CHAR``, a scaled binary number);
        ``attributes`` is ``None`` for an item with no storage to declare.
    """
    picture = str(node.get("picture") or "").strip()
    usage = str(node.get("usage") or "").strip().upper().replace("_", "-")
    if usage in _FLOAT_USAGES:
        return _FLOAT_USAGES[usage], None, None
    if usage == "POINTER":
        return "POINTER", None, None
    if usage == "INDEX":
        return "FIXED BIN(31)", None, None
    size = picture_size(picture or None, usage or None)
    symbols = _symbols(picture) if picture else None
    if symbols is None:
        length = size.length or 1
        return f"CHAR({length})", "picture-as-char", (
            f"PIC {picture or '(none)'} has no PL/I equivalent this export writes; it is declared CHAR({length})."
        )
    kinds = set(symbols)
    if kinds <= {"X"}:
        return f"CHAR({len(symbols)})", None, None
    if kinds <= {"A"}:
        return f"CHAR({len(symbols)})", None, None
    if kinds <= {"N"} and usage in {"", "NATIONAL"}:
        return f"WIDECHAR({len(symbols)})", None, None
    if kinds <= {"S", "9", "V"} and symbols.count("S") <= 1 and symbols.count("V") <= 1:
        digits = symbols.count("9")
        decimals = len(symbols) - symbols.index("V") - 1 if "V" in symbols else 0
        signed = "S" in symbols
        if usage in _PACKED_USAGES:
            return f"FIXED DEC({digits},{decimals})" if decimals else f"FIXED DEC({digits})", None, None
        if usage in _BINARY_USAGES:
            precision = next((p for ceiling, p in _BINARY_PRECISION if digits <= ceiling), None)
            if precision is None:
                return f"CHAR({size.length or digits})", "picture-as-char", (
                    f"PIC {picture} {usage} has more digits than a binary item holds; it is declared "
                    f"CHAR({size.length or digits})."
                )
            if decimals:
                return f"FIXED BIN({precision})", "binary-scale-as-comment", (
                    f"PIC {picture} {usage} is a binary integer with {decimals} implied decimal place(s); PL/I "
                    f"FIXED BIN scales by binary digits, so it is declared FIXED BIN({precision}) and its "
                    "decimal places are noted in a comment."
                )
            return f"FIXED BIN({precision})", None, None
        if usage in {"", "DISPLAY"}:
            return f"PIC'{_zoned_picture(digits, decimals, signed)}'", None, None
    length = size.length or len(symbols)
    return f"CHAR({length})", "picture-as-char", (
        f"PIC {picture}{' ' + usage if usage else ''} is an edited or mixed picture; it is declared "
        f"CHAR({length}), the bytes it takes, and its picture is noted in a comment."
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class _Writer:
    """Writes the PL/I text of one set of trees (single use)."""

    def __init__(self, trees: List[Dict[str, Any]], options: PliRenderOptions, losses: LossTracker,
                 title: str) -> None:
        self._trees = trees
        self._options = options
        self._losses = losses
        self._title = title
        self.namer = PliNamer()
        self._noted: Set[Tuple[str, str]] = set()
        #: The record (``01``) name whose items are being written, for an imported layout's keys.
        self._record = ""

    def render(self) -> str:
        lines: List[str] = []
        if self._options.include_comments:
            lines.extend(self._comment(f"Generated PL/I include structure for {self._title}", 0))
        for index, tree in enumerate(self._trees):
            if index:
                lines.append("")
            self._record = str(tree.get("name") or "")
            lines.extend(self._structure(tree))
        return "\n".join(lines).rstrip() + "\n"

    # --- structure ------------------------------------------------------------

    def _structure(self, tree: Dict[str, Any]) -> List[str]:
        """One ``DCL 1 … ;`` statement for a ``01`` record."""
        entries: List[Tuple[int, List[str], str]] = []  # (depth, comment lines, declaration)
        self._collect(tree, depth=0, parent=None, entries=entries)
        lines: List[str] = []
        for index, (depth, comments, declaration) in enumerate(entries):
            last = index == len(entries) - 1
            lines.extend(comments)
            prefix = "DCL " if index == 0 else ""
            lines.extend(self._declaration(prefix + declaration + (";" if last else ","), depth))
        return lines

    def _collect(self, node: Dict[str, Any], *, depth: int, parent: Optional[Dict[str, Any]],
                 entries: List[Tuple[int, List[str], str]], union: bool = False) -> None:
        """Add ``node`` and its members to ``entries`` (depth-first, in storage order).

        Args:
            node: A plan or layout node, or a ``UNION`` group this writer added (``_synthetic``).
            depth: 0 for the major structure.
            parent: The node it is a member of.
            entries: ``(depth, comment lines, declaration)`` per item, appended to.
            union: Declare the item ``UNION`` (its members share storage).
        """
        key = self._key(node, parent)
        if _is_renames(node):
            self._loss(LossKind.NA, "renames-dropped", key, f"The 66-level RENAMES item {node.get('name')!r} has no "
                       "PL/I declaration; it is left out (it takes no storage of its own).")
            return
        name = str(node["name"]) if node.get("_synthetic") else self.namer.name(str(node.get("name") or "FILLER"))
        children = _members(node)
        for renames in [c for c in node.get("children") or [] if isinstance(c, dict) and _is_renames(c)]:
            self._collect(renames, depth=depth + 1, parent=node, entries=entries)  # recorded, not written
        self_union, members = self._overlays(node, children, key)
        comments = [str(c) for c in node.get("comments") or []]
        conditions = [c for c in node.get("conditions") or [] if isinstance(c, dict)]
        if conditions:
            from .cobolcopybook_emitter import _condition_value  # one rule for how a value is written

            values = ", ".join(f"{pli_name(str(c.get('name', 'VALUE')))} = {_condition_value(c)}" for c in conditions)
            comments.append(f"values: {values}")
            self._loss(LossKind.INFERRED, "conditions-as-comment", key, f"The values of {name} ({values}) are "
                       "COBOL 88-level condition names in the copybook; PL/I has none, so they are a comment above "
                       "the item.")
        attributes: List[str] = []
        if depth == 0:
            attributes.append("UNALIGNED")
            if _has_refer(node):
                attributes.append("BASED")
        if union or self_union:
            attributes.append("UNION")
        if not children:
            data, subject, detail = _attributes(node)
            if data is not None:
                attributes.append(data)
            if subject is not None:
                comments.append(f"copybook: PIC {node.get('picture') or ''} {node.get('usage') or ''}".rstrip())
                self._loss(LossKind.INFERRED, subject, key, f"{name}: {detail}")
        entries.append((depth, [line for text in comments for line in self._comment(text, depth)],
                        " ".join([f"{depth + 1} {name}{self._dimension(node)}", *attributes])))
        for member, member_is_union in members:
            self._collect(member, depth=depth + 1, parent=node, entries=entries, union=member_is_union)

    def _overlays(self, node: Dict[str, Any], children: List[Dict[str, Any]],
                  key: str) -> Tuple[bool, List[Tuple[Dict[str, Any], bool]]]:
        """``node``'s members in storage order, each ``REDEFINES`` run (``A``, ``B REDEFINES A`` …) as a ``UNION``.

        Args:
            node: The group.
            children: Its members.
            key: Where a synthesized ``UNION`` group is recorded.

        Returns:
            ``(node is the UNION, [(member, member is a UNION)])``. When a run is every member of ``node`` (a
            union the plan laid out), ``node`` itself is the ``UNION``; otherwise the run is wrapped in a
            ``UNION`` group of its own, which is recorded as synthesized.
        """
        overlaid: Dict[str, List[Dict[str, Any]]] = {}
        siblings = {str(c.get("name") or "").upper() for c in children if not c.get("redefines")}
        for child in children:
            target = str(child.get("redefines") or "").upper()
            if target and target in siblings:
                overlaid.setdefault(target, []).append(child)
            elif target:
                child["redefines"] = None  # nothing to overlay: written as an item of its own
                self._loss(LossKind.INFERRED, "redefines-unresolved", self._key(child, node),
                           f"{pli_name(str(child.get('name')))} REDEFINES {target}, which is not an item before it in "
                           "the same group; PL/I has nothing to overlay it with, so it is written as an item of its "
                           "own.")
        if not overlaid:
            return False, [(c, False) for c in children]
        members: List[Tuple[Dict[str, Any], bool]] = []
        for child in children:
            if child.get("redefines"):
                continue  # written inside the UNION of the item it redefines
            name = str(child.get("name") or "").upper()
            run = [child, *overlaid.get(name, [])]
            if len(run) == 1:
                members.append((child, False))
                continue
            if len(run) == len(children):
                return True, [(m, False) for m in run]
            union_name = self.namer.fresh(f"{pli_name(name)}_UNION")
            self._loss(LossKind.INFERRED, "overlay-union-synthesized", key,
                       f"{', '.join(pli_name(str(m.get('name'))) for m in run)} share storage (REDEFINES) beside other "
                       f"items; PL/I overlays only the members of a UNION, so they are written inside the UNION "
                       f"{union_name}, a level the copybook does not have.")
            members.append(({"level": 0, "name": union_name, "children": run, "_synthetic": True,
                             "_cobol_parent": node}, True))
        return False, members

    def _dimension(self, node: Mapping[str, Any]) -> str:
        """``(n)`` for a fixed table, ``(n REFER(COUNTER))`` for one that varies, else nothing."""
        high = node.get("occurs_max")
        if high is None:
            return ""
        counter = node.get("depending_on")
        if isinstance(counter, str) and counter:
            return f"({int(high)} REFER({self.namer.name(counter)}))"
        return f"({int(high)})"

    def _key(self, node: Mapping[str, Any], parent: Optional[Mapping[str, Any]]) -> str:
        """The canonical construct a loss about ``node`` is filed on.

        A planned item carries its key; an imported copybook's item is ``<record>.<group>.<name>``, the key
        the copybook normalizer gives it (an unknown key files the loss on the report's root).
        """
        if node.get("key"):
            return str(node["key"])
        parent = (parent or {}).get("_cobol_parent") or parent
        group = str((parent or {}).get("name") or self._record)
        return f"{self._record}.{group}.{node.get('name')}" if self._record else ""

    # --- text -----------------------------------------------------------------

    def _indent(self, depth: int) -> str:
        return _LEFT_MARGIN + "  " * min(depth, _MAX_INDENT_LEVELS)

    def _declaration(self, text: str, depth: int) -> List[str]:
        """One declaration, wrapped between its words to stay within the margins (fixed format)."""
        indent = self._indent(depth)
        if not self._options.fixed_format:
            return [indent + text]
        lines: List[str] = []
        current = indent
        for word in text.split(" "):
            candidate = f"{current}{word}" if current.strip() == "" else f"{current} {word}"
            if len(candidate) <= _RIGHT_MARGIN or current.strip() == "":
                current = candidate
                continue
            lines.append(current)
            current = f"{indent}    {word}"
        lines.append(current)
        return lines

    @staticmethod
    def _comment_text(text: str) -> str:
        """Text that cannot end a PL/I comment early (``*/`` is written ``* /``)."""
        return " ".join(text.split()).replace("*/", "* /")

    def _comment(self, text: str, depth: int) -> List[str]:
        """``/* text */``, split into several comments to stay within the margins (fixed format)."""
        indent = self._indent(depth)
        text = self._comment_text(text)
        if not self._options.fixed_format:
            return [f"{indent}/* {text} */"]
        width = max(_RIGHT_MARGIN - len(indent) - len("/*  */"), 20)
        return [f"{indent}/* {text[i:i + width]} */" for i in range(0, len(text), width)] or [f"{indent}/* */"]

    def _loss(self, kind: LossKind, subject: str, pointer: str, detail: str) -> None:
        if (subject, detail) in self._noted:
            return
        self._noted.add((subject, detail))
        self._losses.record(kind, subject, detail, pointer=pointer or None)


def _is_renames(node: Mapping[str, Any]) -> bool:
    """Whether ``node`` is a 66-level ``RENAMES`` item (another view of storage, not storage of its own)."""
    return int(node.get("level") or 0) == 66


def _members(node: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The items of a group, without its 66-level ``RENAMES`` views (an item with only those is elementary)."""
    return [c for c in node.get("children") or [] if isinstance(c, dict) and not _is_renames(c)]


def _has_refer(node: Mapping[str, Any]) -> bool:
    """Whether the structure holds a table whose size is a runtime value (``DEPENDING ON``)."""
    return bool(node.get("depending_on")) or any(
        _has_refer(child) for child in node.get("children") or [] if isinstance(child, Mapping)
    )


def render_pli(trees: List[Dict[str, Any]], *, title: str, options: PliRenderOptions,
               losses: LossTracker) -> Tuple[str, Dict[str, str]]:
    """Write copybook trees as a PL/I include member.

    Args:
        trees: One tree per ``01`` record (the emit plan, or a copybook item's own layout).
        title: The item's name, for the banner.
        options: Margins and banner.
        losses: Where what only PL/I changes is recorded.

    Returns:
        ``(text, names)``: the PL/I source, and the PL/I name of each COBOL data name it wrote.
    """
    writer = _Writer([_copy(tree) for tree in trees], options, losses, title)
    text = writer.render()
    return text, writer.namer.mapping()


def _copy(node: Mapping[str, Any]) -> Dict[str, Any]:
    """A deep copy of a tree, so the render's bookkeeping never touches the plan."""
    copied = dict(node)
    copied["children"] = [_copy(c) for c in node.get("children") or [] if isinstance(c, Mapping)]
    return copied


# ---------------------------------------------------------------------------
# Losses
# ---------------------------------------------------------------------------

#: How each copybook loss reads in PL/I terms: ``(subject, pattern, replacement)``, applied in order.
#: The subjects and verdicts stay the copybook's (MFX-23.2); only the wording changes.
_RESTATEMENTS: Tuple[Tuple[str, str, str], ...] = (
    ("length-synthesized", r"it is written PIC X\((\d+)\) \(the default length\)",
     r"it is written CHAR(\1) (the default length)"),
    ("counter-synthesized",
     r"it is written OCCURS \d+ TO (\d+) DEPENDING ON (\S+), a counter written just before it",
     r"it is written with the dimension (\1 REFER(\2)), sized by \2, a counter written just before it"),
    ("occurs-fixed", r"inside another table, where DEPENDING ON is not allowed; it is a fixed table of (\d+)",
     r"inside another table, so it is a fixed array of \1: only the outer table's size varies"),
    ("union-as-redefines", r"is written as items that share storage \(REDEFINES \S+\)",
     "is written as a UNION of its members, which share storage"),
    ("union-dropped",
     r"a member holds a table that varies in size \(OCCURS DEPENDING ON\), and COBOL cannot overlay it with "
     r"REDEFINES",
     "a member holds a table that varies in size (REFER), which the record layout does not overlay"),
    ("pattern-as-comment", "a COBOL picture cannot check it", "a PL/I declaration cannot check it"),
    ("format-as-comment", "the picture only sizes the value", "the declaration only sizes the value"),
    ("float-as-decimal", "it is written as a zoned decimal", "it is written as a zoned decimal picture"),
    ("unmapped-scalar", "has no COBOL type", "has no PL/I type"),
    ("map-dropped", "A copybook has no map", "A PL/I structure has no map"),
    ("recursion-cut", "a copybook writes nested records inline", "a PL/I structure writes nested records inline"),
)
_MANGLED = re.compile(r"^The (?P<what>\w+) (?P<source>'.*'|\".*\") is written as '(?P<cobol>[^']+)' to follow the "
                      r"COBOL naming rules\.$")


def _rename_in(text: str, names: Mapping[str, str]) -> str:
    """Every COBOL data name in ``text`` replaced by its PL/I name (whole names only, longest first)."""
    for cobol in sorted(names, key=len, reverse=True):
        if names[cobol] != cobol and names[cobol] != "*":
            text = re.sub(rf"(?<![A-Z0-9-]){re.escape(cobol)}(?![A-Z0-9-])", names[cobol], text)
    return text


def restate_losses(losses: List[Loss], names: Mapping[str, str]) -> List[Loss]:
    """The copybook plan's losses as a PL/I export reports them.

    Each keeps its subject, kind and pointer, so the fidelity report grades it as the copybook mode does
    (MFX-23.2); its message names the PL/I declaration instead of the COBOL clause, and every COBOL data name
    in it is the PL/I name. A ``name-mangled`` respelling is dropped when the PL/I name is the source name
    upper-cased — PL/I keeps an underscore that COBOL had to turn into a hyphen.

    Args:
        losses: The losses the copybook plan recorded.
        names: COBOL data name → PL/I name (:func:`render_pli`).

    Returns:
        The restated losses, in the same order.
    """
    restated: List[Loss] = []
    for loss in losses:
        detail = loss.detail
        if loss.subject == "name-mangled":
            match = _MANGLED.match(detail)
            if match:
                source = match.group("source")[1:-1]
                pli = names.get(match.group("cobol"), pli_name(match.group("cobol")))
                if pli == source.upper():
                    continue
                detail = (f"The {match.group('what')} {match.group('source')} is written as {pli!r} to follow the "
                          "PL/I naming rules.")
                restated.append(loss.model_copy(update={"detail": detail}))
                continue
        for subject, pattern, replacement in _RESTATEMENTS:
            if loss.subject == subject:
                detail = re.sub(pattern, replacement, detail)
        restated.append(loss.model_copy(update={"detail": _rename_in(detail, names)}))
    return restated


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def _cobol_items(node: Mapping[str, Any], path: str, out: List[Tuple[str, Optional[int]]]) -> None:
    """Every elementary copybook item, in storage order, with the bytes one occurrence takes."""
    if _is_renames(node):
        return
    name = f"{path}.{node.get('name')}" if path else str(node.get("name"))
    children = _members(node)
    if not children:
        if node.get("picture") or node.get("usage"):
            out.append((name, picture_size(node.get("picture"), node.get("usage")).length))
        return
    for child in children:
        _cobol_items(child, name, out)


def layout_problems(text: str, trees: List[Dict[str, Any]]) -> List[str]:
    """Where the PL/I member does not describe the copybook layout it was written from.

    The text must parse with Apiome's PL/I reader (:func:`app.pli_parser.parse_pli_text`), declare one
    structure per record, use no attribute the reader does not know, and give every elementary item the bytes
    the copybook item takes (one occurrence, in storage order).

    Args:
        text: The PL/I source.
        trees: The copybook trees it was written from.

    Returns:
        One message per problem; empty when the member matches the layout.

    Raises:
        app.mainframe_misc_common.MainframeParseError: When the text does not parse.
    """
    from .pli_layout import compute_layout
    from .pli_parser import parse_pli_text

    document = parse_pli_text(text, label="export.pli")
    problems: List[str] = []
    if len(document.structures) != len(trees):
        problems.append(f"The member declares {len(document.structures)} structure(s); the layout has "
                        f"{len(trees)} record(s).")
    for structure, tree in zip(document.structures, trees):
        layout = compute_layout(structure)
        written: List[Tuple[str, Optional[int]]] = []

        def walk(item: Any, path: str) -> None:
            name = f"{path}.{item.name}" if path else item.name
            if item.unread:
                problems.append(f"{name}: PL/I attributes the reader does not know: {', '.join(item.unread)}.")
            if item.children:
                for child in item.children:
                    walk(child, name)
            elif item.data is not None:
                written.append((name, layout[id(item)].length))

        walk(structure, "")
        expected: List[Tuple[str, Optional[int]]] = []
        _cobol_items(tree, "", expected)
        if len(written) != len(expected):
            problems.append(f"{structure.name}: {len(written)} elementary item(s) written; the copybook record has "
                            f"{len(expected)}.")
        for (pli, pli_length), (cobol, cobol_length) in zip(written, expected):
            # An item the copybook analysis cannot size (PIC N national text) has nothing to compare with.
            if cobol_length is not None and pli_length != cobol_length:
                problems.append(f"{pli} takes {pli_length} byte(s); the copybook item {cobol} takes {cobol_length}.")
    return problems
