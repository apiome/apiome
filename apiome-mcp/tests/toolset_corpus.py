"""Golden toolset corpus: runner, store and checks — AGX-1.4 (#4532).

Every ``valid`` examples-corpus entry is compiled with the AGX-1.1 operation→tool compiler
(:func:`apiome_mcp.tool_compiler.compile_mcp_tools`) and its canonical JSON
(:meth:`McpToolset.serialize`) is checked in under ``tests/golden/toolsets/``. The suite in
:mod:`test_toolset_goldens` uses this module to hold the compiler to two gates:

* **determinism** — recompiling an entry must reproduce its golden byte for byte;
* **MCP validity** — every tool in every stored golden must be a valid MCP ``tools/list``
  entry (:func:`golden_violations`).

Corpus selection and parsing reuse apiome-rest's IXH corpus helpers
(``apiome-rest/tests/corpus_loader.py`` and ``corpus_adapter_support.py``), so this corpus
covers exactly the entries the canonical goldens cover and never hard-codes a fixture path.

Regenerate with :data:`REGENERATE_COMMAND`; the docs are ``docs/TOOLSET_GOLDENS.md``.
"""

from __future__ import annotations

import difflib
import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import mcp.types as mt
import pytest
from app.import_source import load_builtin_import_sources
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import ValidationError

from apiome_mcp.tool_compiler import (
    MCP_TOOL_MAPPING_VERSION,
    McpToolset,
    compile_mcp_tools,
    mcp_schema_violations,
    validate_mcp_tool,
)

#: Monorepo root (parent of ``apiome-mcp/``).
_REPO_ROOT = Path(__file__).resolve().parents[2]

# The corpus helpers are apiome-rest *test* modules, not part of its package. Appended (not
# prepended) so a same-named module in this tests directory always wins.
sys.path.append(str(_REPO_ROOT / "apiome-rest" / "tests"))

from corpus_adapter_support import (  # noqa: E402
    KNOWN_IMPORT_BUGS,
    adapter_for,
    missing_tools,
    parse_native,
    valid_entries,
)
from corpus_loader import CorpusEntry  # noqa: E402

__all__ = [
    "GOLDEN_ROOT",
    "REGENERATE_COMMAND",
    "UPDATE_OPTION",
    "compile_entry",
    "corpus_entries",
    "corpus_entry_params",
    "describe_drift",
    "golden_entry_paths",
    "golden_mismatch",
    "golden_path",
    "golden_violations",
    "load_golden",
    "prune_orphan_goldens",
    "updating_goldens",
    "write_golden",
]

#: Where the goldens live: ``<GOLDEN_ROOT>/<corpus path>.json``.
GOLDEN_ROOT = Path(__file__).resolve().parent / "golden" / "toolsets"

#: Appended to the corpus path (whose own extension is kept) to name its golden.
_GOLDEN_SUFFIX = ".json"

#: The pytest flag that regenerates goldens instead of comparing them (registered in
#: ``conftest.py``).
UPDATE_OPTION = "--update-golden"

#: The one command that regenerates every golden, run from ``apiome-mcp/``.
REGENERATE_COMMAND = f"uv run pytest tests/test_toolset_goldens.py {UPDATE_OPTION}"

#: Keys of a golden tool that are compiler output rather than part of the MCP
#: ``tools/list`` entry (:meth:`McpToolDefinition.to_dict` adds them to :meth:`to_mcp`).
_COMPILER_ONLY_KEYS = frozenset({"operation", "output"})

#: Longest unified diff a drift report prints before truncating.
_MAX_DIFF_LINES = 60

load_builtin_import_sources()


# ===========================================================================
# Corpus
# ===========================================================================


def corpus_entries() -> list[CorpusEntry]:
    """Return the corpus entries that get a golden, sorted by corpus path.

    These are the ``valid`` manifest entries owned by an import adapter, minus multi-file
    set *members* (a set is compiled once, through its root) — the same selection as the
    IXH-1.6 canonical goldens.

    Returns:
        The entries, in corpus-path order.
    """
    return sorted(valid_entries(), key=lambda entry: entry.path)


