"""TypeScript type-declaration reader — FMT-8.1 (#5462).

The largest population of hand-written schemas in the world is TypeScript ``interface`` and
``type`` declarations. This module reads them, and it does so with the TypeScript compiler
itself rather than a Python approximation of the language: the bundled
``typescript-types-extractor`` tool (``apiome-rest/toolchain/typescript-types-extract.mjs``)
runs the compiler API in the Node toolchain sandbox — the same runner and packaging rule as the
AsyncAPI parser — and returns a *neutral JSON AST* of every declaration. The Python half
(:mod:`app.typescript_types_normalizer`) maps that AST onto the canonical model.

What lives here:

* :class:`TsDocument` — one read module (or module set): its declarations as the extractor
  reported them, which of them the root module exports, and the compiler version that read it.
* :data:`LIMIT_DETAILS` / :class:`LimitRecorder` — the declared parsing limits. FMT-8.1 puts
  conditional, mapped and template-literal types, unresolved generics and declaration merging
  out of scope, and requires each to be *declared* rather than flattened to ``any``; every key
  here is one such construct, worded once and reused by the adapter's capability declaration,
  the format registry and the coverage ledger.
* :func:`parse_typescript_types` / :func:`parse_typescript_types_fileset` — the readers, which
  classify every rejection with an intake taxonomy code before the tool is even run where they
  can (encoding, size, a module that belongs to a schema-builder library).
* :func:`is_typescript_types` — the cheap, subprocess-free detection sniff.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .toolchain_runner import ToolchainError, ToolNotAvailableError, run_tool_blocking

__all__ = [
    "LIMIT_DETAILS",
    "MAX_TYPESCRIPT_BYTES",
    "SCHEMA_LIBRARY_MODULES",
    "TYPESCRIPT_SUFFIXES",
    "TYPESCRIPT_TYPES_TOOL_KEY",
    "LimitRecorder",
    "TsDocument",
    "TsLimit",
    "TsParseError",
    "imported_schema_library",
    "is_typescript_types",
    "parse_typescript_types",
    "parse_typescript_types_fileset",
]

#: Registry key of the bundled extractor (declared in :mod:`app.toolchain_packaging`).
TYPESCRIPT_TYPES_TOOL_KEY = "typescript-types-extractor"

#: File suffixes this reader claims. ``.d.ts`` is listed explicitly so the intake picker shows
#: it, though ``.ts`` already matches it.
TYPESCRIPT_SUFFIXES: Tuple[str, ...] = (".d.ts", ".ts", ".d.mts", ".mts", ".d.cts", ".cts")

#: The largest module set (all members together) the reader will hand the compiler, in bytes.
#: A type-declaration file is small; a few megabytes is a generated bundle, not a model.
MAX_TYPESCRIPT_BYTES = 4 * 1024 * 1024

#: How long one extraction may run before the runner kills it. The compiler loads its own
#: ``lib`` declarations on every call, which dominates a small module's cost.
_EXTRACT_TIMEOUT_SECONDS = 60.0

#: Modules whose import marks a file as a *code-first schema library* module rather than a
#: module of type declarations. Such a file declares its schemas as values (``z.object(…)``),
#: which this reader cannot see — they belong to their own adapters (FMT-8.2 and siblings).
SCHEMA_LIBRARY_MODULES: Tuple[str, ...] = (
    "zod",
    "yup",
    "io-ts",
    "valibot",
    "superstruct",
    "arktype",
    "@sinclair/typebox",
    "@trpc/server",
)

#: Characters that only appear in a TypeScript source decoded from something that was not
#: UTF-8 text — a NUL (UTF-16) or the decoder's replacement character.
_ENCODING_FAULT_MARKERS: Tuple[str, ...] = ("\x00", "�")

#: A top-level type declaration, the evidence detection weighs.
_DECLARATION_RE = re.compile(
    r"^\s*export\s+(?:declare\s+)?(?:interface\s+[A-Za-z_$]|type\s+[A-Za-z_$][\w$]*\s*(?:<[^=]*>)?\s*=|"
    r"(?:const\s+)?enum\s+[A-Za-z_$])",
    re.MULTILINE,
)

#: A re-export, which makes an index module (``export * from './order'``) a type module too.
_REEXPORT_RE = re.compile(r"^\s*export\s+(?:type\s+)?(?:\*|\{[^}]*\})\s+from\s+['\"]", re.MULTILINE)

#: Any ``import … from '<module>'`` / ``export … from '<module>'`` / ``require('<module>')``.
_MODULE_SPECIFIER_RE = re.compile(
    r"""(?:\bfrom\s+|\bimport\s+|\brequire\s*\(\s*)['"]([^'"]+)['"]"""
)


# ===========================================================================
# Declared parsing limits
# ===========================================================================

#: Every construct the reader declares rather than models, with the reviewed sentence that says
#: what happens to it. Out-of-subset constructs are *never* widened to ``any``: the declaration
#: or member that needs one is left out of the model, and this is where that is said.
LIMIT_DETAILS: Dict[str, str] = {
    "typescript.conditional_type": (
        "A conditional type (`T extends U ? X : Y`, including `infer`) computes a type from "
        "another at compile time. It has no fixed shape to model, so the declaration or member "
        "that uses one is left out of the model rather than guessed."
    ),
    "typescript.mapped_type": (
        "A mapped type (`{ [K in keyof T]: … }`) is a transformation over another type's keys, "
        "not a shape of its own. It is left out of the model; `Partial`, `Required`, `Readonly`, "
        "`Pick` and `Omit` applied to a concrete type are evaluated and modelled instead."
    ),
    "typescript.template_literal_type": (
        "A template literal type (`` `on${Capitalize<…>}` ``) describes a set of strings by "
        "computation. The canonical model has no slot for the generated set, so the declaration "
        "or member is left out of the model rather than widened to `string`."
    ),
    "typescript.unresolved_generic": (
        "A generic declaration is modelled where it is instantiated — `Page<Order>` becomes a "
        "concrete record — and not where it is merely declared. A generic that is never "
        "instantiated with concrete arguments, or a type parameter that reaches the model "
        "unbound, has no shape to record and is declared here."
    ),
    "typescript.declaration_merging": (
        "Two or more declarations of the same interface merge into one in TypeScript. Merging is "
        "outside the supported subset, so a merged interface is left out of the model, and so is "
        "any member that refers to it."
    ),
    "typescript.function_type": (
        "A function, constructor or method signature describes behaviour, not data. The "
        "declaration or member is left out of the model."
    ),
    "typescript.symbol_key": (
        "A member keyed by a symbol (`[brand]: true`, `unique symbol`) has no name a data "
        "schema can carry. That member is left out; the rest of its type is modelled."
    ),
    "typescript.type_query": (
        "A type query (`typeof value`, `import('…')`, `this`) or an indexed access / `keyof` "
        "the compiler could not evaluate to a concrete shape points at a value or a computation "
        "rather than a declared type, and is left out of the model."
    ),
    "typescript.lib_type": (
        "A library type with no data shape (`Promise`, `Function`, `RegExp`, `Error`, …) is "
        "left out of the model. Collections (`Array`, `ReadonlyArray`, `Set`, `Map`, "
        "`Record`), `Date` and binary buffers are modelled."
    ),
    "typescript.tuple_positions": (
        "A tuple becomes a list whose items are the union of its element types, bounded by its "
        "length. Which type sits at which position, and each position's label, is recorded in "
        "`typescript_tuple` — preserved and reportable, but not enforced by the canonical list."
    ),
    "typescript.index_signature": (
        "An index signature beside named properties (`{ known: string; [key: string]: … }`) "
        "describes the extra keys an object may carry. The canonical record has no "
        "additional-properties slot, so the signature is recorded in `typescript_index` on the "
        "record; an object made only of an index signature is modelled as a map."
    ),
    "typescript.intersection": (
        "An intersection that includes something other than object shapes (a branded "
        "primitive such as `string & { __brand: … }`) cannot be merged into one record. The "
        "first member is modelled and the intersection is recorded in `typescript_intersection`."
    ),
    "typescript.unmodelled_reference": (
        "A member that refers to a declaration which was itself declared a limit (for example "
        "a merged interface or a conditional type) cannot point at a modelled type, so the "
        "member is left out of the model too."
    ),
}


@dataclass(frozen=True)
class TsLimit:
    """One declared parsing limit, with how often it was met and where.

    Attributes:
        construct: The stable limit key; always a key of :data:`LIMIT_DETAILS`.
        detail: The reviewed sentence for that key.
        count: How many occurrences were met.
        locations: The declarations or members the occurrences sit at, sorted.
    """

    construct: str
    detail: str
    count: int = 1
    locations: Tuple[str, ...] = ()


class LimitRecorder:
    """Accumulates :class:`TsLimit` records while a document is normalized."""

    def __init__(self) -> None:
        self._counts: Dict[str, int] = {}
        self._locations: Dict[str, Set[str]] = {}

    def record(self, construct: str, *, location: Optional[str] = None) -> None:
        """Record one occurrence of ``construct``.

        Args:
            construct: The stable limit key; must be a key of :data:`LIMIT_DETAILS`.
            location: The declaration or member the occurrence sits at, when known.

        Raises:
            KeyError: If ``construct`` is not part of the declared vocabulary.
        """
        if construct not in LIMIT_DETAILS:
            raise KeyError(f"unknown TypeScript limit key: {construct}")
        self._counts[construct] = self._counts.get(construct, 0) + 1
        if location:
            self._locations.setdefault(construct, set()).add(location)

    def limits(self) -> Tuple[TsLimit, ...]:
        """Return the accumulated limits, sorted by construct key."""
        return tuple(
            TsLimit(
                construct=construct,
                detail=LIMIT_DETAILS[construct],
                count=count,
                locations=tuple(sorted(self._locations.get(construct, ()))),
            )
            for construct, count in sorted(self._counts.items())
        )


# ===========================================================================
# The parsed document
# ===========================================================================


class TsParseError(Exception):
    """A TypeScript module could not be read.

    Attributes:
        code: The intake taxonomy code the failure belongs to (``INPUT_MALFORMED``,
            ``INPUT_TRUNCATED``, …), or ``None`` to let the pipeline classify it.
    """

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TsDocument:
    """One TypeScript module, or module set, as the extractor read it.

    Attributes:
        root: The root module's name — the one whose exports define the model.
        files: Every module name in the set, sorted.
        typescript_version: The compiler version that read it.
        declarations: Every top-level ``interface`` / ``type`` / ``enum`` declaration in every
            module, as the extractor's neutral AST (plain JSON objects), in source order.
        sources: Module name → source text, kept for the fidelity bag.
    """

    root: str
    files: Tuple[str, ...]
    typescript_version: str
    declarations: Tuple[Dict[str, Any], ...]
    sources: Dict[str, str] = field(default_factory=dict)

    def by_id(self) -> Dict[str, Dict[str, Any]]:
        """Return the declarations keyed by their ``<module>#<name>`` id."""
        return {declaration["id"]: declaration for declaration in self.declarations}

    def exported(self) -> List[Dict[str, Any]]:
        """Return the declarations the root module exports, in source order."""
        return [declaration for declaration in self.declarations if declaration.get("exported")]


# ===========================================================================
# Detection
# ===========================================================================


def imported_schema_library(text: str) -> Optional[str]:
    """Return the code-first schema library a module imports, or ``None``.

    Args:
        text: The module source.

    Returns:
        The first :data:`SCHEMA_LIBRARY_MODULES` entry the text imports (a sub-path such as
        ``zod/v4`` counts as ``zod``), or ``None``.
    """
    for specifier in _MODULE_SPECIFIER_RE.findall(text):
        for library in SCHEMA_LIBRARY_MODULES:
            if specifier == library or specifier.startswith(f"{library}/"):
                return library
    return None


def is_typescript_types(text: str) -> bool:
    """Whether ``text`` reads as a module of TypeScript type declarations.

    The evidence is an exported ``interface``, ``type … =`` or ``enum`` at the start of a line,
    or a re-export (an index module). A module that imports a code-first schema library is a
    schema-*builder* module and is not claimed, even when it also declares a type.

    Args:
        text: The candidate source.

    Returns:
        ``True`` when the text is claimable by this reader.
    """
    if imported_schema_library(text) is not None:
        return False
    return bool(_DECLARATION_RE.search(text) or _REEXPORT_RE.search(text))


# ===========================================================================
# Reading
# ===========================================================================


def _module_name(source_label: Optional[str]) -> str:
    """The name a pasted or uploaded module is mounted under for the compiler.

    The compiler decides how to read a file from its suffix, so a label without a TypeScript
    suffix (a paste, a URL) is mounted as ``module.ts``.
    """
    name = PurePosixPath(source_label or "").name
    return name if name.lower().endswith(TYPESCRIPT_SUFFIXES) else "module.ts"


def _guard_input(files: Mapping[str, str], *, where: str) -> None:
    """Reject input the compiler should never see, with the taxonomy code it deserves.

    Raises:
        TsParseError: For an empty, oversized, non-UTF-8 or schema-library module.
    """
    if not any(text.strip() for text in files.values()):
        raise TsParseError(f"The TypeScript module is empty{where}.", code="INPUT_EMPTY")
    size = sum(len(text.encode("utf-8", "ignore")) for text in files.values())
    if size > MAX_TYPESCRIPT_BYTES:
        raise TsParseError(
            f"The TypeScript source is {size} bytes{where}, above the "
            f"{MAX_TYPESCRIPT_BYTES}-byte import limit.",
            code="INPUT_TOO_LARGE",
        )
    for name, text in sorted(files.items()):
        if text.startswith("﻿") or any(marker in text for marker in _ENCODING_FAULT_MARKERS):
            raise TsParseError(
                f"{name} is not UTF-8 text (it looks like UTF-16 or binary){where}.",
                code="INPUT_ENCODING_INVALID",
            )
    for name, text in sorted(files.items()):
        library = imported_schema_library(text)
        if library is not None:
            raise TsParseError(
                f"{name} imports `{library}`, so its schemas are values built with that library "
                f"rather than TypeScript type declarations{where}. Code-first schema libraries "
                "are a separate source from TypeScript types.",
                code="FORMAT_MISMATCH",
            )


def _run_extractor(files: Mapping[str, str], root: str, *, where: str) -> Dict[str, Any]:
    """Run the bundled extractor and return its response object.

    Raises:
        TsParseError: When the tool is unavailable, fails, or breaks its output contract.
    """
    request = json.dumps({"files": dict(files), "root": root})
    try:
        result = run_tool_blocking(
            TYPESCRIPT_TYPES_TOOL_KEY,
            stdin=request,
            timeout=_EXTRACT_TIMEOUT_SECONDS,
            thread_name="typescript-types-extract",
        )
    except ToolNotAvailableError as exc:
        raise TsParseError(
            f"The TypeScript extractor is not available in this runtime{where}; TypeScript "
            "type import needs the bundled toolchain (see docs/toolchain_packaging.md).",
            code="ADAPTER_UNAVAILABLE",
        ) from exc
    except ToolchainError as exc:
        raise TsParseError(
            f"The TypeScript extractor failed{where}: {exc}", code="INTERNAL_ADAPTER_FAULT"
        ) from exc
    payload = result.parsed_json
    if not isinstance(payload, dict) or not isinstance(payload.get("declarations"), list):
        raise TsParseError(
            f"The TypeScript extractor returned an unexpected result{where}; the wrapper "
            "contract was violated.",
            code="INTERNAL_ADAPTER_FAULT",
        )
    return payload


def _raise_for_diagnostics(diagnostics: Sequence[Mapping[str, Any]], *, where: str) -> None:
    """Turn the compiler's syntax errors into the taxonomy code they amount to.

    When *every* error sits at the end of the text, the module stopped while a construct was
    still open — it was cut short (``INPUT_TRUNCATED``). An error anywhere earlier is a syntax
    fault in text that is otherwise all there (``INPUT_MALFORMED``).

    Raises:
        TsParseError: Always, when ``diagnostics`` is non-empty.
    """
    if not diagnostics:
        return
    first = diagnostics[0]
    location = f"{first.get('file')}:{first.get('line')}:{first.get('column')}"
    message = f"{location}: {first.get('message')}"
    if len(diagnostics) > 1:
        message += f" (and {len(diagnostics) - 1} more syntax error(s))"
    if all(diagnostic.get("atEnd") for diagnostic in diagnostics):
        raise TsParseError(
            f"The TypeScript module ends in the middle of a declaration{where} — {message}",
            code="INPUT_TRUNCATED",
        )
    raise TsParseError(f"TypeScript syntax error{where} — {message}", code="INPUT_MALFORMED")


def _walk(node: Any) -> Iterable[Dict[str, Any]]:
    """Yield every AST object beneath ``node`` (depth-first)."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _reachable(declarations: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The exported declarations plus every declaration they reach through a reference."""
    by_id = {declaration["id"]: declaration for declaration in declarations}
    pending = [declaration["id"] for declaration in declarations if declaration.get("exported")]
    seen: Set[str] = set()
    while pending:
        current = pending.pop()
        if current in seen or current not in by_id:
            continue
        seen.add(current)
        for node in _walk(by_id[current]):
            if node.get("kind") == "ref" and isinstance(node.get("target"), str):
                pending.append(node["target"])
    return [declaration for declaration in declarations if declaration["id"] in seen]


def _raise_for_unresolved(
    declarations: Sequence[Dict[str, Any]], imports: Sequence[Mapping[str, Any]], *, where: str
) -> None:
    """Reject a model whose exported surface names a type nothing in the set declares.

    Only references the exported types actually reach count: an unused import of a missing
    module costs the model nothing, while a field whose type cannot be found would otherwise
    have to be modelled as ``any`` — which FMT-8.1 forbids.

    Raises:
        TsParseError: ``INPUT_REFERENCE_UNRESOLVED``, naming the type and the missing modules.
    """
    for declaration in _reachable(declarations):
        for node in _walk(declaration):
            if node.get("kind") != "unresolved":
                continue
            missing = sorted(
                {str(entry.get("module")) for entry in imports if not entry.get("resolved")}
            )
            source = f" (unresolved import(s): {', '.join(missing)})" if missing else ""
            raise TsParseError(
                f"{declaration['name']} refers to `{node.get('name')}`, which no module in the "
                f"import declares{source}{where}. Add the module that declares it to the "
                "upload, or import the files as a set.",
                code="INPUT_REFERENCE_UNRESOLVED",
            )


def _read(files: Mapping[str, str], root: str, *, source_label: Optional[str]) -> TsDocument:
    """Read a module set through the extractor and validate the result."""
    where = f" ({source_label})" if source_label else ""
    _guard_input(files, where=where)
    payload = _run_extractor(files, root, where=where)

    diagnostics = [entry for entry in payload.get("diagnostics") or [] if isinstance(entry, dict)]
    if not payload.get("ok") or diagnostics:
        _raise_for_diagnostics(
            diagnostics or [{"message": "syntax error", "atEnd": False}], where=where
        )

    declarations = tuple(
        entry for entry in payload["declarations"] if isinstance(entry, dict) and entry.get("id")
    )
    imports = [entry for entry in payload.get("imports") or [] if isinstance(entry, dict)]
    if not any(declaration.get("exported") for declaration in declarations):
        raise TsParseError(
            f"The TypeScript module exports no interface, type alias or enum{where}, so there is "
            "no schema to import. Export the types the catalog should hold.",
            code="INPUT_SEMANTIC_INVALID",
        )
    _raise_for_unresolved(declarations, imports, where=where)

    return TsDocument(
        root=str(payload.get("root") or root),
        files=tuple(sorted(files)),
        typescript_version=str(payload.get("typescriptVersion") or ""),
        declarations=declarations,
        sources=dict(files),
    )


def parse_typescript_types(raw: str, *, source_label: Optional[str] = None) -> TsDocument:
    """Read one TypeScript module of type declarations.

    Args:
        raw: The module source.
        source_label: The module's name (a filename keeps its suffix, so a ``.d.ts`` is read as
            a declaration file), for the compiler and for error messages.

    Returns:
        The parsed :class:`TsDocument`.

    Raises:
        TsParseError: With the intake taxonomy code the failure belongs to.
    """
    name = _module_name(source_label)
    return _read({name: raw}, name, source_label=source_label)


def parse_typescript_types_fileset(
    members: Mapping[str, str], *, root: str, source_label: Optional[str] = None
) -> TsDocument:
    """Read a set of TypeScript modules that import one another.

    Every member is handed to the compiler together, so an ``import type`` between them
    resolves; only the root module's exports (including what it re-exports) define the model.

    Args:
        members: Module path → source text.
        root: The root module's path.
        source_label: Fallback label for error messages.

    Returns:
        The parsed :class:`TsDocument`.

    Raises:
        TsParseError: With the intake taxonomy code the failure belongs to.
    """
    files = {
        path: text for path, text in members.items() if path.lower().endswith(TYPESCRIPT_SUFFIXES)
    }
    if root not in files:
        raise TsParseError(
            f"The TypeScript set's root module {root!r} is missing or is not a TypeScript file.",
            code="INPUT_SEMANTIC_INVALID",
        )
    return _read(files, root, source_label=source_label or root)
