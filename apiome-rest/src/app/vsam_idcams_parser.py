"""VSAM cluster definitions (IDCAMS) reader — FMT-11.3 (#5484).

Reads the two texts that describe a VSAM file's record envelope:

* **IDCAMS commands** — ``DEFINE CLUSTER``, ``DEFINE AIX`` (``ALTERNATEINDEX``), ``DEFINE PATH``
  and ``DEFINE GDG``, optionally wrapped in the JCL that runs them (``//STEP EXEC PGM=IDCAMS``,
  ``//SYSIN DD *``). Parameters are parenthesised, separated by blanks or commas, and continued
  with a trailing ``-`` (or ``+``); ``/* … */`` comments may appear anywhere. ``IF … THEN`` guards,
  ``DELETE``, ``SET``, ``REPRO``, ``BLDINDEX`` and ``LISTCAT`` commands are recognised and kept as
  utility commands; they describe what is done to a file, not its record.
* **LISTCAT listings** — ``LISTCAT ALL`` output, ``CLUSTER ------- <name>`` entries with their
  ``DATA`` / ``INDEX`` components and ``KEYLEN------10`` attribute pairs. It is often the only
  surviving description of a file.

What a cluster definition gives is the record **envelope**: organisation (``INDEXED`` → KSDS,
``NONINDEXED`` → ESDS, ``NUMBERED`` → RRDS / VRRDS, ``LINEAR`` → LDS), record size, the primary key's
length and offset, the alternate keys an ``AIX`` defines over it, and storage parameters. It never
gives the record's fields — those live in the COBOL copybook or PL/I declaration the programs use —
and the normalizer says so as a declared limit rather than implying a complete schema.

A **fileset** is read whole: an ``AIX`` in one member may ``RELATE`` to a cluster defined in another.

Refusals carry the intake taxonomy code (:mod:`app.intake_error_taxonomy`):

* ``INPUT_ENCODING_INVALID`` — NULs, U+FFFD replacement characters or a byte-order mark;
* ``FORMAT_MISMATCH`` — not a single IDCAMS command or LISTCAT entry was found;
* ``INPUT_MALFORMED`` — an unknown command among IDCAMS ones, a parameter nested inside another
  parameter's value list (a parenthesis left open), a stray ``)``, an unterminated quote or
  comment before the end of the input, or a parameter value that is not a number where one is
  required;
* ``INPUT_TRUNCATED`` — the input ends inside a command: a continuation with nothing after it, or a
  parameter list still open at the end;
* ``INPUT_SEMANTIC_INVALID`` — a definition without ``NAME``, an ``INDEXED`` cluster without
  ``KEYS``, ``KEYS`` on a cluster that has no key, a key outside the record, a name defined twice,
  or nothing with a record structure to model;
* ``INPUT_REFERENCE_UNRESOLVED`` — an ``AIX`` whose ``RELATE`` names no cluster in the import, or a
  ``PATH`` whose ``PATHENTRY`` names nothing defined.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .fileset import IntakeFileset
from .mainframe_misc_common import MainframeParseError, check_encoding, where

__all__ = [
    "FORMAT_KEY",
    "ORGANISATIONS",
    "VsamAlternateIndex",
    "VsamCluster",
    "VsamCommand",
    "VsamDocument",
    "VsamGdg",
    "VsamKey",
    "VsamPath",
    "has_idcams_commands",
    "is_listcat_listing",
    "parse_vsam_fileset",
    "parse_vsam_text",
]

#: The adapter / canonical format key of this sub-format.
FORMAT_KEY = "vsam-idcams"

#: Organisation flag → the dataset type it declares (``NUMBERED`` is refined to VRRDS when the
#: average and maximum record sizes differ).
ORGANISATIONS: Dict[str, str] = {
    "INDEXED": "KSDS",
    "NONINDEXED": "ESDS",
    "NUMBERED": "RRDS",
    "LINEAR": "LDS",
}

#: IDCAMS abbreviations → the full parameter / object keyword they stand for.
_ABBREVIATIONS: Dict[str, str] = {
    "AIX": "ALTERNATEINDEX",
    "BUFSP": "BUFFERSPACE",
    "CISZ": "CONTROLINTERVALSIZE",
    "CNVSZ": "CONTROLINTERVALSIZE",
    "CYL": "CYLINDERS",
    "DATACLAS": "DATACLASS",
    "FSPC": "FREESPACE",
    "GDG": "GENERATIONDATAGROUP",
    "IXD": "INDEXED",
    "KILO": "KILOBYTES",
    "LIN": "LINEAR",
    "MEGA": "MEGABYTES",
    "MGMTCLAS": "MANAGEMENTCLASS",
    "NIXD": "NONINDEXED",
    "NONUNIQKEY": "NONUNIQUEKEY",
    "NUMD": "NUMBERED",
    "NUNQK": "NONUNIQUEKEY",
    "PENT": "PATHENTRY",
    "REC": "RECORDS",
    "RECSZ": "RECORDSIZE",
    "REL": "RELATE",
    "SHR": "SHAREOPTIONS",
    "SPND": "SPANNED",
    "STORCLAS": "STORAGECLASS",
    "TRK": "TRACKS",
    "UNQK": "UNIQUEKEY",
    "UPG": "UPGRADE",
    "VOL": "VOLUMES",
}

#: Commands IDCAMS accepts. ``DO`` / ``END`` / ``ELSE`` are structure, not commands, so they do not
#: count as evidence that a text is IDCAMS input (assembler source ends with ``END`` too).
_COMMANDS = frozenset(
    {
        "ALTER",
        "BLDINDEX",
        "BIX",
        "CNVTCAT",
        "DCOLLECT",
        "DEFINE",
        "DEF",
        "DELETE",
        "DEL",
        "DIAGNOSE",
        "EXAMINE",
        "EXPORT",
        "IF",
        "IMPORT",
        "LISTCAT",
        "LISTC",
        "LISTDATA",
        "PARM",
        "PRINT",
        "REPRO",
        "SET",
        "SETCACHE",
        "SHCDS",
        "VERIFY",
    }
)
_STRUCTURE_WORDS = frozenset({"DO", "END", "ELSE"})

#: ``DEFINE`` objects that are not VSAM record files; kept as utility commands.
_OTHER_OBJECTS = frozenset({"NONVSAM", "ALIAS", "USERCATALOG", "UCAT", "MASTERCATALOG", "MCAT", "PAGESPACE", "PGSPC"})

#: Space-allocation parameters → the unit they allocate in.
_SPACE_UNITS: Dict[str, str] = {
    "CYLINDERS": "cylinders",
    "TRACKS": "tracks",
    "RECORDS": "records",
    "MEGABYTES": "megabytes",
    "KILOBYTES": "kilobytes",
}

#: Parameters whose values are dataset names, read off utility commands.
_DATASET_PARAMETERS = frozenset(
    {"INDATASET", "IDS", "OUTDATASET", "ODS", "ENTRIES", "ENT", "ENTRY", "INFILE", "OUTFILE"}
)

_LISTING_ENTRY_RE = re.compile(
    r"^\s*(CLUSTER|DATA|INDEX|AIX|PATH|GDG|NONVSAM|ALIAS|PAGESPACE|USERCATALOG)\s+-{2,}\s+(\S+)\s*$"
)
_LISTING_MARKER_RE = re.compile(r"^\s*(?:LISTING FROM CATALOG\b|CLUSTER\s+-{3,}\s+\S)", re.MULTILINE)
_LISTING_PAIR_RE = re.compile(r"([A-Z][A-Z0-9%/]*(?:-[A-Z0-9%/]+)*?)-{2,}(\S+)")
_LISTING_ASSOCIATION_RE = re.compile(r"^\s*(DATA|INDEX|AIX|CLUSTER|PATH)-{2,}(\S+)\s*$")
_LISTING_SECTIONS = frozenset({"HISTORY", "ASSOCIATIONS", "ATTRIBUTES", "STATISTICS", "ALLOCATION", "VOLUME"})
#: LISTCAT sections the reader does not model: activity counters and catalog bookkeeping.
DROPPED_LISTING_SECTIONS = frozenset({"HISTORY", "STATISTICS", "ALLOCATION", "VOLUME"})

_DEFINE_RE = re.compile(
    r"^\s*DEF(?:INE)?\s+(?:CLUSTER|AIX|ALTERNATEINDEX|PATH|GDG|GENERATIONDATAGROUP)\b",
    re.IGNORECASE | re.MULTILINE,
)
_TOKEN_RE = re.compile(r"\s*(?:(\()|(\))|(=)|('(?:[^']|'')*')|('[^']*$)|(,)|([^\s(),=']+))")


# ===========================================================================
# The parsed document
# ===========================================================================


@dataclass(frozen=True)
class VsamKey:
    """A key: ``KEYS(length offset)`` — ``length`` bytes at 0-based ``offset`` into the record."""

    length: int
    offset: int


@dataclass
class VsamCluster:
    """One VSAM cluster (a ``DEFINE CLUSTER`` or a ``LISTCAT`` ``CLUSTER`` entry).

    Attributes:
        name: The cluster's dataset name.
        organisation: ``KSDS``, ``ESDS``, ``RRDS``, ``VRRDS`` or ``LDS``.
        organisation_declared: ``False`` when no organisation flag was written (IDCAMS defaults to
            ``INDEXED``).
        key: The primary key (KSDS only).
        record_size: ``(average, maximum)`` record length in bytes, when declared.
        share_options: ``(cross-region, cross-system)``; the second may be ``None``.
        free_space: ``(CI %, CA %)``, when declared.
        ci_size: The data component's control-interval size.
        data_name: The data component's name, when named.
        index_name: The index component's name, when named.
        flags: Every other flag written (``SPANNED``, ``REUSE``, ``ERASE`` …), in source order.
        storage: Space, volume and SMS-class parameters.
        origin: ``define`` or ``listcat``.
        path: The file it was read from.
        associations: Alternate indexes a listing names as associated with the cluster.
    """

    name: str
    organisation: str
    organisation_declared: bool = True
    key: Optional[VsamKey] = None
    record_size: Optional[Tuple[int, int]] = None
    share_options: Optional[Tuple[int, Optional[int]]] = None
    free_space: Optional[Tuple[int, int]] = None
    ci_size: Optional[int] = None
    data_name: Optional[str] = None
    index_name: Optional[str] = None
    flags: Tuple[str, ...] = ()
    storage: Dict[str, object] = field(default_factory=dict)
    origin: str = "define"
    path: Optional[str] = None
    associations: Tuple[str, ...] = ()


@dataclass
class VsamAlternateIndex:
    """One alternate index (``DEFINE AIX``): a second key over its base cluster's records."""

    name: str
    relate: str
    key: VsamKey
    unique: bool = True
    upgrade: bool = True
    record_size: Optional[Tuple[int, int]] = None
    flags: Tuple[str, ...] = ()
    storage: Dict[str, object] = field(default_factory=dict)
    path: Optional[str] = None


