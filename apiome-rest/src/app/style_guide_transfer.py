"""Style-guide import/export — Rule Set Import/Export (#1747).

A style guide's rule configuration — its built-in rule overrides (GOV-2.2) and its custom
rules (GOV-2.3) — lives in ``style_guide_rules`` rows. This module moves that configuration
between tenants and instances as one portable JSON document:

.. code-block:: json

    {
      "format": "apiome.style-guide",
      "formatVersion": 1,
      "exportedAt": "2026-11-12T10:00:00+00:00",
      "guide": {"name": "Payments Guide", "description": null,
                "externalLintProfile": "baseline"},
      "builtinRules": [{"ruleId": "naming.path-kebab-case", "enabled": true,
                        "severity": "error"}],
      "customRules": [{"ruleId": "headers-train-case",
                       "definition": {"description": "…", "severity": "warning",
                                      "given": ["$.paths"], "then": [{"function": "truthy"}]}}]
    }

* :func:`build_export_document` turns a guide row and its rule rows into that document.
* :func:`parse_import_document` strictly validates a document (pasted, uploaded, or fetched
  with :func:`fetch_style_guide_document`) and returns a :class:`StyleGuideImportPlan` of rows
  ready for ``replace_style_guide_builtin_rules`` / ``replace_style_guide_custom_rules``.

Built-in rule ids the importing instance does not register (an export from a newer or older
release) are **reported, never silently dropped**: they land in ``skipped`` with a reason and
the rest of the guide still imports. Everything else that is malformed rejects the whole
document with a :class:`StyleGuideTransferError` carrying a dotted ``pointer``, so nothing is
half-imported. Custom definitions are re-validated by :mod:`app.custom_rule_dsl`, so an
imported guide is guaranteed storable and evaluable.

Policy gates, assignments and revision history are deliberately not part of the document:
they are tenant-specific (project ids, role slugs) rather than rule configuration.

The module does no I/O apart from :func:`fetch_style_guide_document`, which delegates to the
SSRF-guarded ingestion boundary in :mod:`app.import_ingestion`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .custom_rule_dsl import (
    MAX_RULES_PER_GUIDE,
    CustomRuleValidationError,
    validate_custom_definition,
)

__all__ = [
    "FORMAT_ID",
    "FORMAT_VERSION",
    "MAX_DOCUMENT_BYTES",
    "REASON_UNKNOWN_RULE",
    "SEVERITIES",
    "SkippedRule",
    "StyleGuideImportPlan",
    "StyleGuideTransferError",
    "build_export_document",
    "export_filename",
    "fetch_style_guide_document",
    "parse_import_document",
]

#: The ``format`` discriminator every export carries.
FORMAT_ID = "apiome.style-guide"

#: The document version this release writes and reads.
FORMAT_VERSION = 1

#: Hard cap on an imported document (paste, upload, or URL fetch).
MAX_DOCUMENT_BYTES = 1_048_576

#: ``skipped[].reason`` for a built-in rule id this instance does not register.
REASON_UNKNOWN_RULE = "unknown_rule"

#: Severities a guide can assign a rule.
SEVERITIES = ("error", "warning", "info")

#: Upper bound on built-in rule entries — matches ``StyleGuideRulesPutRequest.rules``.
MAX_BUILTIN_RULES = 4096

_TOP_LEVEL_KEYS = ("format", "formatVersion", "exportedAt", "guide", "builtinRules", "customRules")
_GUIDE_KEYS = ("name", "description", "externalLintProfile")
_BUILTIN_KEYS = ("ruleId", "enabled", "severity")
_CUSTOM_KEYS = ("ruleId", "definition")


class StyleGuideTransferError(ValueError):
    """An import document could not be read or failed strict validation.

    Attributes:
        message: Human-readable, actionable description of the problem.
        pointer: Dotted pointer to the offending node (``builtinRules[3].severity``); empty
            when the problem is document-level (not JSON, oversized, unfetchable).
    """

    def __init__(self, message: str, pointer: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.pointer = pointer


@dataclass(frozen=True)
class SkippedRule:
    """A document entry the import reported instead of storing.

    Attributes:
        rule_id: The entry's ``ruleId``.
        reason: Machine-readable code (:data:`REASON_UNKNOWN_RULE`).
        detail: Human explanation.
    """

    rule_id: str
    reason: str
    detail: str


@dataclass(frozen=True)
class StyleGuideImportPlan:
    """A validated import document, shaped as the rows a new guide stores.

    Attributes:
        name: ``guide.name`` from the document (callers may override it).
        description: ``guide.description`` or ``None``.
        external_lint_profile: ``guide.externalLintProfile`` or ``None`` (store default).
        builtin_rows: ``{rule_id, enabled, severity}`` rows for registered built-in rules.
        custom_rows: ``{rule_id, enabled, severity, custom_def}`` rows, validated by the DSL.
        skipped: Entries reported instead of stored (unknown built-in ids).
        exported_at: The document's ``exportedAt`` string, when present.
    """

    name: Optional[str]
    description: Optional[str]
    external_lint_profile: Optional[str]
    builtin_rows: Tuple[Dict[str, Any], ...] = ()
    custom_rows: Tuple[Dict[str, Any], ...] = ()
    skipped: Tuple[SkippedRule, ...] = field(default_factory=tuple)
    exported_at: Optional[str] = None


# --- Export ------------------------------------------------------------------------------------


def build_export_document(
    guide: Mapping[str, Any],
    rows: Iterable[Mapping[str, Any]],
    *,
    reserved_rule_ids: frozenset,
    exported_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Serialize a guide and its ``style_guide_rules`` rows into the export document.

    Built-in rows (no ``custom_def``) become ``builtinRules`` sorted by rule id; custom rows
    become ``customRules`` in stored order, each definition re-validated so a corrupt row fails
    here rather than producing a document that will not import. A stored severity override on
    a custom row is folded into its definition (the same rule the custom-rules tab applies).

    Args:
        guide: The ``style_guides`` row (``name``, ``description``, ``external_lint_profile``).
        rows: The guide's ``style_guide_rules`` rows.
        reserved_rule_ids: The built-in rule ids, which custom ids must not shadow.
        exported_at: Timestamp to stamp; defaults to now (UTC).

    Returns:
        The JSON-serializable export document.

    Raises:
        CustomRuleValidationError: A stored custom definition no longer validates.
    """
    builtin_rules: List[Dict[str, Any]] = []
    custom_rules: List[Dict[str, Any]] = []
    for row in rows:
        if row.get("custom_def") is None:
            builtin_rules.append(
                {
                    "ruleId": row["rule_id"],
                    "enabled": bool(row.get("enabled")),
                    "severity": row.get("severity") or "warning",
                }
            )
            continue
        rule = validate_custom_definition(
            row["rule_id"], row["custom_def"], reserved_rule_ids=reserved_rule_ids
        )
        if row.get("severity") and rule.severity != row["severity"]:
            rule = replace(rule, severity=row["severity"])
        custom_rules.append({"ruleId": rule.rule_id, "definition": rule.as_dict()})
    builtin_rules.sort(key=lambda r: r["ruleId"])
    stamp = exported_at or datetime.now(timezone.utc)
    return {
        "format": FORMAT_ID,
        "formatVersion": FORMAT_VERSION,
        "exportedAt": stamp.isoformat(),
        "guide": {
            "name": guide["name"],
            "description": guide.get("description"),
            "externalLintProfile": guide.get("external_lint_profile") or "baseline",
        },
        "builtinRules": builtin_rules,
        "customRules": custom_rules,
    }


