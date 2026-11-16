"""``apiome usage`` — feed the runtime usage index from the command line (RDG-1.4, #5762).

``apiome usage upload file.har --project pets --environment staging`` turns a browser devtools or
proxy recording into ``apiome.usage.event/v1`` events and posts them to the ingest door
(``POST …/usage/ingest``), so a developer gets a drift report before anyone wires a Collector:

1. The file is read **twice**, streaming: once to check it is a HAR archive (nothing is sent from
   a broken file), once to build and post the events.
2. The project's ``har`` source for the environment is found or created on the server
   (``POST …/usage/sources/har``); ``--source`` names one instead.
3. Each entry becomes an event on this machine (:mod:`apiome_cli.usage_har`): field presence is
   computed from the bodies, then the bodies are discarded. Query values and header values are
   never sent; ``auth_present`` says only whether a credential header was there.
4. Events go up in batches of at most 5,000 (one ``usage_ingest_batch`` ledger row each), and the
   server's counts — accepted, unmatched, sampled out, rejected, scrub findings — are printed.

Bodies are sent only with ``--sample-bodies`` **and** when the source's body window is open; the
server reduces and re-scans every sample and refuses the batch otherwise.

Exit codes follow ``apiome diff``: ``0`` uploaded, ``2`` a parse error, a missing file, an
unsupported format or a rejected request (auth included), ``1`` a transport or server error.
"""

from __future__ import annotations

import gzip
import json
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Optional

import typer

from apiome_cli.cli_context import (
    insecure_from_context,
    settings_from_context,
    timeout_from_context,
)
from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.client.tenant_scope import normalize_tenant_ref
from apiome_cli.config import CliSettings, require_api_key
from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import emit_json, json_mode_from_context
from apiome_cli.usage_har import (
    HarParseError,
    SkippedEntry,
    batches,
    event_from_observation,
    observation_from_entry,
    read_har,
)