@dataclass
class VsamPath:
    """One path (``DEFINE PATH``): the name a program opens to read a cluster through an index."""

    name: str
    entry: str
    update: bool = True
    path: Optional[str] = None


@dataclass
class VsamGdg:
    """One generation data group (``DEFINE GDG``): a schema-free container of like files."""

    name: str
    limit: Optional[int] = None
    flags: Tuple[str, ...] = ()
    path: Optional[str] = None


@dataclass
class VsamCommand:
    """A recognised command that does not define a record file (``REPRO``, ``BLDINDEX`` …)."""

    verb: str
    datasets: Tuple[str, ...] = ()
    path: Optional[str] = None


@dataclass
class VsamDocument:
    """Everything one import read.

    Attributes:
        clusters: The clusters, in source order.
        alternate_indexes: The alternate indexes, in source order.
        paths: The paths, in source order.
        gdgs: The generation data groups.
        commands: Utility commands and non-VSAM ``DEFINE`` objects.
        dropped_sections: ``(section, entry name)`` for each LISTCAT section not modelled.
        sources: Every file's text, keyed by path (or label).
        is_fileset: Whether the import was a fileset.
        label: The upload's label.
    """

    clusters: List[VsamCluster] = field(default_factory=list)
    alternate_indexes: List[VsamAlternateIndex] = field(default_factory=list)
    paths: List[VsamPath] = field(default_factory=list)
    gdgs: List[VsamGdg] = field(default_factory=list)
    commands: List[VsamCommand] = field(default_factory=list)
    dropped_sections: List[Tuple[str, str]] = field(default_factory=list)
    sources: Dict[str, str] = field(default_factory=dict)
    is_fileset: bool = False
    label: Optional[str] = None

    def cluster(self, name: str) -> Optional[VsamCluster]:
        """The cluster named ``name``, or ``None``."""
        return next((c for c in self.clusters if c.name == name), None)


