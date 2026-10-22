"""Zod schema reader — FMT-8.2 (#5463).

Zod is where most TypeScript projects put their *runtime* schema, and unlike a bare type it
carries the validation constraints an API description needs — ``min``/``max``, ``regex``,
``email``, ``uuid``. A Zod schema is a value, so the only faithful way to read one is to run the
module that builds it. That is what the bundled ``zod-schema-extractor`` tool does
(``apiome-rest/toolchain/zod-extract.mjs``): it evaluates the module behind Node's permission
model, inside a time-bounded ``vm`` context with no network, and serializes every exported
schema to JSON Schema from Zod's ``_def`` tree. :mod:`app.zod_normalizer` maps that JSON Schema
onto the canonical model.

What lives here:

* :class:`ZodDocument` — one read module (or module set): the JSON Schema the extractor
  produced, the root module's exported schema names, and the module sources.
* :data:`LIMIT_DETAILS` / :func:`zod_limit_recorder` — the declared limits. FMT-8.2 requires
  ``refine``, ``transform`` and the other constructs with no JSON Schema analogue to be
  *declared*, never silently dropped; every key here is one of them.
* :func:`parse_zod` / :func:`parse_zod_fileset` — the readers, which classify every rejection
  with an intake taxonomy code (a module that throws, runs out of time, imports a module the
  upload does not contain, or holds no Zod at all).
* :func:`is_zod_module` — the cheap, subprocess-free detection sniff.

**This reader executes user code.** The extractor's own walls are described in its header; on
top of them, the call here runs under :meth:`~app.toolchain_sandbox.SandboxPolicy.
for_untrusted_code` — network isolation forced on and *strict* (fail closed) — and with a
wall-clock timeout a little above the module's evaluation budget, so a schema that loops outside
the ``vm`` deadline (a ``z.lazy`` getter, a default factory) is killed too.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .toolchain_runner import (
    ToolchainError,
    ToolNotAvailableError,
    ToolTimeoutError,
    default_runner,
    run_tool_blocking,
)
from .typescript_types_parser import TYPESCRIPT_SUFFIXES, LimitRecorder

__all__ = [
    "EVALUATION_BUDGET_MS",
    "LIMIT_DETAILS",
    "MAX_ZOD_BYTES",
    "PARTIAL_LIMITS",
    "ZOD_SCHEMA_TOOL_KEY",
    "ZodDocument",
    "ZodParseError",
    "evaluate_modules",
    "imports_zod",
    "imports_other_zod_api",
    "is_zod_module",
    "parse_zod",
    "parse_zod_fileset",
    "zod_limit_recorder",
]

#: Registry key of the bundled extractor (declared in :mod:`app.toolchain_packaging`).
ZOD_SCHEMA_TOOL_KEY = "zod-schema-extractor"

#: The largest module set (all members together) the reader will evaluate, in bytes.
MAX_ZOD_BYTES = 2 * 1024 * 1024

#: How long the module set may take to *evaluate*, in milliseconds — the extractor's ``vm``
#: deadline. An endless loop at import fails as ``INPUT_TIME_LIMIT`` within this budget.
EVALUATION_BUDGET_MS = 5000

#: The runner's wall-clock ceiling for the whole tool call: the evaluation budget plus room for
#: Node to start, load Zod and TypeScript, and serialize. It is the backstop for user code that
#: runs *after* evaluation (a ``z.lazy`` getter, a default factory), outside the ``vm`` deadline.
_TOOL_TIMEOUT_SECONDS = EVALUATION_BUDGET_MS / 1000 + 25

#: Any ``import … from '<module>'`` / ``export … from '<module>'`` / ``require('<module>')``.
_MODULE_SPECIFIER_RE = re.compile(
    r"""(?:\bfrom\s+|\bimport\s+|\brequire\s*\(\s*)['"]([^'"]+)['"]"""
)

#: The Zod entry points this reader evaluates (the Zod 3 API).
_ZOD_V3_SPECIFIERS = frozenset({"zod", "zod/v3"})

#: Zod entry points for a different major API, declined with a version error rather than run.
_ZOD_OTHER_SPECIFIERS = frozenset({"zod/v4", "zod/mini", "zod/v4-mini", "zod/v4/core"})

#: An exported Zod value: ``export const X = z.…`` (or a re-export of one).
_EXPORTED_SCHEMA_RE = re.compile(
    r"^\s*export\s+(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*(?::[^=]+)?=\s*z\s*\.", re.MULTILINE
)

#: Characters that only appear in source decoded from something that was not UTF-8 text.
_ENCODING_FAULT_MARKERS: Tuple[str, ...] = ("\x00", "�")


# ===========================================================================
# Declared limits
# ===========================================================================

#: Every construct the reader declares rather than models, with the reviewed sentence that says
#: what happens to it.
LIMIT_DETAILS: Dict[str, str] = {
    "zod.refine": (
        "A `refine` / `superRefine` predicate is arbitrary code with no JSON Schema analogue. The "
        "schema it refines is modelled; the predicate itself is not, and this is where that is "
        "said."
    ),
    "zod.transform": (
        "A `transform` (and the `trim`, `toLowerCase` and `toUpperCase` string checks) changes "
        "the value after it is parsed. The *input* schema is modelled; the output shape the "
        "transform produces is not."
    ),
    "zod.preprocess": (
        "A `preprocess` step runs arbitrary code before parsing. The schema it feeds is modelled; "
        "what the step accepts and rewrites is not."
    ),
    "zod.brand": (
        "A `brand` is a nominal tag that exists only in the type system. The branded schema is "
        "modelled with its constraints; the brand itself has no runtime or schema form."
    ),
    "zod.pipe": (
        "A `pipe` feeds one schema's output into another. The input schema is modelled; the "
        "schema it is piped into is not."
    ),
    "zod.coerce": (
        'A `z.coerce.*` schema converts its input (a string `"42"` to the number 42) before '
        "checking it. The checked type is modelled; the wider set of inputs coercion accepts is "
        "not."
    ),
    "zod.custom": (
        "`z.custom()` is a predicate over any value, with no structure to model. The declaration "
        "or member is left out of the model rather than widened to `any`."
    ),
    "zod.function": (
        "A `z.function()` schema describes behaviour, not data. The declaration or member is "
        "left out of the model."
    ),
    "zod.promise": (
        "A `z.promise()` schema describes an asynchronous value, not a data shape. The "
        "declaration or member is left out of the model."
    ),
    "zod.unrepresentable": (
        "A schema with no data meaning (`never`, `symbol`, `NaN`) or one this reader does not "
        "recognize is left out of the model rather than guessed."
    ),
    "zod.unnamed_recursion": (
        "A recursive schema that is not exported has no name for the recursion to point at, so "
        "the recursive member is left out. Export the schema to model the recursion."
    ),
    "zod.tuple_positions": (
        "A tuple becomes a list whose items are the union of its element types, bounded by its "
        "length. Which type sits at which position is recorded in `typescript_tuple` — "
        "preserved and reportable, but not enforced by the canonical list."
    ),
    "zod.additional_properties": (
        "A `catchall` schema describes the extra keys an object may carry. The canonical record "
        "has no additional-properties slot, so it is recorded in `typescript_index` on the "
        "record; an object that is nothing but a `record` is modelled as a map."
    ),
    "zod.intersection": (
        "An intersection that includes something other than object shapes cannot be merged into "
        "one record. The first member is modelled and the intersection is recorded."
    ),
    "zod.unmodelled_reference": (
        "A member that refers to a schema which was itself declared a limit cannot point at a "
        "modelled type, so the member is left out of the model too."
    ),
}

#: The limits whose construct *is* modelled, with only a detail lost. Every other Zod limit
#: leaves its declaration or member out of the model.
PARTIAL_LIMITS = frozenset(
    {
        "zod.refine",
        "zod.transform",
        "zod.preprocess",
        "zod.brand",
        "zod.pipe",
        "zod.coerce",
        "zod.tuple_positions",
        "zod.additional_properties",
        "zod.intersection",
    }
)

#: The shared model's built-in ``typescript.*`` limits, renamed into this reader's vocabulary.
#: The generic-only limits cannot occur for Zod (a schema is a value, never a generic) and fold
#: into ``zod.unrepresentable`` for completeness.
_TYPESCRIPT_ALIASES: Dict[str, str] = {
    "typescript.tuple_positions": "zod.tuple_positions",
    "typescript.index_signature": "zod.additional_properties",
    "typescript.intersection": "zod.intersection",
    "typescript.unmodelled_reference": "zod.unmodelled_reference",
    "typescript.function_type": "zod.function",
    "typescript.type_query": "zod.unrepresentable",
    "typescript.lib_type": "zod.unrepresentable",
    "typescript.symbol_key": "zod.unrepresentable",
    "typescript.unresolved_generic": "zod.unrepresentable",
    "typescript.declaration_merging": "zod.unrepresentable",
    "typescript.conditional_type": "zod.unrepresentable",
    "typescript.mapped_type": "zod.unrepresentable",
    "typescript.template_literal_type": "zod.unrepresentable",
}


def zod_limit_recorder() -> LimitRecorder:
    """A limit recorder over the Zod vocabulary (the shared model's keys renamed into it)."""
    return LimitRecorder(details=LIMIT_DETAILS, aliases=_TYPESCRIPT_ALIASES)


# ===========================================================================
# The parsed document
# ===========================================================================


class ZodParseError(Exception):
    """A Zod module could not be read.

    Attributes:
        code: The intake taxonomy code the failure belongs to, or ``None`` to let the pipeline
            classify it.
    """

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ZodDocument:
    """One Zod module, or module set, as the extractor read it.

    Attributes:
        root: The root module's name — the one whose exports define the model.
        files: Every module name in the set, sorted.
        zod_version: The Zod version that evaluated it.
        exports: The root module's exported schema names, in export order.
        schema: The JSON Schema document: ``$defs`` holds every exported schema, plus any schema
            a sibling module exports that an export refers to.
        sources: Module name → source text, kept for the fidelity bag.
    """

    root: str
    files: Tuple[str, ...]
    zod_version: str
    exports: Tuple[str, ...]
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


def _specifiers(text: str) -> List[str]:
    return _MODULE_SPECIFIER_RE.findall(text)


def imports_zod(text: str) -> bool:
    """Whether a module imports the Zod 3 API (``zod`` or ``zod/v3``)."""
    return any(specifier in _ZOD_V3_SPECIFIERS for specifier in _specifiers(text))


def imports_other_zod_api(text: str) -> Optional[str]:
    """The Zod 4 / Zod Mini entry point a module imports, or ``None``."""
    return next((s for s in _specifiers(text) if s in _ZOD_OTHER_SPECIFIERS), None)


def is_zod_module(text: str) -> bool:
    """Whether ``text`` reads as a module of exported Zod schemas.

    The evidence is an import of ``zod`` (or a Zod 4 entry point, which is claimed so it can be
    declined by name) together with an exported ``z.…`` value or a re-export. A module that also
    imports ``@trpc/server`` is a tRPC router module and is left to the tRPC adapter.

    Args:
        text: The candidate source.

    Returns:
        ``True`` when the text is claimable by this reader.
    """
    if not (imports_zod(text) or imports_other_zod_api(text)):
        return False
    if "@trpc/server" in _specifiers(text):
        # A tRPC router module imports Zod for its procedures' inputs; it belongs to FMT-8.3.
        return False
    return bool(
        _EXPORTED_SCHEMA_RE.search(text) or re.search(r"^\s*export\s+\*\s+from", text, re.M)
    )


# ===========================================================================
# Reading
# ===========================================================================


def _module_name(source_label: Optional[str]) -> str:
    """The name a pasted or uploaded module is mounted under (it keeps a TypeScript suffix)."""
    name = PurePosixPath(source_label or "").name
    return name if name.lower().endswith(TYPESCRIPT_SUFFIXES) else "module.ts"


def _guard_input(
    files: Mapping[str, str],
    root: str,
    *,
    where: str,
    mismatch: Callable[[Mapping[str, str], str, str], Optional[str]],
) -> None:
    """Reject input that must never be evaluated, with the taxonomy code it deserves.

    Args:
        files: Module name → source.
        root: The root module's name.
        where: The `` (label)`` suffix for messages.
        mismatch: The reader's own format check — a message when the set is not this reader's
            format (``FORMAT_MISMATCH``), ``None`` when it is.

    Raises:
        ZodParseError: For an empty, oversized, non-UTF-8, Zod 4 or wrong-format module set.
    """
    if not any(text.strip() for text in files.values()):
        raise ZodParseError(f"The Zod module is empty{where}.", code="INPUT_EMPTY")
    size = sum(len(text.encode("utf-8", "ignore")) for text in files.values())
    if size > MAX_ZOD_BYTES:
        raise ZodParseError(
            f"The Zod source is {size} bytes{where}, above the {MAX_ZOD_BYTES}-byte import limit.",
            code="INPUT_TOO_LARGE",
        )
    for name, text in sorted(files.items()):
        if text.startswith("﻿") or any(marker in text for marker in _ENCODING_FAULT_MARKERS):
            raise ZodParseError(
                f"{name} is not UTF-8 text (it looks like UTF-16 or binary){where}.",
                code="INPUT_ENCODING_INVALID",
            )
    for name, text in sorted(files.items()):
        other = imports_other_zod_api(text)
        if other is not None:
            raise ZodParseError(
                f"{name} imports `{other}`, the Zod 4 API{where}. This reader evaluates Zod 3 "
                "schemas (`import { z } from 'zod'` with Zod 3.x).",
                code="FORMAT_VERSION_UNSUPPORTED",
            )
    message = mismatch(files, root, where)
    if message is not None:
        raise ZodParseError(message, code="FORMAT_MISMATCH")


def _zod_mismatch(files: Mapping[str, str], root: str, where: str) -> Optional[str]:
    """A Zod module set imports ``zod`` somewhere; anything else is a different format."""
    if any(imports_zod(text) for text in files.values()):
        return None
    return (
        f"{root} does not import `zod`, so it defines no Zod schemas{where}. A module of "
        "TypeScript `interface` / `type` declarations is imported as TypeScript types."
    )


#: The extractor's outcome codes → intake taxonomy codes.
_OUTCOME_CODES: Dict[str, str] = {
    "TIME_LIMIT": "INPUT_TIME_LIMIT",
    "MODULE_THREW": "INPUT_SEMANTIC_INVALID",
    "UNRESOLVED_MODULE": "INPUT_REFERENCE_UNRESOLVED",
    "ZOD_VERSION": "FORMAT_VERSION_UNSUPPORTED",
}


def _run_extractor(
    files: Mapping[str, str], root: str, *, where: str, routers: bool = False
) -> Dict[str, Any]:
    """Run the bundled extractor under the untrusted-code sandbox and return its response.

    Raises:
        ZodParseError: When the tool is unavailable, times out, fails, or breaks its contract.
    """
    request = json.dumps(
        {"files": dict(files), "root": root, "budgetMs": EVALUATION_BUDGET_MS, "routers": routers}
    )
    try:
        result = run_tool_blocking(
            ZOD_SCHEMA_TOOL_KEY,
            stdin=request,
            timeout=_TOOL_TIMEOUT_SECONDS,
            policy=default_runner.default_policy.for_untrusted_code(),
            thread_name="zod-extract",
        )
    except ToolNotAvailableError as exc:
        raise ZodParseError(
            f"The Zod extractor is not available in this runtime{where}; Zod import needs the "
            "bundled toolchain (see docs/toolchain_packaging.md).",
            code="ADAPTER_UNAVAILABLE",
        ) from exc
    except ToolTimeoutError as exc:
        raise ZodParseError(
            f"Reading the Zod schemas took longer than {_TOOL_TIMEOUT_SECONDS:.0f} s{where} — a "
            "schema keeps running code (an endless `z.lazy` getter or default?).",
            code="INPUT_TIME_LIMIT",
        ) from exc
    except ToolchainError as exc:
        raise ZodParseError(
            f"The Zod extractor failed{where}: {exc}", code="INTERNAL_ADAPTER_FAULT"
        ) from exc
    payload = result.parsed_json
    if not isinstance(payload, dict) or "ok" not in payload:
        raise ZodParseError(
            f"The Zod extractor returned an unexpected result{where}; the wrapper contract was "
            "violated.",
            code="INTERNAL_ADAPTER_FAULT",
        )
    return payload


def _raise_for_diagnostics(diagnostics: Sequence[Mapping[str, Any]], *, where: str) -> None:
    """Turn TypeScript syntax errors into ``INPUT_TRUNCATED`` / ``INPUT_MALFORMED``.

    Raises:
        ZodParseError: Always, when ``diagnostics`` is non-empty.
    """
    if not diagnostics:
        return
    first = diagnostics[0]
    message = (
        f"{first.get('file')}:{first.get('line')}:{first.get('column')}: {first.get('message')}"
    )
    if len(diagnostics) > 1:
        message += f" (and {len(diagnostics) - 1} more syntax error(s))"
    if all(diagnostic.get("atEnd") for diagnostic in diagnostics):
        raise ZodParseError(
            f"The module ends in the middle of a declaration{where} — {message}", code="INPUT_TRUNCATED"
        )
    raise ZodParseError(f"TypeScript syntax error{where} — {message}", code="INPUT_MALFORMED")


def evaluate_modules(
    files: Mapping[str, str],
    root: str,
    *,
    source_label: Optional[str],
    mismatch: Callable[[Mapping[str, str], str, str], Optional[str]],
    routers: bool = False,
) -> Dict[str, Any]:
    """Guard, evaluate and classify a module set — the path every code-first reader shares.

    Runs the intake guards, evaluates the set in the sandboxed extractor, and turns syntax
    errors and evaluation failures into taxonomy-coded :class:`ZodParseError`\\s. FMT-8.3's tRPC
    reader calls this with ``routers=True``.

    Args:
        files: Module name → source.
        root: The root module's name.
        source_label: The label for messages.
        mismatch: The reader's own format check (see :func:`_guard_input`).
        routers: Whether the extractor should also walk exported tRPC routers.

    Returns:
        The extractor's response object, for a set that evaluated cleanly.

    Raises:
        ZodParseError: With the intake taxonomy code the failure belongs to.
    """
    where = f" ({source_label})" if source_label else ""
    _guard_input(files, root, where=where, mismatch=mismatch)
    payload = _run_extractor(files, root, where=where, routers=routers)

    diagnostics = [d for d in payload.get("diagnostics") or [] if isinstance(d, dict)]
    _raise_for_diagnostics(diagnostics, where=where)

    error = payload.get("error")
    if isinstance(error, dict):
        code = _OUTCOME_CODES.get(str(error.get("code")), "INPUT_SEMANTIC_INVALID")
        raise ZodParseError(f"{error.get('message')}{where}", code=code)
    return payload


def _read(files: Mapping[str, str], root: str, *, source_label: Optional[str]) -> ZodDocument:
    """Evaluate a module set through the extractor and validate the result."""
    where = f" ({source_label})" if source_label else ""
    payload = evaluate_modules(files, root, source_label=source_label, mismatch=_zod_mismatch)

    schema = payload.get("schema")
    exports = tuple(str(name) for name in payload.get("exports") or [])
    if not payload.get("ok") or not isinstance(schema, dict) or not exports:
        raise ZodParseError(
            f"The module exports no Zod schema{where}, so there is nothing to import. Export the "
            "schemas the catalog should hold (`export const Order = z.object({…})`).",
            code="INPUT_SEMANTIC_INVALID",
        )
    return ZodDocument(
        root=str(payload.get("root") or root),
        files=tuple(sorted(files)),
        zod_version=str(payload.get("zodVersion") or ""),
        exports=exports,
        schema=schema,
        sources=dict(files),
    )


def parse_zod(raw: str, *, source_label: Optional[str] = None) -> ZodDocument:
    """Evaluate one module and read its exported Zod schemas.

    Args:
        raw: The module source.
        source_label: The module's name, for the compiler and error messages.

    Returns:
        The parsed :class:`ZodDocument`.

    Raises:
        ZodParseError: With the intake taxonomy code the failure belongs to.
    """
    name = _module_name(source_label)
    return _read({name: raw}, name, source_label=source_label)


def parse_zod_fileset(
    members: Mapping[str, str], *, root: str, source_label: Optional[str] = None
) -> ZodDocument:
    """Evaluate a set of modules that import one another, rooted at ``root``.

    Args:
        members: Module path → source text.
        root: The root module's path; its exports define the model.
        source_label: Fallback label for error messages.

    Returns:
        The parsed :class:`ZodDocument`.

    Raises:
        ZodParseError: With the intake taxonomy code the failure belongs to.
    """
    files = {
        path: text for path, text in members.items() if path.lower().endswith(TYPESCRIPT_SUFFIXES)
    }
    if root not in files:
        raise ZodParseError(
            f"The Zod set's root module {root!r} is missing or is not a TypeScript file.",
            code="INPUT_SEMANTIC_INVALID",
        )
    return _read(files, root, source_label=source_label or root)
