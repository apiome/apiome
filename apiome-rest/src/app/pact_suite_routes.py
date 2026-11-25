"""Compile a pact version into a contract suite — PFX-3.1 (#6931).

``POST /v1/tenants/{tenant}/pact-suites/provider/{provider}/consumer/{consumer}/pact-version/{sha}``
reads one pact version of the caller's workspace and compiles it with
:func:`app.contract_suite_pact.compile_pact_suite`: one ``pact_interaction`` case per HTTP
interaction, everything it cannot replay reported. The manifest is byte-identical for the same
pact version and options, so a provider verification (PFX-3.2) can cite it by digest.

It lives beside the Pact Broker surface, not under ``…/pact-broker``, because no Pact Broker or
PactFlow client knows it; that surface stays the catalogued, PactFlow-compatible one.

Compiling is a pure read — no job, no row, no audit entry — and requires ``pacts:view``. Every
lookup is scoped to the authenticated tenant, so a pact of another workspace is a ``404``.
"""

from __future__ import annotations

from typing import Any, Dict
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_authentication
from .contract_suite import ContractSuiteManifest, PactSuiteOptions, SuiteSourceInfo
from .contract_suite_pact import compile_pact_suite
from .database import db
from .pact_publication import CODE_PACT_NOT_FOUND, PactPublicationError
from .pact_publication_store import get_pact_by_sha
from .pacticipant import PacticipantValidationError
from .permissions import Action, Resource, enforce_permission

__all__ = ["PactSuiteCompileRequest", "PactSuiteResponse", "pact_suite_reference", "router"]

router = APIRouter(prefix="/v1/tenants", tags=["pact-broker"])

#: A pact version's content address: 64 hexadecimal characters.
_SHA_PATTERN = r"^[0-9a-fA-F]{64}$"


class PactSuiteCompileRequest(BaseModel):
    """What to compile from the pact version named in the URL. An empty body compiles everything."""

    model_config = ConfigDict(extra="forbid")

    options: PactSuiteOptions = Field(
        default_factory=PactSuiteOptions,
        description=(
            "Compiler options. They are echoed on the manifest (`pact.options`) and hashed into "
            "its digest, so the same pact version compiled with the same options always yields "
            "the same suite."
        ),
    )


class PactSuiteResponse(BaseModel):
    """The suite compiled from one pact version."""

    model_config = ConfigDict(extra="forbid")

    consumer: str = Field(description="The consumer's handle.")
    provider: str = Field(description="The provider's handle.")
    pact_version_sha: str = Field(description="The pact version compiled.")
    manifest: ContractSuiteManifest = Field(
        description=(
            "The compiled suite: one `pact_interaction` case per HTTP interaction, with "
            "`unsupported` and `findings` naming everything that could not be replayed."
        )
    )


def pact_suite_reference(provider_slug: str, consumer_slug: str, sha: str) -> str:
    """The reference a pact suite records as its source.

    Args:
        provider_slug: The provider's handle.
        consumer_slug: The consumer's handle.
        sha: The pact version's content address.

    Returns:
        ``pact/{provider}/{consumer}/{sha}``, each segment percent-encoded.
    """
    return "/".join(("pact", quote(provider_slug, safe=""), quote(consumer_slug, safe=""), sha))


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


@router.post(
    "/{tenant_slug}/pact-suites/provider/{provider}/consumer/{consumer}/pact-version/{sha}",
    response_model=PactSuiteResponse,
    summary="Compile a pact version into a contract suite",
    description=(
        "Compile one pact version into an executable contract suite (PFX-3.1): one case per "
        "HTTP interaction, with `source: pact_interaction` and `synthetic: false`. A case's "
        "`request` is the request the consumer recorded; its `pact` block carries the provider "
        "states, the expected response (status, headers, body) and the matching rules and "
        "generators of both sides.\n\n"
        "**Deterministic per pact version.** The same pact version and the same options produce "
        "a byte-identical manifest and the same `sha256:` `digest`, whichever consumer version "
        "published it. `options.interactions` narrows the suite to named interactions "
        "(description or Pact 4 key); `options.max_interactions` caps it.\n\n"
        "**Nothing is skipped silently.** Message and plugin interactions, interactions with no "
        "method or path, and request bodies that cannot be decoded are listed under "
        "`unsupported` and in `findings`; embedded Pact 1 matchers, unknown matchers, request "
        "generators and unreadable response bodies are `degraded` findings; each provider state "
        "the runner must set up is an `info` finding.\n\n"
        "Nothing is persisted. Requires `pacts:view`."
    ),
    responses={
        404: {
            "description": (
                "`pacticipant-not-found` or `pact-not-found`: no such provider, consumer or pact "
                "version in this workspace."
            )
        }
    },
)
def compile_pact_version_suite(
    tenant_slug: str,
    provider: str,
    consumer: str,
    sha: str = Path(..., pattern=_SHA_PATTERN, description="The pact version's SHA-256 (64 hex characters)."),
    body: PactSuiteCompileRequest = PactSuiteCompileRequest(),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PactSuiteResponse:
    """Compile the contract suite of one pact version.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant scopes every lookup).
        provider: The provider's handle, id or name.
        consumer: The consumer's handle, id or name.
        sha: The pact version's content address.
        body: The compiler options.
        auth_data: The authenticated principal.

    Returns:
        The pair, the pact version and the manifest.

    Raises:
        HTTPException: 404 for an unknown or foreign pacticipant or pact version, 403 without
            ``pacts:view``, 400 for a malformed pacticipant reference, 422 for a malformed SHA or
            options.
    """
    enforce_permission(db, auth_data, Resource.PACTS, Action.VIEW)
    _ = tenant_slug
    try:
        pact = get_pact_by_sha(db, _tenant_id(auth_data), provider, consumer, sha)
    except (PactPublicationError, PacticipantValidationError) as exc:
        code = str(getattr(exc, "code", "") or CODE_PACT_NOT_FOUND)
        status = 404 if code.endswith("not-found") else 400
        raise HTTPException(status_code=status, detail={"code": code, "message": str(exc)}) from exc
    manifest = compile_pact_suite(
        pact.content,
        consumer=pact.consumer_name,
        provider=pact.provider_name,
        options=body.options,
        source=SuiteSourceInfo(
            kind="pact",
            reference=pact_suite_reference(pact.provider_slug, pact.consumer_slug, pact.sha),
            artifact_slug=pact.provider_slug,
            source_format=pact.specification_version,
        ),
    )
    return PactSuiteResponse(
        consumer=pact.consumer_slug,
        provider=pact.provider_slug,
        pact_version_sha=pact.sha,
        manifest=manifest,
    )
