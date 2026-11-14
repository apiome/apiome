"""Rules for ``apiome primitives import <file>`` (CLI 5.6, #3222) — no I/O, no HTTP.

The file holds *rows*; the REST API takes a *type-definition bundle*. This module turns one into
the other and reads the answers back:

* :func:`parse_rows` — the rows of a document: an array, one row, or ``{"items": [...]}``;
* :func:`convert_rows` — each row checked locally and turned into a JSON Schema;
* :func:`bundle_payload` — the body of ``POST /v1/primitives/{tenant}/import[/review]``;
* :func:`review_outcomes` / :func:`commit_outcomes` — one :class:`RowOutcome` per row from the
  review (dry run) and from the import;
* :func:`render_plan` / :func:`render_summary` / :func:`build_report` — what the user reads.

A row is either *shorthand* (``name``, ``base``, then any JSON Schema keyword such as ``pattern``
or ``examples``) or a *REST row* (``name`` and ``schema``, as ``apiome types list --json`` prints).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from apiome_cli.property_create import check_examples

#: The values ``base`` may take: the JSON Schema types.
BASE_TYPES = ("string", "number", "integer", "boolean", "object", "array", "null")

#: A file with more rows than this shows a progress bar while it is checked.
PROGRESS_THRESHOLD = 50

#: The ``source_kind`` the rows are sent as: a bundle of named types.
SOURCE_KIND = "type-def-bundle"

#: The name the import route gives to a failure that is not a row (the audit record).
PROVENANCE_ROW = "_provenance"

# Row statuses. The first group describes a plan (review), the second a finished import.
STATUS_NEW = "new"
STATUS_OVERWRITE = "overwrite"
STATUS_CONFLICT = "conflict"
STATUS_UNCHANGED = "unchanged"
STATUS_SYSTEM = "system"
STATUS_INVALID = "invalid"
STATUS_ABORTED = "aborted"
STATUS_IMPORTED = "imported"
STATUS_UPDATED = "updated"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"

#: Statuses that count as a row failure (exit 7 unless ``--continue-on-error``).
FAILURE_STATUSES = (STATUS_INVALID, STATUS_FAILED)

#: Statuses that write to the tenant when the plan is committed.
WRITE_STATUSES = (STATUS_NEW, STATUS_OVERWRITE)

#: Order of the counts in a report's ``summary``.
_SUMMARY_ORDER = (
    STATUS_NEW,
    STATUS_OVERWRITE,
    STATUS_CONFLICT,
    STATUS_IMPORTED,
    STATUS_UPDATED,
    STATUS_SKIPPED,
    STATUS_UNCHANGED,
    STATUS_SYSTEM,
    STATUS_INVALID,
    STATUS_FAILED,
    STATUS_ABORTED,
)


class ImportFileError(ValueError):
    """The document is not something to import (exit 2): wrong shape, or no rows."""


@dataclass(frozen=True)
class ImportRow:
    """One row that passed the local checks.

    Attributes:
        index: Position in the file, from 1.
        name: The primitive's name.
        schema: Its JSON Schema, as it will be sent.
    """

    index: int
    name: str
    schema: dict[str, Any]


@dataclass(frozen=True)
class RowOutcome:
    """What happened, or would happen, to one row.

    Attributes:
        index: Position in the file, from 1.
        name: The row's name, or ``None`` when it has none.
        status: One of the ``STATUS_*`` values.
        message: Why, for the statuses that need a reason; otherwise empty.
    """

    index: int
    name: Optional[str]
    status: str
    message: str = ""

    @property
    def label(self) -> str:
        """``row 3 (acme-id)`` — how the row is named in messages."""
        return f"row {self.index} ({self.name})" if self.name else f"row {self.index}"


def parse_rows(document: Any) -> list[Any]:
    """The rows of a parsed JSON or YAML document.

    Args:
        document: An array of rows, one row (an object with ``name``), or an object with an
            ``items`` array — what ``apiome types list --json`` prints.

    Returns:
        The rows, unchecked.

    Raises:
        ImportFileError: The document is none of those shapes, or holds no rows.
    """
    if isinstance(document, list):
        rows = document
    elif isinstance(document, dict) and "name" not in document and isinstance(document.get("items"), list):
        rows = document["items"]
    elif isinstance(document, dict) and "name" in document:
        rows = [document]
    else:
        raise ImportFileError(
            "must hold one primitive (an object with a name), an array of primitives, "
            'or an object with an "items" array.'
        )
    if not rows:
        raise ImportFileError("holds no primitives.")
    return rows


def _row_schema(row: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The JSON Schema of one row, and the problems found building it.

    A REST row's ``schema`` is used as it is, with the row's ``description`` and ``tags`` copied in
    when the schema has none: the import reads both from the schema, so leaving them out would
    blank them on ``--update``. A shorthand row's keys are the schema, with ``base`` as ``type``.
    """
    problems: list[str] = []
    if "schema" in row:
        schema = row["schema"]
        if not isinstance(schema, dict):
            return {}, ["schema: must be an object"]
        schema = dict(schema)
        if isinstance(row.get("description"), str) and row["description"].strip():
            schema.setdefault("description", row["description"])
        if isinstance(row.get("tags"), list) and row["tags"]:
            schema.setdefault("tags", list(row["tags"]))
        return schema, problems

    schema = {key: value for key, value in row.items() if key not in ("name", "base")}
    base = row.get("base", schema.get("type"))
    if "base" in row and "type" in schema and schema["type"] != row["base"]:
        problems.append("base: differs from type; give one of them")
    if base is None:
        problems.append(f"base: is required (one of {', '.join(BASE_TYPES)}), or give a schema")
    elif base not in BASE_TYPES:
        problems.append(f"base: {base!r} is not one of {', '.join(BASE_TYPES)}")
    else:
        schema = {"type": base, **{key: value for key, value in schema.items() if key != "type"}}
    return schema, problems