def export_filename(guide_name: str) -> str:
    """Return a download filename for a guide's export (``payments-guide.style-guide.json``).

    Args:
        guide_name: The guide's display name.

    Returns:
        A lowercase, filesystem-safe filename; ``style-guide.json`` when the name has no
        usable characters.
    """
    slug = "".join(ch if ch.isalnum() else "-" for ch in guide_name.lower())
    slug = "-".join(part for part in slug.split("-") if part)[:80].rstrip("-")
    return f"{slug}.style-guide.json" if slug else "style-guide.json"


# --- Import ------------------------------------------------------------------------------------


def _reject_unknown(value: Mapping[str, Any], allowed: Tuple[str, ...], pointer: str) -> None:
    """Raise when ``value`` carries keys outside ``allowed`` (typos must not import silently)."""
    unknown = sorted(str(k) for k in value if k not in allowed)
    if unknown:
        where = f"{pointer}." if pointer else ""
        raise StyleGuideTransferError(
            f"unknown key '{unknown[0]}' (expected one of: {', '.join(allowed)})",
            f"{where}{unknown[0]}",
        )


def _optional_string(value: Any, pointer: str, max_length: int) -> Optional[str]:
    """Validate an optional string field; blank strings normalize to ``None``."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise StyleGuideTransferError("must be a string or null", pointer)
    value = value.strip()
    if len(value) > max_length:
        raise StyleGuideTransferError(f"must be at most {max_length} characters", pointer)
    return value or None


def _load_json(text: str) -> Mapping[str, Any]:
    """Parse the document text into its top-level mapping."""
    if not text or not text.strip():
        raise StyleGuideTransferError("the document is empty")
    if len(text.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise StyleGuideTransferError(
            f"the document exceeds the {MAX_DOCUMENT_BYTES // 1024} KiB limit"
        )
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StyleGuideTransferError(
            f"not valid JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}"
        ) from exc
    if not isinstance(doc, dict):
        raise StyleGuideTransferError("the document must be a JSON object")
    return doc


def _check_header(doc: Mapping[str, Any]) -> None:
    """Validate ``format`` / ``formatVersion`` before reading anything else."""
    if doc.get("format") != FORMAT_ID:
        hint = (
            " — to bring in a .spectral.yaml use POST /v1/lint/custom-rules/import"
            if "rules" in doc or "extends" in doc
            else ""
        )
        raise StyleGuideTransferError(
            f"not an Apiome style-guide export: 'format' must be '{FORMAT_ID}'{hint}", "format"
        )
    version = doc.get("formatVersion")
    if not isinstance(version, int) or isinstance(version, bool):
        raise StyleGuideTransferError("'formatVersion' must be an integer", "formatVersion")
    if version != FORMAT_VERSION:
        raise StyleGuideTransferError(
            f"unsupported formatVersion {version} (this release reads version {FORMAT_VERSION})",
            "formatVersion",
        )
    _reject_unknown(doc, _TOP_LEVEL_KEYS, "")


def _parse_builtin_rules(
    raw: Any, registered: frozenset
) -> Tuple[List[Dict[str, Any]], List[SkippedRule]]:
    """Validate ``builtinRules``; unknown ids are skipped and reported, not stored."""
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        raise StyleGuideTransferError("must be an array", "builtinRules")
    if len(raw) > MAX_BUILTIN_RULES:
        raise StyleGuideTransferError(
            f"at most {MAX_BUILTIN_RULES} entries are allowed", "builtinRules"
        )
    rows: List[Dict[str, Any]] = []
    skipped: List[SkippedRule] = []
    seen: set = set()
    for index, entry in enumerate(raw):
        pointer = f"builtinRules[{index}]"
        if not isinstance(entry, dict):
            raise StyleGuideTransferError("must be an object", pointer)
        _reject_unknown(entry, _BUILTIN_KEYS, pointer)
        rule_id = entry.get("ruleId")
        if not isinstance(rule_id, str) or not rule_id.strip():
            raise StyleGuideTransferError("'ruleId' must be a non-empty string", f"{pointer}.ruleId")
        if rule_id in seen:
            raise StyleGuideTransferError(f"duplicate rule id '{rule_id}'", f"{pointer}.ruleId")
        seen.add(rule_id)
        enabled = entry.get("enabled")
        if not isinstance(enabled, bool):
            raise StyleGuideTransferError("'enabled' must be true or false", f"{pointer}.enabled")
        severity = entry.get("severity")
        if severity not in SEVERITIES:
            raise StyleGuideTransferError(
                f"'severity' must be one of: {', '.join(SEVERITIES)}", f"{pointer}.severity"
            )
        if rule_id not in registered:
            skipped.append(
                SkippedRule(
                    rule_id=rule_id,
                    reason=REASON_UNKNOWN_RULE,
                    detail=f"'{rule_id}' is not a built-in rule on this instance",
                )
            )
            continue
        rows.append({"rule_id": rule_id, "enabled": enabled, "severity": severity})
    return rows, skipped


def _parse_custom_rules(raw: Any, registered: frozenset) -> List[Dict[str, Any]]:
    """Validate ``customRules`` through the custom-rule DSL."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise StyleGuideTransferError("must be an array", "customRules")
    if len(raw) > MAX_RULES_PER_GUIDE:
        raise StyleGuideTransferError(
            f"a style guide may define at most {MAX_RULES_PER_GUIDE} custom rules", "customRules"
        )
    rows: List[Dict[str, Any]] = []
    seen: set = set()
    for index, entry in enumerate(raw):
        pointer = f"customRules[{index}]"
        if not isinstance(entry, dict):
            raise StyleGuideTransferError("must be an object", pointer)
        _reject_unknown(entry, _CUSTOM_KEYS, pointer)
        rule_id = entry.get("ruleId")
        if isinstance(rule_id, str) and rule_id in seen:
            raise StyleGuideTransferError(f"duplicate rule id '{rule_id}'", f"{pointer}.ruleId")
        try:
            rule = validate_custom_definition(
                rule_id,
                entry.get("definition"),
                pointer=f"{pointer}.definition",
                reserved_rule_ids=registered,
            )
        except CustomRuleValidationError as exc:
            raise StyleGuideTransferError(exc.message, exc.pointer) from exc
        seen.add(rule.rule_id)
        rows.append(
            {
                "rule_id": rule.rule_id,
                "enabled": True,
                "severity": rule.severity,
                "custom_def": rule.as_dict(),
            }
        )
    return rows


