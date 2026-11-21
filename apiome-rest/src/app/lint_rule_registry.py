"""Built-in lint-rule catalog registry — GOV-1.2 (#4428).

Before this module, the built-in lint rules were engine internals: the OpenAPI spec linter
(:mod:`app.schema_lint`) kept a private ``(category, severity)`` catalogue and the canonical
rule packs (:mod:`app.lint_engine` and the per-format packs) each carried their own
:class:`~app.lint_engine.LintRule` lists. Nothing enumerated them all in one place, so no
style guide could enable/disable a rule by id, no UI could list them, and no violation could
link to a rationale.

This registry gives every built-in rule one durable descriptor — a **stable id**, its
**category**, its **default severity**, a **one-line rationale**, and a **docs anchor** into
the rule reference page (``apiome-docs/docs/build/lint-rules.md``) — and is exposed over REST via
``GET /v1/lint/rules`` (see :mod:`app.lint_routes`).

Stable-id policy
----------------

The registry's stable id **is** the rule id the engines already emit in every finding's
``rule`` field (``documentation.operation-missing-summary``, ``common.type-missing-description``,
``asyncapi.message-missing-name``, …). Those ids are hashed into finding ids and the
``report_fingerprint``, and GOV-1.1 seeds the built-in "Apiome Recommended" guide so that
existing scores do not change on upgrade — so shipped ids are never renamed, and violations
are attributable to a registered rule with no mapping layer.

Sources aggregated (all derived from the live engines, so the registry cannot drift):

* the OpenAPI spec linter's :data:`app.schema_lint.OPENAPI_RULES` catalogue;
* every unconditional pack the engine runs for all formats
  (:func:`app.lint_engine.unconditional_rule_packs` — the cross-format ``common`` pack and the
  IXH-5.4 ``examples`` pack);
* every registered per-format :class:`app.lint_engine.RulePack` (AsyncAPI, GraphQL,
  protobuf, Arazzo, …), loaded through the same lazy loader the lint engine uses;
* every registered per-*paradigm* pack (FMT-5.5's ``data-contract`` pack, which runs for
  every ``data_schema`` artifact rather than for one format key) — catalogued here so a
  style guide can govern its rules exactly like any other built-in rule;
* the ``overlay`` pack (:data:`app.overlay_lint_rules.OVERLAY_RULES`, GVM-4.1) — OpenAPI Overlay
  findings raised while overlays are applied (or a bare overlay is linted);
* the intake-stage catalogue (:data:`app.intake_lint_rules.INTAKE_RULES`) — rules that
  describe the *source document as it arrived* rather than the model it produced (MFI-29.4's
  unresolved external references), which no model-driven pack can emit;
* the fixable OpenAPI rules (:func:`app.openapi_fix_rules.openapi_fix_rules`, GVM-3.1) — rules
  evaluated on demand when a fix is asked for, never by the default lint.

Every descriptor also publishes the rule's **fix capability** (GVM-3.1, #5869): ``fixable``,
and for a fixable rule its ``fix_class``, ``wire_visible``, ``fix_scope``, ``fix_default`` and
a one-line ``fix_summary`` — read from the :class:`~app.lint_engine.LintRule` itself — plus
``fix_owner``, which says who repairs the rule's findings (:func:`app.lint_fix.fix_owner_for`):
the deterministic ``engine``, the ``agent`` (documentation, examples and security findings,
whose repair invents meaning) or a ``human``.

Every descriptor also publishes the two fields the security score needs (ASP-1.3, #5921):
``owasp`` — the OWASP API Security Top 10 category ids a rule cites (declared on the
:class:`~app.lint_engine.LintRule`, validated against :mod:`app.owasp_api` here) — and, for
every ``security``-category rule, its published scoring ``weight``
(:func:`app.security_score.security_rule_weight`).

A renamed rule keeps its old id as an **alias** (GVM-4.4, #5879; :mod:`app.lint_rule_aliases`):
the descriptor publishes ``aliases``, :func:`resolve_rule_id` maps an alias to its descriptor,
and every consumer that matches stored ids — style-guide compilation, the guide editor, finding
fingerprints — accepts either spelling.

The MCP *surface* linter (:mod:`app.mcp_lint`, V2-MCP-21.x) is intentionally **not**
included: it lints an MCP capability surface, not a schema revision, and is not part of the
governance style-guide surface (GOV-1.4 evaluates guides in the revision lint paths).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .docs_site import guide_page
from .intake_lint_rules import INTAKE_PACK, INTAKE_RULES
from .lint_engine import (
    LintRule,
    available_lint_formats,
    available_lint_paradigms,
    get_paradigm_rule_pack,
    get_rule_pack,
    load_format_rule_packs,
    unconditional_rule_packs,
)
from .lint_fix import fix_owner_for
from .lint_rule_aliases import aliases_for, canonical_rule_id
from .openapi_fix_rules import OPENAPI_FIX_PACK, openapi_fix_rule, openapi_fix_rules
from .overlay_lint_rules import OVERLAY_PACK, OVERLAY_RULES
from .owasp_api import validate_risk_ids
from .schema_lint import OPENAPI_RULES
from .security_score import SECURITY_CATEGORY, security_rule_weight

__all__ = [
    "LINT_RULE_DOCS_PAGE",
    "LintRuleDescriptor",
    "builtin_rule_descriptors",
    "builtin_rule_ids",
    "docs_anchor_for",
    "registered_rule_ids_with_aliases",
    "resolve_rule_id",
]

#: Repository-relative path of the human-readable rule reference every descriptor's
#: ``docs_anchor`` points into — a page of the docs site (DOCS-1.2, #5619).
LINT_RULE_DOCS_PAGE = guide_page("build", "lint-rules")

#: Pack key recorded on descriptors sourced from the OpenAPI spec linter.
_OPENAPI_PACK = "openapi"


def docs_anchor_for(rule_id: str) -> str:
    """Return the docs anchor for ``rule_id`` inside :data:`LINT_RULE_DOCS_PAGE`.

    The anchor is the rule id with every ``.`` replaced by ``-`` (e.g.
    ``naming.schema-pascal-case`` -> ``naming-schema-pascal-case``). The reference page
    gives each rule's heading an explicit Docusaurus heading id (``### `rule.id` {#slug}``)
    with exactly this slug, so the anchor does not depend on any renderer's
    heading-slugification rules.

    :param rule_id: The rule's stable id.
    :returns: The anchor slug (without a leading ``#``).
    """
    return rule_id.replace(".", "-")


@dataclass(frozen=True)
class LintRuleDescriptor:
    """One registered built-in lint rule: identity, defaults, rationale, and docs pointer.

    Attributes:
        rule_id: Stable identifier — exactly the string the engine emits in a finding's
            ``rule`` field. Never renamed once shipped (it is hashed into finding ids and
            report fingerprints).
        pack: Which rule pack the rule belongs to (``openapi``, ``common``, ``asyncapi``,
            ``graphql``, ``protobuf``, ``arazzo``, …).
        category: The rule's group (``naming`` / ``documentation`` / ``structure`` /
            ``compatibility`` / …), used for grouping and per-category score rollups.
        default_severity: ``"error"`` | ``"warning"`` | ``"info"`` — the severity the rule
            carries when no style guide overrides it.
        rationale: One-line human explanation of why the rule exists.
        docs_anchor: Anchor slug into :data:`LINT_RULE_DOCS_PAGE` documenting the rule.
        owasp_ids: OWASP API Security Top 10 category ids the rule cites (ASP-1.3), in
            catalog order; empty for a rule that cites none.
        fixable: Whether the rule carries a deterministic fix (GVM-3.1).
        fix_class: ``structural`` / ``removal`` / ``fill-in`` / ``rename`` for a fixable
            rule, else ``None``.
        wire_visible: Whether the fix changes what clients see on the wire or in generated
            code; ``None`` for a rule that is not fixable.
        fix_summary: One line saying what the fix does; ``None`` when not fixable.
        fix_scope: ``finding`` or ``document`` — what the fix may touch; ``None`` when not
            fixable.
        fix_default: Whether the fix is applied without an explicit opt-in; ``None`` when
            not fixable.
        aliases: Earlier ids of this rule that still match it (GVM-4.4) — a style-guide row,
            stored finding or waiver recorded under one governs this rule. Empty for most rules.
    """

    rule_id: str
    pack: str
    category: str
    default_severity: str
    rationale: str
    docs_anchor: str
    owasp_ids: Tuple[str, ...] = ()
    fixable: bool = False
    fix_class: Optional[str] = None
    wire_visible: Optional[bool] = None
    fix_summary: Optional[str] = None
    fix_scope: Optional[str] = None
    fix_default: Optional[bool] = None
    aliases: Tuple[str, ...] = ()

    @property
    def fix_owner(self) -> str:
        """Who repairs this rule's findings: ``engine``, ``agent`` or ``human``."""
        return fix_owner_for(self.category, self.fixable, self.pack)

    @property
    def weight(self) -> Optional[float]:
        """The rule's published security-score weight; ``None`` unless it is a ``security`` rule."""
        if self.category != SECURITY_CATEGORY:
            return None
        return security_rule_weight(self.rule_id)

    def as_dict(self) -> Dict[str, Any]:
        """Return the descriptor as a plain dict (snake_case keys).

        Carries ``weight`` (``security`` rules only, else ``None``), ``owasp`` (the cited
        category ids, or ``None`` when the rule cites none) and the fix capability
        (``fixable``, ``fix_owner`` and — for a fixable rule — ``fix_class``,
        ``wire_visible``, ``fix_summary``, ``fix_scope``, ``fix_default``). Blocking (error) rules
        additionally carry CLX-4.3 transparency fields from
        :mod:`app.scanner_rule_transparency`.
        """
        from .scanner_rule_transparency import enrich_rule_dict

        base: Dict[str, Any] = {
            "rule_id": self.rule_id,
            "pack": self.pack,
            "category": self.category,
            "default_severity": self.default_severity,
            "rationale": self.rationale,
            "docs_anchor": self.docs_anchor,
            "weight": self.weight,
            "owasp": list(self.owasp_ids) if self.owasp_ids else None,
            "fixable": self.fixable,
            "fix_class": self.fix_class,
            "wire_visible": self.wire_visible,
            "fix_summary": self.fix_summary,
            "fix_scope": self.fix_scope,
            "fix_default": self.fix_default,
            "fix_owner": self.fix_owner,
            "aliases": list(self.aliases),
        }
        return enrich_rule_dict(base, self.rule_id)


