"""Shared plumbing for the typed configuration language readers — FMT-8.5 (#5466).

CUE, Pkl and Dhall are typed configuration languages whose schemas are genuine, checkable type
definitions. FMT-8.5 reads each one the same way: the language's **own** tool evaluates the
upload inside the sandboxed toolchain runner — network-free, time-bounded, with its own cache —
and its output is projected to a JSON Schema document that the shared JSON Schema translator
(:func:`app.zod_normalizer.translate_schema`) turns into canonical types. What a language can say
and JSON Schema cannot (CUE's lattice unification, Pkl's late binding, Dhall's type-level
functions) is **declared** as a limit, never approximated.

This module holds what the three readers share:

* :class:`TypedConfigDocument` — one read upload: the JSON Schema projection, the exported
  definition names, the declared limits, the validated instance names and the sources.
* :class:`TypedConfigParseError` — a rejection carrying its intake taxonomy code.
* :func:`guard_input` — the checks every upload passes before any tool sees it (empty, too
  large, not UTF-8 text, an unsafe member path).
* :func:`workspace` — a private temporary directory the upload is laid out in, which is also the
  tool's ``HOME`` and cache, removed afterwards.
* :func:`run_typed_config_tool` — run a bundled tool there under the untrusted-code sandbox and
  map runner failures onto taxonomy codes.
* :func:`syntax_error_code` / :func:`strip_ansi` — the shared reading of a tool's error output.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from .toolchain_runner import (
    ToolchainError,
    ToolExecutionError,
    ToolNotAvailableError,
    ToolRunResult,
    ToolTimeoutError,
    default_runner,
    run_tool_blocking,
)

__all__ = [
    "MAX_TYPED_CONFIG_BYTES",
    "TOOL_TIMEOUT_SECONDS",
    "ToolFailure",
    "TypedConfigDocument",
    "TypedConfigParseError",
    "MODEL_PARTIAL_SUFFIXES",
    "first_lines",
    "guard_input",
    "model_limit_aliases",
    "model_limit_details",
    "pascal_case",
    "run_typed_config_tool",
    "strip_ansi",
    "syntax_error_code",
    "workspace",
]

#: The largest upload (all members together) a reader will hand to its tool, in bytes.
MAX_TYPED_CONFIG_BYTES = 2 * 1024 * 1024

#: The wall-clock ceiling of one tool call, in seconds. Evaluation is the slow part of a typed
#: configuration language — a CUE comprehension or a Dhall fold can loop for a long time — so a
#: call that runs past this is killed and the import fails with ``INPUT_TIME_LIMIT``.
TOOL_TIMEOUT_SECONDS = 20.0

#: Characters that only appear in text decoded from something that was not UTF-8.
_ENCODING_FAULT_MARKERS: Tuple[str, ...] = ("\x00", "�")

#: An ANSI colour / cursor escape sequence (the tools colour their error output).
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def model_limit_details(language: str, label: str) -> Dict[str, str]:
    """The limits the shared model itself can declare, in one language's vocabulary.

    The JSON Schema translator and the FMT-8.1 model builder record a handful of limits of their
    own — a tuple's positions, a record's extra keys, a non-object intersection, a reference to
    something left out, a node nothing can express. Every typed-config reader declares them
    under its own prefix (``cue.tuple_positions``), so the coverage ledger names the language.

    Args:
        language: The limit-key prefix (``cue``, ``pkl``, ``dhall``).
        label: The language's display name, for the sentences.

    Returns:
        ``limit key → detail sentence``.
    """
    return {
        f"{language}.tuple_positions": (
            "A fixed-length list (a tuple) becomes a list whose items are the union of its "
            "element types, bounded by its length. Which type sits at which position is recorded "
            "in `typescript_tuple` — preserved and reportable, but not enforced by the canonical "
            "list."
        ),
        f"{language}.additional_properties": (
            f"A {label} record that declares fields and also accepts any other key describes the "
            "extra keys it may carry. The canonical record has no additional-properties slot, so "
            "it is recorded in `typescript_index` on the record; a record that is nothing but its "
            "extra keys is modelled as a map."
        ),
        f"{language}.intersection": (
            "A combination of shapes that are not all records cannot be merged into one record. "
            "The first member is modelled and the combination is recorded."
        ),
        f"{language}.unmodelled_reference": (
            "A field that refers to a definition which was itself left out of the model cannot "
            "point at a modelled type, so the field is left out too."
        ),
        f"{language}.unrepresentable": (
            f"A {label} definition or field that the JSON Schema projection cannot express at all "
            "is left out of the model rather than modelled as any value."
        ),
    }


#: The model-level limits whose construct is still modelled (see :func:`model_limit_details`).
MODEL_PARTIAL_SUFFIXES: Tuple[str, ...] = ("tuple_positions", "additional_properties", "intersection")


def model_limit_aliases(language: str) -> Dict[str, str]:
    """The shared model's built-in ``typescript.*`` limit keys, renamed into one vocabulary.

    The generic-only and TypeScript-only keys cannot occur for a typed configuration language
    (its JSON Schema projection has no generics, mapped or conditional types) and fold into
    ``<language>.unrepresentable`` for completeness.
    """
    return {
        "typescript.tuple_positions": f"{language}.tuple_positions",
        "typescript.index_signature": f"{language}.additional_properties",
        "typescript.intersection": f"{language}.intersection",
        "typescript.unmodelled_reference": f"{language}.unmodelled_reference",
        **{
            f"typescript.{key}": f"{language}.unrepresentable"
            for key in (
                "function_type",
                "type_query",
                "lib_type",
                "symbol_key",
                "unresolved_generic",
                "declaration_merging",
                "conditional_type",
                "mapped_type",
                "template_literal_type",
            )
        },
    }


class TypedConfigParseError(Exception):
    """A typed configuration upload could not be read.

    Attributes:
        code: The intake taxonomy code the failure belongs to, or ``None`` to let the pipeline
            classify it.
    """

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TypedConfigDocument:
    """One CUE, Pkl or Dhall upload, as its reader projected it.

    Attributes:
        language: The format key (``cue``, ``pkl`` or ``dhall``).
        root: The root file's name — the one whose definitions are the model.
        files: Every file name in the upload, sorted.
        tool_version: The version banner of the tool that evaluated it (empty when unknown).
        schema: The JSON Schema projection: ``$defs`` holds every definition, including the ones
            another file defines that a definition refers to.
        exports: The root's own definition names, in declaration order.
        limits: ``(construct, location)`` for every construct declared rather than modelled.
        instances: The names of the concrete values the upload defines, which the tool
            validated against the schema but which are data, not schema.
        identity: The name the catalog item takes (the root's main definition).
        sources: File name → source text, kept for the fidelity bag.
    """

    language: str
    root: str
    files: Tuple[str, ...]
    tool_version: str
    schema: Dict[str, Any]
    exports: Tuple[str, ...]
    limits: Tuple[Tuple[str, str], ...] = ()
    instances: Tuple[str, ...] = ()
    identity: Optional[str] = None
    sources: Dict[str, str] = field(default_factory=dict)

    @property
    def definitions(self) -> Dict[str, Any]:
        """The ``$defs`` map: definition name → JSON Schema."""
        defs = self.schema.get("$defs")
        return defs if isinstance(defs, dict) else {}


def pascal_case(text: str) -> str:
    """Turn a module or file name into a type name (``example.beacon`` → ``Beacon``).

    The last dotted segment is used, split on non-alphanumerics, stripped of leading numeric
    parts and joined with each part capitalised; a result that is empty or starts with a digit
    is prefixed with ``"Schema"``.
    """
    tail = re.split(r"[./\\]", text.strip())[-1] if text.strip() else ""
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", tail) if part]
    while len(parts) > 1 and parts[0].isdigit():
        parts = parts[1:]  # a corpus-style `01-minimal-schema` names `MinimalSchema`
    name = "".join(part[:1].upper() + part[1:] for part in parts)
    if not name or name[0].isdigit():
        name = f"Schema{name}"
    return name


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from a tool's output."""
    return _ANSI_RE.sub("", text or "")


def _safe_member_path(name: str) -> Optional[PurePosixPath]:
    """The member's relative path, or ``None`` when it would escape the workspace."""
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or not path.parts or any(part in ("..", "") for part in path.parts):
        return None
    return path


def guard_input(
    files: Mapping[str, str],
    *,
    label: str,
    where: str,
    max_bytes: int = MAX_TYPED_CONFIG_BYTES,
) -> None:
    """Reject input that must never reach a tool, with the taxonomy code it deserves.

    Args:
        files: File name → source.
        label: The language's display name, for messages (``"CUE"``).
        where: The `` (label)`` suffix for messages.
        max_bytes: The size ceiling of the whole upload.

    Raises:
        TypedConfigParseError: For an empty, oversized or non-UTF-8 upload, or a member whose
            path is absolute or climbs out of the upload.
    """
    if not any(text.strip() for text in files.values()):
        raise TypedConfigParseError(f"The {label} source is empty{where}.", code="INPUT_EMPTY")
    size = sum(len(text.encode("utf-8", "ignore")) for text in files.values())
    if size > max_bytes:
        raise TypedConfigParseError(
            f"The {label} source is {size} bytes{where}, above the {max_bytes}-byte import limit.",
            code="INPUT_TOO_LARGE",
        )
    for name, text in sorted(files.items()):
        if text.startswith("﻿") or any(marker in text for marker in _ENCODING_FAULT_MARKERS):
            raise TypedConfigParseError(
                f"{name} is not UTF-8 text (it looks like UTF-16 or binary){where}.",
                code="INPUT_ENCODING_INVALID",
            )
        if _safe_member_path(name) is None:
            raise TypedConfigParseError(
                f"{name!r} is not a relative path inside the upload{where}.",
                code="INPUT_SEMANTIC_INVALID",
            )


@contextmanager
def workspace(files: Mapping[str, str]) -> Iterator[Path]:
    """Lay an upload out in a private temporary directory, and remove it afterwards.

    The directory doubles as the tool's ``HOME`` and cache (see :func:`run_typed_config_tool`),
    so nothing a tool writes outlives the call or lands in the service's own home.

    Args:
        files: Relative path → text; every path must have passed :func:`guard_input`.

    Yields:
        The directory's path.
    """
    root = Path(tempfile.mkdtemp(prefix="apiome-typed-config-"))
    try:
        for name, text in files.items():
            relative = _safe_member_path(name)
            if relative is None:  # pragma: no cover - guard_input rejects these first
                continue
            target = root.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


@dataclass(frozen=True)
class ToolFailure:
    """A tool that ran and exited non-zero: what it printed, with colour codes removed.

    Attributes:
        exit_code: The process exit status.
        output: stderr, then stdout, joined and stripped of ANSI escapes.
    """

    exit_code: int
    output: str


def run_typed_config_tool(
    tool_key: str,
    args: Sequence[str],
    *,
    cwd: Path,
    label: str,
    where: str,
    stdin: Optional[str] = None,
    timeout: float = TOOL_TIMEOUT_SECONDS,
) -> "ToolRunResult | ToolFailure":
    """Run a bundled language tool inside ``cwd`` under the untrusted-code sandbox.

    The policy is :meth:`~app.toolchain_sandbox.SandboxPolicy.for_untrusted_code`: network
    isolation forced on and *strict* (if the kernel cannot isolate the network, the import fails
    rather than evaluating with network access). ``HOME`` and the XDG cache point into ``cwd``.

    Args:
        tool_key: The bundled tool's registry key.
        args: The tool's arguments.
        cwd: The workspace the upload was laid out in.
        label: The language's display name, for messages.
        where: The `` (label)`` suffix for messages.
        stdin: Text fed to the tool's standard input.
        timeout: The wall-clock ceiling of the call.

    Returns:
        The :class:`~app.toolchain_runner.ToolRunResult` of a clean run, or a
        :class:`ToolFailure` when the tool exited non-zero (the caller reads its output to
        classify the rejection).

    Raises:
        TypedConfigParseError: When the tool is not installed (``ADAPTER_UNAVAILABLE``), runs
            out of time (``INPUT_TIME_LIMIT``) or fails in the runner itself
            (``INTERNAL_ADAPTER_FAULT``).
    """
    env = {
        "HOME": str(cwd),
        "XDG_CACHE_HOME": str(cwd / ".cache"),
        "XDG_CONFIG_HOME": str(cwd / ".config"),
        "NO_COLOR": "1",
    }
    try:
        return run_tool_blocking(
            tool_key,
            list(args),
            stdin=stdin,
            timeout=timeout,
            policy=default_runner.default_policy.for_untrusted_code(),
            thread_name=f"{tool_key}-eval",
            cwd=str(cwd),
            extra_env=env,
        )
    except ToolNotAvailableError as exc:
        raise TypedConfigParseError(
            f"The {label} toolchain is not available in this runtime{where}; {label} import "
            "needs the bundled toolchain (see docs/toolchain_packaging.md).",
            code="ADAPTER_UNAVAILABLE",
        ) from exc
    except ToolTimeoutError as exc:
        raise TypedConfigParseError(
            f"Evaluating the {label} source took longer than {timeout:.0f} s{where} — an "
            "evaluation that does not finish (a runaway comprehension or recursion?).",
            code="INPUT_TIME_LIMIT",
        ) from exc
    except ToolExecutionError as exc:
        output = "\n".join(part for part in (exc.stderr, exc.stdout) if part and part.strip())
        return ToolFailure(exit_code=exc.exit_code, output=_scrub(strip_ansi(output), cwd).strip())
    except ToolchainError as exc:
        raise TypedConfigParseError(
            f"The {label} toolchain failed{where}: {exc}", code="INTERNAL_ADAPTER_FAULT"
        ) from exc


#: A double-quoted string literal (with escapes), removed before brackets are counted.
_STRING_LITERAL_RE = re.compile(r'"(?:\\.|[^"\\])*"')

#: Characters a line cannot end with when the statement on it is complete.
_CONTINUATION_CHARS = "&|,=:(<[{+-*/.\\"

#: Bracket pairs counted on the last line. A ``<`` followed by ``=``, ``-`` or a digit is a
#: comparison, not an opening angle (CUE ``<=99``, Pkl ``length < 5``), and is not counted.
_OPENERS = {"(": ")", "[": "]", "{": "}"}
_ANGLE_OPEN_RE = re.compile(r"<(?![=\-\d\s]*\d)(?!=)")


def _line_is_unfinished(line: str) -> bool:
    """Whether a source line stops in the middle of an expression."""
    if line.count('"') - len(_STRING_LITERAL_RE.findall(line)) * 2 > 0:
        return True  # an unterminated string literal
    bare = _STRING_LITERAL_RE.sub('""', line).rstrip()
    if not bare:
        return False
    if bare[-1] in _CONTINUATION_CHARS:
        return True
    if any(bare.count(opener) > bare.count(closer) for opener, closer in _OPENERS.items()):
        return True
    return len(_ANGLE_OPEN_RE.findall(bare)) > bare.count(">")


def _scrub(text: str, cwd: Path) -> str:
    """Replace the private workspace path in a tool's message with the upload's own names."""
    root = str(cwd)
    while root and "apiome-typed-config-" not in PurePosixPath(root).name and root != "/":
        root = str(PurePosixPath(root).parent)
    if "apiome-typed-config-" not in root:
        root = str(cwd)
    return text.replace(f"file://{root}/", "").replace(f"{root}/", "").replace(root, ".")


def syntax_error_code(text: Optional[str]) -> str:
    """Tell a file cut off mid-construct from one that is simply malformed.

    A tool reports both as "unexpected end of input". The difference this reader can see is the
    file itself: a truncated file stops *inside* an expression — its last line ends on an
    operator or a separator, leaves a bracket or a string open, or has no newline — while a
    malformed one ends on a complete line and is simply missing a closing brace or keyword.

    Args:
        text: The source of the file the syntax error is in, when known.

    Returns:
        ``INPUT_TRUNCATED`` when the file stops mid-expression, else ``INPUT_MALFORMED``.
    """
    if text is None or not text.strip():
        return "INPUT_MALFORMED"
    if not text.endswith("\n"):
        return "INPUT_TRUNCATED"
    last = next(line for line in reversed(text.splitlines()) if line.strip())
    return "INPUT_TRUNCATED" if _line_is_unfinished(last) else "INPUT_MALFORMED"


def first_lines(text: str, count: int = 6) -> str:
    """The first ``count`` non-empty lines of a tool's error output, joined for a message."""
    lines: List[str] = [line.rstrip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[:count])
