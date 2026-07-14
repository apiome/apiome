"""
Revision-scoped lint evidence contract (CLX-1.1, #4848).

One immutable evidence record per lint/scan run, shared by catalog revisions
(``apiome.versions``) and MCP endpoint versions (``apiome.mcp_endpoint_versions``) and stored
in ``apiome.lint_evidence_runs`` (V167). Native reports keep their existing read models
(``versions.quality_*`` / ``mcp_version_scores``) and API responses; evidence rows are the
provenance/audit substrate underneath them, and the substrate future external scanners
(Buf, GraphQL tooling, security scanners, ...) write into.

Three contracts live here:

* The **source-neutral finding envelope**: every finding, from any scanner, is normalized to
  the same shape (stable ``rule_id``, ``location``, ``severity``, ``confidence``,
  ``remediation``, ``source_fingerprint``). :func:`normalize_native_finding` maps the native
  engines' legacy dicts into it and MUST stay in lock-step with the SQL projection in
  migration V167 (``apiome-db/scripts/V167__lint_evidence_runs_4848.sql``).
* The **evidence run**: :func:`native_evidence_run` / :func:`mcp_evidence_run` build the
  write-once row recorded whenever a native report is persisted.
* The **coverage view**: :func:`coverage_entries` folds stored runs plus the expected scanner
  set into per-scanner coverage where a scanner with no run reads ``not_run`` — an absent
  scan is a visible state, never silently a clean result.

This module is dependency-free within the app (no database / route imports) so both the
persistence layer and the API layer can use it without cycles. Coordinates with #1746/#3609
(schema_lint), #3719 (rule-pack SPI), #4423 (style guides), and #3655/#3686 (MCP lint)
without duplicating their scope: they compute reports; this module records evidence about
those computations.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

# --- Contract vocabulary ----------------------------------------------------------------------

#: Version of the finding-envelope contract emitted by this module. Bump when the envelope
#: shape changes; stored per run so historical rows remain interpretable.
ENVELOPE_VERSION = 1

#: Version of the built-in adapter that normalizes native engine output into the envelope
#: (the ticket's "parser version"). Bump when :func:`normalize_native_finding` changes.
NATIVE_ADAPTER_VERSION = "apiome-native/1"

#: Scanner id for the native catalog-revision lint engines (schema_lint + canonical rule packs).
NATIVE_SCANNER_ID = "apiome.native-lint"

#: Scanner id for the native MCP surface lint engine (mcp_lint / mcp_score).
MCP_SCANNER_ID = "apiome.mcp-lint"

#: Subject discriminators, mirroring the V167 CHECK constraint.
SUBJECT_CATALOG_REVISION = "catalog_revision"
SUBJECT_MCP_ENDPOINT_VERSION = "mcp_endpoint_version"

#: Closed outcome vocabulary (CLX-1.1). ``not_run`` / ``unavailable`` are first-class so an
#: absent scan is recordable and never renders as clean.
OUTCOME_PASSED = "passed"
OUTCOME_FINDINGS = "findings"
OUTCOME_NOT_RUN = "not_run"
OUTCOME_UNAVAILABLE = "unavailable"
OUTCOME_FAILED = "failed"
OUTCOME_BLOCKED_BY_POLICY = "blocked_by_policy"
OUTCOMES = (
    OUTCOME_PASSED,
    OUTCOME_FINDINGS,
    OUTCOME_NOT_RUN,
    OUTCOME_UNAVAILABLE,
    OUTCOME_FAILED,
    OUTCOME_BLOCKED_BY_POLICY,
)

#: Coverage states for a run over its subject.
COVERAGE_FULL = "full"
COVERAGE_PARTIAL = "partial"
COVERAGE_NONE = "none"
COVERAGE_UNKNOWN = "unknown"

#: Execution profiles the built-in seams stamp on their runs.
PROFILE_IMPORT_CAPTURE = "import-capture"
PROFILE_DISCOVERY_CAPTURE = "discovery-capture"
PROFILE_RECOMPUTE = "recompute"

#: Config keys whose values are secrets and must never influence a stored fingerprint's
#: reversible content. Matching is substring-based on the lowercased key name.
_SECRET_KEY_MARKERS = ("secret", "token", "password", "credential", "api_key", "apikey")


# --- Finding envelope -------------------------------------------------------------------------


def normalize_native_finding(finding: Mapping[str, Any]) -> Dict[str, Any]:
    """Project one native lint finding dict into the source-neutral finding envelope.

    The native engines (:mod:`app.schema_lint`, :mod:`app.lint_engine` packs,
    :mod:`app.mcp_lint`) all emit ``{id, path, category, rule, severity, message}`` dicts.
    The envelope renames ``rule`` -> ``rule_id``, wraps ``path`` in a structured ``location``,
    and keeps the engine's stable finding ``id`` as the ``source_fingerprint`` so a finding can
    be tracked across runs. Native lint is deterministic, so ``confidence`` is always ``high``.

    MUST stay in lock-step with the V167 backfill projection so backfilled and runtime rows
    are indistinguishable.

    Args:
        finding: One native finding as a JSON-ready mapping.

    Returns:
        The envelope dict with keys ``rule_id``, ``message``, ``severity``, ``confidence``,
        ``category``, ``location``, ``remediation``, ``source_fingerprint``.
    """
    return {
        "rule_id": finding.get("rule"),
        "message": finding.get("message"),
        "severity": finding.get("severity"),
        "confidence": "high",
        "category": finding.get("category"),
        "location": {"path": finding.get("path")},
        "remediation": None,
        "source_fingerprint": finding.get("id"),
    }


def normalize_native_findings(findings: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize a sequence of native finding dicts into envelope dicts (order preserved).

    Args:
        findings: Native finding mappings, e.g. ``report["findings"]``.

    Returns:
        A list of envelope dicts (see :func:`normalize_native_finding`).
    """
    return [normalize_native_finding(f) for f in findings]


