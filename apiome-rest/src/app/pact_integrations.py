"""The Contracts landing's integrations list — PFX-8.1 (#7298): the pure half.

An **integration** is one consumer ↔ provider pair with a pact. The Contracts landing
(``/ade/dashboard/pacts``) lists them in one table and folds what needs attention into one status
strip. This module decides, for each pair, from facts :mod:`app.pact_integrations_store` read:

* its **kind** — ``bidirectional`` when its newest verdict is a bi-directional comparison (PFX-2.3),
  or when it has no verdict yet and the provider has published a provider contract; ``pact``
  otherwise;
* its **verdict**, one of :data:`VERDICTS`, first match wins:

  ===========================  ===============================================================
  ``failing``                  the newest result of the newest pact failed
  ``stale``                    the stale-pact sweep (PFX-6.2) found the newest pact overdue
  ``verified``                 the newest result passed
  ``no-provider-contract``     never verified, and the provider has no provider contract —
                               nothing to compare the pact with yet
  ``unverified``               never verified, but the provider has a provider contract
  ===========================  ===============================================================

* whether it is **pending** (PFX-1.7): a Pact-kind pact the provider has never passed natively,
  so a failure cannot break the provider's build yet;
* the **environments both sides are deployed in** right now.

It also validates the query (search text, filter, page) — an unknown filter, an over-long search
or a page outside the bounds is a ``400`` with a code, never ignored — and filters, counts and
pages the classified rows. No database, no HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, Iterable, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ATTENTION_EXAMPLES",
    "CODE_FILTER_INVALID",
    "CODE_MINE_NEEDS_USER",
    "CODE_PAGE_INVALID",
    "CODE_SEARCH_INVALID",
    "DEFAULT_LIMIT",
    "FILTERS",
    "IntegrationFacts",
    "IntegrationsError",
    "IntegrationsQuery",
    "MAX_INTEGRATIONS",
    "MAX_LIMIT",
    "MAX_SEARCH_LENGTH",
    "PactIntegration",
    "PactIntegrationAttention",
    "PactIntegrationCounts",
    "PactIntegrationRef",
    "PactIntegrationsPage",
    "VERDICTS",
    "build_page",
    "classify",
    "parse_query",
]

#: The most pairs one read classifies. A workspace with more is answered ``truncated`` with the
#: number left out, so the list query stays bounded (and has a plan-check entry).
MAX_INTEGRATIONS = 1000

#: The page size when none is asked for, and the largest one allowed.
DEFAULT_LIMIT = 25
MAX_LIMIT = 100

#: The longest search text accepted.
MAX_SEARCH_LENGTH = 100

#: How many pairs each status-strip category names.
ATTENTION_EXAMPLES = 3

#: Every verdict, worst first (the order the table sorts by).
VERDICTS: Tuple[str, ...] = ("failing", "stale", "no-provider-contract", "unverified", "verified")

#: The table's filter chips.
FILTERS: Tuple[str, ...] = ("all", "failing", "stale", "bidirectional", "mine")

CODE_FILTER_INVALID = "pact-integrations-filter-invalid"
CODE_SEARCH_INVALID = "pact-integrations-search-invalid"
CODE_PAGE_INVALID = "pact-integrations-page-invalid"
CODE_MINE_NEEDS_USER = "pact-integrations-mine-needs-user"

Kind = Literal["pact", "bidirectional"]
Verdict = Literal["failing", "stale", "no-provider-contract", "unverified", "verified"]


class IntegrationsError(ValueError):
    """A refused query, carrying a machine-readable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        """Keep the code beside the message.

        Args:
            code: One of the ``CODE_*`` constants.
            message: What a person reads.
        """
        super().__init__(message)
        self.code = code


# --- the query ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class IntegrationsQuery:
    """A checked query.

    Attributes:
        search: Lower-cased text a handle or name must contain, or ``None``.
        filter: One of :data:`FILTERS`.
        limit: The page size.
        offset: How many matching rows to skip.
    """

    search: Optional[str] = None
    filter: str = "all"
    limit: int = DEFAULT_LIMIT
    offset: int = 0


