"""Catalog facts for per-kind scorecards — the fact catalogue, pure — CDG-5.4 (#5982).

GVM-1.x maturity ladders (still to come) will score catalog entities per kind. Their rule inputs are
**facts**: typed, evidence-backed statements about one entity, such as "it has a confirmed owner
team" or "its source refreshed within twice its cadence". This module says which facts apply to
which kind, what they are called, and how a fact's status is decided; the reads live in
:mod:`app.catalog_fact_store` and the route in :mod:`app.catalog_entity_routes`.

**No silent success.** A fact Apiome cannot establish is ``not_assessed`` — never ``met`` — and a
fact that cannot apply to the entity is ``not_applicable``. Until GVM-1.x lands there is no score:
:class:`CatalogFactsOut` carries ``score: null`` and pages show the facts as a plain checklist, never
a grade computed from partial facts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

__all__ = [
    "APPLICABLE_FACTS",
    "FACT_LABELS",
    "CatalogFact",
    "CatalogFactsOut",
    "FactEvidence",
    "count_status",
    "facts_for_kind",
    "freshness",
]

FactStatus = Literal["met", "unmet", "not_applicable", "not_assessed"]

#: What each fact is called on a checklist.
FACT_LABELS: Dict[str, str] = {
    "owner.present": "Has an owner team",
    "owner.contactable": "Owner team is contactable",
    "consumers.declared": "Consumers declared",
    "dependencies.declared": "Dependencies declared",
    "refresh.fresh": "Refreshed within twice its cadence",
    "deployment.known": "Deployment known",
    "shadow.none": "No shadow APIs",
    "registry.level-set": "Compatibility level set",
    "mcp.baseline-approved": "Trust baseline approved",
    "agent.readiness": "Agent readiness",
}

#: The facts each registry kind (:data:`app.catalog_entities.REGISTRY`) carries, in display order.
#: A kind that is not listed (``team``) has none.
APPLICABLE_FACTS: Dict[str, Tuple[str, ...]] = {
    "api": (
        "owner.present",
        "owner.contactable",
        "consumers.declared",
        "dependencies.declared",
        "refresh.fresh",
        "deployment.known",
    ),
    "spec": (
        "owner.present",
        "owner.contactable",
        "consumers.declared",
        "dependencies.declared",
        "refresh.fresh",
        "deployment.known",
        "registry.level-set",
    ),
    "mcp_server": (
        "owner.present",
        "owner.contactable",
        "dependencies.declared",
        "refresh.fresh",
        "mcp.baseline-approved",
    ),
    "connector": ("owner.present", "owner.contactable", "dependencies.declared", "refresh.fresh", "shadow.none"),
    "gateway_config": ("owner.present", "owner.contactable", "refresh.fresh", "deployment.known", "shadow.none"),
    "agent": ("owner.present", "owner.contactable", "consumers.declared", "agent.readiness"),
    "model": ("owner.present", "owner.contactable"),
    "consumer": ("owner.present", "owner.contactable", "dependencies.declared"),
    "component": ("owner.present", "owner.contactable", "dependencies.declared"),
}


def facts_for_kind(kind: str) -> Tuple[str, ...]:
    """The fact keys a kind carries (empty for a kind with none)."""
    return APPLICABLE_FACTS.get(kind, ())


def count_status(count: Optional[int]) -> FactStatus:
    """``met`` for a count of at least one, ``unmet`` for zero, ``not_assessed`` when unknown."""
    if count is None:
        return "not_assessed"
    return "met" if count >= 1 else "unmet"


def freshness(last_success: Optional[datetime], cadence_seconds: int, now: Optional[datetime] = None) -> FactStatus:
    """Whether a source last succeeded within twice its cadence.

    Args:
        last_success: When it last refreshed successfully, or ``None`` when it never has.
        cadence_seconds: Its refresh cadence.
        now: Clock override for tests.

    Returns:
        ``met`` within ``2 × cadence``, else ``unmet`` (a source that never succeeded is unmet).
    """
    if last_success is None:
        return "unmet"
    moment = last_success if last_success.tzinfo else last_success.replace(tzinfo=timezone.utc)
    window = timedelta(seconds=2 * max(1, int(cadence_seconds)))
    return "met" if (now or datetime.now(timezone.utc)) - moment <= window else "unmet"


# ---------------------------------------------------------------------------------------------
# Wire shapes
# ---------------------------------------------------------------------------------------------


class _CamelModel(BaseModel):
    """Wire base: snake_case fields, camelCase JSON."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class FactEvidence(_CamelModel):
    """Where to check a fact: a page in the app and/or the API that holds the data."""

    label: str
    href: Optional[str] = Field(default=None, description="The app page.")
    api: Optional[str] = Field(default=None, description="The REST route (relative to the API host).")


class CatalogFact(_CamelModel):
    """One fact about one entity."""

    key: str = Field(description="`owner.present`, `consumers.declared`, `refresh.fresh`, …")
    label: str
    status: FactStatus = Field(
        description="`met`, `unmet`, `not_applicable` (cannot apply to this entity) or `not_assessed` "
        "(Apiome cannot establish it — never treated as met)."
    )
    value: Union[bool, int, None] = Field(default=None, description="A count for count facts, else the boolean.")
    detail: Optional[str] = Field(default=None, description="What the status is based on.")
    evidence: List[FactEvidence] = Field(default_factory=list)


class CatalogFactsOut(_CamelModel):
    """An entity's facts, in display order. No score until GVM-1.x ladders consume them."""

    kind: str
    id: str
    name: str
    facts: List[CatalogFact]
    score: None = Field(
        default=None,
        description="Always `null`: maturity ladders (GVM-1.x) are not available yet, and a grade is never "
        "computed from partial facts.",
    )
