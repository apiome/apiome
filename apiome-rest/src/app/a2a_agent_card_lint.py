"""A2A Agent Card lint pack — MFI-18.1 (#3974).

Native capability and auth hygiene rules for an imported Agent Card, run by the shared lint
engine (:func:`app.lint_engine.lint_canonical_model`) beside its always-on common pack. Each
rule reads the canonical model the A2A normalizer produced
(:mod:`app.a2a_agent_card_normalizer`): card facts on ``api.extras``, skills as operations.

**Auth hygiene**

* ``a2a.security-undeclared-scheme`` — a ``security`` requirement (card or skill) names a scheme
  ``securitySchemes`` does not define, so no client can satisfy it.
* ``a2a.no-security`` — the card declares no security at all: the agent accepts anonymous calls.
* ``a2a.unknown-scheme-type`` — a scheme's ``type`` is none of the A2A / OpenAPI types.
* ``a2a.apikey-in-query`` — an ``apiKey`` scheme sent in the query string, where it leaks into
  logs and referrers.
* ``a2a.insecure-endpoint`` — an endpoint served over plain ``http`` (loopback excepted).

**Capability / descriptor hygiene**

* ``a2a.missing-required-field`` — a field the spec requires (``description``, ``url``,
  ``version``, ``capabilities``, ``defaultInputModes``, ``defaultOutputModes``) is absent.
* ``a2a.skill-missing-description`` / ``a2a.skill-missing-tags`` — a skill a caller cannot
  choose (no description) or find (no tags).
* ``a2a.duplicate-skill-id`` — two skills share an ``id``, so neither has a stable identity.
* ``a2a.skill-without-modes`` — a skill with no input or output modes of its own *and* no card
  default, so its contract is unknown.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Tuple
from urllib.parse import urlsplit

from .canonical_model import CanonicalApi, Operation
from .lint_engine import LintRule, RulePack, lint_canonical_model
from .schema_lint import LintResult

__all__ = ["A2aRulePack", "lint_a2a_agent_card", "lint_a2a_result"]

#: Security-scheme ``type`` values A2A accepts (the OpenAPI 3 set).
_KNOWN_SCHEME_TYPES = frozenset({"apiKey", "http", "oauth2", "openIdConnect", "mutualTLS"})

#: Card fields A2A marks required beyond ``name`` / ``skills`` (which the parser enforces).
_REQUIRED_CARD_FIELDS: Tuple[str, ...] = (
    "description",
    "url",
    "version",
    "capabilities",
    "defaultInputModes",
    "defaultOutputModes",
)

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _skills(api: CanonicalApi) -> List[Operation]:
    """Every skill operation, in key order."""
    ops: List[Operation] = []
    for service in sorted(api.services, key=lambda s: s.key):
        ops.extend(sorted(service.operations, key=lambda o: o.key))
    return ops


def _schemes(api: CanonicalApi) -> Mapping[str, Any]:
    """The card's ``securitySchemes`` map."""
    schemes = api.extras.get("security_schemes")
    return schemes if isinstance(schemes, Mapping) else {}


def _requirement_names(requirements: Any) -> List[str]:
    """Scheme names referenced by a ``[{scheme: [scopes]}]`` list."""
    names: List[str] = []
    if isinstance(requirements, list):
        for requirement in requirements:
            if isinstance(requirement, Mapping):
                names.extend(str(name) for name in requirement)
    return names


