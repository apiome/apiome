"""
Backward compatibility analysis between two OpenAPI 3.1 documents (base vs head).

Semantics: a consumer or client aligned with **base** remains valid when the system
exposes **head** only if changes are non-breaking. Structural removals, stricter
constraints, and incompatible type changes are classified as breaking.

Output is deterministic: findings are sorted by (path, rule, message).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

Category = Literal["breaking", "safe", "unknown"]
Overall = Literal["breaking", "safe", "unknown"]

BREAKING_DOC_ISSUE_URL = "https://github.com/KenSuenobu/apiome/issues/746"


@dataclass
class CompatibilityRules:
    """Toggle groups of checks (defaults match strict API evolution review)."""

    check_paths: bool = True
    check_schemas: bool = True
    treat_removed_schema_as_breaking: bool = True
    treat_removed_property_as_breaking: bool = True
    treat_removed_path_as_breaking: bool = True
    treat_removed_operation_as_breaking: bool = True
    detect_possible_renames: bool = True


@dataclass
class CompatibilityFinding:
    path: str
    category: Category
    rule: str
    message: str
    id: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not self.id:
            h = hashlib.sha256(
                f"{self.path}|{self.rule}|{self.message}".encode("utf-8")
            ).hexdigest()[:16]
            self.id = f"cmp-{h}"


def _stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _sorted_keys(d: Any) -> List[str]:
    if not isinstance(d, dict):
        return []
    return sorted(d.keys())


def _finding(
    path: str, category: Category, rule: str, message: str
) -> CompatibilityFinding:
    return CompatibilityFinding(path=path, category=category, rule=rule, message=message)


def _overall(findings: List[CompatibilityFinding]) -> Overall:
    cats = {f.category for f in findings}
    if "breaking" in cats:
        return "breaking"
    if "unknown" in cats:
        return "unknown"
    return "safe"


def _schema_top_level_prop_keys(schema: Any) -> Optional[Set[str]]:
    if not isinstance(schema, dict):
        return None
    props = schema.get("properties")
    if not isinstance(props, dict):
        return set()
    return set(props.keys())


def _pair_rename_candidates(
    removed: Dict[str, Any], added: Dict[str, Any]
) -> Tuple[Set[Tuple[str, str]], Set[str], Set[str]]:
    """
    Greedy pairing: same top-level property key-sets => possible rename (unknown).
    Returns (pairs, removed_left, added_left).
    """
    pairs: Set[Tuple[str, str]] = set()
    removed_names = sorted(removed.keys())
    added_names = sorted(added.keys())
    used_r: Set[str] = set()
    used_a: Set[str] = set()
    for rn in removed_names:
        if rn in used_r:
            continue
        rk = _schema_top_level_prop_keys(removed[rn])
        if rk is None:
            continue
        for an in added_names:
            if an in used_a:
                continue
            ak = _schema_top_level_prop_keys(added[an])
            if ak is None:
                continue
            if rk == ak and rk is not None:
                pairs.add((rn, an))
                used_r.add(rn)
                used_a.add(an)
                break
    rem_left = set(removed.keys()) - used_r
    add_left = set(added.keys()) - used_a
    return pairs, rem_left, add_left


def _enum_narrowing(base: Any, head: Any, path: str) -> Optional[CompatibilityFinding]:
    if not isinstance(base, list) or not isinstance(head, list):
        return None
    sb, sh = set(base), set(head)
    if not sb:
        return None
    lost = sb - sh
    if lost:
        return _finding(
            path,
            "breaking",
            "enum_narrowed",
            f"Enum values removed: {sorted(lost)!r}",
        )
    return None


def _compare_primitive_constraints(
    base: Dict[str, Any], head: Dict[str, Any], path: str
) -> List[CompatibilityFinding]:
    out: List[CompatibilityFinding] = []

    def num_break(
        key: str, more_strict: str, base_v: Any, head_v: Any, label: str
    ) -> None:
        if base_v is None or head_v is None:
            return
        try:
            bf, hf = float(base_v), float(head_v)
        except (TypeError, ValueError):
            out.append(
                _finding(
                    path,
                    "unknown",
                    f"constraint_{key}",
                    f"Could not compare {label}: {base_v!r} vs {head_v!r}",
                )
            )
            return
        if more_strict == "higher_min" and hf > bf:
            out.append(
                _finding(
                    path,
                    "breaking",
                    f"constraint_{key}",
                    f"{label} increased: {bf} -> {hf}",
                )
            )
        if more_strict == "lower_max" and hf < bf:
            out.append(
                _finding(
                    path,
                    "breaking",
                    f"constraint_{key}",
                    f"{label} decreased: {bf} -> {hf}",
                )
            )

    num_break("minimum", "higher_min", base.get("minimum"), head.get("minimum"), "minimum")
    num_break("maximum", "lower_max", base.get("maximum"), head.get("maximum"), "maximum")

    # string / array lengths
    for key, label, more_strict in (
        ("minLength", "minLength", "higher_min"),
        ("minItems", "minItems", "higher_min"),
    ):
        num_break(key, more_strict, base.get(key), head.get(key), label)
    for key, label, more_strict in (
        ("maxLength", "maxLength", "lower_max"),
        ("maxItems", "maxItems", "lower_max"),
    ):
        num_break(key, more_strict, base.get(key), head.get(key), label)

    bp = base.get("pattern")
    hp = head.get("pattern")
    if isinstance(bp, str) and isinstance(hp, str) and bp != hp:
        out.append(
            _finding(
                path,
                "unknown",
                "pattern_changed",
                "Pattern changed; manual review required for strictness",
            )
        )

    unk_keys = ("not", "if", "then", "else", "dependentSchemas", "dependentRequired")
    for uk in unk_keys:
        if uk in base or uk in head:
            if _stable_json(base.get(uk)) != _stable_json(head.get(uk)):
                out.append(
                    _finding(
                        path,
                        "unknown",
                        f"keyword_{uk}",
                        f"Schema keyword {uk!r} differs — needs manual review",
                    )
                )

    return out


def _compare_json_schema(
    base: Any,
    head: Any,
    path: str,
    rules: CompatibilityRules,
) -> List[CompatibilityFinding]:
    findings: List[CompatibilityFinding] = []

    if base == head:
        return findings

    if type(base) is not type(head):
        findings.append(
            _finding(
                path,
                "breaking",
                "type_structure_change",
                f"Value kind changed: {type(base).__name__} vs {type(head).__name__}",
            )
        )
        return findings

    if isinstance(base, dict) and isinstance(head, dict):
        bref = base.get("$ref")
        href = head.get("$ref")
        if isinstance(bref, str) or isinstance(href, str):
            if isinstance(bref, str) and isinstance(href, str):
                if bref != href:
                    findings.append(
                        _finding(
                            path,
                            "breaking",
                            "ref_change",
                            f"$ref changed: {bref!r} -> {href!r}",
                        )
                    )
                return findings
            findings.append(
                _finding(
                    path,
                    "breaking",
                    "ref_structure_change",
                    "$ref presence changed vs inline schema",
                )
            )
            return findings

        # composition
        for comp in ("allOf", "anyOf", "oneOf"):
            if comp in base or comp in head:
                if _stable_json(base.get(comp)) != _stable_json(head.get(comp)):
                    findings.append(
                        _finding(
                            path,
                            "unknown",
                            f"composition_{comp}",
                            f"{comp} changed — needs manual review",
                        )
                    )

        bt = base.get("type")
        ht = head.get("type")
        if bt != ht and (bt is not None or ht is not None):
            findings.append(
                _finding(
                    path,
                    "breaking",
                    "json_type_change",
                    f"type changed: {bt!r} -> {ht!r}",
                )
            )

        # enum
        if "enum" in base or "enum" in head:
            en = _enum_narrowing(
                base.get("enum") if isinstance(base.get("enum"), list) else [],
                head.get("enum") if isinstance(head.get("enum"), list) else [],
                path,
            )
            if en:
                findings.append(en)

        findings.extend(_compare_primitive_constraints(base, head, path))

        # required fields on object
        br = set(base.get("required") or [])
        hr = set(head.get("required") or [])
        new_required = hr - br
        if new_required:
            findings.append(
                _finding(
                    path,
                    "breaking",
                    "required_field_added",
                    f"New required properties: {sorted(new_required)!r}",
                )
            )

        bprops = base.get("properties")
        hprops = head.get("properties")
        if isinstance(bprops, dict) or isinstance(hprops, dict):
            bprops = bprops if isinstance(bprops, dict) else {}
            hprops = hprops if isinstance(hprops, dict) else {}
            keys = sorted(set(bprops.keys()) | set(hprops.keys()))
            for k in keys:
                p = f"{path}.properties.{k}"
                if k in bprops and k not in hprops:
                    if rules.treat_removed_property_as_breaking:
                        findings.append(
                            _finding(
                                p,
                                "breaking",
                                "property_removed",
                                "Property removed from schema",
                            )
                        )
                elif k not in bprops and k in hprops:
                    findings.append(
                        _finding(
                            p,
                            "safe",
                            "property_added",
                            "Optional new property (verify required arrays at parent)",
                        )
                    )
                else:
                    findings.extend(
                        _compare_json_schema(bprops[k], hprops[k], p, rules)
                    )

        # items for array
        bi, hi = base.get("items"), head.get("items")
        if bi is not None or hi is not None:
            findings.extend(
                _compare_json_schema(bi, hi, f"{path}.items", rules)
            )

        return findings

    if isinstance(base, list) and isinstance(head, list):
        if len(base) != len(head):
            findings.append(
                _finding(
                    path,
                    "unknown",
                    "tuple_length",
                    f"Array schema length changed: {len(base)} -> {len(head)}",
                )
            )
        else:
            for i, (bx, hx) in enumerate(zip(base, head)):
                findings.extend(_compare_json_schema(bx, hx, f"{path}[{i}]", rules))
        return findings

    findings.append(
        _finding(
            path,
            "unknown",
            "value_mismatch",
            f"Compared values differ: {base!r} vs {head!r}",
        )
    )
    return findings


def _compare_operations(
    base_path_item: Dict[str, Any],
    head_path_item: Dict[str, Any],
    path_prefix: str,
    rules: CompatibilityRules,
) -> List[CompatibilityFinding]:
    findings: List[CompatibilityFinding] = []
    http_methods = ("get", "post", "put", "patch", "delete", "head", "options", "trace")
    for m in http_methods:
        if m in base_path_item and m not in head_path_item:
            if rules.treat_removed_operation_as_breaking:
                findings.append(
                    _finding(
                        f"{path_prefix}.{m}",
                        "breaking",
                        "operation_removed",
                        f"HTTP {m.upper()} removed from path",
                    )
                )
        elif m in head_path_item and m not in base_path_item:
            findings.append(
                _finding(
                    f"{path_prefix}.{m}",
                    "safe",
                    "operation_added",
                    f"HTTP {m.upper()} added",
                )
            )
    return findings


def _compare_paths(
    base_spec: Dict[str, Any], head_spec: Dict[str, Any], rules: CompatibilityRules
) -> List[CompatibilityFinding]:
    findings: List[CompatibilityFinding] = []
    bp = base_spec.get("paths") or {}
    hp = head_spec.get("paths") or {}
    if not isinstance(bp, dict) or not isinstance(hp, dict):
        return findings
    for p in sorted(bp.keys()):
        if p not in hp:
            if rules.treat_removed_path_as_breaking:
                findings.append(
                    _finding(
                        f"paths.{p}",
                        "breaking",
                        "path_removed",
                        "Path removed from API surface",
                    )
                )
        else:
            findings.extend(
                _compare_operations(
                    bp[p] if isinstance(bp[p], dict) else {},
                    hp[p] if isinstance(hp[p], dict) else {},
                    f"paths.{p}",
                    rules,
                )
            )
    for p in sorted(hp.keys()):
        if p not in bp:
            findings.append(
                _finding(
                    f"paths.{p}",
                    "safe",
                    "path_added",
                    "New path added",
                )
            )
    return findings


def analyze_schema_compatibility(
    base_spec: Dict[str, Any],
    head_spec: Dict[str, Any],
    rules: Optional[CompatibilityRules] = None,
) -> Tuple[Overall, List[CompatibilityFinding]]:
    """
    Compare base (older) OpenAPI document to head (newer).
    Returns overall classification and a list of findings (unsorted).
    """
    r = rules or CompatibilityRules()
    findings: List[CompatibilityFinding] = []

    if r.check_paths:
        findings.extend(_compare_paths(base_spec, head_spec, r))

    if not r.check_schemas:
        out = sorted(findings, key=lambda f: (f.path, f.rule, f.message))
        return _overall(out), out

    comps_b = (base_spec.get("components") or {})
    comps_h = (head_spec.get("components") or {})
    if not isinstance(comps_b, dict):
        comps_b = {}
    if not isinstance(comps_h, dict):
        comps_h = {}

    schemas_b = comps_b.get("schemas") or {}
    schemas_h = comps_h.get("schemas") or {}
    if not isinstance(schemas_b, dict):
        schemas_b = {}
    if not isinstance(schemas_h, dict):
        schemas_h = {}

    removed: Dict[str, Any] = {
        k: schemas_b[k] for k in schemas_b if k not in schemas_h
    }
    added: Dict[str, Any] = {k: schemas_h[k] for k in schemas_h if k not in schemas_b}

    if r.detect_possible_renames:
        pairs, rem_left, add_left = _pair_rename_candidates(removed, added)
        for rn, an in sorted(pairs):
            findings.append(
                _finding(
                    f"components.schemas.{rn}->components.schemas.{an}",
                    "unknown",
                    "possible_rename",
                    "Removed and added schemas share the same property keys — possible rename (verify)",
                )
            )
        # Only compare leftovers
        names = sorted(set(schemas_b.keys()) & set(schemas_h.keys()))
        for name in names:
            findings.extend(
                _compare_json_schema(
                    schemas_b[name],
                    schemas_h[name],
                    f"components.schemas.{name}",
                    r,
                )
            )
        for name in sorted(rem_left):
            if r.treat_removed_schema_as_breaking:
                findings.append(
                    _finding(
                        f"components.schemas.{name}",
                        "breaking",
                        "schema_removed",
                        "Schema component removed",
                    )
                )
        for name in sorted(add_left):
            findings.append(
                _finding(
                    f"components.schemas.{name}",
                    "safe",
                    "schema_added",
                    "New schema component added",
                )
            )
    else:
        names = sorted(set(schemas_b.keys()) | set(schemas_h.keys()))
        for name in names:
            if name in schemas_b and name not in schemas_h:
                if r.treat_removed_schema_as_breaking:
                    findings.append(
                        _finding(
                            f"components.schemas.{name}",
                            "breaking",
                            "schema_removed",
                            "Schema component removed",
                        )
                    )
            elif name not in schemas_b and name in schemas_h:
                findings.append(
                    _finding(
                        f"components.schemas.{name}",
                        "safe",
                        "schema_added",
                        "New schema component added",
                    )
                )
            else:
                findings.extend(
                    _compare_json_schema(
                        schemas_b[name],
                        schemas_h[name],
                        f"components.schemas.{name}",
                        r,
                    )
                )

    out = sorted(findings, key=lambda f: (f.path, f.rule, f.message))
    return _overall(out), out

