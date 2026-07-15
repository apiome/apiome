"""
Catalog-wide lint posture and remediation workspace (CLX-4.1, #4859).

Builds the cross-subject findings index the workspace queue, summary, and trends read from:
the newest evidence run per (subject, scanner) across a tenant's latest live catalog revisions
and MCP snapshots, joined with axis evaluations (CLX-1.2), the latest policy evaluation and
finding decisions / waivers (CLX-1.3).

Everything below :func:`build_workspace_index` is pure (rows in, plain dicts out) so filtering,
sorting, facets, summary, trends, and the waiver-transition rules unit-test without HTTP or a
database. Only :func:`build_workspace_index` / :func:`load_trend_inputs` touch ``app.database``.

The waiver state machine (request -> review) lives here so the bulk endpoint and the single
decision upsert route share one implementation:

======================  =======================================  ==================
From                    To                                       Permission
======================  =======================================  ==================
open / acknowledged /   acknowledged, fixed, false_positive,     lint_findings:edit
fixed / false_positive  open, waiver_requested (rationale req.)
(or no decision row)
waiver_requested        waived (approve; rationale + expiry) or  lint_findings:publish
                        open (reject)
any                     waived (direct; rationale + expiry)      lint_findings:publish
waived                  any other state (revoke / reopen)        lint_findings:publish
expired waiver          open                                     automatic at read time
======================  =======================================  ==================

A ``waiver_requested`` finding still gates CI exactly like ``open`` — see
:data:`app.policy_evaluate.SUPPRESSED_FOR_ERRORS`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .axis_score import AXIS_KEYS, AXIS_LABELS, axis_key_for_finding
from .database import db
from .lint_evidence import (
    SUBJECT_CATALOG_REVISION,
    SUBJECT_MCP_ENDPOINT_VERSION,
)
from .policy_evaluate import (
    DECISION_STATES,
    DEFAULT_REQUIRED_COVERAGE,
    SUPPRESSED_FOR_ERRORS,
    effective_decision_state,
    match_decision_for_fingerprint,
)

# --- Vocabularies -----------------------------------------------------------------------------

#: Finding severities, worst first (also the severity sort order).
SEVERITIES: Tuple[str, ...] = ("error", "warning", "info")

#: Queue sort keys accepted by ``GET /v1/lint/workspace/findings``.
SORT_KEYS: Tuple[str, ...] = ("severity", "newest", "rule", "subject")

#: Letter grades for the composite-grade filter.
GRADES: Tuple[str, ...] = ("A", "B", "C", "D", "F")

#: Coverage filter values: subjects missing required coverage vs. meeting it.
COVERAGE_FILTERS: Tuple[str, ...] = ("missing", "met")

#: Subject discriminators accepted by the ``subjectType`` filter.
SUBJECT_TYPES: Tuple[str, ...] = (SUBJECT_CATALOG_REVISION, SUBJECT_MCP_ENDPOINT_VERSION)

#: RBAC actions a decision transition can require (``lint_findings`` resource).
ACTION_EDIT = "edit"
ACTION_PUBLISH = "publish"

#: Days before expiry a waiver counts as "expiring soon" in the summary.
EXPIRING_SOON_DAYS = 14

#: Cap on items in one bulk decision request.
BULK_ITEM_CAP = 200

#: Filter keys accepted in saved views and the findings query (closed set).
FILTER_KEYS: Tuple[str, ...] = (
    "severity",
    "state",
    "axis",
    "grade",
    "coverage",
    "profile",
    "scanner",
    "subject_type",
    "project_id",
    "owner_user_id",
    "rule_id",
    "category",
    "new",
    "q",
)


class WorkspaceValidationError(ValueError):
    """A filter / transition payload failed closed-vocabulary validation."""


# --- Waiver state machine ----------------------------------------------------------------------


def required_action_for_transition(before_state: Optional[str], after_state: str) -> str:
    """Return the ``lint_findings`` action a decision transition requires.

    Approval-tier transitions (anything entering or leaving ``waived``, and resolving a
    ``waiver_requested`` row to approved/rejected) require ``publish``; everything else —
    assigning, acknowledging, fixing, false-positive marking, and *requesting* a waiver —
    requires only ``edit``.

    Args:
        before_state: Current stored state; ``None`` (no decision row yet) reads as ``open``.
        after_state: Requested target state.

    Returns:
        :data:`ACTION_EDIT` or :data:`ACTION_PUBLISH`.
    """
    before = str(before_state or "open")
    if after_state == "waived":
        return ACTION_PUBLISH
    if before == "waived":
        return ACTION_PUBLISH
    if before == "waiver_requested" and after_state == "open":
        # Rejecting a waiver request is a review decision; withdrawing to `acknowledged`
        # stays an edit so a requester can retract their own request.
        return ACTION_PUBLISH
    return ACTION_EDIT


def transition_error(
    after_state: str,
    *,
    rationale: Optional[str] = None,
    expires_at: Optional[Any] = None,
) -> Optional[str]:
    """Validate a decision transition's target state and required fields.

    Args:
        after_state: Requested target state.
        rationale: Rationale accompanying the transition, if any.
        expires_at: Expiry accompanying the transition, if any.

    Returns:
        A human-readable error message, or ``None`` when the transition is well-formed.
    """
    if after_state not in DECISION_STATES:
        return f"Invalid state; expected one of {', '.join(DECISION_STATES)}"
    if after_state == "waived":
        if not (rationale or "").strip():
            return "Waivers require a non-empty rationale"
        if expires_at is None:
            return "Waivers require an expiresAt timestamp"
    if after_state == "waiver_requested" and not (rationale or "").strip():
        return "Waiver requests require a non-empty rationale"
    return None


# --- Index building ----------------------------------------------------------------------------


def _parse_dt(value: Optional[Any]) -> Optional[datetime]:
    """Parse a datetime or ISO string into an aware UTC datetime (lenient)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _subject_key(row: Mapping[str, Any]) -> Tuple[str, str]:
    """(subject_type, subject_id) discriminator for any subject-bearing row."""
    if row.get("version_record_id"):
        return (SUBJECT_CATALOG_REVISION, str(row["version_record_id"]))
    return (SUBJECT_MCP_ENDPOINT_VERSION, str(row.get("mcp_version_id") or ""))


