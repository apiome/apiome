"""
Mustache-based rendering for persisted ChangeReportModel JSON (CR-03, #2701).

Uses the **chevron** library (Mustache); no arbitrary code execution.
"""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Dict, Mapping, Optional, Tuple

import chevron

from .change_report_default_templates import (
    DEFAULT_BODY_TEMPLATE,
    DEFAULT_FOOTNOTE_TEMPLATE,
    DEFAULT_HEADER_TEMPLATE,
    SYSTEM_TEMPLATE_ID,
    SYSTEM_TEMPLATE_SEMVER,
)

_VALID_SEMVER = re.compile(r"^[0-9A-Za-z._-]{1,64}$")


def get_generator_version() -> str:
    """Version string for footnotes (``apiome-rest`` package, or fallback)."""
    try:
        return f"apiome-rest/{version('apiome-rest')}"
    except PackageNotFoundError:
        return "apiome-rest/unknown"


def bundled_system_template_row() -> Dict[str, Any]:
    """In-memory system template (same content as seeded DB row)."""
    return {
        "id": SYSTEM_TEMPLATE_ID,
        "semver": SYSTEM_TEMPLATE_SEMVER,
        "header_template": DEFAULT_HEADER_TEMPLATE,
        "body_template": DEFAULT_BODY_TEMPLATE,
        "footnote_template": DEFAULT_FOOTNOTE_TEMPLATE,
        "owner_tenant_id": None,
    }


def build_render_metadata(
    *,
    product_name: str = "API",
    from_version_label: str = "—",
    to_version_label: str = "—",
    publish_timestamp: str = "—",
    static_footnote: str = "",
) -> Dict[str, str]:
    """Optional header/footnote placeholders (filled by CR-04 publish hook later)."""
    return {
        "productName": product_name,
        "fromVersionLabel": from_version_label,
        "toVersionLabel": to_version_label,
        "publishTimestamp": publish_timestamp,
        "staticFootnote": static_footnote,
    }


def _counts(cm: Mapping[str, Any]) -> Dict[str, Any]:
    schemas = cm.get("schemas") if isinstance(cm.get("schemas"), dict) else {}
    added = schemas.get("added") if isinstance(schemas.get("added"), list) else []
    removed = schemas.get("removed") if isinstance(schemas.get("removed"), list) else []
    modified = schemas.get("modified") if isinstance(schemas.get("modified"), list) else []
    props = cm.get("properties") if isinstance(cm.get("properties"), list) else []
    refs = cm.get("references") if isinstance(cm.get("references"), list) else []
    rels = cm.get("relationships") if isinstance(cm.get("relationships"), list) else []
    docs = cm.get("documentation") if isinstance(cm.get("documentation"), list) else []
    warns = cm.get("warnings") if isinstance(cm.get("warnings"), list) else []
    skipped = cm.get("skipped") if isinstance(cm.get("skipped"), list) else []
    return {
        "schemaCounts": {"added": len(added), "removed": len(removed), "modified": len(modified)},
        "propertyCount": len(props),
        "referenceCount": len(refs),
        "relationshipCount": len(rels),
        "documentationCount": len(docs),
        "warningCount": len(warns),
        "skippedCount": len(skipped),
    }


