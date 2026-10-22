"""CUE reader — the CUE third of FMT-8.5 (#5466).

CUE schemas are *definitions* (``#Order: { … }``) whose constraints — disjunctions, bounds,
regular expressions, closedness — are checked by CUE's own evaluator. This reader lets that
evaluator do the reading. In the sandboxed toolchain runner it runs the bundled ``cue`` twice:

1. ``cue export`` — evaluates the upload exactly as a user would. A conflict, an incomplete
   value or a syntax error rejects the import with the reason CUE gave; a clean run names the
   concrete values the file defines, which were validated but are data, not schema.
2. ``cue export --out jsonschema -e '{"Order": #Order, …}'`` — CUE's own JSON Schema
   generator, given every definition the root package declares, writes one ``$defs`` entry per
   definition (and per definition of an imported package that one refers to).

The JSON Schema is lightly normalized (:func:`simplify_schema` merges the ``allOf`` CUE emits
for ``int & >=0`` and folds a default branch back into its disjunction) and handed to the shared
JSON Schema translator by :mod:`app.typed_config_normalizer`.

**Declared limits.** CUE's lattice unification exceeds JSON Schema. Comprehensions, conditional
fields, ``let`` bindings, hidden fields, interpolations, defaults and validators the generator
cannot express are found in the source (:func:`scan_limits`) and declared — and a field or
definition whose projection would only be an approximation of a computed value is left out
rather than modelled wrongly.

**Module layout.** A CUE module is a directory with a ``cue.mod/module.cue`` file and one
directory per package. An upload may arrive in that shape or flat (a ``cue.mod`` file beside the
package files, as an intake fileset holds them); :func:`layout_module` lays a flat upload out as
the module CUE expects before the tool runs.
"""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from .typed_config_common import (
    MODEL_PARTIAL_SUFFIXES,
    ToolFailure,
    TypedConfigDocument,
    TypedConfigParseError,
    first_lines,
    guard_input,
    model_limit_details,
    run_typed_config_tool,
    syntax_error_code,
    workspace,
)

__all__ = [
    "CUE_FORMAT",
    "CUE_SUFFIXES",
    "CUE_TOOL_KEY",
    "LIMIT_DETAILS",
    "PARTIAL_LIMITS",
    "is_cue_source",
    "layout_module",
    "parse_cue",
    "parse_cue_fileset",
    "scan_limits",
    "simplify_schema",
    "strip_conditionals",
]

#: The format key the reader, normalizer and adapter share.
CUE_FORMAT = "cue"

#: Registry key of the bundled ``cue`` CLI (declared in :mod:`app.toolchain_packaging`).
CUE_TOOL_KEY = "cue"

#: The file suffixes a CUE upload uses.
CUE_SUFFIXES: Tuple[str, ...] = (".cue",)

#: The display name used in messages.
_LABEL = "CUE"

#: Every construct the reader declares rather than models, with the sentence that says what
#: happens to it.
LIMIT_DETAILS: Dict[str, str] = {
    "cue.comprehension": (
        "A comprehension (`[for x in xs {…}]`) computes a value from other values during "
        "evaluation. JSON Schema cannot say how a field is computed, so the field is left out of "
        "the model."
    ),
    "cue.conditional_field": (
        "A conditional field (`if tier == \"paid\" { seats: … }`) exists only when another field "
        "has a given value. The definition's unconditional fields are modelled; the conditional "
        "ones, and the condition, are not. A definition that is nothing but its conditions is "
        "left out."
    ),
    "cue.let_binding": (
        "A `let` binding is a name that exists only during evaluation. Constraints written in "
        "terms of it keep the bound value CUE resolved; the binding itself is not modelled."
    ),
    "cue.hidden_field": (
        "A hidden field (`_secret`) and a hidden definition are private to the CUE package and "
        "are never exported. They are not modelled."
    ),
    "cue.interpolation": (
        "An interpolated string (`\"\\(host):\\(port)\"`) is computed from other fields. The field "
        "is left out of the model rather than typed as any string."
    ),
    "cue.default": (
        "A default (`*\"new\"`) is applied by CUE's evaluation; the JSON Schema CUE generates does "
        "not carry it, so the field is modelled with its type and without the default."
    ),
    "cue.builtin_validator": (
        "A validator from CUE's standard library other than the rune and item-count bounds "
        "(`strings.HasPrefix`, `net.IPv4`, `time.Time`, …) has no JSON Schema keyword. The "
        "field's type is modelled; the validator is not."
    ),
    "cue.bytes": (
        "A `bytes` value has no JSON Schema type. The field is modelled as accepting any value."
    ),
    "cue.label_reference": (
        "A pattern constraint that refers to the label it matches (`[Name=string]: {name: Name}`) "
        "ties a value to its key. The map and its value type are modelled; the tie is not."
    ),
}