app = typer.Typer(
    name="usage",
    help="Feed the runtime usage index: upload recorded traffic (HAR) as usage events.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

#: The header that names the source on the ingest door.
SOURCE_HEADER = "X-Apiome-Usage-Source"

#: Request files that need a response the format does not record (IXH-7.4 ``.http`` / ``.rest``).
UNSUPPORTED_SUFFIXES = (".http", ".rest")

#: The ingest response counters summed across batches.
COUNTERS = (
    "received",
    "accepted",
    "attributed",
    "unmatched",
    "sampledOut",
    "rejected",
    "scrubFindings",
)


@app.callback(invoke_without_command=True)
def usage_group(ctx: typer.Context) -> None:
    """Usage command group."""
    group_callback_without_subcommand(ctx)


def _fail(message: str) -> None:
    """Print ``message`` on stderr and exit with :data:`EXIT_USAGE`."""
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(EXIT_USAGE)


def _tenant_segment(settings: CliSettings) -> str:
    """The tenant for the route's path, as configured (slug or UUID).

    The usage routes take the tenant from the API key, so a ``usage:ingest`` key — which cannot
    read ``/v1/tenants/me`` — is never asked to resolve a UUID to a slug.
    """
    ref = (settings.tenant_id or "").strip()
    if not ref:
        _fail(
            "tenant scope required for this command. Set --tenant or APIOME_TENANT_ID (UUID or slug)."
        )
    return normalize_tenant_ref(ref)


def _check_file(path: Path) -> None:
    """Refuse a missing file, a ``.http`` request file, or a file that is not a HAR archive.

    The whole archive is streamed once, so a truncated or malformed file is refused before any
    event is sent.
    """
    if path.suffix.lower() in UNSUPPORTED_SUFFIXES:
        _fail(
            f"{path.name}: .http / .rest request files record requests without responses, and a usage "
            "event needs the response status. Record the traffic as a HAR (browser devtools or a proxy) "
            "and upload that."
        )
    if not path.is_file():
        _fail(f"{path}: no such file")
    try:
        for _ in read_har(path):
            pass
    except HarParseError as exc:
        _fail(f"{path.name}: {exc}")
    except OSError as exc:
        _fail(f"{path}: {exc.strerror or exc}")


def _events(
    path: Path, *, environment: str, sample_bodies: bool, skipped: list[SkippedEntry]
) -> Iterator[dict[str, Any]]:
    """Stream the file's events, recording every entry that produced none in ``skipped``."""
    for index, entry in read_har(path):
        observation = observation_from_entry(entry, index=index, label=path.name)
        if observation is None:
            skipped.append(SkippedEntry(index=index, reason="invalid-entry"))
            continue
        event, reason = event_from_observation(
            observation, environment=environment, sample_bodies=sample_bodies
        )
        if event is None:
            skipped.append(SkippedEntry(index=index, reason=str(reason)))
            continue
        yield event


def _post_batch(
    client: RestClient, tenant: str, source_id: str, events: list[dict[str, Any]]
) -> dict[str, Any]:
    """Post one gzip-compressed batch; return the ledger counts the server echoes."""
    body = json.dumps(
        {"source_id": source_id, "events": events},
        separators=(",", ":"),
        ensure_ascii=False,
    )
    response = client.post(
        api_paths.usage_ingest(tenant),
        content=gzip.compress(body.encode("utf-8"), mtime=0),
        headers={
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
            SOURCE_HEADER: source_id,
        },
    )
    return response.json()


def summarize(
    *,
    file: str,
    source: dict[str, Any],
    entries: int,
    skipped: list[SkippedEntry],
    responses: list[dict[str, Any]],
) -> dict[str, Any]:
    """The upload's report: the source, what was skipped locally and the server's summed counts.

    Args:
        file: The file name.
        source: The ``…/usage/sources/har`` answer.
        entries: Entries in the file.
        skipped: Entries that produced no event, with why.
        responses: The ingest responses, one per batch.

    Returns:
        A JSON-ready dict (the ``--json`` output).
    """
    totals = {name: sum(int(r.get(name) or 0) for r in responses) for name in COUNTERS}
    rejections: Counter[str] = Counter()
    for response in responses:
        for rejection in response.get("rejections") or []:
            rejections[str(rejection.get("reason"))] += 1
    samples = {
        "stored": sum(
            int((r.get("samples") or {}).get("stored") or 0) for r in responses
        ),
        "dropped": sum(
            int((r.get("samples") or {}).get("dropped") or 0) for r in responses
        ),
    }
    return {
        "file": file,
        "source": source,
        "entries": entries,
        "skipped": dict(sorted(Counter(s.reason for s in skipped).items())),
        "batches": [r.get("batchId") for r in responses],
        "totals": totals,
        "samples": samples,
        "rejections": dict(sorted(rejections.items())),
        "rejectionsTruncated": any(r.get("rejectionsTruncated") for r in responses),
        "basis": "sampled"
        if any(r.get("basis") == "sampled" for r in responses)
        else "complete",
    }


def format_summary(report: dict[str, Any]) -> list[str]:
    """Human-readable lines for :func:`summarize`'s report."""
    source = report["source"]
    totals = report["totals"]
    created = ", created" if source.get("created") else ""
    lines = [
        f"Uploaded {report['file']}: {report['entries']:,} entries in {len(report['batches'])} batch(es)",
        f"Source {source.get('sourceId')} (har · {source.get('environment')}{created})",
        (
            f"Received {totals['received']:,} · accepted {totals['accepted']:,} · unmatched "
            f"{totals['unmatched']:,} · sampled out {totals['sampledOut']:,} · rejected {totals['rejected']:,}"
        ),
        f"Scrub findings: {totals['scrubFindings']:,} (strings the server rewrote or dropped; never what was found)",
    ]
    if report["basis"] == "sampled":
        lines.append(
            "Counts are scaled by the source's sampling rate (basis: sampled)."
        )
    if report["skipped"]:
        detail = ", ".join(
            f"{reason} {count:,}" for reason, count in report["skipped"].items()
        )
        lines.append(
            f"Skipped on this machine: {sum(report['skipped'].values()):,} ({detail})"
        )
    if report["rejections"]:
        detail = ", ".join(
            f"{reason} {count:,}" for reason, count in report["rejections"].items()
        )
        more = " (first 100 per batch)" if report["rejectionsTruncated"] else ""
        lines.append(f"Rejected by the server: {detail}{more}")
    samples = report["samples"]
    if samples["stored"] or samples["dropped"]:
        lines.append(
            f"Body samples: {samples['stored']:,} stored, {samples['dropped']:,} dropped by the re-scan"
        )
    if not source.get("fieldCapture"):
        lines.append("Field presence is not counted: the source has field capture off.")
    return lines


@app.command("upload")
def upload(
    ctx: typer.Context,
    file: Path = typer.Argument(
        ...,
        help="The HAR file (browser devtools or proxy recording).",
        show_default=False,
    ),
    project: str = typer.Option(
        ..., "--project", help="Project slug or UUID the traffic is for."
    ),
    environment: str = typer.Option(
        ...,
        "--environment",
        help="Environment the traffic happened in (prod, staging, ...). mock is reserved.",
    ),
    source: Optional[str] = typer.Option(
        None,
        "--source",
        help="A har usage source id of the project. Default: the project's har source for the environment "
        "(created when there is none).",
    ),
    sample_bodies: bool = typer.Option(
        False,
        "--sample-bodies",
        help="Also send redacted body samples. Refused unless the source's body window is open.",
    ),
) -> None:
    """Upload a HAR file as usage events (POST …/usage/ingest).

    Field presence is computed from the bodies on this machine; the bodies, query values and
    header values are never sent. Exit 0 uploaded, 2 parse error or rejected request (auth
    included), 1 unreachable.
    """
    environment = environment.strip()
    _check_file(file)
    settings = settings_from_context(ctx)
    require_api_key(settings)
    tenant = _tenant_segment(settings)
    client = RestClient(
        settings,
        timeout=timeout_from_context(ctx),
        verify=not insecure_from_context(ctx),
    )

    request: dict[str, Any] = {"project": project, "environment": environment}
    if source:
        request["sourceId"] = source.strip()
    resolved = client.post(api_paths.usage_har_source(tenant), json=request).json()
    if sample_bodies and not resolved.get("bodySamplesOpen"):
        _fail(
            "--sample-bodies: this source does not accept body samples (its body window is closed). "
            "Upload without --sample-bodies, or ask an operator to open the source's sample window."
        )
    source_id = str(resolved.get("sourceId"))

    skipped: list[SkippedEntry] = []
    events = _events(
        file, environment=environment, sample_bodies=sample_bodies, skipped=skipped
    )
    responses = [
        _post_batch(client, tenant, source_id, batch) for batch in batches(events)
    ]
    entries = len(skipped) + sum(int(r.get("received") or 0) for r in responses)
    report = summarize(
        file=file.name,
        source=resolved,
        entries=entries,
        skipped=skipped,
        responses=responses,
    )
    if json_mode_from_context(ctx):
        emit_json(report)
    else:
        for line in format_summary(report):
            typer.echo(line)
