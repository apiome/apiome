"""
Pluggable compatibility check engine: deterministic classification, findings, and rule hit counts.

Wraps :func:`analyze_schema_compatibility` for use in REST routes and commit/merge pipelines.

Since COA-5.6 (#7082) the diff family — classified diff, the compatibility check and its evidence,
merge-request changes (which call the classified diff) and the version changelog — reads each side
with :func:`read_revision_openapi`: the revision's rendered OpenAPI document from the document
store (COA-5.5, :mod:`app.rendered_documents`), rendered only on a miss. Two sides whose rendered
digests are equal are the same document, so :func:`same_document` lets a caller answer "no
changes" without classifying, and :func:`document_cache_header` reports ``hit`` / ``miss`` per
side in ``X-Apiome-Document-Cache``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Tuple

from fastapi import HTTPException

from .database import db
from .openapi_generator import generate_openapi_spec
from .rendered_documents import KIND_OPENAPI, rendered_document
from .schema_compatibility import (
    CompatibilityFinding,
    CompatibilityRules,
    Overall,
    analyze_schema_compatibility,
)
from .spec_snapshot import load_classes_and_properties

logger = logging.getLogger(__name__)

#: Response header naming, per side, whether the rendered document came from the store (COA-5.6).
DOCUMENT_CACHE_HEADER = "X-Apiome-Document-Cache"
#: The header's entry in a route's ``responses={200: {"headers": …}}`` OpenAPI description.
DOCUMENT_CACHE_HEADER_DOC: Dict[str, Any] = {
    DOCUMENT_CACHE_HEADER: {
        "description": (
            "Whether each side's rendered OpenAPI document came from the document store (`hit`) or "
            "was rendered by this request (`miss`), for example `base=hit, head=miss`. A transitive "
            "comparison adds `prior` (`miss` when any earlier revision missed). Absent when the "
            "sides were compared as canonical models."
        ),
        "schema": {"type": "string"},
    }
}
#: :attr:`RevisionOpenApi.cache` values.
CACHE_HIT = "hit"
CACHE_MISS = "miss"


def compat_report_fingerprint(
    overall: str,
    finding_dicts: List[Dict[str, Any]],
    deprecation_dicts: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Stable hash over sorted findings (and optional deprecation warnings) for audit/API identity.
    """
    payload: Dict[str, Any] = {
        "overall": overall,
        "findings": sorted(
            finding_dicts,
            key=lambda x: (x.get("path", ""), x.get("rule", ""), x.get("id", "")),
        ),
    }
    if deprecation_dicts:
        payload["deprecationWarnings"] = sorted(
            deprecation_dicts,
            key=lambda x: (x.get("revisionId", ""), x.get("role", "")),
        )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def rule_hits_from_findings(findings: List[CompatibilityFinding]) -> Mapping[str, int]:
    """Count findings per rule id (deterministic key order when serialized via sorted())."""
    hits: Dict[str, int] = {}
    for f in findings:
        hits[f.rule] = hits.get(f.rule, 0) + 1
    return MappingProxyType(hits)


@dataclass(frozen=True)
class CompatibilityCheckResult:
    """Output of :class:`CompatibilityCheckEngine` — suitable for APIs and audit payloads."""

    overall: Overall
    findings: Tuple[CompatibilityFinding, ...]
    rule_hits: Mapping[str, int]
    report_fingerprint: str

    @property
    def finding_dicts(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": f.id,
                "path": f.path,
                "category": f.category,
                "rule": f.rule,
                "message": f.message,
            }
            for f in self.findings
        ]


class CompatibilityCheckEngine:
    """
    Pluggable rules via :class:`CompatibilityRules`; analysis is pure and deterministic
    (findings sorted by path, rule, message).
    """

    @staticmethod
    def run(
        base_spec: Dict[str, Any],
        head_spec: Dict[str, Any],
        rules: Optional[CompatibilityRules] = None,
    ) -> CompatibilityCheckResult:
        r = rules or CompatibilityRules()
        overall, findings_list = analyze_schema_compatibility(base_spec, head_spec, r)
        findings = tuple(findings_list)
        rh = rule_hits_from_findings(list(findings))
        fdicts = [
            {
                "id": f.id,
                "path": f.path,
                "category": f.category,
                "rule": f.rule,
                "message": f.message,
            }
            for f in findings
        ]
        fp = compat_report_fingerprint(overall, fdicts)
        return CompatibilityCheckResult(
            overall=overall,
            findings=findings,
            rule_hits=rh,
            report_fingerprint=fp,
        )