# ===========================================================================
# Sniffing
# ===========================================================================


def is_listcat_listing(text: str) -> bool:
    """Whether ``text`` is LISTCAT output (``LISTING FROM CATALOG`` or a ``CLUSTER ---`` entry)."""
    return bool(_LISTING_MARKER_RE.search(text))


def has_idcams_commands(text: str) -> bool:
    """Whether ``text`` holds an IDCAMS ``DEFINE CLUSTER`` / ``AIX`` / ``PATH`` / ``GDG`` command."""
    return bool(_DEFINE_RE.search(text))


# ===========================================================================
# Lexing: JCL, comments, continuations, tokens
# ===========================================================================


@dataclass
class _Node:
    """One parsed element: a word, optionally followed by a parenthesised group.

    ``word`` is ``None`` for an anonymous group ``( … )``; ``children`` is ``None`` for a bare word.
    """

    word: Optional[str]
    children: Optional[List["_Node"]] = None


@dataclass
class _Command:
    """One logical command: its nodes, the line it starts on, and what went wrong reading it."""

    nodes: List[_Node]
    line: int
    error: Optional[MainframeParseError] = None


def _strip_jcl_and_comments(text: str, path: Optional[str]) -> List[str]:
    """Blank JCL statements and ``/* … */`` comments, keeping line numbers.

    A line starting ``//`` is JCL; a line that is only ``/*`` is the JCL in-stream delimiter.
    Everything else is IDCAMS input, in which ``/*`` opens a comment that ``*/`` closes, possibly on
    a later line. Quoted strings are respected.

    Raises:
        MainframeParseError: ``INPUT_TRUNCATED`` when a comment is still open at the end.
    """
    lines: List[str] = []
    in_comment = False
    for raw in text.splitlines():
        if not in_comment and (raw.startswith("//") or raw.strip() == "/*"):
            lines.append("")
            continue
        out: List[str] = []
        index = 0
        in_quote = False
        while index < len(raw):
            pair = raw[index : index + 2]
            if in_comment:
                if pair == "*/":
                    in_comment = False
                    index += 2
                    continue
                index += 1
                continue
            char = raw[index]
            if char == "'":
                in_quote = not in_quote
            elif not in_quote and pair == "/*":
                in_comment = True
                out.append(" ")
                index += 2
                continue
            out.append(char)
            index += 1
        lines.append("".join(out))
    if in_comment:
        raise MainframeParseError(f"The IDCAMS input{where(path)} ends inside a /* comment */", code="INPUT_TRUNCATED")
    return lines


def _logical_commands(lines: Sequence[str]) -> Tuple[List[Tuple[str, int]], bool]:
    """Join continued lines into commands.

    Returns:
        ``(commands, dangling)`` — each command's text and 1-based start line, and whether the
        input ended on a continuation mark.
    """
    commands: List[Tuple[str, int]] = []
    parts: List[str] = []
    start = 0
    for number, line in enumerate(lines, start=1):
        content = line.rstrip()
        if not parts and not content.strip():
            continue
        if not parts:
            start = number
        if content.endswith(("-", "+")):
            parts.append(content[:-1])
            continue
        parts.append(content)
        commands.append((" ".join(parts), start))
        parts = []
    if parts:
        commands.append((" ".join(parts), start))
        return commands, True
    return commands, False


def _tokenize(text: str) -> Tuple[List[str], bool]:
    """Split one command into tokens (``(``, ``)``, ``=``, quoted strings, words).

    Returns:
        ``(tokens, open_quote)`` — commas are separators and are dropped; ``open_quote`` is true
        when a quoted string is not closed.
    """
    tokens: List[str] = []
    position = 0
    while position < len(text):
        match = _TOKEN_RE.match(text, position)
        if match is None or match.end() == position:
            break
        position = match.end()
        if match.group(5) is not None:
            return tokens, True
        if match.group(6) is not None:
            continue
        token = next(group for group in match.groups() if group is not None)
        tokens.append(token)
    return tokens, False


