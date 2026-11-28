"""The what-is-where board and the environment history — PFX-8.13 (#7310).

What the **Environments** page's two views read:

* :func:`read_board` — **Board**: pacticipants down, environments across (non-production first,
  production last), each cell the version(s) running there with can-i-deploy's verdict for them
  (the dot), and — where the environment to its left runs a newer version — whether that version
  *can go next*. A last column lists the releases each pacticipant has supported.

  Every verdict is :func:`app.pact_deployments.verdict_for`, the one the deploy simulator asks, so
  a cell and the simulator can never disagree about the same version and environment.

  **Bounded.** The contents are the PFX-5.7 topology (two reads capped at
  :data:`~app.pact_deployments.MAX_TOPOLOGY_ROWS`) plus one read of the pacticipants with nothing
  anywhere (capped at :data:`MAX_IDLE_ROWS`); at most :data:`MAX_BOARD_CHECKS` verdicts are asked.
  A verdict past the cap, or one the matrix refused, is returned with ``checked: false`` and the
  reason — nothing is dropped.

* :func:`list_history` — **History**: every deployment, undeployment, release and end of support in
  the workspace, newest first, with who did it and (V455) can-i-deploy's answer when it was recorded.
  A replacement is told once, on the deployment that replaced the old one (``replaces``). One page
  at a time: four index-ordered reads of at most ``limit + 1`` rows each, merged.

**Everything starts from the caller's tenant.** Every read filters on ``tenant_id``.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .pact_deployments import (
    Check,
    TopologyEntry,
    environment_by_name,
    read_topology,
    verdict_for,
)
from .pact_environment import EnvironmentRecord
from .pact_environment_store import list_environments
from .pact_publication import PactPublicationError
from .pacticipant import PacticipantValidationError
from .pacticipant_store import get_pacticipant
from .revision_deprecation import is_uuid_string

__all__ = [
    "CODE_HISTORY_CURSOR_INVALID",
    "DEFAULT_HISTORY_PAGE",
    "EVENT_DEPLOYED",
    "EVENT_RELEASED",
    "EVENT_SUPPORT_ENDED",
    "EVENT_UNDEPLOYED",
    "IDLE_SQL",
    "MAX_BOARD_CHECKS",
    "MAX_HISTORY_PAGE",
    "MAX_IDLE_ROWS",
    "Board",
    "BoardCell",
    "BoardNext",
    "BoardRelease",
    "BoardRow",
    "BoardVersion",
    "HistoryEvent",
    "HistoryPage",
    "board_order",
    "decode_history_cursor",
    "encode_history_cursor",
    "history_sql",
    "list_history",
    "next_candidate",
    "read_board",
]

#: The most verdicts one board read asks (each is one matrix query).
MAX_BOARD_CHECKS = 100
#: The most pacticipants with nothing deployed or released anywhere a board lists.
MAX_IDLE_ROWS = 50

#: An unreadable history ``cursor`` (400).
CODE_HISTORY_CURSOR_INVALID = "pact-history-cursor-invalid"
DEFAULT_HISTORY_PAGE = 25
MAX_HISTORY_PAGE = 50

EVENT_DEPLOYED = "deployed"
EVENT_UNDEPLOYED = "undeployed"
EVENT_RELEASED = "released"
EVENT_SUPPORT_ENDED = "support-ended"

#: Why a verdict was not asked.
_OVER_LIMIT = f"Only {MAX_BOARD_CHECKS} versions are checked per board; open the deploy simulator for this one."

# ---------------------------------------------------------------------------------------------
# Board — the pure part
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BoardVersion:
    """One version running in one environment (every instance it runs in).

    Attributes:
        version_number: The version.
        version_seq: Its recording order (newer is larger).
        application_instances: The instances it runs in; ``None`` is the unnamed one.
        deployed_at: When it was last recorded there.
        check: Its can-i-deploy verdict for the environment, or ``None`` when not asked.
        not_checked: Why it was not asked, when it was not.
    """

    version_number: str
    version_seq: int
    application_instances: Tuple[Optional[str], ...]
    deployed_at: Optional[str]
    check: Optional[Check] = None
    not_checked: Optional[str] = None


@dataclass(frozen=True)
class BoardNext:
    """The version that could move into an environment next.

    Attributes:
        version_number: The candidate (running in ``from_environment``, newer than anything here).
        from_environment: The name of the environment it runs in — the nearest one to the left.
        check: Its can-i-deploy verdict for this environment (the simulator's answer), or ``None``.
        not_checked: Why it was not asked, when it was not.
    """

    version_number: str
    from_environment: str
    check: Optional[Check] = None
    not_checked: Optional[str] = None


@dataclass(frozen=True)
class BoardCell:
    """What one pacticipant has in one environment.

    Attributes:
        environment_id: The environment (the board's column).
        deployed: The versions running there, newest first.
        next: The version that could go next, if any.
    """

    environment_id: str
    deployed: List[BoardVersion] = field(default_factory=list)
    next: Optional[BoardNext] = None


@dataclass(frozen=True)
class BoardRelease:
    """A release a pacticipant has supported.

    Attributes:
        version_number: The released version.
        environment_name: Where it is released.
        released_at: When it was recorded.
        check: Its can-i-deploy verdict for that environment, or ``None``.
        not_checked: Why it was not asked, when it was not.
    """

    version_number: str
    environment_name: str
    released_at: Optional[str]
    check: Optional[Check] = None
    not_checked: Optional[str] = None


@dataclass(frozen=True)
class BoardRow:
    """One pacticipant's row.

    Attributes:
        pacticipant_slug: Its handle.
        pacticipant_name: Its name.
        cells: One per environment, in the board's order.
        released: Its supported releases, newest first.
    """

    pacticipant_slug: str
    pacticipant_name: str
    cells: List[BoardCell]
    released: List[BoardRelease]

    @property
    def idle(self) -> bool:
        """Whether nothing of it is deployed or released anywhere."""
        return not self.released and not any(cell.deployed for cell in self.cells)


@dataclass(frozen=True)
class Board:
    """The what-is-where board.

    Attributes:
        environments: The columns, non-production first, production last.
        rows: One per pacticipant, by name.
        truncated: Whether a read stopped at its cap (the topology, or the idle pacticipants).
        checks: How many verdicts were asked.
        not_checked: How many were not (over :data:`MAX_BOARD_CHECKS`, or refused).
        evaluated_at: When the state was read.
    """

    environments: List[EnvironmentRecord]
    rows: List[BoardRow]
    truncated: bool
    checks: int
    not_checked: int
    evaluated_at: str


def board_order(environments: Sequence[EnvironmentRecord]) -> List[EnvironmentRecord]:
    """The board's columns: the order versions are promoted in — non-production, then production.

    Within each group the environments keep their order (by name), so ``development`` comes before
    ``staging``.

    Args:
        environments: The workspace's environments.

    Returns:
        The same environments, reordered.
    """
    return [e for e in environments if not e.production] + [e for e in environments if e.production]


def next_candidate(cells: Sequence[Sequence[BoardVersion]], index: int) -> Optional[Tuple[BoardVersion, int]]:
    """The version that could go next into column ``index``: the newest version in the nearest
    column to its left that runs this pacticipant at all, when it is newer than everything here.

    Promotion flows left to right, so a version that skipped a column (a hotfix straight to
    production) is not offered back to the columns before it, and a column stops the search even
    when what it runs is not newer — that column is the gate the next version passes first.

    Args:
        cells: The pacticipant's running versions per column, each newest first.
        index: The column.

    Returns:
        ``(version, column)``, or ``None``.
    """
    here = cells[index]
    newest_here = max((v.version_seq for v in here), default=None)
    for left in range(index - 1, -1, -1):
        if not cells[left]:
            continue
        candidate = max(cells[left], key=lambda v: v.version_seq)
        if newest_here is None or candidate.version_seq > newest_here:
            return candidate, left
        return None
    return None


def _group(entries: Sequence[TopologyEntry]) -> List[BoardVersion]:
    """One :class:`BoardVersion` per version (its instances together), newest first."""
    grouped: Dict[str, BoardVersion] = {}
    for entry in entries:
        found = grouped.get(entry.version_number)
        if found is None:
            grouped[entry.version_number] = BoardVersion(
                entry.version_number, entry.version_seq, (entry.application_instance,), entry.recorded_at
            )
        else:
            grouped[entry.version_number] = BoardVersion(
                found.version_number,
                found.version_seq,
                found.application_instances + (entry.application_instance,),
                found.deployed_at,
            )
    return sorted(grouped.values(), key=lambda v: v.version_seq, reverse=True)


# ---------------------------------------------------------------------------------------------
# Board — reading and asking
# ---------------------------------------------------------------------------------------------

#: The pacticipants with nothing deployed or released anywhere (a row of dashes and "Record its
#: first deployment"), by name, at most ``limit``. apiome-db plan-check: ``pact.environment_board_idle``.
IDLE_SQL = """
    SELECT p.slug, p.name
    FROM apiome.pacticipant p
    WHERE p.tenant_id = %s::uuid AND p.deleted_at IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM apiome.deployed_version d
          WHERE d.pacticipant_id = p.id AND d.tenant_id = p.tenant_id AND d.currently_deployed)
      AND NOT EXISTS (
          SELECT 1 FROM apiome.released_version r
          WHERE r.pacticipant_id = p.id AND r.tenant_id = p.tenant_id AND r.currently_supported)
    ORDER BY p.name, p.slug
    LIMIT %s
"""


class _Asker:
    """Asks verdicts until :data:`MAX_BOARD_CHECKS`, then says why it stopped."""

    def __init__(self, db: Any, tenant_id: str, limit: int) -> None:
        """Bind the database, the tenant and the budget."""
        self.db = db
        self.tenant_id = tenant_id
        self.left = limit
        self.asked = 0
        self.skipped = 0

    def ask(self, slug: str, version: str, environment: str) -> Tuple[Optional[Check], Optional[str]]:
        """One verdict, or ``(None, reason)``."""
        if self.left <= 0:
            self.skipped += 1
            return None, _OVER_LIMIT
        self.left -= 1
        self.asked += 1
        try:
            return verdict_for(self.db, self.tenant_id, slug, version, environment), None
        except (PactPublicationError, PacticipantValidationError) as exc:
            self.skipped += 1
            return None, str(exc)


def read_board(db: Any, tenant_id: str, *, max_checks: int = MAX_BOARD_CHECKS) -> Board:
    """Read the what-is-where board.

    Verdicts are asked row by row (by pacticipant name), each row's columns left to right — running
    versions, then the next candidate — then its releases, until ``max_checks``.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        max_checks: The most verdicts to ask.

    Returns:
        The board.
    """
    evaluated_at = datetime.now(timezone.utc).isoformat()
    topology = read_topology(db, tenant_id)
    environments = board_order(topology.environments)
    column = {environment.id: index for index, environment in enumerate(environments)}
    names = {environment.id: environment.name for environment in environments}

    deployed: Dict[str, Dict[int, List[TopologyEntry]]] = {}
    released: Dict[str, List[TopologyEntry]] = {}
    label: Dict[str, str] = {}
    for entry in topology.deployed:
        if entry.environment_id in column:
            deployed.setdefault(entry.pacticipant_slug, {}).setdefault(column[entry.environment_id], []).append(entry)
            label[entry.pacticipant_slug] = entry.pacticipant_name
    for entry in topology.released:
        if entry.environment_id in column:
            released.setdefault(entry.pacticipant_slug, []).append(entry)
            label[entry.pacticipant_slug] = entry.pacticipant_name

    idle_rows = db.execute_query(IDLE_SQL, (tenant_id, MAX_IDLE_ROWS + 1)) or []
    for row in idle_rows[:MAX_IDLE_ROWS]:
        label.setdefault(row["slug"], row["name"])

    asker = _Asker(db, tenant_id, max_checks)
    rows: List[BoardRow] = []
    for slug in sorted(label, key=lambda s: (label[s], s)):
        per_column = [_group(deployed.get(slug, {}).get(i, [])) for i in range(len(environments))]
        cells: List[BoardCell] = []
        for index, environment in enumerate(environments):
            running = []
            for version in per_column[index]:
                check, reason = asker.ask(slug, version.version_number, environment.name)
                running.append(
                    BoardVersion(
                        version.version_number,
                        version.version_seq,
                        version.application_instances,
                        version.deployed_at,
                        check,
                        reason,
                    )
                )
            candidate = next_candidate(per_column, index)
            following: Optional[BoardNext] = None
            if candidate is not None:
                version, left = candidate
                check, reason = asker.ask(slug, version.version_number, environment.name)
                following = BoardNext(version.version_number, environments[left].name, check, reason)
            cells.append(BoardCell(environment.id, running, following))
        releases = []
        for entry in released.get(slug, []):
            environment_name = names[entry.environment_id]
            check, reason = asker.ask(slug, entry.version_number, environment_name)
            releases.append(BoardRelease(entry.version_number, environment_name, entry.recorded_at, check, reason))
        rows.append(BoardRow(slug, label[slug], cells, releases))

    return Board(
        environments=environments,
        rows=rows,
        truncated=topology.truncated or len(idle_rows) > MAX_IDLE_ROWS,
        checks=asker.asked,
        not_checked=asker.skipped,
        evaluated_at=evaluated_at,
    )


# ---------------------------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class HistoryEvent:
    """One thing that happened in an environment.

    Attributes:
        kind: ``deployed``, ``undeployed``, ``released`` or ``support-ended``.
        id: The deployment's or release's ``uuid``.
        at: When it happened (ISO 8601).
        pacticipant_slug: The pacticipant's handle.
        pacticipant_name: Its name.
        version_number: The version.
        environment: The environment.
        application_instance: The instance (deployments only).
        actor: Who recorded it, when known.
        verdict: can-i-deploy's answer when it was recorded (``deployed`` / ``released`` only; V455):
            ``deployable``, ``not-deployable``, ``unknown``, or ``None`` when not known.
        replaces: The version this deployment replaced in the same instance, if any.
    """

    kind: str
    id: str
    at: str
    pacticipant_slug: str
    pacticipant_name: str
    version_number: str
    environment: EnvironmentRecord
    application_instance: Optional[str] = None
    actor: Optional[str] = None
    verdict: Optional[str] = None
    replaces: Optional[str] = None


@dataclass(frozen=True)
class HistoryPage:
    """One page of the history.

    Attributes:
        events: Newest first.
        next_cursor: The ``cursor`` of the next page; ``None`` on the last.
    """

    events: List[HistoryEvent]
    next_cursor: Optional[str]


#: Each event kind: its table alias, its timestamp column, its extra filter, and its columns.
_SOURCES: Dict[str, Dict[str, str]] = {
    EVENT_DEPLOYED: {
        "from": """apiome.deployed_version d
            LEFT JOIN apiome.deployed_version rd ON rd.id = d.replaced_id
            LEFT JOIN apiome.pacticipant_version rv ON rv.id = rd.version_id AND rv.deleted_at IS NULL""",
        "alias": "d",
        "at": "d.created_at",
        "extra": "",
        "columns": "d.application_instance, d.actor_label AS actor, d.recorded_verdict AS verdict, "
        "rv.number AS replaces",
    },
    EVENT_UNDEPLOYED: {
        "from": "apiome.deployed_version d",
        "alias": "d",
        "at": "d.undeployed_at",
        "extra": " AND d.undeployed_at IS NOT NULL AND d.ended_reason IS DISTINCT FROM 'replaced'",
        "columns": "d.application_instance, d.ended_actor_label AS actor, NULL::text AS verdict, "
        "NULL::text AS replaces",
    },
    EVENT_RELEASED: {
        "from": "apiome.released_version d",
        "alias": "d",
        "at": "d.created_at",
        "extra": "",
        "columns": "NULL::text AS application_instance, d.actor_label AS actor, d.recorded_verdict AS verdict, "
        "NULL::text AS replaces",
    },
    EVENT_SUPPORT_ENDED: {
        "from": "apiome.released_version d",
        "alias": "d",
        "at": "d.support_ended_at",
        "extra": " AND d.support_ended_at IS NOT NULL",
        "columns": "NULL::text AS application_instance, d.ended_actor_label AS actor, NULL::text AS verdict, "
        "NULL::text AS replaces",
    },
}

#: The order events of one instant are listed in (descending), and the cursor's tie-break.
_KINDS = sorted(_SOURCES)


def encode_history_cursor(event: HistoryEvent) -> str:
    """The ``cursor`` that starts the page after ``event``.

    Args:
        event: The last event of a page.

    Returns:
        URL-safe text.
    """
    raw = f"{event.at}|{event.kind}|{event.id}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_history_cursor(cursor: Optional[str]) -> Optional[Tuple[datetime, str, str]]:
    """Read a history ``cursor``.

    Args:
        cursor: The previous page's ``nextCursor``, or ``None``.

    Returns:
        ``(at, kind, id)``, or ``None``.

    Raises:
        PactPublicationError: ``pact-history-cursor-invalid`` — not a cursor this API gave out.
    """
    if cursor is None:
        return None
    try:
        if len(cursor) > 200:
            raise ValueError("too long")
        text = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("utf-8")
        at, kind, ident = text.split("|")
        moment = datetime.fromisoformat(at)
        if kind not in _SOURCES or not is_uuid_string(ident) or moment.tzinfo is None:
            raise ValueError("bad part")
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise PactPublicationError(
            CODE_HISTORY_CURSOR_INVALID, "cursor is not a cursor this API gave out", pointer="/cursor"
        ) from exc
    return moment, kind, ident


def history_sql(kind: str, *, after_kind: Optional[str], environment: bool, pacticipant: bool) -> str:
    """The read of one event kind's page (also what apiome-db plan-check runs).

    Args:
        kind: The event kind.
        after_kind: The cursor's kind, or ``None`` for the first page. With a cursor ``(at, k, id)``
            the page continues strictly after it in ``(at, kind, id)`` descending order: a kind
            sorting before ``k`` may still use ``at`` itself, the same kind only ids below ``id``.
        environment: Whether an environment filter is applied.
        pacticipant: Whether a pacticipant filter is applied.

    Returns:
        SQL taking ``tenant_id``, [environment id], [pacticipant id], [cursor at[, cursor id]], limit.
    """
    source = _SOURCES[kind]
    alias, at = source["alias"], source["at"]
    where = [f"{alias}.tenant_id = %s::uuid"]
    if environment:
        where.append(f"{alias}.environment_id = %s::uuid")
    if pacticipant:
        where.append(f"{alias}.pacticipant_id = %s::uuid")
    if after_kind is not None:
        if kind < after_kind:
            where.append(f"{at} <= %s")
        elif kind == after_kind:
            where.append(f"({at}, {alias}.id) < (%s, %s::uuid)")
        else:
            where.append(f"{at} < %s")
    return f"""
        SELECT '{kind}' AS kind, {alias}.id::text AS id, {at} AS at, {source["columns"]},
               p.slug AS pacticipant_slug, p.name AS pacticipant_name, v.number AS version_number,
               {alias}.environment_id::text AS environment_id
        FROM {source["from"]}
        JOIN apiome.pacticipant p
          ON p.id = {alias}.pacticipant_id AND p.tenant_id = {alias}.tenant_id AND p.deleted_at IS NULL
        JOIN apiome.pacticipant_version v
          ON v.id = {alias}.version_id AND v.pacticipant_id = {alias}.pacticipant_id AND v.deleted_at IS NULL
        WHERE {" AND ".join(where)}{source["extra"]}
        ORDER BY {at} DESC, {alias}.id DESC
        LIMIT %s
    """


def _iso(value: Any) -> str:
    """A timestamp as ISO 8601 text (timezone-aware values from the database)."""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def list_history(
    db: Any,
    tenant_id: str,
    *,
    environment_name: Optional[str] = None,
    pacticipant_ref: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = DEFAULT_HISTORY_PAGE,
) -> HistoryPage:
    """Read one page of everything that happened in the workspace's environments, newest first.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        environment_name: Only this environment.
        pacticipant_ref: Only this pacticipant (handle, id or name).
        cursor: The previous page's ``next_cursor``.
        limit: The page size, 1 to :data:`MAX_HISTORY_PAGE`.

    Returns:
        The page.

    Raises:
        PactPublicationError: ``pact-environment-not-found``, ``pact-history-cursor-invalid``.
        PacticipantValidationError: ``pacticipant-not-found``.
    """
    after = decode_history_cursor(cursor)
    size = max(1, min(int(limit), MAX_HISTORY_PAGE))
    environments = {e.id: e for e in list_environments(db, tenant_id)}
    environment_id = environment_by_name(db, tenant_id, environment_name).id if environment_name is not None else None
    pacticipant_id = get_pacticipant(db, tenant_id, pacticipant_ref).id if pacticipant_ref is not None else None

    rows: List[Dict[str, Any]] = []
    for kind in _KINDS:
        params: List[Any] = [tenant_id]
        if environment_id is not None:
            params.append(environment_id)
        if pacticipant_id is not None:
            params.append(pacticipant_id)
        if after is not None:
            params.append(after[0])
            if kind == after[1]:
                params.append(after[2])
        params.append(size + 1)
        sql = history_sql(
            kind,
            after_kind=after[1] if after else None,
            environment=environment_id is not None,
            pacticipant=pacticipant_id is not None,
        )
        rows.extend(dict(row) for row in db.execute_query(sql, tuple(params)) or [])

    rows.sort(key=lambda row: (row["at"], row["kind"], row["id"]), reverse=True)
    page = rows[:size]
    events = [
        HistoryEvent(
            kind=row["kind"],
            id=row["id"],
            at=_iso(row["at"]),
            pacticipant_slug=row["pacticipant_slug"],
            pacticipant_name=row["pacticipant_name"],
            version_number=row["version_number"],
            environment=environments[row["environment_id"]],
            application_instance=row.get("application_instance"),
            actor=row.get("actor"),
            verdict=row.get("verdict"),
            replaces=row.get("replaces"),
        )
        for row in page
        if row["environment_id"] in environments
    ]
    next_cursor = encode_history_cursor(events[-1]) if len(rows) > size and events else None
    return HistoryPage(events=events, next_cursor=next_cursor)