def _schema_problems(schema: Mapping[str, Any]) -> list[str]:
    """Problems with a row's schema that can be found without the server.

    Checks that ``pattern`` is a regular expression, that the schema is valid JSON Schema
    2020-12, and that each of its ``examples`` satisfies it.
    """
    problems: list[str] = []
    pattern = schema.get("pattern")
    if isinstance(pattern, str):
        try:
            re.compile(pattern)
        except re.error as exc:
            problems.append(f"pattern: not a regular expression ({exc})")
    try:
        Draft202012Validator.check_schema(dict(schema))
    except SchemaError as exc:
        where = "/".join(str(part) for part in exc.absolute_path)
        problems.append(f"schema{'.' + where if where else ''}: {exc.message}")
        return problems
    examples = schema.get("examples")
    if isinstance(examples, list) and not problems:
        errors, _warnings = check_examples(schema, examples)
        problems.extend(str(error) for error in errors)
    return problems


def convert_rows(
    rows: Sequence[Any], *, on_row: Optional[Callable[[], None]] = None
) -> tuple[list[ImportRow], list[RowOutcome]]:
    """Check every row locally and turn the good ones into schemas.

    Args:
        rows: The rows from :func:`parse_rows`.
        on_row: Called once per row checked (drives the progress bar).

    Returns:
        ``(rows, outcomes)``: the rows to send, and an outcome for each row that is not sent —
        ``invalid`` with every problem found, or ``system`` for a read-only system primitive.
    """
    accepted: list[ImportRow] = []
    outcomes: list[RowOutcome] = []
    seen: dict[str, int] = {}
    for index, row in enumerate(rows, start=1):
        if on_row is not None:
            on_row()
        if not isinstance(row, dict):
            outcomes.append(RowOutcome(index, None, STATUS_INVALID, "must be an object with a name"))
            continue
        raw_name = row.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) else None
        if row.get("is_system") is True:
            outcomes.append(RowOutcome(index, name, STATUS_SYSTEM, "System primitives are read-only."))
            continue
        problems: list[str] = []
        if not name:
            problems.append("name: is required")
        elif name in seen:
            problems.append(f"name: {name!r} is already used by row {seen[name]}")
        schema, schema_problems = _row_schema(row)
        problems.extend(schema_problems)
        if not schema_problems:
            problems.extend(_schema_problems(schema))
        if problems:
            outcomes.append(RowOutcome(index, name or None, STATUS_INVALID, "; ".join(problems)))
            continue
        seen[name] = index
        accepted.append(ImportRow(index, name, schema))
    return accepted, outcomes