def _build_nodes(tokens: Sequence[str]) -> Tuple[List[_Node], int, bool]:
    """Build the node tree of one command.

    Returns:
        ``(nodes, open_groups, stray_close)`` — the top-level nodes, how many groups were still
        open at the end, and whether a ``)`` closed nothing.
    """
    root: List[_Node] = []
    stack: List[List[_Node]] = [root]
    previous_word: Optional[_Node] = None
    stray = False
    for token in tokens:
        if token == "(":
            group: List[_Node] = []
            if previous_word is not None and previous_word.children is None:
                previous_word.children = group
            else:
                stack[-1].append(_Node(word=None, children=group))
            stack.append(group)
            previous_word = None
        elif token == ")":
            if len(stack) == 1:
                stray = True
            else:
                stack.pop()
            previous_word = None
        elif token == "=":
            stack[-1].append(_Node(word="="))
            previous_word = None
        else:
            node = _Node(word=token.upper() if not token.startswith("'") else token)
            stack[-1].append(node)
            previous_word = node
    return root, len(stack) - 1, stray


def _unquote(value: str) -> str:
    """``'A.B'`` → ``A.B`` (``''`` → ``'``); anything else as written."""
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def _canonical(word: Optional[str]) -> Optional[str]:
    """Expand an IDCAMS abbreviation."""
    if word is None:
        return None
    return _ABBREVIATIONS.get(word, word)


def _nested_parameter(nodes: Sequence[_Node], *, object_level: bool) -> Optional[str]:
    """The first parameter written inside another parameter's value list, or ``None``.

    A ``DEFINE`` object (``CLUSTER``, ``DATA``, ``INDEX``, ``AIX`` …) holds parameters; a parameter
    (``KEYS``, ``VOLUMES`` …) holds plain values. A group inside a value list means a parenthesis
    was left open, so the next parameter was read as one of its values.
    """
    for node in nodes:
        if node.children is None:
            continue
        if object_level and _canonical(node.word) in _GROUP_HOLDERS:
            found = _nested_parameter(node.children, object_level=False)
        else:
            found = next((child.word or "(" for child in node.children if child.children is not None), None)
        if found is not None:
            return found if node.word is None else f"{node.word}({found}"
    return None


#: Nodes whose group holds parameters rather than values.
_GROUP_HOLDERS = frozenset(
    {"CLUSTER", "DATA", "INDEX", "ALTERNATEINDEX", "PATH", "GENERATIONDATAGROUP"} | _OTHER_OBJECTS
)


def _read_commands(text: str, path: Optional[str]) -> List[_Command]:
    """Read every logical command, deferring per-command errors to the caller.

    Errors are attached to their command rather than raised, so the caller can first decide
    whether the text is IDCAMS input at all (``FORMAT_MISMATCH``) before reporting a fault in it.
    """
    lines = _strip_jcl_and_comments(text, path)
    logical, dangling = _logical_commands(lines)
    commands: List[_Command] = []
    for index, (command_text, line) in enumerate(logical):
        last = index == len(logical) - 1
        tokens, open_quote = _tokenize(command_text)
        nodes, open_groups, stray = _build_nodes(tokens)
        command = _Command(nodes=nodes, line=line)
        at = f"{where(path)} at line {line}"
        nested = _nested_parameter(nodes, object_level=bool(nodes) and _canonical(nodes[0].word) in {"DEFINE", "DEF"})
        if stray:
            command.error = MainframeParseError(
                f"The command{at} closes a parenthesis it never opened", code="INPUT_MALFORMED"
            )
        elif nested is not None:
            command.error = MainframeParseError(
                f"The command{at} has a parameter inside another parameter's values ({nested}…): "
                "a parenthesis is not closed",
                code="INPUT_MALFORMED",
            )
        elif open_quote or open_groups:
            what = "a quoted string" if open_quote else "a parameter list"
            if last:
                command.error = MainframeParseError(
                    f"The IDCAMS input{where(path)} ends inside {what} of the command at line {line}",
                    code="INPUT_TRUNCATED",
                )
            else:
                command.error = MainframeParseError(f"The command{at} leaves {what} open", code="INPUT_MALFORMED")
        elif dangling and last:
            command.error = MainframeParseError(
                f"The IDCAMS input{where(path)} ends on a continuation of the command at line {line}",
                code="INPUT_TRUNCATED",
            )
        commands.append(command)
    return commands


# ===========================================================================
# Interpreting DEFINE parameters
# ===========================================================================


@dataclass
class _Parameters:
    """The parameters of one ``DEFINE`` object group: valued parameters and bare flags."""

    values: Dict[str, List[str]] = field(default_factory=dict)
    flags: List[str] = field(default_factory=list)

    @classmethod
    def read(cls, nodes: Sequence[_Node]) -> "_Parameters":
        params = cls()
        for node in nodes:
            word = _canonical(node.word)
            if word is None:
                continue
            if node.children is None:
                if word not in params.flags:
                    params.flags.append(word)
            else:
                params.values[word] = [_unquote(child.word or "") for child in node.children]
        return params

    def merged(self, other: "_Parameters") -> "_Parameters":
        """These parameters with ``other``'s filling the gaps (a ``DATA`` component's)."""
        values = dict(other.values)
        values.update(self.values)
        flags = list(self.flags) + [flag for flag in other.flags if flag not in self.flags]
        return _Parameters(values=values, flags=flags)


