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
   ``tspconfig.yaml`` emitting ``@typespec/openapi3``, with the safe settings of an uploaded
   ``tspconfig.yaml`` beside the root merged in (MFI-14.5, :mod:`app.typespec_config`);
3. links the bundled TypeSpec libraries (:func:`typespec_node_modules`) in as ``node_modules``,
   so ``import "@typespec/http"`` resolves as it would in a project;
4. runs ``tsp compile <root> --output-dir <out>`` and reads the emitted OpenAPI
   (:func:`read_typespec_openapi_output`).

Compile errors (``models/pets.tsp:9:11 - error invalid-ref: Unknown identifier``) become
``INPUT_SEMANTIC_INVALID`` with each diagnostic quoted. The *warnings* of a successful compile —
the compiler's own (``deprecated``), the libraries', and the built-in linter rules Apiome enables
(``@typespec/http/op-reference-container-route``, MFI-14.3) — are kept on
:attr:`TypeSpecCompiled.diagnostics` for the ``typespec`` lint pack (:mod:`app.typespec_lint`).
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
from .typespec_config import TypeSpecConfig, build_tspconfig, find_tspconfig, resolve_tspconfig
from .typespec_versioning import TypeSpecVersion, declared_versions, order_versions

__all__ = [
    "OPENAPI_TSPCONFIG",
    "TSP_NODE_MODULES_ENV",
    "TSP_TIMEOUT_SECONDS",
    "TSP_TOOL_KEY",
    "TypeSpecCompiled",
    "TypeSpecDiagnostic",
    "check_import_targets",
    "compile_typespec_set",
    "find_import_targets",
    "link_typespec_libraries",
    "openapi_sha256",
    "parse_diagnostics",
    "read_typespec_openapi_output",
    "read_typespec_openapi_outputs",
    "typespec_node_modules",
    "typespec_members",
]

#: Registry key of the bundled TypeSpec compiler.
TSP_TOOL_KEY = "tsp"

#: Environment variable naming the ``node_modules`` that holds the TypeSpec libraries.
TSP_NODE_MODULES_ENV = "APIOME_TSP_NODE_MODULES"

#: Wall-clock limit for one ``tsp compile``.
TSP_TIMEOUT_SECONDS = 120.0

#: The project configuration written next to the staged files: emit OpenAPI 3 as one JSON file
#: (an uploaded ``tspconfig.yaml`` adds its honored settings, :mod:`app.typespec_config`).
OPENAPI_TSPCONFIG = build_tspconfig()

