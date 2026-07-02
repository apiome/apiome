"""
Three-way merge for OpenAPI ``components.schemas`` (Git-style merge-base + JSON merge).

Ports the Studio ``schema-diff`` / ``version-merge`` semantics to the REST service
so merge preview and merge apply share one engine (#738).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union

_MISSING = object()


def _stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def json_equal(a: Any, b: Any) -> bool:
    """Deep equality suitable for OpenAPI fragments (handles dict/list/scalar)."""
    if a is _MISSING and b is _MISSING:
        return True
    if a is _MISSING or b is _MISSING:
        return False
    return _stable_json(a) == _stable_json(b)


@dataclass
class SchemaDiffEntry:
    type: str  # added | removed | modified | unchanged
    path: str
    item_type: str  # schema | property
    old_value: Any = None
    new_value: Any = None
    changes: Optional[List[str]] = None


@dataclass
class DiffSummary:
    added: List[SchemaDiffEntry] = field(default_factory=list)
    removed: List[SchemaDiffEntry] = field(default_factory=list)
    modified: List[SchemaDiffEntry] = field(default_factory=list)
    unchanged: List[SchemaDiffEntry] = field(default_factory=list)


def _compare_schema_objects(obj1: Any, obj2: Any) -> List[str]:
    changes: List[str] = []
    if not isinstance(obj1, dict) or not isinstance(obj2, dict):
        return ["structure"] if not json_equal(obj1, obj2) else []
    if obj1.get("description") != obj2.get("description"):
        changes.append("description")
    if obj1.get("type") != obj2.get("type"):
        changes.append("type")
    if _stable_json(obj1.get("required") or []) != _stable_json(obj2.get("required") or []):
        changes.append("required")
    for key in ("allOf", "anyOf", "oneOf"):
        if _stable_json(obj1.get(key)) != _stable_json(obj2.get(key)):
            changes.append(key)
    return changes


def _compare_property_objects(prop1: Any, prop2: Any) -> List[str]:
    changes: List[str] = []
    if not isinstance(prop1, dict) or not isinstance(prop2, dict):
        return ["structure"] if not json_equal(prop1, prop2) else []
    if _stable_json(prop1.get("type")) != _stable_json(prop2.get("type")):
        changes.append("type")
    if prop1.get("description") != prop2.get("description"):
        changes.append("description")
    if prop1.get("format") != prop2.get("format"):
        changes.append("format")
    if prop1.get("$ref") != prop2.get("$ref"):
        changes.append("$ref")
    if _stable_json(prop1.get("enum")) != _stable_json(prop2.get("enum")):
        changes.append("enum")
    if _stable_json(prop1.get("items")) != _stable_json(prop2.get("items")):
        changes.append("items")
    for key in (
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
    ):
        if prop1.get(key) != prop2.get(key):
            changes.append(key)
    return changes


def compare_schemas(spec1: Union[str, Dict[str, Any]], spec2: Union[str, Dict[str, Any]]) -> DiffSummary:
    """Compare two OpenAPI specs (or JSON strings) at ``components.schemas`` granularity."""
    schema1 = json.loads(spec1) if isinstance(spec1, str) else spec1
    schema2 = json.loads(spec2) if isinstance(spec2, str) else spec2
    schemas1 = (schema1 or {}).get("components", {}).get("schemas") or {}
    schemas2 = (schema2 or {}).get("components", {}).get("schemas") or {}

    diffs: List[SchemaDiffEntry] = []
    all_names: Set[str] = set(schemas1.keys()) | set(schemas2.keys())

    for schema_name in sorted(all_names):
        schema1_exists = schema_name in schemas1
        schema2_exists = schema_name in schemas2

        if not schema1_exists and schema2_exists:
            diffs.append(
                SchemaDiffEntry(
                    type="added",
                    path=f"schemas.{schema_name}",
                    item_type="schema",
                    new_value=schemas2[schema_name],
                )
            )
            props2 = (schemas2[schema_name] or {}).get("properties") or {}
            for prop_name in props2:
                diffs.append(
                    SchemaDiffEntry(
                        type="added",
                        path=f"schemas.{schema_name}.properties.{prop_name}",
                        item_type="property",
                        new_value=props2[prop_name],
                    )
                )
        elif schema1_exists and not schema2_exists:
            diffs.append(
                SchemaDiffEntry(
                    type="removed",
                    path=f"schemas.{schema_name}",
                    item_type="schema",
                    old_value=schemas1[schema_name],
                )
            )
            props1 = (schemas1[schema_name] or {}).get("properties") or {}
            for prop_name in props1:
                diffs.append(
                    SchemaDiffEntry(
                        type="removed",
                        path=f"schemas.{schema_name}.properties.{prop_name}",
                        item_type="property",
                        old_value=props1[prop_name],
                    )
                )
        else:
            s1 = schemas1[schema_name]
            s2 = schemas2[schema_name]
            sch_changes = _compare_schema_objects(s1, s2)
            if sch_changes:
                diffs.append(
                    SchemaDiffEntry(
                        type="modified",
                        path=f"schemas.{schema_name}",
                        item_type="schema",
                        old_value=s1,
                        new_value=s2,
                        changes=sch_changes,
                    )
                )
            else:
                diffs.append(
                    SchemaDiffEntry(
                        type="unchanged",
                        path=f"schemas.{schema_name}",
                        item_type="schema",
                        old_value=s1,
                        new_value=s2,
                    )
                )

            props1 = (s1 or {}).get("properties") or {}
            props2 = (s2 or {}).get("properties") or {}
            all_props = set(props1.keys()) | set(props2.keys())
            for prop_name in sorted(all_props):
                p1_exists = prop_name in props1
                p2_exists = prop_name in props2
                if not p1_exists and p2_exists:
                    diffs.append(
                        SchemaDiffEntry(
                            type="added",
                            path=f"schemas.{schema_name}.properties.{prop_name}",
                            item_type="property",
                            new_value=props2[prop_name],
                        )
                    )
                elif p1_exists and not p2_exists:
                    diffs.append(
                        SchemaDiffEntry(
                            type="removed",
                            path=f"schemas.{schema_name}.properties.{prop_name}",
                            item_type="property",
                            old_value=props1[prop_name],
                        )
                    )
                else:
                    pc = _compare_property_objects(props1[prop_name], props2[prop_name])
                    if pc:
                        diffs.append(
                            SchemaDiffEntry(
                                type="modified",
                                path=f"schemas.{schema_name}.properties.{prop_name}",
                                item_type="property",
                                old_value=props1[prop_name],
                                new_value=props2[prop_name],
                                changes=pc,
                            )
                        )
                    else:
                        diffs.append(
                            SchemaDiffEntry(
                                type="unchanged",
                                path=f"schemas.{schema_name}.properties.{prop_name}",
                                item_type="property",
                                old_value=props1[prop_name],
                                new_value=props2[prop_name],
                            )
                        )

    return DiffSummary(
        added=[d for d in diffs if d.type == "added"],
        removed=[d for d in diffs if d.type == "removed"],
        modified=[d for d in diffs if d.type == "modified"],
        unchanged=[d for d in diffs if d.type == "unchanged"],
    )


def classify_merge_diff_two_way(summary: DiffSummary) -> Tuple[bool, List[str], List[str]]:
    """Legacy two-way classification (target vs source): conflicts = modified + removed paths."""
    conflict_paths = [d.path for d in summary.modified] + [d.path for d in summary.removed]
    added_schema_names = [
        d.path.replace("schemas.", "", 1)
        for d in summary.added
        if d.item_type == "schema" and d.path.startswith("schemas.") and ".properties." not in d.path
    ]
    return (len(conflict_paths) == 0, conflict_paths, added_schema_names)


def merge_json_three_way(b: Any, o: Any, t: Any, path: str) -> Tuple[Any, List[str]]:
    """
    Git-style recursive three-way merge. Uses _MISSING for absent keys in parent dicts
    (caller wraps with get(..., _MISSING)).
    Returns (merged_value, conflict_paths).
    """
    if json_equal(o, t):
        return o, []
    if json_equal(o, b):
        return t, []
    if json_equal(t, b):
        return o, []

    if isinstance(b, dict) and isinstance(o, dict) and isinstance(t, dict):
        out: Dict[str, Any] = {}
        keys = set(b.keys()) | set(o.keys()) | set(t.keys())
        for k in sorted(keys):
            bk = b.get(k, _MISSING)
            ok = o.get(k, _MISSING)
            tk = t.get(k, _MISSING)
            subpath = f"{path}.{k}" if path else str(k)
            mv, conflicts = merge_json_three_way(bk, ok, tk, subpath)
            if conflicts:
                return None, conflicts
            if mv is _MISSING:
                continue
            out[k] = mv
        return out, []

    return None, [path or "<root>"]


def merge_components_schemas_three_way(
    base: Optional[Dict[str, Any]],
    ours: Optional[Dict[str, Any]],
    theirs: Optional[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """Three-way merge of ``components.schemas`` dicts (schema name -> schema)."""
    b = base or {}
    o = ours or {}
    t = theirs or {}
    keys = set(b.keys()) | set(o.keys()) | set(t.keys())
    merged: Dict[str, Any] = {}
    all_conflicts: List[str] = []
    for name in sorted(keys):
        bk = b.get(name, _MISSING)
        ok = o.get(name, _MISSING)
        tk = t.get(name, _MISSING)
        mv, conflicts = merge_json_three_way(bk, ok, tk, f"schemas.{name}")
        if conflicts:
            all_conflicts.extend(conflicts)
            continue
        if mv is _MISSING:
            continue
        merged[name] = mv
    if all_conflicts:
        return None, sorted(set(all_conflicts))
    return merged, []


def compute_merge_bases_from_common(
    common: Set[str], is_ancestor: Any
) -> List[str]:
    """
    :param common: set of revision ids common to both branches
    :param is_ancestor: callable (anc, desc) -> bool
    """
    bases = [
        c
        for c in common
        if not any(c != d and is_ancestor(c, d) for d in common)
    ]
    return sorted(bases)


def schema_merge_materializable_paths(
    merged: Dict[str, Any],
    ours: Dict[str, Any],
    theirs: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """
    Merge result is persisted by taking full copies from either branch tip per schema.
    If the three-way merged schema differs from *both* branch tips, apply cannot run safely.
    """
    bad: List[str] = []
    all_names = set(merged.keys()) | set(ours.keys()) | set(theirs.keys())
    for name in sorted(all_names):
        m_val = merged.get(name, _MISSING)
        o_val = ours.get(name, _MISSING)
        t_val = theirs.get(name, _MISSING)
        if m_val is _MISSING and o_val is _MISSING and t_val is _MISSING:
            continue
        if json_equal(m_val, o_val) or json_equal(m_val, t_val):
            continue
        bad.append(f"schemas.{name}")
    return (len(bad) == 0, bad)


def format_diff_summary_text(summary: DiffSummary) -> str:
    lines = [
        "Changes Summary:",
        f"  Added: {len(summary.added)} items",
        f"  Removed: {len(summary.removed)} items",
        f"  Modified: {len(summary.modified)} items",
        "",
    ]
    return "\n".join(lines)