def _integers(params: _Parameters, name: str, *, at: str, count: Tuple[int, int]) -> Optional[List[int]]:
    """Read parameter ``name`` as ``count[0]``–``count[1]`` integers, or ``None`` when absent.

    Raises:
        MainframeParseError: ``INPUT_MALFORMED`` for a non-numeric or wrongly sized value list.
    """
    raw = params.values.get(name)
    if raw is None:
        return None
    if not count[0] <= len(raw) <= count[1] or not all(value.isdigit() for value in raw):
        expected = f"{count[0]}" if count[0] == count[1] else f"{count[0]} or {count[1]}"
        raise MainframeParseError(
            f"{name}({' '.join(raw)}){at} must be {expected} whole number(s)", code="INPUT_MALFORMED"
        )
    return [int(value) for value in raw]


def _name(params: _Parameters, *, what: str, at: str) -> str:
    """The definition's ``NAME``.

    Raises:
        MainframeParseError: ``INPUT_SEMANTIC_INVALID`` when it is missing.
    """
    raw = params.values.get("NAME")
    if not raw or not raw[0]:
        raise MainframeParseError(f"DEFINE {what}{at} has no NAME", code="INPUT_SEMANTIC_INVALID")
    return raw[0]


def _storage(params: _Parameters) -> Dict[str, object]:
    """Space, volume and SMS-class parameters, as declared metadata."""
    storage: Dict[str, object] = {}
    for parameter, unit in _SPACE_UNITS.items():
        raw = params.values.get(parameter)
        if raw:
            storage["space"] = {
                "unit": unit,
                "primary": int(raw[0]) if raw[0].isdigit() else raw[0],
                **({"secondary": int(raw[1]) if raw[1].isdigit() else raw[1]} if len(raw) > 1 else {}),
            }
    if params.values.get("VOLUMES"):
        storage["volumes"] = list(params.values["VOLUMES"])
    for parameter, key in (
        ("STORAGECLASS", "storageClass"),
        ("MANAGEMENTCLASS", "managementClass"),
        ("DATACLASS", "dataClass"),
    ):
        if params.values.get(parameter):
            storage[key] = params.values[parameter][0]
    return storage


def _record_size(params: _Parameters, at: str) -> Optional[Tuple[int, int]]:
    values = _integers(params, "RECORDSIZE", at=at, count=(2, 2))
    return (values[0], values[1]) if values else None


def _key(params: _Parameters, at: str) -> Optional[VsamKey]:
    values = _integers(params, "KEYS", at=at, count=(2, 2))
    if values is None:
        return None
    if values[0] < 1:
        raise MainframeParseError(f"KEYS{at} declares a key of length 0", code="INPUT_SEMANTIC_INVALID")
    return VsamKey(length=values[0], offset=values[1])


#: Valued parameters the cluster model reads itself; everything else valued is ignored metadata.
_RESERVED_FLAGS = frozenset(ORGANISATIONS) | {"UNIQUEKEY", "NONUNIQUEKEY", "UPGRADE", "NOUPGRADE", "UPDATE", "NOUPDATE"}


def _cluster_from_define(nodes: Sequence[_Node], *, path: Optional[str], at: str) -> VsamCluster:
    """Build a cluster from ``DEFINE CLUSTER (…) [DATA (…)] [INDEX (…)]``."""
    groups: Dict[str, _Parameters] = {}
    for node in nodes:
        word = _canonical(node.word)
        if word in {"CLUSTER", "DATA", "INDEX"} and node.children is not None:
            groups[word] = _Parameters.read(node.children)
    base = groups.get("CLUSTER", _Parameters())
    data = groups.get("DATA", _Parameters())
    params = base.merged(data)
    name = _name(base, what="CLUSTER", at=at)
    declared = [flag for flag in params.flags if flag in ORGANISATIONS]
    organisation = ORGANISATIONS[declared[0]] if declared else "KSDS"
    record_size = _record_size(params, at)
    if organisation == "RRDS" and record_size and record_size[0] != record_size[1]:
        organisation = "VRRDS"
    key = _key(params, at)
    if organisation == "KSDS" and key is None:
        raise MainframeParseError(
            f"Cluster {name}{at} is INDEXED (key-sequenced) but declares no KEYS, so the key's "
            "position and length are unknown (IDCAMS would assume KEYS(64 0); Apiome does not "
            "invent a key)",
            code="INPUT_SEMANTIC_INVALID",
        )
    if organisation != "KSDS" and key is not None:
        raise MainframeParseError(
            f"Cluster {name}{at} declares KEYS but is {declared[0] if declared else organisation}: only an "
            "INDEXED cluster has a key",
            code="INPUT_SEMANTIC_INVALID",
        )
    share = _integers(params, "SHAREOPTIONS", at=at, count=(1, 2))
    free = _integers(params, "FREESPACE", at=at, count=(1, 2))
    ci = _integers(params, "CONTROLINTERVALSIZE", at=at, count=(1, 1))
    data_name = data.values.get("NAME", [None])[0]
    index_name = groups.get("INDEX", _Parameters()).values.get("NAME", [None])[0]
    return VsamCluster(
        name=name,
        organisation=organisation,
        organisation_declared=bool(declared),
        key=key,
        record_size=record_size,
        share_options=(share[0], share[1] if len(share) > 1 else None) if share else None,
        free_space=(free[0], free[1] if len(free) > 1 else 0) if free else None,
        ci_size=ci[0] if ci else None,
        data_name=data_name,
        index_name=index_name,
        flags=tuple(flag for flag in params.flags if flag not in _RESERVED_FLAGS),
        storage=_storage(params),
        origin="define",
        path=path,
    )