_IMPORT_RE = re.compile(r"""^\s*import\s+["']([^"']+)["']\s*;""", re.MULTILINE)
_NAMESPACE_RE = re.compile(r"^\s*namespace\s+([A-Za-z_][\w.]*)", re.MULTILINE)
#: One diagnostic line: an optional ``file:line:column - `` location, the severity, the code (a
#: library's codes are prefixed with its name: ``@typespec/http/op-reference-container-route``) and
#: the message.
_DIAGNOSTIC_RE = re.compile(
    r"^(?:(?P<file>\S.*?):(?P<line>\d+):(?P<column>\d+) - )?(?P<severity>error|warning) "
    r"(?P<code>[\w@./-]+): (?P<message>.*)$",
    re.MULTILINE,
)
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
        config: The uploaded ``tspconfig.yaml`` as Apiome read it (MFI-14.5); ``None`` when the
            project had none.
        diagnostics: The warnings the compile reported (MFI-14.3): compiler, library and built-in
            linter diagnostics, in the order reported.
        versions: For a ``@versioned`` service, every version's emitted OpenAPI, oldest first
            (MFI-14.4); :attr:`openapi` is the newest. Empty for an unversioned service.
    """

    openapi: Dict[str, Any]
    root_text: str
    source_files: Tuple[str, ...]
    namespaces: Tuple[str, ...]
    openapi_sha256: str
    config: Optional[TypeSpecConfig] = None
    diagnostics: Tuple[TypeSpecDiagnostic, ...] = ()
    versions: Tuple[TypeSpecVersion, ...] = ()


@dataclass(frozen=True)
class TypeSpecDiagnostic:
    """One diagnostic the TypeSpec compiler reported.

    Attributes:
        severity: ``warning`` or ``error``.
        code: The diagnostic code (``deprecated``, ``@typespec/http/op-reference-container-route``).
        message: The compiler's message.
        file: The ``.tsp`` file, relative to the project (``None`` when the diagnostic has no location).
        line: 1-based line, or ``None``.
        column: 1-based column, or ``None``.
    """

    severity: str
    code: str
    message: str
    file: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None

    def as_dict(self) -> Dict[str, Any]:
        """The diagnostic as a JSON-ready dict (location keys only when located)."""
        data: Dict[str, Any] = {"severity": self.severity, "code": self.code, "message": self.message}
        if self.file is not None:
            data.update(file=self.file, line=self.line, column=self.column)
        return data


def parse_diagnostics(output: str) -> List[TypeSpecDiagnostic]:
    """Read the diagnostics out of ``tsp compile`` output.

    The code-frame lines the compiler prints under each diagnostic (``> 19 | …``) and its summary
    (``Found 2 warnings.``) are not diagnostics and are skipped; a repeated diagnostic is kept once.

    Args:
        output: The compiler's stdout and stderr, already scrubbed of the staging path.

    Returns:
        The diagnostics, in the order the compiler reported them.
    """
    found: List[TypeSpecDiagnostic] = []
    for match in _DIAGNOSTIC_RE.finditer(output):
        diagnostic = TypeSpecDiagnostic(
            severity=match["severity"],
            code=match["code"],
            message=match["message"].strip(),
            file=match["file"],
            line=int(match["line"]) if match["line"] else None,
            column=int(match["column"]) if match["column"] else None,
        )
        if diagnostic not in found:
            found.append(diagnostic)
    return found


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


def read_typespec_openapi_outputs(output_dir: Path) -> List[Dict[str, Any]]:
    """Every OpenAPI 3 document ``@typespec/openapi3`` emitted under ``output_dir`` (MFI-14.4).

    A ``@versioned`` service emits one ``openapi.<version>.json`` per version; any other service one
    ``openapi.json``.

    Args:
        output_dir: The compile's ``--output-dir``.

    Returns:
        The documents, in file-name order (the caller orders versions).
    """
    if not output_dir.is_dir():
        return []
    documents: List[Dict[str, Any]] = []
    for path in sorted(output_dir.rglob("*.json")):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if _is_openapi3(data):
            documents.append(data)
    return documents


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
    matches = list(_DIAGNOSTIC_RE.finditer(scrubbed))
    lines = [m.group(0).strip() for m in matches]
    errors = [m.group(0).strip() for m in matches if m["severity"] == "error"] or lines
    if not errors:
        errors = [line.strip() for line in scrubbed.splitlines() if line.strip()][-3:]
    return errors[:_MAX_REPORTED_DIAGNOSTICS]


def _run_compile(
    root: str, staging_dir: Path, output_dir: Path, home: Path
) -> Tuple[List[Dict[str, Any]], List[TypeSpecDiagnostic]]:
    """Run ``tsp compile``; return the emitted OpenAPI document(s) and the compile's warnings."""
    try:
        result = run_tool_blocking(
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
    documents = read_typespec_openapi_outputs(output_dir)
    if not documents:
        document = read_typespec_openapi_output(output_dir)
        documents = [document] if document is not None else []
    if not documents:
        raise ImportSourceError(
            "The TypeSpec compiler emitted no OpenAPI document.", code="INPUT_MALFORMED"
        )
    output = _scrub(f"{result.stdout}\n{result.stderr}", staging_dir)
    return documents, parse_diagnostics(output)


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
    config_path = find_tspconfig(members, root)
    config = resolve_tspconfig(members[config_path], path=config_path) if config_path else None

    staging_dir = Path(tempfile.mkdtemp(prefix="apiome-tsp-set-"))
    scratch = Path(tempfile.mkdtemp(prefix="apiome-tsp-run-"))
    try:
        for path, normalized in staged_paths.items():
            target = staging_dir / normalized
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(sources[path], encoding="utf-8")
        (staging_dir / "tspconfig.yaml").write_text(
            build_tspconfig(config.applied if config else None), encoding="utf-8"
        )
        link_typespec_libraries(staging_dir)
        documents, diagnostics = _run_compile(staged_paths[root], staging_dir, scratch / "out", scratch)
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
        shutil.rmtree(scratch, ignore_errors=True)

    namespaces = sorted({ns for text in sources.values() for ns in _NAMESPACE_RE.findall(text)})
    versions: Tuple[TypeSpecVersion, ...] = ()
    if len(documents) > 1:
        # MFI-14.4: a @versioned service — one document per version, oldest first; the catalog
        # item is the newest.
        ordered = order_versions(documents, declared_versions(sources))
        versions = tuple(
            TypeSpecVersion(version=version, openapi=doc, openapi_sha256=openapi_sha256(doc))
            for version, doc in ordered
        )
        document = versions[-1].openapi
    else:
        document = documents[0]
    return TypeSpecCompiled(
        openapi=document,
        root_text=sources[root],
        source_files=tuple(sorted(staged_paths.values())),
        namespaces=tuple(namespaces),
        openapi_sha256=openapi_sha256(document),
        config=config,
        diagnostics=tuple(diagnostics),
        versions=versions,
    )