def _descriptor(
    rule_id: str,
    pack: str,
    category: str,
    severity: str,
    rationale: str,
    owasp_ids: Tuple[str, ...] = (),
    fix_rule: Optional[LintRule] = None,
) -> LintRuleDescriptor:
    """Build one descriptor, deriving the docs anchor from the rule id.

    :param fix_rule: The :class:`~app.lint_engine.LintRule` whose fix capability the
        descriptor publishes; a rule without a fix (or ``None``) yields ``fixable=False``.
    :raises app.owasp_api.UnknownRiskError: when ``owasp_ids`` cites a category the OWASP API
        catalog does not define — a pack bug surfaced where the catalog is built, not later.
    """
    return LintRuleDescriptor(
        rule_id=rule_id,
        pack=pack,
        category=category,
        default_severity=severity,
        rationale=rationale,
        docs_anchor=docs_anchor_for(rule_id),
        owasp_ids=validate_risk_ids(owasp_ids),
        aliases=aliases_for(rule_id),
        **_fix_fields(fix_rule),
    )


def _fix_fields(rule: Optional[LintRule]) -> Dict[str, Any]:
    """Return the descriptor's fix fields for ``rule`` (empty when it carries no fix)."""
    if rule is None or getattr(rule, "fix", None) is None:
        return {}
    return {
        "fixable": True,
        "fix_class": rule.fix_class,
        "wire_visible": rule.wire_visible,
        "fix_summary": rule.fix_summary,
        "fix_scope": rule.fix_scope,
        "fix_default": rule.fix_default,
    }


