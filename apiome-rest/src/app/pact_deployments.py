"""Environments and deployments: the topology, the history and the deploy simulator — PFX-5.7 (#6951).

What the **Environments** pages of the Contracts workspace read, beside the Pact Broker's
environment routes (PFX-1.5):

* :func:`read_topology` — every environment of the workspace with what is deployed to it now and
  the releases it supports: the dashboard's grid of pacticipants × environments.
* :func:`list_deployment_history` — every deployment recorded to one environment, current or
  replaced, newest first, one page at a time (``seq`` keyset; V446 orders it).
* :func:`simulate_deployment` — *what if this version were deployed there?* The candidate's own
  can-i-deploy verdict, and how the verdict of every version its counterparts have changes:

  - **running** — a counterpart version already in the environment: does it stay deployable, or
    would the candidate *break* it (or *fix* it)?
  - **pending** — a counterpart version deployed somewhere else (staging, say) but not here yet:
    would the candidate *clear* its way here (the predicted-clear look-ahead), or *block* it?

  Each answer is two calls of the one verdict function (:func:`app.pact_matrix.deployment_verdict`)
  — once against the environment as recorded, once with the candidate swapped in for the version
  it replaces — so the simulator can never disagree with ``can-i-deploy``.

**Nothing is dropped.** A counterpart version past :data:`MAX_SIMULATED_CHECKS`, or one whose
check was refused, is listed in ``not_checked`` with the reason.

**Read only.** The simulator records nothing; it answers from the state at ``evaluated_at``.

**Everything starts from the caller's tenant.** Every read filters on ``tenant_id``; pacticipants
are resolved through :func:`app.pacticipant_store.get_pacticipant`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlencode

from .pact_environment import CODE_ENVIRONMENT_NOT_FOUND, EnvironmentRecord
from .pact_environment_store import get_environment, list_environments
from .pact_matrix import Verdict, deployment_verdict, parse_can_i_deploy_query
from .pact_matrix_store import query_matrix
from .pact_publication import PactPublicationError
from .pacticipant import PacticipantRecord, PacticipantValidationError
from .pacticipant_store import get_pacticipant, get_version

__all__ = [
    "CODE_DEPLOYMENT_CURSOR_INVALID",
    "CODE_SIMULATION_INVALID",
    "DEFAULT_HISTORY_PAGE",
    "EFFECT_BLOCKS",
    "EFFECT_BREAKS",
    "EFFECT_CHANGES",
    "EFFECT_CLEARS",
    "EFFECT_FIXES",
    "EFFECT_UNCHANGED",
    "MAX_HISTORY_PAGE",
    "MAX_SIMULATED_CHECKS",
    "MAX_TOPOLOGY_ROWS",
    "PLACEMENT_PENDING",
    "PLACEMENT_RUNNING",
    "VERDICT_DEPLOYABLE",
    "VERDICT_NOT_DEPLOYABLE",
    "VERDICT_UNKNOWN",
    "Check",
    "HistoryEntry",
    "HistoryPage",
    "Impact",
    "NotChecked",
    "Placement",
    "Simulation",
    "Topology",
    "TopologyEntry",
    "classify_effect",
    "decode_history_cursor",
    "environment_by_name",
    "list_deployment_history",
    "plan_checks",
    "read_topology",
    "simulate_deployment",
    "validate_application_instance",
    "verdict_for",
    "verdict_when_recorded",
    "verdict_word",
]

#: An unreadable ``cursor`` (400).
CODE_DEPLOYMENT_CURSOR_INVALID = "pact-deployment-cursor-invalid"
#: A simulation the request cannot describe — a malformed application instance (400).
CODE_SIMULATION_INVALID = "pact-simulation-invalid"

#: The history's default and largest page.
DEFAULT_HISTORY_PAGE = 25
MAX_HISTORY_PAGE = 50

#: The most current deployments (and, separately, supported releases) the topology reads; past it
#: the answer says it is ``truncated``.
MAX_TOPOLOGY_ROWS = 2000

#: The most counterpart versions one simulation checks (each check is two matrix queries).
MAX_SIMULATED_CHECKS = 20

#: The longest environment name or application instance accepted (the columns are 255 wide).
_MAX_TEXT = 255

PLACEMENT_RUNNING = "running"
PLACEMENT_PENDING = "pending"

EFFECT_UNCHANGED = "unchanged"
#: A running version that is deployable now and would not be.
EFFECT_BREAKS = "breaks"
#: A running version that is not deployable now and would be.
EFFECT_FIXES = "fixes"
#: A pending version that cannot come here now and could.
EFFECT_CLEARS = "clears"
#: A pending version that could come here now and could not.
EFFECT_BLOCKS = "blocks"
#: The verdict moves between *no* and *not known yet*.
EFFECT_CHANGES = "changes"

_INSTANCE = re.compile(r"^[^\x00-\x1f\x7f]+$")


def _iso(value: Any) -> Optional[str]:
    """A timestamp as ISO 8601 text."""
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


# ---------------------------------------------------------------------------------------------
# Lookups and validation
# ---------------------------------------------------------------------------------------------


def environment_by_name(db: Any, tenant_id: str, name: str) -> EnvironmentRecord:
    """The tenant's environment with exactly this name.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        name: The environment's name (what tooling uses, ``production``).

    Returns:
        The environment.

    Raises:
        PactPublicationError: ``pact-environment-not-found`` — no such environment in the workspace
            (also for an empty or over-long name, which no environment can have).
    """
    text = (name or "").strip()
    found = list_environments(db, tenant_id, name=text) if text and len(text) <= _MAX_TEXT else []
    if not found:
        raise PactPublicationError(
            CODE_ENVIRONMENT_NOT_FOUND, f"This workspace has no environment named '{text}'", pointer="/environment"
        )
    return found[0]


def validate_application_instance(value: Optional[str]) -> Optional[str]:
    """Check an application instance named in a request.

    Args:
        value: The instance, or ``None`` for the environment's unnamed one.

    Returns:
        The instance, or ``None``.

    Raises:
        PactPublicationError: ``pact-simulation-invalid`` — empty, padded with spaces, over 255
            characters or carrying a control character (what the column refuses).
    """
    if value is None:
        return None
    if not value or value != value.strip() or len(value) > _MAX_TEXT or not _INSTANCE.match(value):
        raise PactPublicationError(
            CODE_SIMULATION_INVALID,
            "applicationInstance must be 1–255 characters with no surrounding spaces or control characters",
            pointer="/applicationInstance",
        )
    return value


def decode_history_cursor(cursor: Optional[str]) -> Optional[int]:
    """Read a history ``cursor`` (the ``nextCursor`` of the previous page).

    Args:
        cursor: The cursor, or ``None`` for the first page.

    Returns:
        The position the page starts after, or ``None``.

    Raises:
        PactPublicationError: ``pact-deployment-cursor-invalid`` — not a cursor this API gave out.
    """
    if cursor is None:
        return None
    if not cursor.isdigit() or len(cursor) > 19 or int(cursor) <= 0:
        raise PactPublicationError(
            CODE_DEPLOYMENT_CURSOR_INVALID, "cursor is not a cursor this API gave out", pointer="/cursor"
        )
    return int(cursor)


# ---------------------------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TopologyEntry:
    """One pacticipant version in an environment now.

    Attributes:
        environment_id: The environment.
        pacticipant_slug: The pacticipant's handle.
        pacticipant_name: Its display name.
        version_number: The version.
        application_instance: The instance (deployments only; ``None`` for the unnamed one).
        recorded_at: When the deployment or release was recorded.
        version_seq: The version's place in the order its pacticipant's versions were recorded
            (newer is larger) — how the board tells which version is newer.
    """

    environment_id: str
    pacticipant_slug: str
    pacticipant_name: str
    version_number: str
    application_instance: Optional[str]
    recorded_at: Optional[str]
    version_seq: int = 0


@dataclass(frozen=True)
class Topology:
    """Every environment and what is in it.

    Attributes:
        environments: The environments, by name.
        deployed: The current deployments, by pacticipant name then newest first.
        released: The currently supported releases, the same order.
        truncated: Whether either list stopped at :data:`MAX_TOPOLOGY_ROWS`.
    """

    environments: List[EnvironmentRecord]
    deployed: List[TopologyEntry]
    released: List[TopologyEntry]
    truncated: bool


_TOPOLOGY_DEPLOYED = """
    SELECT d.environment_id::text AS environment_id, p.slug AS pacticipant_slug, p.name AS pacticipant_name,
           v.number AS version_number, v.seq AS version_seq, d.application_instance, d.created_at AS recorded_at
    FROM apiome.deployed_version d
    JOIN apiome.pacticipant p ON p.id = d.pacticipant_id AND p.tenant_id = d.tenant_id AND p.deleted_at IS NULL
    JOIN apiome.pacticipant_version v
      ON v.id = d.version_id AND v.pacticipant_id = d.pacticipant_id AND v.deleted_at IS NULL
    WHERE d.tenant_id = %s::uuid AND d.currently_deployed
    ORDER BY p.name, p.slug, d.seq DESC
    LIMIT %s