LIMIT_DETAILS.update(model_limit_details(CUE_FORMAT, _LABEL))

#: The limits whose construct is still modelled, with only a detail lost. The rest leave a field
#: or definition out of the model.
PARTIAL_LIMITS = frozenset(
    {
        *(f"{CUE_FORMAT}.{suffix}" for suffix in MODEL_PARTIAL_SUFFIXES),
        "cue.conditional_field",
        "cue.let_binding",
        "cue.default",
        "cue.builtin_validator",
        "cue.bytes",
        "cue.label_reference",
    }
)

#: CUE standard-library validators the JSON Schema generator expresses as keywords.
_EXPRESSIBLE_BUILTINS = frozenset(
    {"strings.MinRunes", "strings.MaxRunes", "list.MinItems", "list.MaxItems", "list.UniqueItems"}
)

_PACKAGE_RE = re.compile(r"^\s*package\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", re.MULTILINE)
_DEFINITION_RE = re.compile(r"^#([A-Za-z][A-Za-z0-9_]*)\s*:", re.MULTILINE)
_HIDDEN_DEFINITION_RE = re.compile(r"^#?_[A-Za-z0-9_]*\s*:", re.MULTILINE)
_FIELD_RE = re.compile(r"^\s*(#?[A-Za-z_$][A-Za-z0-9_$]*|\"[^\"]*\")\s*[?!]?\s*:")
_IMPORT_ERROR_RE = re.compile(
    r"cannot find package|package .* (?:not found|is not part of)|import failed|"
    r"cannot determine package|no dependency found",
    re.IGNORECASE,
)
_SYNTAX_ERROR_RE = re.compile(
    r"expected .+, found|illegal character|string literal not terminated|"
    r"missing ',' in|unexpected|imports must appear before",
    re.IGNORECASE,
)
_ERROR_POSITION_RE = re.compile(r"\./?([^\s:]+\.cue):(\d+):(\d+)")
_BUILTIN_CALL_RE = re.compile(r"\b(strings|list|math|net|time|struct|regexp|uuid|encoding)\.([A-Z]\w*)\s*\(")


# ===========================================================================
# Detection
# ===========================================================================


def is_cue_source(text: str) -> bool:
    """Whether ``text`` reads as a CUE file that declares schema definitions.

    The evidence is a ``package`` clause together with a top-level ``#Definition:`` — a ``#``
    line on its own is a comment in YAML, TOML and shell, so the clause is what tells CUE apart.

    Args:
        text: The candidate source.

    Returns:
        ``True`` when the text is claimable by this reader.
    """
    return bool(_PACKAGE_RE.search(text) and _DEFINITION_RE.search(text))


def _package_of(text: str) -> Optional[str]:
    """The ``package`` clause's name, or ``None`` for a file without one."""
    match = _PACKAGE_RE.search(text)
    return match.group(1) if match else None


def _mismatch(files: Mapping[str, str], root: str, where: str) -> Optional[str]:
    """A message when the root is not CUE at all (``FORMAT_MISMATCH``), else ``None``."""
    text = files[root]
    suffix = PurePosixPath(root).suffix.lower()
    if suffix and suffix not in CUE_SUFFIXES and suffix != ".mod":
        if not is_cue_source(text):
            return (
                f"{PurePosixPath(root).name} is a `{suffix}` file, not CUE{where}. CUE import "
                "reads `.cue` files that declare `#Definitions`."
            )
    if _package_of(text) is None and not any(_FIELD_RE.match(line) for line in text.splitlines()):
        return f"{root} has no CUE fields or definitions{where}, so it is not a CUE file."
    return None


# ===========================================================================
# Module layout
# ===========================================================================


