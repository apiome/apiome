"""TypeSpec compile via the toolchain runner — MFI-14.1 (#3794).

A TypeSpec API is usually split across files: the root ``import``\\s its siblings
(``import "./models/pets.tsp"``) and TypeSpec libraries (``import "@typespec/http"``). The
TypeSpec compiler (``toolchain_packaging.BundledTool`` key ``tsp``) is the authority that
resolves all of it. Following the epic, the compiler's **emitted OpenAPI** is the integration
surface: a compiled set is normalized by the existing OpenAPI normalizer, so its diff and lint are
the OpenAPI ones (see :mod:`app.typespec_import_source`).

:func:`compile_typespec_set`:

1. checks every relative ``import`` stays inside the uploaded set (``INPUT_REFERENCE_UNRESOLVED``);
2. stages only the ``.tsp`` members in a private temporary directory — never an uploaded
   ``tspconfig.yaml``, ``package.json`` or ``node_modules`` — and writes Apiome's own
   ``tspconfig.yaml`` emitting ``@typespec/openapi3``;
3. links the bundled TypeSpec libraries (:func:`typespec_node_modules`) in as ``node_modules``,
   so ``import "@typespec/http"`` resolves as it would in a project;
4. runs ``tsp compile <root> --output-dir <out>`` and reads the emitted OpenAPI
   (:func:`read_typespec_openapi_output`).

Compile diagnostics (``models/pets.tsp:9:11 - error invalid-ref: Unknown identifier``) become
``INPUT_SEMANTIC_INVALID`` with each diagnostic quoted.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .fileset import normalize_member_path, resolve_relative_reference
from .import_ingestion import IngestionError, parse_document
from .import_source import ImportSourceError
from .toolchain_runner import (
    ToolchainError,
    ToolExecutionError,
    ToolNotAvailableError,
    ToolTimeoutError,
    run_tool_blocking,
)

__all__ = [
    "OPENAPI_TSPCONFIG",
    "TSP_NODE_MODULES_ENV",
    "TSP_TIMEOUT_SECONDS",
    "TSP_TOOL_KEY",
    "TypeSpecCompiled",
    "check_import_targets",
    "compile_typespec_set",
    "find_import_targets",
    "link_typespec_libraries",
    "openapi_sha256",
    "read_typespec_openapi_output",
    "typespec_node_modules",
    "typespec_members",
]

#: Registry key of the bundled TypeSpec compiler.
TSP_TOOL_KEY = "tsp"

#: Environment variable naming the ``node_modules`` that holds the TypeSpec libraries.
TSP_NODE_MODULES_ENV = "APIOME_TSP_NODE_MODULES"

#: Wall-clock limit for one ``tsp compile``.
TSP_TIMEOUT_SECONDS = 120.0

#: The project configuration written next to the staged files: emit OpenAPI 3 as one JSON file.
OPENAPI_TSPCONFIG = "\n".join(
    [
        "emit:",
        '  - "@typespec/openapi3"',
        "options:",
        '  "@typespec/openapi3":',
        "    output-file: openapi.json",
        "",
    ]
)

_IMPORT_RE = re.compile(r"""^\s*import\s+["']([^"']+)["']\s*;""", re.MULTILINE)
_NAMESPACE_RE = re.compile(r"^\s*namespace\s+([A-Za-z_][\w.]*)", re.MULTILINE)
_DIAGNOSTIC_RE = re.compile(r"^\S.*:\d+:\d+ - (error|warning) [\w-]+: .*$", re.MULTILINE)
_MAX_REPORTED_DIAGNOSTICS = 10


@dataclass(frozen=True)
class TypeSpecCompiled:
    """A TypeSpec set compiled to OpenAPI.

    Attributes:
        openapi: The OpenAPI 3 document ``@typespec/openapi3`` emitted.
        root_text: The root document's text.
        source_files: Every ``.tsp`` file of the set.
        namespaces: The namespaces the set declares, in sorted order.
        openapi_sha256: SHA-256 of the emitted document (sorted-key JSON).
    """

    openapi: Dict[str, Any]
    root_text: str
    source_files: Tuple[str, ...]
    namespaces: Tuple[str, ...]
    openapi_sha256: str


def typespec_members(members: Mapping[str, str]) -> Dict[str, str]:
    """The set's ``.tsp`` files (anything else — configuration, packages — is left out)."""
    return {path: text for path, text in members.items() if path.lower().endswith(".tsp")}


def find_import_targets(text: str) -> List[str]:
    """The ``import`` targets of a TypeSpec file, as written (libraries and files alike)."""
    return _IMPORT_RE.findall(text)