def _object_group(nodes: Sequence[_Node], keyword: str) -> _Parameters:
    for node in nodes:
        if _canonical(node.word) == keyword and node.children is not None:
            return _Parameters.read(node.children)
    return _Parameters()


def _aix_from_define(nodes: Sequence[_Node], *, path: Optional[str], at: str) -> VsamAlternateIndex:
    """Build an alternate index from ``DEFINE AIX (…)``."""
    params = _object_group(nodes, "ALTERNATEINDEX").merged(_object_group(nodes, "DATA"))
    name = _name(params, what="AIX", at=at)
    relate = params.values.get("RELATE")
    if not relate or not relate[0]:
        raise MainframeParseError(
            f"Alternate index {name}{at} has no RELATE, so its base cluster is unknown",
            code="INPUT_SEMANTIC_INVALID",
        )
    key = _key(params, at)
    if key is None:
        raise MainframeParseError(
            f"Alternate index {name}{at} declares no KEYS, so the alternate key is unknown",
            code="INPUT_SEMANTIC_INVALID",
        )
    return VsamAlternateIndex(
        name=name,
        relate=relate[0],
        key=key,
        unique="NONUNIQUEKEY" not in params.flags,
        upgrade="NOUPGRADE" not in params.flags,
        record_size=_record_size(params, at),
        flags=tuple(flag for flag in params.flags if flag not in _RESERVED_FLAGS),
        storage=_storage(params),
        path=path,
    )


def _path_from_define(nodes: Sequence[_Node], *, path: Optional[str], at: str) -> VsamPath:
    params = _object_group(nodes, "PATH")
    name = _name(params, what="PATH", at=at)
    entry = params.values.get("PATHENTRY")
    if not entry or not entry[0]:
        raise MainframeParseError(f"Path {name}{at} has no PATHENTRY", code="INPUT_SEMANTIC_INVALID")
    return VsamPath(name=name, entry=entry[0], update="NOUPDATE" not in params.flags, path=path)


def _gdg_from_define(nodes: Sequence[_Node], *, path: Optional[str], at: str) -> VsamGdg:
    params = _object_group(nodes, "GENERATIONDATAGROUP")
    limit = _integers(params, "LIMIT", at=at, count=(1, 1))
    return VsamGdg(
        name=_name(params, what="GDG", at=at),
        limit=limit[0] if limit else None,
        flags=tuple(params.flags),
        path=path,
    )


def _datasets(nodes: Sequence[_Node]) -> Tuple[str, ...]:
    """Dataset names a utility command names (``INDATASET``, ``OUTDATASET``, ``ENTRIES`` …)."""
    names: List[str] = []
    for node in nodes:
        if node.children is not None and (node.word is None or node.word in _DATASET_PARAMETERS):
            names.extend(child.word for child in node.children if child.word and child.children is None)
    return tuple(names)


def _interpret(command: _Command, document: VsamDocument, path: Optional[str]) -> None:
    """Add one error-free command's definitions to ``document``."""
    nodes = command.nodes
    at = f"{where(path)} at line {command.line}"
    while nodes and nodes[0].word in {"IF", "ELSE"}:
        then = next((i for i, node in enumerate(nodes) if node.word == "THEN"), None)
        if nodes[0].word == "ELSE":
            nodes = nodes[1:]
        elif then is None:
            raise MainframeParseError(f"IF{at} has no THEN", code="INPUT_MALFORMED")
        else:
            nodes = nodes[then + 1 :]
    while nodes and nodes[0].word in _STRUCTURE_WORDS:
        nodes = nodes[1:]
    if not nodes:
        return
    verb = _canonical(nodes[0].word) or ""
    if verb in {"DEFINE", "DEF"}:
        target = _canonical(nodes[1].word) if len(nodes) > 1 else None
        rest = nodes[1:]
        if target == "CLUSTER":
            document.clusters.append(_cluster_from_define(rest, path=path, at=at))
        elif target == "ALTERNATEINDEX":
            document.alternate_indexes.append(_aix_from_define(rest, path=path, at=at))
        elif target == "PATH":
            document.paths.append(_path_from_define(rest, path=path, at=at))
        elif target == "GENERATIONDATAGROUP":
            document.gdgs.append(_gdg_from_define(rest, path=path, at=at))
        elif target in _OTHER_OBJECTS:
            group = _object_group(rest, target)
            document.commands.append(
                VsamCommand(verb=f"DEFINE {target}", datasets=tuple(group.values.get("NAME", [])), path=path)
            )
        else:
            raise MainframeParseError(
                f"DEFINE{at} names no object IDCAMS knows ({target or 'nothing'})", code="INPUT_MALFORMED"
            )
        return
    if verb == "DEL":
        verb = "DELETE"
    document.commands.append(VsamCommand(verb=verb, datasets=_datasets(nodes[1:]) or _positional(nodes), path=path))


def _positional(nodes: Sequence[_Node]) -> Tuple[str, ...]:
    """The bare dataset names after a ``DELETE`` (``DELETE A.B.C CLUSTER PURGE``)."""
    if not nodes or _canonical(nodes[0].word) != "DELETE":
        return ()
    return tuple(node.word for node in nodes[1:2] if node.word and node.children is None)


