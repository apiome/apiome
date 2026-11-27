"""The report ``apiome pact migrate`` prints — PFX-6.7 (#6959).

One table of counts per record kind, then everything not portable (with what to do), every record
the server refused (with its reason), what the migration never reads, and where the resume state is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from apiome_cli.pact_broker_output import table
from apiome_cli.pact_migration_plan import KINDS, NOT_READ, Finding

#: The columns of an import's table and of a dry run's.
_IMPORT_COLUMNS = ("created", "updated", "unchanged", "refused")
_CHECK_COLUMNS = ("would-create", "exists", "refused")


@dataclass
class MigrationSummary:
    """What a run did, kind by kind.

    Attributes:
        dry_run: Whether it was a check.
        counts: ``{kind: {outcome: n}}`` from the server's answers.
        skipped: ``{kind: n}`` records skipped because an earlier run imported them.
        refused: ``(kind, source key, code, message)`` of every refused record.
    """

    dry_run: bool
    counts: dict[str, dict[str, int]] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    refused: list[tuple[str, str, str, str]] = field(default_factory=list)

    def add(self, kind: str, key: str, result: Mapping[str, Any]) -> None:
        """Count one record's outcome (and remember a refusal)."""
        outcome = str(result.get("outcome") or "refused")
        per_kind = self.counts.setdefault(kind, {})
        per_kind[outcome] = per_kind.get(outcome, 0) + 1
        if outcome == "refused":
            self.refused.append(
                (
                    kind,
                    key,
                    str(result.get("code") or ""),
                    str(result.get("message") or ""),
                )
            )

    def refuse(self, kind: str, key: str, code: str, message: str) -> None:
        """Count a record refused before it was sent (the source could not return its document)."""
        self.add(kind, key, {"outcome": "refused", "code": code, "message": message})


def _key_label(key: str) -> str:
    """A source key without its ``kind:`` prefix."""
    return key.split(":", 1)[1] if ":" in key else key


def migration_document(
    summary: MigrationSummary,
    *,
    source: str,
    tenant: str,
    read_counts: Mapping[str, int],
    findings: list[Finding],
    state_file: Optional[str],
) -> dict[str, Any]:
    """The JSON form of the report.

    Args:
        summary: What the run did.
        source: The source broker.
        tenant: The target workspace.
        read_counts: How many items of each kind the source returned.
        findings: What is not portable.
        state_file: The resume state written, or ``None`` for a dry run.

    Returns:
        ``{source, tenant, dry_run, kinds, refused, not_portable, not_read, state_file}``.
    """
    return {
        "source": source,
        "tenant": tenant,
        "dry_run": summary.dry_run,
        "kinds": {
            kind: {
                "read": read_counts.get(kind, 0),
                "skipped": summary.skipped.get(kind, 0),
                **summary.counts.get(kind, {}),
            }
            for kind in KINDS
        },
        "refused": [
            {"kind": kind, "key": _key_label(key), "code": code, "message": message}
            for kind, key, code, message in summary.refused
        ],
        "not_portable": [
            {"kind": f.kind, "subject": f.subject, "detail": f.detail} for f in findings
        ],
        "not_read": list(NOT_READ),
        "state_file": state_file,
    }


def migration_lines(
    summary: MigrationSummary,
    *,
    source: str,
    tenant: str,
    read_counts: Mapping[str, int],
    findings: list[Finding],
    state_file: Optional[str],
    fmt: str,
) -> list[str]:
    """The report as text or markdown.

    Args:
        summary: What the run did.
        source: The source broker.
        tenant: The target workspace.
        read_counts: How many items of each kind the source returned.
        findings: What is not portable.
        state_file: The resume state written, or ``None`` for a dry run.
        fmt: ``table`` or ``markdown``.

    Returns:
        The lines.
    """
    bullet = "- " if fmt == "markdown" else "  - "
    title = f"Migration from {source} to workspace {tenant}" + (
        " (dry run: nothing was written)" if summary.dry_run else ""
    )
    columns = _CHECK_COLUMNS if summary.dry_run else _IMPORT_COLUMNS
    rows = [
        [
            kind,
            read_counts.get(kind, 0),
            *(summary.counts.get(kind, {}).get(c, 0) for c in columns),
            summary.skipped.get(kind, 0),
        ]
        for kind in KINDS
    ]
    headers = ["Kind", "Read", *(c.capitalize() for c in columns), "Done earlier"]
    lines = [title, "", *table(headers, rows, fmt)]

    lines += [
        "",
        f"Not portable ({len(findings)}):" if findings else "Not portable: nothing.",
    ]
    lines += [f"{bullet}{f.kind} {f.subject}: {f.detail}" for f in findings]

    if summary.refused:
        verb = "Would be refused" if summary.dry_run else "Refused"
        lines += ["", f"{verb} ({len(summary.refused)}):"]
        lines += [
            f"{bullet}{kind} {_key_label(key)}: {code}: {message}"
            for kind, key, code, message in summary.refused
        ]

    lines += ["", "Not read from the source:"]
    lines += [f"{bullet}{item}" for item in NOT_READ]
    if state_file:
        lines += [
            "",
            f"Progress is saved in {state_file}: run the same command again to retry what was refused.",
        ]
    return lines
