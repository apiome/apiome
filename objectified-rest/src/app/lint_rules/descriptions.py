"""
Description-presence rules.

Both rules are warnings, not errors: a schema with no descriptions is still
publishable, just not great for downstream consumers (SDK generators, doc
sites). Errors are reserved for things that prevent the schema from being
usable at all (see `structure.py`).
"""

from typing import Any, Dict, List

from ..lint_engine import LintFinding, LintRule, class_path, property_path, registry


def _has_text(value: Any) -> bool:
    """Same truth test the quality scorer uses — present, string, non-empty
    after stripping. Matches how the frontend renders these fields."""
    return isinstance(value, str) and value.strip() != ""


def _check_class_missing_description(ctx: Dict[str, Any]) -> List[LintFinding]:
    cls = ctx["class"]
    # `structure.class-name-empty` already flags classes with blank names as
    # an error; piling a description warning on top of that is just noise.
    if not _has_text(cls.get("name")):
        return []
    if _has_text(cls.get("description")):
        return []
    return [
        LintFinding(
            rule_id="class-missing-description",
            severity="warning",
            target_kind="class",
            target_id=str(cls.get("id")) if cls.get("id") is not None else None,
            target_path=class_path(cls),
            message="Class has no description.",
            suggestion="Add a one-sentence description so SDK and doc generators have something to render.",
        )
    ]


def _check_property_missing_description(ctx: Dict[str, Any]) -> List[LintFinding]:
    prop = ctx["property"]
    if not _has_text(prop.get("name")):
        return []
    if _has_text(prop.get("description")):
        return []
    return [
        LintFinding(
            rule_id="property-missing-description",
            severity="warning",
            target_kind="property",
            target_id=str(prop.get("id")) if prop.get("id") is not None else None,
            target_path=property_path(ctx["class"], prop),
            message="Property has no description.",
            suggestion="Describe what this property represents and any non-obvious constraints.",
        )
    ]


registry.register(
    LintRule(
        id="class-missing-description",
        severity="warning",
        title="Class is missing a description",
        description=(
            "Every class should carry a description. Description text is the "
            "primary signal SDK generators and doc sites use to explain a type "
            "to consumers."
        ),
        target_kind="class",
        check=_check_class_missing_description,
    )
)

registry.register(
    LintRule(
        id="property-missing-description",
        severity="warning",
        title="Property is missing a description",
        description=(
            "Every property should carry a description. Property descriptions "
            "are the only schema-level place to capture intent, units, "
            "constraints, and examples beyond the raw type."
        ),
        target_kind="property",
        check=_check_property_missing_description,
    )
)
