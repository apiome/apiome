"""Dhall reader — the Dhall third of FMT-8.5 (#5466).

In Dhall, types are values: a schema file is an expression whose fields are record types
(``{ id : Text, seenAt : Natural }``), union types (``< New | Paid >``) and *schema records*
(``{ Type = …, default = … }``, the shape the ``::`` completion operator reads). This reader lets
the Dhall interpreter do the reading. In the sandboxed toolchain runner it runs the bundled
``dhall`` twice:

1. ``dhall --file <root>`` — resolves the upload's imports, type-checks and normalizes it. A type
   error, an import that is not in the upload or a syntax error rejects the import with the
   reason Dhall gave. What comes back is the expression in normal form: every ``let`` inlined,
   every ``//\\`` record-type merge and every function application already computed.
2. ``dhall encode --json`` — the normal form in Dhall's standard binary encoding, as JSON: an
   unambiguous syntax tree this reader walks (:func:`project`).

``dhall-to-json`` renders *values*; a Dhall schema is a type, which it cannot render, so the
reader projects the types itself, following ``dhall-to-json``'s conventions for what a value of
each type looks like in JSON (an ``Optional`` may be ``null``, an empty union alternative is its
name, ``List { mapKey, mapValue }`` is an object).

**Imports.** Dhall can import from URLs, environment variables and absolute paths. The sandbox
refuses all three before Dhall runs (:func:`refused_imports`) — the evaluation has no network
anyway, but a local file or variable outside the upload must never be read. Relative imports
within the upload resolve normally.

**Declared limits.** Normalization erases names: a record type used in two places is one
structure, so the reader names a nested type by matching it against the top-level types
(Dhall's types are structural, so the match is exact). Functions — type-level (``\\(a : Type) ->
…``) or not — have no JSON Schema analogue and are declared, as is an import's integrity hash.
"""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .typed_config_common import (
    MODEL_PARTIAL_SUFFIXES,
    ToolFailure,
    TypedConfigDocument,
    TypedConfigParseError,
    first_lines,
    guard_input,
    model_limit_details,
    pascal_case,
    run_typed_config_tool,
    syntax_error_code,
    workspace,
)

__all__ = [
    "DHALL_FORMAT",
    "DHALL_SUFFIXES",
    "DHALL_TOOL_KEY",
    "LIMIT_DETAILS",
    "PARTIAL_LIMITS",
    "is_dhall_source",
    "parse_dhall",
    "parse_dhall_fileset",
    "project",
    "refused_imports",
]

#: The format key the reader, normalizer and adapter share.
DHALL_FORMAT = "dhall"

#: Registry key of the bundled ``dhall`` CLI (declared in :mod:`app.toolchain_packaging`).
DHALL_TOOL_KEY = "dhall"

#: The file suffixes a Dhall upload uses.
DHALL_SUFFIXES: Tuple[str, ...] = (".dhall",)

#: The display name used in messages.
_LABEL = "Dhall"

#: Every construct the reader declares rather than models, with the sentence that says what
#: happens to it.
LIMIT_DETAILS: Dict[str, str] = {
    "dhall.function": (
        "A function — a type-level one (`\\(a : Type) -> { items : List a }`) or any other — "
        "computes a type or a value from its arguments. It has no JSON Schema analogue and is "
        "left out of the model; a type it was applied to (`Page Text`) is modelled as the type "
        "it produced."
    ),
    "dhall.integrity_check": (
        "An import pinned with a `sha256:` integrity hash is modelled as the expression it "
        "resolved to. The pin itself — that the import must never change — is not modelled."
    ),
    "dhall.computed_default": (
        "A default in a schema record that is not a plain value after normalization (it still "
        "depends on a function's argument) has no single value to record. The field is modelled "
        "without a default."
    ),
}
LIMIT_DETAILS.update(model_limit_details(DHALL_FORMAT, _LABEL))

#: The limits whose construct is still modelled, with only a detail lost.
PARTIAL_LIMITS = frozenset(
    {
        *(f"{DHALL_FORMAT}.{suffix}" for suffix in MODEL_PARTIAL_SUFFIXES),
        "dhall.integrity_check",
        "dhall.computed_default",
    }
)

