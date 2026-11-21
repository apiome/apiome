"""Renamed lint-rule ids and their aliases — GVM-4.4 (#5879).

A shipped rule id is a stable identifier: findings carry it, style-guide rows store it,
waivers are keyed by a fingerprint derived from it. When an id has to change — the Arazzo pack
shipped ``arzzo.unresolvable-operation-ref`` with a typo — the old spelling stays live as an
**alias** of the new one:

* the engine emits only the canonical id;
* the GOV-1.2 registry publishes each canonical rule's aliases (``GET /v1/lint/rules``);
* a style-guide row stored under an alias governs the canonical rule
  (:func:`app.style_guide_engine.compile_style_guide`), and the guide editor accepts it;
* a finding's stable ``id`` (the fingerprint decisions and waivers match on) is hashed with the
  rule's **legacy** id, so a waiver recorded before the rename keeps matching the finding after
  it (:class:`app.schema_lint.LintFinding`).

This module has no imports so the low-level finding type can use it without a cycle.
"""

from __future__ import annotations

from typing import Dict, Mapping, Tuple

__all__ = [
    "RULE_ID_ALIASES",
    "aliases_for",
    "canonical_rule_id",
    "fingerprint_rule_id",
]

#: ``{alias: canonical id}``. Entries are never removed — stored data may carry the alias forever.
RULE_ID_ALIASES: Mapping[str, str] = {
    "arzzo.unresolvable-operation-ref": "arazzo.unresolvable-operation-ref",
}

#: ``{canonical id: the alias its finding fingerprints are hashed with}`` — the spelling the rule
#: shipped under first, so fingerprints recorded before the rename still match.
_FINGERPRINT_IDS: Dict[str, str] = {canonical: alias for alias, canonical in RULE_ID_ALIASES.items()}


def canonical_rule_id(rule_id: str) -> str:
    """Return the canonical id for ``rule_id`` (itself when it is not an alias).

    Args:
        rule_id: A rule id as stored or received — canonical or an alias.

    Returns:
        The id the engine emits for that rule.
    """
    return RULE_ID_ALIASES.get(rule_id, rule_id)


def aliases_for(rule_id: str) -> Tuple[str, ...]:
    """Return the aliases of a canonical rule id, sorted (empty when it has none)."""
    return tuple(sorted(alias for alias, canonical in RULE_ID_ALIASES.items() if canonical == rule_id))


def fingerprint_rule_id(rule_id: str) -> str:
    """Return the id a finding of ``rule_id`` hashes into its stable ``id``.

    For a renamed rule this is the original (alias) spelling, which keeps finding ids — and with
    them lint decisions and waivers — unchanged across the rename. Every other rule hashes its
    own id.

    Args:
        rule_id: The rule id carried by the finding (canonical or alias).

    Returns:
        The spelling to hash.
    """
    return _FINGERPRINT_IDS.get(canonical_rule_id(rule_id), rule_id)