def bundle_payload(
    rows: Sequence[ImportRow], *, source_label: str, overwrite: Iterable[str] = ()
) -> dict[str, Any]:
    """The body of the review and import requests: the rows as a type-definition bundle.

    Args:
        rows: The rows to send.
        source_label: The file name (or ``stdin``), kept on the import's audit record.
        overwrite: Names of existing primitives to overwrite; every other conflict is kept.

    Returns:
        A ``PrimitiveImportRequest`` body.
    """
    payload: dict[str, Any] = {
        "schema": {"types": {row.name: row.schema for row in rows}},
        "source_kind": SOURCE_KIND,
        "source_label": source_label,
        "import_all": True,
    }
    resolutions = {name: {"action": "overwrite"} for name in overwrite}
    if resolutions:
        payload["resolutions"] = resolutions
    return payload


def _error_message(error: Any) -> str:
    """One line from the ``error`` the API attaches to a row it rejects."""
    if not isinstance(error, dict):
        return str(error) if error else "rejected by the server"
    details = error.get("details")
    if isinstance(details, list) and details:
        parts = []
        for detail in details:
            if isinstance(detail, dict) and detail.get("message"):
                path = detail.get("path")
                parts.append(f"{path}: {detail['message']}" if path and path != "(root)" else str(detail["message"]))
            else:
                parts.append(str(detail))
        return "; ".join(parts)
    if isinstance(details, str) and details:
        return details
    return str(error.get("error") or "rejected by the server")


def review_outcomes(rows: Sequence[ImportRow], review: Mapping[str, Any], *, update: bool) -> list[RowOutcome]:
    """One outcome per row from ``POST …/import/review``: what an import would do.

    Args:
        rows: The rows that were reviewed.
        review: The review response; ``types`` classifies each row.
        update: Whether ``--update`` was passed, so a conflict would be overwritten.

    Returns:
        ``new``, ``overwrite`` or ``conflict``, ``unchanged`` and ``invalid`` outcomes, in file
        order. A row the review does not mention is ``invalid``.
    """
    reviewed = {
        entry.get("name"): entry
        for entry in (review.get("types") or [])
        if isinstance(entry, dict)
    }
    outcomes: list[RowOutcome] = []
    for row in rows:
        entry = reviewed.get(row.name)
        status = entry.get("status") if entry else None
        if status == "new":
            outcomes.append(RowOutcome(row.index, row.name, STATUS_NEW))
        elif status == "identical":
            outcomes.append(RowOutcome(row.index, row.name, STATUS_UNCHANGED))
        elif status == "conflict":
            outcomes.append(RowOutcome(row.index, row.name, STATUS_OVERWRITE if update else STATUS_CONFLICT))
        elif entry is None:
            outcomes.append(RowOutcome(row.index, row.name, STATUS_INVALID, "not accepted as a type by the server"))
        else:
            outcomes.append(RowOutcome(row.index, row.name, STATUS_INVALID, _error_message(entry.get("error"))))
    return outcomes


