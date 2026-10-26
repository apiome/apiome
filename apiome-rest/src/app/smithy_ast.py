"""Smithy model assembly through the Smithy CLI → JSON AST — MFI-17.1 (#3808).

A Smithy model is usually split across files: shapes in one ``.smithy`` file target shapes in
another, by absolute shape id or through ``use`` statements, and a namespace may span files.
The **Smithy CLI** (``toolchain_packaging.BundledTool`` key ``smithy``) is the authority that
assembles them: ``smithy ast <files>`` loads every file, validates the combined model, and
writes it as one **JSON AST** — every shape keyed by its absolute id, every reference already
absolute — which is read here with plain :mod:`json`.

This module is the Python seam over that CLI, run through the polyglot toolchain runner:

1. :func:`stage_smithy_members` writes the set's model files (``.smithy`` and JSON AST ``.json``)
   into a private temporary directory. Other members — a ``smithy-build.json`` in particular,
   which could pull Maven dependencies over the network — are never staged.
2. :func:`run_smithy_ast` runs ``smithy ast --allow-unknown-traits <files>`` from a separate,
   empty working directory (so no build configuration is ever picked up) and parses the AST.
   Traits from packages that are not bundled (``aws.protocols#restJson1``) are allowed rather
   than failing the import; their values are kept in the AST.
3. :func:`ast_sha256` fingerprints the assembled model (``sort_keys`` JSON), not the raw bytes.
4. :mod:`app.smithy_ast_mapper` turns the AST into the
   :class:`~app.smithy_parser.SmithyDocument` the normalizer consumes, recording the model's
   ``$version`` and namespaces.

A JSON AST uploaded on its own needs no CLI: :func:`parse_smithy_ast_text` reads it directly.
Every failure is an :class:`~app.import_source.ImportSourceError` with an intake-taxonomy code.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .fileset import normalize_member_path
from .import_source import ImportSourceError
from .smithy_ast_mapper import document_from_ast, is_smithy_ast_document
from .smithy_parser import SmithyDocument
from .toolchain_runner import (
    ToolchainError,
    ToolExecutionError,
    ToolNotAvailableError,
    ToolTimeoutError,
    run_tool_blocking,
)

__all__ = [
    "SMITHY_TIMEOUT_SECONDS",
    "SMITHY_TOOL_KEY",
    "assemble_smithy_set",
    "ast_sha256",
    "is_smithy_ast_text",
    "model_members",
    "parse_smithy_ast_text",
    "run_smithy_ast",
    "smithy_cli_available",
    "stage_smithy_members",
]

#: Registry key of the bundled Smithy CLI (declared in :mod:`app.toolchain_packaging`).
SMITHY_TOOL_KEY = "smithy"

#: Wall-clock limit for one ``smithy ast``.
SMITHY_TIMEOUT_SECONDS = 120.0

#: Most validation messages quoted in an error.
_MAX_REPORTED_EVENTS = 10

#: A Smithy validation event line (``ERROR: ns#Shape: message`` / ``── ERROR ──``), and an
#: error-severity marker in either of the CLI's output styles.
_EVENT_RE = re.compile(r"\b(ERROR|DANGER)\b")


def smithy_cli_available() -> bool:
    """Whether the ``smithy`` tool can be resolved in this runtime (a cheap ``PATH`` lookup)."""
    from .toolchain_packaging import probe_tool, register_bundled_tools

    register_bundled_tools()
    return bool(probe_tool(SMITHY_TOOL_KEY).available)


def is_smithy_ast_text(text: str) -> bool:
    """Whether ``text`` is a Smithy JSON AST model (``{"smithy": "2.0", "shapes": {...}}``)."""
    if not isinstance(text, str) or not text.lstrip().startswith("{") or '"smithy"' not in text:
        return False
    try:
        return is_smithy_ast_document(json.loads(text))
    except ValueError:
        return False


def model_members(members: Mapping[str, str]) -> Dict[str, str]:
    """The set's model files: ``.smithy`` IDL and JSON AST ``.json`` files.

    Args:
        members: The set's members, path → text.

    Returns:
        The model files, path → text. A ``smithy-build.json`` and any other file are left out.
    """
    models: Dict[str, str] = {}
    for path, text in members.items():
        name = posixpath.basename(path.replace("\\", "/")).lower()
        if name == "smithy-build.json":
            continue
        if name.endswith(".smithy") or (name.endswith(".json") and is_smithy_ast_text(text)):
            models[path] = text
    return models


def ast_sha256(ast: Mapping[str, Any]) -> str:
    """Fingerprint an assembled model: SHA-256 of its JSON with sorted keys.

    Args:
        ast: The JSON AST.

    Returns:
        Hex digest; equal for the same model however its files were split or ordered.
    """
    canonical = json.dumps(ast, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def stage_smithy_members(members: Mapping[str, str], directory: Path) -> List[Path]:
    """Write the model files under ``directory``.

    Args:
        members: The model files, path → text (see :func:`model_members`).
        directory: An empty, private directory.

    Returns:
        The files written, in sorted member order.

    Raises:
        ImportSourceError: ``INPUT_ARCHIVE_INVALID`` for a member path outside the set.
    """
    written: List[Path] = []
    for member in sorted(members):
        normalized = normalize_member_path(member)
        if normalized is None:
            raise ImportSourceError(
                f"Smithy file path {member!r} is not a relative path inside the upload.",
                code="INPUT_ARCHIVE_INVALID",
            )
        target = directory / normalized
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(members[member], encoding="utf-8")
        written.append(target)
    return written


def _scrub(text: str, staging_dir: Path) -> str:
    """``text`` with the staging directory's path removed (members show as set paths)."""
    prefix = str(staging_dir.resolve())
    return text.replace(prefix + "/", "").replace(prefix, "")


