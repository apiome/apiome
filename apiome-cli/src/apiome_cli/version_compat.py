"""The rules of ``apiome versions compatibility`` (CLI 4.8, #3215).

The command compares two revisions of one project with the server's native compatibility engine
(``POST /v1/versions/{tenant}/{project}/compatibility``) and turns its findings into a CI verdict.
These functions hold every decision the command makes, without HTTP:

* :func:`default_head` / :func:`default_base` — head defaults to the latest version, base to the
  most recent **published** version older than head;
* :func:`classify` — each finding's severity (``breaking`` → ``error``, ``unknown`` → ``warn``,
  ``safe`` → ``info``), its kind (addition / removal / change), and whether ``--ignore`` or
  ``--allow-removals`` suppresses it for the exit code;
* :func:`render_table` / :func:`render_result` — the human report;
* :func:`to_json` / :func:`to_sarif` — the machine reports (SARIF 2.1.0 for GitHub code scanning).

Exit codes: ``0`` no unsuppressed breaking change, ``6`` at least one, ``8`` the server could not
be reached or failed fetching either side.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

#: Finding category (server) → severity (CLI, SARIF level in :data:`_SARIF_LEVEL`).
SEVERITY_OF_CATEGORY = {"breaking": "error", "unknown": "warn", "safe": "info"}
SEVERITIES = ("error", "warn", "info")
_RANK = {"info": 0, "warn": 1, "error": 2}
_SARIF_LEVEL = {"error": "error", "warn": "warning", "info": "note"}
_KIND_MARK = {"addition": "+ addition", "removal": "- removal", "change": "~ change"}

SARIF_SCHEMA = "https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json"
TOOL_NAME = "apiome versions compatibility"


class CompatError(ValueError):
    """An argument the command refuses, with a message for stderr (exit 2)."""


def _instant(value: Any) -> float:
    if isinstance(value, str) and value.strip():
        try:
            moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return float("-inf")
        return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp()
    return float("-inf")


def _newest_first(versions: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(versions, key=lambda v: _instant(v.get("created_at")), reverse=True)


def default_head(versions: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """The latest version (most recently created, published or not).

    Raises:
        CompatError: When the project has no versions.
    """
    ordered = _newest_first(versions)
    if not ordered:
        raise CompatError("The project has no versions to compare.")
    return ordered[0]


def default_base(versions: Sequence[Mapping[str, Any]], head: Mapping[str, Any]) -> Mapping[str, Any]:
    """The most recent **published** version created before ``head``.

    Raises:
        CompatError: When there is none — pass ``--base``.
    """
    head_at = _instant(head.get("created_at"))
    for version in _newest_first(versions):
        if str(version.get("id")) == str(head.get("id")) or not version.get("published"):
            continue
        if _instant(version.get("created_at")) <= head_at:
            return version
    raise CompatError(
        f"No published version older than {head.get('version_id')} to compare against; pass --base."
    )


def normalize_rule(rule: str) -> str:
    """``removed-path`` / ``Path-Removed`` / ``path_removed`` → ``path_removed``.

    The server's rule ids are ``<subject>_<change>`` (``path_removed``, ``enum_narrowed``); a
    two-word id written the other way round (``removed-path``, ``narrowed-enum``) is accepted too.
    """
    words = [w for w in rule.strip().lower().replace("-", "_").split("_") if w]
    if len(words) == 2 and words[0].endswith("ed") and not words[1].endswith("ed"):
        words.reverse()
    return "_".join(words)


def _kind(rule: str) -> str:
    if rule.endswith("_removed"):
        return "removal"
    if rule.endswith("_added") and not rule.startswith("required_"):
        return "addition"
    return "change"


@dataclass(frozen=True)
class Finding:
    """One server finding as the command reports it."""

    id: str
    rule: str
    path: str
    message: str
    #: Severity before suppression (from the server's category).
    original_severity: str
    #: Severity after ``--allow-removals``.
    severity: str
    kind: str
    #: ``ignore`` (``--ignore``) or ``allow-removals``; ``None`` when it counts.
    suppressed_by: Optional[str]

    @property
    def breaking(self) -> bool:
        """Whether this finding fails the gate (exit 6)."""
        return self.severity == "error" and self.suppressed_by is None


def classify(
    findings: Sequence[Mapping[str, Any]],
    *,
    ignore: Iterable[str] = (),
    allow_removals: bool = False,
) -> list[Finding]:
    """Turn the server's findings into :class:`Finding` s, applying the suppressions.

    Args:
        findings: ``findings`` from ``POST …/compatibility`` (``id``, ``path``, ``category``,
            ``rule``, ``message``).
        ignore: ``--ignore`` rule ids (any spelling :func:`normalize_rule` accepts).
        allow_removals: ``--allow-removals`` — a breaking removal becomes a warning.

    Returns:
        The findings, most severe first, then by path and rule.
    """
    ignored = {normalize_rule(r) for r in ignore if r.strip()}
    out: list[Finding] = []
    for raw in findings:
        rule = str(raw.get("rule") or "")
        original = SEVERITY_OF_CATEGORY.get(str(raw.get("category") or ""), "warn")
        kind = _kind(rule)
        severity, suppressed = original, None
        if rule in ignored:
            suppressed = "ignore"
        elif allow_removals and kind == "removal" and original == "error":
            severity, suppressed = "warn", "allow-removals"
        out.append(
            Finding(
                id=str(raw.get("id") or ""),
                rule=rule,
                path=str(raw.get("path") or ""),
                message=str(raw.get("message") or ""),
                original_severity=original,
                severity=severity,
                kind=kind,
                suppressed_by=suppressed,
            )
        )
    return sorted(out, key=lambda f: (-_RANK[f.severity], f.path, f.rule, f.id))


def at_least(findings: Sequence[Finding], severity: str) -> list[Finding]:
    """``--severity``: the findings at ``severity`` or above (display only; the exit code ignores it)."""
    floor = _RANK[severity]
    return [f for f in findings if _RANK[f.severity] >= floor]


def breaking(findings: Sequence[Finding]) -> list[Finding]:
    """The findings that fail the gate."""
    return [f for f in findings if f.breaking]


def render_table(findings: Sequence[Finding]) -> str:
    """The findings as a two-column box table, or a one-line note when there are none."""
    if not findings:
        return "  No findings."
    rows = []
    for f in findings:
        label = f"{'✖' if f.breaking else '!' if f.severity == 'warn' else '·'} {f.severity}"
        note = f" [{f.suppressed_by}]" if f.suppressed_by else ""
        rows.append((label, f"{_KIND_MARK[f.kind]}  {f.rule}  {f.path} — {f.message}{note}"))
    left = max(len("SEVERITY"), *(len(r[0]) for r in rows))
    right = max(len("FINDING"), *(len(r[1]) for r in rows))

    def line(a: str, b: str) -> str:
        return f"  ║ {a.ljust(left)} │ {b.ljust(right)} ║"

    return "\n".join(
        [
            f"  ╔{'═' * (left + 2)}╤{'═' * (right + 2)}╗",
            line("SEVERITY", "FINDING"),
            f"  ╠{'═' * (left + 2)}╪{'═' * (right + 2)}╣",
            *(line(a, b) for a, b in rows),
            f"  ╚{'═' * (left + 2)}╧{'═' * (right + 2)}╝",
        ]
    )


def render_result(findings: Sequence[Finding]) -> str:
    """The verdict line(s) under the table."""
    failing = breaking(findings)
    suppressed = [f for f in findings if f.suppressed_by]
    if failing:
        shown = ", ".join(f"{f.rule} {f.path}" for f in failing[:3])
        more = f", and {len(failing) - 3} more" if len(failing) > 3 else ""
        noun = "change" if len(failing) == 1 else "changes"
        line = f"Result: {len(failing)} breaking {noun} found ({shown}{more})."
    else:
        line = "Result: no breaking changes."
    if suppressed:
        line += f" {len(suppressed)} suppressed (--ignore / --allow-removals)."
    return line


def _side(version: Mapping[str, Any]) -> dict[str, Any]:
    return {"id": str(version.get("id")), "version": version.get("version_id")}


def to_json(
    *,
    base: Mapping[str, Any],
    head: Mapping[str, Any],
    report: Mapping[str, Any],
    findings: Sequence[Finding],
    exit_code: int,
) -> dict[str, Any]:
    """The ``--json`` document: both sides, the verdict, and every finding (suppressed ones too)."""
    return {
        "base": _side(base),
        "head": _side(head),
        "overall": report.get("overall"),
        "reportFingerprint": report.get("reportFingerprint"),
        "breaking": len(breaking(findings)),
        "exitCode": exit_code,
        "findings": [
            {
                "id": f.id,
                "rule": f.rule,
                "severity": f.severity,
                "originalSeverity": f.original_severity,
                "kind": f.kind,
                "path": f.path,
                "message": f.message,
                "breaking": f.breaking,
                "suppressedBy": f.suppressed_by,
            }
            for f in findings
        ],
    }


def to_sarif(
    *,
    findings: Sequence[Finding],
    artifact_uri: str,
    tool_version: str,
    base: Mapping[str, Any],
    head: Mapping[str, Any],
) -> dict[str, Any]:
    """A SARIF 2.1.0 log for GitHub code scanning.

    Each finding is a result on ``artifact_uri`` (the head version's spec URL path), with its JSON
    path as a logical location; suppressed findings carry a SARIF ``suppressions`` entry so code
    scanning shows them as dismissed rather than dropping them.
    """
    rule_ids = sorted({f.rule for f in findings})
    rules = [
        {
            "id": rule,
            "name": rule,
            "shortDescription": {"text": rule.replace("_", " ")},
            "properties": {"tags": ["api-compatibility"]},
        }
        for rule in rule_ids
    ]
    results = []
    for f in findings:
        result: dict[str, Any] = {
            "ruleId": f.rule,
            "ruleIndex": rule_ids.index(f.rule),
            "level": _SARIF_LEVEL[f.severity],
            "message": {"text": f"{f.path}: {f.message}"},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": artifact_uri},
                        "region": {"startLine": 1},
                    },
                    "logicalLocations": [{"fullyQualifiedName": f.path, "kind": "member"}],
                }
            ],
            "partialFingerprints": {"apiomeFindingId": f.id},
        }
        if f.suppressed_by:
            result["suppressions"] = [{"kind": "external", "justification": f"--{f.suppressed_by}"}]
        results.append(result)
    return {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": TOOL_NAME,
                        "version": tool_version,
                        "informationUri": "https://github.com/apiome/apiome",
                        "rules": rules,
                    }
                },
                "results": results,
                "properties": {"base": _side(base), "head": _side(head)},
            }
        ],
    }
