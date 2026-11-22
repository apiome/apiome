"""Per-request SQL statement counter for apiome-rest (DBP-1.1, #7184).

Counts every statement the REST service sends to PostgreSQL, and the time each takes, so that a
request that grows from 5 statements to 5,000 shows up in the access log and fails a test.

How it works:

* :class:`CountingDictCursor` is the cursor class of every pooled connection (``app.database``
  passes it as ``cursor_factory``). Each ``execute`` / ``executemany`` / ``callproc`` call is timed
  and handed to :func:`record`.
* :class:`~app.observability.ObservabilityMiddleware` opens a :class:`StatementStats` for each
  request with :func:`begin_request`. The stats object lives in a :class:`contextvars.ContextVar`;
  FastAPI copies the context into the worker thread of a synchronous handler, and the object is
  mutable, so statements run on that thread are added to the request's own counter.
* :func:`capture` collects every statement in the process while its ``with`` block is open,
  whatever request or thread runs it. Tests use it through :func:`assert_max_queries`.

``executemany`` counts as one call, as the caller sees it: psycopg2 sends one statement per
parameter set, so a loop rewritten as ``executemany`` does not lower the count. Use a multi-row
statement (``execute_values``) to do that.
"""

from __future__ import annotations

import contextvars
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, List, Optional

from psycopg2.extras import RealDictCursor

#: Characters of each statement's text kept by a :func:`capture` for its failure message.
_SQL_PREVIEW_CHARS = 160


@dataclass
class StatementStats:
    """Statements counted for one request or one :func:`capture` block.

    Attributes:
        count: Statements executed.
        total_ms: Their summed wall-clock time, in milliseconds.
        statements: The first characters of each statement's SQL, in order. Only filled when
            ``keep_sql`` is true (captures do, requests do not, so a request costs no memory).
        keep_sql: Whether :meth:`add` keeps the SQL text.
    """

    count: int = 0
    total_ms: float = 0.0
    statements: List[str] = field(default_factory=list)
    keep_sql: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def add(self, elapsed_ms: float, sql: Any = None) -> None:
        """Count one statement.

        Args:
            elapsed_ms: How long the statement took, in milliseconds.
            sql: The statement text (``str`` or ``bytes``), kept only when ``keep_sql`` is set.
        """
        with self._lock:
            self.count += 1
            self.total_ms += elapsed_ms
            if self.keep_sql:
                self.statements.append(_preview(sql))


def _preview(sql: Any) -> str:
    """One line of a statement's SQL, shortened for a failure message."""
    if isinstance(sql, (bytes, bytearray)):
        sql = sql.decode("utf-8", "replace")
    text = " ".join(str(sql or "").split())
    return text if len(text) <= _SQL_PREVIEW_CHARS else text[: _SQL_PREVIEW_CHARS - 1] + "…"


_current: contextvars.ContextVar[Optional[StatementStats]] = contextvars.ContextVar(
    "apiome_statement_stats", default=None
)
_captures: List[StatementStats] = []
_captures_lock = threading.Lock()


def begin_request() -> tuple[StatementStats, contextvars.Token]:
    """Start counting the statements of the current request.

    Returns:
        The request's :class:`StatementStats`, and the token :func:`end_request` needs.
    """
    stats = StatementStats()
    return stats, _current.set(stats)


def end_request(token: contextvars.Token) -> None:
    """Stop counting for the request :func:`begin_request` started.

    Args:
        token: The token :func:`begin_request` returned.
    """
    try:
        _current.reset(token)
    except ValueError:
        # Reset from another context (the middleware's ``finally`` ran on a different task);
        # clearing is the same outcome for the next request on this context.
        _current.set(None)


def current() -> Optional[StatementStats]:
    """The current request's stats, or ``None`` outside a request."""
    return _current.get()


def record(elapsed_ms: float, sql: Any = None) -> None:
    """Add one statement to the current request and to every open :func:`capture`.

    Args:
        elapsed_ms: How long the statement took, in milliseconds.
        sql: The statement text, for captures that keep it.
    """
    stats = _current.get()
    if stats is not None:
        stats.add(elapsed_ms, sql)
    if _captures:
        with _captures_lock:
            open_captures = list(_captures)
        for capture_stats in open_captures:
            capture_stats.add(elapsed_ms, sql)


@contextmanager
def capture() -> Iterator[StatementStats]:
    """Collect every statement the process runs while the block is open.

    Process-wide on purpose: a test client runs the request on another thread and in another
    context, so a context variable set by the test would not see it.

    Yields:
        A :class:`StatementStats` that fills while the block runs (``keep_sql`` is set).
    """
    stats = StatementStats(keep_sql=True)
    with _captures_lock:
        _captures.append(stats)
    try:
        yield stats
    finally:
        with _captures_lock:
            _captures.remove(stats)


class QueryBudgetExceededError(AssertionError):
    """A block ran more statements than its budget allows (raised by :func:`assert_max_queries`)."""


@contextmanager
def assert_max_queries(budget: int, label: str = "block") -> Iterator[StatementStats]:
    """Fail when the block runs more than ``budget`` SQL statements.

    Example::

        with assert_max_queries(6, "GET /v1/projects/{tenant}"):
            client.get(f"/v1/projects/{slug}")

    Args:
        budget: The most statements the block may run (``>= 0``).
        label: What the block is, for the failure message.

    Yields:
        The block's :class:`StatementStats`, so a test can also read ``count`` and ``total_ms``.

    Raises:
        ValueError: ``budget`` is negative.
        QueryBudgetExceededError: The block ran more than ``budget`` statements. The message lists
            them, so the extra ones can be found without rerunning.
    """
    if budget < 0:
        raise ValueError("a statement budget cannot be negative")
    with capture() as stats:
        yield stats
    if stats.count > budget:
        listing = "\n".join(f"  {i + 1:>3}. {sql}" for i, sql in enumerate(stats.statements))
        raise QueryBudgetExceededError(
            f"{label} ran {stats.count} SQL statements; its budget is {budget}.\n{listing}"
        )


class CountingDictCursor(RealDictCursor):
    """A :class:`RealDictCursor` that reports each statement to :func:`record`.

    Behaves exactly like its parent: rows are dicts and errors propagate. A failed statement is
    still counted, because it still cost a round trip.
    """

    def execute(self, query: Any, vars: Any = None) -> Any:  # noqa: A002 - psycopg2's name
        start = time.perf_counter()
        try:
            return super().execute(query, vars)
        finally:
            record((time.perf_counter() - start) * 1000.0, query)

    def executemany(self, query: Any, vars_list: Any) -> Any:
        start = time.perf_counter()
        try:
            return super().executemany(query, vars_list)
        finally:
            record((time.perf_counter() - start) * 1000.0, query)

    def callproc(self, procname: Any, parameters: Any = None) -> Any:
        start = time.perf_counter()
        try:
            return super().callproc(procname, parameters)
        finally:
            record((time.perf_counter() - start) * 1000.0, f"CALL {procname}")