"""

_TOPOLOGY_RELEASED = """
    SELECT r.environment_id::text AS environment_id, p.slug AS pacticipant_slug, p.name AS pacticipant_name,
           v.number AS version_number, v.seq AS version_seq, NULL::text AS application_instance,
           r.created_at AS recorded_at
    FROM apiome.released_version r
    JOIN apiome.pacticipant p ON p.id = r.pacticipant_id AND p.tenant_id = r.tenant_id AND p.deleted_at IS NULL
    JOIN apiome.pacticipant_version v
      ON v.id = r.version_id AND v.pacticipant_id = r.pacticipant_id AND v.deleted_at IS NULL
    WHERE r.tenant_id = %s::uuid AND r.currently_supported
    ORDER BY p.name, p.slug, r.seq DESC
    LIMIT %s
"""


def _topology_entries(db: Any, query: str, tenant_id: str) -> Tuple[List[TopologyEntry], bool]:
    """Run one topology read; the entries and whether there were more than the limit."""
    rows = db.execute_query(query, (tenant_id, MAX_TOPOLOGY_ROWS + 1)) or []
    entries = [
        TopologyEntry(
            environment_id=str(row["environment_id"]),
            pacticipant_slug=row["pacticipant_slug"],
            pacticipant_name=row["pacticipant_name"],
            version_number=row["version_number"],
            application_instance=row.get("application_instance"),
            recorded_at=_iso(row.get("recorded_at")),
            version_seq=int(row.get("version_seq") or 0),
        )
        for row in rows[:MAX_TOPOLOGY_ROWS]
    ]
    return entries, len(rows) > MAX_TOPOLOGY_ROWS


def read_topology(db: Any, tenant_id: str) -> Topology:
    """Read every environment of the workspace and what is deployed and released to each now.

    Args:
        db: The database.
        tenant_id: The caller's tenant.

    Returns:
        The topology.
    """
    deployed, more_deployed = _topology_entries(db, _TOPOLOGY_DEPLOYED, tenant_id)
    released, more_released = _topology_entries(db, _TOPOLOGY_RELEASED, tenant_id)
    return Topology(
        environments=list_environments(db, tenant_id),
        deployed=deployed,
        released=released,
        truncated=more_deployed or more_released,
    )


# ---------------------------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class HistoryEntry:
    """One deployment recorded to an environment.

    Attributes:
        id: The deployment's ``uuid`` (the broker's deployed-version id).
        pacticipant_slug: The pacticipant's handle.
        pacticipant_name: Its display name.
        version_number: The version deployed.
        application_instance: The instance; ``None`` for the unnamed one.
        currently_deployed: Whether it is still deployed.
        deployed_at: When it was recorded.
        undeployed_at: When it was replaced or undeployed; ``None`` while deployed.
        recorded_by: Who recorded it (the actor label), when known.
    """

    id: str
    pacticipant_slug: str
    pacticipant_name: str
    version_number: str
    application_instance: Optional[str]
    currently_deployed: bool
    deployed_at: Optional[str]
    undeployed_at: Optional[str]
    recorded_by: Optional[str]


@dataclass(frozen=True)
class HistoryPage:
    """One page of an environment's deployment history.

    Attributes:
        environment: The environment.
        deployments: The deployments, newest first.
        next_cursor: The ``cursor`` of the next page; ``None`` on the last.
    """

    environment: EnvironmentRecord
    deployments: List[HistoryEntry]
    next_cursor: Optional[str]


def list_deployment_history(
    db: Any,
    tenant_id: str,
    environment_name: str,
    *,
    pacticipant_ref: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = DEFAULT_HISTORY_PAGE,
) -> HistoryPage:
    """Read one page of every deployment recorded to an environment, current or not, newest first.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        environment_name: The environment's name.
        pacticipant_ref: Only this pacticipant (handle, id or name).
        cursor: The previous page's ``next_cursor``.
        limit: The page size, 1 to :data:`MAX_HISTORY_PAGE`.

    Returns:
        The page.

    Raises:
        PactPublicationError: ``pact-environment-not-found``, ``pact-deployment-cursor-invalid``.
        PacticipantValidationError: ``pacticipant-not-found`` for an unknown ``pacticipant_ref``.
    """
    environment = environment_by_name(db, tenant_id, environment_name)
    after = decode_history_cursor(cursor)
    size = max(1, min(int(limit), MAX_HISTORY_PAGE))
    where = ["d.tenant_id = %s::uuid", "d.environment_id = %s::uuid"]
    params: List[Any] = [tenant_id, environment.id]
    if pacticipant_ref is not None:
        where.append("d.pacticipant_id = %s::uuid")
        params.append(get_pacticipant(db, tenant_id, pacticipant_ref).id)
    if after is not None:
        where.append("d.seq < %s")
        params.append(after)
    params.append(size + 1)
    rows = (
        db.execute_query(
            f"""
            SELECT d.id::text AS id, d.seq, d.application_instance, d.currently_deployed, d.undeployed_at,
                   d.created_at, d.actor_label, p.slug AS pacticipant_slug, p.name AS pacticipant_name,
                   v.number AS version_number
            FROM apiome.deployed_version d
            JOIN apiome.pacticipant p
              ON p.id = d.pacticipant_id AND p.tenant_id = d.tenant_id AND p.deleted_at IS NULL
            JOIN apiome.pacticipant_version v
              ON v.id = d.version_id AND v.pacticipant_id = d.pacticipant_id AND v.deleted_at IS NULL
            WHERE {" AND ".join(where)}
            ORDER BY d.seq DESC
            LIMIT %s
            """,
            tuple(params),
        )
        or []
    )
    page = rows[:size]
    entries = [
        HistoryEntry(
            id=row["id"],
            pacticipant_slug=row["pacticipant_slug"],
            pacticipant_name=row["pacticipant_name"],
            version_number=row["version_number"],
            application_instance=row.get("application_instance"),
            currently_deployed=bool(row["currently_deployed"]),
            deployed_at=_iso(row.get("created_at")),
            undeployed_at=_iso(row.get("undeployed_at")),
            recorded_by=row.get("actor_label"),
        )
        for row in page
    ]
    next_cursor = str(page[-1]["seq"]) if len(rows) > size and page else None
    return HistoryPage(environment=environment, deployments=entries, next_cursor=next_cursor)


# ---------------------------------------------------------------------------------------------
# The simulator — the pure part
# ---------------------------------------------------------------------------------------------


def classify_effect(placement: str, before: Optional[bool], after: Optional[bool]) -> str:
    """Say what deploying the candidate does to one counterpart version's verdict.

    Args:
        placement: :data:`PLACEMENT_RUNNING` (already in the environment) or
            :data:`PLACEMENT_PENDING` (elsewhere, not here yet).
        before: Its verdict against the environment as recorded (``None``: not known yet).
        after: Its verdict with the candidate deployed.

    Returns:
        :data:`EFFECT_UNCHANGED` when the verdict stays; for a running version
        :data:`EFFECT_BREAKS` (was deployable, would not be) or :data:`EFFECT_FIXES` (would become
        deployable); for a pending one :data:`EFFECT_BLOCKS` or :data:`EFFECT_CLEARS`; and
        :data:`EFFECT_CHANGES` for a move between *no* and *not known yet*.
    """
    if before is after:
        return EFFECT_UNCHANGED
    running = placement == PLACEMENT_RUNNING
    if after is True:
        return EFFECT_FIXES if running else EFFECT_CLEARS
    if before is True:
        return EFFECT_BREAKS if running else EFFECT_BLOCKS
    return EFFECT_CHANGES


@dataclass(frozen=True)
class Placement:
    """A counterpart version the simulation could check.

    Attributes:
        pacticipant_id: The counterpart.
        pacticipant_slug: Its handle.
        pacticipant_name: Its display name.
        version_number: The version.
        placement: ``running`` or ``pending``.
        environments: For a pending version, the environments it is deployed to now.
    """

    pacticipant_id: str
    pacticipant_slug: str
    pacticipant_name: str
    version_number: str
    placement: str
    environments: Tuple[str, ...] = ()


def plan_checks(
    placements: Sequence[Placement], limit: int = MAX_SIMULATED_CHECKS
) -> Tuple[List[Placement], List[Placement]]:
    """Choose which counterpart versions to check: running ones first, then pending, each by name.

    Args:
        placements: Every candidate check (a version appears once per pacticipant and placement).
        limit: The most to check.

    Returns:
        ``(checked, over_limit)`` — nothing is dropped: what is not checked is returned.
    """
    ordered = sorted(
        placements,
        key=lambda p: (0 if p.placement == PLACEMENT_RUNNING else 1, p.pacticipant_name, p.pacticipant_slug),
    )
    return ordered[:limit], ordered[limit:]


# ---------------------------------------------------------------------------------------------
# The simulator — reading and evaluating
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    """One verdict, as the simulation reports it.

    Attributes:
        deployable: ``True``, ``False`` or ``None`` (not known yet).
        reasons: The verdict's reasons (``type``, ``code``, ``text``).
        counts: ``success``, ``failed``, ``unknown``.
    """

    deployable: Optional[bool]
    reasons: List[Dict[str, str]]
    counts: Dict[str, int]

    @staticmethod
    def of(verdict: Verdict) -> "Check":
        """Adapt a :class:`~app.pact_matrix.Verdict`."""
        return Check(
            deployable=verdict.deployable,
            reasons=[{"type": r.type, "code": r.code, "text": r.text} for r in verdict.reasons],
            counts=dict(verdict.counts),
        )


@dataclass(frozen=True)
class Impact:
    """How the candidate changes one counterpart version's verdict.

    Attributes:
        placement: The version checked.
        roles: ``consumer`` and/or ``provider`` — the counterpart's side of its integration with the
            candidate's pacticipant.
        before: Its verdict now.
        after: Its verdict with the candidate deployed.
        effect: :func:`classify_effect`'s answer.
    """

    placement: Placement
    roles: Tuple[str, ...]
    before: Check
    after: Check
    effect: str


@dataclass(frozen=True)
class NotChecked:
    """A counterpart version the simulation did not check, and why.

    Attributes:
        placement: The version.
        code: ``pact-simulation-over-limit`` or the refusal's code.
        reason: The sentence.
    """

    placement: Placement
    code: str
    reason: str


@dataclass(frozen=True)
class Simulation:
    """The answer to *what if this version were deployed there?*

    Attributes:
        environment: The environment.
        pacticipant: The candidate's pacticipant.
        version_number: The candidate version.
        application_instance: The instance it would be deployed to (``None``: the unnamed one).
        replaces: The version it would replace in that instance, if any.
        already_deployed: Whether the candidate is already deployed there (nothing would change).
        verdict: The candidate's own can-i-deploy verdict.
        impacts: Each checked counterpart version.
        not_checked: Each counterpart version not checked, with the reason.
        evaluated_at: When the state was read.
    """

    environment: EnvironmentRecord
    pacticipant: PacticipantRecord
    version_number: str
    application_instance: Optional[str]
    replaces: Optional[str]
    already_deployed: bool
    verdict: Check
    impacts: List[Impact] = field(default_factory=list)
    not_checked: List[NotChecked] = field(default_factory=list)
    evaluated_at: str = ""


_COUNTERPARTS = """
    SELECT DISTINCT q.id::text AS id, q.slug, q.name, x.role
    FROM (
        SELECT pp.provider_id AS other_id, 'provider' AS role
        FROM apiome.pact_publication pp WHERE pp.consumer_id = %s::uuid
        UNION
        SELECT pp.consumer_id AS other_id, 'consumer' AS role
        FROM apiome.pact_publication pp WHERE pp.provider_id = %s::uuid
    ) x
    JOIN apiome.pacticipant q ON q.id = x.other_id AND q.tenant_id = %s::uuid AND q.deleted_at IS NULL
    WHERE q.id <> %s::uuid
    ORDER BY q.name, q.slug, x.role