def commit_outcomes(rows: Sequence[ImportRow], result: Mapping[str, Any]) -> list[RowOutcome]:
    """One outcome per row from ``POST …/import``: what the import did.

    Args:
        rows: The rows that were sent.
        result: The import response (``imported``, ``overwritten``, ``identical``, ``skipped``,
            ``errors``).

    Returns:
        ``imported``, ``updated``, ``unchanged``, ``skipped`` and ``failed`` outcomes, in file
        order. A row the response does not mention is ``failed``.
    """
    imported = set(result.get("imported") or [])
    updated = set(result.get("overwritten") or [])
    unchanged = set(result.get("identical") or [])
    skipped = set(result.get("skipped") or [])
    errors = {
        entry.get("name"): entry
        for entry in (result.get("errors") or [])
        if isinstance(entry, dict)
    }
    outcomes: list[RowOutcome] = []
    for row in rows:
        if row.name in errors:
            outcomes.append(RowOutcome(row.index, row.name, STATUS_FAILED, _error_message(errors[row.name])))
        elif row.name in imported:
            outcomes.append(RowOutcome(row.index, row.name, STATUS_IMPORTED))
        elif row.name in updated:
            outcomes.append(RowOutcome(row.index, row.name, STATUS_UPDATED))
        elif row.name in unchanged:
            outcomes.append(RowOutcome(row.index, row.name, STATUS_UNCHANGED))
        elif row.name in skipped:
            outcomes.append(
                RowOutcome(row.index, row.name, STATUS_SKIPPED, "Already exists; pass --update to overwrite.")
            )
        else:
            outcomes.append(RowOutcome(row.index, row.name, STATUS_FAILED, "not reported by the server"))
    return outcomes


def provenance_warning(result: Mapping[str, Any]) -> Optional[str]:
    """The import's audit-record failure, if it reported one — a warning, not a row failure."""
    for entry in result.get("errors") or []:
        if isinstance(entry, dict) and entry.get("name") == PROVENANCE_ROW:
            return _error_message(entry)
    return None


def abort_outcomes(rows: Sequence[ImportRow]) -> list[RowOutcome]:
    """Outcomes for good rows that were not imported because another row failed."""
    return [
        RowOutcome(row.index, row.name, STATUS_ABORTED, "Not imported because another row failed.")
        for row in rows
    ]


def has_failures(outcomes: Iterable[RowOutcome]) -> bool:
    """Whether any row is invalid or failed."""
    return any(outcome.status in FAILURE_STATUSES for outcome in outcomes)


def describe_schema(schema: Mapping[str, Any]) -> str:
    """A short description of a schema for the plan, e.g. ``string, pattern ^LM-[0-9]{8}$``."""
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = " | ".join(str(item) for item in kind)
    parts = [str(kind) if kind else ("$ref" if "$ref" in schema else "any")]
    if isinstance(schema.get("format"), str):
        parts.append(f"format {schema['format']}")
    if isinstance(schema.get("pattern"), str):
        parts.append(f"pattern {schema['pattern']}")
    if isinstance(schema.get("enum"), list):
        parts.append(f"{len(schema['enum'])} values")
    return ", ".join(parts)