#: Built-in types and their JSON Schema, as ``dhall-to-json`` renders their values.
_BUILTIN_TYPES: Dict[str, Dict[str, Any]] = {
    "Text": {"type": "string"},
    "Natural": {"type": "integer", "minimum": 0},
    "Integer": {"type": "integer"},
    "Double": {"type": "number"},
    "Bool": {"type": "boolean"},
    "Date": {"type": "string", "format": "date"},
    "Time": {"type": "string", "format": "time"},
    "TimeZone": {"type": "string"},
    "Bytes": {"type": "string"},
}

# Standard-encoding labels (the first element of an encoded expression).
_APP, _LAMBDA, _PI, _LIST, _SOME = 0, 1, 2, 4, 5
_RECORD_TYPE, _RECORD, _FIELD, _UNION_TYPE = 7, 8, 9, 11
_NATURAL, _INTEGER, _TEXT = 15, 16, 18

#: A ``let`` binding at the start of a line.
_LET_RE = re.compile(r"^\s*let\s+[A-Za-z_][\w/-]*\s*(?::|=)", re.MULTILINE)
#: A typed field written the Dhall way, with whitespace before the colon (``id : Text``). YAML and
#: JSON never put a space there, so ``summary: List widgets`` is not mistaken for Dhall.
_TYPED_FIELD_RE = re.compile(
    r"\b[A-Za-z_]\w*\s+:\s+(?:Text|Natural|Integer|Double|Bool|Optional\s+\S|List\s+\S)"
)
_FOREIGN_MARKERS_RE = re.compile(
    r"^\s*package\s+\w+\s*$|^#\w+\s*:|^\s*module\s+[\w.]+\s*$|^\s*class\s+[A-Z]|\|\s*doc\s+\"|\bstd\.\w",
    re.MULTILINE,
)
_REMOTE_IMPORT_RE = re.compile(r"\bhttps?://[^\s)]+")
_ENV_IMPORT_RE = re.compile(r"\benv:(?:[A-Za-z_]\w*|\"[^\"]*\")")
_ABSOLUTE_IMPORT_RE = re.compile(r"(?<![\w/\\.~])/(?![/\\\s])[^\s()\[\]{},]+")
_HOME_IMPORT_RE = re.compile(r"(?<![\w/\\])~/[^\s()\[\]{},]+")
_RELATIVE_IMPORT_RE = re.compile(r"(?<![\w/\\])(\.\.?/[^\s()\[\]{},]+)")
_HASH_RE = re.compile(r"\bsha256:[0-9a-fA-F]{64}\b")
_ERROR_POSITION_RE = re.compile(r"(?:^|\s)([^\s:]+\.dhall):(\d+):(\d+)", re.MULTILINE)


# ===========================================================================
# Source scanning (detection, import refusal)
# ===========================================================================


def _code_only(text: str) -> str:
    """The source with comments and text literals blanked, so a scan sees only code."""
    out: List[str] = []
    index, depth = 0, 0
    length = len(text)
    while index < length:
        if depth:
            if text.startswith("{-", index):
                depth, index = depth + 1, index + 2
            elif text.startswith("-}", index):
                depth, index = depth - 1, index + 2
            else:
                out.append("\n" if text[index] == "\n" else " ")
                index += 1
            continue
        if text.startswith("{-", index):
            depth, index = 1, index + 2
            continue
        if text.startswith("--", index):
            end = text.find("\n", index)
            index = length if end < 0 else end
            continue
        if text.startswith("''", index):
            end = text.find("''", index + 2)
            index = length if end < 0 else end + 2
            out.append('""')
            continue
        if text[index] == '"':
            match = re.compile(r'"(?:\\.|[^"\\])*"').match(text, index)
            index = match.end() if match else length
            out.append('""')
            continue
        out.append(text[index])
        index += 1
    return "".join(out)


def is_dhall_source(text: str) -> bool:
    """Whether ``text`` reads as a Dhall schema expression.

    The evidence is a ``let`` binding, a typed record field (``id : Text``) or a schema record
    (``{ Type = …``), and nothing that marks the text as CUE, Pkl or Nickel.

    Args:
        text: The candidate source.

    Returns:
        ``True`` when the text is claimable by this reader.
    """
    code = _code_only(text)
    if _FOREIGN_MARKERS_RE.search(code):
        return False
    has_let = bool(_LET_RE.search(code)) and bool(re.search(r"\bin\b", code))
    return has_let or bool(_TYPED_FIELD_RE.search(code)) or bool(re.search(r"\{\s*Type\s*=", code))


