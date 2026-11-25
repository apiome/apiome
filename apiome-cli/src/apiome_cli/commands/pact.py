"""Pact Broker commands — ``apiome pact`` (PFX-2.4, #6928; PFX-2.6, #6930).

``apiome pact publish-provider-contract <openapi-file> --provider … --provider-app-version …
--evidence <report>`` publishes a provider contract for bi-directional contract testing, with the
evidence that the provider honours it. The flags follow PactFlow's ``pactflow
publish-provider-contract`` where they overlap (``--provider-app-version``, ``--branch``, ``--tag``,
``--build-url``, ``--verification-exit-code``, ``--verifier``), so a pipeline moves over by
changing the command name.

``apiome pact export-consumer-contract`` / ``publish-consumer-contract --project … --consumer …``
turn a consumer surface declared in the UI picker into a Pact v4 file (sample values from the
specification's examples) and write it, or publish it to the workspace's Pact Broker.

``apiome pact publish-verification-results <report> --provider … --consumer … --pact-version …
--provider-app-version …`` publishes the result of a verification that ran elsewhere
(``pact_verifier_cli --json`` output or JUnit XML) as a verification result in the broker, so
can-i-deploy sees it (PFX-3.5).

Authentication is the usual ``APIOME_API_KEY`` / config path; the workspace is the configured
tenant.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import quote

import json

import typer

from apiome_cli.cli_context import insecure_from_context, settings_from_context
from apiome_cli.client.http import RestClient
from apiome_cli.client.pact_consumer_export import (
    build_publish_body as build_consumer_publish_body,
)
from apiome_cli.client.pact_consumer_export import (
    consumer_pact_path,
    has_findings,
)
from apiome_cli.client.pact_consumer_export import (
    summary_lines as consumer_summary_lines,
)
from apiome_cli.client.pact_external_verification import (
    REPORT_FORMATS,
    external_results_path,
    report_content_type,
)
from apiome_cli.client.pact_external_verification import (
    summary_lines as verification_summary_lines,
)
from apiome_cli.client.pact_provider_contract import (
    build_publish_body,
    build_verification_results,
    contract_content_type,
    evidence_content_type,
    is_verified,
    summary_lines,
)
from apiome_cli.client.tenant_scope import require_tenant_slug
from apiome_cli.config import require_api_key
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import emit_json, json_mode_from_context

app = typer.Typer(
    name="pact",
    help="Pact Broker: publish provider contracts, and export consumer surfaces as Pact files.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def pact_group(ctx: typer.Context) -> None:
    """Pact Broker command group."""
    group_callback_without_subcommand(ctx)


def provider_contract_path(tenant_slug: str, provider: str, version: str) -> str:
    """``/v1/tenants/{t}/pact-broker/contracts/provider/{p}/version/{v}``, each segment escaped."""
    return (
        f"/v1/tenants/{quote(tenant_slug, safe='')}/pact-broker/contracts/provider/"
        f"{quote(provider, safe='')}/version/{quote(version, safe='')}"
    )


@app.command("publish-provider-contract")
def publish_provider_contract(
    ctx: typer.Context,
    contract: Optional[Path] = typer.Argument(
        None,
        exists=True,
        dir_okay=False,
        readable=True,
        help="The provider's OpenAPI 3.x document (JSON or YAML). Omit with --apiome-version.",
    ),
    provider: str = typer.Option(..., "--provider", help="The provider's name in the broker."),
    provider_app_version: str = typer.Option(
        ..., "--provider-app-version", "-a", help="The provider build's version (a commit SHA is best)."
    ),
    apiome_version: Optional[str] = typer.Option(
        None,
        "--apiome-version",
        help="Render the contract from an Apiome version, '<project>@<version>', instead of a file.",
    ),
    content_type: Optional[str] = typer.Option(
        None, "--content-type", help="The contract's media type; inferred from .json / .yaml / .yml."
    ),
    branch: Optional[str] = typer.Option(None, "--branch", help="The branch the build came from."),
    tag: Optional[list[str]] = typer.Option(None, "--tag", "-t", help="Tag the provider version (repeatable)."),
    build_url: Optional[str] = typer.Option(None, "--build-url", help="http(s) URL of the CI build."),
    evidence: Optional[Path] = typer.Option(
        None,
        "--evidence",
        "--verification-results",
        exists=True,
        dir_okay=False,
        readable=True,
        help=(
            "Self-verification report: JUnit XML (Schemathesis, Dredd, Newman or any JUnit writer), "
            "Newman JSON or Schemathesis NDJSON."
        ),
    ),
    evidence_type: Optional[str] = typer.Option(
        None,
        "--evidence-content-type",
        "--verification-results-content-type",
        help="The report's media type; inferred from .xml / .json / .ndjson / .jsonl / .txt.",
    ),
    evidence_report: Optional[str] = typer.Option(
        None,
        "--evidence-report",
        help="An Apiome provider-verification report id instead of a report file.",
    ),
    exit_code: Optional[int] = typer.Option(
        None,
        "--verification-exit-code",
        help="The verifier's exit code; 0 is success. Without it a report file counts as success "
        "unless the report shows failures.",
    ),
    verifier: Optional[str] = typer.Option(
        None, "--verifier", help="The tool that wrote the report (schemathesis, dredd, newman)."
    ),
    verifier_version: Optional[str] = typer.Option(None, "--verifier-version", help="That tool's version."),
    fail_on_unverified: bool = typer.Option(
        False,
        "--fail-on-unverified",
        help="Exit 1 when the published contract has no passing self-verification evidence.",
    ),
) -> None:
    """Publish a provider contract with its self-verification evidence (PUT …/contracts/provider/…).

    Prints what was published, what the evidence proved (verified, failed, inconclusive or missing,
    with the report's kind, tool, digest and counts) and the bi-directional comparisons the publish
    ran. Exits 2 when the server refuses the request (a bad document or report, with its location),
    and 1 with --fail-on-unverified when the contract is unverified.
    """
    try:
        results = build_verification_results(
            evidence=evidence,
            evidence_content_type=evidence_content_type(evidence, evidence_type) if evidence else None,
            evidence_report=evidence_report,
            exit_code=exit_code,
            verifier=verifier,
            verifier_version=verifier_version,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--evidence") from exc
    try:
        body = build_publish_body(
            contract=contract,
            content_type=contract_content_type(contract, content_type) if contract else None,
            apiome_version=apiome_version,
            branch=branch,
            tags=tag,
            build_url=build_url,
            verification_results=results,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="CONTRACT / --apiome-version") from exc

    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = RestClient(settings, verify=not insecure_from_context(ctx))
    tenant_slug = require_tenant_slug(settings, client)
    response = client.put(provider_contract_path(tenant_slug, provider, provider_app_version), json=body)
    payload = response.json()

    if json_mode_from_context(ctx):
        emit_json(payload)
    else:
        for line in summary_lines(payload, created=response.status_code == 201):
            typer.echo(line)
    raise typer.Exit(EXIT_ERROR if fail_on_unverified and not is_verified(payload) else EXIT_SUCCESS)


def _write_pact(payload: dict, output: Optional[Path]) -> None:
    """Write the generated Pact document to ``output``, or to stdout when it is ``None``."""
    text = json.dumps(payload.get("pact") or {}, indent=2, sort_keys=False) + "\n"
    if output is None:
        typer.echo(text, nl=False)
    else:
        output.write_text(text, encoding="utf-8")


def _report(ctx: typer.Context, payload: dict, *, to_stderr: bool) -> None:
    """Print the response (JSON mode) or its summary lines."""
    if json_mode_from_context(ctx):
        emit_json(payload)
        return
    for line in consumer_summary_lines(payload):
        typer.echo(line, err=to_stderr)


@app.command("export-consumer-contract")
def export_consumer_contract(
    ctx: typer.Context,
    project: str = typer.Option(..., "--project", "-p", help="The project the consumer consumes (slug or id)."),
    consumer: str = typer.Option(..., "--consumer", "-c", help="The consumer (slug or id)."),
    revision: Optional[int] = typer.Option(
        None, "--revision", min=1, help="A contract revision; defaults to the current one."
    ),
    provider: Optional[str] = typer.Option(
        None, "--provider", help="The provider pacticipant name; defaults to the project's bound pacticipant."
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", dir_okay=False, writable=True, help="Write the Pact file here instead of stdout."
    ),
    fail_on_findings: bool = typer.Option(
        False, "--fail-on-findings", help="Exit 1 when any value was invented or anything was left out."
    ),
) -> None:
    """Export a picker-declared consumer surface as a Pact v4 file (GET …/consumers/{c}/pact).

    The pact carries one interaction per declared operation and response status, only the declared
    fields, and the specification's examples as sample values. Prints the findings — every value
    that had to be invented (placeholder) and everything left out (omitted), with a reason. Without
    --output the Pact JSON goes to stdout and the summary to stderr. Exits 2 when the server refuses
    (a contract imported from a Pact file, or one that yields no interaction), and 1 with
    --fail-on-findings when there are findings.
    """
    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = RestClient(settings, verify=not insecure_from_context(ctx))
    tenant_slug = require_tenant_slug(settings, client)
    payload = client.get(
        consumer_pact_path(tenant_slug, project, consumer, revision=revision, provider=provider)
    ).json()

    if json_mode_from_context(ctx):
        if output is not None:
            _write_pact(payload, output)
        emit_json(payload)
    else:
        _write_pact(payload, output)
        _report(ctx, payload, to_stderr=output is None)
        if output is not None:
            typer.echo(f"  wrote {output}")
    raise typer.Exit(EXIT_ERROR if fail_on_findings and has_findings(payload) else EXIT_SUCCESS)


@app.command("publish-consumer-contract")
def publish_consumer_contract(
    ctx: typer.Context,
    project: str = typer.Option(..., "--project", "-p", help="The project the consumer consumes (slug or id)."),
    consumer: str = typer.Option(..., "--consumer", "-c", help="The consumer (slug or id)."),
    consumer_app_version: str = typer.Option(
        ..., "--consumer-app-version", "-a", help="The consumer build's version (a commit SHA is best)."
    ),
    branch: Optional[str] = typer.Option(None, "--branch", help="The branch the build came from."),
    tag: Optional[list[str]] = typer.Option(None, "--tag", "-t", help="Tag the consumer version (repeatable)."),
    build_url: Optional[str] = typer.Option(None, "--build-url", help="http(s) URL of the CI build."),
    revision: Optional[int] = typer.Option(
        None, "--revision", min=1, help="A contract revision; defaults to the current one."
    ),
    provider: Optional[str] = typer.Option(
        None, "--provider", help="The provider pacticipant name; defaults to the project's bound pacticipant."
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", dir_okay=False, writable=True, help="Also write the published Pact file here."
    ),
    fail_on_findings: bool = typer.Option(
        False, "--fail-on-findings", help="Exit 1 when any value was invented or anything was left out."
    ),
) -> None:
    """Publish a picker-declared consumer surface to the Pact Broker (POST …/consumers/{c}/pact/publish).

    Generates the same Pact v4 file as export-consumer-contract and publishes it for the consumer
    version, as `pact-broker publish` would: branch, tags and build URL are recorded and the
    bi-directional comparisons run. Prints the findings and the broker's notices. Exits 2 when the
    server refuses (409 when that version already published a different pact), and 1 with
    --fail-on-findings when there are findings.
    """
    body = build_consumer_publish_body(
        consumer_app_version=consumer_app_version,
        branch=branch,
        tags=tag,
        build_url=build_url,
        revision=revision,
        provider=provider,
    )
    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = RestClient(settings, verify=not insecure_from_context(ctx))
    tenant_slug = require_tenant_slug(settings, client)
    payload = client.post(consumer_pact_path(tenant_slug, project, consumer, publish=True), json=body).json()

    if output is not None:
        _write_pact(payload, output)
    _report(ctx, payload, to_stderr=False)
    raise typer.Exit(EXIT_ERROR if fail_on_findings and has_findings(payload) else EXIT_SUCCESS)


@app.command("publish-verification-results")
def publish_verification_results(
    ctx: typer.Context,
    report: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="The report: pact_verifier_cli --json output, or JUnit XML.",
    ),
    provider: str = typer.Option(
        ..., "--provider", help="The provider's name in the broker."
    ),
    consumer: str = typer.Option(
        ..., "--consumer", help="The consumer's name in the broker."
    ),
    pact_version: str = typer.Option(
        ..., "--pact-version", help="The verified pact version's SHA-256."
    ),
    provider_app_version: str = typer.Option(
        ...,
        "--provider-app-version",
        "-a",
        help="The provider build's version (a commit SHA is best).",
    ),
    branch: Optional[str] = typer.Option(
        None, "--branch", help="The branch the provider build came from."
    ),
    tag: Optional[list[str]] = typer.Option(
        None, "--tag", "-t", help="Tag the provider version (repeatable)."
    ),
    build_url: Optional[str] = typer.Option(
        None, "--build-url", help="http(s) URL of the CI build."
    ),
    report_format: str = typer.Option(
        "auto",
        "--format",
        help=f"The report's format ({', '.join(REPORT_FORMATS)}); auto reads the file name, then the body.",
    ),
    content_type: Optional[str] = typer.Option(
        None,
        "--content-type",
        help="The report's media type; inferred from .json / .xml.",
    ),
    verifier: Optional[str] = typer.Option(
        None, "--verifier", help="The tool that wrote the report."
    ),
    verifier_version: Optional[str] = typer.Option(
        None, "--verifier-version", help="That tool's version."
    ),
    fail_on_failure: bool = typer.Option(
        False,
        "--fail-on-failure",
        help="Exit 1 when the published result is a failure.",
    ),
) -> None:
    """Publish a verification report produced elsewhere (POST …/external-verification-results).

    Reads pact_verifier_cli --json output or JUnit XML on the server, stores it as a verification
    result of the pact version and prints the verdict and every note about what could not be used.
    Exits 2 when the server refuses (a malformed or empty report, an unknown pact version), and 1
    with --fail-on-failure when the result is a failure.
    """
    if report_format not in REPORT_FORMATS:
        raise typer.BadParameter(
            f"must be one of {', '.join(REPORT_FORMATS)}", param_hint="--format"
        )
    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = RestClient(settings, verify=not insecure_from_context(ctx))
    tenant_slug = require_tenant_slug(settings, client)
    path = external_results_path(
        tenant_slug,
        provider,
        consumer,
        pact_version,
        provider_app_version=provider_app_version,
        build_url=build_url,
        branch=branch,
        tags=tag,
        report_format=report_format,
        verifier=verifier,
        verifier_version=verifier_version,
    )
    response = client.post(
        path,
        content=report.read_bytes(),
        headers={"Content-Type": report_content_type(report, content_type)},
    )
    payload = response.json()

    if json_mode_from_context(ctx):
        emit_json(payload)
    else:
        for line in verification_summary_lines(payload):
            typer.echo(line)
    raise typer.Exit(
        EXIT_ERROR if fail_on_failure and not payload.get("success") else EXIT_SUCCESS
    )