def parse_import_document(text: str, *, registered_rule_ids: frozenset) -> StyleGuideImportPlan:
    """Strictly validate an export document and plan the rows a new guide stores.

    Args:
        text: The document's JSON text.
        registered_rule_ids: This instance's built-in rule ids — the ids ``builtinRules`` may
            store and the ids ``customRules`` must not shadow.

    Returns:
        The :class:`StyleGuideImportPlan`.

    Raises:
        StyleGuideTransferError: The document is empty, oversized, not JSON, not an
            ``apiome.style-guide`` document of a supported version, or has a malformed entry.
    """
    doc = _load_json(text)
    _check_header(doc)

    guide = doc.get("guide")
    if guide is None:
        guide = {}
    if not isinstance(guide, dict):
        raise StyleGuideTransferError("must be an object", "guide")
    _reject_unknown(guide, _GUIDE_KEYS, "guide")
    name = _optional_string(guide.get("name"), "guide.name", 255)
    description = _optional_string(guide.get("description"), "guide.description", 4000)
    profile = _optional_string(guide.get("externalLintProfile"), "guide.externalLintProfile", 64)

    builtin_rows, skipped = _parse_builtin_rules(doc.get("builtinRules"), registered_rule_ids)
    custom_rows = _parse_custom_rules(doc.get("customRules"), registered_rule_ids)

    exported_at = doc.get("exportedAt")
    return StyleGuideImportPlan(
        name=name,
        description=description,
        external_lint_profile=profile,
        builtin_rows=tuple(builtin_rows),
        custom_rows=tuple(custom_rows),
        skipped=tuple(skipped),
        exported_at=exported_at if isinstance(exported_at, str) else None,
    )


def fetch_style_guide_document(url: str) -> Tuple[str, str]:
    """Fetch an export document over http/https through the SSRF-guarded ingestion boundary.

    Args:
        url: The document URL.

    Returns:
        ``(text, resolved_label)``.

    Raises:
        StyleGuideTransferError: On a malformed/blocked URL, a network failure, or an oversized
            or unparseable body.
    """
    from .import_ingestion import IngestionError, ingest_source
    from .intake_resource_guard import IntakeLimitError

    try:
        ingested = ingest_source("url", url=url, max_bytes=MAX_DOCUMENT_BYTES)
    except IngestionError as exc:
        raise StyleGuideTransferError(exc.message) from exc
    except IntakeLimitError as exc:
        raise StyleGuideTransferError(str(exc)) from exc
    return (ingested.text, ingested.resolved_label or url)