def corpus_entry_params() -> list[Any]:
    """Return :func:`corpus_entries` as pytest params, marked for what cannot run here.

    An entry on apiome-rest's ``KNOWN_IMPORT_BUGS`` list is a **strict** xfail, so fixing
    that adapter fails this suite until the entry leaves the list and gains a golden. An
    entry whose adapter needs a bundled tool (``buf``, ``asyncapi-parser``) that does not
    resolve here is skipped; its golden stays on disk.

    Returns:
        One ``pytest.param`` per entry, with the corpus path as its id.
    """
    params = []
    for entry in corpus_entries():
        marks: list[Any] = []
        if entry.path in KNOWN_IMPORT_BUGS:
            marks.append(pytest.mark.xfail(reason=KNOWN_IMPORT_BUGS[entry.path], strict=True))
        missing = missing_tools(entry.adapter_key or "")
        if missing:
            marks.append(pytest.mark.skip(reason=f"bundled {', '.join(missing)} not resolvable here"))
        params.append(pytest.param(entry, id=entry.path, marks=marks))
    return params


def compile_entry(entry: CorpusEntry) -> McpToolset:
    """Import one corpus entry through its adapter and compile its toolset.

    The toolset uses the default exposure (every callable, non-deprecated operation) —
    what a version serves before any AGX-1.2 curation.

    Args:
        entry: A ``valid`` manifest entry from :func:`corpus_entries`.

    Returns:
        The compiled toolset; empty when the entry declares no callable operation.
    """
    adapter = adapter_for(entry)
    api = adapter.normalize(parse_native(adapter, entry), include_raw=False)
    return compile_mcp_tools(api)


# ===========================================================================
# Store
# ===========================================================================


def updating_goldens(config: pytest.Config) -> bool:
    """Return whether this run regenerates goldens (``--update-golden``) instead of comparing."""
    return bool(config.getoption(UPDATE_OPTION, default=False))


def golden_path(entry_path: str, *, root: Path = GOLDEN_ROOT) -> Path:
    """Return the golden file for a corpus path (``openapi/x.yaml`` → ``openapi/x.yaml.json``)."""
    return root / f"{entry_path}{_GOLDEN_SUFFIX}"


def golden_entry_paths(*, root: Path = GOLDEN_ROOT) -> list[str]:
    """Return the corpus path of every golden on disk, sorted."""
    if not root.is_dir():
        return []
    return sorted(
        path.relative_to(root).as_posix()[: -len(_GOLDEN_SUFFIX)] for path in root.rglob(f"*{_GOLDEN_SUFFIX}")
    )


def load_golden(entry_path: str, *, root: Path = GOLDEN_ROOT) -> bytes | None:
    """Return a golden's stored bytes, or ``None`` when the entry has no golden."""
    path = golden_path(entry_path, root=root)
    return path.read_bytes() if path.is_file() else None


