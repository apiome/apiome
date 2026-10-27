"""Avro compatibility engine — MFI-12.4 (#3785).

Avro data written with one schema (the **writer's**) is read with another (the **reader's**), and
the `Avro specification's schema resolution rules
<https://avro.apache.org/docs/1.12.0/specification/#schema-resolution>`_ decide whether that works.
:func:`can_read` applies them the way Avro's Java ``SchemaCompatibility`` does — the checker a
Confluent Schema Registry runs — and reports each problem with the same incompatibility type and
location:

* ``NAME_MISMATCH`` — a record, enum or fixed whose (unqualified) name differs, unless one of the
  reader's aliases is the writer's full name.
* ``FIXED_SIZE_MISMATCH`` — a fixed of another size.
* ``MISSING_ENUM_SYMBOLS`` — writer symbols the reader lacks, unless the reader's enum has a
  ``default``.
* ``READER_FIELD_MISSING_DEFAULT_VALUE`` — a reader field the writer does not have (by name or the
  reader field's aliases) and that has no ``default``. Writer fields the reader lacks are skipped.
* ``TYPE_MISMATCH`` — types that do not resolve; the promotions int → long / float / double,
  long → float / double, float → double and string ↔ bytes do.
* ``MISSING_UNION_BRANCH`` — a writer branch no reader branch can read.

On top of that, :func:`check_compatibility` evaluates Confluent's compatibility levels: ``BACKWARD``
(the new schema reads data written with the old), ``FORWARD`` (the old reads the new), ``FULL``
(both), against the latest version or — ``*_TRANSITIVE`` — every version.

Pure: schemas in, findings out.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import fastavro.schema

from .avro_parser import AvroDocument

__all__ = [
    "LEVELS",
    "AvroCompatibilityError",
    "Incompatibility",
    "ParsedSchema",
    "CompatibilityVerdict",
    "parse_schema_text",
    "schema_of_document",
    "can_read",
    "directions_for",
    "check_compatibility",
    "describe",
    "confluent_messages",
]

#: Confluent's compatibility levels.
LEVELS: Tuple[str, ...] = (
    "NONE",
    "BACKWARD",
    "BACKWARD_TRANSITIVE",
    "FORWARD",
    "FORWARD_TRANSITIVE",
    "FULL",
    "FULL_TRANSITIVE",
)

_PRIMITIVES = frozenset({"null", "boolean", "int", "long", "float", "double", "bytes", "string"})

#: Reader type → the writer types it also reads (Avro's promotions).
_PROMOTIONS: Dict[str, frozenset] = {
    "long": frozenset({"int"}),
    "float": frozenset({"int", "long"}),
    "double": frozenset({"int", "long", "float"}),
    "bytes": frozenset({"string"}),
    "string": frozenset({"bytes"}),
}


class AvroCompatibilityError(ValueError):
    """Raised when a schema cannot be read for a compatibility check."""


@dataclass(frozen=True)
class ParsedSchema:
    """An Avro schema ready to compare.

    Attributes:
        schema: The schema as fastavro parses it: names are full names and a named type used
            again is referred to by its full name.
        named: Every named type the schema declares, by full name.
    """

    schema: Any
    named: Mapping[str, Any]


@dataclass(frozen=True)
class Incompatibility:
    """One reason the reader cannot read data written with the writer.

    Attributes:
        type: Avro's incompatibility type (``READER_FIELD_MISSING_DEFAULT_VALUE``, …).
        location: JSON pointer into the reader schema (``/fields/1/type``), as Avro reports it.
        message: Avro's message (the missing field, the missing symbols, the mismatched types…).
        record: Full name of the record the location is inside, when it is inside one.
        field: Name of the record field the location is on, when it is on one.
        schema: Full name of the reader's named type the problem is about (the enum missing
            symbols, the fixed of another size, the renamed type), when it is one.
    """

    type: str
    location: str
    message: str
    record: Optional[str] = None
    field: Optional[str] = None
    schema: Optional[str] = None


@dataclass
class _Context:
    reader_named: Mapping[str, Any]
    writer_named: Mapping[str, Any]
    #: Pairs being compared further up the stack; a recursive type compares as compatible there.
    in_progress: Set[Tuple[str, str]] = field(default_factory=set)


def parse_schema_text(text: str) -> ParsedSchema:
    """Parse ``.avsc`` JSON text (including a primitive schema such as ``"string"``).

    Args:
        text: The schema text.

    Returns:
        The parsed schema.

    Raises:
        AvroCompatibilityError: When the text is not a valid Avro schema.
    """
    try:
        raw = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise AvroCompatibilityError(f"Invalid Avro schema JSON: {exc}") from exc
    return _parse(raw)


def _parse(raw: Any, named: Optional[Dict[str, Any]] = None) -> ParsedSchema:
    named = {} if named is None else named
    try:
        parsed = fastavro.schema.parse_schema(raw, named, _write_hint=False, _ignore_default_error=True)
    except Exception as exc:  # fastavro raises several exception types for invalid schemas
        raise AvroCompatibilityError(f"Invalid Avro schema: {exc}") from exc
    return ParsedSchema(schema=parsed, named=named)


def schema_of_document(document: AvroDocument, full_name: Optional[str] = None) -> ParsedSchema:
    """Return one named type of a parsed ``.avsc`` / IDL document as a :class:`ParsedSchema`.

    Args:
        document: The parsed document.
        full_name: The type to return; the document's root type when ``None``.

    Returns:
        The type, with every named type the document declares available to resolve references.

    Raises:
        AvroCompatibilityError: When a type cannot be parsed or ``full_name`` is not declared.
    """
    named: Dict[str, Any] = {}
    pending = list(document.types)
    # IDL types refer to one another by name, so a type is parsed once the types it names are.
    while pending:
        left = []
        for named_schema in pending:
            try:
                fastavro.schema.parse_schema(
                    named_schema.schema, named, _write_hint=False, _ignore_default_error=True
                )
            except Exception:  # noqa: BLE001 - retried once its references are parsed
                left.append(named_schema)
        if len(left) == len(pending):
            names = ", ".join(_full(t.name, t.namespace) for t in left)
            raise AvroCompatibilityError(f"Avro types could not be resolved: {names}")
        pending = left
    root = full_name or _full(document.root.name, document.root.namespace)
    if root not in named:
        raise AvroCompatibilityError(f"Avro type {root!r} is not declared")
    return ParsedSchema(schema=named[root], named=named)


def _full(name: str, namespace: Optional[str]) -> str:
    return f"{namespace}.{name}" if namespace and "." not in name else name


# ===========================================================================
# Reader / writer resolution
# ===========================================================================


def can_read(reader: ParsedSchema, writer: ParsedSchema) -> List[Incompatibility]:
    """Return every reason ``reader`` cannot read data written with ``writer`` (empty: it can).

    Args:
        reader: The reader's schema.
        writer: The writer's schema.

    Returns:
        The incompatibilities, in the order Avro's checker finds them.
    """
    context = _Context(reader.named, writer.named)
    return _compare(reader.schema, writer.schema, context, [], None, None)


def _resolve(schema: Any, named: Mapping[str, Any]) -> Any:
    """Resolve a named reference (``"com.example.Status"``) to its definition."""
    if isinstance(schema, str) and schema not in _PRIMITIVES:
        return named.get(schema, schema)
    return schema


def _kind(schema: Any) -> str:
    if isinstance(schema, list):
        return "union"
    if isinstance(schema, str):
        return schema if schema in _PRIMITIVES else "unknown"
    if isinstance(schema, dict):
        kind = schema.get("type")
        if kind == "error":
            return "record"
        if isinstance(kind, str):
            return kind
    return "unknown"


def _type_name(schema: Any) -> str:
    """Avro's upper-case type name (``RECORD``, ``INT``), as its messages print it."""
    return _kind(schema).upper()