def layout_module(files: Mapping[str, str], root: str) -> Tuple[Dict[str, str], str]:
    """Lay a flat upload out as the module directory CUE expects.

    A real module upload (``cue.mod/module.cue``, one directory per package) is returned as is.
    A flat one — a ``cue.mod`` *file* beside the package files — has its module file moved to
    ``cue.mod/module.cue`` and every ``.cue`` file whose package differs from the root's moved into
    a directory named after its package, which is where ``import "<module>/<package>"`` looks.

    Args:
        files: Relative path → source.
        root: The root file's path.

    Returns:
        ``(laid-out files, root path)``.
    """
    if "cue.mod" not in {PurePosixPath(name).name for name in files} or any(
        name.startswith("cue.mod/") for name in files
    ):
        return dict(files), root
    root_dir = PurePosixPath(root).parent
    root_package = _package_of(files[root])
    laid: Dict[str, str] = {}
    for name, text in files.items():
        path = PurePosixPath(name)
        if path.name == "cue.mod":
            laid[str(path.parent / "cue.mod" / "module.cue")] = text
            continue
        package = _package_of(text) if path.suffix == ".cue" else None
        if path.parent == root_dir and package and root_package and package != root_package:
            laid[str(path.parent / package / path.name)] = text
            continue
        laid[name] = text
    return laid, root


def _package_files(files: Mapping[str, str], root: str) -> List[str]:
    """The root's package: the root file first, then same-package files beside it, sorted."""
    root_path = PurePosixPath(root)
    package = _package_of(files[root])
    siblings = sorted(
        name
        for name, text in files.items()
        if name != root
        and PurePosixPath(name).parent == root_path.parent
        and PurePosixPath(name).suffix == ".cue"
        and package is not None
        and _package_of(text) == package
    )
    return [root, *siblings]


# ===========================================================================
# Declared limits (a source scan — CUE's own output does not say what it dropped)
# ===========================================================================


def _strip_comments(line: str) -> str:
    """The line without a trailing ``//`` comment (outside string literals)."""
    in_string = False
    index = 0
    while index < len(line):
        char = line[index]
        if char == "\\" and in_string:
            index += 2
            continue
        if char == '"':
            in_string = not in_string
        elif not in_string and line.startswith("//", index):
            return line[:index]
        index += 1
    return line


def _definition_blocks(text: str) -> List[Tuple[str, List[str]]]:
    """Split a file into its top-level definitions: ``(name, body lines)`` in source order.

    A definition starts at a column-0 ``#Name:`` and runs until the next column-0 line that is
    not a closing brace or a comment.
    """
    blocks: List[Tuple[str, List[str]]] = []
    current: Optional[Tuple[str, List[str]]] = None
    for raw in text.splitlines():
        line = _strip_comments(raw)
        match = _DEFINITION_RE.match(line)
        if match:
            current = (match.group(1), [line[match.end():]])
            blocks.append(current)
            continue
        starts_top_level = bool(line) and not line[0].isspace() and not line.startswith("}")
        if starts_top_level and line.strip():
            current = None
        elif current is not None:
            current[1].append(line)
    return blocks


def _field_name(line: str) -> Optional[str]:
    """The label a field line declares, without quotes or a ``?`` / ``!`` marker."""
    match = _FIELD_RE.match(line)
    return match.group(1).strip('"') if match else None