def parse_query(
    search: Optional[str] = None,
    filter: Optional[str] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> IntegrationsQuery:
    """Check the query parameters.

    Args:
        search: The search text (trimmed; empty reads as none).
        filter: A filter chip (``None`` for ``all``).
        limit: The page size, 1 … :data:`MAX_LIMIT`.
        offset: Rows to skip, 0 … :data:`MAX_INTEGRATIONS`.

    Returns:
        The query.

    Raises:
        IntegrationsError: ``pact-integrations-filter-invalid``, ``-search-invalid`` or
            ``-page-invalid``, naming what was wrong.
    """
    chosen = filter if filter is not None else "all"
    if chosen not in FILTERS:
        raise IntegrationsError(CODE_FILTER_INVALID, f"Unknown filter '{chosen}'. Use one of: {', '.join(FILTERS)}.")
    text = (search or "").strip()
    if len(text) > MAX_SEARCH_LENGTH:
        raise IntegrationsError(CODE_SEARCH_INVALID, f"Search text is longer than {MAX_SEARCH_LENGTH} characters.")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise IntegrationsError(CODE_SEARCH_INVALID, "Search text contains a control character.")
    size = DEFAULT_LIMIT if limit is None else limit
    if size < 1 or size > MAX_LIMIT:
        raise IntegrationsError(CODE_PAGE_INVALID, f"limit must be between 1 and {MAX_LIMIT}.")
    skip = 0 if offset is None else offset
    if skip < 0 or skip > MAX_INTEGRATIONS:
        raise IntegrationsError(CODE_PAGE_INVALID, f"offset must be between 0 and {MAX_INTEGRATIONS}.")
    return IntegrationsQuery(search=text.lower() or None, filter=chosen, limit=size, offset=skip)


# --- the facts the store reads ----------------------------------------------------------------------


@dataclass(frozen=True)
class IntegrationFacts:
    """What the store read about one pair.

    Attributes:
        provider: The provider's handle.
        provider_name: Its display name.
        consumer: The consumer's handle.
        consumer_name: Its display name.
        provider_id: The provider's id (for the owner check).
        consumer_id: The consumer's id.
        consumer_version: The newest pact's consumer version.
        pact_version_sha: The newest pact's content sha.
        published_at: When it was published (ISO 8601).
        latest_success: The newest result's verdict, or ``None`` when never verified.
        latest_kind: ``native`` or ``bidirectional``, or ``None``.
        latest_at: When the newest result was recorded.
        provider_version: The provider version the newest result verified.
        provider_has_contract: Whether the provider has published a provider contract.
        native_success: Whether the provider ever passed this content natively (pending rule).
        stale: Whether the stale-pact sweep found the newest pact overdue.
        consumer_environments: Where the consumer is deployed now.
        provider_environments: Where the provider is deployed now.
    """

    provider: str
    provider_name: str
    consumer: str
    consumer_name: str
    provider_id: str = ""
    consumer_id: str = ""
    consumer_version: str = ""
    pact_version_sha: str = ""
    published_at: Optional[str] = None
    latest_success: Optional[bool] = None
    latest_kind: Optional[str] = None
    latest_at: Optional[str] = None
    provider_version: Optional[str] = None
    provider_has_contract: bool = False
    native_success: bool = False
    stale: bool = False
    consumer_environments: FrozenSet[str] = field(default_factory=frozenset)
    provider_environments: FrozenSet[str] = field(default_factory=frozenset)


# --- the answer -------------------------------------------------------------------------------------


class PactIntegration(BaseModel):
    """One row of the integrations table."""

    model_config = ConfigDict(extra="forbid")

    consumer: str = Field(..., description="The consumer's handle.")
    consumer_name: str = Field(..., description="The consumer's display name.")
    provider: str = Field(..., description="The provider's handle.")
    provider_name: str = Field(..., description="The provider's display name.")
    consumer_version: str = Field(..., description="The consumer version of the newest pact.")
    provider_version: Optional[str] = Field(None, description="The provider version the newest result verified.")
    pact_version_sha: str = Field(..., description="The newest pact's content sha.")
    published_at: Optional[str] = Field(None, description="When the newest pact was published.")
    kind: Kind = Field(..., description="`pact`, or `bidirectional` when a provider contract is compared.")
    verdict: Verdict = Field(..., description="`failing`, `stale`, `no-provider-contract`, `unverified` or `verified`.")
    pending: bool = Field(..., description="A Pact-kind pact the provider has never passed (PFX-1.7).")
    environments: List[str] = Field(
        default_factory=list, description="The environments both sides are deployed in now, by name."
    )
    verified_at: Optional[str] = Field(None, description="When the newest result was recorded; null if never.")
    mine: bool = Field(False, description="Whether a team the caller is on owns the consumer or the provider.")


class PactIntegrationRef(BaseModel):
    """A pair the status strip names."""

    model_config = ConfigDict(extra="forbid")

    consumer: str
    consumer_name: str
    provider: str
    provider_name: str
    consumer_version: str
    provider_version: Optional[str] = None
    verified_at: Optional[str] = None
    published_at: Optional[str] = None


class PactIntegrationAttention(BaseModel):
    """Up to :data:`ATTENTION_EXAMPLES` pairs per status-strip category, worst first."""

    model_config = ConfigDict(extra="forbid")

    failing: List[PactIntegrationRef] = Field(default_factory=list)
    stale: List[PactIntegrationRef] = Field(default_factory=list)
    no_provider_contract: List[PactIntegrationRef] = Field(default_factory=list)
    pending: List[PactIntegrationRef] = Field(default_factory=list)


class PactIntegrationCounts(BaseModel):
    """Counts over every classified pair (the search and filter do not narrow them)."""

    model_config = ConfigDict(extra="forbid")

    integrations: int = 0
    verified: int = 0
    failing: int = 0
    stale: int = 0
    no_provider_contract: int = 0
    unverified: int = 0
    pending: int = 0
    bidirectional: int = 0
    mine: int = 0


class PactIntegrationsPage(BaseModel):
    """What ``GET /v1/tenants/{tenant}/pact-integrations`` answers."""

    model_config = ConfigDict(extra="forbid")

    integrations: List[PactIntegration] = Field(default_factory=list, description="This page, worst first.")
    total: int = Field(0, description="Rows matching the search and filter.")
    offset: int = 0
    limit: int = DEFAULT_LIMIT
    filter: str = "all"
    search: Optional[str] = None
    counts: PactIntegrationCounts = Field(default_factory=PactIntegrationCounts)
    attention: PactIntegrationAttention = Field(default_factory=PactIntegrationAttention)
    pacticipants: int = Field(0, description="Pacticipants in the workspace.")
    environments: int = Field(0, description="Environments in the workspace.")
    truncated: bool = Field(False, description=f"More than {MAX_INTEGRATIONS} pairs: the rest are not classified.")
    omitted_integrations: int = Field(0, description="How many pairs were left out when truncated.")
    mine_available: bool = Field(True, description="False for a credential with no user (no `mine` filter).")


# --- the rules --------------------------------------------------------------------------------------


def _verdict(facts: IntegrationFacts) -> Verdict:
    """The pair's verdict (see the module table)."""
    if facts.latest_success is False:
        return "failing"
    if facts.stale:
        return "stale"
    if facts.latest_success is True:
        return "verified"
    return "unverified" if facts.provider_has_contract else "no-provider-contract"


def _kind(facts: IntegrationFacts) -> Kind:
    """``bidirectional`` or ``pact`` (see the module docstring)."""
    if facts.latest_kind is not None:
        return "bidirectional" if facts.latest_kind == "bidirectional" else "pact"
    return "bidirectional" if facts.provider_has_contract else "pact"


def classify(facts: IntegrationFacts, owned: FrozenSet[str] = frozenset()) -> PactIntegration:
    """One pair's row.

    Args:
        facts: What the store read.
        owned: The pacticipant ids a team of the caller owns.

    Returns:
        The row.
    """
    kind = _kind(facts)
    return PactIntegration(
        consumer=facts.consumer,
        consumer_name=facts.consumer_name,
        provider=facts.provider,
        provider_name=facts.provider_name,
        consumer_version=facts.consumer_version,
        provider_version=facts.provider_version,
        pact_version_sha=facts.pact_version_sha,
        published_at=facts.published_at,
        kind=kind,
        verdict=_verdict(facts),
        pending=kind == "pact" and not facts.native_success,
        environments=sorted(facts.consumer_environments & facts.provider_environments),
        verified_at=facts.latest_at,
        mine=bool(owned) and (facts.consumer_id in owned or facts.provider_id in owned),
    )


def _sort_key(row: PactIntegration) -> Tuple[int, str, str]:
    """Worst verdict first, then by consumer and provider name."""
    return (VERDICTS.index(row.verdict), row.consumer_name.lower(), row.provider_name.lower())


def _matches(row: PactIntegration, query: IntegrationsQuery) -> bool:
    """Whether a row passes the search and the filter."""
    if query.search:
        haystack = " ".join((row.consumer, row.consumer_name, row.provider, row.provider_name)).lower()
        if query.search not in haystack:
            return False
    if query.filter == "failing":
        return row.verdict == "failing"
    if query.filter == "stale":
        return row.verdict == "stale"
    if query.filter == "bidirectional":
        return row.kind == "bidirectional"
    if query.filter == "mine":
        return row.mine
    return True


def _ref(row: PactIntegration) -> PactIntegrationRef:
    """The strip's short form of a row."""
    return PactIntegrationRef(
        consumer=row.consumer,
        consumer_name=row.consumer_name,
        provider=row.provider,
        provider_name=row.provider_name,
        consumer_version=row.consumer_version,
        provider_version=row.provider_version,
        verified_at=row.verified_at,
        published_at=row.published_at,
    )


def _examples(rows: Iterable[PactIntegration]) -> List[PactIntegrationRef]:
    """The first :data:`ATTENTION_EXAMPLES` rows, as refs."""
    return [_ref(row) for row in list(rows)[:ATTENTION_EXAMPLES]]


def build_page(
    facts: Sequence[IntegrationFacts],
    query: IntegrationsQuery,
    *,
    owned: FrozenSet[str] = frozenset(),
    pacticipants: int = 0,
    environments: int = 0,
    omitted: int = 0,
    mine_available: bool = True,
) -> PactIntegrationsPage:
    """Classify, count, filter and page the pairs.

    Args:
        facts: Every pair read (at most :data:`MAX_INTEGRATIONS`).
        query: The checked query.
        owned: The pacticipant ids a team of the caller owns.
        pacticipants: The workspace's pacticipant count.
        environments: The workspace's environment count.
        omitted: Pairs left out because the read was capped.
        mine_available: Whether the caller is a user (so ``mine`` means something).

    Returns:
        The page.
    """
    rows = sorted((classify(item, owned) for item in facts), key=_sort_key)
    counts = PactIntegrationCounts(
        integrations=len(rows),
        verified=sum(1 for row in rows if row.verdict == "verified"),
        failing=sum(1 for row in rows if row.verdict == "failing"),
        stale=sum(1 for row in rows if row.verdict == "stale"),
        no_provider_contract=sum(1 for row in rows if row.verdict == "no-provider-contract"),
        unverified=sum(1 for row in rows if row.verdict == "unverified"),
        pending=sum(1 for row in rows if row.pending),
        bidirectional=sum(1 for row in rows if row.kind == "bidirectional"),
        mine=sum(1 for row in rows if row.mine),
    )
    attention = PactIntegrationAttention(
        failing=_examples(row for row in rows if row.verdict == "failing"),
        stale=_examples(row for row in rows if row.verdict == "stale"),
        no_provider_contract=_examples(row for row in rows if row.verdict == "no-provider-contract"),
        pending=_examples(row for row in rows if row.pending),
    )
    matching = [row for row in rows if _matches(row, query)]
    return PactIntegrationsPage(
        integrations=matching[query.offset : query.offset + query.limit],
        total=len(matching),
        offset=query.offset,
        limit=query.limit,
        filter=query.filter,
        search=query.search,
        counts=counts,
        attention=attention,
        pacticipants=pacticipants,
        environments=environments,
        truncated=omitted > 0,
        omitted_integrations=omitted,
        mine_available=mine_available,
    )