def _read_idcams(text: str, path: Optional[str], document: VsamDocument) -> None:
    """Read IDCAMS commands into ``document``."""
    commands = _read_commands(text, path)
    verbs = [_canonical(command.nodes[0].word) if command.nodes else None for command in commands]
    if not any(verb in _COMMANDS for verb in verbs):
        raise MainframeParseError(
            f"No IDCAMS command{where(path)} (DEFINE CLUSTER, DEFINE AIX, LISTCAT …) and no LISTCAT "
            "listing was found; this is not VSAM catalog input",
            code="FORMAT_MISMATCH",
        )
    for command, verb in zip(commands, verbs):
        if command.error is not None:
            raise command.error
        if verb not in _COMMANDS and verb not in _STRUCTURE_WORDS:
            raise MainframeParseError(
                f"{verb or 'The text'}{where(path)} at line {command.line} is not an IDCAMS command",
                code="INPUT_MALFORMED",
            )
        _interpret(command, document, path)


# ===========================================================================
# LISTCAT listings
# ===========================================================================


@dataclass
class _ListingEntry:
    kind: str
    name: str
    attributes: Dict[str, str] = field(default_factory=dict)
    flags: List[str] = field(default_factory=list)
    associations: List[Tuple[str, str]] = field(default_factory=list)


def _read_listing(text: str, path: Optional[str], document: VsamDocument) -> None:
    """Read ``LISTCAT`` output into ``document``.

    The ``ATTRIBUTES`` of a cluster's ``DATA`` component carry its envelope: ``KEYLEN`` and ``RKP``
    (relative key position) are the key, ``AVGLRECL`` / ``MAXLRECL`` the record size, ``SHROPTNS``
    the share options, and one of ``INDEXED`` / ``NONINDEXED`` / ``NUMBERED`` / ``LINEAR`` the
    organisation. ``HISTORY`` and ``STATISTICS`` are counted as dropped sections.
    """
    lines = _strip_jcl_and_comments(text, path)
    entries: List[_ListingEntry] = []
    section: Optional[str] = None
    for line in lines:
        match = _LISTING_ENTRY_RE.match(line)
        if match:
            entries.append(_ListingEntry(kind=match.group(1), name=match.group(2)))
            section = None
            continue
        stripped = line.strip()
        if not stripped or not entries:
            continue
        if stripped.startswith("IN-CAT"):
            continue
        if stripped in _LISTING_SECTIONS:
            section = stripped
            if stripped in DROPPED_LISTING_SECTIONS:
                document.dropped_sections.append((stripped, entries[-1].name))
            continue
        entry = entries[-1]
        if section == "ASSOCIATIONS":
            association = _LISTING_ASSOCIATION_RE.match(line)
            if association:
                entry.associations.append((association.group(1), association.group(2)))
        elif section == "ATTRIBUTES":
            for name, value in _LISTING_PAIR_RE.findall(stripped):
                entry.attributes[name] = value
            remainder = _LISTING_PAIR_RE.sub(" ", stripped)
            for word in remainder.split():
                if word.startswith("SHROPTNS(") and word.endswith(")"):
                    entry.attributes["SHROPTNS"] = word[len("SHROPTNS(") : -1]
                elif re.fullmatch(r"[A-Z][A-Z0-9-]*", word):
                    entry.flags.append(word)
    if not any(entry.kind == "CLUSTER" for entry in entries):
        raise MainframeParseError(
            f"The LISTCAT listing{where(path)} lists no CLUSTER entry", code="INPUT_SEMANTIC_INVALID"
        )
    _clusters_from_listing(entries, path, document)


def _listing_int(entry: Optional[_ListingEntry], name: str, at: str) -> Optional[int]:
    if entry is None or name not in entry.attributes:
        return None
    value = entry.attributes[name]
    if not value.isdigit():
        raise MainframeParseError(f"{name}----{value}{at} is not a number", code="INPUT_MALFORMED")
    return int(value)


def _clusters_from_listing(entries: Sequence[_ListingEntry], path: Optional[str], document: VsamDocument) -> None:
    """Turn listing entries into clusters (and alternate indexes, when an AIX entry is listed)."""
    by_name = {entry.name: entry for entry in entries}
    for entry in entries:
        if entry.kind not in {"CLUSTER", "AIX"}:
            continue
        at = f"{where(path)} ({entry.kind} {entry.name})"
        data_name = next((name for kind, name in entry.associations if kind == "DATA"), None)
        index_name = next((name for kind, name in entry.associations if kind == "INDEX"), None)
        data = by_name.get(data_name) if data_name else None
        source = data or entry
        flags = list(source.flags)
        declared = [flag for flag in flags if flag in ORGANISATIONS]
        keylen = _listing_int(source, "KEYLEN", at)
        rkp = _listing_int(source, "RKP", at) or 0
        average = _listing_int(source, "AVGLRECL", at)
        maximum = _listing_int(source, "MAXLRECL", at)
        record_size = (average if average is not None else maximum, maximum) if maximum is not None else None
        key = VsamKey(length=keylen, offset=rkp) if keylen else None
        if entry.kind == "AIX":
            relate = next((name for kind, name in entry.associations if kind == "CLUSTER"), None)
            if relate is None or key is None:
                continue
            document.alternate_indexes.append(
                VsamAlternateIndex(
                    name=entry.name,
                    relate=relate,
                    key=key,
                    unique="NONUNIQKEY" not in flags and "NONUNIQUEKEY" not in flags,
                    upgrade="NOUPGRADE" not in flags,
                    record_size=record_size,
                    path=path,
                )
            )
            continue
        organisation = ORGANISATIONS[declared[0]] if declared else "KSDS"
        if organisation == "RRDS" and record_size and record_size[0] != record_size[1]:
            organisation = "VRRDS"
        if organisation == "KSDS" and key is None:
            raise MainframeParseError(
                f"Cluster {entry.name}{at} is INDEXED but the listing shows no KEYLEN",
                code="INPUT_SEMANTIC_INVALID",
            )
        share = (source.attributes.get("SHROPTNS") or "").split(",")
        ci = _listing_int(source, "CISIZE", at)
        document.clusters.append(
            VsamCluster(
                name=entry.name,
                organisation=organisation,
                organisation_declared=bool(declared),
                key=key if organisation == "KSDS" else None,
                record_size=record_size,
                share_options=(int(share[0]), int(share[1]) if len(share) > 1 and share[1].isdigit() else None)
                if share[0].isdigit()
                else None,
                ci_size=ci,
                data_name=data_name,
                index_name=index_name,
                flags=tuple(flag for flag in flags if flag not in _RESERVED_FLAGS),
                origin="listcat",
                path=path,
                associations=tuple(name for kind, name in entry.associations if kind == "AIX"),
            )
        )


