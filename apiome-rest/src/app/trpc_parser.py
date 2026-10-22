"""tRPC router reader — FMT-8.3 (#5464).

tRPC is type-safe RPC with no IDL at all: the contract exists only as a router *value* — a tree
of procedures, each a ``query``, ``mutation`` or ``subscription`` whose input and output are
(usually) Zod schemas. Like a Zod schema, a router only exists once its module has run, so this
reader evaluates the module with the same sandboxed extractor FMT-8.2 built
(``apiome-rest/toolchain/zod-extract.mjs``, ``routers`` mode) — permission-locked, network-free,
time-bounded — and reads every exported router's procedure map. Inputs and outputs are
serialized through the FMT-8.2 Zod path, so a procedure's schemas carry the same constraints and
declared limits a Zod import does. :mod:`app.trpc_normalizer` maps the result onto ``rpc``
operations.

What lives here:

* :class:`TrpcDocument` — the routers the root module exports, each procedure's path, kind,
  input and output, and the JSON Schema of every named schema they refer to.
* :data:`LIMIT_DETAILS` — the Zod vocabulary plus the tRPC-only limits (a hand-written
  validator, a lazily-loaded router).
* :func:`parse_trpc` / :func:`parse_trpc_fileset` and :func:`is_trpc_module`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .typescript_types_parser import TYPESCRIPT_SUFFIXES, LimitRecorder
from .zod_parser import (
    _TYPESCRIPT_ALIASES,
    ZodParseError,
    _module_name,
    _specifiers,
    evaluate_modules,
)
from .zod_parser import LIMIT_DETAILS as ZOD_LIMIT_DETAILS
from .zod_parser import PARTIAL_LIMITS as ZOD_PARTIAL_LIMITS

__all__ = [
    "LIMIT_DETAILS",
    "PARTIAL_LIMITS",
    "PROCEDURE_KINDS",
    "TrpcDocument",
    "TrpcParseError",
    "imports_trpc",
    "is_trpc_module",
    "parse_trpc",
    "parse_trpc_fileset",
    "trpc_limit_recorder",
]

#: The tRPC server entry points a router module imports.
_TRPC_SPECIFIERS = frozenset({"@trpc/server"})

#: The procedure kinds tRPC defines.
PROCEDURE_KINDS = ("query", "mutation", "subscription")

#: An ``initTRPC`` call, or a router built from one: the evidence a module defines a router.
_ROUTER_RE = re.compile(r"\binitTRPC\b|\.\s*router\s*\(", re.MULTILINE)

#: tRPC-only limits, on top of the Zod vocabulary every procedure schema is read with.
_TRPC_LIMITS: Dict[str, str] = {
    "trpc.non_schema_input": (
        "A procedure whose `.input()` is a hand-written validator function rather than a Zod "
        "schema has no schema to extract. The procedure is modelled; its request payload is not, "
        "rather than being presented as an empty body."
    ),
    "trpc.non_schema_output": (
        "A procedure whose `.output()` is a hand-written validator function has no schema to "
        "extract. The procedure is modelled; its response payload is not."
    ),
    "trpc.lazy_router": (
        "A router loaded with `lazy()` is only resolved when it is first called, so its "
        "procedures are not known when the module is read and are not modelled."
    ),
}

#: Every construct the reader declares rather than models.
LIMIT_DETAILS: Dict[str, str] = {**ZOD_LIMIT_DETAILS, **_TRPC_LIMITS}

#: The limits whose construct is still modelled. A non-schema validator leaves its *procedure*
#: modelled (only the payload is missing), so it is partial; a lazy router's procedures are not
#: modelled at all.
PARTIAL_LIMITS = frozenset(ZOD_PARTIAL_LIMITS | {"trpc.non_schema_input", "trpc.non_schema_output"})


def trpc_limit_recorder() -> LimitRecorder:
    """A limit recorder over the tRPC vocabulary (the shared model's keys renamed into it)."""
    return LimitRecorder(details=LIMIT_DETAILS, aliases=_TYPESCRIPT_ALIASES)


class TrpcParseError(ZodParseError):
    """A tRPC router module could not be read (same taxonomy codes as a Zod module)."""


@dataclass(frozen=True)
class TrpcDocument:
    """The routers one tRPC module (or module set) exports, as the extractor read them.

    Attributes:
        root: The root module's name.
        files: Every module name in the set, sorted.
        zod_version: The Zod version that evaluated the schemas.
        routers: One entry per exported router: ``{"name", "procedures": [{"path", "type",
            "inputs", "output", "meta"}], "lazy": [path]}``.
        schema: The JSON Schema document whose ``$defs`` holds every named schema a procedure
            refers to.
        sources: Module name → source text, kept for the fidelity bag.
    """

    root: str
    files: Tuple[str, ...]
    zod_version: str
    routers: Tuple[Dict[str, Any], ...]
    schema: Dict[str, Any]
    sources: Dict[str, str] = field(default_factory=dict)

    @property
    def definitions(self) -> Dict[str, Any]:
        """The ``$defs`` map: schema name → JSON Schema."""
        defs = self.schema.get("$defs")
        return defs if isinstance(defs, dict) else {}


# ===========================================================================
# Detection
# ===========================================================================


def imports_trpc(text: str) -> bool:
    """Whether a module imports the tRPC server package."""
    return any(specifier in _TRPC_SPECIFIERS for specifier in _specifiers(text))


def is_trpc_module(text: str) -> bool:
    """Whether ``text`` reads as a module that defines a tRPC router.

    Args:
        text: The candidate source.

    Returns:
        ``True`` for a module that imports ``@trpc/server`` and builds a router.
    """
    return imports_trpc(text) and bool(_ROUTER_RE.search(text))


# ===========================================================================
# Reading
# ===========================================================================


def _trpc_mismatch(files: Mapping[str, str], root: str, where: str) -> Optional[str]:
    """A router set imports ``@trpc/server`` somewhere; anything else is a different format."""
    if any(imports_trpc(text) for text in files.values()):
        return None
    return (
        f"{root} does not import `@trpc/server`, so it defines no tRPC router{where}. A module of "
        "Zod schemas is imported as Zod schemas, and one of TypeScript types as TypeScript types."
    )


def _has_schema(node: Any) -> bool:
    """Whether a procedure input/output node is a real schema (not a non-schema marker)."""
    return isinstance(node, dict) and "x-trpc-unsupported" not in node


def _read(files: Mapping[str, str], root: str, *, source_label: Optional[str]) -> TrpcDocument:
    """Evaluate a module set in routers mode and validate the routers it exports."""
    where = f" ({source_label})" if source_label else ""
    try:
        payload = evaluate_modules(
            files, root, source_label=source_label, mismatch=_trpc_mismatch, routers=True
        )
    except ZodParseError as exc:
        raise TrpcParseError(str(exc), code=exc.code) from exc

    routers = [r for r in payload.get("routers") or [] if isinstance(r, dict)]
    if not routers:
        raise TrpcParseError(
            f"The module exports no tRPC router{where}. Export the app router "
            "(`export const appRouter = t.router({…})`).",
            code="INPUT_SEMANTIC_INVALID",
        )
    procedures = [p for r in routers for p in r.get("procedures") or [] if isinstance(p, dict)]
    if not procedures:
        raise TrpcParseError(
            f"The exported router declares no procedures{where}, so it has no callable surface "
            "to import.",
            code="INPUT_SEMANTIC_INVALID",
        )
    if not any(
        any(_has_schema(node) for node in p.get("inputs") or []) or _has_schema(p.get("output"))
        for p in procedures
    ):
        raise TrpcParseError(
            f"No procedure in the router validates with a Zod schema{where} — every input is a "
            "hand-written function and no procedure declares an output schema, so there is no "
            "request or response shape to import. Use Zod schemas for `.input()` / `.output()`.",
            code="INPUT_SEMANTIC_INVALID",
        )
    schema = payload.get("schema") if isinstance(payload.get("schema"), dict) else {}
    return TrpcDocument(
        root=str(payload.get("root") or root),
        files=tuple(sorted(files)),
        zod_version=str(payload.get("zodVersion") or ""),
        routers=tuple(routers),
        schema=schema,
        sources=dict(files),
    )


def parse_trpc(raw: str, *, source_label: Optional[str] = None) -> TrpcDocument:
    """Evaluate one router module and read the routers it exports.

    Args:
        raw: The module source.
        source_label: The module's name, for the compiler and error messages.

    Returns:
        The parsed :class:`TrpcDocument`.

    Raises:
        TrpcParseError: With the intake taxonomy code the failure belongs to.
    """
    name = _module_name(source_label)
    return _read({name: raw}, name, source_label=source_label)


def parse_trpc_fileset(
    members: Mapping[str, str], *, root: str, source_label: Optional[str] = None
) -> TrpcDocument:
    """Evaluate a set of modules (routers and the schemas they share), rooted at ``root``.

    Args:
        members: Module path → source text.
        root: The module that exports the app router.
        source_label: Fallback label for error messages.

    Returns:
        The parsed :class:`TrpcDocument`.

    Raises:
        TrpcParseError: With the intake taxonomy code the failure belongs to.
    """
    files = {p: t for p, t in members.items() if p.lower().endswith(TYPESCRIPT_SUFFIXES)}
    if root not in files:
        raise TrpcParseError(
            f"The tRPC set's root module {root!r} is missing or is not a TypeScript file.",
            code="INPUT_SEMANTIC_INVALID",
        )
    return _read(files, root, source_label=source_label or root)


def procedure_paths(document: TrpcDocument) -> List[str]:
    """Every procedure path across the document's routers, sorted (for messages and tests)."""
    return sorted(p["path"] for r in document.routers for p in r.get("procedures") or [])