def _check_undeclared_scheme(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    schemes = _schemes(api)
    for name in sorted(set(_requirement_names(api.extras.get("security_requirements")))):
        if name not in schemes:
            yield (
                "security",
                f"Card security requires scheme {name!r}, which securitySchemes does not define.",
            )
    for op in _skills(api):
        if op.extras.get("security_source") != "skill":
            continue
        for name in sorted(set(_requirement_names(op.extras.get("security_requirements")))):
            if name not in schemes:
                yield (
                    f"operations.{op.key}.security",
                    f"Skill {op.name!r} requires scheme {name!r}, which securitySchemes does "
                    "not define.",
                )


def _check_no_security(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    if _schemes(api) or _requirement_names(api.extras.get("security_requirements")):
        return
    if any(_requirement_names(op.extras.get("security_requirements")) for op in _skills(api)):
        return
    yield (
        "securitySchemes",
        "The card declares no security schemes or requirements; the agent accepts anonymous "
        "requests.",
    )


def _check_unknown_scheme_type(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for name, scheme in sorted(_schemes(api).items()):
        scheme_type = scheme.get("type") if isinstance(scheme, Mapping) else None
        if scheme_type not in _KNOWN_SCHEME_TYPES:
            yield (
                f"securitySchemes.{name}",
                f"Security scheme {name!r} has type {scheme_type!r}; expected one of "
                + ", ".join(sorted(_KNOWN_SCHEME_TYPES))
                + ".",
            )


def _check_apikey_in_query(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for name, scheme in sorted(_schemes(api).items()):
        if isinstance(scheme, Mapping) and scheme.get("type") == "apiKey" and scheme.get(
            "in"
        ) == "query":
            yield (
                f"securitySchemes.{name}",
                f"API key scheme {name!r} is sent in the query string, where it is logged; "
                "send it in a header instead.",
            )


def _check_insecure_endpoint(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for index, server in enumerate(api.servers):
        parts = urlsplit(server.url)
        if parts.scheme.lower() == "http" and (parts.hostname or "") not in _LOOPBACK_HOSTS:
            yield (
                f"servers[{index}]",
                f"Endpoint {server.url!r} is served over plain HTTP; A2A requires HTTPS in "
                "production.",
            )


def _check_missing_required_field(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    present = set(api.extras.get("present_keys") or ())
    for field_name in _REQUIRED_CARD_FIELDS:
        if field_name not in present:
            yield (field_name, f"The card is missing the required `{field_name}` field.")


def _check_skill_missing_description(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for op in _skills(api):
        if not (op.description or "").strip():
            yield (
                f"operations.{op.key}",
                f"Skill {op.name!r} has no description; a calling agent cannot tell when to "
                "use it.",
            )


def _check_skill_missing_tags(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for op in _skills(api):
        if not op.tags:
            yield (
                f"operations.{op.key}",
                f"Skill {op.name!r} has no tags, so it cannot be found by tag.",
            )


def _check_duplicate_skill_id(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for op in _skills(api):
        first = op.extras.get("duplicate_of")
        if first:
            yield (
                f"operations.{op.key}",
                f"Skill id {op.extras.get('skill_id')!r} is already used by {first!r}; skill "
                "ids must be unique within a card.",
            )


def _check_skill_without_modes(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for op in _skills(api):
        missing: Dict[str, bool] = {
            "input": not op.extras.get("input_modes"),
            "output": not op.extras.get("output_modes"),
        }
        gaps = [direction for direction, empty in missing.items() if empty]
        if gaps:
            yield (
                f"operations.{op.key}",
                f"Skill {op.name!r} has no {' or '.join(gaps)} modes and the card sets no "
                "default.",
            )


class A2aRulePack(RulePack, register=True):
    """Capability and auth hygiene rules for A2A Agent Cards."""

    format = "a2a"
    pack_id = "a2a"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="a2a.security-undeclared-scheme",
            category="security",
            severity="error",
            description="Flag security requirements that name an undefined scheme.",
            check=_check_undeclared_scheme,
        ),
        LintRule(
            rule_id="a2a.no-security",
            category="security",
            severity="warning",
            description="Flag cards that declare no security at all.",
            check=_check_no_security,
        ),
        LintRule(
            rule_id="a2a.unknown-scheme-type",
            category="security",
            severity="warning",
            description="Flag security schemes whose type A2A does not define.",
            check=_check_unknown_scheme_type,
        ),
        LintRule(
            rule_id="a2a.apikey-in-query",
            category="security",
            severity="warning",
            description="Flag API keys sent in the query string.",
            check=_check_apikey_in_query,
        ),
        LintRule(
            rule_id="a2a.insecure-endpoint",
            category="security",
            severity="warning",
            description="Flag endpoints served over plain HTTP.",
            check=_check_insecure_endpoint,
        ),
        LintRule(
            rule_id="a2a.missing-required-field",
            category="structure",
            severity="warning",
            description="Flag cards missing a field the A2A spec requires.",
            check=_check_missing_required_field,
        ),
        LintRule(
            rule_id="a2a.skill-missing-description",
            category="documentation",
            severity="warning",
            description="Flag skills with no description.",
            check=_check_skill_missing_description,
        ),
        LintRule(
            rule_id="a2a.skill-missing-tags",
            category="quality",
            severity="info",
            description="Flag skills with no tags.",
            check=_check_skill_missing_tags,
        ),
        LintRule(
            rule_id="a2a.duplicate-skill-id",
            category="naming",
            severity="error",
            description="Flag skill ids repeated within one card.",
            check=_check_duplicate_skill_id,
        ),
        LintRule(
            rule_id="a2a.skill-without-modes",
            category="structure",
            severity="info",
            description="Flag skills with no input or output modes and no card default.",
            check=_check_skill_without_modes,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the pack's rules."""
        return list(self._RULES)


def lint_a2a_result(model: CanonicalApi) -> LintResult:
    """Lint a normalized Agent Card through the shared engine (common + ``a2a`` packs).

    Args:
        model: The canonical model the A2A adapter produced.

    Returns:
        The engine's deterministic lint result.
    """
    return lint_canonical_model(model)


def lint_a2a_agent_card(raw: str) -> LintResult:
    """Parse, normalize and lint raw Agent Card text end to end.

    Args:
        raw: The card JSON.

    Returns:
        The lint result.

    Raises:
        app.import_source.ImportSourceError: When the card cannot be parsed.
    """
    from .a2a_import_source import A2aImportSource

    adapter = A2aImportSource()
    return lint_a2a_result(adapter.normalize(adapter.parse(raw)))
