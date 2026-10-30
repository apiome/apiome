"""API Blueprint diagnostics from ``drafter`` — MFI-16.3 (#3806).

API Blueprint imports are read by the built-in parser (:mod:`app.apiblueprint_parser`), so a
catalog import never depends on the external toolchain. ``drafter`` (apiaryio/drafter 4.0.0,
``toolchain_packaging.BundledTool`` key ``drafter``) is the reference parser, and what it says about
a blueprint — its **annotations** — is the format's own lint: zero warnings is a good blueprint.

:func:`run_drafter` feeds the document to ``drafter -f json`` on stdin and reads the annotations out
of the Refract parse result (:func:`read_drafter_annotations`). drafter exits with the code of its
first error (``4`` for a circular or undefined base type, ``2`` for tabs), with the parse result still
on stdout, so a non-zero exit is read like a zero one. The annotations are recorded on the catalog item
and reported by the ``apiblueprint`` lint pack (:mod:`app.apiblueprint_lint`).

The check is best effort: without ``drafter`` on the server, or when it fails to run, the import is
unaffected and simply carries no annotations.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Mapping, Optional

from .toolchain_runner import ToolchainError, ToolExecutionError, run_tool_blocking

__all__ = [
    "DRAFTER_TIMEOUT_SECONDS",
    "DRAFTER_TOOL_KEY",
    "drafter_available",
    "read_drafter_annotations",
    "run_drafter",
]

logger = logging.getLogger(__name__)

#: Registry key of the bundled drafter CLI (declared in :mod:`app.toolchain_packaging`).
DRAFTER_TOOL_KEY = "drafter"

#: Wall-clock limit for one ``drafter`` run (it parses a large blueprint in well under a second).
DRAFTER_TIMEOUT_SECONDS = 30.0


def drafter_available() -> bool:
    """Whether the ``drafter`` tool can be resolved in this runtime (a cheap ``PATH`` lookup)."""
    from .toolchain_packaging import probe_tool, register_bundled_tools

    register_bundled_tools()
    return bool(probe_tool(DRAFTER_TOOL_KEY).available)


def _content(element: Any) -> Any:
    """A Refract element's ``content`` (the value itself when it is not an element)."""
    return element.get("content") if isinstance(element, Mapping) else element


def _start(annotation: Mapping[str, Any]) -> Dict[str, int]:
    """The 1-based ``line`` / ``column`` where an annotation's first source-map range starts."""
    source_map = _content((annotation.get("attributes") or {}).get("sourceMap")) or []
    for entry in source_map if isinstance(source_map, list) else []:
        for span in _content(entry) or []:
            positions = _content(span) or []
            if not positions or not isinstance(positions[0], Mapping):
                continue
            attributes = positions[0].get("attributes") or {}
            line, column = _content(attributes.get("line")), _content(attributes.get("column"))
            if isinstance(line, int) and isinstance(column, int):
                return {"line": line, "column": column}
    return {}


def read_drafter_annotations(stdout: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    """Read the annotations of a drafter Refract parse result.

    Args:
        stdout: ``drafter -f json`` output.

    Returns:
        One dict per annotation, in document order: ``severity`` (``warning`` / ``error``),
        ``code`` (drafter's annotation code), ``message`` and, when drafter located it, the 1-based
        ``line`` / ``column``. ``None`` when the output is not a parse result.
    """
    try:
        result = json.loads(stdout or "")
    except json.JSONDecodeError:
        return None
    if not isinstance(result, Mapping) or result.get("element") != "parseResult":
        return None
    annotations: List[Dict[str, Any]] = []
    for element in result.get("content") or []:
        if not isinstance(element, Mapping) or element.get("element") != "annotation":
            continue
        classes = _content((element.get("meta") or {}).get("classes")) or []
        severity = str(_content(classes[0])) if classes else "warning"
        code = _content((element.get("attributes") or {}).get("code"))
        annotations.append(
            {
                "severity": severity,
                "code": code if isinstance(code, int) else None,
                "message": str(element.get("content") or "").strip(),
                **_start(element),
            }
        )
    return annotations


def run_drafter(text: str, *, strict: bool = False) -> List[Dict[str, Any]]:
    """Run ``drafter -f json`` on a blueprint and return its annotations.

    Args:
        text: The API Blueprint document.
        strict: Raise instead of returning ``[]`` when drafter could not give an answer. The import
            treats drafter as best effort; the export gate (MFX-18.3) must not mistake "drafter did
            not run" for "drafter found nothing".

    Returns:
        The annotations (:func:`read_drafter_annotations`). Without ``strict``, empty when drafter is
        missing, fails to run, or prints no parse result — the import does not depend on it.

    Raises:
        ToolchainError: With ``strict``, when drafter is missing (``ToolNotAvailableError``) or failed
            to run (a timeout, a resource limit…).
        ValueError: With ``strict``, when drafter printed no parse result.
    """
    try:
        result = run_tool_blocking(
            DRAFTER_TOOL_KEY, ["-f", "json"], stdin=text, timeout=DRAFTER_TIMEOUT_SECONDS, thread_name="drafter"
        )
        stdout = result.stdout
    except ToolExecutionError as exc:
        stdout = exc.stdout
    except ToolchainError as exc:
        if strict:
            raise
        logger.warning("drafter did not run; the blueprint is imported without its annotations: %s", exc)
        return []
    annotations = read_drafter_annotations(stdout)
    if annotations is None:
        if strict:
            raise ValueError("drafter printed no parse result")
        logger.warning("drafter printed no parse result; the blueprint is imported without its annotations")
        return []
    return annotations