def scan_limits(text: str) -> Tuple[List[Tuple[str, str]], Dict[str, Set[str]], Set[str]]:
    """Find the constructs JSON Schema cannot carry, per definition and field.

    Args:
        text: One CUE file's source.

    Returns:
        ``(limits, dropped fields, conditional definitions)``: every ``(construct, location)``
        found; ``definition → fields`` whose projection would only approximate a computed value
        (comprehensions and interpolations), which the reader removes; and the definitions that
        contain conditional fields.
    """
    limits: List[Tuple[str, str]] = []
    dropped: Dict[str, Set[str]] = {}
    conditional: Set[str] = set()

    for match in _HIDDEN_DEFINITION_RE.finditer(text):
        limits.append(("cue.hidden_field", match.group(0).rstrip(":").strip()))

    for name, lines in _definition_blocks(text):
        depth = 0
        for line in lines:
            stripped = line.strip()
            field = _field_name(line) if depth <= 1 else None
            location = f"{name}.{field}" if field else name
            if depth <= 1 and re.match(r"if\s", stripped):
                limits.append(("cue.conditional_field", name))
                conditional.add(name)
            if depth <= 1 and re.match(r"let\s+\w+\s*=", stripped):
                limits.append(("cue.let_binding", name))
            if depth <= 1 and field and field.startswith("_"):
                limits.append(("cue.hidden_field", location))
            if re.search(r"[\[{]\s*for\s+\w+(\s*,\s*\w+)?\s+in\s", stripped):
                limits.append(("cue.comprehension", location))
                if field:
                    dropped.setdefault(name, set()).add(field)
            if "\\(" in stripped:
                limits.append(("cue.interpolation", location))
                if field:
                    dropped.setdefault(name, set()).add(field)
            if re.search(r"(^|[|:]\s*)\*", stripped):
                limits.append(("cue.default", location))
            if re.search(r"\bbytes\b", stripped) and field:
                limits.append(("cue.bytes", location))
            if re.search(r"\[\s*[A-Za-z_]\w*\s*=", stripped):
                limits.append(("cue.label_reference", location))
            for package, function in _BUILTIN_CALL_RE.findall(stripped):
                if f"{package}.{function}" not in _EXPRESSIBLE_BUILTINS:
                    limits.append(("cue.builtin_validator", location))
            depth += stripped.count("{") - stripped.count("}")
    return limits, dropped, conditional


def strip_conditionals(text: str) -> str:
    """The source with every conditional block inside a definition removed.

    CUE's JSON Schema generator cannot express a definition that contains an ``if`` block, and
    gives up on the whole definition. Projecting from this copy keeps the definition's
    unconditional fields; the evaluation that validates the upload always runs on the original.

    Args:
        text: One CUE file's source.

    Returns:
        The same source with each ``if … { … }`` block at a definition's top level blanked out
        (line numbers are kept, so tool messages still point at the right place).
    """
    out: List[str] = []
    in_definition = False
    depth = 0
    skipping = 0
    for raw in text.splitlines():
        line = _strip_comments(raw)
        if _DEFINITION_RE.match(line):
            in_definition, depth = True, 0
        elif line and not line[0].isspace() and not line.startswith("}") and line.strip():
            in_definition = False
        opened, closed = line.count("{"), line.count("}")
        if skipping:
            skipping += opened - closed
            out.append("")
            continue
        if in_definition and depth == 1 and re.match(r"\s*if\s", line) and opened > closed:
            skipping = opened - closed
            out.append("")
            continue
        depth += opened - closed
        out.append(raw)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


# ===========================================================================
# JSON Schema normalization
# ===========================================================================

#: Keywords a merged scalar ``allOf`` may carry (anything else keeps the ``allOf``).
_SCALAR_KEYWORDS = frozenset(
    {
        "type",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "minItems",
        "maxItems",
        "uniqueItems",
        "items",
        "prefixItems",
        "description",
    }
)


def _merge_all_of(members: List[Any]) -> Optional[Dict[str, Any]]:
    """Merge an ``allOf`` of keyword-only schemas into one, or ``None`` when it cannot be.

    ``int & >=0`` arrives as ``allOf: [{type: number}, {type: integer, minimum: 0}]``; a
    non-empty list as ``allOf: [{prefixItems: [true]}, {type: array, items: …, minItems: 1}]``.
    Both merge losslessly. A ``$ref`` or an object shape does not merge here.
    """
    merged: Dict[str, Any] = {}
    for member in members:
        if member is True:
            continue
        if not isinstance(member, dict) or not set(member) <= _SCALAR_KEYWORDS:
            return None
        for key, value in member.items():
            if key == "type":
                previous = merged.get("type")
                if previous is None or previous == value or (previous, value) == ("number", "integer"):
                    merged["type"] = value
                elif (previous, value) == ("integer", "number"):
                    continue
                else:
                    return None
            elif key == "prefixItems":
                if not all(item is True or item == {} for item in value):
                    return None
                merged["minItems"] = max(merged.get("minItems", 0), len(value))
            elif key in ("minimum", "minLength", "minItems", "exclusiveMinimum"):
                merged[key] = max(merged.get(key, value), value)
            elif key in ("maximum", "maxLength", "maxItems", "exclusiveMaximum"):
                merged[key] = min(merged.get(key, value), value)
            elif key in merged and merged[key] != value:
                return None
            else:
                merged[key] = value
    if "prefixItems" not in merged and "minItems" in merged and "type" not in merged:
        merged["type"] = "array"
    return merged


