"""TypeSpec versioning: one OpenAPI document per version, and what changed between them — MFI-14.4 (#3797).

A TypeSpec service annotated ``@versioned(Versions)`` (``@typespec/versioning``) describes several
versions of one API: ``@added`` / ``@removed`` / ``@madeOptional`` … say when each piece appears.
The OpenAPI emitter writes one document per version when its ``output-file`` names ``{version}``
(:data:`app.typespec_config.OPENAPI_OUTPUT_FILE`), each carrying the version in ``info.version`` —
the enum member's value, or its name when it has none.

Following the epic ("treat emitted OpenAPI as the integration surface … for breaking changes compile
both versions → OpenAPI and run openapi-diff"), this module orders those documents by the version
enum's declaration order (:func:`declared_versions`, :func:`order_versions`) and grades each step
from one version to the next with the OpenAPI compatibility analysis Apiome already runs on OpenAPI
revisions (:func:`app.schema_compatibility.analyze_schema_compatibility`, :func:`version_changes`).
The catalog item is the **latest** version; the steps are recorded on it
(:mod:`app.typespec_import_source`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .schema_compatibility import analyze_schema_compatibility

__all__ = [
    "MAX_RECORDED_FINDINGS",
    "TypeSpecVersion",
    "declared_versions",
    "order_versions",
    "version_changes",
]

#: Most compatibility findings recorded per version step (the rest are counted).
MAX_RECORDED_FINDINGS = 50

_VERSIONED_RE = re.compile(r"@versioned\(\s*([A-Za-z_][\w.]*)\s*\)")
_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
_DECORATOR_RE = re.compile(r"@[\w.]+(\([^)]*\))?")
_MEMBER_RE = re.compile(r"^\s*([A-Za-z_]\w*|`[^`]+`)\s*(?::\s*(\"(?:[^\"\\]|\\.)*\"|[^,]+))?\s*$")


@dataclass(frozen=True)
class TypeSpecVersion:
    """One version's emitted OpenAPI document.

    Attributes:
        version: The version (``info.version``: the enum member's value, else its name).
        openapi: The OpenAPI document emitted for it.
        openapi_sha256: SHA-256 of the document (sorted-key JSON).
    """

    version: str
    openapi: Dict[str, Any]
    openapi_sha256: str


def _enum_body(sources: Mapping[str, str], name: str) -> Optional[str]:
    """The body of ``enum <name> { … }`` in any of the sources, comments removed."""
    pattern = re.compile(r"\benum\s+" + re.escape(name) + r"\s*\{(.*?)\}", re.DOTALL)
    for text in sources.values():
        match = pattern.search(_COMMENT_RE.sub("", text))
        if match:
            return match.group(1)
    return None


def declared_versions(sources: Mapping[str, str]) -> List[str]:
    """The versions a ``@versioned`` service declares, in declaration order.

    Args:
        sources: The project's ``.tsp`` files, path → text.

    Returns:
        Each member of the versions enum as the emitter writes it — the member's string value, or
        its name when it has none. Empty when no ``@versioned`` enum is found.
    """
    for text in sources.values():
        match = _VERSIONED_RE.search(_COMMENT_RE.sub("", text))
        if not match:
            continue
        body = _enum_body(sources, match.group(1).split(".")[-1])
        if body is None:
            return []
        versions: List[str] = []
        for raw in _DECORATOR_RE.sub("", body).split(","):
            member = _MEMBER_RE.match(raw)
            if not member or not raw.strip():
                continue
            name, value = member.group(1).strip("`"), member.group(2)
            if value and value.strip().startswith('"'):
                versions.append(value.strip()[1:-1])
            else:
                versions.append(name)
        return versions
    return []


def _natural_key(version: str) -> Tuple[Any, ...]:
    """Sort key that orders ``v2`` before ``v10``."""
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", version))


def order_versions(documents: Sequence[Mapping[str, Any]], declared: Sequence[str]) -> List[Tuple[str, Dict[str, Any]]]:
    """Order emitted documents oldest → newest.

    Args:
        documents: The emitted OpenAPI documents.
        declared: :func:`declared_versions` (the enum order).

    Returns:
        ``(version, document)`` pairs: declared versions in enum order, then any the enum did not
        name in natural order.
    """
    by_version = {str((doc.get("info") or {}).get("version") or ""): dict(doc) for doc in documents}
    ordered = [(version, by_version.pop(version)) for version in declared if version in by_version]
    ordered.extend((version, by_version[version]) for version in sorted(by_version, key=_natural_key))
    return ordered


def version_changes(versions: Sequence[TypeSpecVersion]) -> List[Dict[str, Any]]:
    """Grade each step from one version to the next with the OpenAPI compatibility analysis.

    Args:
        versions: The versions, oldest first.

    Returns:
        One record per adjacent pair: ``from`` / ``to``, ``overall`` (``breaking`` / ``safe`` /
        ``unknown``), ``counts`` per category, and the first :data:`MAX_RECORDED_FINDINGS` findings
        (``path`` / ``category`` / ``rule`` / ``message``) with ``finding_count``.
    """
    changes: List[Dict[str, Any]] = []
    for before, after in zip(versions, versions[1:]):
        overall, findings = analyze_schema_compatibility(before.openapi, after.openapi)
        counts: Dict[str, int] = {}
        for finding in findings:
            counts[finding.category] = counts.get(finding.category, 0) + 1
        changes.append(
            {
                "from": before.version,
                "to": after.version,
                "overall": overall,
                "counts": counts,
                "findings": [
                    {"path": f.path, "category": f.category, "rule": f.rule, "message": f.message}
                    for f in findings[:MAX_RECORDED_FINDINGS]
                ],
                "finding_count": len(findings),
            }
        )
    return changes
