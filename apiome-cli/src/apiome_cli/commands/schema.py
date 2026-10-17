"""``apiome schema`` — published-spec downloads (CLI 9.x) and CI schema testing (#5117).

``apiome schema arazzo <tenant>/<project>/<version>`` (CLI 9.6, #3249) and ``apiome schema json``
(CLI 9.7, #3250) download a published version's Arazzo workflows or JSON Schema through
:func:`_download_published`; the shared ref/format/checksum logic is in
:mod:`apiome_cli.published_spec`.

``apiome schema diff <tenant>/<project> <v1> <v2>`` (CLI 9.8, #3251) compares two published
versions client-side; the differ and its four renderings are in :mod:`apiome_cli.schema_diff`.

``apiome schema test`` runs CI schema testing over the IXH-5.1/5.2 services.

The command runs the same server-side validation the Schema Test Bench uses, against the
same path-shaped schema reference, and turns the verdicts into CI evidence: a stable
``--json`` report, JUnit XML via ``--junit``, and exit codes that keep "the tests failed"
(6) apart from "the network was down" (1) and "the credentials or the reference were
rejected" (2).

Three case sources, combinable in one run:

* ``--payload FILE`` (repeatable) — validate a concrete payload, expected valid;
* ``--generate`` — the IXH-5.2 generated set (valid instances + single-constraint
  mutants), each verified server-side through the IXH-5.1 validator;
* ``--suite PATH`` — the saved payload sets the Test Bench exports (IXH-5.3): a directory
  of payload files, or an IXH-1.1 corpus manifest whose ``instance-payload`` entries are
  run. Suite mode also runs the generated set unless ``--no-generate``.

All judging, rendering, and exit-code logic lives in :mod:`apiome_cli.schema_test`;
this module owns only the flags and the HTTP calls.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Optional

import typer

from apiome_cli import __version__
from apiome_cli import schema_diff as schema_diff_core
from apiome_cli.cli_context import insecure_from_context, settings_from_context, timeout_from_context
from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.client.spec_download import SpecFormat
from apiome_cli.client.version_scope import tenant_scoped_client
from apiome_cli.exit_codes import EXIT_CHECKSUM_MISMATCH, EXIT_DIFFERENCES, EXIT_ERROR, EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import emit_json, json_mode_from_context
from apiome_cli.published_spec import (
    fetch_published_document,
    fetch_published_openapi,
    normalize_expected_sha256,
    parse_project_ref,
    parse_published_ref,
    parse_serialization,
    published_document_path,
    sha256_hex,
)
from apiome_cli.spec_output import build_spec_export_metadata, emit_download_metadata, write_document_bytes
from apiome_cli.schema_test import (
    SOURCE_PAYLOAD,
    SOURCE_SUITE,
    SchemaTestCase,
    SuiteLoadError,
    SuitePayload,
    build_report,
    case_from_validation,
    cases_from_synthesis,
    exit_code_for_cases,
    load_payload_file,
    load_suite,
    render_human,
    render_junit,
)

app = typer.Typer(
    name="schema",
    help="Download and diff published specs; test payloads against schemas.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def schema_group(ctx: typer.Context) -> None:
    """Schema testing command group."""
    group_callback_without_subcommand(ctx)


@app.command("arazzo")
def schema_arazzo(
    ctx: typer.Context,
    ref: str = typer.Argument(
        ...,
        metavar="TENANT/PROJECT/VERSION",
        help="Published version by slugs, e.g. acme-corp/payments-api/2.1.0.",
    ),
    class_name: Optional[str] = typer.Option(
        None,
        "--class",
        help="Download only this class's workflows (the per-class route).",
    ),
    serialization: str = typer.Option(
        "yaml",
        "--format",
        help="json or yaml (default yaml, the usual form for Arazzo).",
    ),
    output: str = typer.Option(
        "-",
        "--output",
        "-o",
        help="File to write, or - for stdout (default).",
    ),
    expect_sha256: Optional[str] = typer.Option(
        None,
        "--expect-sha256",
        help="Fail with exit 6, writing nothing, unless the document has this SHA-256.",
    ),
) -> None:
    """Download a published version's Arazzo workflows.

    Fetches GET /v1/arazzo/{tenant}/{project}/{version}, or the per-class route with --class,
    and writes the document byte for byte as served. A summary with its sha256 checksum goes
    to stderr (with --json, a JSON line: on stdout when --output is a file, on stderr when the
    document goes to stdout).

    Exit codes: 0 written; 6 --expect-sha256 did not match (nothing written); 2 bad usage, or
    the version or class is unknown, unpublished, or private without an API key; 1 a
    transport or server error.
    """
    _download_published(
        ctx,
        route="arazzo",
        spec_format="arazzo",
        ref=ref,
        class_name=class_name,
        serialization=serialization,
        output=output,
        expect_sha256=expect_sha256,
    )


@app.command("json")
def schema_json(
    ctx: typer.Context,
    ref: str = typer.Argument(
        ...,
        metavar="TENANT/PROJECT/VERSION",
        help="Published version by slugs, e.g. acme-corp/payments-api/2.1.0.",
    ),
    class_name: Optional[str] = typer.Option(
        None,
        "--class",
        help="Download only this class's schema (the per-class route).",
    ),
    serialization: str = typer.Option(
        "json",
        "--format",
        help="json (default) or yaml.",
    ),
    output: str = typer.Option(
        "-",
        "--output",
        "-o",
        help="File to write, or - for stdout (default).",
    ),
    expect_sha256: Optional[str] = typer.Option(
        None,
        "--expect-sha256",
        help="Fail with exit 6, writing nothing, unless the document has this SHA-256.",
    ),
) -> None:
    """Download a published version's JSON Schema.

    Fetches GET /v1/json/{tenant}/{project}/{version}, or the per-class route with --class,
    and streams the document byte for byte as served (no transformation), so it pipes
    straight into code generators. A summary with its sha256 checksum goes to stderr (with
    --json, a JSON line: on stdout when --output is a file, on stderr when the document goes
    to stdout).

    Exit codes: 0 written; 6 --expect-sha256 did not match (nothing written); 2 bad usage, or
    the version or class is unknown, unpublished, or private without an API key; 1 a
    transport or server error.
    """
    _download_published(
        ctx,
        route="json",
        spec_format="json-schema",
        ref=ref,
        class_name=class_name,
        serialization=serialization,
        output=output,
        expect_sha256=expect_sha256,
    )


def _download_published(
    ctx: typer.Context,
    *,
    route: str,
    spec_format: SpecFormat,
    ref: str,
    class_name: Optional[str],
    serialization: str,
    output: str,
    expect_sha256: Optional[str],
) -> None:
    """Download one published document for a ``schema <format>`` command and write it.

    Shared by ``schema arazzo`` and ``schema json``: validates the flags (exit 2 before any
    request), fetches ``/v1/{route}/{tenant}/{project}/{version}[/{class}]``, checks
    ``--expect-sha256`` before writing (exit 6, nothing written), writes the bytes unchanged and
    emits the summary.

    Args:
        ctx: Typer context (settings, timeout, ``--insecure``, global ``--json``).
        route: The spec route name, ``arazzo`` or ``json``.
        spec_format: Recorded as ``format`` in the summary.
        ref: The ``tenant/project/version`` argument.
        class_name: ``--class``, or ``None`` for the whole bundle.
        serialization: ``--format`` value (``json`` or ``yaml``).
        output: ``--output`` path, or ``-`` for stdout.
        expect_sha256: ``--expect-sha256`` digest, or ``None``.
    """
    try:
        published = parse_published_ref(ref)
        wanted_format = parse_serialization(serialization)
        expected = normalize_expected_sha256(expect_sha256) if expect_sha256 is not None else None
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    if class_name is not None and not class_name.strip():
        typer.echo("--class cannot be empty.", err=True)
        raise typer.Exit(EXIT_USAGE)
    output = output.strip()
    if not output:
        typer.echo("--output cannot be empty.", err=True)
        raise typer.Exit(EXIT_USAGE)

    settings = settings_from_context(ctx)
    client = RestClient(settings, timeout=timeout_from_context(ctx), verify=not insecure_from_context(ctx))
    path = published_document_path(route, published, class_name.strip() if class_name else None)
    download = fetch_published_document(client, path, spec_format=spec_format, serialization=wanted_format)

    actual = sha256_hex(download.body)
    if expected is not None and actual != expected:
        typer.echo(
            f"SHA-256 mismatch for {published.label()}: expected {expected}, got {actual}. "
            "Nothing was written.",
            err=True,
        )
        raise typer.Exit(EXIT_CHECKSUM_MISMATCH)

    write_document_bytes(download.body, output)
    metadata = replace(
        build_spec_export_metadata(
            download=download,
            scope_source_openapi_version=None,
            scope_fidelity_target=None,
            fidelity=None,
            output=output,
        ),
        checksum=f"sha256:{actual}",
    )
    emit_download_metadata(metadata, json_mode=json_mode_from_context(ctx))


@app.command("diff")
def schema_diff(
    ctx: typer.Context,
    project_ref: str = typer.Argument(
        ..., metavar="TENANT/PROJECT", help="Project by slugs, e.g. acme-corp/payments-api."
    ),
    base_version: str = typer.Argument(..., metavar="V1", help="Base (older) published version, e.g. 2.0.0."),
    head_version: str = typer.Argument(..., metavar="V2", help="Head (newer) published version, e.g. 2.1.0."),
    output_format: str = typer.Option(
        "summary", "--format", help="summary (default), unified, sarif or json. Global --json means json."
    ),
    scope: str = typer.Option("all", "--scope", help="Compare paths, schemas or all (default)."),
    ignore: Optional[list[str]] = typer.Option(
        None, "--ignore", help="Drop a kind of change (repeatable): description-only."
    ),
    exit_code: bool = typer.Option(
        False, "--exit-code", help="Git-like: exit 1 if there are differences, 0 if identical."
    ),
    output: str = typer.Option("-", "--output", "-o", help="File to write, or - for stdout (default)."),
) -> None:
    """Compare two published versions: paths, classes and properties.

    Both sides are fetched from the public GET /v1/schema/{tenant}/{project}/{version} (no login;
    APIOME_API_KEY is sent for private versions) and compared in the CLI. A version typed as
    v2.1.0 that is not found is retried as 2.1.0. This lists what changed; to grade changes as
    breaking, use apiome versions compatibility.

    Exit codes: 0 done (with --exit-code: identical); 1 with --exit-code, differences found;
    2 bad usage, or a version is unknown, unpublished or private without a key. Without
    --exit-code a transport or server error exits 1; with it, 2, so 1 always means "differs".
    """
    fmt = "json" if json_mode_from_context(ctx) else output_format.strip().lower()
    try:
        tenant, project = parse_project_ref(project_ref)
        if fmt not in schema_diff_core.FORMATS:
            raise ValueError(f"--format must be one of {', '.join(schema_diff_core.FORMATS)}, got {output_format!r}")
        scope_value = scope.strip().lower()
        if scope_value not in schema_diff_core.SCOPES:
            raise ValueError(f"--scope must be one of {', '.join(schema_diff_core.SCOPES)}, got {scope!r}")
        ignored = schema_diff_core.normalize_ignore(ignore or [])
        base_ref = parse_published_ref(f"{tenant}/{project}/{base_version}")
        head_ref = parse_published_ref(f"{tenant}/{project}/{head_version}")
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    output = output.strip()
    if not output:
        typer.echo("--output cannot be empty.", err=True)
        raise typer.Exit(EXIT_USAGE)

    settings = settings_from_context(ctx)
    client = RestClient(settings, timeout=timeout_from_context(ctx), verify=not insecure_from_context(ctx))
    try:
        base_ref, base_doc = fetch_published_openapi(client, base_ref)
        head_ref, head_doc = fetch_published_openapi(client, head_ref)
    except typer.Exit as exc:
        # With --exit-code, 1 must only ever mean "differences": remap transport/5xx to 2.
        if exit_code and exc.exit_code == EXIT_ERROR:
            raise typer.Exit(EXIT_USAGE) from exc
        raise

    changes = schema_diff_core.apply_ignore(
        schema_diff_core.diff_specs(base_doc, head_doc, scope=scope_value), ignored
    )
    sides = {
        "base": {"label": base_ref.label(), "url": published_document_path("schema", base_ref)},
        "head": {"label": head_ref.label(), "url": published_document_path("schema", head_ref)},
    }
    if fmt == "summary":
        text = schema_diff_core.render_summary(changes, base_label=base_ref.version, head_label=head_ref.version) + "\n"
    elif fmt == "unified":
        text = schema_diff_core.render_unified(
            base_doc, head_doc, base_label=base_ref.label(), head_label=head_ref.label(), scope=scope_value, ignore=ignored
        )
    elif fmt == "json":
        payload = schema_diff_core.to_json(changes, **sides, scope=scope_value, ignore=ignored)
        text = json.dumps(payload, indent=2) + "\n"
    else:
        payload = schema_diff_core.to_sarif(
            changes, artifact_uri=sides["head"]["url"], tool_version=__version__, **sides
        )
        text = json.dumps(payload, indent=2) + "\n"
    write_document_bytes(text.encode("utf-8"), output)
    if output != "-":
        typer.echo(f"Wrote {fmt} diff ({len(changes)} changes) to {output}", err=True)
    if exit_code and changes:
        raise typer.Exit(EXIT_DIFFERENCES)


@app.command("test")
def schema_test(
    ctx: typer.Context,
    schema_ref: str = typer.Option(
        ...,
        "--schema",
        help=(
            "Path-shaped schema reference: project/{slug}/{version}/{type}, "
            "catalog/{item}/{version}/{type}, or registry/{namespace}/{name}; the "
            "trailing /{type} segment is optional. {version} is a version label, a "
            "revision id, or 'latest'."
        ),
    ),
    payload: Optional[list[Path]] = typer.Option(
        None,
        "--payload",
        help="Payload file to validate (repeatable). JSON by default; *.xml is sent as XML.",
    ),
    generate: Optional[bool] = typer.Option(
        None,
        "--generate/--no-generate",
        help=(
            "Run the generated set: valid instances plus single-constraint mutants, each "
            "verified server-side. Default: off, except in --suite mode where it is on."
        ),
    ),
    suite: Optional[Path] = typer.Option(
        None,
        "--suite",
        help=(
            "Suite mode: a directory of saved payload files (all expected valid), or an "
            "IXH-1.1 corpus manifest whose 'instance-payload' entries are run with "
            "expectations from validity_class. Also runs the generated set unless "
            "--no-generate."
        ),
    ),
    seed: int = typer.Option(
        0,
        "--seed",
        min=0,
        help="Synthesis seed: the same schema and seed generate byte-identical payloads.",
    ),
    junit: Optional[Path] = typer.Option(
        None,
        "--junit",
        help="Write the run as JUnit XML to this file ('-' for stdout).",
    ),
) -> None:
    """Run schema tests server-side and gate on the verdicts.

    Exit codes: 0 every case passed; 6 at least one case failed (a payload's verdict did
    not match its expectation, or a mutant did not violate its intended constraint); 1 a
    case could not be checked at all, a transport/server fault, or an empty run; 2 bad
    usage, rejected credentials, or a schema reference the server refused (any 4xx).
    """
    run_generated = generate if generate is not None else suite is not None
    if not payload and not run_generated and suite is None:
        raise typer.BadParameter(
            "nothing to test: provide --payload, --generate, and/or --suite",
            param_hint="--payload",
        )
    if junit is not None and str(junit) == "-" and json_mode_from_context(ctx):
        raise typer.BadParameter(
            "cannot write JUnit to stdout together with --json; give --junit a file path",
            param_hint="--junit",
        )

    try:
        payload_files = [load_payload_file(p) for p in payload or []]
        suite_payloads = load_suite(suite) if suite is not None else []
    except SuiteLoadError as exc:
        raise typer.BadParameter(str(exc)) from exc

    client, tenant_slug = tenant_scoped_client(ctx)

    cases: list[SchemaTestCase] = []
    source_echo: Optional[dict[str, Any]] = None
    diagnostics: list[dict[str, Any]] = []
    rejected_mutants = 0

    def _validate(entry: SuitePayload, source: str) -> None:
        """Validate one payload file and record its judged case."""
        nonlocal source_echo
        response = client.post(
            api_paths.schema_validate(tenant_slug, schema_ref),
            json={"instance_text": entry.payload_text, "media_type": entry.media_type},
        ).json()
        source_echo = source_echo or response.get("source")
        _collect_diagnostics(diagnostics, response)
        cases.append(case_from_validation(entry, response, source=source))

    for entry in payload_files:
        _validate(entry, SOURCE_PAYLOAD)
    for entry in suite_payloads:
        _validate(entry, SOURCE_SUITE)

    if run_generated:
        response = client.post(
            api_paths.schema_synthesize(tenant_slug, schema_ref),
            json={"seed": seed, "verify": True},
        ).json()
        source_echo = source_echo or response.get("source")
        _collect_diagnostics(diagnostics, response)
        rejected = response.get("rejected_mutants")
        rejected_mutants = int(rejected) if isinstance(rejected, int) else 0
        cases.extend(cases_from_synthesis(response))

    report = build_report(
        schema_ref=schema_ref,
        seed=seed,
        cases=cases,
        source=source_echo,
        rejected_mutants=rejected_mutants,
        diagnostics=diagnostics,
    )

    if junit is not None:
        junit_text = render_junit(report)
        if str(junit) == "-":
            typer.echo(junit_text, nl=False)
        else:
            junit.write_text(junit_text, encoding="utf-8")

    if json_mode_from_context(ctx):
        emit_json(report)
    elif junit is None or str(junit) != "-":
        for line in render_human(report):
            typer.echo(line)
        if junit is not None:
            typer.echo(f"  wrote junit artifact to {junit}")

    raise typer.Exit(exit_code_for_cases(cases))


def _collect_diagnostics(collected: list[dict[str, Any]], response: dict[str, Any]) -> None:
    """Aggregate a response's top-level diagnostics, deduplicated by code + message."""
    for diagnostic in response.get("diagnostics") or []:
        if not isinstance(diagnostic, dict):
            continue
        if any(
            d.get("code") == diagnostic.get("code")
            and d.get("message") == diagnostic.get("message")
            for d in collected
        ):
            continue
        collected.append(diagnostic)