def _subsumes(schema: Any, value: Any, definitions: Mapping[str, Any]) -> bool:
    """Whether ``value`` is already one of the values ``schema`` accepts (for a default branch)."""
    if not isinstance(schema, dict):
        return False
    ref = schema.get("$ref")
    if isinstance(ref, str):
        return _subsumes(definitions.get(ref.rsplit("/", 1)[-1]), value, definitions)
    if isinstance(schema.get("enum"), list):
        return value in schema["enum"]
    if "const" in schema:
        return schema["const"] == value
    kind = schema.get("type")
    checks = {
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "array": lambda v: isinstance(v, list),
    }
    return bool(kind in checks and checks[kind](value))


def simplify_schema(node: Any, definitions: Mapping[str, Any]) -> Any:
    """Normalize the JSON Schema CUE's generator writes into the shape the translator reads.

    * ``true`` (any value) becomes ``{}``;
    * an ``allOf`` of keyword-only members is merged (:func:`_merge_all_of`);
    * a ``$ref`` beside an object shape (an embedded or narrowed definition) becomes an
      ``allOf`` of the reference and the shape, which the shared model merges into one record;
    * a disjunction with a default branch the other branch already accepts
      (``#OrderStatus | *"new"``) folds back to that branch.

    Args:
        node: A JSON Schema node.
        definitions: The document's ``$defs``, to resolve a default branch's reference.

    Returns:
        The simplified node.
    """
    if node is True:
        return {}
    if isinstance(node, list):
        return [simplify_schema(item, definitions) for item in node]
    if not isinstance(node, dict):
        return node
    out = {key: simplify_schema(value, definitions) for key, value in node.items()}
    if isinstance(out.get("properties"), dict):
        out["properties"] = {
            name: simplify_schema(value, definitions) for name, value in node["properties"].items()
        }

    if isinstance(out.get("allOf"), list):
        merged = _merge_all_of(out["allOf"])
        if merged is not None:
            rest = {key: value for key, value in out.items() if key != "allOf"}
            out = {**merged, **rest}

    if isinstance(out.get("$ref"), str) and ({"properties", "type"} & set(out)):
        ref = {"$ref": out.pop("$ref")}
        description = out.pop("description", None)
        out = {"allOf": [ref, out]} if out.get("properties") else ref
        if description:
            out["description"] = description

    for keyword in ("anyOf", "oneOf"):
        branches = out.get(keyword)
        if isinstance(branches, list) and len(branches) == 2:
            first, second = branches
            for kept, default in ((first, second), (second, first)):
                if isinstance(default, dict) and set(default) == {"const"} and _subsumes(
                    kept, default["const"], definitions
                ):
                    rest = {key: value for key, value in out.items() if key != keyword}
                    out = {**kept, **rest} if isinstance(kept, dict) else rest
                    break
    return out


def _drop_fields(schema: Dict[str, Any], fields: Iterable[str]) -> Dict[str, Any]:
    """Remove computed fields from a definition's object shape (wherever its ``allOf`` put it)."""
    names = set(fields)

    def prune(node: Any) -> Any:
        if not isinstance(node, dict):
            return node
        node = dict(node)
        if isinstance(node.get("properties"), dict):
            node["properties"] = {k: v for k, v in node["properties"].items() if k not in names}
            if isinstance(node.get("required"), list):
                node["required"] = [name for name in node["required"] if name not in names]
        if isinstance(node.get("allOf"), list):
            node["allOf"] = [prune(member) for member in node["allOf"]]
        return node

    return prune(schema)


