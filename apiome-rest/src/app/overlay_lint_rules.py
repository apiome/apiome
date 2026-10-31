"""The ``overlay`` lint rule pack — OpenAPI Overlay findings (GVM-4.1, #5876).

IXH-7.7 surfaced overlay problems as two intake-stage rules (``intake.overlay-unmatched-target``,
``intake.overlay-action-invalid``). GVM-4.1 promotes them to a registered pack of their own, so the
built-in style guide seeds them, a tenant guide can raise any of them to ``error``, and the rule
catalogue (``GET /v1/lint/rules``) and generated rule docs list them under ``overlay``.

The findings themselves are produced by :mod:`app.openapi_overlay` — while an overlay is applied
to its base during import, or by :func:`app.openapi_overlay.lint_bare_overlay` for an overlay on
its own — and adapted into lint findings by :func:`app.openapi_overlay.overlay_lint_findings`. No
canonical-model rule pack can emit them: the canonical model never sees the overlay.

Two of the rules need the base document to be decided (:data:`BASE_DEPENDENT_RULES`); a bare
overlay lint reports them ``skipped: no-base`` rather than passing them.
"""

from __future__ import annotations

from typing import Dict, Tuple

__all__ = [
    "BASE_DEPENDENT_RULES",
    "OVERLAY_PACK",
    "OVERLAY_RULES",
    "RULE_OVERLAY_ACTION_INVALID",
    "RULE_OVERLAY_EXTENDS_UNRESOLVED",
    "RULE_OVERLAY_TARGET_EXPRESSION_INVALID",
    "RULE_OVERLAY_UNMATCHED_TARGET",
    "RULE_OVERLAY_VERSION_UNSUPPORTED",
]

#: Pack label reported for these rules in the rule catalogue.
OVERLAY_PACK = "overlay"

#: An action's ``target`` matched nothing in the base document, so it changed nothing.
RULE_OVERLAY_UNMATCHED_TARGET = "overlay.unmatched-target"

#: An action that cannot be applied as written for its Overlay revision.
RULE_OVERLAY_ACTION_INVALID = "overlay.action-invalid"

#: An action's ``target`` (or ``copy``) is not a JSONPath expression Apiome can evaluate.
RULE_OVERLAY_TARGET_EXPRESSION_INVALID = "overlay.target-expression-invalid"

#: The overlay's ``extends`` names a document other than the base it was applied to.
RULE_OVERLAY_EXTENDS_UNRESOLVED = "overlay.extends-unresolved"

#: The overlay declares an Overlay Specification version Apiome does not read.
RULE_OVERLAY_VERSION_UNSUPPORTED = "overlay.version-unsupported"

#: Rules that can only be decided against the base document.
BASE_DEPENDENT_RULES: Tuple[str, ...] = (RULE_OVERLAY_UNMATCHED_TARGET, RULE_OVERLAY_EXTENDS_UNRESOLVED)

#: ``rule_id → (category, default_severity, rationale)`` — the shape of
#: :data:`app.intake_lint_rules.INTAKE_RULES`, consumed by :mod:`app.lint_rule_registry` and the
#: docs generator without a special case.
OVERLAY_RULES: Dict[str, Tuple[str, str, str]] = {
    RULE_OVERLAY_UNMATCHED_TARGET: (
        "structure",
        "warning",
        "An Overlay action whose `target` JSONPath matches nothing in the base document has no "
        "effect: the modification it describes is silently skipped everywhere the resolved document "
        "is used. Fix the target expression, or remove the action if the construct it targeted no "
        "longer exists in the base.",
    ),
    RULE_OVERLAY_ACTION_INVALID: (
        "structure",
        "warning",
        "An Overlay action that cannot be applied as written for its revision — no target, nothing "
        "to do (`update`, `copy` or `remove: true`), an `update` or `copy` value whose type does not "
        "fit the selected nodes, a `copy` source that is not exactly one node, a feature the declared "
        "revision does not have (`copy` before 1.1, reusable actions before 1.2), or a broken "
        "reusable-action `$ref` — leaves the resolved document without the change the overlay "
        "describes. Fix the action, or declare the Overlay revision that has the feature.",
    ),
    RULE_OVERLAY_TARGET_EXPRESSION_INVALID: (
        "structure",
        "warning",
        "An Overlay action's `target` (or `copy` source) must be an RFC 9535 JSONPath query. An "
        "expression that does not parse or cannot be evaluated selects nothing, so the action is "
        "never applied. Correct the expression; avoid tool-specific JSONPath extensions.",
    ),
    RULE_OVERLAY_EXTENDS_UNRESOLVED: (
        "structure",
        "warning",
        "An Overlay's `extends` says which document it was written for. When it names neither the "
        "base it is applied to (by path relative to the overlay) nor that base's `$self`, the overlay "
        "may be meant for a different document — its targets can still match by accident and change "
        "the wrong API. Point `extends` at the base, or apply the overlay to the document it names.",
    ),
    RULE_OVERLAY_VERSION_UNSUPPORTED: (
        "structure",
        "error",
        "Apiome applies Overlay 1.0, 1.1 and 1.2 documents. An overlay declaring any other version "
        "(`overlay: 1.3.0`, `2.0.0`) is refused rather than applied with semantics it was not written "
        "for. Declare a supported revision, or wait for Apiome to support the newer one.",
    ),
}