def _is_library(target: str) -> bool:
    """Whether an import names a library (``@typespec/http``, ``my-lib``) rather than a file."""
    return not target.startswith((".", "/", "\\")) and not re.match(r"^[A-Za-z][\w+.-]*:", target)


def check_import_targets(members: Mapping[str, str]) -> None:
    """Refuse a set whose file imports leave it or name a file that is not in it.

    Args:
        members: The ``.tsp`` files, path → text.

    Raises:
        ImportSourceError: ``INPUT_REFERENCE_UNRESOLVED`` naming each refused import.
    """
    normalized = {normalize_member_path(path) for path in members}
    outside: List[str] = []
    missing: List[str] = []
    for path, text in members.items():
        for target in find_import_targets(text):
            if _is_library(target):
                continue
            resolved = resolve_relative_reference(normalize_member_path(path) or path, target)
            if resolved is None:
                outside.append(f"{path} → {target}")
            elif resolved not in normalized:
                missing.append(f"{path} → {target}")
    if outside:
        raise ImportSourceError(
            "TypeSpec imports must be relative paths inside the uploaded files; these point "
            f"outside them and were not read: {', '.join(outside)}.",
            code="INPUT_REFERENCE_UNRESOLVED",
        )
    if missing:
        raise ImportSourceError(
            f"TypeSpec imports name files that are not in the upload: {', '.join(missing)}. "
            "Add them to the archive.",
            code="INPUT_REFERENCE_UNRESOLVED",
        )


def typespec_node_modules() -> Optional[Path]:
    """The ``node_modules`` directory that holds the bundled TypeSpec libraries.

    Taken from :data:`TSP_NODE_MODULES_ENV` when set, otherwise found from where the ``tsp``
    executable resolves: the runtime image's ``<prefix>/bin/tsp`` wrapper sits beside
    ``<prefix>/lib/node/node_modules``, and an npm install's ``node_modules/.bin/tsp`` sits inside
    its ``node_modules``.

    Returns:
        A directory containing ``@typespec``, or ``None`` when none is found.
    """
    override = os.environ.get(TSP_NODE_MODULES_ENV)
    candidates: List[Path] = [Path(override)] if override else []
    from .toolchain_packaging import probe_tool, register_bundled_tools

    register_bundled_tools()
    probe = probe_tool(TSP_TOOL_KEY)
    if probe is not None and probe.resolved_path:
        for executable in (Path(probe.resolved_path), Path(probe.resolved_path).resolve()):
            candidates.append(executable.parent.parent / "lib" / "node" / "node_modules")
            candidates.extend(p for p in executable.parents if p.name == "node_modules")
    for candidate in candidates:
        if (candidate / "@typespec").is_dir():
            return candidate
    return None


def link_typespec_libraries(project_dir: Path) -> bool:
    """Link the bundled TypeSpec libraries into ``project_dir`` as ``node_modules``.

    Args:
        project_dir: A staged TypeSpec project.

    Returns:
        ``True`` when the libraries were found and linked.
    """
    libraries = typespec_node_modules()
    if libraries is None:
        return False
    (project_dir / "node_modules").symlink_to(libraries, target_is_directory=True)
    return True


def _is_openapi3(document: Any) -> bool:
    """Whether ``document`` is an OpenAPI 3 document."""
    version = document.get("openapi") if isinstance(document, dict) else None
    return isinstance(version, str) and version.startswith("3.")


def read_typespec_openapi_output(output_dir: Path) -> Optional[Dict[str, Any]]:
    """Find and parse the OpenAPI JSON/YAML ``@typespec/openapi3`` emitted under ``output_dir``.

    Args:
        output_dir: The compile's ``--output-dir``.

    Returns:
        The first OpenAPI 3 document found, or ``None``.
    """
    if not output_dir.is_dir():
        return None
    candidates: List[Path] = []
    for pattern in ("**/openapi.json", "**/*.openapi.json", "**/openapi.yaml", "**/openapi.yml"):
        candidates.extend(sorted(output_dir.glob(pattern)))
    for path in sorted(output_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".json", ".yaml", ".yml"} and path not in candidates:
            candidates.append(path)

    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if path.suffix.lower() == ".json":
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
        else:
            try:
                data = parse_document(text, source_label=str(path))
            except IngestionError:
                continue
        if _is_openapi3(data):
            return data
    return None


def openapi_sha256(document: Mapping[str, Any]) -> str:
    """SHA-256 of an OpenAPI document as sorted-key JSON (independent of key order)."""
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _scrub(text: str, directory: Path) -> str:
    """``text`` with ``directory``'s path removed."""
    prefix = str(directory.resolve())
    return text.replace(prefix + "/", "").replace(prefix, "")