"""

#: Every version of the given pacticipants deployed or supported anywhere now, with the environment.
_PLACED_VERSIONS = """
    SELECT s.pacticipant_id::text AS pacticipant_id, v.id::text AS version_id, v.number, s.environment_id::text
           AS environment_id, e.name AS environment_name, s.application_instance, s.kind, s.seq
    FROM (
        SELECT d.pacticipant_id, d.version_id, d.environment_id, d.application_instance, 'deployed' AS kind, d.seq
        FROM apiome.deployed_version d
        WHERE d.tenant_id = %s::uuid AND d.currently_deployed AND d.pacticipant_id = ANY(%s::uuid[])
        UNION ALL
        SELECT r.pacticipant_id, r.version_id, r.environment_id, NULL, 'released' AS kind, r.seq
        FROM apiome.released_version r
        WHERE r.tenant_id = %s::uuid AND r.currently_supported AND r.pacticipant_id = ANY(%s::uuid[])
    ) s
    JOIN apiome.pacticipant_version v
      ON v.id = s.version_id AND v.pacticipant_id = s.pacticipant_id AND v.deleted_at IS NULL
    JOIN apiome.pact_environment e ON e.id = s.environment_id AND e.tenant_id = %s::uuid
    ORDER BY s.seq DESC
"""


def verdict_for(
    db: Any,
    tenant_id: str,
    pacticipant_slug: str,
    version_number: str,
    environment_name: str,
    override: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Check:
    """One can-i-deploy verdict, read exactly as ``GET /can-i-deploy`` reads it.

    The deploy simulator, the what-is-where board (PFX-8.13) and the verdict stored when a
    deployment or release is recorded all ask through here, so they can never disagree.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        pacticipant_slug: The pacticipant's handle.
        version_number: The version.
        environment_name: The environment's name.
        override: The simulator's hypothetical environment contents, or ``None`` for the recorded ones.

    Returns:
        The verdict.

    Raises:
        PactPublicationError: a query the matrix refuses.
        PacticipantValidationError: an unknown pacticipant or version.
    """
    query = urlencode({"pacticipant": pacticipant_slug, "version": version_number, "toEnvironment": environment_name})
    selectors, options = parse_can_i_deploy_query(query)
    result = query_matrix(db, tenant_id, selectors, options, environment_override=override)
    return Check.of(deployment_verdict(result))


#: The words V455 stores for a verdict (``recorded_verdict``) and the board and history answer.
VERDICT_DEPLOYABLE = "deployable"
VERDICT_NOT_DEPLOYABLE = "not-deployable"
VERDICT_UNKNOWN = "unknown"


def verdict_word(deployable: Optional[bool]) -> str:
    """A verdict as one word.

    Args:
        deployable: can-i-deploy's ``deployable`` (``None``: a verification is still missing).

    Returns:
        :data:`VERDICT_DEPLOYABLE`, :data:`VERDICT_NOT_DEPLOYABLE` or :data:`VERDICT_UNKNOWN`.
    """
    if deployable is True:
        return VERDICT_DEPLOYABLE
    if deployable is False:
        return VERDICT_NOT_DEPLOYABLE
    return VERDICT_UNKNOWN


def verdict_when_recorded(
    db: Any, tenant_id: str, pacticipant_ref: str, version_number: str, environment_id: str
) -> Optional[str]:
    """can-i-deploy's answer for a version and environment, asked just before recording it there.

    ``record-deployment`` and ``record-release`` store it (V455) so the Environments history can
    say whether a version was verified at the time. Recording never depends on it: a question the
    matrix cannot answer (an unknown pacticipant, version or environment — the record call refuses
    those itself) gives ``None``, "not known".

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        pacticipant_ref: The pacticipant's handle, id or name.
        version_number: The version about to be recorded.
        environment_id: The environment's id (the broker routes address it by ``uuid``).

    Returns:
        :func:`verdict_word`'s answer, or ``None``.
    """
    try:
        environment = get_environment(db, tenant_id, environment_id)
        pacticipant = get_pacticipant(db, tenant_id, pacticipant_ref)
        check = verdict_for(db, tenant_id, pacticipant.slug, version_number, environment.name)
    except (PactPublicationError, PacticipantValidationError):
        return None
    return verdict_word(check.deployable)


def _array(ids: Sequence[str]) -> str:
    """A Postgres uuid array literal."""
    return "{" + ",".join(ids) + "}"


def simulate_deployment(
    db: Any,
    tenant_id: str,
    environment_name: str,
    pacticipant_ref: str,
    version_number: str,
    *,
    application_instance: Optional[str] = None,
) -> Simulation:
    """Answer *what if this version were deployed to that environment?* without recording anything.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        environment_name: The environment's name.
        pacticipant_ref: The candidate's pacticipant (handle, id or name).
        version_number: The candidate version.
        application_instance: The instance it would go to; ``None`` for the unnamed one. Only the
            deployment in that instance is replaced, as ``record-deployment`` would.

    Returns:
        The simulation.

    Raises:
        PactPublicationError: ``pact-environment-not-found``, ``pact-simulation-invalid``.
        PacticipantValidationError: ``pacticipant-not-found``, ``pacticipant-version-not-found``.
    """
    instance = validate_application_instance(application_instance)
    environment = environment_by_name(db, tenant_id, environment_name)
    pacticipant = get_pacticipant(db, tenant_id, pacticipant_ref)
    candidate = get_version(db, pacticipant, version_number)
    evaluated_at = datetime.now(timezone.utc).isoformat()

    counterparts = db.execute_query(_COUNTERPARTS, (pacticipant.id, pacticipant.id, tenant_id, pacticipant.id)) or []
    roles: Dict[str, List[str]] = {}
    names: Dict[str, Tuple[str, str]] = {}
    for row in counterparts:
        roles.setdefault(row["id"], []).append(row["role"])
        names[row["id"]] = (row["slug"], row["name"])

    placed = (
        db.execute_query(
            _PLACED_VERSIONS,
            (
                tenant_id,
                _array([pacticipant.id] + list(names)),
                tenant_id,
                _array([pacticipant.id] + list(names)),
                tenant_id,
            ),
        )
        or []
    )

    # The candidate's pacticipant in this environment, as it would be: the deployment in the target
    # instance replaced by the candidate, every other instance and supported release kept.
    hypothetical: Dict[str, Dict[str, Any]] = {candidate.id: {"id": candidate.id, "number": candidate.number}}
    replaces: Optional[str] = None
    already = False
    for row in placed:
        if row["pacticipant_id"] != pacticipant.id or row["environment_id"] != environment.id:
            continue
        in_target = row["kind"] == "deployed" and (row.get("application_instance") or None) == instance
        if in_target:
            replaces = row["number"]
            already = row["version_id"] == candidate.id
            continue
        hypothetical.setdefault(row["version_id"], {"id": row["version_id"], "number": row["number"]})
    override = {pacticipant.id: list(hypothetical.values())}

    placements = _placements(placed, names, environment.id)
    checked, over_limit = plan_checks(placements)

    verdict = verdict_for(db, tenant_id, pacticipant.slug, candidate.number, environment.name)
    impacts: List[Impact] = []
    not_checked = [
        NotChecked(
            placement=p,
            code="pact-simulation-over-limit",
            reason=f"Only {MAX_SIMULATED_CHECKS} counterpart versions are checked per simulation.",
        )
        for p in over_limit
    ]
    for placement in checked:
        try:
            before = verdict_for(db, tenant_id, placement.pacticipant_slug, placement.version_number, environment.name)
            after = (
                before
                if already
                else verdict_for(
                    db, tenant_id, placement.pacticipant_slug, placement.version_number, environment.name, override
                )
            )
        except (PactPublicationError, PacticipantValidationError) as exc:
            not_checked.append(NotChecked(placement=placement, code=exc.code, reason=str(exc)))
            continue
        impacts.append(
            Impact(
                placement=placement,
                roles=tuple(roles.get(placement.pacticipant_id, ())),
                before=before,
                after=after,
                effect=classify_effect(placement.placement, before.deployable, after.deployable),
            )
        )
    return Simulation(
        environment=environment,
        pacticipant=pacticipant,
        version_number=candidate.number,
        application_instance=instance,
        replaces=replaces,
        already_deployed=already,
        verdict=verdict,
        impacts=impacts,
        not_checked=not_checked,
        evaluated_at=evaluated_at,
    )


def _placements(
    placed: Sequence[Dict[str, Any]], names: Dict[str, Tuple[str, str]], environment_id: str
) -> List[Placement]:
    """Each counterpart version once: *running* when it is in the environment, else *pending*.

    Args:
        placed: Every placed version of the candidate's pacticipant and its counterparts, newest first.
        names: The counterparts, by id: ``(slug, name)``.
        environment_id: The simulated environment.

    Returns:
        The placements; a pending version lists every environment it is in now.
    """
    running: Dict[Tuple[str, str], Placement] = {}
    pending: Dict[Tuple[str, str], Tuple[Dict[str, Any], List[str]]] = {}
    for row in placed:
        pid = row["pacticipant_id"]
        if pid not in names:
            continue
        key = (pid, row["version_id"])
        if row["environment_id"] == environment_id:
            slug, name = names[pid]
            running.setdefault(key, Placement(pid, slug, name, row["number"], PLACEMENT_RUNNING))
        else:
            entry = pending.setdefault(key, (row, []))
            if row["environment_name"] not in entry[1]:
                entry[1].append(row["environment_name"])
    result = list(running.values())
    for key, (row, environments) in pending.items():
        if key in running:
            continue
        slug, name = names[key[0]]
        result.append(Placement(key[0], slug, name, row["number"], PLACEMENT_PENDING, tuple(sorted(environments))))
    return result