def _validation_events(output: str, staging_dir: Path) -> List[str]:
    """The error lines of a failed ``smithy ast`` run, scrubbed of the staging path."""
    lines = [line.strip(" ─-") for line in _scrub(output, staging_dir).splitlines()]
    events = [line for line in lines if line and _EVENT_RE.search(line)]
    if not events:
        events = [line for line in lines if line][:3]
    return events[:_MAX_REPORTED_EVENTS]


def run_smithy_ast(files: List[Path], *, staging_dir: Path, work_dir: Path) -> Dict[str, Any]:
    """Run ``smithy ast`` on staged model files and return the parsed JSON AST.

    Args:
        files: The staged model files.
        staging_dir: Where they were staged (scrubbed from messages).
        work_dir: An empty directory used as the working directory and ``HOME``.

    Returns:
        The JSON AST.

    Raises:
        ImportSourceError: ``ADAPTER_UNAVAILABLE`` when the CLI is missing,
            ``INPUT_TIME_LIMIT`` on timeout, ``INPUT_SEMANTIC_INVALID`` when the model does not
            validate (the CLI's errors quoted), ``INPUT_MALFORMED`` when no AST came back.
    """
    args = ["ast", "--allow-unknown-traits", *[str(path) for path in files]]
    try:
        result = run_tool_blocking(
            SMITHY_TOOL_KEY,
            args,
            timeout=SMITHY_TIMEOUT_SECONDS,
            thread_name="smithy-ast",
            cwd=str(work_dir),
            extra_env={"HOME": str(work_dir)},
        )
    except ToolNotAvailableError as exc:
        raise ImportSourceError(
            "Assembling a multi-file Smithy model needs the bundled Smithy CLI, which is not "
            "available on this server (see docs/toolchain_packaging.md).",
            code="ADAPTER_UNAVAILABLE",
        ) from exc
    except ToolTimeoutError as exc:
        raise ImportSourceError(
            f"The Smithy CLI took longer than {SMITHY_TIMEOUT_SECONDS:.0f} s to assemble the model.",
            code="INPUT_TIME_LIMIT",
        ) from exc
    except ToolExecutionError as exc:
        events = _validation_events(f"{exc.stderr}\n{exc.stdout}", staging_dir)
        raise ImportSourceError(
            f"The Smithy model does not validate: {'; '.join(events) or 'the CLI reported an error'}",
            code="INPUT_SEMANTIC_INVALID",
        ) from exc
    except ToolchainError as exc:
        raise ImportSourceError(
            f"The Smithy CLI could not assemble the model: {_scrub(str(exc), staging_dir)}",
            code="INPUT_MALFORMED",
        ) from exc
    try:
        ast = json.loads(result.stdout or "")
    except ValueError:
        ast = None
    if not is_smithy_ast_document(ast):
        raise ImportSourceError(
            "The Smithy CLI did not return a JSON AST model.", code="INPUT_MALFORMED"
        )
    return ast


def _source_files(members: Mapping[str, str]) -> Tuple[str, ...]:
    """The model files' normalized paths, sorted."""
    return tuple(sorted(filter(None, (normalize_member_path(m) for m in members))))


def assemble_smithy_set(
    members: Mapping[str, str],
    root: str,
    *,
    source_label: Optional[str] = None,
) -> SmithyDocument:
    """Assemble a set of Smithy model files through the CLI into a :class:`SmithyDocument`.

    Args:
        members: The set's members, path → text (non-model files are ignored).
        root: The root document's path (kept as the document's ``raw``).
        source_label: Label used in error messages.

    Returns:
        The document, with its namespaces, AST hash and source files recorded.

    Raises:
        ImportSourceError: ``INPUT_ARCHIVE_INVALID`` when the root is missing or the set has no
            model files; see :func:`run_smithy_ast` and
            :func:`app.smithy_ast_mapper.document_from_ast`.
    """
    if root not in members:
        raise ImportSourceError("Smithy fileset is missing its root document", code="INPUT_ARCHIVE_INVALID")
    models = model_members(members)
    if not models:
        raise ImportSourceError(
            "The Smithy fileset holds no model files (.smithy, or a JSON AST .json).",
            code="INPUT_ARCHIVE_INVALID",
        )
    staging_dir = Path(tempfile.mkdtemp(prefix="apiome-smithy-models-"))
    work_dir = Path(tempfile.mkdtemp(prefix="apiome-smithy-work-"))
    try:
        files = stage_smithy_members(models, staging_dir)
        ast = run_smithy_ast(files, staging_dir=staging_dir, work_dir=work_dir)
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
        shutil.rmtree(work_dir, ignore_errors=True)
    return document_from_ast(
        ast,
        raw=members[root],
        model_sha256=ast_sha256(ast),
        source_files=_source_files(models),
        source_label=source_label or root,
    )


def parse_smithy_ast_text(text: str, *, source_label: Optional[str] = None) -> SmithyDocument:
    """Read one JSON AST model directly (no CLI needed).

    Args:
        text: The JSON AST text.
        source_label: Label used in error messages.

    Returns:
        The document.

    Raises:
        ImportSourceError: See :func:`app.smithy_ast_mapper.document_from_ast`.
    """
    try:
        ast = json.loads(text)
    except ValueError as exc:
        raise ImportSourceError(f"Smithy JSON AST is not valid JSON: {exc}", code="INPUT_MALFORMED") from exc
    return document_from_ast(
        ast,
        raw=text,
        model_sha256=ast_sha256(ast) if is_smithy_ast_document(ast) else None,
        source_label=source_label,
    )
