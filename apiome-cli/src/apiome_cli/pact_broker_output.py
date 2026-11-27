"""Human output of the ``pact-broker``-compatible ``apiome pact`` commands — PFX-4.1 (#6938).

Each command prints one of three formats, chosen with ``--output`` (``-o``) as on ``pact-broker``:

* ``table`` (default) — aligned columns and the sentences ``pact-broker`` prints, so a log reads
  the same after a pipeline moves over;
* ``json`` — the server's answer, unchanged (also what the root ``--json`` flag selects);
* ``markdown`` — GitHub-flavoured tables and lists, ready for a job summary or a pull-request
  comment.

Every function here is pure: it takes the parsed response and returns lines.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence

#: The ``--output`` choices.
OUTPUT_FORMATS = ("table", "json", "markdown")


def validate_output(value: str) -> str:
    """The ``--output`` value, lower-cased, or a :class:`ValueError` listing the choices."""
    choice = (value or "").strip().lower()
    if choice == "md":
        choice = "markdown"
    if choice not in OUTPUT_FORMATS:
        raise ValueError(f"must be one of {', '.join(OUTPUT_FORMATS)}")
    return choice


def _text(value: Any) -> str:
    """A cell's text: ``''`` for ``None``, ``true`` / ``false`` for booleans, else ``str``."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _md_cell(value: Any) -> str:
    """A markdown table cell: pipes escaped, line breaks flattened."""
    return _text(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def table(headers: Sequence[str], rows: Iterable[Sequence[Any]], fmt: str) -> list[str]:
    """A table as text or markdown.

    Args:
        headers: Column titles.
        rows: The cells, one sequence per row.
        fmt: ``table`` or ``markdown``.

    Returns:
        The lines. A text table pads each column to its widest cell and separates columns with
        ``|``, as ``pact-broker`` does.
    """
    body = [[_text(cell) for cell in row] for row in rows]
    if fmt == "markdown":
        lines = ["| " + " | ".join(_md_cell(h) for h in headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
        lines += ["| " + " | ".join(_md_cell(cell) for cell in row) + " |" for row in body]
        return lines
    widths = [len(h) for h in headers]
    for row in body:
        widths = [max(width, len(cell)) for width, cell in zip(widths, row)]

    def line(cells: Sequence[str]) -> str:
        return " | ".join(cell.ljust(width) for cell, width in zip(cells, widths)).rstrip()

    return [line(list(headers)), "-|-".join("-" * width for width in widths), *(line(row) for row in body)]


def _notice_lines(notices: Any, fmt: str) -> list[str]:
    """The ``notices`` of a response, one line each (a list item in markdown)."""
    lines: list[str] = []
    for notice in notices or []:
        if not isinstance(notice, dict) or not notice.get("text"):
            continue
        kind = notice.get("type")
        prefix = f"{kind}: " if kind and kind not in ("info", "success", "debug") else ""
        lines.append(("- " if fmt == "markdown" else "") + prefix + str(notice["text"]))
    return lines


# ---------------------------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------------------------


def publish_lines(responses: Sequence[Mapping[str, Any]], fmt: str) -> list[str]:
    """What ``publish`` prints: the broker's notices for each request.

    Args:
        responses: One ``POST …/contracts/publish`` answer per request.
        fmt: ``table`` or ``markdown``.

    Returns:
        The lines; a response without notices prints the pacticipant version it recorded.
    """
    lines: list[str] = []
    for response in responses:
        notices = _notice_lines(response.get("notices"), fmt)
        if notices:
            lines += notices
            continue
        version = ((response.get("_embedded") or {}).get("version") or {}).get("number")
        consumer = ((response.get("_embedded") or {}).get("pacticipant") or {}).get("name")
        lines.append(("- " if fmt == "markdown" else "") + f"Published the pacts of {consumer} version {version}")
    return lines


# ---------------------------------------------------------------------------------------------
# list-pacticipants / describe-version
# ---------------------------------------------------------------------------------------------


def pacticipant_lines(records: Sequence[Mapping[str, Any]], fmt: str) -> list[str]:
    """``list-pacticipants``: name, handle, main branch, repository and labels per pacticipant."""
    if not records:
        return ["No pacticipants."]
    return table(
        ("NAME", "HANDLE", "MAIN BRANCH", "REPOSITORY", "LABELS"),
        (
            (
                record.get("name"),
                record.get("slug"),
                record.get("main_branch"),
                record.get("repository_url"),
                ", ".join(str(label) for label in record.get("labels") or []),
            )
            for record in records
        ),
        fmt,
    )


def _names(items: Any) -> str:
    """``[{"name": …}, …]`` as a comma-separated list."""
    return ", ".join(str(item.get("name")) for item in items or [] if isinstance(item, dict) and item.get("name"))


def version_lines(document: Mapping[str, Any], pacticipant: str, fmt: str) -> list[str]:
    """``describe-version``: the version's number, branches, tags, build URL and creation time."""
    embedded = document.get("_embedded") or {}
    return table(
        ("PACTICIPANT", "VERSION", "BRANCHES", "TAGS", "BUILD URL", "CREATED"),
        [
            (
                pacticipant,
                document.get("number"),
                _names(embedded.get("branchVersions")),
                _names(embedded.get("tags")),
                document.get("buildUrl"),
                document.get("createdAt"),
            )
        ],
        fmt,
    )


def native_version_document(record: Mapping[str, Any]) -> dict[str, Any]:
    """A native ``PacticipantVersionRecord`` in the broker's version shape, for one renderer."""
    return {
        "number": record.get("number"),
        "buildUrl": record.get("build_url"),
        "createdAt": record.get("created_at"),
        "_embedded": {
            "branchVersions": [{"name": name} for name in record.get("branches") or []],
            "tags": [{"name": name} for name in record.get("tags") or []],
        },
    }


# ---------------------------------------------------------------------------------------------
# can-i-deploy
# ---------------------------------------------------------------------------------------------


def _version_number(party: Any) -> Optional[str]:
    """``consumer.version.number`` / ``provider.version.number`` of a matrix row."""
    version = party.get("version") if isinstance(party, dict) else None
    return version.get("number") if isinstance(version, dict) else None


def _result_number(row: Mapping[str, Any]) -> str:
    """The verification result's number, from the end of its ``self`` link."""
    result = row.get("verificationResult")
    if not isinstance(result, dict):
        return ""
    href = ((result.get("_links") or {}).get("self") or {}).get("href") or ""
    return href.rsplit("/", 1)[-1] if href else ""


def _success(row: Mapping[str, Any]) -> str:
    """``true`` / ``false`` / ``???`` (no result yet), as ``pact-broker`` prints it."""
    result = row.get("verificationResult")
    if not isinstance(result, dict) or not isinstance(result.get("success"), bool):
        return "???"
    text = "true" if result["success"] else "false"
    return text + (" (ignored)" if row.get("ignored") else "")


def can_i_deploy_lines(
    document: Mapping[str, Any], fmt: str, *, dry_run: bool = False, retries: int = 0
) -> list[str]:
    """``can-i-deploy``: the matrix rows, the verdict, its reason and the notices.

    Args:
        document: The matrix document (``summary``, ``notices``, ``matrix``).
        fmt: ``table`` or ``markdown``.
        dry_run: Say the verdict is not enforced.
        retries: How many times the query was retried while the verdict was unknown.

    Returns:
        The lines: "Computer says yes \\o/" when deployable, "Computer says no ¯\\_(ツ)_/¯" when not,
        "Computer says no ... (unknown)" while a result is missing — the sentences
        ``pact-broker`` prints.
    """
    rows = [row for row in document.get("matrix") or [] if isinstance(row, dict)]
    lines: list[str] = []
    if rows:
        lines += table(
            ("CONSUMER", "C.VERSION", "PROVIDER", "P.VERSION", "SUCCESS?", "RESULT#"),
            (
                (
                    (row.get("consumer") or {}).get("name"),
                    _version_number(row.get("consumer")),
                    (row.get("provider") or {}).get("name"),
                    _version_number(row.get("provider")),
                    _success(row),
                    _result_number(row),
                )
                for row in rows
            ),
            fmt,
        )
        lines.append("")
    summary = document.get("summary") or {}
    verdict = summary.get("deployable") if isinstance(summary, dict) else None
    if verdict is True:
        headline = "Computer says yes \\o/"
    elif verdict is False:
        headline = "Computer says no ¯\\_(ツ)_/¯"
    else:
        headline = "Computer says no ¯\\_(ツ)_/¯ (a verification result is missing)"
    lines.append(f"**{headline}**" if fmt == "markdown" else headline)
    if dry_run:
        lines.append("[dry-run] the verdict is not enforced: exit 0 whatever it says")
    if retries:
        lines.append(f"Retried {retries} time(s) while the verdict was unknown")
    reason = summary.get("reason") if isinstance(summary, dict) else None
    if reason:
        lines += ["", str(reason)]
    notices = _notice_lines(document.get("notices"), fmt)
    if notices:
        lines += ["", *notices]
    return lines


# ---------------------------------------------------------------------------------------------
# environments, deployments, releases, webhooks
# ---------------------------------------------------------------------------------------------


def environment_created_lines(document: Mapping[str, Any]) -> list[str]:
    """``create-environment``: the sentence ``pact-broker`` prints, with the new UUID."""
    return [f"Created {document.get('name')} environment in the Pact Broker with UUID {document.get('uuid')}"]


def recorded_lines(
    kind: str, *, pacticipant: str, version: str, environment: str, application_instance: Optional[str] = None
) -> list[str]:
    """``record-deployment`` / ``record-release``: the sentence ``pact-broker`` prints.

    Args:
        kind: ``deployment`` or ``release``.
        pacticipant: What was deployed or released.
        version: Its version.
        environment: Where.
        application_instance: The instance deployed to, when named.

    Returns:
        One line.
    """
    instance = f" (application instance {application_instance})" if application_instance else ""
    return [
        f"Recorded {kind} of {pacticipant} version {version} to {environment} environment{instance} in the Pact Broker."
    ]


def webhook_created_lines(document: Mapping[str, Any]) -> list[str]:
    """``create-webhook``: what was created, its UUID and its events."""
    events = _names(document.get("events"))
    description = document.get("description") or "Webhook"
    lines = [f"Webhook {description!r} created with UUID {document.get('uuid')}"]
    if events:
        lines.append(f"  events: {events}")
    return lines


# ---------------------------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------------------------


def _counts(counts: Any) -> str:
    """``passed 3, failed 1, …`` from an interaction-count object."""
    if not isinstance(counts, dict):
        return ""
    return ", ".join(f"{key} {value}" for key, value in counts.items() if isinstance(value, int))


def verify_lines(response: Mapping[str, Any], fmt: str) -> list[str]:
    """``verify``: one row per pact, then the run's outcome.

    Args:
        response: The hosted-verifier answer.
        fmt: ``table`` or ``markdown``.

    Returns:
        The lines; a pact that was not published says why.
    """
    pacts = [pact for pact in response.get("pacts") or [] if isinstance(pact, dict)]
    lines: list[str] = []
    if pacts:
        lines += table(
            ("CONSUMER", "C.VERSION", "OUTCOME", "PENDING", "INTERACTIONS", "PUBLISHED"),
            (
                (
                    pact.get("consumer_name") or pact.get("consumer"),
                    pact.get("consumer_version"),
                    pact.get("outcome"),
                    pact.get("pending"),
                    _counts(pact.get("counts")),
                    "yes" if pact.get("published") else f"no ({pact.get('not_published_reason') or 'not published'})",
                )
                for pact in pacts
            ),
            fmt,
        )
        lines.append("")
    target = response.get("target") or {}
    headline = (
        f"Verification of {response.get('provider')} {response.get('provider_version')} against "
        f"{target.get('slug') or target.get('base_url')}: {response.get('outcome')}"
    )
    lines.append(f"**{headline}**" if fmt == "markdown" else headline)
    for pact in pacts:
        for item in pact.get("unsupported") or []:
            if isinstance(item, dict):
                prefix = "- " if fmt == "markdown" else "  "
                lines.append(
                    f"{prefix}not replayed: {item.get('operation_key')} ({item.get('code')}): {item.get('reason')}"
                )
    return lines


# ---------------------------------------------------------------------------------------------
# check (PFX-8.4, #7301)
# ---------------------------------------------------------------------------------------------

#: How ``check`` names an interaction's outcome.
_OUTCOME_WORDS = {"match": "match", "differs": "differs", "not-in-spec": "not in spec"}


def _interaction_name(row: Mapping[str, Any]) -> str:
    """``POST /invoices — 201`` or the interaction's description."""
    if row.get("method") and row.get("path"):
        status = f" — {row['status']}" if row.get("status") is not None else ""
        return f"{row['method']} {row['path']}{status}"
    return str(row.get("description") or f"interaction {row.get('index')}")


def check_lines(checks: Sequence[Mapping[str, Any]], fmt: str) -> list[str]:
    """What ``check`` prints: per pact, one row per provider version, then what did not match.

    Args:
        checks: One ``POST …/pacts/check`` answer per pact file, each with ``file`` added.
        fmt: ``table`` or ``markdown``.

    Returns:
        The lines: a heading per pact, a table of provider versions (selected by, verdict, match /
        differs / not-in-spec counts), each interaction that does not match with its first
        failure, each selector that named nothing with the reason, each version over the limit,
        and a closing verdict line.
    """
    item = "- " if fmt == "markdown" else "  "
    lines: list[str] = []
    passed = 0
    for check in checks:
        consumer = (check.get("consumer") or {}).get("name") or "?"
        provider = (check.get("provider") or {}).get("name") or "?"
        lines.append(f"{'### ' if fmt == 'markdown' else ''}{consumer} → {provider} ({check.get('file')})")
        results = [result for result in check.get("results") or [] if isinstance(result, dict)]
        if results:
            rows = []
            for result in results:
                counts = result.get("counts") or {}
                label = str(result.get("providerVersion")) + (" (draft)" if result.get("draft") else "")
                rows.append(
                    [
                        label,
                        ", ".join(result.get("selectors") or []),
                        result.get("verdict"),
                        counts.get("match", 0),
                        counts.get("differs", 0),
                        counts.get("notInSpec", 0),
                    ]
                )
            lines += table(["Provider version", "Selected by", "Verdict", "Match", "Differs", "Not in spec"], rows, fmt)
            for result in results:
                if result.get("error"):
                    lines.append(f"{item}{result.get('providerVersion')}: could not compare: {result['error']}")
                for row in result.get("interactions") or []:
                    if row.get("outcome") == "match":
                        continue
                    first = (row.get("failures") or [{}])[0]
                    why = f": {first.get('code')}: {first.get('message')}" if first.get("code") else ""
                    lines.append(
                        f"{item}{result.get('providerVersion')}: {_interaction_name(row)} "
                        f"{_OUTCOME_WORDS.get(row.get('outcome'), row.get('outcome'))}{why}"
                    )
        for entry in check.get("unresolved") or []:
            lines.append(f"{item}not compared: {entry.get('selector')} — {entry.get('reason')}")
        for entry in check.get("skipped") or []:
            lines.append(f"{item}skipped: {entry.get('providerVersion')} ({entry.get('selector')}) — {entry.get('reason')}")
        if (check.get("summary") or {}).get("success"):
            passed += 1
    total = len(checks)
    if passed == total:
        lines.append(f"Every pact matches every provider version checked ({total} pact{'s' if total != 1 else ''}).")
    else:
        lines.append(f"{total - passed} of {total} pacts would not pass against every provider version checked.")
    lines.append("Nothing was published.")
    return lines
