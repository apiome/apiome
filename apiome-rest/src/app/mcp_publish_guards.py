"""Public publish guards for MCP catalog endpoints (V2-MCP-23.5 / MCAT-9.5, #3695).

``POST /v1/mcp/{tenant}/endpoints/{id}/publish`` makes an endpoint ``published`` and
``public``, which puts it in the ``apiome.mcp_v_public_endpoints`` read view (V134) that the
anonymous public browse pages read. Before that happens three guards run — the MCP twin of the
version publish prechecks (:mod:`app.version_publish_prechecks`):

* **credentials** — nothing the public view shows may carry a credential. The view projects
  the endpoint's name, slug, category, description and host, and the public pages show the
  current snapshot's server identity, instructions and capability names / titles /
  descriptions; each of those values is scanned with the intake secret scrubber
  (:func:`app.intake_secret_scrub.scrub_document_text`). The raw ``endpoint_url`` is never in the
  view (only its host, with userinfo stripped) and stored outbound credentials live in their
  own sealed table, so neither blocks publishing.
* **grade** — the current snapshot's stored quality grade must be at least the configured
  minimum (``APIOME_MCP_PUBLISH_MIN_GRADE``, default ``C``; ``off`` disables the guard). An
  endpoint that was never scored fails it.
* **reachable** — the endpoint must be enabled, not quarantined, discovered, with its last
  discovery succeeding (:func:`app.mcp_catalog_inventory.derive_health` reads ``healthy``), and
  its latest health probe within :data:`HEALTH_PROBE_WINDOW_HOURS` (if any) must be ``up``.

Every guard runs (they do not short-circuit), so a refused publish lists every reason at once.
The module is pure: the route loads the rows and hands them in, which keeps it testable without
a database. Findings name *where* a secret was found and its type — never the value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .intake_secret_scrub import scrub_document_text
from .mcp_catalog_inventory import derive_health
from .models import mcp_endpoint_host

#: Guard ids, in the order they run and are reported.
GUARD_CREDENTIALS = "credentials"
GUARD_GRADE = "grade"
GUARD_REACHABLE = "reachable"

#: Letter grades best-first (the :data:`app.mcp_score.GRADE_THRESHOLDS` bands).
GRADE_ORDER: Tuple[str, ...] = ("A", "B", "C", "D", "F")

#: Values of ``APIOME_MCP_PUBLISH_MIN_GRADE`` that turn the grade guard off.
GRADE_GUARD_DISABLED_VALUES = frozenset({"", "off", "none", "disabled"})

#: How far back the reachability guard looks for the latest health probe. A probe older than
#: this is ignored (the discovery state still has to be healthy).
HEALTH_PROBE_WINDOW_HOURS = 24

#: Capability-item text fields the public pages show, scanned by the credentials guard.
_CAPABILITY_TEXT_FIELDS: Tuple[str, ...] = ("name", "title", "description")

#: Snapshot (version) text fields the public pages show, scanned by the credentials guard.
_VERSION_TEXT_FIELDS: Tuple[str, ...] = ("server_name", "server_title", "instructions")

#: Endpoint text fields the public view projects, scanned by the credentials guard.
_ENDPOINT_TEXT_FIELDS: Tuple[str, ...] = ("name", "slug", "category", "description")


@dataclass(frozen=True)
class PublishGuardResult:
    """The outcome of one publish guard.

    Attributes:
        guard: The guard id (``credentials`` / ``grade`` / ``reachable``).
        passed: Whether the guard allows publishing.
        reason: A one-sentence, human-readable explanation (why it failed, or what passed).
        details: Machine-readable context — for ``credentials`` the ``findings`` list
            (``field`` + ``secret_type``, never the value); for ``grade`` the ``grade`` /
            ``score`` / ``min_grade``; for ``reachable`` the ``health`` label and the latest
            ``probe_status``.
    """

    guard: str
    passed: bool
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        """Serialize to the wire shape the publish route returns."""
        return {
            "guard": self.guard,
            "passed": self.passed,
            "reason": self.reason,
            "details": dict(self.details),
        }


def normalize_min_grade(value: Optional[str]) -> Optional[str]:
    """Resolve the configured minimum grade to a letter, or ``None`` when the guard is off.

    Args:
        value: The raw setting (``A``–``F``, case-insensitive, or ``off`` / ``none`` /
            ``disabled`` / blank to disable).

    Returns:
        The upper-cased letter, or ``None`` when the grade guard is disabled.

    Raises:
        ValueError: When ``value`` is neither a grade letter nor a disabling value — a
            misconfiguration is reported rather than silently publishing everything.
    """
    raw = (value or "").strip()
    if raw.lower() in GRADE_GUARD_DISABLED_VALUES:
        return None
    letter = raw.upper()
    if letter not in GRADE_ORDER:
        raise ValueError(
            f"APIOME_MCP_PUBLISH_MIN_GRADE must be one of {list(GRADE_ORDER)} or 'off', got {value!r}"
        )
    return letter


def grade_meets_minimum(grade: Optional[str], min_grade: str) -> bool:
    """True when ``grade`` is ``min_grade`` or better; an unknown or missing grade never meets it."""
    letter = (grade or "").strip().upper()
    if letter not in GRADE_ORDER:
        return False
    return GRADE_ORDER.index(letter) <= GRADE_ORDER.index(min_grade)


def public_text_fields(
    endpoint: Mapping[str, Any],
    version: Optional[Mapping[str, Any]],
    capability_items: Iterable[Mapping[str, Any]],
) -> List[Tuple[str, str]]:
    """List every ``(field label, text)`` pair the public view and public pages expose.

    Args:
        endpoint: The ``apiome.mcp_endpoints`` row.
        version: The current snapshot row (``None`` when never discovered).
        capability_items: The current snapshot's capability rows.

    Returns:
        Non-empty string values, labelled so a finding can say where it is
        (``description``, ``host``, ``version.instructions``, ``tool:search.description``).
    """
    pairs: List[Tuple[str, str]] = []

    def _add(label: str, value: Any) -> None:
        if isinstance(value, str) and value.strip():
            pairs.append((label, value))

    for name in _ENDPOINT_TEXT_FIELDS:
        _add(name, endpoint.get(name))
    _add("host", mcp_endpoint_host(endpoint.get("endpoint_url")))
    if version:
        for name in _VERSION_TEXT_FIELDS:
            _add(f"version.{name}", version.get(name))
    for item in capability_items:
        prefix = f"{item.get('item_type') or 'item'}:{item.get('name') or '?'}"
        for name in _CAPABILITY_TEXT_FIELDS:
            _add(f"{prefix}.{name}", item.get(name))
    return pairs


def check_credentials(fields: Sequence[Tuple[str, str]]) -> PublishGuardResult:
    """Guard: no public-facing text may contain a credential.

    Args:
        fields: ``(label, text)`` pairs from :func:`public_text_fields`.

    Returns:
        A failing result listing each ``{field, secret_type}`` found, or a passing one.
    """
    findings: List[Dict[str, str]] = []
    for label, text in fields:
        outcome = scrub_document_text(text)
        for secret_type in sorted({f.secret_type for f in outcome.findings}):
            findings.append({"field": label, "secret_type": secret_type})
    if findings:
        where = ", ".join(sorted({f["field"] for f in findings}))
        return PublishGuardResult(
            guard=GUARD_CREDENTIALS,
            passed=False,
            reason=(
                f"{len(findings)} credential-like value(s) would be exposed in the public view "
                f"(in {where}). Remove them before publishing."
            ),
            details={"findings": findings},
        )
    return PublishGuardResult(
        guard=GUARD_CREDENTIALS,
        passed=True,
        reason="No credentials found in the fields the public view exposes.",
        details={"findings": [], "fields_scanned": len(fields)},
    )


def check_grade(
    version: Optional[Mapping[str, Any]], min_grade: Optional[str]
) -> PublishGuardResult:
    """Guard: the current snapshot's stored grade must be at least ``min_grade``.

    Args:
        version: The current snapshot row with its joined ``score`` / ``grade`` (``None``
            when never discovered).
        min_grade: The minimum letter from :func:`normalize_min_grade`; ``None`` disables
            the guard (it then passes).

    Returns:
        The guard result with ``grade``, ``score`` and ``min_grade`` details.
    """
    grade = (version or {}).get("grade")
    score = (version or {}).get("score")
    details = {
        "grade": str(grade) if grade is not None else None,
        "score": int(score) if score is not None else None,
        "min_grade": min_grade,
    }
    if min_grade is None:
        return PublishGuardResult(
            guard=GUARD_GRADE,
            passed=True,
            reason="The minimum lint grade guard is turned off.",
            details=details,
        )
    if grade is None:
        return PublishGuardResult(
            guard=GUARD_GRADE,
            passed=False,
            reason=(
                f"The endpoint has no lint grade yet; it needs grade {min_grade} or better. "
                "Run discovery so the current snapshot is scored."
            ),
            details=details,
        )
    if not grade_meets_minimum(str(grade), min_grade):
        return PublishGuardResult(
            guard=GUARD_GRADE,
            passed=False,
            reason=f"Lint grade {grade} is below the minimum grade {min_grade} for public endpoints.",
            details=details,
        )
    return PublishGuardResult(
        guard=GUARD_GRADE,
        passed=True,
        reason=f"Lint grade {grade} meets the minimum grade {min_grade}.",
        details=details,
    )


def check_reachable(
    endpoint: Mapping[str, Any], latest_probe: Optional[Mapping[str, Any]]
) -> PublishGuardResult:
    """Guard: the endpoint must be reachable.

    Args:
        endpoint: The ``apiome.mcp_endpoints`` row (enabled, quarantine, discovery and
            failure columns).
        latest_probe: The newest health-check row within :data:`HEALTH_PROBE_WINDOW_HOURS`,
            or ``None`` when there is none (the discovery state alone then decides).

    Returns:
        The guard result with the ``health`` label, ``last_discovery_status`` and the latest
        ``probe_status`` / ``probe_error_code``.
    """
    health = derive_health(endpoint)
    probe_status = str(latest_probe.get("status")) if latest_probe else None
    probe_error = latest_probe.get("error_code") if latest_probe else None
    details = {
        "health": health,
        "last_discovery_status": endpoint.get("last_discovery_status"),
        "probe_status": probe_status,
        "probe_error_code": str(probe_error) if probe_error else None,
    }
    reasons = {
        "quarantined": "The endpoint is quarantined after repeated discovery failures.",
        "disabled": "The endpoint is disabled.",
        "undiscovered": "The endpoint has never been discovered successfully.",
        "failing": "The endpoint's latest discovery attempts failed.",
    }
    if health in reasons:
        return PublishGuardResult(
            guard=GUARD_REACHABLE, passed=False, reason=reasons[health], details=details
        )
    if probe_status == "down":
        code = f" ({probe_error})" if probe_error else ""
        return PublishGuardResult(
            guard=GUARD_REACHABLE,
            passed=False,
            reason=f"The latest health probe could not reach the endpoint{code}.",
            details=details,
        )
    return PublishGuardResult(
        guard=GUARD_REACHABLE,
        passed=True,
        reason="The endpoint is enabled, discovered and answering.",
        details=details,
    )


def evaluate_publish_guards(
    *,
    endpoint: Mapping[str, Any],
    version: Optional[Mapping[str, Any]],
    capability_items: Iterable[Mapping[str, Any]],
    latest_probe: Optional[Mapping[str, Any]],
    min_grade: Optional[str],
) -> List[PublishGuardResult]:
    """Run every publish guard and return the results in report order.

    Args:
        endpoint: The ``apiome.mcp_endpoints`` row.
        version: The current snapshot row with joined ``score`` / ``grade``, or ``None``.
        capability_items: The current snapshot's capability rows.
        latest_probe: The newest health probe in the window, or ``None``.
        min_grade: The minimum grade letter, or ``None`` when the grade guard is off.

    Returns:
        ``[credentials, grade, reachable]`` results; publishing is allowed only when all pass.
    """
    return [
        check_credentials(public_text_fields(endpoint, version, capability_items)),
        check_grade(version, min_grade),
        check_reachable(endpoint, latest_probe),
    ]


def failed_guards(results: Iterable[PublishGuardResult]) -> List[PublishGuardResult]:
    """The results that block publishing (empty when publishing is allowed)."""
    return [r for r in results if not r.passed]