def write_golden(entry_path: str, serialized: str, *, root: Path = GOLDEN_ROOT) -> bool:
    """Store ``serialized`` as the entry's golden, leaving an identical file untouched.

    Args:
        entry_path: The corpus path.
        serialized: The toolset's :meth:`McpToolset.serialize` text.
        root: The golden store (tests pass a temporary one).

    Returns:
        ``True`` when the file was created or changed.
    """
    data = serialized.encode("utf-8")
    if load_golden(entry_path, root=root) == data:
        return False
    path = golden_path(entry_path, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def prune_orphan_goldens(known: Iterable[str], *, root: Path = GOLDEN_ROOT) -> list[str]:
    """Delete goldens whose corpus entry no longer exists, and any directory left empty.

    Only an entry missing from ``known`` is an orphan: a golden whose entry is merely
    skipped here (a bundled tool is missing) is kept.

    Args:
        known: Corpus paths that should have a golden (:func:`corpus_entries`).
        root: The golden store.

    Returns:
        The corpus paths whose goldens were deleted, sorted.
    """
    keep = set(known)
    removed = [entry_path for entry_path in golden_entry_paths(root=root) if entry_path not in keep]
    for entry_path in removed:
        golden_path(entry_path, root=root).unlink()
    for directory in sorted((path for path in root.rglob("*") if path.is_dir()), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()
    return removed


# ===========================================================================
# Determinism gate
# ===========================================================================


def golden_mismatch(entry_path: str, serialized: str, *, root: Path = GOLDEN_ROOT) -> str | None:
    """Explain why a fresh compile does not reproduce its golden byte for byte.

    Args:
        entry_path: The corpus path.
        serialized: The fresh compile's :meth:`McpToolset.serialize` text.
        root: The golden store.

    Returns:
        ``None`` when the golden matches; otherwise the failure message, which names the
        drifted tools and ends with :data:`REGENERATE_COMMAND`.
    """
    stored = load_golden(entry_path, root=root)
    if stored is None:
        return f"{entry_path}: no golden toolset; generate it with `{REGENERATE_COMMAND}`, review and commit it."
    if stored == serialized.encode("utf-8"):
        return None
    return describe_drift(entry_path, stored.decode("utf-8", errors="replace"), serialized)


def describe_drift(entry_path: str, golden_text: str, compiled_text: str) -> str:
    """Render a golden mismatch as tool-level changes followed by a bounded text diff.

    Tools are matched by the operation they invoke, the identity curation (AGX-1.2) and
    invocation (AGX-2.1) resolve a tool by, so a renamed tool reads as ``RENAMED`` rather
    than as one tool removed and another added.

    Args:
        entry_path: The corpus path.
        golden_text: The stored golden.
        compiled_text: The fresh compile.

    Returns:
        A multi-line report ending with :data:`REGENERATE_COMMAND`.
    """
    lines = [f"{entry_path}: the compiled toolset no longer matches its golden."]
    try:
        golden = json.loads(golden_text)
    except ValueError:
        lines.append("  the stored golden is not valid JSON")
    else:
        lines.extend(f"  {change}" for change in _tool_changes(golden, json.loads(compiled_text)))
    diff = list(
        difflib.unified_diff(
            golden_text.splitlines(),
            compiled_text.splitlines(),
            fromfile="golden",
            tofile="compiled",
            lineterm="",
            n=2,
        )
    )
    if len(diff) > _MAX_DIFF_LINES:
        diff = [*diff[:_MAX_DIFF_LINES], f"... {len(diff) - _MAX_DIFF_LINES} more diff lines"]
    lines.extend(diff)
    lines.append(
        f"If the change is intended, regenerate with `{REGENERATE_COMMAND}` and commit the golden diff "
        "in the same PR (bump MCP_TOOL_MAPPING_VERSION when a mapping change alters output for an "
        "unchanged spec)."
    )
    return "\n".join(lines)


def _tool_changes(golden: Any, compiled: Any) -> list[str]:
    """List what changed between two golden documents, one line per tool-level change."""
    if not isinstance(golden, dict) or not isinstance(compiled, dict):
        return ["the golden is not a toolset object"]
    changes = []
    if golden.get("mappingVersion") != compiled.get("mappingVersion"):
        changes.append(f"mappingVersion: {golden.get('mappingVersion')!r} → {compiled.get('mappingVersion')!r}")
    before = _tools_by_operation(golden)
    after = _tools_by_operation(compiled)
    for operation in sorted(before.keys() - after.keys()):
        changes.append(f"REMOVED {before[operation].get('name')!r} ({operation})")
    for operation in sorted(after.keys() - before.keys()):
        changes.append(f"ADDED {after[operation].get('name')!r} ({operation})")
    for operation in sorted(before.keys() & after.keys()):
        old, new = before[operation], after[operation]
        if old.get("name") != new.get("name"):
            changes.append(f"RENAMED {old.get('name')!r} → {new.get('name')!r} ({operation})")
        fields = sorted(key for key in old.keys() | new.keys() if key != "name" and old.get(key) != new.get(key))
        if fields:
            changes.append(f"CHANGED {new.get('name')!r} ({operation}): {', '.join(fields)}")
    if not changes and list(before) != list(after):
        changes.append("tool order changed")
    return changes


def _tools_by_operation(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Index a golden's tools by their operation key (falling back to the tool name)."""
    tools = document.get("tools")
    indexed: dict[str, dict[str, Any]] = {}
    for tool in tools if isinstance(tools, list) else []:
        if isinstance(tool, dict):
            indexed[str(tool.get("operation") or tool.get("name"))] = tool
    return indexed


# ===========================================================================
# MCP validity gate
# ===========================================================================


def golden_violations(document: Any) -> list[str]:
    """Check a stored golden against the MCP tool contract.

    Each tool's MCP entry (the tool minus the compiler-only ``operation`` and ``output``)
    must pass the compiler's own :func:`validate_mcp_tool`, validate as the MCP SDK's
    ``mcp.types.Tool`` and carry an ``inputSchema`` that is a valid JSON-Schema 2020-12
    schema. An ``output.schema`` must stay in the MCP keyword subset and be a valid schema
    too. Tool names must be unique, and the golden must carry the current
    ``MCP_TOOL_MAPPING_VERSION``.

    Args:
        document: A parsed golden file.

    Returns:
        Violations as ``<JSON pointer>: <problem>`` strings; empty when the golden is valid.
    """
    if not isinstance(document, dict):
        return ["/: a golden toolset must be a JSON object"]
    problems = []
    if document.get("mappingVersion") != MCP_TOOL_MAPPING_VERSION:
        problems.append(
            f"/mappingVersion: {document.get('mappingVersion')!r} is not the current mapping version "
            f"{MCP_TOOL_MAPPING_VERSION}"
        )
    tools = document.get("tools")
    if not isinstance(tools, list):
        return [*problems, "/tools: must be an array"]
    seen: set[str] = set()
    for index, tool in enumerate(tools):
        pointer = f"/tools/{index}"
        if not isinstance(tool, dict):
            problems.append(f"{pointer}: must be an object")
            continue
        problems.extend(f"{pointer}{problem}" for problem in _tool_violations(tool))
        name = tool.get("name")
        if isinstance(name, str):
            if name in seen:
                problems.append(f"{pointer}/name: {name!r} is duplicated within the toolset")
            seen.add(name)
    return problems


def _tool_violations(tool: Mapping[str, Any]) -> list[str]:
    """Return the violations of one golden tool, as pointers relative to the tool."""
    entry = {key: value for key, value in tool.items() if key not in _COMPILER_ONLY_KEYS}
    problems = list(validate_mcp_tool(entry))
    try:
        mt.Tool.model_validate(entry)
    except ValidationError as error:
        problems.extend(
            f"/{'/'.join(map(str, issue['loc']))}: MCP SDK rejects it ({issue['msg']})" for issue in error.errors()
        )
    problems.extend(_metaschema_violations(entry.get("inputSchema"), "/inputSchema"))
    output = tool.get("output")
    if isinstance(output, dict) and output.get("schema") is not None:
        problems.extend(mcp_schema_violations(output["schema"], pointer="/output/schema"))
        problems.extend(_metaschema_violations(output["schema"], "/output/schema"))
    return problems


def _metaschema_violations(schema: Any, pointer: str) -> list[str]:
    """Return a problem when ``schema`` is not a valid JSON-Schema 2020-12 schema."""
    if not isinstance(schema, dict):
        return []  # validate_mcp_tool / mcp_schema_violations already report a non-object
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        location = "".join(f"/{part}" for part in error.absolute_path)
        return [f"{pointer}{location}: not a valid JSON-Schema 2020-12 schema ({error.message})"]
    return []