def _pack_descriptor(rule: Any, pack_label: str) -> LintRuleDescriptor:
    """Build the descriptor of one :class:`~app.lint_engine.LintRule` of ``pack_label``."""
    return _descriptor(
        rule.rule_id,
        pack_label,
        rule.category,
        rule.severity,
        rule.description,
        tuple(getattr(rule, "owasp_ids", ()) or ()),
        fix_rule=rule,
    )


def builtin_rule_descriptors() -> Tuple[LintRuleDescriptor, ...]:
    """Enumerate every built-in lint rule as a :class:`LintRuleDescriptor`, sorted by id.

    The list is assembled from the live engines on every call (the underlying catalogues are
    module-level constants, so this is cheap): the OpenAPI catalogue, the common pack, and
    every registered format pack. A pack registered under multiple format keys (e.g. the
    AsyncAPI pack under ``asyncapi-2`` and ``asyncapi-3``) contributes each rule once.

    :returns: All built-in rule descriptors, sorted by ``rule_id`` for a deterministic payload.
    """
    by_id: Dict[str, LintRuleDescriptor] = {}

    # 1. The OpenAPI spec linter's catalogue (rationales live alongside it in schema_lint).
    #    A rule of it that gained a fix (GVM-3.1) publishes that fix from the fixable rules.
    for rule_id, (category, severity, rationale) in OPENAPI_RULES.items():
        by_id[rule_id] = _descriptor(
            rule_id,
            _OPENAPI_PACK,
            category,
            severity,
            rationale,
            fix_rule=openapi_fix_rule(rule_id),
        )
    #    The fixable OpenAPI rules that run on demand only (GVM-3.1): catalogued so a fix plan's
    #    findings are attributable, never emitted by the default lint.
    for rule in openapi_fix_rules():
        by_id.setdefault(rule.rule_id, _pack_descriptor(rule, OPENAPI_FIX_PACK))

    # 2. Every unconditional pack (the cross-format common pack and the IXH-5.4
    #    example-conformance pack) — taken from the engine itself, so the catalogue lists
    #    exactly what runs on every canonical-model lint.
    for pack in unconditional_rule_packs():
        pack_label = pack.pack_id or type(pack).__name__
        for rule in pack.rules():
            by_id[rule.rule_id] = _pack_descriptor(rule, pack_label)

    # 3. The intake-stage catalogue: rules emitted while a source is being ingested
    #    (MFI-29.4 remote $ref resolution), which never run through a model rule pack.
    for rule_id, (category, severity, rationale) in INTAKE_RULES.items():
        by_id[rule_id] = _descriptor(rule_id, INTAKE_PACK, category, severity, rationale)
    # The OpenAPI Overlay pack (GVM-4.1): emitted while overlays are applied, never by a model pack.
    for rule_id, (category, severity, rationale) in OVERLAY_RULES.items():
        by_id[rule_id] = _descriptor(rule_id, OVERLAY_PACK, category, severity, rationale)

    # 4. Every registered per-*paradigm* pack (FMT-5.5). A paradigm pack runs for a whole
    #    family of formats rather than one syntax — the data-contract pack for every
    #    ``data_schema`` artifact — so its rules are catalogued once, here, and a style
    #    guide can enable, disable or re-severity them exactly like any other built-in rule.
    load_format_rule_packs()
    for paradigm_key in available_lint_paradigms():
        paradigm_cls = get_paradigm_rule_pack(paradigm_key)
        if paradigm_cls is None:  # pragma: no cover - registry keys always resolve
            continue
        pack_label = paradigm_cls.pack_id or paradigm_cls.__name__
        for rule in paradigm_cls().rules():
            by_id.setdefault(rule.rule_id, _pack_descriptor(rule, pack_label))

    # 5. Every registered per-format pack. Subclass registrations under extra format keys
    #    (same rules, different key) dedupe naturally through the by-id dict.
    for format_key in available_lint_formats():
        pack_cls = get_rule_pack(format_key)
        if pack_cls is None:  # pragma: no cover - registry keys always resolve
            continue
        pack_label = pack_cls.pack_id or pack_cls.__name__
        for rule in pack_cls().rules():
            by_id.setdefault(rule.rule_id, _pack_descriptor(rule, pack_label))

    return tuple(by_id[rule_id] for rule_id in sorted(by_id))


def builtin_rule_ids() -> List[str]:
    """Return every registered built-in rule id, sorted — the ids findings may carry."""
    return [descriptor.rule_id for descriptor in builtin_rule_descriptors()]


def registered_rule_ids_with_aliases() -> frozenset:
    """Every id a stored row may name: the registered rule ids plus their aliases (GVM-4.4).

    Use it where an id is *accepted* (a guide row, a custom rule's reserved-id check); emit and
    compare with :func:`app.lint_rule_aliases.canonical_rule_id` applied.
    """
    ids = set(builtin_rule_ids())
    for descriptor in builtin_rule_descriptors():
        ids.update(descriptor.aliases)
    return frozenset(ids)


def resolve_rule_id(rule_id: str) -> Optional[LintRuleDescriptor]:
    """Return the descriptor for ``rule_id`` — canonical or an alias — or ``None`` when unknown.

    Args:
        rule_id: A rule id as stored or requested.

    Returns:
        The registered rule's descriptor (an alias resolves to the renamed rule's descriptor).
    """
    canonical = canonical_rule_id(rule_id)
    for descriptor in builtin_rule_descriptors():
        if descriptor.rule_id == canonical:
            return descriptor
    return None