def refused_imports(text: str, *, path: str) -> List[str]:
    """The imports in one file that reach outside the upload.

    A URL, an environment variable, an absolute or home-relative path, and a relative path that
    climbs above the upload's root are all refused: the evaluation may read the upload and
    nothing else.

    Args:
        text: One file's source.
        path: The file's path inside the upload (relative imports resolve against it).

    Returns:
        The refused import tokens, in source order.
    """
    code = _code_only(text)
    refused = [
        *(m.group(0) for m in _REMOTE_IMPORT_RE.finditer(code)),
        *(m.group(0) for m in _ENV_IMPORT_RE.finditer(code)),
        *(m.group(0) for m in _HOME_IMPORT_RE.finditer(code)),
    ]
    without_urls = _REMOTE_IMPORT_RE.sub(" ", code)
    refused.extend(m.group(0) for m in _ABSOLUTE_IMPORT_RE.finditer(without_urls))
    base = PurePosixPath(path).parent
    for match in _RELATIVE_IMPORT_RE.finditer(without_urls):
        depth = len(base.parts)
        for part in PurePosixPath(match.group(1)).parts:
            depth += -1 if part == ".." else (0 if part == "." else 1)
            if depth < 0:
                refused.append(match.group(1))
                break
    return refused


def _mismatch(files: Mapping[str, str], root: str, where: str) -> Optional[str]:
    """A message when the root is not Dhall at all (``FORMAT_MISMATCH``), else ``None``."""
    text = files[root]
    suffix = PurePosixPath(root).suffix.lower()
    if suffix and suffix not in DHALL_SUFFIXES and not is_dhall_source(text):
        return (
            f"{PurePosixPath(root).name} is a `{suffix}` file, not Dhall{where}. Dhall import reads "
            "`.dhall` expressions of record and union types."
        )
    if _FOREIGN_MARKERS_RE.search(_code_only(text)):
        return f"{root} is not Dhall{where}: it reads as CUE, Pkl or Nickel."
    return None


# ===========================================================================
# Projection (normal form → JSON Schema)
# ===========================================================================


def _key(node: Any) -> str:
    """A canonical spelling of an encoded expression, for structural matching."""
    return json.dumps(node, sort_keys=True, separators=(",", ":"))


def _is_type(node: Any) -> bool:
    """Whether an encoded expression in normal form is a (data) type."""
    if isinstance(node, str):
        return node in _BUILTIN_TYPES
    if not isinstance(node, list) or not node:
        return False
    if node[0] in (_RECORD_TYPE, _UNION_TYPE):
        return True
    return node[0] == _APP and len(node) == 3 and node[1] in ("List", "Optional") and _is_type(node[2])


def _is_function(node: Any) -> bool:
    return isinstance(node, list) and bool(node) and node[0] in (_LAMBDA, _PI)


def _schema_record(node: Any) -> Optional[Tuple[Any, Dict[str, Any]]]:
    """``(Type, default fields)`` when the node is a ``{ Type = …, default = … }`` record."""
    if not (isinstance(node, list) and len(node) == 2 and node[0] == _RECORD and isinstance(node[1], dict)):
        return None
    fields = node[1]
    if set(fields) != {"Type", "default"} or not _is_type(fields["Type"]):
        return None
    default = fields["default"]
    if isinstance(default, list) and len(default) == 2 and default[0] == _RECORD and isinstance(default[1], dict):
        return fields["Type"], default[1]
    return fields["Type"], {}


def _value(node: Any) -> Tuple[bool, Any]:
    """Decode a normal-form value as ``dhall-to-json`` would render it: ``(ok, value)``."""
    if isinstance(node, bool) or isinstance(node, float):
        return True, node
    if not isinstance(node, list) or not node:
        return False, None
    label = node[0]
    if label in (_NATURAL, _INTEGER) and len(node) == 2:
        return True, node[1]
    if label == _TEXT and len(node) == 2 and isinstance(node[1], str):
        return True, node[1]
    if label == _APP and len(node) == 3 and node[1] == "None":
        return True, None
    if label == _SOME and len(node) == 3:
        return _value(node[2])
    if label == _LIST:
        items = []
        for item in node[2:]:
            ok, value = _value(item)
            if not ok:
                return False, None
            items.append(value)
        return True, items
    if label == _RECORD and isinstance(node[1], dict):
        record = {}
        for name, item in node[1].items():
            ok, value = _value(item)
            if not ok:
                return False, None
            record[name] = value
        return True, record
    if label == _FIELD and len(node) == 3 and isinstance(node[1], list) and node[1][:1] == [_UNION_TYPE]:
        return True, node[2]
    if label == _APP and len(node) == 3 and isinstance(node[1], list) and node[1][:1] == [_FIELD]:
        return _value(node[2])
    return False, None