def compat_audit_detail(
    *,
    pipeline: str,
    base_revision_id: str,
    head_revision_id: str,
    result: CompatibilityCheckResult,
) -> Dict[str, Any]:
    """Structured ``workflow_audit.detail`` for persisted compatibility runs (#2589)."""
    return {
        "pipeline": pipeline,
        "baseRevisionId": base_revision_id,
        "headRevisionId": head_revision_id,
        "overall": result.overall,
        "ruleHits": dict(sorted(result.rule_hits.items())),
        "reportFingerprint": result.report_fingerprint,
        "findingCount": len(result.findings),
    }


def openapi_for_revision(
    version: Dict[str, Any],
    tenant_slug: str,
    tenant_id: str,
    *,
    component_pin_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Build the OpenAPI spec for a persisted revision.

    Shared helper used by the compatibility API and push/merge audit pipelines.
    Extracted from ``compatibility_routes`` to avoid cross-router coupling.

    ``component_pin_rows`` replaces the version's stored component-library pins when given
    (DCW-3.4: the bulk-upgrade preview builds the document as it would read after the upgrade);
    ``None`` reads the stored pins, as before.
    """
    project = db.get_project_by_id(version["project_id"], tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found for revision")
    # One query per table, not one per class (COA-5.5, #7081).
    classes, all_properties = load_classes_and_properties(db, version["id"])
    return generate_openapi_spec(
        tenant_slug,
        project["slug"],
        version["version_id"],
        classes,
        all_properties,
        project.get("description"),
        version_db_id=version["id"],
        revision_metadata=version.get("metadata"),
        project_metadata=project.get("metadata"),
        component_pin_rows=component_pin_rows,
    )


@dataclass(frozen=True)
class RevisionOpenApi:
    """A revision's OpenAPI document as the diff family reads it (COA-5.6, #7082).

    Attributes:
        spec: The OpenAPI document. The caller owns it (a fresh parse on every read).
        sha256: Lower-case hex SHA-256 of the rendered bytes, or ``None`` when the document was
            generated outside the cache (see :func:`read_revision_openapi`).
        cache: :data:`CACHE_HIT` when the bytes came from the document store; :data:`CACHE_MISS`
            when this read generated them.
    """

    spec: Dict[str, Any]
    sha256: Optional[str]
    cache: str


def read_revision_openapi(version: Dict[str, Any], tenant_slug: str, tenant_id: str) -> RevisionOpenApi:
    """Read a persisted revision's OpenAPI document through the rendered document cache.

    The document is the one :func:`openapi_for_revision` builds — the cache renders it with the
    same generator from the same rows — so a warm read does no generation at all. When the cache
    cannot serve the revision (no live row in the tenant, or the render through the cache fails)
    the document is generated directly by :func:`openapi_for_revision`, which raises what it always
    raised (for example 404 when the project is gone).

    Args:
        version: The revision row (needs ``id``; ``project_id``, ``version_id`` and ``metadata`` for
            the direct fallback).
        tenant_slug: Tenant slug, passed to the direct fallback.
        tenant_id: The tenant that must own the revision.

    Returns:
        The document, its digest when it went through the cache, and whether it was a hit.
    """
    try:
        document = rendered_document(str(version["id"]), KIND_OPENAPI, tenant_id=str(tenant_id), database=db)
    except Exception as exc:  # noqa: BLE001 - the direct path below raises the real error, if any
        logger.warning("rendered OpenAPI not read version_id=%s: %s", version.get("id"), type(exc).__name__)
        document = None
    if document is None:
        spec = openapi_for_revision(version, tenant_slug, tenant_id)
        return RevisionOpenApi(spec=spec, sha256=None, cache=CACHE_MISS)
    return RevisionOpenApi(
        spec=document.json(),
        sha256=document.sha256,
        cache=CACHE_HIT if document.cached else CACHE_MISS,
    )


def same_document(left: RevisionOpenApi, right: RevisionOpenApi) -> bool:
    """Report whether two reads are byte-identical rendered documents, so their diff is empty.

    Only digests from the cache count: a document generated outside it has no digest and is
    never assumed equal to anything.
    """
    return bool(left.sha256) and left.sha256 == right.sha256


def document_cache_header(sides: List[Tuple[str, RevisionOpenApi]]) -> Optional[str]:
    """Build the ``X-Apiome-Document-Cache`` value for the sides a comparison read.

    Args:
        sides: ``(role, read)`` pairs in reading order. Roles are ``base`` and ``head``, and
            ``prior`` for each earlier revision a transitive comparison read; the priors are
            reported once, as ``miss`` when any of them missed.

    Returns:
        For example ``"base=hit, head=miss, prior=hit"``, or ``None`` when no side was read.
    """
    statuses: Dict[str, str] = {}
    for role, read in sides:
        if statuses.get(role) == CACHE_MISS:
            continue
        statuses[role] = read.cache
    if not statuses:
        return None
    return ", ".join(f"{role}={status}" for role, status in statuses.items())
