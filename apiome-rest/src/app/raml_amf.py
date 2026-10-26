"""RAML parse / resolve through AMF — MFI-15.1 (#3799).

AMF (aml-org's AML Modeling Framework, the maintained RAML parser) is the authority for
RAML: it parses the root document *and* everything it pulls in — ``!include`` fragments,
``uses`` libraries, external examples — into one resolved model. This module is the
Python seam over the bundled ``amf`` CLI (``toolchain_packaging.BundledTool`` key ``amf``,
a JVM jar behind a wrapper), run through the polyglot toolchain runner:

1. :func:`stage_raml_members` lays the import's files out in a private temporary directory
   after :func:`check_reference_targets` has refused any reference that could read outside
   the set (an absolute path, a URL, or a ``..`` that escapes the set).
2. :func:`run_amf_parse` runs ``amf parse`` on the root with source maps (needed for
   library aliases) and returns the JSON-LD graph. The CLI exits ``0`` even when it throws,
   so success is judged from the output, never the exit code.
3. :func:`amf_model_sha256` hashes the resolved model with every path-dependent detail
   stripped — the fingerprint the issue asks for ("hash the AMF-resolved model, not raw
   bytes").
4. :mod:`app.raml_amf_mapper` turns the graph into the :class:`~app.raml_parser.RamlDocument`
   the RAML normalizer already consumes.

:func:`parse_raml_set_with_amf` runs all four. Every failure is an
:class:`~app.import_source.ImportSourceError` carrying an intake-taxonomy code.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import yaml

from .fileset import resolve_relative_reference
from .import_source import ImportSourceError
from .raml_parser import RamlDocument
from .raml_traits import IncludeAsText
from .toolchain_runner import ToolchainError, ToolNotAvailableError, ToolTimeoutError, run_tool_blocking

__all__ = [
    "AMF_TOOL_KEY",
    "AMF_TIMEOUT_SECONDS",
    "amf_available",
    "amf_model_sha256",
    "check_reference_targets",
    "find_reference_targets",
    "parse_raml_set_with_amf",
    "parse_validation_violations",
    "references_other_files",
    "run_amf_parse",
    "stage_raml_members",
]

#: Registry key of the bundled AMF CLI (declared in :mod:`app.toolchain_packaging`).
AMF_TOOL_KEY = "amf"

#: Wall-clock limit for one ``amf parse``. The JVM starts in about a second; a set that
#: takes much longer is pathological.
AMF_TIMEOUT_SECONDS = 120.0

_RAML_HEADER_RE = re.compile(r"^\s*#%RAML\s+(\d+\.\d+)", re.IGNORECASE)
_INCLUDE_RE = re.compile(r"!include\s+([^\s#]+)")
_JSON_REF_RE = re.compile(r'"\$ref"\s*:\s*"([^"]+)"')
_FILE_URI_RE = re.compile(r"file:/+[^\s\"'#]*")


def amf_available() -> bool:
    """Whether the ``amf`` tool can be resolved in this runtime (a cheap ``PATH`` lookup).

    Returns:
        ``True`` when :func:`app.toolchain_packaging.probe_tool` reports it available.
    """
    from .toolchain_packaging import probe_tool, register_bundled_tools

    register_bundled_tools()
    return bool(probe_tool(AMF_TOOL_KEY).available)


# ===========================================================================
# Reference scanning (what a set pulls in, and whether that is safe)
# ===========================================================================


def find_reference_targets(path: str, text: str) -> List[str]:
    """List the files a RAML or JSON member points at, as written.

    Covers ``!include <path>``, the values of ``uses`` (libraries), ``extends`` /
    ``masterRef`` (overlays, extensions) and, in a JSON member, every non-local ``"$ref"``.

    Args:
        path: The member's path inside the set (only its extension is read).
        text: The member's text.

    Returns:
        The targets in the order found; fragments (``#...``) are kept.
    """
    targets: List[str] = list(_INCLUDE_RE.findall(text))
    if path.lower().endswith(".json"):
        targets.extend(ref for ref in _JSON_REF_RE.findall(text) if not ref.startswith("#"))
        return targets
    try:
        document = yaml.load(text, Loader=IncludeAsText)  # noqa: S506 - SafeLoader subclass
    except yaml.YAMLError:
        return targets
    if isinstance(document, Mapping):
        uses = document.get("uses")
        if isinstance(uses, Mapping):
            targets.extend(str(value) for value in uses.values() if isinstance(value, str))
        for key in ("extends", "masterRef"):
            if isinstance(document.get(key), str):
                targets.append(document[key])
    return targets


def references_other_files(members: Mapping[str, str]) -> bool:
    """Whether any member of the set includes or uses another file.

    Args:
        members: The set's members, path → text.

    Returns:
        ``True`` when at least one member names a reference target.
    """
    return any(find_reference_targets(path, text) for path, text in members.items())


def check_reference_targets(members: Mapping[str, str]) -> None:
    """Refuse a set whose references could read outside it.

    AMF resolves references straight from the filesystem, so a target that is absolute, a
    URL, or climbs out of the set with ``..`` would make it read (and embed) a file the
    import was never given. Targets that stay inside the set but are not in it are left
    for AMF, which reports them as unresolved.

    Args:
        members: The set's members, path → text.

    Raises:
        ImportSourceError: ``INPUT_REFERENCE_UNRESOLVED`` naming each refused reference.
    """
    refused: List[str] = []
    for path, text in members.items():
        for target in find_reference_targets(path, text):
            if resolve_relative_reference(path, target) is None:
                refused.append(f"{path} → {target}")
    if refused:
        raise ImportSourceError(
            "RAML references must be relative paths inside the uploaded files; these point "
            f"outside them and were not read: {', '.join(refused)}. Bundle the referenced "
            "files into the upload and use relative paths.",
            code="INPUT_REFERENCE_UNRESOLVED",
        )


# ===========================================================================
# Staging and running AMF
# ===========================================================================


def _safe_member_path(member: str) -> str:
    """Normalize a member path, refusing anything that would land outside the staging root."""
    normalized = posixpath.normpath(member.replace("\\", "/").lstrip("/"))
    if normalized in ("", ".") or normalized == ".." or normalized.startswith("../"):
        raise ImportSourceError(
            f"RAML file path {member!r} is not a relative path inside the upload.",
            code="INPUT_ARCHIVE_INVALID",
        )
    return normalized


def stage_raml_members(members: Mapping[str, str], directory: Path) -> Dict[str, Path]:
    """Write the set's members as regular files under ``directory``.

    Args:
        members: The set's members, path → text.
        directory: An empty, private directory.

    Returns:
        Member path (normalized) → the file written for it.

    Raises:
        ImportSourceError: ``INPUT_ARCHIVE_INVALID`` for a member path outside the set.
    """
    written: Dict[str, Path] = {}
    for member, text in members.items():
        relative = _safe_member_path(member)
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        written[relative] = target
    return written


def _amf_format(root_text: str) -> str:
    """The ``-in`` format for a root document (``RAML 0.8`` or ``RAML 1.0``)."""
    match = _RAML_HEADER_RE.match(root_text)
    return "RAML 0.8" if match and match.group(1) == "0.8" else "RAML 1.0"


def run_amf_parse(root_file: Path, *, root_text: str, staging_dir: Path) -> Dict[str, Any]:
    """Run ``amf parse`` on a staged root document and return its JSON-LD model.

    Args:
        root_file: The staged root document.
        root_text: The root document's text (its ``#%RAML`` header picks the AMF format).
        staging_dir: The staging directory (the tool's working directory and ``HOME``).

    Returns:
        The parsed JSON-LD document (with ``@graph`` and ``@context``).

    Raises:
        ImportSourceError: ``ADAPTER_UNAVAILABLE`` when the tool is missing,
            ``INPUT_TIME_LIMIT`` on timeout, ``INPUT_MALFORMED`` when AMF could not produce
            a model (its error text is included, with the staging path removed).
    """
    args = [
        "parse",
        root_file.resolve().as_uri(),
        "-in",
        _amf_format(root_text),
        "-mime-in",
        "application/yaml",
        "-ctx",
        "true",
        "-sm",
        "true",
    ]
    env = {"HOME": str(staging_dir)}
    try:
        result = run_tool_blocking(
            AMF_TOOL_KEY,
            args,
            timeout=AMF_TIMEOUT_SECONDS,
            thread_name="amf-parse",
            cwd=str(staging_dir),
            extra_env=env,
        )
    except ToolNotAvailableError as exc:
        raise ImportSourceError(
            "RAML import needs the bundled AMF toolchain, which is not available on this "
            "server (see docs/toolchain_packaging.md).",
            code="ADAPTER_UNAVAILABLE",
        ) from exc
    except ToolTimeoutError as exc:
        raise ImportSourceError(
            f"AMF took longer than {AMF_TIMEOUT_SECONDS:.0f} s to parse the RAML set.",
            code="INPUT_TIME_LIMIT",
        ) from exc
    except ToolchainError as exc:
        raise ImportSourceError(
            f"AMF could not parse the RAML set: {_scrub(str(exc), staging_dir)}",
            code="INPUT_MALFORMED",
        ) from exc

    try:
        model = json.loads(result.stdout or "")
    except json.JSONDecodeError:
        model = None
    if not isinstance(model, dict) or not isinstance(model.get("@graph"), list):
        violations = parse_validation_violations(result.stderr, staging_dir)
        if violations:
            raise ImportSourceError(
                f"AMF found {len(violations)} problem{'s' if len(violations) != 1 else ''} in the "
                f"RAML set: {'; '.join(violations)}",
                code="INPUT_SEMANTIC_INVALID",
            )
        detail = _first_error_line(result.stderr) or "it produced no model"
        raise ImportSourceError(
            f"AMF could not parse the RAML set: {_scrub(detail, staging_dir)}",
            code="INPUT_MALFORMED",
        )
    return model


_REPORT_FIELD_RE = re.compile(r"^\s*-?\s*(Constraint|Message|Severity|Range|Location):\s*(.*)$")
_RANGE_LINE_RE = re.compile(r"\((\d+),\d+\)")


def parse_validation_violations(stderr: Optional[str], staging_dir: Path) -> List[str]:
    """Read the violations of the validation report AMF prints when a parse fails.

    The report lists one result per problem (``Message``, ``Severity``, ``Range``,
    ``Location``). Only ``Violation`` results are returned; each is rendered as
    ``"<message> (<file> line <n>)"`` with the staging directory removed from the file.

    Args:
        stderr: The tool's standard error.
        staging_dir: The staging directory (removed from locations).

    Returns:
        The violations, in report order; empty when the output holds no report.
    """
    results: List[Dict[str, str]] = []
    current: Dict[str, str] = {}
    for line in (stderr or "").splitlines():
        match = _REPORT_FIELD_RE.match(line)
        if not match:
            continue
        field, value = match.group(1), match.group(2).strip()
        if field == "Constraint":
            if current:
                results.append(current)
            current = {}
        current[field] = value
    if current:
        results.append(current)

    violations: List[str] = []
    for item in results:
        if item.get("Severity", "Violation") != "Violation" or not item.get("Message"):
            continue
        where = _scrub(item.get("Location", ""), staging_dir).lstrip("/")
        line_match = _RANGE_LINE_RE.search(item.get("Range", ""))
        place = " ".join(part for part in (where, f"line {line_match.group(1)}" if line_match else "") if part)
        violations.append(f"{item['Message']} ({place})" if place else item["Message"])
    return violations


def _first_error_line(stderr: Optional[str]) -> Optional[str]:
    """The first meaningful line of a JVM error (skips the ``at ...`` stack frames)."""
    for line in (stderr or "").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(("at ", "Picked up ")):
            return stripped
    return None


def _scrub(text: str, staging_dir: Path) -> str:
    """Remove the staging directory from tool output so no server path is surfaced."""
    root = str(staging_dir.resolve())
    return re.sub(r"file:/+" + re.escape(root.lstrip("/")) + "/?", "", text).replace(root + "/", "").replace(root, "")


def _check_model_locations(model: Mapping[str, Any], staging_dir: Path) -> None:
    """Refuse a model that records a file outside the staging directory (defense in depth)."""
    root = staging_dir.resolve()
    outside: List[str] = []
    for uri in set(_FILE_URI_RE.findall(json.dumps(model))):
        path = Path("/" + re.sub(r"^file:/+", "", uri))
        try:
            path.resolve().relative_to(root)
        except ValueError:
            outside.append(path.name)
    if outside:
        raise ImportSourceError(
            "AMF read a file outside the uploaded RAML set "
            f"({', '.join(sorted(outside))}); the import was refused.",
            code="INPUT_REFERENCE_UNRESOLVED",
        )


# ===========================================================================
# Resolved-model hash
# ===========================================================================


def _strip_for_hash(value: Any, staging_prefixes: Tuple[str, ...]) -> Any:
    """Drop source maps and make recorded locations relative, recursively."""
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, item in value.items():
            if key.startswith("sourcemaps:"):
                continue
            out[key] = _strip_for_hash(item, staging_prefixes)
        return out
    if isinstance(value, list):
        return [_strip_for_hash(item, staging_prefixes) for item in value]
    if isinstance(value, str):
        for prefix in staging_prefixes:
            value = value.replace(prefix, "")
        return value
    return value


def amf_model_sha256(model: Mapping[str, Any], staging_dir: Optional[Path] = None) -> str:
    """SHA-256 of the AMF-resolved model, independent of where the set was staged.

    Source-map nodes and keys are dropped (they carry line/column positions and absolute
    paths) and any staging-directory prefix is removed from recorded locations, so the same
    set hashes the same on every run and every server.

    Args:
        model: The JSON-LD model from :func:`run_amf_parse`.
        staging_dir: The staging directory the model was produced in.

    Returns:
        The lowercase hex digest.
    """
    prefixes: Tuple[str, ...] = ()
    if staging_dir is not None:
        root = str(staging_dir.resolve()).lstrip("/")
        prefixes = tuple(f"file:{'/' * n}{root}/" for n in (4, 3, 2, 1))
    graph = model.get("@graph", []) if isinstance(model, Mapping) else []
    kept = [
        node
        for node in graph
        if isinstance(node, Mapping)
        and "sourcemaps:SourceMap" not in (node.get("@type") or [])
        and "/source-map" not in str(node.get("@id", ""))
    ]
    canonical = json.dumps(_strip_for_hash(kept, prefixes), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ===========================================================================
# Entry point
# ===========================================================================


def parse_raml_set_with_amf(
    members: Mapping[str, str],
    root: str,
    *,
    source_label: Optional[str] = None,
) -> RamlDocument:
    """Parse and resolve a RAML set through AMF into a :class:`RamlDocument`.

    Args:
        members: The set's members, path → text (a single document is a one-member set).
        root: The root document's path among ``members``.
        source_label: Label used in error messages.

    Returns:
        The document, with ``model_sha256`` and ``source_files`` set.

    Raises:
        ImportSourceError: See :func:`check_reference_targets`, :func:`run_amf_parse` and
            :func:`app.raml_amf_mapper.document_from_amf_model`.
    """
    from .raml_amf_mapper import document_from_amf_model

    if root not in members:
        raise ImportSourceError("RAML fileset is missing its root document", code="INPUT_ARCHIVE_INVALID")
    check_reference_targets(members)
    root_path = _safe_member_path(root)

    staging_dir = Path(tempfile.mkdtemp(prefix="apiome-raml-amf-"))
    try:
        staged = stage_raml_members(members, staging_dir)
        model = run_amf_parse(staged[root_path], root_text=members[root], staging_dir=staging_dir)
        _check_model_locations(model, staging_dir)
        return document_from_amf_model(
            model,
            raw=members[root],
            model_sha256=amf_model_sha256(model, staging_dir),
            source_files=_source_files(members),
            source_label=source_label or root,
        )
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def _source_files(members: Iterable[str]) -> Tuple[str, ...]:
    """The set's member paths, normalized and sorted."""
    return tuple(sorted(_safe_member_path(member) for member in members))