def _drop_artifact_refs(node: Any, artifacts: Set[str]) -> Any:
    """Remove references to the generator's pseudo-definitions, collapsing what they leave.

    For a pattern constraint that refers to its own label (``[Name=string]: {name: Name}``)
    CUE's JSON Schema generator emits a ``$ref`` to a definition named after the *field*, which
    describes nothing. The tie is declared (``cue.label_reference``); the property that would
    point at the pseudo-definition is dropped, and an ``allOf`` left with only its base
    reference collapses to that reference.
    """
    if isinstance(node, list):
        return [_drop_artifact_refs(item, artifacts) for item in node]
    if not isinstance(node, dict):
        return node
    out = {key: _drop_artifact_refs(value, artifacts) for key, value in node.items()}
    properties = out.get("properties")
    if isinstance(properties, dict):
        dropped = {
            name
            for name, schema in properties.items()
            if isinstance(schema, dict) and str(schema.get("$ref", "")).rsplit("/", 1)[-1] in artifacts
        }
        if dropped:
            out["properties"] = {k: v for k, v in properties.items() if k not in dropped}
            if isinstance(out.get("required"), list):
                out["required"] = [name for name in out["required"] if name not in dropped]
    members = out.get("allOf")
    if isinstance(members, list):
        kept = [
            member
            for member in members
            if not (isinstance(member, dict) and member.get("type") == "object" and not member.get("properties"))
        ]
        if len(kept) == 1 and set(out) == {"allOf"}:
            return kept[0]
        out["allOf"] = kept
    return out


def _is_empty_projection(schema: Any) -> bool:
    """Whether CUE's generator could say nothing about a definition (``{}`` or a bare comment)."""
    return isinstance(schema, dict) and not (set(schema) - {"description", "$comment"})


# ===========================================================================
# Reading
# ===========================================================================


def _classify(failure: ToolFailure, files: Mapping[str, str], *, where: str) -> TypedConfigParseError:
    """Turn ``cue``'s error output into a taxonomy-coded rejection."""
    output = failure.output
    detail = first_lines(output)
    if _IMPORT_ERROR_RE.search(output):
        return TypedConfigParseError(
            f"A CUE import cannot be resolved{where} — {detail}", code="INPUT_REFERENCE_UNRESOLVED"
        )
    if _SYNTAX_ERROR_RE.search(output):
        position = _ERROR_POSITION_RE.search(output)
        source = None
        if position:
            name = position.group(1)
            source = next((text for path, text in files.items() if path.endswith(name)), None)
        code = syntax_error_code(source) if "EOF" in output else "INPUT_MALFORMED"
        problem = "ends in the middle of a declaration" if code == "INPUT_TRUNCATED" else "is not valid CUE"
        return TypedConfigParseError(f"The CUE source {problem}{where} — {detail}", code=code)
    return TypedConfigParseError(
        f"CUE evaluation failed{where} — {detail}", code="INPUT_SEMANTIC_INVALID"
    )


