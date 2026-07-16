"""CTG-1.1 change-taxonomy rule registry (#4467).

An extensible table of classification rules. Each rule has a stable ``rule_id``, a
default :class:`~app.change_taxonomy.Severity`, and the ``change_kind`` it matches on
raw enumerator output. The classifier core only looks up this registry; GOV style
guides can later call :func:`override_severity` without editing matchers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Literal, Optional

Severity = Literal["breaking", "non-breaking", "docs-only"]

UNCLASSIFIED_RULE_ID = "ctg.unclassified"


@dataclass(frozen=True)
class TaxonomyRule:
    """One classification rule in the CTG taxonomy.

    Attributes:
        rule_id: Stable identifier (e.g. ``ctg.path_removed``).
        change_kind: Raw enumerator kind this rule matches exactly.
        severity: Default severity when the rule fires.
        summary: One-line human description of the rule.
    """

    rule_id: str
    change_kind: str
    severity: Severity
    summary: str


#: rule_id -> descriptor for every registered taxonomy rule.
RULE_REGISTRY: Dict[str, TaxonomyRule] = {}

#: change_kind -> rule_id for O(1) matcher lookup.
_KIND_INDEX: Dict[str, str] = {}

#: Optional severity overrides keyed by rule_id (GOV hook).
_SEVERITY_OVERRIDES: Dict[str, Severity] = {}


def register_rule(rule: TaxonomyRule) -> None:
    """Register a single taxonomy rule.

    Re-registering an identical descriptor is a no-op. Redefining an existing
    ``rule_id`` with different metadata raises.

    Args:
        rule: The descriptor to register.

    Raises:
        ValueError: If ``rule_id`` is already registered with different metadata,
            or if another rule already claims the same ``change_kind``.
    """
    existing = RULE_REGISTRY.get(rule.rule_id)
    if existing is not None:
        if existing != rule:
            raise ValueError(
                f"taxonomy rule '{rule.rule_id}' is already registered with different "
                f"metadata; rule ids are stable and may not be redefined"
            )
        return

    kind_owner = _KIND_INDEX.get(rule.change_kind)
    if kind_owner is not None and kind_owner != rule.rule_id:
        raise ValueError(
            f"change_kind '{rule.change_kind}' is already claimed by rule '{kind_owner}'"
        )

    RULE_REGISTRY[rule.rule_id] = rule
    _KIND_INDEX[rule.change_kind] = rule.rule_id


def register_rules(rules: Iterable[TaxonomyRule]) -> None:
    """Register multiple taxonomy rules.

    Args:
        rules: Descriptors to register.
    """
    for rule in rules:
        register_rule(rule)


def get_rule(rule_id: str) -> Optional[TaxonomyRule]:
    """Return a registered rule by id, or ``None``."""
    return RULE_REGISTRY.get(rule_id)


def rule_for_kind(change_kind: str) -> Optional[TaxonomyRule]:
    """Return the rule that matches ``change_kind``, or ``None``."""
    rule_id = _KIND_INDEX.get(change_kind)
    if rule_id is None:
        return None
    return RULE_REGISTRY.get(rule_id)


def override_severity(rule_id: str, severity: Severity) -> None:
    """Override the effective severity for a registered rule (GOV hook).

    Args:
        rule_id: An already-registered rule id.
        severity: Severity to apply instead of the rule's default.

    Raises:
        ValueError: If ``rule_id`` is not registered.
    """
    if rule_id not in RULE_REGISTRY:
        raise ValueError(f"cannot override unknown taxonomy rule '{rule_id}'")
    _SEVERITY_OVERRIDES[rule_id] = severity


def clear_severity_overrides() -> None:
    """Clear all severity overrides (test helper)."""
    _SEVERITY_OVERRIDES.clear()


def unregister_rule(rule_id: str) -> None:
    """Remove a rule from the registry (test helper for temporary custom rules).

    Args:
        rule_id: The rule id to remove. No-op when absent.
    """
    rule = RULE_REGISTRY.pop(rule_id, None)
    if rule is not None:
        _KIND_INDEX.pop(rule.change_kind, None)
    _SEVERITY_OVERRIDES.pop(rule_id, None)


def effective_severity(rule: TaxonomyRule, overrides: Optional[Dict[str, Severity]] = None) -> Severity:
    """Resolve severity for a rule, applying call-site and registry overrides.

    Call-site ``overrides`` win over registry overrides, which win over the rule default.

    Args:
        rule: The matched rule.
        overrides: Optional per-call severity map (rule_id -> severity).

    Returns:
        The effective severity.
    """
    if overrides and rule.rule_id in overrides:
        return overrides[rule.rule_id]
    if rule.rule_id in _SEVERITY_OVERRIDES:
        return _SEVERITY_OVERRIDES[rule.rule_id]
    return rule.severity


def list_rules() -> List[TaxonomyRule]:
    """Return all registered rules in stable ``rule_id`` order."""
    return [RULE_REGISTRY[k] for k in sorted(RULE_REGISTRY.keys())]


def _default_rules() -> List[TaxonomyRule]:
    """Built-in CTG-1.1 taxonomy rules."""
    breaking: List[tuple[str, str, str]] = [
        ("ctg.path_removed", "path_removed", "Path removed from the API surface."),
        ("ctg.operation_removed", "operation_removed", "HTTP operation removed from a path."),
        ("ctg.response_removed", "response_removed", "Response status removed from an operation."),
        ("ctg.property_removed", "property_removed", "Schema property removed."),
        ("ctg.type_narrowed", "type_narrowed", "JSON Schema type changed incompatibly."),
        ("ctg.optional_to_required", "optional_to_required", "Optional schema property became required."),
        ("ctg.required_param_added", "required_param_added", "New required parameter added."),
        ("ctg.enum_value_removed", "enum_value_removed", "Enum value removed."),
        ("ctg.security_tightened", "security_tightened", "Security requirement added or tightened."),
        ("ctg.server_removed", "server_removed", "Server entry removed."),
    ]
    non_breaking: List[tuple[str, str, str]] = [
        ("ctg.path_added", "path_added", "New path added."),
        ("ctg.operation_added", "operation_added", "New HTTP operation added."),
        ("ctg.response_added", "response_added", "New response status added."),
        ("ctg.property_added", "property_added", "Optional schema property added."),
        ("ctg.optional_param_added", "optional_param_added", "Optional parameter added."),
        ("ctg.server_added", "server_added", "Server entry added."),
        ("ctg.enum_value_added", "enum_value_added", "Enum value added (widened)."),
        ("ctg.security_relaxed", "security_relaxed", "Security requirement removed or relaxed."),
    ]
    docs_only: List[tuple[str, str, str]] = [
        ("ctg.docs_description", "docs_description", "Description text changed."),
        ("ctg.docs_summary", "docs_summary", "Summary text changed."),
        ("ctg.docs_example", "docs_example", "Example / examples changed."),
        ("ctg.docs_external_docs", "docs_external_docs", "externalDocs changed."),
        ("ctg.docs_tag", "docs_tag", "Tag metadata changed."),
    ]

    rules: List[TaxonomyRule] = []
    for rule_id, kind, summary in breaking:
        rules.append(TaxonomyRule(rule_id=rule_id, change_kind=kind, severity="breaking", summary=summary))
    for rule_id, kind, summary in non_breaking:
        rules.append(
            TaxonomyRule(rule_id=rule_id, change_kind=kind, severity="non-breaking", summary=summary)
        )
    for rule_id, kind, summary in docs_only:
        rules.append(TaxonomyRule(rule_id=rule_id, change_kind=kind, severity="docs-only", summary=summary))
    return rules


# Self-register defaults on import.
register_rules(_default_rules())