def _finding_fingerprint(finding: Mapping[str, Any]) -> Optional[str]:
    """Stable fingerprint from an envelope (or native) finding dict."""
    fp = finding.get("source_fingerprint") or finding.get("id")
    return str(fp) if fp else None


def _run_fingerprints(run: Mapping[str, Any]) -> set:
    """The set of finding fingerprints one evidence run carries."""
    out = set()
    for finding in run.get("findings") or []:
        if isinstance(finding, Mapping):
            fp = _finding_fingerprint(finding)
            if fp:
                out.add(fp)
    return out


def _group_runs_by_subject_scanner(
    evidence_rows: Sequence[Mapping[str, Any]],
) -> Dict[Tuple[str, str], Dict[str, List[Mapping[str, Any]]]]:
    """Group evidence rows (newest first) into subject -> scanner -> [runs newest-first]."""
    grouped: Dict[Tuple[str, str], Dict[str, List[Mapping[str, Any]]]] = {}
    for row in evidence_rows:
        key = _subject_key(row)
        scanner = str(row.get("scanner_id") or "")
        grouped.setdefault(key, {}).setdefault(scanner, []).append(row)
    return grouped


def build_index_from_rows(
    *,
    evidence_rows: Sequence[Mapping[str, Any]],
    axis_rows: Sequence[Mapping[str, Any]],
    policy_rows: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Assemble the workspace index from pre-loaded rows (pure; see module docstring).

    Args:
        evidence_rows: Output of ``db.list_latest_lint_evidence_runs_for_tenant`` — up to two
            newest runs per (subject, scanner), newest first.
        axis_rows: Output of ``db.list_latest_axis_evaluations_for_tenant``.
        policy_rows: Output of ``db.list_latest_lint_policy_evaluations_for_tenant``.
        decisions: Output of ``db.list_lint_finding_decisions``.
        now: Clock for waiver-expiry evaluation (UTC).

    Returns:
        ``{"findings": [enriched finding dict, ...], "subjects": [subject dict, ...]}``.
        A finding row carries everything acceptance criterion 2 links: the revision
        (``project_id`` + ``version_record_id`` / ``mcp_version_id``), the evidence run
        (``evidence_run_id``), the policy decision (``latest_policy_evaluation_id`` /
        ``policy_passed`` / ``decision``), and the source ``location``.
    """
    clock = now or datetime.now(timezone.utc)

    axis_by_subject: Dict[Tuple[str, str], Mapping[str, Any]] = {
        _subject_key(row): row for row in axis_rows
    }
    policy_by_subject: Dict[Tuple[str, str], Mapping[str, Any]] = {
        _subject_key(row): row for row in policy_rows
    }
    grouped = _group_runs_by_subject_scanner(evidence_rows)

    subjects: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def subject_entry(key: Tuple[str, str], source_row: Mapping[str, Any]) -> Dict[str, Any]:
        """Get-or-create the rollup entry for a subject, filling identity from any row."""
        entry = subjects.get(key)
        if entry is None:
            subject_type, subject_id = key
            entry = {
                "subject_type": subject_type,
                "subject_id": subject_id,
                "version_record_id": (
                    subject_id if subject_type == SUBJECT_CATALOG_REVISION else None
                ),
                "mcp_version_id": (
                    subject_id if subject_type == SUBJECT_MCP_ENDPOINT_VERSION else None
                ),
                "project_id": None,
                "project_name": None,
                "subject_label": None,
                "composite_grade": None,
                "required_coverage_met": None,
                "axes": [],
                "missing_axes": [],
                "policy_passed": None,
                "latest_policy_evaluation_id": None,
            }
            subjects[key] = entry
        if entry["project_id"] is None and source_row.get("project_id"):
            entry["project_id"] = str(source_row["project_id"])
        if entry["project_name"] is None and source_row.get("project_name"):
            entry["project_name"] = str(source_row["project_name"])
        if entry["subject_label"] is None and source_row.get("subject_label"):
            entry["subject_label"] = str(source_row["subject_label"])
        return entry

    # Axis evaluations: grade / coverage / per-axis rows.
    for key, row in axis_by_subject.items():
        entry = subject_entry(key, row)
        entry["composite_grade"] = row.get("composite_grade")
        entry["required_coverage_met"] = (
            bool(row["required_coverage_met"])
            if row.get("required_coverage_met") is not None
            else None
        )
        axes = row.get("axes") if isinstance(row.get("axes"), list) else []
        entry["axes"] = [a for a in axes if isinstance(a, Mapping)]

    # Policy evaluations: pass/fail plus the authoritative required-coverage gap when present.
    for key, row in policy_by_subject.items():
        entry = subject_entry(key, row)
        entry["policy_passed"] = (
            bool(row["passed"]) if row.get("passed") is not None else None
        )
        entry["latest_policy_evaluation_id"] = (
            str(row["id"]) if row.get("id") is not None else None
        )
        gates = row.get("gate_results")
        if isinstance(gates, Mapping):
            detail = (gates.get("required_coverage") or {}).get("detail") or {}
            missing = detail.get("missing")
            if isinstance(missing, list):
                entry["missing_axes"] = [str(m) for m in missing]

    findings: List[Dict[str, Any]] = []
    for key, by_scanner in grouped.items():
        subject_type, _ = key
        for scanner_id in sorted(by_scanner):
            runs = by_scanner[scanner_id]
            latest = runs[0]
            entry = subject_entry(key, latest)
            previous = runs[1] if len(runs) > 1 else None
            previous_fps = _run_fingerprints(previous) if previous else None
            for finding in latest.get("findings") or []:
                if not isinstance(finding, Mapping):
                    continue
                fp = _finding_fingerprint(finding)
                decision = (
                    match_decision_for_fingerprint(
                        decisions, fp, project_id=entry["project_id"]
                    )
                    if fp
                    else None
                )
                effective = effective_decision_state(
                    decision, now=clock, finding_present=True
                )
                severity = str(finding.get("severity") or "").strip().lower()
                findings.append(
                    {
                        "source_fingerprint": fp,
                        "rule_id": (
                            str(finding.get("rule_id") or finding.get("rule") or "")
                            or None
                        ),
                        "message": finding.get("message"),
                        "severity": severity or None,
                        "confidence": finding.get("confidence"),
                        "category": finding.get("category"),
                        "axis_key": axis_key_for_finding(
                            finding.get("category"), scanner_id=scanner_id
                        ),
                        "location": (
                            finding.get("location")
                            if isinstance(finding.get("location"), Mapping)
                            else {}
                        ),
                        "remediation": finding.get("remediation"),
                        "scanner_id": scanner_id,
                        "profile": latest.get("profile"),
                        "subject_type": subject_type,
                        "version_record_id": entry["version_record_id"],
                        "mcp_version_id": entry["mcp_version_id"],
                        "project_id": entry["project_id"],
                        "project_name": entry["project_name"],
                        "subject_label": entry["subject_label"],
                        "composite_grade": entry["composite_grade"],
                        "required_coverage_met": entry["required_coverage_met"],
                        "evidence_run_id": (
                            str(latest["id"]) if latest.get("id") is not None else None
                        ),
                        "evidence_created_at": latest.get("created_at"),
                        # New = present in this scanner's newest run but absent from its
                        # previous run; a scanner's very first run is all-new.
                        "is_new": (
                            previous_fps is None or (fp is not None and fp not in previous_fps)
                        ),
                        "effective_state": effective,
                        "waived": effective in SUPPRESSED_FOR_ERRORS,
                        "decision": dict(decision) if decision else None,
                        "latest_policy_evaluation_id": entry["latest_policy_evaluation_id"],
                        "policy_passed": entry["policy_passed"],
                    }
                )

    # Fallback coverage gap for subjects with an axis row but no policy evaluation: the
    # default required axes that are not assessed (never conflated with a clean score).
    for entry in subjects.values():
        if not entry["missing_axes"] and entry["required_coverage_met"] is not True:
            assessed = {
                str(a.get("key")): bool(a.get("assessed")) for a in entry["axes"]
            }
            entry["missing_axes"] = [
                axis
                for axis in DEFAULT_REQUIRED_COVERAGE
                if not assessed.get(axis, False)
            ]

    return {"findings": findings, "subjects": list(subjects.values())}


def build_workspace_index(
    tenant_id: str,
    *,
    project_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Load rows from the database and assemble the workspace index for one tenant."""
    return build_index_from_rows(
        evidence_rows=db.list_latest_lint_evidence_runs_for_tenant(
            tenant_id, project_id=project_id
        ),
        axis_rows=db.list_latest_axis_evaluations_for_tenant(
            tenant_id, project_id=project_id
        ),
        policy_rows=db.list_latest_lint_policy_evaluations_for_tenant(
            tenant_id, project_id=project_id
        ),
        decisions=db.list_lint_finding_decisions(tenant_id, project_id=project_id),
        now=now,
    )


# --- Filters, sorting, pagination, facets --------------------------------------------------------


def _csv_values(raw: Any) -> List[str]:
    """Split a csv string (or pass through a list) into stripped non-empty values."""
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = raw.split(",")
    elif isinstance(raw, (list, tuple)):
        parts = [str(p) for p in raw]
    else:
        parts = [str(raw)]
    return [p.strip() for p in parts if p and p.strip()]


def normalize_filters(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate a filter mapping into the canonical workspace filter dict.

    Closed vocabularies (severity, state, axis, grade, coverage, subjectType) reject unknown
    values; free-text keys (profile, scanner, ids, q) pass through trimmed. Unknown keys are
    dropped so a stale saved view cannot smuggle arbitrary parameters.

    Args:
        raw: Query params or a saved view's ``filters`` blob (camelCase or snake_case keys).

    Returns:
        Canonical snake_case filter dict containing only supplied keys.

    Raises:
        WorkspaceValidationError: When a closed-vocabulary value is unknown.
    """
    aliases = {
        "subjectType": "subject_type",
        "projectId": "project_id",
        "ownerUserId": "owner_user_id",
        "ruleId": "rule_id",
    }
    vocab = {
        "severity": set(SEVERITIES),
        "state": set(DECISION_STATES),
        "axis": set(AXIS_KEYS),
        "grade": set(GRADES),
    }
    out: Dict[str, Any] = {}
    for raw_key, value in raw.items():
        key = aliases.get(str(raw_key), str(raw_key))
        if key not in FILTER_KEYS or value is None:
            continue
        if key in vocab:
            values = _csv_values(value)
            unknown = [v for v in values if v not in vocab[key]]
            if unknown:
                raise WorkspaceValidationError(
                    f"Unknown {key} value(s): {', '.join(sorted(unknown))}"
                )
            if values:
                out[key] = values
        elif key in ("profile", "scanner"):
            values = _csv_values(value)
            if values:
                out[key] = values
        elif key == "coverage":
            text = str(value).strip()
            if not text:
                continue
            if text not in COVERAGE_FILTERS:
                raise WorkspaceValidationError(
                    f"Unknown coverage value: {text} (expected missing or met)"
                )
            out[key] = text
        elif key == "subject_type":
            text = str(value).strip()
            if not text:
                continue
            if text not in SUBJECT_TYPES:
                raise WorkspaceValidationError(f"Unknown subjectType value: {text}")
            out[key] = text
        elif key == "new":
            if isinstance(value, bool):
                out[key] = value
            else:
                text = str(value).strip().lower()
                if text in ("true", "1", "yes"):
                    out[key] = True
                elif text in ("false", "0", "no", ""):
                    if text:
                        out[key] = False
                else:
                    raise WorkspaceValidationError("new must be a boolean")
        else:  # project_id, owner_user_id, rule_id, category, q
            text = str(value).strip()
            if text:
                out[key] = text
    return out


def normalize_sort(raw: Optional[str]) -> str:
    """Validate a sort key, defaulting to ``severity``."""
    text = str(raw or "").strip()
    if not text:
        return "severity"
    if text not in SORT_KEYS:
        raise WorkspaceValidationError(
            f"Unknown sort value: {text} (expected one of {', '.join(SORT_KEYS)})"
        )
    return text


def _searchable_text(finding: Mapping[str, Any]) -> str:
    """Lowercased haystack for the free-text ``q`` filter."""
    location = finding.get("location") or {}
    location_bits = " ".join(str(v) for v in location.values()) if isinstance(
        location, Mapping
    ) else str(location)
    return " ".join(
        str(part)
        for part in (
            finding.get("rule_id"),
            finding.get("message"),
            finding.get("subject_label"),
            finding.get("project_name"),
            location_bits,
        )
        if part
    ).lower()


def filter_findings(
    findings: Sequence[Mapping[str, Any]], filters: Mapping[str, Any]
) -> List[Mapping[str, Any]]:
    """Apply canonical workspace filters (from :func:`normalize_filters`) to finding rows."""
    severity = set(filters.get("severity") or [])
    state = set(filters.get("state") or [])
    axis = set(filters.get("axis") or [])
    grade = set(filters.get("grade") or [])
    profile = set(filters.get("profile") or [])
    scanner = set(filters.get("scanner") or [])
    coverage = filters.get("coverage")
    subject_type = filters.get("subject_type")
    project_id = filters.get("project_id")
    owner_user_id = filters.get("owner_user_id")
    rule_id = filters.get("rule_id")
    category = filters.get("category")
    only_new = filters.get("new")
    q = str(filters.get("q") or "").strip().lower()

    out: List[Mapping[str, Any]] = []
    for f in findings:
        if severity and str(f.get("severity") or "") not in severity:
            continue
        if state and str(f.get("effective_state") or "") not in state:
            continue
        if axis and str(f.get("axis_key") or "") not in axis:
            continue
        if grade and str(f.get("composite_grade") or "") not in grade:
            continue
        if profile and str(f.get("profile") or "") not in profile:
            continue
        if scanner and str(f.get("scanner_id") or "") not in scanner:
            continue
        if coverage == "missing" and f.get("required_coverage_met") is True:
            continue
        if coverage == "met" and f.get("required_coverage_met") is not True:
            continue
        if subject_type and str(f.get("subject_type") or "") != subject_type:
            continue
        if project_id and str(f.get("project_id") or "") != str(project_id):
            continue
        if owner_user_id:
            decision = f.get("decision") or {}
            if str(decision.get("owner_user_id") or "") != str(owner_user_id):
                continue
        if rule_id and str(f.get("rule_id") or "") != rule_id:
            continue
        if category and str(f.get("category") or "").lower() != category.lower():
            continue
        if only_new is True and not f.get("is_new"):
            continue
        if only_new is False and f.get("is_new"):
            continue
        if q and q not in _searchable_text(f):
            continue
        out.append(f)
    return out


def _severity_rank(severity: Optional[str]) -> int:
    """error < warning < info < unknown for sorting (worst first)."""
    sev = str(severity or "")
    return SEVERITIES.index(sev) if sev in SEVERITIES else len(SEVERITIES)


def _created_sort_key(value: Any) -> str:
    """ISO-comparable string for created-at values (datetime or string)."""
    dt = _parse_dt(value)
    return dt.isoformat() if dt else ""


def sort_findings(
    findings: Sequence[Mapping[str, Any]], sort: str
) -> List[Mapping[str, Any]]:
    """Order finding rows by a :data:`SORT_KEYS` key (deterministic tie-breaks)."""
    rows = list(findings)
    if sort == "newest":
        rows.sort(
            key=lambda f: (
                _invert_iso(_created_sort_key(f.get("evidence_created_at"))),
                f.get("source_fingerprint") or "",
            )
        )
    elif sort == "rule":
        rows.sort(
            key=lambda f: (
                str(f.get("rule_id") or "~"),
                _severity_rank(f.get("severity")),
                f.get("source_fingerprint") or "",
            )
        )
    elif sort == "subject":
        rows.sort(
            key=lambda f: (
                str(f.get("subject_label") or "~"),
                _severity_rank(f.get("severity")),
                f.get("source_fingerprint") or "",
            )
        )
    else:  # severity (default)
        rows.sort(
            key=lambda f: (
                _severity_rank(f.get("severity")),
                # Within a severity, newest evidence first (inverted ISO string sorts desc).
                _invert_iso(_created_sort_key(f.get("evidence_created_at"))),
                f.get("source_fingerprint") or "",
            )
        )
    return rows


def _invert_iso(text: str) -> str:
    """Map an ISO timestamp string to a key that sorts newest-first ascending."""
    return "".join(chr(0x10FFFF - ord(c)) for c in text) if text else "￿"


def paginate(
    rows: Sequence[Any], *, limit: int, offset: int
) -> Tuple[List[Any], int]:
    """Slice rows into a page; returns ``(page, total)``."""
    total = len(rows)
    start = max(0, int(offset))
    end = start + max(0, int(limit))
    return list(rows[start:end]), total


def facet_counts(findings: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, int]]:
    """Value counts over the *filtered* (pre-pagination) queue for the toolbar facets."""
    facets: Dict[str, Dict[str, int]] = {
        "severity": {},
        "effectiveState": {},
        "scannerId": {},
        "axis": {},
        "grade": {},
    }

    def bump(group: str, value: Optional[Any]) -> None:
        key = str(value) if value else "none"
        facets[group][key] = facets[group].get(key, 0) + 1

    for f in findings:
        bump("severity", f.get("severity"))
        bump("effectiveState", f.get("effective_state"))
        bump("scannerId", f.get("scanner_id"))
        bump("axis", f.get("axis_key"))
        bump("grade", f.get("composite_grade") or "ungraded")
    return facets


# --- Summary -------------------------------------------------------------------------------------


def build_summary(
    index: Mapping[str, Any], *, now: Optional[datetime] = None
) -> Dict[str, Any]:
    """Roll the workspace index up into the posture summary (see route docstring)."""
    clock = now or datetime.now(timezone.utc)
    findings: Sequence[Mapping[str, Any]] = index.get("findings") or []
    subjects: Sequence[Mapping[str, Any]] = index.get("subjects") or []

    grade_distribution = {g: 0 for g in GRADES}
    grade_distribution["ungraded"] = 0
    subject_counts = {SUBJECT_CATALOG_REVISION: 0, SUBJECT_MCP_ENDPOINT_VERSION: 0}
    axis_rollup: Dict[str, Dict[str, Any]] = {
        key: {
            "key": key,
            "label": AXIS_LABELS[key],
            "assessed_count": 0,
            "not_assessed_count": 0,
            "score_sum": 0,
            "grade_distribution": {g: 0 for g in GRADES},
            "severity_counts": {"error": 0, "warning": 0, "info": 0},
        }
        for key in AXIS_KEYS
    }
    coverage_subjects: List[Dict[str, Any]] = []

    for subject in subjects:
        subject_counts[str(subject.get("subject_type"))] = (
            subject_counts.get(str(subject.get("subject_type")), 0) + 1
        )
        grade = subject.get("composite_grade")
        if grade in grade_distribution:
            grade_distribution[str(grade)] += 1
        else:
            grade_distribution["ungraded"] += 1
        for axis in subject.get("axes") or []:
            key = str(axis.get("key") or "")
            rollup = axis_rollup.get(key)
            if not rollup:
                continue
            if axis.get("assessed") is True:
                rollup["assessed_count"] += 1
                if axis.get("score") is not None:
                    rollup["score_sum"] += int(axis["score"])
                axis_grade = axis.get("grade")
                if axis_grade in rollup["grade_distribution"]:
                    rollup["grade_distribution"][str(axis_grade)] += 1
                counts = axis.get("severity_counts")
                if isinstance(counts, Mapping):
                    for sev in ("error", "warning", "info"):
                        rollup["severity_counts"][sev] += int(counts.get(sev) or 0)
            else:
                rollup["not_assessed_count"] += 1
        missing = subject.get("missing_axes") or []
        if missing:
            coverage_subjects.append(
                {
                    "subject_type": subject.get("subject_type"),
                    "subject_id": subject.get("subject_id"),
                    "project_id": subject.get("project_id"),
                    "subject_label": subject.get("subject_label"),
                    "missing_axes": list(missing),
                }
            )

    axes_out: List[Dict[str, Any]] = []
    for key in AXIS_KEYS:
        rollup = axis_rollup[key]
        assessed = rollup["assessed_count"]
        axes_out.append(
            {
                "key": key,
                "label": rollup["label"],
                "assessed_count": assessed,
                "not_assessed_count": rollup["not_assessed_count"],
                "average_score": (
                    round(rollup["score_sum"] / assessed) if assessed else None
                ),
                "grade_distribution": rollup["grade_distribution"],
                "severity_counts": rollup["severity_counts"],
            }
        )

    state_counts = {state: 0 for state in DECISION_STATES}
    new_count = 0
    unwaived_errors = 0
    unwaived_security_errors = 0
    waivers_active: set = set()
    waivers_requested: set = set()
    waivers_expiring_soon: set = set()
    soon_cutoff = clock + timedelta(days=EXPIRING_SOON_DAYS)

    for f in findings:
        effective = str(f.get("effective_state") or "open")
        if effective in state_counts:
            state_counts[effective] += 1
        if f.get("is_new"):
            new_count += 1
        if str(f.get("severity") or "") == "error" and not f.get("waived"):
            unwaived_errors += 1
            if str(f.get("axis_key") or "") == "security":
                unwaived_security_errors += 1
        decision = f.get("decision") or {}
        decision_key = str(decision.get("id") or f.get("source_fingerprint") or "")
        if not decision_key:
            continue
        if effective == "waived":
            waivers_active.add(decision_key)
            expires = _parse_dt(decision.get("expires_at"))
            if expires is not None and expires <= soon_cutoff:
                waivers_expiring_soon.add(decision_key)
        elif effective == "waiver_requested":
            waivers_requested.add(decision_key)

    return {
        "subjects": {
            "catalog_revisions": subject_counts.get(SUBJECT_CATALOG_REVISION, 0),
            "mcp_endpoint_versions": subject_counts.get(
                SUBJECT_MCP_ENDPOINT_VERSION, 0
            ),
        },
        "grade_distribution": grade_distribution,
        "axes": axes_out,
        "coverage": {
            "missing_count": len(coverage_subjects),
            "subjects": coverage_subjects,
        },
        "findings": {
            "open": state_counts["open"],
            "acknowledged": state_counts["acknowledged"],
            "waiver_requested": state_counts["waiver_requested"],
            "waived": state_counts["waived"],
            "fixed": state_counts["fixed"],
            "false_positive": state_counts["false_positive"],
            "new_count": new_count,
            "unwaived_errors": unwaived_errors,
            "unwaived_security_errors": unwaived_security_errors,
        },
        "waivers": {
            "active": len(waivers_active),
            "requested": len(waivers_requested),
            "expiring_soon": len(waivers_expiring_soon),
        },
    }


# --- Trends --------------------------------------------------------------------------------------

#: Evidence-run depth per (subject, scanner) fetched for trend diffing.
TRENDS_RUNS_PER_SCANNER = 64


def load_trend_inputs(
    tenant_id: str, *, project_id: Optional[str] = None, since: datetime
) -> Dict[str, Any]:
    """Load the four row sets :func:`build_trends` consumes for one tenant."""
    return {
        "evidence_rows": db.list_latest_lint_evidence_runs_for_tenant(
            tenant_id,
            project_id=project_id,
            runs_per_scanner=TRENDS_RUNS_PER_SCANNER,
        ),
        "decision_events": db.list_lint_finding_decision_events_for_tenant(
            tenant_id, since=since, project_id=project_id
        ),
        "policy_versions": db.list_style_guide_policy_versions_for_tenant(
            tenant_id, since=since
        ),
        "decisions": db.list_lint_finding_decisions(tenant_id, project_id=project_id),
    }


def build_trends(
    *,
    evidence_rows: Sequence[Mapping[str, Any]],
    decision_events: Sequence[Mapping[str, Any]],
    policy_versions: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
    days: int,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build the daily remediation-vs-policy trend series (pure).

    Genuine remediation is kept separate from policy and coverage change (acceptance
    criterion 4): ``remediated_findings`` counts fingerprints that *disappeared* between two
    consecutive runs of the same scanner and whose decision is NOT waived / false_positive —
    a finding that vanished because it was waived counts under ``waivers_granted`` instead,
    and a policy pack publication is its own series, never folded into remediation.

    Args:
        evidence_rows: Deep per-(subject, scanner) run window, newest first.
        decision_events: Decision audit events in the window, oldest first.
        policy_versions: Policy pack publications in the window, oldest first.
        decisions: Current decision rows (for waiver-expiry and suppression lookups).
        days: Window size in days (>= 1).
        now: Clock (UTC).

    Returns:
        ``{"days": days, "series": [{"date", "new_findings", "remediated_findings",
        "waivers_granted", "waivers_expired", "marked_false_positive",
        "policy_pack_publications"}, ...]}`` oldest day first, one entry per day.
    """
    clock = now or datetime.now(timezone.utc)
    window_days = max(1, int(days))
    start = (clock - timedelta(days=window_days - 1)).date()

    day_keys = [
        (start + timedelta(days=i)).isoformat() for i in range(window_days)
    ]
    zero = {
        "new_findings": 0,
        "remediated_findings": 0,
        "waivers_granted": 0,
        "waivers_expired": 0,
        "marked_false_positive": 0,
        "policy_pack_publications": 0,
    }
    buckets: Dict[str, Dict[str, int]] = {key: dict(zero) for key in day_keys}

    def bucket_for(value: Any) -> Optional[Dict[str, int]]:
        dt = _parse_dt(value)
        if dt is None:
            return None
        return buckets.get(dt.date().isoformat())

    # Evidence diffs: consecutive runs of the same scanner on the same subject.
    grouped = _group_runs_by_subject_scanner(evidence_rows)
    suppressed_states = {"waived", "false_positive"}
    for by_scanner in grouped.values():
        for runs_newest_first in by_scanner.values():
            runs = list(reversed(runs_newest_first))  # oldest -> newest
            previous_fps: Optional[set] = None
            for run in runs:
                current_fps = _run_fingerprints(run)
                bucket = bucket_for(run.get("created_at"))
                if bucket is not None:
                    if previous_fps is None:
                        bucket["new_findings"] += len(current_fps)
                    else:
                        bucket["new_findings"] += len(current_fps - previous_fps)
                        for fp in previous_fps - current_fps:
                            decision = match_decision_for_fingerprint(
                                decisions, fp, project_id=(
                                    str(run["project_id"]) if run.get("project_id") else None
                                ),
                            )
                            state = str((decision or {}).get("state") or "open")
                            if state not in suppressed_states:
                                bucket["remediated_findings"] += 1
                previous_fps = current_fps

    for event in decision_events:
        bucket = bucket_for(event.get("created_at"))
        if bucket is None:
            continue
        after = str(event.get("after_state") or "")
        if after == "waived":
            bucket["waivers_granted"] += 1
        elif after == "false_positive":
            bucket["marked_false_positive"] += 1

    for decision in decisions:
        if str(decision.get("state") or "") != "waived":
            continue
        expires = _parse_dt(decision.get("expires_at"))
        if expires is None or expires > clock:
            continue
        bucket = bucket_for(expires)
        if bucket is not None:
            bucket["waivers_expired"] += 1

    for pack in policy_versions:
        bucket = bucket_for(pack.get("created_at"))
        if bucket is not None:
            bucket["policy_pack_publications"] += 1

    return {
        "days": window_days,
        "series": [{"date": key, **buckets[key]} for key in day_keys],
    }


__all__ = [
    "ACTION_EDIT",
    "ACTION_PUBLISH",
    "BULK_ITEM_CAP",
    "COVERAGE_FILTERS",
    "EXPIRING_SOON_DAYS",
    "FILTER_KEYS",
    "GRADES",
    "SEVERITIES",
    "SORT_KEYS",
    "SUBJECT_TYPES",
    "TRENDS_RUNS_PER_SCANNER",
    "WorkspaceValidationError",
    "build_index_from_rows",
    "build_summary",
    "build_trends",
    "build_workspace_index",
    "facet_counts",
    "filter_findings",
    "load_trend_inputs",
    "normalize_filters",
    "normalize_sort",
    "paginate",
    "required_action_for_transition",
    "sort_findings",
    "transition_error",
]