def _diagnostics(output: str, staging_dir: Path) -> List[str]:
    """The compiler's error/warning lines, scrubbed of the staging path."""
    scrubbed = _scrub(output, staging_dir)
    lines = [m.group(0).strip() for m in _DIAGNOSTIC_RE.finditer(scrubbed)]
    errors = [line for line in lines if " - error " in line] or lines
    if not errors:
        errors = [line.strip() for line in scrubbed.splitlines() if line.strip()][-3:]
    return errors[:_MAX_REPORTED_DIAGNOSTICS]


def _run_compile(root: str, staging_dir: Path, output_dir: Path, home: Path) -> Dict[str, Any]:
    """Run ``tsp compile`` and return the emitted OpenAPI (see :func:`compile_typespec_set`)."""
    try:
        run_tool_blocking(
            TSP_TOOL_KEY,
            ["compile", root, "--output-dir", str(output_dir)],
            timeout=TSP_TIMEOUT_SECONDS,
            thread_name="tsp-compile",
            cwd=str(staging_dir),
            extra_env={"HOME": str(home)},
        )
    except ToolNotAvailableError as exc:
        raise ImportSourceError(
            "Compiling a multi-file TypeSpec set needs the bundled TypeSpec compiler, which is "
            "not available on this server (see docs/toolchain_packaging.md).",
            code="ADAPTER_UNAVAILABLE",
        ) from exc
    except ToolTimeoutError as exc:
        raise ImportSourceError(
            f"The TypeSpec compiler took longer than {TSP_TIMEOUT_SECONDS:.0f} s.",
            code="INPUT_TIME_LIMIT",
        ) from exc
    except ToolExecutionError as exc:
        found = _diagnostics(f"{exc.stdout}\n{exc.stderr}", staging_dir)
        raise ImportSourceError(
            f"The TypeSpec set does not compile: {'; '.join(found) or 'the compiler reported an error'}",
            code="INPUT_SEMANTIC_INVALID",
        ) from exc
    except ToolchainError as exc:
        raise ImportSourceError(
            f"The TypeSpec compiler failed: {_scrub(str(exc), staging_dir)}", code="INPUT_MALFORMED"
        ) from exc
    document = read_typespec_openapi_output(output_dir)
    if document is None:
        raise ImportSourceError(
            "The TypeSpec compiler emitted no OpenAPI document.", code="INPUT_MALFORMED"
        )
    return document


def compile_typespec_set(
    members: Mapping[str, str],
    root: str,
    *,
    source_label: Optional[str] = None,
) -> TypeSpecCompiled:
    """Compile a TypeSpec set to OpenAPI through ``tsp``.

    Args:
        members: The set's members, path → text (only ``.tsp`` files are used).
        root: The root document's path — the compile's entry point.
        source_label: Label used when the root is missing.

    Returns:
        The compiled set.

    Raises:
        ImportSourceError: ``INPUT_ARCHIVE_INVALID`` when the root is missing or a path leaves
            the set; ``INPUT_REFERENCE_UNRESOLVED`` for an import outside the set or missing
            from it; ``ADAPTER_UNAVAILABLE``, ``INPUT_TIME_LIMIT``, ``INPUT_SEMANTIC_INVALID``,
            ``INPUT_MALFORMED`` from the compile.
    """
    sources = typespec_members(members)
    if root not in sources:
        label = f" ({source_label})" if source_label else ""
        raise ImportSourceError(
            f"TypeSpec fileset is missing its root .tsp document{label}", code="INPUT_ARCHIVE_INVALID"
        )
    staged_paths: Dict[str, str] = {}
    for path in sources:
        normalized = normalize_member_path(path)
        if normalized is None:
            raise ImportSourceError(
                f"TypeSpec file path {path!r} is not a relative path inside the upload.",
                code="INPUT_ARCHIVE_INVALID",
            )
        staged_paths[path] = normalized
    check_import_targets(sources)

    staging_dir = Path(tempfile.mkdtemp(prefix="apiome-tsp-set-"))
    scratch = Path(tempfile.mkdtemp(prefix="apiome-tsp-run-"))
    try:
        for path, normalized in staged_paths.items():
            target = staging_dir / normalized
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(sources[path], encoding="utf-8")
        (staging_dir / "tspconfig.yaml").write_text(OPENAPI_TSPCONFIG, encoding="utf-8")
        link_typespec_libraries(staging_dir)
        document = _run_compile(staged_paths[root], staging_dir, scratch / "out", scratch)
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
        shutil.rmtree(scratch, ignore_errors=True)

    namespaces = sorted({ns for text in sources.values() for ns in _NAMESPACE_RE.findall(text)})
    return TypeSpecCompiled(
        openapi=document,
        root_text=sources[root],
        source_files=tuple(sorted(staged_paths.values())),
        namespaces=tuple(namespaces),
        openapi_sha256=openapi_sha256(document),
    )
