"""
Semantic OpenAPI 3.x diff: two resolved documents -> versioned ChangeReportModel JSON (#2699).

Inputs are expected to be resolved (internal $refs only, dereferenced components). Unsupported
constructs are recorded in ``warnings`` / ``skipped`` rather than omitted silently.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set, Tuple

CHANGE_REPORT_MODEL_VERSION = "1.0"

# MVP: diff these ``info`` fields; nested contact/license are skipped explicitly.
_INFO_SCALAR_KEYS = ("title", "version", "description", "termsOfService")

# Keys whose scalar/array differences are treated as constraint changes (not type).
_CONSTRAINT_KEYS = frozenset(
    {
        "enum",
        "format",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minLength",
        "maxLength",
        "pattern",
        "multipleOf",
        "minItems",
        "maxItems",
        "uniqueItems",
        "default",
        "const",
        "nullable",
        "readOnly",
        "writeOnly",
        "deprecated",
    }
)

_DOC_KEYS = frozenset({"description", "title", "summary"})

_REL_KEYS = frozenset({"allOf", "oneOf", "anyOf", "discriminator"})


def _json_pointer_join(base: str, segment: str) -> str:
    escaped_segment = segment.replace("~", "~0").replace("/", "~1")
    if base == "":
        return f"/{escaped_segment}"
    return f"{base}/{escaped_segment}"


def sort_keys_deep(obj: Any) -> Any:
    """Recursively sort mapping keys for deterministic equality / serialization."""
    if isinstance(obj, dict):
        return {k: sort_keys_deep(obj[k]) for k in sorted(obj.keys())}
    if isinstance(obj, list):
        return [sort_keys_deep(x) for x in obj]
    return obj


def _sorted_json(obj: Any) -> str:
    return json.dumps(sort_keys_deep(obj), sort_keys=True, separators=(",", ":"))


def _ref_string(node: Any) -> Optional[str]:
    if not isinstance(node, dict):
        return None
    r = node.get("$ref")
    return r if isinstance(r, str) else None


def _classify_leaf_change(ptr: str, key: Optional[str], parent_key: Optional[str]) -> str:
    if key == "type" or ptr.endswith("/type"):
        return "type_changed"
    if key == "required" or parent_key == "required" or ptr.endswith("/required"):
        return "required_changed"
    if key in _DOC_KEYS or (parent_key and parent_key in _DOC_KEYS):
        return "documentation_changed"
    if key in _CONSTRAINT_KEYS:
        return "constraint_changed"
    return "constraint_changed"


class _Accumulator:
    __slots__ = (
        "properties",
        "references",
        "relationships",
        "documentation",
        "warnings",
        "skipped",
    )

    def __init__(self) -> None:
        self.properties: List[Dict[str, Any]] = []
        self.references: List[Dict[str, Any]] = []
        self.relationships: List[Dict[str, Any]] = []
        self.documentation: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []
        self.skipped: List[Dict[str, Any]] = []


def _emit_doc(
    acc: _Accumulator,
    scope: str,
    path: str,
    field: str,
    change_kind: str,
    baseline_preview: Any,
    candidate_preview: Any,
    *,
    method: Optional[str] = None,
    schema_name: Optional[str] = None,
) -> None:
    row: Dict[str, Any] = {
        "scope": scope,
        "path": path,
        "field": field,
        "changeKind": change_kind,
        "baselinePreview": baseline_preview,
        "candidatePreview": candidate_preview,
    }
    if method is not None:
        row["method"] = method.lower()
    if schema_name is not None:
        row["schemaName"] = schema_name
    acc.documentation.append(row)


def _emit_prop(
    acc: _Accumulator,
    schema_name: str,
    path: str,
    change_kind: str,
    detail: Optional[str] = None,
) -> None:
    acc.properties.append(
        {
            "schemaName": schema_name,
            "path": path,
            "changeKind": change_kind,
            "detail": detail,
        }
    )


def _emit_ref(
    acc: _Accumulator,
    schema_name: str,
    path: str,
    change_kind: str,
    baseline_ref: Optional[str],
    candidate_ref: Optional[str],
) -> None:
    acc.references.append(
        {
            "schemaName": schema_name,
            "path": path,
            "changeKind": change_kind,
            "baselineRef": baseline_ref,
            "candidateRef": candidate_ref,
        }
    )


def _emit_rel(
    acc: _Accumulator,
    schema_name: str,
    path: str,
    kind: str,
    change_kind: str,
    detail: Optional[str],
) -> None:
    acc.relationships.append(
        {
            "schemaName": schema_name,
            "path": path,
            "kind": kind,
            "changeKind": change_kind,
            "detail": detail,
        }
    )


def _warn_external_ref(acc: _Accumulator, ref: str, path: str) -> None:
    if ref.startswith("#"):
        return
    acc.warnings.append(
        {
            "code": "external_ref_not_followed",
            "message": "External or non-document $ref is not expanded; comparison may be incomplete.",
            "path": path,
            "ref": ref,
        }
    )


def _scan_external_refs(obj: Any, ptr: str, acc: _Accumulator, seen: Set[str]) -> None:
    """Emit warnings for external $ref values even when subtrees are otherwise unchanged."""
    if isinstance(obj, dict):
        r = obj.get("$ref")
        if isinstance(r, str) and not r.startswith("#"):
            key = f"{ptr}|{r}"
            if key not in seen:
                seen.add(key)
                _warn_external_ref(acc, r, ptr if ptr else "/")
        for k, v in obj.items():
            _scan_external_refs(v, _json_pointer_join(ptr, str(k)), acc, seen)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _scan_external_refs(v, f"{ptr}/{i}" if ptr else f"/{i}", acc, seen)


def _diff_scalar_schema(
    schema_name: str,
    base: Any,
    cand: Any,
    ptr: str,
    key: Optional[str],
    parent_key: Optional[str],
    acc: _Accumulator,
) -> None:
    if base == cand:
        return
    if type(base) is not type(cand):
        _emit_prop(acc, schema_name, ptr, "type_changed", f"{type(base).__name__} -> {type(cand).__name__}")
        return
    ck = _classify_leaf_change(ptr, key, parent_key)
    if ck == "documentation_changed":
        _emit_doc(acc, "schema", ptr, key or "value", "modified", base, cand, schema_name=schema_name)
        return
    if ck == "type_changed":
        _emit_prop(acc, schema_name, ptr, "type_changed", f"{base!r} -> {cand!r}")
        return
    if ck == "required_changed":
        _emit_prop(acc, schema_name, ptr, "required_changed", f"{base!r} -> {cand!r}")
        return
    _emit_prop(acc, schema_name, ptr, ck, f"{base!r} -> {cand!r}")


def _diff_json_schema_value(
    schema_name: str,
    base: Any,
    cand: Any,
    ptr: str,
    key: Optional[str],
    parent_key: Optional[str],
    acc: _Accumulator,
    depth: int,
) -> None:
    if depth > 64:
        acc.skipped.append({"reason": "max_depth_exceeded", "path": ptr, "schemaName": schema_name})
        return

    if type(base) is not type(cand):
        _emit_prop(acc, schema_name, ptr, "type_changed", f"{type(base).__name__} -> {type(cand).__name__}")
        return

    if isinstance(base, dict) and isinstance(cand, dict):
        br, cr = _ref_string(base), _ref_string(cand)
        if br or cr:
            if br:
                _warn_external_ref(acc, br, ptr)
            if cr:
                _warn_external_ref(acc, cr, ptr)
            if br != cr:
                rk = "retargeted" if br and cr else ("added" if not br else "removed")
                _emit_ref(acc, schema_name, ptr, rk, br, cr)
            keys_b = set(base.keys())
            keys_c = set(cand.keys())
            for k in sorted(keys_b | keys_c):
                if k == "$ref":
                    continue
                pb, pc = base.get(k), cand.get(k)
                np = _json_pointer_join(ptr, k)
                if pb is None and pc is not None:
                    if k in _DOC_KEYS:
                        _emit_doc(acc, "schema", np, k, "added", None, pc, schema_name=schema_name)
                    elif k in _REL_KEYS:
                        _emit_rel(acc, schema_name, np, k, "added", None)
                    else:
                        _emit_prop(acc, schema_name, np, "added", None)
                elif pb is not None and pc is None:
                    if k in _DOC_KEYS:
                        _emit_doc(acc, "schema", np, k, "removed", pb, None, schema_name=schema_name)
                    elif k in _REL_KEYS:
                        _emit_rel(acc, schema_name, np, k, "removed", None)
                    else:
                        _emit_prop(acc, schema_name, np, "removed", None)
                elif pb != pc:
                    _diff_json_schema_value(schema_name, pb, pc, np, k, k, acc, depth + 1)
            return

    if isinstance(base, dict) and isinstance(cand, dict):
        all_keys = set(base.keys()) | set(cand.keys())
        for k in sorted(all_keys):
            if k in _REL_KEYS:
                pb, pc = base.get(k), cand.get(k)
                np = _json_pointer_join(ptr, k)
                if pb != pc:
                    detail = None
                    if isinstance(pb, list) and isinstance(pc, list) and k != "discriminator":
                        detail = f"length {len(pb)} -> {len(pc)}"
                    _emit_rel(acc, schema_name, np, k, "modified", detail)
                if pb is not None and pc is not None:
                    _diff_json_schema_value(schema_name, pb, pc, np, k, k, acc, depth + 1)
                continue
            pb, pc = base.get(k), cand.get(k)
            np = _json_pointer_join(ptr, k)
            if pb is None and pc is not None:
                _emit_prop(acc, schema_name, np, "added", None)
            elif pb is not None and pc is None:
                _emit_prop(acc, schema_name, np, "removed", None)
            else:
                _diff_json_schema_value(schema_name, pb, pc, np, k, k, acc, depth + 1)
        return

    if isinstance(base, list) and isinstance(cand, list):
        if key == "required":
            sb, sc = sorted(base), sorted(cand)
            if sb != sc:
                _emit_prop(acc, schema_name, ptr, "required_changed", f"{sb!r} -> {sc!r}")
            return
        if base != cand:
            _diff_scalar_schema(schema_name, base, cand, ptr, key, parent_key, acc)
        return

    _diff_scalar_schema(schema_name, base, cand, ptr, key, parent_key, acc)


def _diff_components_schemas(
    base_schemas: Dict[str, Any],
    cand_schemas: Dict[str, Any],
    acc: _Accumulator,
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]], List[Dict[str, str]]]:
    added: List[Dict[str, str]] = []
    removed: List[Dict[str, str]] = []
    modified: List[Dict[str, str]] = []

    b_names = set(base_schemas.keys())
    c_names = set(cand_schemas.keys())
    for n in sorted(c_names - b_names):
        added.append({"name": n})
    for n in sorted(b_names - c_names):
        removed.append({"name": n})
    for n in sorted(b_names & c_names):
        bs, cs = base_schemas[n], cand_schemas[n]
        if _sorted_json(bs) == _sorted_json(cs):
            continue
        _diff_json_schema_value(n, bs, cs, "", None, None, acc, 0)
        modified.append({"name": n})

    return added, removed, modified


def _diff_info(base: Dict[str, Any], cand: Dict[str, Any], acc: _Accumulator) -> None:
    for k in ("contact", "license"):
        if k in base or k in cand:
            acc.skipped.append({"reason": "info_nested_object_not_diffed_mvp", "path": f"/info/{k}"})
    for k in _INFO_SCALAR_KEYS:
        vb, vc = base.get(k), cand.get(k)
        if vb == vc:
            continue
        if vb is None and vc is not None:
            _emit_doc(acc, "info", f"/info/{k}", k, "added", vb, vc)
        elif vb is not None and vc is None:
            _emit_doc(acc, "info", f"/info/{k}", k, "removed", vb, vc)
        else:
            _emit_doc(acc, "info", f"/info/{k}", k, "modified", vb, vc)


def _diff_paths_operations(base_paths: Dict[str, Any], cand_paths: Dict[str, Any], acc: _Accumulator) -> None:
    http_methods = frozenset(
        {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
    )
    all_path_keys = set(base_paths.keys()) | set(cand_paths.keys())
    for p in sorted(all_path_keys):
        bo = base_paths.get(p) if isinstance(base_paths.get(p), dict) else {}
        co = cand_paths.get(p) if isinstance(cand_paths.get(p), dict) else {}
        if not isinstance(bo, dict):
            bo = {}
        if not isinstance(co, dict):
            co = {}
        for m in sorted(set(bo.keys()) | set(co.keys())):
            if m not in http_methods:
                continue
            op_b = bo.get(m)
            op_c = co.get(m)
            if not isinstance(op_b, dict) and not isinstance(op_c, dict):
                continue
            if isinstance(op_b, dict) ^ isinstance(op_c, dict):
                acc.skipped.append(
                    {
                        "reason": "operation_present_vs_absent",
                        "path": f"{p}#{m}",
                    }
                )
                continue
            assert isinstance(op_b, dict) and isinstance(op_c, dict)
            for fld in ("summary", "description"):
                vb, vc = op_b.get(fld), op_c.get(fld)
                if vb == vc:
                    continue
                if vb is None and vc is not None:
                    _emit_doc(acc, "operation", p, fld, "added", vb, vc, method=m)
                elif vb is not None and vc is None:
                    _emit_doc(acc, "operation", p, fld, "removed", vb, vc, method=m)
                else:
                    _emit_doc(acc, "operation", p, fld, "modified", vb, vc, method=m)


def _sort_report_lists(report: Dict[str, Any]) -> None:
    """Stable ordering for determinism."""

    def sort_key(row: Dict[str, Any]) -> Tuple:
        return (
            row.get("schemaName") or "",
            row.get("path") or "",
            row.get("changeKind") or "",
            row.get("kind") or "",
            row.get("method") or "",
            row.get("field") or "",
        )

    for section in ("properties", "references", "relationships"):
        if section in report and isinstance(report[section], list):
            report[section] = sorted(report[section], key=sort_key)
    if "documentation" in report and isinstance(report["documentation"], list):
        report["documentation"] = sorted(
            report["documentation"],
            key=lambda r: (
                r.get("scope") or "",
                r.get("schemaName") or "",
                r.get("path") or "",
                r.get("method") or "",
                r.get("field") or "",
                r.get("changeKind") or "",
            ),
        )
    if "warnings" in report and isinstance(report["warnings"], list):
        warn_seen: Set[Tuple[str, str, str]] = set()
        uniq_warn: List[Dict[str, Any]] = []
        for w in sorted(
            report["warnings"],
            key=lambda x: (x.get("code"), x.get("path") or "", x.get("ref") or ""),
        ):
            t = (str(w.get("code")), str(w.get("path") or ""), str(w.get("ref") or ""))
            if t in warn_seen:
                continue
            warn_seen.add(t)
            uniq_warn.append(w)
        report["warnings"] = uniq_warn
    if "skipped" in report and isinstance(report["skipped"], list):
        report["skipped"] = sorted(report["skipped"], key=lambda s: (s.get("reason"), s.get("path") or ""))


def build_change_report(baseline_openapi: Dict[str, Any], candidate_openapi: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compare two resolved OpenAPI 3.x JSON documents and return a ChangeReportModel dict.

    The structure is versioned via ``schemaVersion`` (semantic version of this JSON shape).
    """
    acc = _Accumulator()

    b_vers = str(baseline_openapi.get("openapi") or "")
    c_vers = str(candidate_openapi.get("openapi") or "")
    if b_vers and c_vers and b_vers != c_vers:
        acc.warnings.append(
            {
                "code": "openapi_version_mismatch",
                "message": f"Baseline openapi field {b_vers!r} differs from candidate {c_vers!r}.",
                "path": "/openapi",
            }
        )

    try:
        raw_size = len(json.dumps(baseline_openapi)) + len(json.dumps(candidate_openapi))
        if raw_size > 5_000_000:
            acc.warnings.append(
                {
                    "code": "large_document",
                    "message": f"Combined JSON size {raw_size} bytes exceeds soft limit; diff may be slow.",
                    "path": "/",
                }
            )
    except (TypeError, ValueError):
        acc.warnings.append({"code": "size_check_failed", "message": "Could not measure document size.", "path": "/"})

    b_comp = baseline_openapi.get("components") if isinstance(baseline_openapi.get("components"), dict) else {}
    c_comp = candidate_openapi.get("components") if isinstance(candidate_openapi.get("components"), dict) else {}
    b_schemas = b_comp.get("schemas") if isinstance(b_comp.get("schemas"), dict) else {}
    c_schemas = c_comp.get("schemas") if isinstance(c_comp.get("schemas"), dict) else {}

    if not isinstance(b_schemas, dict):
        b_schemas = {}
    if not isinstance(c_schemas, dict):
        c_schemas = {}

    ref_seen: Set[str] = set()
    for name, sch in b_schemas.items():
        _scan_external_refs(sch, f"/components/schemas/{name}", acc, ref_seen)
    for name, sch in c_schemas.items():
        _scan_external_refs(sch, f"/components/schemas/{name}", acc, ref_seen)

    added, removed, modified = _diff_components_schemas(b_schemas, c_schemas, acc)

    b_info = baseline_openapi.get("info") if isinstance(baseline_openapi.get("info"), dict) else {}
    c_info = candidate_openapi.get("info") if isinstance(candidate_openapi.get("info"), dict) else {}
    if not isinstance(b_info, dict):
        b_info = {}
    if not isinstance(c_info, dict):
        c_info = {}
    _diff_info(b_info, c_info, acc)

    b_paths = baseline_openapi.get("paths") if isinstance(baseline_openapi.get("paths"), dict) else {}
    c_paths = candidate_openapi.get("paths") if isinstance(candidate_openapi.get("paths"), dict) else {}
    if not isinstance(b_paths, dict):
        b_paths = {}
    if not isinstance(c_paths, dict):
        c_paths = {}
    _diff_paths_operations(b_paths, c_paths, acc)

    for section in ("callbacks", "webhooks"):
        if isinstance(baseline_openapi.get(section), dict) or isinstance(candidate_openapi.get(section), dict):
            acc.skipped.append({"reason": f"{section}_not_diffed_mvp", "path": f"/{section}"})

    report: Dict[str, Any] = {
        "schemaVersion": CHANGE_REPORT_MODEL_VERSION,
        "schemas": {
            "added": added,
            "removed": removed,
            "modified": modified,
        },
        "properties": acc.properties,
        "references": acc.references,
        "relationships": acc.relationships,
        "documentation": acc.documentation,
        "warnings": acc.warnings,
        "skipped": acc.skipped,
    }
    _sort_report_lists(report)
    return report