def _plural(count: int, noun: str = "primitive") -> str:
    """``1 primitive`` / ``3 primitives``."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _named(outcomes: Sequence[RowOutcome], status: str) -> list[RowOutcome]:
    """The outcomes with one status, in file order."""
    return [outcome for outcome in outcomes if outcome.status == status]


def _failure_lines(outcomes: Sequence[RowOutcome], status: str) -> list[str]:
    """``! row 3 (name): message`` lines for one failure status."""
    return [f"    ! {outcome.label}: {outcome.message}" for outcome in _named(outcomes, status)]


def render_plan(outcomes: Sequence[RowOutcome], rows: Sequence[ImportRow]) -> str:
    """The dry-run text: what would be imported, the conflicts, and the rows that cannot be.

    Args:
        outcomes: Every row's outcome so far (local checks and the review).
        rows: The checked rows, for each new primitive's schema description.

    Returns:
        The indented block the command prints before asking, or as the whole of ``--dry-run``.
    """
    schemas = {row.index: row.schema for row in rows}
    new = _named(outcomes, STATUS_NEW)
    overwrite = _named(outcomes, STATUS_OVERWRITE)
    conflicts = _named(outcomes, STATUS_CONFLICT)
    unchanged = _named(outcomes, STATUS_UNCHANGED)
    system = _named(outcomes, STATUS_SYSTEM)
    lines: list[str] = []
    if new:
        width = max(len(str(outcome.name)) for outcome in new)
        lines.append(f"  Would import {_plural(len(new))}:")
        lines.extend(
            f"    + {str(outcome.name).ljust(width)}  ({describe_schema(schemas.get(outcome.index, {}))})"
            for outcome in new
        )
    else:
        lines.append("  No new primitives to import.")
    if overwrite:
        lines.append(f"  Would overwrite {_plural(len(overwrite), 'existing primitive')}:")
        lines.extend(f"    ~ {outcome.name}  (already exists, overwritten by --update)" for outcome in overwrite)
    if conflicts:
        lines.append("  Conflicts (skipped without --update):")
        lines.extend(
            f"    ~ {outcome.name}  (already exists, would be overwritten with --update)" for outcome in conflicts
        )
    if unchanged:
        lines.append(f"  Unchanged: {_plural(len(unchanged))} already identical.")
    if system:
        lines.append(f"  Skipped: {_plural(len(system), 'system primitive')} (read-only).")
    invalid = _failure_lines(outcomes, STATUS_INVALID)
    if invalid:
        lines.append("  Invalid:")
        lines.extend(invalid)
    return "\n".join(lines)


def render_summary(outcomes: Sequence[RowOutcome]) -> str:
    """The text after an import: what was written, what was left alone, and what failed."""
    imported = len(_named(outcomes, STATUS_IMPORTED))
    updated = len(_named(outcomes, STATUS_UPDATED))
    skipped = len(_named(outcomes, STATUS_SKIPPED))
    unchanged = len(_named(outcomes, STATUS_UNCHANGED))
    if imported or updated:
        lines = [f"  ✔ Imported {imported} new, updated {_plural(updated, 'existing primitive')}."]
    else:
        lines = ["  No primitives were imported or updated."]
    if skipped:
        lines.append(f"  Skipped {_plural(skipped, 'conflict')} (pass --update to overwrite).")
    if unchanged:
        lines.append(f"  Unchanged: {_plural(unchanged)} already identical.")
    failures = _failure_lines(outcomes, STATUS_INVALID) + _failure_lines(outcomes, STATUS_FAILED)
    if failures:
        lines.append(f"  Failed: {_plural(len(failures), 'row')}.")
        lines.extend(failures)
    return "\n".join(lines)


def build_report(
    outcomes: Sequence[RowOutcome],
    *,
    source: str,
    tenant: Optional[str],
    committed: bool,
    import_id: Optional[str] = None,
) -> dict[str, Any]:
    """The per-row report ``--report`` writes and ``--json`` prints.

    Args:
        outcomes: Every row's outcome.
        source: The file name, or ``stdin``.
        tenant: The tenant slug, or ``None`` when the run stopped before reaching the API.
        committed: Whether the import request was sent; ``False`` for a dry run or a refusal.
        import_id: The id of the import's audit record, when the import ran.

    Returns:
        ``{"source", "tenant", "dryRun", "importId", "summary", "rows"}`` — ``summary`` counts the
        rows by status and ``rows`` lists them in file order.
    """
    ordered = sorted(outcomes, key=lambda outcome: outcome.index)
    counts = {status: len(_named(ordered, status)) for status in _SUMMARY_ORDER}
    return {
        "source": source,
        "tenant": tenant,
        "dryRun": not committed,
        "importId": import_id,
        "summary": {"total": len(ordered), **{status: count for status, count in counts.items() if count}},
        "rows": [
            {"row": outcome.index, "name": outcome.name, "status": outcome.status, "message": outcome.message}
            for outcome in ordered
        ],
    }
