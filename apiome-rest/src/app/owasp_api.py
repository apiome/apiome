"""OWASP API Security Top 10 (2023) risk catalog (ASP-1.3, #5921).

The catalog-revision security axis publishes one sub-score per OWASP API risk category, and
every native ``security.*`` rule declares the categories it speaks to, so a security finding
always answers "which recognized risk is this an instance of?" rather than standing as an
isolated opinion. This module is the single place those category ids are defined;
:mod:`app.lint_rule_registry` validates every registered rule's ``owasp_ids`` against it when
the catalog is built, so a rule citing a category that does not exist is a startup failure,
not a broken link discovered by a user later.

It is the API-paradigm sibling of :mod:`app.mcp_owasp` (the OWASP MCP Top 10 the trust-posture
engine maps to) and follows it deliberately: a local, transparent reading of a published list,
with a resolvable reference per entry and a stated :data:`CATALOG_REVISION`, never a vendored
copy of the upstream document.

Coverage, honestly
------------------
:func:`coverage_summary` reports, for a set of rules, which categories are covered and which are
not. An uncovered category is reported as uncovered — Apiome never implies that a risk it has no
rule for is a risk the API does not have. The security axis applies the same contract per
revision: a category none of whose rules evaluated reads *not assessed*, never 100
(:mod:`app.security_score`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

#: The edition of the OWASP API Security Top 10 this catalog's reading tracks. Stamped into
#: coverage summaries so a stored sub-score stays interpretable after the upstream list moves on.
CATALOG_REVISION = "2023"

#: Resolvable reference for the published list this catalog reads.
CATALOG_REFERENCE = "https://owasp.org/API-Security/editions/2023/en/0x11-t10/"

_EDITION_ROOT = "https://owasp.org/API-Security/editions/2023/en/"

# --- Category ids ------------------------------------------------------------------------------
# Stable, never renamed once shipped: they are persisted inside stored axis evaluations and
# published per rule by ``GET /v1/lint/rules``, exactly like rule ids.

API1_BROKEN_OBJECT_LEVEL_AUTHORIZATION = "API1"
API2_BROKEN_AUTHENTICATION = "API2"
API3_BROKEN_OBJECT_PROPERTY_LEVEL_AUTHORIZATION = "API3"
API4_UNRESTRICTED_RESOURCE_CONSUMPTION = "API4"
API5_BROKEN_FUNCTION_LEVEL_AUTHORIZATION = "API5"
API6_UNRESTRICTED_ACCESS_TO_SENSITIVE_BUSINESS_FLOWS = "API6"
API7_SERVER_SIDE_REQUEST_FORGERY = "API7"
API8_SECURITY_MISCONFIGURATION = "API8"
API9_IMPROPER_INVENTORY_MANAGEMENT = "API9"
API10_UNSAFE_CONSUMPTION_OF_APIS = "API10"


@dataclass(frozen=True)
class OwaspApiRisk:
    """One category of the OWASP API Security Top 10, as this catalog reads it.

    Attributes:
        risk_id: Stable id (``API1`` … ``API10``). Never renamed once shipped.
        title: The category's published short title.
        description: What the category means concretely for an API description — written so a
            finding that cites it explains itself without the reader having to open the list.
        reference: Resolvable URL for the category.
    """

    risk_id: str
    title: str
    description: str
    reference: str

    def as_dict(self) -> Dict[str, str]:
        """Return the category as a JSON-ready dict (the catalog payload the API serves)."""
        return {
            "risk_id": self.risk_id,
            "title": self.title,
            "description": self.description,
            "reference": self.reference,
        }


def _risk(risk_id: str, title: str, slug: str, description: str) -> OwaspApiRisk:
    """Build one catalog entry whose reference is the edition page for ``slug``."""
    return OwaspApiRisk(
        risk_id=risk_id,
        title=title,
        description=description,
        reference=f"{_EDITION_ROOT}{slug}/",
    )


#: The catalog in published order (``API1`` first, ``API10`` last). Every rendering of it —
#: the sub-score list on an axis, the docs table, the coverage summary — uses this order.
RISKS: Mapping[str, OwaspApiRisk] = {
    API1_BROKEN_OBJECT_LEVEL_AUTHORIZATION: _risk(
        API1_BROKEN_OBJECT_LEVEL_AUTHORIZATION,
        "Broken object level authorization",
        "0xa1-broken-object-level-authorization",
        "An operation reads or changes a resource by an identifier the caller supplies without "
        "the description establishing that the caller is allowed to reach that object.",
    ),
    API2_BROKEN_AUTHENTICATION: _risk(
        API2_BROKEN_AUTHENTICATION,
        "Broken authentication",
        "0xa2-broken-authentication",
        "An operation — above all one that writes — declares no authentication requirement, or "
        "relies on a scheme or flow that does not protect the credential it carries.",
    ),
    API3_BROKEN_OBJECT_PROPERTY_LEVEL_AUTHORIZATION: _risk(
        API3_BROKEN_OBJECT_PROPERTY_LEVEL_AUTHORIZATION,
        "Broken object property level authorization",
        "0xa3-broken-object-property-level-authorization",
        "A request accepts properties the caller should not be able to set, or a response "
        "returns properties the caller should not be able to see.",
    ),
    API4_UNRESTRICTED_RESOURCE_CONSUMPTION: _risk(
        API4_UNRESTRICTED_RESOURCE_CONSUMPTION,
        "Unrestricted resource consumption",
        "0xa4-unrestricted-resource-consumption",
        "Inputs carry no bound — an unbounded string, array or integer, a list with no page "
        "size — and nothing in the description says what happens when a caller exceeds it.",
    ),
    API5_BROKEN_FUNCTION_LEVEL_AUTHORIZATION: _risk(
        API5_BROKEN_FUNCTION_LEVEL_AUTHORIZATION,
        "Broken function level authorization",
        "0xa5-broken-function-level-authorization",
        "An administrative or privileged operation is reachable under the same authorization "
        "as an ordinary one, so the description cannot tell the two apart.",
    ),
    API6_UNRESTRICTED_ACCESS_TO_SENSITIVE_BUSINESS_FLOWS: _risk(
        API6_UNRESTRICTED_ACCESS_TO_SENSITIVE_BUSINESS_FLOWS,
        "Unrestricted access to sensitive business flows",
        "0xa6-unrestricted-access-to-sensitive-business-flows",
        "A flow that harms the business when automated — a purchase, a sign-up, a reservation "
        "— is exposed without any stated control on excessive or scripted use.",
    ),
    API7_SERVER_SIDE_REQUEST_FORGERY: _risk(
        API7_SERVER_SIDE_REQUEST_FORGERY,
        "Server side request forgery",
        "0xa7-server-side-request-forgery",
        "An input is a URL the server will fetch — a callback, a webhook, an import location "
        "— and nothing constrains where it may point.",
    ),
    API8_SECURITY_MISCONFIGURATION: _risk(
        API8_SECURITY_MISCONFIGURATION,
        "Security misconfiguration",
        "0xa8-security-misconfiguration",
        "The description itself is misconfigured: a plain-HTTP server, a credential embedded in "
        "a server URL or in the document, a secured operation with no documented error "
        "responses.",
    ),
    API9_IMPROPER_INVENTORY_MANAGEMENT: _risk(
        API9_IMPROPER_INVENTORY_MANAGEMENT,
        "Improper inventory management",
        "0xa9-improper-inventory-management",
        "The description does not say which environment a server is, which version is current, "
        "or when a deprecated surface goes away — so stale and shadow surfaces stay reachable.",
    ),
    API10_UNSAFE_CONSUMPTION_OF_APIS: _risk(
        API10_UNSAFE_CONSUMPTION_OF_APIS,
        "Unsafe consumption of APIs",
        "0xaa-unsafe-consumption-of-apis",
        "Data obtained from another API is trusted more than user input: fetched over an "
        "unprotected channel, followed through redirects, or passed on without validation.",
    ),
}

#: Every known category id, in published catalog order (not lexical: ``API10`` is last).
RISK_IDS: Tuple[str, ...] = tuple(RISKS)

_ORDER: Mapping[str, int] = {risk_id: index for index, risk_id in enumerate(RISK_IDS)}


class UnknownRiskError(ValueError):
    """A rule cites an OWASP API category id that is not in the catalog.

    Raised when the rule catalog is built rather than when a finding is scored: a rule pack
    citing a category that does not exist is a bug in the pack, and failing early beats
    publishing a sub-score whose category resolves to nothing.
    """

    def __init__(self, risk_id: str) -> None:
        super().__init__(
            f"unknown OWASP API category id '{risk_id}'; known categories: {list(RISK_IDS)}"
        )
        self.risk_id = risk_id


def validate_risk_ids(risk_ids: Iterable[str]) -> Tuple[str, ...]:
    """Check that every id in ``risk_ids`` is a known category and normalize the sequence.

    Args:
        risk_ids: The category ids a rule claims to cover.

    Returns:
        The ids, de-duplicated and in catalog order, so a rule's mapping renders identically
        every time.

    Raises:
        UnknownRiskError: If any id is not in :data:`RISKS`.
    """
    validated = set()
    for risk_id in risk_ids:
        if risk_id not in RISKS:
            raise UnknownRiskError(risk_id)
        validated.add(risk_id)
    return tuple(sorted(validated, key=_ORDER.__getitem__))


def risk_titles(risk_ids: Iterable[str]) -> List[str]:
    """Return the human titles of ``risk_ids`` (unknown ids are skipped), in catalog order.

    Args:
        risk_ids: Category ids to label.

    Returns:
        The titles, for rendering a finding's category chips.
    """
    known = {r for r in risk_ids if r in RISKS}
    return [RISKS[r].title for r in sorted(known, key=_ORDER.__getitem__)]


def catalog() -> List[Dict[str, str]]:
    """Return the full catalog as JSON-ready dicts, in catalog order."""
    return [RISKS[risk_id].as_dict() for risk_id in RISK_IDS]


def coverage_summary(
    rule_risk_ids: Sequence[Sequence[str]],
) -> Dict[str, Any]:
    """Report which OWASP API categories a set of rules covers — and which it does not.

    The uncovered list is the point of this function. A catalog that only reported what it
    *does* check would let a reader infer that an unmentioned category is a risk the API does
    not have. Naming the gaps keeps the report honest about the limits of its own coverage.

    Args:
        rule_risk_ids: One entry per rule — the category ids that rule covers.

    Returns:
        ``{"revision", "reference", "covered": [...], "uncovered": [...], "rules_per_risk": {...}}``
        where ``rules_per_risk`` counts how many rules speak to each covered category. Lists
        and keys follow catalog order.
    """
    rules_per_risk: Dict[str, int] = {}
    for ids in rule_risk_ids:
        for risk_id in set(ids):
            if risk_id in RISKS:
                rules_per_risk[risk_id] = rules_per_risk.get(risk_id, 0) + 1

    covered = [risk_id for risk_id in RISK_IDS if risk_id in rules_per_risk]
    uncovered = [risk_id for risk_id in RISK_IDS if risk_id not in rules_per_risk]
    return {
        "revision": CATALOG_REVISION,
        "reference": CATALOG_REFERENCE,
        "covered": covered,
        "uncovered": uncovered,
        "rules_per_risk": {risk_id: rules_per_risk[risk_id] for risk_id in covered},
    }
