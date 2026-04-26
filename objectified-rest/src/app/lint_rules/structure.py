"""
Structural rules — the only rules in v1 that emit `error` severity.

Errors here mark a schema as fundamentally broken (no classes, blank names),
which is what drops the version's letter grade to D/F. Warnings are reserved
for `class-no-properties`, which is unusual but technically valid.
"""

from typing import Any, Dict, List

from ..lint_engine import LintFinding, LintRule, class_path, property_path, registry


def _is_blank(value: Any) -> bool:
    return not isinstance(value, str) or value.strip() == ""


def _check_schema_empty(ctx: Dict[str, Any]) -> List[LintFinding]:
    classes = ctx.get("classes") or []
    if classes:
        return []
    return [
        LintFinding(
            rule_id="schema-empty",
            severity="error",
            target_kind="schema",
            target_path="<schema>",
            message="Version contains no classes.",
            suggestion="Add at least one class before publishing this version.",
        )
    ]


def _check_class_name_empty(ctx: Dict[str, Any]) -> List[LintFinding]:
    cls = ctx["class"]
    if not _is_blank(cls.get("name")):
        return []
    cid = str(cls.get("id")) if cls.get("id") is not None else None
    return [
        LintFinding(
            rule_id="class-name-empty",
            severity="error",
            target_kind="class",
            target_id=cid,
            target_path=cid or "<unnamed-class>",
            message="Class has a missing or blank name.",
            suggestion="Set a non-empty class name before publishing.",
        )
    ]


def _check_property_name_empty(ctx: Dict[str, Any]) -> List[LintFinding]:
    prop = ctx["property"]
    if not _is_blank(prop.get("name")):
        return []
    pid = str(prop.get("id")) if prop.get("id") is not None else None
    cls = ctx["class"]
    return [
        LintFinding(
            rule_id="property-name-empty",
            severity="error",
            target_kind="property",
            target_id=pid,
            target_path=f"{class_path(cls)}.{pid or '<unnamed-property>'}",
            message="Property has a missing or blank name.",
            suggestion="Set a non-empty property name before publishing.",
        )
    ]


def _check_class_no_properties(ctx: Dict[str, Any]) -> List[LintFinding]:
    """Only flag at the schema level — we need the full property list to know
    which classes are empty, and dispatching this as a per-class rule would
    fire once per class (correct) but cost an O(n_props * n_classes) scan
    (wrong). One pass through `properties` is cheaper and produces the same
    findings."""
    classes = ctx.get("classes") or []
    properties = ctx.get("properties") or []
    if not classes:
        return []
    classes_with_properties = {str(p.get("class_id")) for p in properties}
    findings: List[LintFinding] = []
    for cls in classes:
        cid = str(cls.get("id"))
        if cid in classes_with_properties:
            continue
        if _is_blank(cls.get("name")):
            # `class-name-empty` already covers this case; flagging "no
            # properties" on top of "no name" is just noise.
            continue
        findings.append(
            LintFinding(
                rule_id="class-no-properties",
                severity="warning",
                target_kind="class",
                target_id=cid if cls.get("id") is not None else None,
                target_path=class_path(cls),
                message="Class has no properties.",
                suggestion=(
                    "Add at least one property, or remove the class if it's a "
                    "leftover from an earlier draft."
                ),
            )
        )
    return findings


registry.register(
    LintRule(
        id="schema-empty",
        severity="error",
        title="Schema has no classes",
        description=(
            "A version with zero classes can't be consumed by an SDK or a doc "
            "generator. Either add classes or delete the version."
        ),
        target_kind="schema",
        check=_check_schema_empty,
    )
)

registry.register(
    LintRule(
        id="class-name-empty",
        severity="error",
        title="Class name is empty",
        description=(
            "Classes without names can't be referenced from properties or "
            "generated code. This is almost always a stale draft row."
        ),
        target_kind="class",
        check=_check_class_name_empty,
    )
)

registry.register(
    LintRule(
        id="property-name-empty",
        severity="error",
        title="Property name is empty",
        description=(
            "Properties without names produce broken schemas in every output "
            "format we generate (OpenAPI, JSON Schema, Arazzo)."
        ),
        target_kind="property",
        check=_check_property_name_empty,
    )
)

registry.register(
    LintRule(
        id="class-no-properties",
        severity="warning",
        title="Class has no properties",
        description=(
            "Empty classes are unusual — they're typically forgotten drafts or "
            "marker types. They generate as `{}` in JSON Schema, which is "
            "rarely what was intended."
        ),
        target_kind="schema",
        check=_check_class_no_properties,
    )
)