def _read(files: Mapping[str, str], root: str, *, source_label: Optional[str]) -> TypedConfigDocument:
    """Guard, lay out, evaluate and project a CUE upload."""
    where = f" ({source_label})" if source_label else ""
    guard_input(files, label=_LABEL, where=where)
    message = _mismatch(files, root, where)
    if message is not None:
        raise TypedConfigParseError(message, code="FORMAT_MISMATCH")

    laid, laid_root = layout_module(files, root)
    package_files = _package_files(laid, laid_root)
    root_dir = PurePosixPath(laid_root).parent
    args = [str(PurePosixPath(name).relative_to(root_dir)) for name in package_files]

    exports: List[str] = []
    limits: List[Tuple[str, str]] = []
    dropped: Dict[str, Set[str]] = {}
    conditional: Set[str] = set()
    for name in package_files:
        exports.extend(n for n in _DEFINITION_RE.findall(laid[name]) if n not in exports)
        found, computed, conditions = scan_limits(laid[name])
        limits.extend(found)
        for definition, fields in computed.items():
            dropped.setdefault(definition, set()).update(fields)
        conditional |= conditions

    with workspace(laid) as directory:
        cwd = directory.joinpath(*root_dir.parts) if root_dir.parts else directory
        evaluated = run_typed_config_tool(
            CUE_TOOL_KEY, ["export", "--out", "json", *args], cwd=cwd, label=_LABEL, where=where
        )
        if isinstance(evaluated, ToolFailure):
            raise _classify(evaluated, laid, where=where)
        try:
            data = json.loads(evaluated.stdout or "{}")
        except ValueError as exc:
            raise TypedConfigParseError(
                f"cue export returned something other than JSON{where}.",
                code="INTERNAL_ADAPTER_FAULT",
            ) from exc
        if not exports:
            raise TypedConfigParseError(
                f"{root} declares no `#Definition`{where}, so there is no schema to import. A CUE "
                "schema is written as definitions (`#Order: { … }`).",
                code="INPUT_SEMANTIC_INVALID",
            )
        if conditional:
            # Re-lay the package without its conditional blocks for the projection only.
            for name in package_files:
                directory.joinpath(*PurePosixPath(name).parts).write_text(
                    strip_conditionals(laid[name]), encoding="utf-8"
                )
        expression = "{" + ", ".join(f'"{name}": #{name}' for name in exports) + "}"
        projected = run_typed_config_tool(
            CUE_TOOL_KEY,
            ["export", "--out", "jsonschema", "-e", expression, *args],
            cwd=cwd,
            label=_LABEL,
            where=where,
        )
        if isinstance(projected, ToolFailure):
            raise _classify(projected, laid, where=where)
        try:
            raw_schema = json.loads(projected.stdout)
        except ValueError as exc:
            raise TypedConfigParseError(
                f"cue export --out jsonschema returned something other than JSON{where}.",
                code="INTERNAL_ADAPTER_FAULT",
            ) from exc

    raw_defs = raw_schema.get("$defs") if isinstance(raw_schema, dict) else None
    raw_defs = raw_defs if isinstance(raw_defs, dict) else {}
    declared = {name for text in laid.values() for name in _DEFINITION_RE.findall(text)}
    artifacts = {name for name in raw_defs if name not in declared}
    # A pattern at a definition's own top level names its pseudo-definition after the
    # definition itself, so there the definition's own name is an artifact reference too.
    tied = {location.split(".", 1)[0] for construct, location in limits if construct == "cue.label_reference"}
    raw_defs = {
        name: _drop_artifact_refs(schema, artifacts | ({name} if name in tied else set()))
        for name, schema in raw_defs.items()
        if name not in artifacts
    }
    definitions: Dict[str, Any] = {}
    kept_exports: List[str] = []
    for name in [*exports, *(n for n in raw_defs if n not in exports)]:
        if name not in raw_defs:
            continue
        schema = simplify_schema(raw_defs[name], raw_defs)
        if name in dropped:
            schema = _drop_fields(schema, dropped[name])
        if _is_empty_projection(schema) and (name in conditional or name in exports):
            if name not in conditional:
                limits.append(("cue.unrepresentable", name))
            continue
        definitions[name] = schema
        if name in exports:
            kept_exports.append(name)

    identity = next(
        (
            name
            for name in kept_exports
            if "properties" in definitions[name] or "allOf" in definitions[name]
        ),
        kept_exports[0] if kept_exports else None,
    )
    return TypedConfigDocument(
        language=CUE_FORMAT,
        root=root,
        files=tuple(sorted(files)),
        tool_version="",
        schema={"$schema": raw_schema.get("$schema"), "$defs": definitions},
        exports=tuple(kept_exports),
        limits=tuple(limits),
        instances=tuple(sorted(data)) if isinstance(data, dict) else (),
        identity=identity,
        sources=dict(files),
    )


def _file_name(source_label: Optional[str]) -> str:
    """The name a pasted or uploaded file is written under (it keeps the ``.cue`` suffix)."""
    name = PurePosixPath(source_label or "").name
    return name if name else "schema.cue"


def parse_cue(raw: str, *, source_label: Optional[str] = None) -> TypedConfigDocument:
    """Evaluate one CUE file and project its definitions.

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


def parse_cue_fileset(
    members: Mapping[str, str], *, root: str, source_label: Optional[str] = None
) -> TypedConfigDocument:
    """Evaluate a CUE module — a root package plus the packages it imports.

    Args:
        members: Relative path → source (``cue.mod`` included).
        root: The root file's path; its package's definitions are the model.
        source_label: Fallback label for messages.

    Returns:
        The parsed document.

    Raises:
        TypedConfigParseError: With the intake taxonomy code the failure belongs to.
    """
    if root not in members:
        raise TypedConfigParseError(
            f"The CUE set's root file {root!r} is missing.", code="INPUT_SEMANTIC_INVALID"
        )
    return _read(dict(members), root, source_label=source_label or root)
