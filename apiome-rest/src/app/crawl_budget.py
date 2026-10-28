"""Crawl budgets and checkpoints for registry discovery — MFI-31.4 (#4401).

A registry-as-source connector crawls a *catalog*: a Confluent Schema Registry with thousands of
subjects, an xRegistry, a FHIR server. Crawled without limits it is hostile to the registry; crawled
from zero every time it is fragile for us (one timeout and the whole pass is lost). This module holds
the primitives every crawl shares:

* :class:`CrawlBudget` — the limits of one crawl (one sync): requests per second to one host, total
  requests, listing pages and response bytes. A connector sets them with scope keys
  (:data:`BUDGET_SCOPE_KEYS`), checked by :func:`validate_budget_scope` against the family's
  :class:`BudgetLimits` (defaults and hard caps), and read by :func:`budget_from_scope`.
* :class:`CrawlMeter` — spends one budget: :meth:`~CrawlMeter.claim_request` rate-limits and counts a
  request (and refuses once anything is spent), :meth:`~CrawlMeter.add_bytes` counts response bytes,
  :meth:`~CrawlMeter.claim_page` counts a listing page. A refusal is :class:`CrawlBudgetExceededError`, a
  :class:`~app.refresh_source.RefreshSourceError` with ``error_class = "budget-exceeded"``.
  :meth:`~CrawlMeter.report` is what a run summary shows.
* :class:`HostRateLimiter` — spaces requests to one host (moved here from :mod:`app.registry_crawl`).
* :class:`CrawlState` with :func:`load_crawl_state` / :func:`save_crawl_state` — the **checkpoint**
  a connector keeps between runs in ``apiome.catalog_connector_crawl_state`` (V335): the pass in
  progress and where it got to, when the last full pass finished, and the incremental watermark.
  A crawl writes it as it goes, so a run that is killed or runs out of budget resumes where it
  stopped.

The Confluent crawler (:mod:`app.schema_registry_connector_source`) uses all of it; the generic
registry crawls (:mod:`app.registry_crawl`) use the meter.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Callable, Dict, Mapping, Optional

from .refresh_source import RefreshSourceError

__all__ = [
    "BUDGET_SCOPE_KEYS",
    "ERROR_CLASS_BUDGET",
    "BudgetLimits",
    "CrawlBudget",
    "CrawlBudgetExceededError",
    "CrawlMeter",
    "CrawlState",
    "HostRateLimiter",
    "budget_from_scope",
    "load_crawl_state",
    "save_crawl_state",
    "validate_budget_scope",
]

#: Error class of a crawl that spent its budget.
ERROR_CLASS_BUDGET = "budget-exceeded"

#: The connector scope keys that set a crawl's budget.
BUDGET_SCOPE_KEYS = ("requestsPerSecond", "maxRequests", "maxPages", "maxBytes")


@dataclass(frozen=True)
class CrawlBudget:
    """The limits of one crawl.

    Attributes:
        requests_per_second: The most requests per second to one host.
        max_requests: The most requests the crawl makes in total.
        max_pages: The most listing pages it reads.
        max_bytes: The most response bytes it reads in total.
    """

    requests_per_second: float
    max_requests: int
    max_pages: int
    max_bytes: int

    def as_dict(self) -> Dict[str, Any]:
        """The budget in scope-key spelling."""
        return {
            "requestsPerSecond": self.requests_per_second,
            "maxRequests": self.max_requests,
            "maxPages": self.max_pages,
            "maxBytes": self.max_bytes,
        }


@dataclass(frozen=True)
class BudgetLimits:
    """A connector family's budget defaults and hard caps.

    Attributes:
        default: The budget when the scope sets nothing.
        ceiling: The highest value each scope key may take.
    """

    default: CrawlBudget
    ceiling: CrawlBudget


def validate_budget_scope(scope: Mapping[str, Any], limits: BudgetLimits) -> None:
    """Check the budget keys of a connector scope.

    Args:
        scope: The connector scope.
        limits: The family's limits.

    Raises:
        ValueError: A key that is not a number above 0 and at most its ceiling (the message names
            the key and the ceiling; callers wrap it in their own refusal).
    """
    ceilings = limits.ceiling.as_dict()
    for key in BUDGET_SCOPE_KEYS:
        value = scope.get(key)
        if value is None:
            continue
        integral = key != "requestsPerSecond"
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or (integral and not float(value).is_integer())
            or not 0 < value <= ceilings[key]
        ):
            kind = "a whole number" if integral else "a number"
            raise ValueError(f"{key} must be {kind} above 0 and at most {ceilings[key]:g}.")


def budget_from_scope(scope: Mapping[str, Any], limits: BudgetLimits) -> CrawlBudget:
    """The budget a connector scope asks for, its unset keys at the family default.

    Values are clamped to the ceiling, so a scope stored before a ceiling was lowered still runs.

    Args:
        scope: The connector scope (already validated).
        limits: The family's limits.

    Returns:
        The :class:`CrawlBudget`.
    """
    default = limits.default.as_dict()
    ceiling = limits.ceiling.as_dict()
    values: Dict[str, Any] = {}
    for key in BUDGET_SCOPE_KEYS:
        raw = scope.get(key)
        value = raw if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0 else default[key]
        values[key] = min(value, ceiling[key])
    return CrawlBudget(
        requests_per_second=float(values["requestsPerSecond"]),
        max_requests=int(values["maxRequests"]),
        max_pages=int(values["maxPages"]),
        max_bytes=int(values["maxBytes"]),
    )


class CrawlBudgetExceededError(RefreshSourceError):
    """A crawl spent part of its budget.

    Attributes:
        dimension: ``requests``, ``pages`` or ``bytes``.
    """

    def __init__(self, message: str, *, dimension: str) -> None:
        super().__init__(message, error_class=ERROR_CLASS_BUDGET)
        self.dimension = dimension


class HostRateLimiter:
    """Space requests to each host at least ``1 / rate`` seconds apart.

    Args:
        requests_per_second: The most requests per second to one host.
        clock: Monotonic clock (tests).
        sleep: Sleep function (tests).
    """

    def __init__(
        self,
        requests_per_second: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._interval = 1.0 / requests_per_second
        self._clock = clock
        self._sleep = sleep
        self._next: Dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        """Block until a request to ``host`` is allowed, then claim the slot.

        Args:
            host: The request's host (``netloc``).
        """
        with self._lock:
            now = self._clock()
            due = self._next.get(host, now)
            delay = max(0.0, due - now)
            self._next[host] = max(due, now) + self._interval
        if delay:
            self._sleep(delay)


#: Messages per spent dimension (the request one is what registry crawls have always said).
_SPENT = {
    "requests": "The registry crawl used its whole request budget; narrow the scope or lower the page count.",
    "pages": "The registry crawl read its whole page budget.",
    "bytes": "The registry crawl read its whole byte budget.",
}


class CrawlMeter:
    """Spends one crawl's budget.

    Once the request or byte budget is spent the meter is **exhausted** and refuses every further
    request, so a crawl can stop cleanly and checkpoint instead of failing half-way through a step.
    The page budget only ends the *listing* (:meth:`claim_page`): what was listed can still be
    synced with the requests that are left.

    Args:
        budget: The budget.
        limiter: A rate limiter override (tests); by default one at the budget's rate.
    """

    def __init__(self, budget: CrawlBudget, *, limiter: Optional[HostRateLimiter] = None) -> None:
        self.budget = budget
        self._limiter = limiter or HostRateLimiter(budget.requests_per_second)
        self.requests = 0
        self.pages = 0
        self.bytes = 0
        self.exhausted_by: Optional[str] = None
        self.pages_spent = False

    @property
    def exhausted(self) -> bool:
        """Whether the request or byte budget is spent (no further request is allowed)."""
        return self.exhausted_by is not None

    @property
    def requests_left(self) -> int:
        """Requests still allowed."""
        return max(0, self.budget.max_requests - self.requests)

    def _refuse(self, dimension: str) -> CrawlBudgetExceededError:
        if self.exhausted_by is None:
            self.exhausted_by = dimension
        return CrawlBudgetExceededError(_SPENT[dimension], dimension=dimension)

    def claim_request(self, host: str) -> None:
        """Count one request to ``host`` and wait for its rate slot.

        Raises:
            CrawlBudgetExceededError: The budget is spent (nothing is sent).
        """
        if self.exhausted_by is not None:
            raise self._refuse(self.exhausted_by)
        if self.requests >= self.budget.max_requests:
            raise self._refuse("requests")
        self.requests += 1
        self._limiter.wait(host)

    def add_bytes(self, count: int) -> None:
        """Count response bytes; passing the byte budget exhausts the meter for later requests."""
        self.bytes += max(0, int(count))
        if self.bytes > self.budget.max_bytes and self.exhausted_by is None:
            self.exhausted_by = "bytes"

    def claim_page(self) -> None:
        """Count one listing page.

        Raises:
            CrawlBudgetExceededError: The page budget is spent (the meter is not exhausted by it).
        """
        if self.pages >= self.budget.max_pages:
            self.pages_spent = True
            raise CrawlBudgetExceededError(_SPENT["pages"], dimension="pages")
        self.pages += 1

    def report(self) -> Dict[str, Any]:
        """What the crawl spent, for the run summary."""
        return {
            "requests": self.requests,
            "pages": self.pages,
            "bytes": self.bytes,
            "budget": self.budget.as_dict(),
            "exhaustedBy": self.exhausted_by,
            "pageBudgetReached": self.pages_spent,
        }


# ---------------------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CrawlState:
    """A connector's crawl checkpoint (``apiome.catalog_connector_crawl_state``).

    Attributes:
        cursor: In a full pass, the last item settled, in the crawl's order; ``None`` when no full
            pass is in progress.
        pass_started_at: When the full pass in progress began.
        last_full_pass_at: When the last full pass finished.
        watermark: The incremental watermark (for Confluent, the highest global schema id seen).
        probe_supported: Whether the registry answers the incremental probe (``None``: not tried).
        extra: Crawl-specific state.
    """

    cursor: Optional[str] = None
    pass_started_at: Optional[datetime] = None
    last_full_pass_at: Optional[datetime] = None
    watermark: Optional[int] = None
    probe_supported: Optional[bool] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def with_changes(self, **changes: Any) -> "CrawlState":
        """A copy with ``changes`` applied."""
        return replace(self, **changes)


def load_crawl_state(db: Any, connector_id: str) -> CrawlState:
    """The connector's checkpoint, or an empty one when it has none."""
    rows = db.execute_query(
        """
        SELECT cursor, pass_started_at, last_full_pass_at, watermark, probe_supported, extra
        FROM apiome.catalog_connector_crawl_state
        WHERE connector_id = %s::uuid
        """,
        (connector_id,),
    )
    if not rows:
        return CrawlState()
    row = rows[0]
    return CrawlState(
        cursor=row.get("cursor"),
        pass_started_at=row.get("pass_started_at"),
        last_full_pass_at=row.get("last_full_pass_at"),
        watermark=int(row["watermark"]) if row.get("watermark") is not None else None,
        probe_supported=row.get("probe_supported"),
        extra=dict(row.get("extra") or {}),
    )


def save_crawl_state(db: Any, connector_id: str, state: CrawlState) -> None:
    """Write the connector's checkpoint (create or replace)."""
    import json

    db.execute_query(
        """
        INSERT INTO apiome.catalog_connector_crawl_state
            (connector_id, cursor, pass_started_at, last_full_pass_at, watermark, probe_supported, extra, updated_at)
        VALUES (%s::uuid, %s, %s, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP)
        ON CONFLICT (connector_id) DO UPDATE SET
            cursor = EXCLUDED.cursor,
            pass_started_at = EXCLUDED.pass_started_at,
            last_full_pass_at = EXCLUDED.last_full_pass_at,
            watermark = EXCLUDED.watermark,
            probe_supported = EXCLUDED.probe_supported,
            extra = EXCLUDED.extra,
            updated_at = CURRENT_TIMESTAMP
        RETURNING connector_id
        """,
        (
            connector_id,
            state.cursor,
            state.pass_started_at,
            state.last_full_pass_at,
            state.watermark,
            state.probe_supported,
            json.dumps(state.extra),
        ),
    )
