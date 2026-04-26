"""
Name-style rules.

These are deliberately permissive: we don't pick a project-wide convention
(camelCase vs snake_case for properties, e.g.) — we only flag names that don't
match *either* common style, since those are usually typos or paste-errors.
A future rule could compare every name in a version against the dominant style
in that version and flag the outliers; v1 keeps things local.
"""

import re
from typing import Any, Dict, List

from ..lint_engine import LintFinding, LintRule, class_path, property_path, registry


# PascalCase: starts with an uppercase letter; alphanumerics only; no spaces,
# punctuation, or underscores. Allows internal uppercase (e.g. `OrderItem`)
# and digits after the first character (e.g. `User2`).
_PASCAL_CASE = re.compile(r"^[A-Z][A-Za-z0-9]*$")

# camelCase: lowercase initial letter, no underscores, alphanumerics only.
_CAMEL_CASE = re.compile(r"^[a-z][A-Za-z0-9]*$")

# snake_case: all lowercase, alphanumerics and underscores; no leading,
# trailing, or doubled underscores.
_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


def _is_blank(value: Any) -> bool:
    return not isinstance(value, str) or value.strip() == ""


def _check_class_name_pascal_case(ctx: Dict[str, Any]) -> List[LintFinding]:
    cls = ctx["class"]
    name = cls.get("name")
    if _is_blank(name):
        # `structure.class-name-empty` handles the empty case as an error;
        # avoid emitting a duplicate finding here.
        return []
    name = str(name)
    if _PASCAL_CASE.fullmatch(name):
        return []
    return [
        LintFinding(
            rule_id="class-name-pascal-case",
            severity="warning",
            target_kind="class",
            target_id=str(cls.get("id")) if cls.get("id") is not None else None,
            target_path=class_path(cls),
            message=f"Class name `{name}` is not PascalCase.",
            suggestion="Class names are PascalCase by convention (e.g. `User`, `OrderItem`).",
        )
    ]


def _check_property_name_style(ctx: Dict[str, Any]) -> List[LintFinding]:
    prop = ctx["property"]
    name = prop.get("name")
    if _is_blank(name):
        return []
    name = str(name)
    if _CAMEL_CASE.fullmatch(name) or _SNAKE_CASE.fullmatch(name):
        return []
    return [
        LintFinding(
            rule_id="property-name-style",
            severity="warning",
            target_kind="property",
            target_id=str(prop.get("id")) if prop.get("id") is not None else None,
            target_path=property_path(ctx["class"], prop),
            message=f"Property name `{name}` is neither camelCase nor snake_case.",
            suggestion=(
                "Rename to camelCase (`firstName`) or snake_case (`first_name`) "
                "to match common API conventions."
            ),
        )
    ]


registry.register(
    LintRule(
        id="class-name-pascal-case",
        severity="warning",
        title="Class name is not PascalCase",
        description=(
            "Class names should follow PascalCase (`User`, `OrderItem`). "
            "Schema generators in most ecosystems assume PascalCase for type "
            "identifiers; deviating produces awkward generated SDK code."
        ),
        target_kind="class",
        check=_check_class_name_pascal_case,
    )
)

registry.register(
    LintRule(
        id="property-name-style",
        severity="warning",
        title="Property name is not camelCase or snake_case",
        description=(
            "Property names should be camelCase (`firstName`) or snake_case "
            "(`first_name`). Mixed styles (e.g. `First_Name`) and punctuation "
            "produce inconsistent SDK code and confuse consumers."
        ),
        target_kind="property",
        check=_check_property_name_style,
    )
)