def _pointer(path: Sequence[str]) -> str:
    return "/" + "/".join(path) if path else "/"


def _short_name(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def _names_match(reader: Dict[str, Any], writer: Dict[str, Any]) -> bool:
    """Avro's ``schemaNameEquals``: same unqualified name, or a reader alias names the writer."""
    reader_name, writer_name = str(reader.get("name", "")), str(writer.get("name", ""))
    if _short_name(reader_name) == _short_name(writer_name):
        return True
    namespace = reader_name.rsplit(".", 1)[0] if "." in reader_name else None
    aliases = {_full(str(alias), namespace) for alias in reader.get("aliases") or []}
    return writer_name in aliases


def _compare(
    reader: Any,
    writer: Any,
    context: _Context,
    path: List[str],
    record: Optional[str],
    field_name: Optional[str],
) -> List[Incompatibility]:
    reader = _resolve(reader, context.reader_named)
    writer = _resolve(writer, context.writer_named)
    reader_kind, writer_kind = _kind(reader), _kind(writer)

    def incompatible(kind: str, message: str, *extra: str, schema: Optional[str] = None) -> List[Incompatibility]:
        return [Incompatibility(kind, _pointer(path + list(extra)), message, record, field_name, schema)]

    if reader_kind == writer_kind:
        if reader_kind in _PRIMITIVES:
            return []
        if reader_kind == "array":
            return _compare(reader["items"], writer["items"], context, path + ["items"], record, field_name)
        if reader_kind == "map":
            return _compare(reader["values"], writer["values"], context, path + ["values"], record, field_name)
        if reader_kind == "union":
            # Every branch the writer may have written must be readable.
            found: List[Incompatibility] = []
            for index, branch in enumerate(writer):
                found += _compare(reader, branch, context, path + [str(index)], record, field_name)
            return found
        if reader_kind in ("record", "enum", "fixed"):
            named = str(reader.get("name"))
            if not _names_match(reader, writer):
                return incompatible("NAME_MISMATCH", f"expected: {writer.get('name')}", "name", schema=named)
            if reader_kind == "fixed":
                if reader.get("size") != writer.get("size"):
                    return incompatible(
                        "FIXED_SIZE_MISMATCH",
                        f"expected: {writer.get('size')}, found: {reader.get('size')}",
                        "size",
                        schema=named,
                    )
                return []
            if reader_kind == "enum":
                return _compare_enums(reader, writer, path, record, field_name)
            return _compare_records(reader, writer, context, path)
        return []

    if writer_kind == "union":
        # Avro's checker compares each writer branch with a fresh location stack here, so a
        # problem is reported at ``/`` (Confluent's messages show the same).
        found = []
        for branch in writer:
            found += _compare(reader, branch, context, [], record, field_name)
        return found
    if reader_kind in _PRIMITIVES:
        if writer_kind in _PROMOTIONS.get(reader_kind, ()):
            return []
        return incompatible(
            "TYPE_MISMATCH",
            f"reader type: {_type_name(reader)} not compatible with writer type: {_type_name(writer)}",
        )
    if reader_kind == "union":
        for branch in reader:
            if not _compare(branch, writer, context, path, record, field_name):
                return []
        return incompatible("MISSING_UNION_BRANCH", f"reader union lacking writer type: {_type_name(writer)}")
    return incompatible(
        "TYPE_MISMATCH",
        f"reader type: {_type_name(reader)} not compatible with writer type: {_type_name(writer)}",
    )


def _compare_enums(
    reader: Dict[str, Any], writer: Dict[str, Any], path: List[str], record: Optional[str], field_name: Optional[str]
) -> List[Incompatibility]:
    missing = sorted(set(writer.get("symbols") or []) - set(reader.get("symbols") or []))
    if not missing:
        return []
    default = reader.get("default")
    if default is not None and default in (reader.get("symbols") or []):
        return []
    return [
        Incompatibility(
            "MISSING_ENUM_SYMBOLS",
            _pointer(path + ["symbols"]),
            f"[{', '.join(missing)}]",
            record,
            field_name,
            str(reader.get("name")),
        )
    ]


def _compare_records(
    reader: Dict[str, Any], writer: Dict[str, Any], context: _Context, path: List[str]
) -> List[Incompatibility]:
    pair = (str(reader.get("name")), str(writer.get("name")))
    if pair in context.in_progress:
        return []  # a recursive reference: the enclosing comparison decides
    context.in_progress.add(pair)
    try:
        record = str(reader.get("name"))
        writer_fields = {f.get("name"): f for f in writer.get("fields") or []}
        found: List[Incompatibility] = []
        for index, reader_field in enumerate(reader.get("fields") or []):
            name = reader_field.get("name")
            writer_field = writer_fields.get(name)
            if writer_field is None:
                for alias in reader_field.get("aliases") or []:
                    if alias in writer_fields:
                        writer_field = writer_fields[alias]
                        break
            field_path = path + ["fields", str(index)]
            if writer_field is None:
                if "default" not in reader_field:
                    found.append(
                        Incompatibility(
                            "READER_FIELD_MISSING_DEFAULT_VALUE", _pointer(field_path), str(name), record, name
                        )
                    )
                continue
            found += _compare(
                reader_field.get("type"), writer_field.get("type"), context, field_path + ["type"], record, name
            )
        return found
    finally:
        context.in_progress.discard(pair)


# ===========================================================================
# Confluent compatibility levels
# ===========================================================================


@dataclass(frozen=True)
class CompatibilityVerdict:
    """The verdict of one candidate schema against a subject's versions.

    Attributes:
        is_compatible: Whether the candidate satisfies the level.
        level: The level checked.
        failed_version: Index into the ``previous`` sequence given to :func:`check_compatibility`
            of the version the candidate failed against, or ``None`` when it is compatible.
            Like a Confluent registry, the check stops at the newest version that fails.
        failures: ``(direction, incompatibility)`` for every problem against that version, the
            ``forward`` ones (it cannot read the candidate) before the ``backward`` ones (the
            candidate cannot read it), in Confluent's order.
    """

    is_compatible: bool
    level: str
    failed_version: Optional[int] = None
    failures: Tuple[Tuple[str, Incompatibility], ...] = ()


def directions_for(level: str) -> Tuple[Tuple[str, ...], bool]:
    """Return the directions a level checks and whether it checks every version.

    Args:
        level: A Confluent compatibility level.

    Returns:
        ``(directions, transitive)``: directions from ``("backward", "forward")``.

    Raises:
        AvroCompatibilityError: For an unknown level.
    """
    if level not in LEVELS:
        raise AvroCompatibilityError(f"Unknown compatibility level {level!r}")
    if level == "NONE":
        return (), False
    base, _, transitive = level.partition("_")
    directions = {"BACKWARD": ("backward",), "FORWARD": ("forward",), "FULL": ("backward", "forward")}[base]
    return directions, bool(transitive)


def check_compatibility(
    level: str, candidate: ParsedSchema, previous: Sequence[ParsedSchema], *, only_latest: bool = False
) -> CompatibilityVerdict:
    """Check ``candidate`` against a subject's versions under a Confluent level.

    The versions the level selects — the latest, or every one for ``*_TRANSITIVE`` — are checked
    newest first, and the check stops at the first that fails, as a Confluent registry's does.

    Args:
        level: The compatibility level.
        candidate: The new schema.
        previous: The subject's versions, oldest first.
        only_latest: Check only the last of ``previous`` whatever the level (a request naming one
            version passes just that version).

    Returns:
        The verdict. ``NONE`` and an empty ``previous`` are always compatible.
    """
    directions, transitive = directions_for(level)
    if not directions or not previous:
        return CompatibilityVerdict(True, level)
    indexes = range(len(previous) - 1, -1, -1) if transitive and not only_latest else [len(previous) - 1]
    for index in indexes:
        old = previous[index]
        failures: List[Tuple[str, Incompatibility]] = []
        # Confluent lists a FULL check's forward problems before its backward ones.
        if "forward" in directions:
            failures += [("forward", found) for found in can_read(old, candidate)]
        if "backward" in directions:
            failures += [("backward", found) for found in can_read(candidate, old)]
        if failures:
            return CompatibilityVerdict(False, level, index, tuple(failures))
    return CompatibilityVerdict(True, level)


# ===========================================================================
# Confluent's messages
# ===========================================================================

#: Description templates by incompatibility type, as Confluent Schema Registry words them.
#: ``{reader}`` / ``{writer}`` are "new" / "old" for a backward check and the reverse for a
#: forward one.
_DESCRIPTIONS: Dict[str, str] = {
    "READER_FIELD_MISSING_DEFAULT_VALUE": (
        "The field '{info}' at path '{path}' in the {reader} schema has no default value and is missing in the "
        "{writer} schema"
    ),
    "TYPE_MISMATCH": (
        "The type (path '{path}') of a field in the {reader} schema does not match with the {writer} schema"
    ),
    "NAME_MISMATCH": "The name of the schema has changed (path '{path}')",
    "MISSING_ENUM_SYMBOLS": (
        "The {reader} schema is missing enum symbols '{info}' at path '{path}' in the {writer} schema"
    ),
    "MISSING_UNION_BRANCH": (
        "The {reader} schema is missing a type inside a union field at path '{path}' in the {writer} schema"
    ),
    "FIXED_SIZE_MISMATCH": (
        "The size of FIXED type field at path '{path}' in the {reader} schema does not match with the {writer} "
        "schema"
    ),
}


def describe(direction: str, incompatibility: Incompatibility) -> str:
    """Return one incompatibility as Confluent's ``{errorType, description, additionalInfo}`` message.

    Args:
        direction: ``backward`` (the new schema is the reader) or ``forward`` (the old one is).
        incompatibility: The incompatibility.

    Returns:
        The message, e.g. ``{errorType:'TYPE_MISMATCH', description:'…', additionalInfo:'…'}``.
    """
    reader, writer = ("new", "old") if direction == "backward" else ("old", "new")
    template = _DESCRIPTIONS.get(incompatibility.type, "{type} at path '{path}'")
    description = template.format(
        info=incompatibility.message,
        path=incompatibility.location,
        reader=reader,
        writer=writer,
        type=incompatibility.type,
    )
    return (
        f"{{errorType:'{incompatibility.type}', description:'{description}', "
        f"additionalInfo:'{incompatibility.message}'}}"
    )


def confluent_messages(
    verdict: CompatibilityVerdict, *, old_version: Optional[int] = None, old_schema: Optional[str] = None
) -> List[str]:
    """Return a verdict's ``messages`` as a Confluent registry's verbose answer lists them.

    Each incompatibility (:func:`describe`), then — unless every failure is a ``forward`` one
    under a ``FULL`` level, where Confluent omits them — ``{oldSchemaVersion: n}`` and
    ``{oldSchema: '…'}`` for the version that failed, then the level. A compatible verdict has no
    messages.

    Args:
        verdict: The verdict.
        old_version: The registry version number of ``verdict.failed_version``.
        old_schema: That version's schema text.

    Returns:
        The messages.
    """
    if verdict.is_compatible:
        return []
    messages = [describe(direction, found) for direction, found in verdict.failures]
    full = verdict.level.startswith("FULL")
    if not full or any(direction == "backward" for direction, _ in verdict.failures):
        if old_version is not None:
            messages.append(f"{{oldSchemaVersion: {old_version}}}")
        if old_schema is not None:
            messages.append(f"{{oldSchema: '{old_schema}'}}")
    messages.append(f"{{validateFields: 'false', compatibility: '{verdict.level}'}}")
    return messages