# ===========================================================================
# Entry points and cross-definition checks
# ===========================================================================


def _read_file(text: str, path: Optional[str], document: VsamDocument) -> None:
    check_encoding(text, path, what="IDCAMS input")
    if is_listcat_listing(text):
        _read_listing(text, path, document)
    else:
        _read_idcams(text, path, document)
    document.sources[path or "input.idcams"] = text


def _check_document(document: VsamDocument) -> None:
    """Cross-definition checks: unique names, resolvable references, keys inside records.

    Raises:
        MainframeParseError: ``INPUT_SEMANTIC_INVALID`` or ``INPUT_REFERENCE_UNRESOLVED``.
    """
    seen: Dict[str, str] = {}
    named: List[Tuple[str, Optional[str]]] = [(c.name, c.path) for c in document.clusters]
    named += [(a.name, a.path) for a in document.alternate_indexes]
    named += [(p.name, p.path) for p in document.paths]
    named += [(g.name, g.path) for g in document.gdgs]
    for name, path in named:
        if name in seen:
            raise MainframeParseError(
                f"{name} is defined twice ({seen[name]} and {path or 'the input'})",
                code="INPUT_SEMANTIC_INVALID",
            )
        seen[name] = path or "the input"
    for cluster in document.clusters:
        if cluster.key and cluster.record_size and cluster.key.offset + cluster.key.length > cluster.record_size[1]:
            raise MainframeParseError(
                f"The key of {cluster.name} (KEYS({cluster.key.length} {cluster.key.offset})) ends past "
                f"its {cluster.record_size[1]}-byte maximum record",
                code="INPUT_SEMANTIC_INVALID",
            )
    for aix in document.alternate_indexes:
        base = document.cluster(aix.relate)
        if base is None:
            raise MainframeParseError(
                f"Alternate index {aix.name}{where(aix.path)} RELATEs to {aix.relate}, which no DEFINE "
                "CLUSTER in the import creates; import the base cluster's definition with it",
                code="INPUT_REFERENCE_UNRESOLVED",
            )
        if base.organisation not in {"KSDS", "ESDS"}:
            raise MainframeParseError(
                f"Alternate index {aix.name} RELATEs to {aix.relate}, a {base.organisation}: alternate "
                "indexes exist only over key-sequenced and entry-sequenced clusters",
                code="INPUT_SEMANTIC_INVALID",
            )
        if base.record_size and aix.key.offset + aix.key.length > base.record_size[1]:
            raise MainframeParseError(
                f"The alternate key of {aix.name} (KEYS({aix.key.length} {aix.key.offset})) ends past "
                f"the {base.record_size[1]}-byte maximum record of {base.name}",
                code="INPUT_SEMANTIC_INVALID",
            )
    defined = {c.name for c in document.clusters} | {a.name for a in document.alternate_indexes}
    for vsam_path in document.paths:
        if vsam_path.entry not in defined:
            raise MainframeParseError(
                f"Path {vsam_path.name}{where(vsam_path.path)} has PATHENTRY({vsam_path.entry}), which no "
                "DEFINE in the "
                "import creates",
                code="INPUT_REFERENCE_UNRESOLVED",
            )
    if not any(cluster.organisation != "LDS" for cluster in document.clusters):
        raise MainframeParseError(
            "The import defines no cluster with a record structure (only linear datasets, generation "
            "data groups or utility commands), so there is no record to model",
            code="INPUT_SEMANTIC_INVALID",
        )


def parse_vsam_text(text: str, *, label: Optional[str] = None) -> VsamDocument:
    """Parse one uploaded IDCAMS job, command stream or LISTCAT listing.

    Args:
        text: The file text.
        label: The upload's file name, for messages.

    Returns:
        The parsed document.

    Raises:
        MainframeParseError: See the module docstring.
    """
    if text is None or not text.strip():
        raise MainframeParseError("The IDCAMS input is empty", code="INPUT_EMPTY")
    document = VsamDocument(label=label)
    _read_file(text, label, document)
    _check_document(document)
    return document


def parse_vsam_fileset(fileset: IntakeFileset, *, label: Optional[str] = None) -> VsamDocument:
    """Parse a set of IDCAMS / LISTCAT members read together.

    Members are read in path order; a blank member is skipped. References (``RELATE``,
    ``PATHENTRY``) resolve across every member.

    Args:
        fileset: The uploaded set.
        label: The upload's label.

    Returns:
        The parsed document.

    Raises:
        MainframeParseError: See the module docstring.
    """
    document = VsamDocument(label=label or fileset.root, is_fileset=True)
    for path in sorted(fileset.members):
        text = fileset.members[path]
        if not text.strip():
            continue
        _read_file(text, path, document)
    if not document.sources:
        raise MainframeParseError("Every member of the IDCAMS upload is empty", code="INPUT_EMPTY")
    _check_document(document)
    return document