# --- Fingerprints & outcomes ------------------------------------------------------------------


def redacted_config_fingerprint(config: Optional[Mapping[str, Any]]) -> Optional[str]:
    """Fingerprint a scanner configuration after redacting secret-bearing keys.

    Keys whose lowercased name contains a secret marker (``secret``, ``token``, ``password``,
    ``credential``, ``api_key``/``apikey``) are replaced with the fixed sentinel
    ``"<redacted>"`` — recursively — before hashing, so the fingerprint is stable for the same
    non-secret configuration but never derivable from (or into) secret material. Only the hash
    is ever stored; the redacted projection itself is discarded.

    Args:
        config: The scanner configuration mapping, or ``None`` when the run had none.

    Returns:
        A hex SHA-256 digest of the canonicalized redacted configuration, or ``None`` when
        ``config`` is ``None`` or empty.
    """
    if not config:
        return None
    redacted = _redact(config)
    canonical = json.dumps(redacted, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _redact(value: Any) -> Any:
    """Recursively replace values under secret-marked keys with a fixed sentinel."""
    if isinstance(value, Mapping):
        return {
            key: "<redacted>" if _is_secret_key(str(key)) else _redact(sub)
            for key, sub in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def _is_secret_key(key: str) -> bool:
    """True when a config key name indicates its value is secret material."""
    lowered = key.lower()
    return any(marker in lowered for marker in _SECRET_KEY_MARKERS)


def outcome_for_report(report: Mapping[str, Any]) -> str:
    """Derive the evidence outcome for a successfully computed native report.

    A report that itemizes findings is ``findings``; a clean report is ``passed``. (The other
    outcomes — ``not_run``, ``unavailable``, ``failed``, ``blocked_by_policy`` — describe runs
    that produced no report and are set explicitly by their recorders.)

    Args:
        report: A native report dict (``LintResult.report_dict()`` shape).

    Returns:
        ``"findings"`` or ``"passed"``.
    """
    return OUTCOME_FINDINGS if report.get("findings") else OUTCOME_PASSED


# --- Evidence-run builders ---------------------------------------------------------------------


def native_evidence_run(
    version_record_id: str,
    report: Mapping[str, Any],
    *,
    profile: str = PROFILE_IMPORT_CAPTURE,
    input_fingerprint: Optional[str] = None,
    source_fingerprint: Optional[str] = None,
    config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the evidence-run row for a native catalog-revision lint report.

    Args:
        version_record_id: The scanned revision (``versions.id``).
        report: The computed report (``LintResult.report_dict()`` shape) being persisted.
        profile: Execution profile to stamp (defaults to the import-capture seam).
        input_fingerprint: Fingerprint of the exact document the engine consumed, when known.
        source_fingerprint: Fingerprint of the upstream source, when distinct from the input.
        config: Non-persisted scanner configuration; only its redacted fingerprint is stored.

    Returns:
        A column-name -> value dict ready for the persistence layer (JSONB values are plain
        Python structures; the DB layer wraps them).
    """
    return _evidence_run(
        subject_type=SUBJECT_CATALOG_REVISION,
        subject_id=version_record_id,
        scanner_id=NATIVE_SCANNER_ID,
        report=report,
        profile=profile,
        input_fingerprint=input_fingerprint,
        source_fingerprint=source_fingerprint,
        config=config,
    )


def mcp_evidence_run(
    mcp_version_id: str,
    report: Mapping[str, Any],
    *,
    profile: str = PROFILE_DISCOVERY_CAPTURE,
    input_fingerprint: Optional[str] = None,
    source_fingerprint: Optional[str] = None,
    config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the evidence-run row for a native MCP surface lint report.

    Args:
        mcp_version_id: The scanned discovery snapshot (``mcp_endpoint_versions.id``).
        report: The computed report (``MCPScoreResult.report_dict()`` shape) being persisted.
        profile: Execution profile to stamp (defaults to the discovery-capture seam).
        input_fingerprint: Fingerprint of the surface consumed (e.g. ``surface_fingerprint``).
        source_fingerprint: Fingerprint of the upstream source, when distinct from the input.
        config: Non-persisted scanner configuration; only its redacted fingerprint is stored.

    Returns:
        A column-name -> value dict ready for the persistence layer.
    """
    return _evidence_run(
        subject_type=SUBJECT_MCP_ENDPOINT_VERSION,
        subject_id=mcp_version_id,
        scanner_id=MCP_SCANNER_ID,
        report=report,
        profile=profile,
        input_fingerprint=input_fingerprint,
        source_fingerprint=source_fingerprint,
        config=config,
    )


def _evidence_run(
    *,
    subject_type: str,
    subject_id: str,
    scanner_id: str,
    report: Mapping[str, Any],
    profile: str,
    input_fingerprint: Optional[str],
    source_fingerprint: Optional[str],
    config: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Shared builder behind the two subject-specific evidence-run constructors."""
    subject_column = (
        "version_record_id"
        if subject_type == SUBJECT_CATALOG_REVISION
        else "mcp_version_id"
    )
    return {
        "subject_type": subject_type,
        subject_column: subject_id,
        "scanner_id": scanner_id,
        "scanner_version": None,
        "adapter_version": NATIVE_ADAPTER_VERSION,
        "profile": profile,
        "outcome": outcome_for_report(report),
        "input_fingerprint": input_fingerprint,
        "source_fingerprint": source_fingerprint,
        "config_fingerprint": redacted_config_fingerprint(config),
        "raw_artifact_ref": None,
        "report_fingerprint": report.get("report_fingerprint"),
        "findings": normalize_native_findings(report.get("findings") or []),
        "coverage": {"state": COVERAGE_FULL},
        "envelope_version": ENVELOPE_VERSION,
    }


# --- Coverage view -----------------------------------------------------------------------------


def expected_scanners_for_subject(subject_type: str) -> List[str]:
    """Return the scanner ids expected to have evidence for a subject kind.

    Today only the native engines are expected; external scanners (Buf, GraphQL tooling, ...)
    join this set as their adapters land in later CLX issues.

    Args:
        subject_type: ``catalog_revision`` or ``mcp_endpoint_version``.

    Returns:
        The expected scanner ids, deterministic order.
    """
    if subject_type == SUBJECT_MCP_ENDPOINT_VERSION:
        return [MCP_SCANNER_ID]
    return [NATIVE_SCANNER_ID]


def coverage_entries(
    runs: Sequence[Mapping[str, Any]],
    expected_scanners: Sequence[str],
) -> List[Dict[str, Any]]:
    """Fold stored evidence runs into per-scanner coverage, surfacing absent scans.

    Every expected scanner appears exactly once. A scanner with at least one run contributes
    its most recent run's outcome and coverage state; an expected scanner with NO run yields a
    synthetic ``not_run`` entry with ``coverage.state == "none"`` — so a missing scan is always
    a visible state and can never be mistaken for a clean result. Unexpected scanners that do
    have runs (e.g. a scanner later removed from the expected set) are still listed after the
    expected ones, keeping historical evidence visible.

    Args:
        runs: Stored evidence-run rows, most recent first (each with at least ``scanner_id``,
            ``outcome``, ``coverage``).
        expected_scanners: Scanner ids that should have evidence for the subject.

    Returns:
        One entry per scanner: ``{"scanner_id", "outcome", "coverage", "run_id",
        "recorded_at"}`` (``run_id``/``recorded_at`` are ``None`` for synthetic entries).
    """
    latest_by_scanner: Dict[str, Mapping[str, Any]] = {}
    for run in runs:
        scanner = str(run.get("scanner_id"))
        if scanner not in latest_by_scanner:
            latest_by_scanner[scanner] = run

    entries: List[Dict[str, Any]] = []
    listed = set()
    for scanner in list(expected_scanners) + [
        s for s in latest_by_scanner if s not in expected_scanners
    ]:
        if scanner in listed:
            continue
        listed.add(scanner)
        run = latest_by_scanner.get(scanner)
        if run is None:
            entries.append(
                {
                    "scanner_id": scanner,
                    "outcome": OUTCOME_NOT_RUN,
                    "coverage": {"state": COVERAGE_NONE},
                    "run_id": None,
                    "recorded_at": None,
                }
            )
        else:
            coverage = run.get("coverage")
            entries.append(
                {
                    "scanner_id": scanner,
                    "outcome": run.get("outcome"),
                    "coverage": coverage if isinstance(coverage, dict) else {"state": COVERAGE_UNKNOWN},
                    "run_id": str(run["id"]) if run.get("id") is not None else None,
                    "recorded_at": run.get("created_at"),
                }
            )
    return entries
