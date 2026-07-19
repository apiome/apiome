"""Backend mirror of the DCW-0.2 OAS resource-limits artifact — DCW-2.1 (private-suite#2352).

``designer/src/lib/oas-capability/oas-resource-limits.json`` (in the private-suite
repo) is the versioned, machine-readable source of truth for document-size,
alias-expansion, nesting-depth, duplicate-key, and multi-document bounds on every
OpenAPI source surface. The DCW-0.2 gate registry requires the backend parser to
mirror that artifact **field-for-field** (the same convention as the DCW-0.1
capability matrix): ``src/app/data/oas_resource_limits.json`` is a verbatim copy,
and this module is its typed Python consumer.

Keeping the two copies in sync is a review-time rule enforced by tests on both
sides pinning ``limitsVersion`` and every limit value: bumping one artifact
without the other fails that repo's pin test, which is the cross-repo conflict
signal (the DCW-0.1 "conflicting consumer versions fail CI" convention).

This module also loads the DCW-0.1 capability-matrix mirror
(``oas_capability_matrix.json``) that :mod:`app.preservation_envelope` validates
preserved content against.

Everything here is pure and import-time cached: no DB, no network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

__all__ = [
    "OAS_RESOURCE_LIMITS_PATH",
    "OAS_CAPABILITY_MATRIX_PATH",
    "OasResourceLimitValues",
    "load_resource_limits_artifact",
    "resource_limit_values",
    "load_capability_matrix_artifact",
    "supported_dialects",
    "capability_for_pointer",
    "lexical_exclusions",
]

_DATA_DIR = Path(__file__).parent / "data"

#: Verbatim copy of the designer's ``oas-resource-limits.json`` (DCW-0.2, #2419).
OAS_RESOURCE_LIMITS_PATH = _DATA_DIR / "oas_resource_limits.json"

#: Verbatim copy of the designer's ``oas-capability-matrix.json`` (DCW-0.1, #2418).
OAS_CAPABILITY_MATRIX_PATH = _DATA_DIR / "oas_capability_matrix.json"


@dataclass(frozen=True)
class OasResourceLimitValues:
    """The numeric limits the safe parser enforces (mirror of the TS type)."""

    max_document_bytes: int
    max_alias_count: int
    max_nesting_depth: int
    max_yaml_documents_per_source: int


@lru_cache(maxsize=1)
def load_resource_limits_artifact() -> Dict[str, Any]:
    """Load and cache the resource-limits artifact as a plain dict.

    Returns:
        The parsed artifact. Its ``limitsVersion``, ``limits`` values, and
        ``duplicateKeyPolicy`` are pinned by ``tests/test_oas_resource_limits.py``
        so an unreviewed drift from the designer copy fails CI.

    Raises:
        ValueError: If the artifact is missing a required field — a broken
            deployment must fail loudly at import of the parser, not silently
            parse without limits.
    """
    artifact = json.loads(OAS_RESOURCE_LIMITS_PATH.read_text(encoding="utf-8"))
    for field in ("limitsVersion", "limits", "duplicateKeyPolicy", "onViolation"):
        if field not in artifact:
            raise ValueError(f"oas_resource_limits.json is missing required field {field!r}")
    for limit in (
        "maxDocumentBytes",
        "maxAliasCount",
        "maxNestingDepth",
        "maxYamlDocumentsPerSource",
    ):
        entry = artifact["limits"].get(limit)
        if not isinstance(entry, dict) or not isinstance(entry.get("value"), int):
            raise ValueError(f"oas_resource_limits.json limit {limit!r} has no integer value")
    return artifact


def resource_limit_values() -> OasResourceLimitValues:
    """Return the effective numeric limits from the artifact."""
    limits = load_resource_limits_artifact()["limits"]
    return OasResourceLimitValues(
        max_document_bytes=limits["maxDocumentBytes"]["value"],
        max_alias_count=limits["maxAliasCount"]["value"],
        max_nesting_depth=limits["maxNestingDepth"]["value"],
        max_yaml_documents_per_source=limits["maxYamlDocumentsPerSource"]["value"],
    )


@lru_cache(maxsize=1)
def load_capability_matrix_artifact() -> Dict[str, Any]:
    """Load and cache the DCW-0.1 capability-matrix artifact as a plain dict.

    Raises:
        ValueError: If the artifact is missing a required field.
    """
    artifact = json.loads(OAS_CAPABILITY_MATRIX_PATH.read_text(encoding="utf-8"))
    for field in ("matrixVersion", "supportedDialects", "dialects", "fidelity"):
        if field not in artifact:
            raise ValueError(f"oas_capability_matrix.json is missing required field {field!r}")
    return artifact


def supported_dialects() -> List[str]:
    """Return the OAS dialect versions the capability contract supports."""
    return list(load_capability_matrix_artifact()["supportedDialects"])


def _pointer_first_segment(pointer: str) -> str:
    """Return the first RFC 6901 segment of ``pointer`` (unescaped), or ``''``."""
    if not pointer.startswith("/"):
        return ""
    segment = pointer[1:].split("/", 1)[0]
    return segment.replace("~1", "/").replace("~0", "~")


def capability_for_pointer(dialect: str, pointer: str) -> str:
    """Classify a JSON Pointer under the capability matrix for ``dialect``.

    Mirrors the designer adapter's resolution rules: an ``x-*`` leading segment
    resolves to ``extensionCapability``; otherwise the longest matching
    ``pointerPrefix`` among the dialect's pointer families wins; anything
    unmatched falls back to ``defaultCapability``.

    Args:
        dialect: A supported dialect version, e.g. ``"3.1.0"``.
        pointer: An RFC 6901 JSON Pointer into the document (``""`` is the root).

    Returns:
        One capability state string (``visual-edit`` / ``raw-edit`` /
        ``preserved-read-only`` / ``converted-with-review`` / ``unsupported``).

    Raises:
        ValueError: If ``dialect`` is not in the matrix.
    """
    matrix = load_capability_matrix_artifact()
    dialect_entry = matrix["dialects"].get(dialect)
    if dialect_entry is None:
        raise ValueError(f"dialect {dialect!r} is not defined in the capability matrix")
    if _pointer_first_segment(pointer).startswith("x-"):
        return matrix["extensionCapability"]
    best_capability = matrix["defaultCapability"]
    best_len = -1
    for family in dialect_entry["pointerFamilies"]:
        prefix = family["pointerPrefix"]
        if (pointer == prefix or pointer.startswith(prefix + "/")) and len(prefix) > best_len:
            best_capability = family["capability"]
            best_len = len(prefix)
    return best_capability


def lexical_exclusions() -> List[str]:
    """Return the lexical characteristics the fidelity contract excludes.

    These are the differences (comments, anchors, key order, quoting,
    whitespace, multi-file layout) a semantic fingerprint intentionally does not
    see; DCW-2.1 reports them alongside every fingerprint so "unchanged" is
    never over-claimed as lexical.
    """
    return list(load_capability_matrix_artifact()["fidelity"]["lexical"]["exclusions"])