def build_mustache_context(
    change_model: Mapping[str, Any],
    metadata: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """
    Single merged context for header, body, and footnote templates.

    Templates may use only the keys they need; Mustache ignores the rest.
    """
    md = dict(metadata or {})
    cm = dict(change_model)
    meta = build_render_metadata(
        product_name=md.get("productName") or md.get("product_name") or "API",
        from_version_label=md.get("fromVersionLabel") or md.get("from_version_label") or "—",
        to_version_label=md.get("toVersionLabel") or md.get("to_version_label") or "—",
        publish_timestamp=md.get("publishTimestamp") or md.get("publish_timestamp") or "—",
        static_footnote=md.get("staticFootnote") or md.get("static_footnote") or "",
    )

    schemas = cm.get("schemas") if isinstance(cm.get("schemas"), dict) else {}
    properties = cm.get("properties") if isinstance(cm.get("properties"), list) else []
    references = cm.get("references") if isinstance(cm.get("references"), list) else []
    relationships = cm.get("relationships") if isinstance(cm.get("relationships"), list) else []
    documentation = cm.get("documentation") if isinstance(cm.get("documentation"), list) else []
    warnings = cm.get("warnings") if isinstance(cm.get("warnings"), list) else []
    skipped = cm.get("skipped") if isinstance(cm.get("skipped"), list) else []

    counts = _counts(cm)
    ctx: Dict[str, Any] = {
        **meta,
        "staticNote": meta.get("staticFootnote") or md.get("staticNote") or "",
        "schemaVersion": cm.get("schemaVersion") or cm.get("schema_version") or "?",
        "schemas": schemas,
        "properties": properties,
        "references": references,
        "relationships": relationships,
        "documentation": documentation,
        "warnings": warnings,
        "skipped": skipped,
        **counts,
        "generatorVersion": get_generator_version(),
        "schemaSection": bool(
            (schemas.get("added") or [])
            or (schemas.get("removed") or [])
            or (schemas.get("modified") or [])
        ),
        "propertiesSection": bool(properties),
        "referencesSection": bool(references),
        "relationshipsSection": bool(relationships),
        "documentationSection": bool(documentation),
        "warningsSection": bool(warnings),
        "skippedSection": bool(skipped),
    }
    return ctx


def render_mustache(template: str, context: Mapping[str, Any]) -> str:
    return chevron.render(template, context)


def render_change_report_from_templates(
    change_model: Mapping[str, Any],
    header_template: str,
    body_template: str,
    footnote_template: str,
    metadata: Optional[Mapping[str, str]] = None,
) -> Tuple[str, str, str]:
    """Render header, body, and footnote using Mustache and a shared context."""
    ctx = build_mustache_context(change_model, metadata)
    header = render_mustache(header_template, ctx).strip()
    body = render_mustache(body_template, ctx).strip()
    footnote = render_mustache(footnote_template, ctx).strip()
    return header, body, footnote


def validate_change_report_templates(
    header_template: str,
    body_template: str,
    footnote_template: str,
) -> None:
    """
    Ensure templates parse and render with a **minimal** synthetic context.

    Raises:
        ValueError: with a short message suitable for HTTP 400.
    """
    minimal: Dict[str, Any] = {
        "productName": "P",
        "fromVersionLabel": "a",
        "toVersionLabel": "b",
        "publishTimestamp": "t",
        "schemaVersion": "1.0",
        "schemaCounts": {"added": 0, "removed": 0, "modified": 0},
        "propertyCount": 0,
        "referenceCount": 0,
        "relationshipCount": 0,
        "documentationCount": 0,
        "warningCount": 0,
        "skippedCount": 0,
        "schemas": {"added": [], "removed": [], "modified": []},
        "properties": [],
        "references": [],
        "relationships": [],
        "documentation": [],
        "warnings": [],
        "skipped": [],
        "generatorVersion": "test",
        "staticNote": "",
        "schemaSection": False,
        "propertiesSection": False,
        "referencesSection": False,
        "relationshipsSection": False,
        "documentationSection": False,
        "warningsSection": False,
        "skippedSection": False,
    }
    for label, tpl in (
        ("headerTemplate", header_template),
        ("bodyTemplate", body_template),
        ("footnoteTemplate", footnote_template),
    ):
        try:
            chevron.render(tpl, minimal)
        except Exception as exc:
            raise ValueError(f"{label}: {exc}") from exc


def validate_template_semver(semver: str) -> None:
    if not semver or not _VALID_SEMVER.match(semver):
        raise ValueError("semver must be 1–64 characters: [A-Za-z0-9._-]")


def template_row_to_strings(row: Mapping[str, Any]) -> Tuple[str, str, str]:
    return (
        str(row["header_template"]),
        str(row["body_template"]),
        str(row["footnote_template"]),
    )


def render_from_template_row(
    change_model: Mapping[str, Any],
    template_row: Mapping[str, Any],
    metadata: Optional[Mapping[str, str]] = None,
) -> Tuple[str, str, str]:
    h, b, f = template_row_to_strings(template_row)
    return render_change_report_from_templates(change_model, h, b, f, metadata=metadata)


# Backwards-compatible name used by CR-02 routes/tests.
def placeholder_render_from_change_model(
    change_model: Dict[str, Any],
    metadata: Optional[Mapping[str, str]] = None,
) -> Tuple[str, str, str]:
    """Render with the **bundled** system default templates (no DB lookup)."""
    row = bundled_system_template_row()
    return render_from_template_row(change_model, row, metadata=metadata)