def compute_openapi_change_report(
    baseline_openapi: Dict[str, Any],
    candidate_openapi: Dict[str, Any],
) -> Dict[str, Any]:
    """Alias for :func:`build_change_report` (explicit name for callers)."""
    return build_change_report(baseline_openapi, candidate_openapi)


# Sections of a ChangeReportModel that represent a *substantive* change. ``warnings``
# and ``skipped`` are diagnostic notes (e.g. an external $ref that could not be
# followed) and are intentionally excluded: a refresh whose only output is a warning
# carries no schema/property/reference/relationship/documentation delta and is still a
# no-op for change-report purposes (RAR-4.3).
_SUBSTANTIVE_LIST_SECTIONS = (
    "properties",
    "references",
    "relationships",
    "documentation",
)


def change_report_change_counts(change_model: Dict[str, Any]) -> Dict[str, int]:
    """Count substantive changes in a ChangeReportModel, by section.

    Args:
        change_model: A ChangeReportModel dict as produced by :func:`build_change_report`.

    Returns:
        A dict with one entry per substantive section: ``schemasAdded``,
        ``schemasRemoved``, ``schemasModified``, ``properties``, ``references``,
        ``relationships`` and ``documentation``. Diagnostic ``warnings`` / ``skipped``
        are not counted (see :data:`_SUBSTANTIVE_LIST_SECTIONS`).
    """
    schemas = change_model.get("schemas")
    schemas = schemas if isinstance(schemas, dict) else {}

    def _len(value: Any) -> int:
        return len(value) if isinstance(value, list) else 0

    counts = {
        "schemasAdded": _len(schemas.get("added")),
        "schemasRemoved": _len(schemas.get("removed")),
        "schemasModified": _len(schemas.get("modified")),
    }
    for section in _SUBSTANTIVE_LIST_SECTIONS:
        counts[section] = _len(change_model.get(section))
    return counts


def change_report_total_changes(change_model: Dict[str, Any]) -> int:
    """Return the total number of substantive changes in a ChangeReportModel."""
    return sum(change_report_change_counts(change_model).values())


def change_report_is_noop(change_model: Dict[str, Any]) -> bool:
    """Return ``True`` when a ChangeReportModel carries no substantive change.

    A no-op report is one where the candidate and baseline are semantically identical
    across every diffed section (schemas, properties, references, relationships,
    documentation). Diagnostic warnings/skipped notes do not make a report non-no-op.
    """
    return change_report_total_changes(change_model) == 0