class _Projector:
    """Turns the normal form's types into ``$defs``, naming nested types structurally."""

    def __init__(self, named: Dict[str, str]) -> None:
        self.named = named
        self.definitions: Dict[str, Any] = {}
        self.limits: List[Tuple[str, str]] = []

    def schema(self, node: Any, *, location: str, own: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """One encoded type as JSON Schema; a nested type equal to a named one is a ``$ref``.

        Args:
            node: The encoded type.
            location: Where it sits, for limit locations.
            own: The definition being projected, so its root is not replaced by a self-reference.
        """
        name = self.named.get(_key(node))
        if name is not None and name != own:
            return {"$ref": f"#/$defs/{name}"}
        if isinstance(node, str) and node in _BUILTIN_TYPES:
            return dict(_BUILTIN_TYPES[node])
        if _is_function(node):
            self.limits.append(("dhall.function", location))
            return None
        if not isinstance(node, list) or not node:
            self.limits.append((f"{DHALL_FORMAT}.unrepresentable", location))
            return None
        if node[0] == _APP and len(node) == 3 and node[1] == "Optional":
            inner = self.schema(node[2], location=location)
            return None if inner is None else {"anyOf": [inner, {"type": "null"}]}
        if node[0] == _APP and len(node) == 3 and node[1] == "List":
            element = node[2]
            if (
                isinstance(element, list)
                and element[:1] == [_RECORD_TYPE]
                and set(element[1]) == {"mapKey", "mapValue"}
                and element[1]["mapKey"] == "Text"
                and self.named.get(_key(element)) is None
            ):
                value = self.schema(element[1]["mapValue"], location=location)
                return None if value is None else {"type": "object", "additionalProperties": value}
            items = self.schema(element, location=location)
            return None if items is None else {"type": "array", "items": items}
        if node[0] == _RECORD_TYPE and isinstance(node[1], dict):
            return self.record(node[1], location=location)
        if node[0] == _UNION_TYPE and isinstance(node[1], dict):
            return self.union(node[1], location=location, owner=own or location)
        self.limits.append((f"{DHALL_FORMAT}.unrepresentable", location))
        return None

    def record(
        self, fields: Mapping[str, Any], *, location: str, defaults: Optional[Mapping[str, Any]] = None
    ) -> Dict[str, Any]:
        """A record type as a closed object; an ``Optional`` field (or one with a default) is not required."""
        properties: Dict[str, Any] = {}
        required: List[str] = []
        for name, field_type in fields.items():
            schema = self.schema(field_type, location=f"{location}.{name}")
            if schema is None:
                continue
            if defaults is not None and name in defaults:
                ok, value = _value(defaults[name])
                if ok:
                    schema = {**schema, "default": value}
                else:
                    self.limits.append(("dhall.computed_default", f"{location}.{name}"))
            properties[name] = schema
            optional = isinstance(field_type, list) and field_type[:2] == [_APP, "Optional"]
            if not optional and not (defaults is not None and name in defaults):
                required.append(name)
        shape: Dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
        if required:
            shape["required"] = required
        return shape

    def union(self, alternatives: Mapping[str, Any], *, location: str, owner: str) -> Dict[str, Any]:
        """A union type: an enum of names, or one branch per alternative.

        An alternative with a payload renders (in ``dhall-to-json``) as its payload; an inline
        record payload is given its own definition, ``<Union><Alternative>``, so the canonical
        union names its variants.
        """
        if all(payload is None for payload in alternatives.values()):
            return {"enum": list(alternatives)}
        branches: List[Dict[str, Any]] = []
        for name, payload in alternatives.items():
            if payload is None:
                branches.append({"const": name})
                continue
            schema = self.schema(payload, location=f"{location}.{name}")
            if schema is None:
                continue
            if "$ref" not in schema and schema.get("type") == "object" and "properties" in schema:
                definition = f"{pascal_case(owner)}{pascal_case(name)}"
                self.definitions[definition] = schema
                schema = {"$ref": f"#/$defs/{definition}"}
            branches.append(schema)
        return {"anyOf": branches}


def _source_order(names: List[str], text: str) -> List[str]:
    """Order a normalized record's (sorted) fields by where the source first binds them."""

    def position(name: str) -> int:
        bound = re.search(rf"\blet\s+{re.escape(name)}\b", text)
        if bound:
            return bound.start()
        used = re.search(rf"(?<![\w.]){re.escape(name)}\b", text)
        return used.start() if used else len(text)

    return sorted(names, key=position)


def project(
    normal_form: Any, *, root_name: str, source: str
) -> Tuple[Dict[str, Any], List[str], List[str], List[Tuple[str, str]]]:
    """Project a normal-form expression to ``$defs``.

    A record literal's type-valued fields and schema records become definitions; its function
    fields are declared; every other field is data, listed as an instance. A root that is itself
    a type or a schema record becomes one definition named after the file.

    Args:
        normal_form: The encoded normal form (``dhall encode --json``).
        root_name: The definition name for a root that is itself a type.
        source: The root file's source, to order the definitions as written.

    Returns:
        ``(definitions, exports, instances, limits)``.
    """
    if isinstance(normal_form, list) and len(normal_form) == 2 and normal_form[0] == _RECORD and _schema_record(
        normal_form
    ) is None:
        fields: Dict[str, Any] = dict(normal_form[1])
    else:
        fields = {root_name: normal_form}

    named: Dict[str, str] = {}
    kinds: Dict[str, str] = {}
    limits: List[Tuple[str, str]] = []
    instances: List[str] = []
    for name in _source_order(list(fields), source):
        node = fields[name]
        record = _schema_record(node)
        if record is not None:
            named.setdefault(_key(record[0]), name)
            kinds[name] = "schema"
        elif _is_type(node):
            named.setdefault(_key(node), name)
            kinds[name] = "type"
        elif _is_function(node):
            limits.append(("dhall.function", name))
        else:
            instances.append(name)

    projector = _Projector(named)
    exports: List[str] = []
    for name in _source_order(list(kinds), source):
        node = fields[name]
        if kinds[name] == "schema":
            type_node, defaults = _schema_record(node) or (None, {})
            if isinstance(type_node, list) and type_node[:1] == [_RECORD_TYPE]:
                schema: Optional[Dict[str, Any]] = projector.record(type_node[1], location=name, defaults=defaults)
            else:
                schema = projector.schema(type_node, location=name, own=name)
        else:
            schema = projector.schema(node, location=name, own=name)
        if schema is None:
            continue
        projector.definitions[name] = schema
        exports.append(name)
    limits.extend(projector.limits)
    ordered = {name: projector.definitions[name] for name in exports}
    ordered.update({k: v for k, v in projector.definitions.items() if k not in ordered})
    return ordered, exports, instances, limits


# ===========================================================================
# Reading
# ===========================================================================


def _classify(failure: ToolFailure, files: Mapping[str, str], *, where: str) -> TypedConfigParseError:
    """Turn ``dhall``'s error output into a taxonomy-coded rejection."""
    output = re.sub(r"^dhall:\s*$", "", failure.output, flags=re.MULTILINE).strip()
    output = output.replace('Use "dhall --explain" for detailed errors', "").strip()
    detail = first_lines(output, 4)
    if re.search(
        r"Missing file|Missing environment variable|Cyclic import|Remote import|HostCannotConnect|"
        r"Import resolution is disabled|Invalid path|Missing `missing`|cannot be resolved",
        output,
    ):
        return TypedConfigParseError(
            f"A Dhall import cannot be resolved{where} — {detail}", code="INPUT_REFERENCE_UNRESOLVED"
        )
    if "Invalid input" in output:
        position = _ERROR_POSITION_RE.search(output)
        source = None
        if position:
            name = PurePosixPath(position.group(1)).name
            source = next((text for path, text in files.items() if PurePosixPath(path).name == name), None)
        code = syntax_error_code(source)
        problem = "ends in the middle of an expression" if code == "INPUT_TRUNCATED" else "is not valid Dhall"
        return TypedConfigParseError(f"The Dhall source {problem}{where} — {detail}", code=code)
    return TypedConfigParseError(
        f"The Dhall expression does not type-check{where} — {detail}", code="INPUT_SEMANTIC_INVALID"
    )


def _read(files: Mapping[str, str], root: str, *, source_label: Optional[str]) -> TypedConfigDocument:
    """Guard, normalize, encode and project a Dhall upload."""
    where = f" ({source_label})" if source_label else ""
    guard_input(files, label=_LABEL, where=where)
    message = _mismatch(files, root, where)
    if message is not None:
        raise TypedConfigParseError(message, code="FORMAT_MISMATCH")

    limits: List[Tuple[str, str]] = []
    for name, text in sorted(files.items()):
        refused = refused_imports(text, path=name)
        if refused:
            raise TypedConfigParseError(
                f"{name} imports {', '.join(f'`{token}`' for token in refused[:3])}{where}. The "
                "evaluation sandbox reads only the uploaded files — URLs, environment variables "
                "and paths outside the upload are refused. Upload the imported files with it.",
                code="INPUT_REFERENCE_UNRESOLVED",
            )
        for _ in _HASH_RE.finditer(_code_only(text)):
            limits.append(("dhall.integrity_check", PurePosixPath(name).name))

    with workspace(files) as directory:
        normalized = run_typed_config_tool(
            DHALL_TOOL_KEY, ["--plain", "--no-cache", "--file", root], cwd=directory, label=_LABEL, where=where
        )
        if isinstance(normalized, ToolFailure):
            raise _classify(normalized, files, where=where)
        encoded = run_typed_config_tool(
            DHALL_TOOL_KEY,
            ["encode", "--json"],
            cwd=directory,
            label=_LABEL,
            where=where,
            stdin=normalized.stdout,
        )
        if isinstance(encoded, ToolFailure):
            raise TypedConfigParseError(
                f"dhall encode failed on the normal form{where} — {first_lines(encoded.output, 3)}",
                code="INTERNAL_ADAPTER_FAULT",
            )
    try:
        normal_form = json.loads(encoded.stdout)
    except ValueError as exc:
        raise TypedConfigParseError(
            f"dhall encode returned something other than JSON{where}.", code="INTERNAL_ADAPTER_FAULT"
        ) from exc

    root_name = pascal_case(PurePosixPath(root).stem)
    definitions, exports, instances, found = project(normal_form, root_name=root_name, source=files[root])
    limits.extend(found)
    if not exports:
        raise TypedConfigParseError(
            f"{root} defines no record or union type{where}, so there is no schema to import. A "
            "Dhall schema is an expression whose fields are types (`{ Order = { id : Text } }`) or "
            "schema records (`{ Type = …, default = … }`).",
            code="INPUT_SEMANTIC_INVALID",
        )
    identity = next(
        (name for name in exports if "properties" in definitions.get(name, {})), exports[0]
    )
    return TypedConfigDocument(
        language=DHALL_FORMAT,
        root=root,
        files=tuple(sorted(files)),
        tool_version="",
        schema={"$defs": definitions},
        exports=tuple(exports),
        limits=tuple(limits),
        instances=tuple(instances),
        identity=identity,
        sources=dict(files),
    )


def _file_name(source_label: Optional[str]) -> str:
    """The name a pasted or uploaded file is written under (it keeps the ``.dhall`` suffix)."""
    name = PurePosixPath(source_label or "").name
    return name if name else "schema.dhall"


def parse_dhall(raw: str, *, source_label: Optional[str] = None) -> TypedConfigDocument:
    """Normalize one Dhall file and project its types.

    Args:
        raw: The file's source.
        source_label: The file's name, for the tool and for messages.

    Returns:
        The parsed :class:`~app.typed_config_common.TypedConfigDocument`.

    Raises:
        TypedConfigParseError: With the intake taxonomy code the failure belongs to.
    """
    name = _file_name(source_label)
    return _read({name: raw}, name, source_label=source_label)


def parse_dhall_fileset(
    members: Mapping[str, str], *, root: str, source_label: Optional[str] = None
) -> TypedConfigDocument:
    """Normalize a Dhall package — a root file and the files it imports.

    Args:
        members: Relative path → source.
        root: The root file's path (conventionally ``package.dhall``).
        source_label: Fallback label for messages.

    Returns:
        The parsed document.

    Raises:
        TypedConfigParseError: With the intake taxonomy code the failure belongs to.
    """
    if root not in members:
        raise TypedConfigParseError(
            f"The Dhall set's root file {root!r} is missing.", code="INPUT_SEMANTIC_INVALID"
        )
    return _read(dict(members), root, source_label=source_label or root)
