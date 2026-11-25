"""Pact Broker commands — ``apiome pact`` (PFX-2.4, #6928).

``apiome pact publish-provider-contract <openapi-file> --provider … --provider-app-version …
--evidence <report>`` publishes a provider contract for bi-directional contract testing, with the
evidence that the provider honours it. The flags follow PactFlow's ``pactflow
publish-provider-contract`` where they overlap (``--provider-app-version``, ``--branch``, ``--tag``,
``--build-url``, ``--verification-exit-code``, ``--verifier``), so a pipeline moves over by
changing the command name.

Authentication is the usual ``APIOME_API_KEY`` / config path; the workspace is the configured
tenant.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import quote

import typer

from apiome_cli.cli_context import insecure_from_context, settings_from_context
from apiome_cli.client.http import RestClient
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
    help="Pact Broker: publish provider contracts for bi-directional contract testing.",
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
