"""The public "Get SDK" surface — SDK-3.3 (#4493).

Two anonymous, slug-addressed routes behind the browse portal's Get SDK panel:

* **``GET /v1/browse/tenants/{t}/projects/{p}/versions/{v}/sdk``** — what the panel needs to draw
  itself: the resolved package names (SDK-3.4), the install line per language, the generated Go
  client's module path (SDK-2.4), how many operations the kit covers, and the download's filename.
  The Go client is *named* here, never generated: its module path and package name are pure
  functions of the coordinates and the branding.
* **``GET …/sdk/download``** — the kit itself (:mod:`app.sdk_kit`) as ``application/zip``.

**One gate, one answer.** Both routes resolve the revision through
:func:`app.export_source.load_public_export_source`, so a private, draft or unknown version is a
uniform 404 that cannot confirm a hidden artifact exists. They then ask
:func:`app.sdk_generation_settings_store.load_public_sdk_enabled` whether this project has opted
in, and **a project that has not gets the same 404**. That is deliberate: a distinct 403 would
tell an anonymous caller that the project exists and merely declined, and the browse panel needs
no such distinction — it draws nothing when the info call fails.

**Nothing is stored.** The kit is built per request from the persisted canonical model. Because
:func:`app.sdk_kit.build_client_kit` is byte-deterministic, the download still carries a strong
content-addressed ``ETag`` (and honours ``If-None-Match``) plus a ``Digest`` over the exact bytes,
without an artifact store to retain, expire or invalidate. Both routes share the MFX-7.3 public
export rate limit and the download reuses its size cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .export_artifact_store import content_sha256_hex, content_sha256_hex_only, digest_header_value
from .export_source import ExportSource, ExportSourceError, load_public_export_source
from .go_client_generator import DEFAULT_GO_VERSION, GO_ECOSYSTEM
from .server_stub_generator import EXPRESS_DIRECTORY, FASTAPI_DIRECTORY
from .public_export_guards import (
    enforce_public_export_rate_limit,
    public_export_document_max_bytes,
)
from .sdk_generation_settings import PatternContext, ResolvedBranding
from .sdk_generation_settings_store import load_settings, public_sdk_enabled_from
from .sdk_kit import (
    GO_CLIENT_DIRECTORY,
    SERVER_STUB_DIRECTORY,
    KIT_MEDIA_TYPE,
    KIT_SCHEMA_VERSION,
    LANGUAGE_FILE_EXTENSIONS,
    LANGUAGE_LABELS,
    ClientKit,
    KitCoordinates,
    build_client_kit,
    go_client_coordinates,
    server_stub_coordinates,
    kit_filename,
    package_install_command,
    summarize_kit,
)
from .snippet_render import INSTALL_LINES, SUPPORTED_LANGS

router = APIRouter(prefix="/v1/browse", tags=["browse"])

_SDK_PATH = "/tenants/{tenant_slug}/projects/{project_slug}/versions/{version_slug}/sdk"

# Short enough that opting a project in (or re-publishing it) propagates promptly; the ETag makes
# repeat reads of an unchanged kit free.
_SDK_MAX_AGE = 300

_GATED_404 = {
    404: {
        "description": (
            "No published public version matches the slugs, or the project has not enabled "
            "public SDK access. The two are deliberately indistinguishable."
        )
    },
    429: {"description": "Public export rate limit exceeded (MFX-7.3)."},
}


# ===========================================================================
# Response models
# ===========================================================================


class SdkLanguageModel(BaseModel):
    """One language the kit and the snippet tabs offer."""

    model_config = ConfigDict(extra="forbid")

    lang: str = Field(description="The canonical language key (``ts`` / ``python`` / ``curl``).")
    label: str = Field(description="Human label for a tab or heading.")
    install: Optional[str] = Field(
        default=None, description="Shell command installing the dependency, or null."
    )
    file_extension: str = Field(description="Extension the kit writes this language's files with.")


class SdkPackageModel(BaseModel):
    """One resolved package name, as the tenant's SDK-3.4 patterns produce it."""

    model_config = ConfigDict(extra="forbid")

    ecosystem: str = Field(description="Package ecosystem (``npm``, ``pypi``).")
    name: str = Field(description="The resolved package name for this project.")
    install: Optional[str] = Field(
        default=None, description="The command that installs it, when the ecosystem has one."
    )


class SdkGoClientModel(BaseModel):
    """The generated Go client the download carries — SDK-2.4 (#4488).

    Reported separately from ``languages`` because it is not a snippet: it is a compilable module
    inside the archive, with a module path a consumer imports rather than a tab they copy from.
    """

    model_config = ConfigDict(extra="forbid")

    directory: str = Field(description="The directory the module sits in inside the archive.")
    module_path: str = Field(description="The `go.mod` module path the generated client declares.")
    package_name: str = Field(description="The Go package name its files declare.")
    go_version: str = Field(description="The `go` directive the module declares.")
    install: Optional[str] = Field(
        default=None,
        description="The `go get` command, once the module is published at that path.",
    )
    method_count: int = Field(
        description="Client methods the module carries — the kit's renderable operations."
    )


class SdkServerStubsModel(BaseModel):
    """The generated server stubs the download carries — SDK-2.5 (#4490).

    Reported alongside the Go client because it answers the opposite question: the client is what a
    consumer *calls* this API with, the stubs are what a team *implements* it with. A panel that
    offered only one of the two would hide half of what the same archive contains.
    """

    model_config = ConfigDict(extra="forbid")

    directory: str = Field(description="The directory the stub projects sit in inside the archive.")
    targets: List[str] = Field(
        default_factory=list,
        description="The frameworks generated, in documentation order (``fastapi``, ``express``).",
    )
    python_package: str = Field(description="The Python package the FastAPI project declares.")
    npm_package: str = Field(description="The npm package the Express project declares.")
    route_count: int = Field(
        description="Routes each project carries — the kit's renderable operations."
    )


class SdkDownloadModel(BaseModel):
    """What the download will be, so a client can label its button before fetching."""

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(description="Suggested download filename.")
    media_type: str = Field(description="The download's media type (``application/zip``).")
    schema_version: str = Field(description="The kit manifest's shape (``sdk.client-kit.v1``).")


class PublicSdkInfoResponse(BaseModel):
    """Everything the browse Get SDK panel needs, in one anonymous call."""

    model_config = ConfigDict(extra="forbid")

    tenant_slug: str = Field(description="The owning tenant's slug, as requested.")
    project_slug: str = Field(description="The project (artifact) slug, as requested.")
    version_slug: str = Field(description="The version label, as requested (e.g. ``1.0.0``).")
    version_record_id: str = Field(description="The resolved revision (``versions.id``).")
    version_label: Optional[str] = Field(
        default=None, description="The resolved revision's source-declared version label."
    )
    api_title: Optional[str] = Field(default=None, description="The API's declared title.")
    languages: List[SdkLanguageModel] = Field(
        default_factory=list, description="Languages offered, in documentation order."
    )
    packages: List[SdkPackageModel] = Field(
        default_factory=list,
        description="Resolved package names for this project, empty when none are configured.",
    )
    operation_count: int = Field(
        description="Operations the kit carries a snippet for (non-HTTP ones are excluded)."
    )
    total_operation_count: int = Field(description="Operations the API declares in total.")
    truncated: bool = Field(
        description="True when the API has more operations than one kit carries."
    )
    license_header: Optional[str] = Field(
        default=None, description="The licence text stamped on every snippet, when configured."
    )
    settings_fingerprint: Optional[str] = Field(
        default=None,
        description="Fingerprint of the merged SDK settings the kit was branded with (SDK-3.4).",
    )
    go_client: SdkGoClientModel = Field(
        description="The generated Go client the download carries (SDK-2.4)."
    )
    server_stubs: SdkServerStubsModel = Field(
        description="The generated server stubs the download carries (SDK-2.5)."
    )
    download: SdkDownloadModel


# ===========================================================================
# Shared helpers
# ===========================================================================


def _require_public_sdk_rate_limit(request: Request) -> None:
    """FastAPI dependency: reuse the MFX-7.3 public-export rate limit for SDK reads."""
    enforce_public_export_rate_limit(request)


def _not_found(tenant_slug: str, project_slug: str, version_slug: str) -> HTTPException:
    """The one refusal both routes use, whatever the actual reason.

    A version that does not exist, one that is private or unpublished, and one whose project has
    not opted into public SDK access all produce this. Distinguishing them would leak exactly what
    the gate exists to hide.
    """
    return HTTPException(
        status_code=404,
        detail=(
            f"No public SDK is available for {tenant_slug!r}/{project_slug!r} "
            f"version {version_slug!r}."
        ),
    )


@dataclass(frozen=True)
class _SdkRequest:
    """Everything both routes need about one gated revision, read once.

    The gate, the branding and the provenance fingerprint all come out of the *same* two settings
    rows. Asking three separate loaders would mean three identical queries per anonymous request,
    so this resolves the revision and reads the settings once, then hands both routes what they
    need.

    Attributes:
        source: The resolved published revision.
        coordinates: The kit coordinates for this request.
        branding: The tenant's resolved SDK-3.4 branding.
        settings_fingerprint: The merged settings' fingerprint, for provenance.
    """

    source: ExportSource
    coordinates: KitCoordinates
    branding: ResolvedBranding
    settings_fingerprint: Optional[str]


def _load_gated_request(
    tenant_slug: str, project_slug: str, version_slug: str
) -> _SdkRequest:
    """Resolve a published public revision that has opted into public SDK access.

    Args:
        tenant_slug: The owning tenant's slug.
        project_slug: The project (artifact) slug.
        version_slug: The version label of the published revision.

    Returns:
        The revision and the settings that apply to it.

    Raises:
        HTTPException: 404 when the revision is not publicly visible or the project has not opted
            in; the loader's own status (e.g. 422) when a visible revision has no usable source.
    """
    try:
        source = load_public_export_source(tenant_slug, project_slug, version_slug)
    except ExportSourceError as exc:
        if exc.status_code == 404:
            raise _not_found(tenant_slug, project_slug, version_slug) from exc
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    # An anonymous caller supplied slugs; the loader is where a tenant id comes from, and it is
    # what lets a public surface read tenant-scoped settings at all.
    if not source.tenant_id:
        raise _not_found(tenant_slug, project_slug, version_slug)

    context = PatternContext(
        tenant=tenant_slug,
        project=project_slug,
        version=str(source.version_label or version_slug),
    )
    out = load_settings(source.tenant_id, source.artifact_id, context)
    if not public_sdk_enabled_from(out):
        raise _not_found(tenant_slug, project_slug, version_slug)

    return _SdkRequest(
        source=source,
        coordinates=KitCoordinates(
            tenant_slug=tenant_slug,
            project_slug=project_slug,
            version_slug=version_slug,
            version_record_id=source.version_record_id,
            version_label=source.version_label,
        ),
        branding=ResolvedBranding(
            package_names=dict(out.resolved.package_names),
            license_header=out.resolved.license_header,
            user_agent=out.resolved.user_agent,
        ),
        settings_fingerprint=out.content_fingerprint,
    )


def _build_kit(request: _SdkRequest, apiome_version: Optional[str]) -> ClientKit:
    """Build the kit for an already-gated revision."""
    return build_client_kit(
        request.source.api,
        coordinates=request.coordinates,
        branding=request.branding,
        source_text=request.source.source_text,
        source_format=request.source.source_format,
        settings_fingerprint=request.settings_fingerprint,
        apiome_version=apiome_version,
    )


def _if_none_match_hit(if_none_match: Optional[str], etag: str) -> bool:
    """Return ``True`` when the client's ``If-None-Match`` already holds ``etag``.

    Tolerates the weak-validator ``W/`` prefix, the ``*`` wildcard, and a comma-separated
    candidate list — the same semantics as the sibling snippet routes.
    """
    if not if_none_match:
        return False
    for candidate in if_none_match.split(","):
        token = candidate.strip()
        if token == "*":
            return True
        if token.startswith("W/"):
            token = token[2:].strip()
        if token == etag:
            return True
    return False


def _apiome_version(request: Request) -> Optional[str]:
    """The running API version, for the kit's provenance."""
    return getattr(request.app, "version", None)


# ===========================================================================
# Routes
# ===========================================================================


@router.get(
    _SDK_PATH,
    response_model=PublicSdkInfoResponse,
    responses=dict(_GATED_404),
    dependencies=[Depends(_require_public_sdk_rate_limit)],
    summary="Describe the public SDK available for a published public version (no auth)",
)
async def get_public_sdk_info(
    tenant_slug: str,
    project_slug: str,
    version_slug: str,
) -> PublicSdkInfoResponse:
    """Return what the browse Get SDK panel needs to render itself.

    A 404 is the panel's instruction to render nothing at all — it is what an unpublished, private
    or non-opted-in project returns, so the caller needs no second question.

    Args:
        tenant_slug: The owning tenant's slug.
        project_slug: The project (artifact) slug within the tenant.
        version_slug: The version label (e.g. ``1.0.0``) of the published revision.

    Returns:
        The :class:`PublicSdkInfoResponse`.
    """
    gated = _load_gated_request(tenant_slug, project_slug, version_slug)
    source = gated.source
    branding = gated.branding
    # Counted, not built: rendering every snippet in three languages to report three numbers
    # would do the download's whole job for a call that throws the archive away.
    summary = summarize_kit(source.api)
    # Named, not generated: the module path and package name are pure functions of the coordinates
    # and the branding, so the panel can label the Go client without paying to emit it.
    go_module, go_package = go_client_coordinates(source.api, gated.coordinates, branding)
    # Named, not generated, for the same reason: both package names are pure functions of the
    # coordinates and the branding, so the panel can label the server stubs without emitting two
    # whole projects for a call that would throw them away.
    python_package, npm_package = server_stub_coordinates(source.api, gated.coordinates, branding)

    return PublicSdkInfoResponse(
        tenant_slug=tenant_slug,
        project_slug=project_slug,
        version_slug=version_slug,
        version_record_id=source.version_record_id,
        version_label=source.version_label,
        api_title=source.api.title,
        languages=[
            SdkLanguageModel(
                lang=lang,
                label=LANGUAGE_LABELS.get(lang, lang),
                install=INSTALL_LINES.get(lang),
                file_extension=LANGUAGE_FILE_EXTENSIONS.get(lang, "txt"),
            )
            for lang in SUPPORTED_LANGS
        ],
        packages=[
            SdkPackageModel(
                ecosystem=ecosystem,
                name=name,
                install=package_install_command(ecosystem, name),
            )
            for ecosystem, name in sorted(branding.package_names.items())
        ],
        operation_count=summary.operation_count,
        total_operation_count=summary.total_operation_count,
        truncated=summary.truncated,
        license_header=branding.license_header,
        settings_fingerprint=gated.settings_fingerprint,
        go_client=SdkGoClientModel(
            directory=GO_CLIENT_DIRECTORY,
            module_path=go_module,
            package_name=go_package,
            go_version=DEFAULT_GO_VERSION,
            install=package_install_command(GO_ECOSYSTEM, go_module),
            method_count=summary.operation_count,
        ),
        server_stubs=SdkServerStubsModel(
            directory=SERVER_STUB_DIRECTORY,
            targets=[FASTAPI_DIRECTORY, EXPRESS_DIRECTORY],
            python_package=python_package,
            npm_package=npm_package,
            route_count=summary.operation_count,
        ),
        download=SdkDownloadModel(
            filename=kit_filename(gated.coordinates),
            media_type=KIT_MEDIA_TYPE,
            schema_version=KIT_SCHEMA_VERSION,
        ),
    )


@router.get(
    _SDK_PATH + "/download",
    response_class=Response,
    responses={
        **_GATED_404,
        200: {"content": {KIT_MEDIA_TYPE: {}}, "description": "The client kit archive."},
        304: {"description": "Not modified (ETag matched If-None-Match)."},
        413: {"description": "The kit exceeds the public download limit."},
    },
    dependencies=[Depends(_require_public_sdk_rate_limit)],
    summary="Download the client kit for a published public version (no auth)",
)
async def download_public_sdk(
    request: Request,
    tenant_slug: str,
    project_slug: str,
    version_slug: str,
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
) -> Response:
    """Serve the ``sdk.client-kit.v1`` archive for one published public version.

    The archive is built per request and is byte-deterministic, so its ``ETag`` is a digest of the
    bytes themselves and a repeat request with ``If-None-Match`` short-circuits to 304 without the
    body being sent.

    Args:
        request: The incoming request, for the running API version.
        tenant_slug: The owning tenant's slug.
        project_slug: The project (artifact) slug within the tenant.
        version_slug: The version label (e.g. ``1.0.0``) of the published revision.
        if_none_match: Standard conditional-request header.

    Returns:
        The zip archive, or an empty 304.

    Raises:
        HTTPException: 404 when no public SDK is available; 413 when the kit exceeds the public
            download cap.
    """
    gated = _load_gated_request(tenant_slug, project_slug, version_slug)
    kit = _build_kit(gated, _apiome_version(request))

    cap = public_export_document_max_bytes()
    if cap is not None and kit.content_length > cap:
        raise HTTPException(
            status_code=413,
            detail=(
                f"The client kit exceeds the {cap}-byte public download limit "
                f"({kit.content_length} bytes built)."
            ),
        )

    # One hash, two uses: the archive's bytes are the ETag and the Digest, because building is
    # deterministic and there is no stored artifact whose identity could differ from its content.
    digest = content_sha256_hex(kit.content)
    etag = f'"{content_sha256_hex_only(digest)}"'
    headers: Dict[str, str] = {
        "Cache-Control": f"public, max-age={_SDK_MAX_AGE}",
        "ETag": etag,
        "Content-Disposition": f'attachment; filename="{kit.filename}"',
        "Digest": digest_header_value(digest),
        "X-Content-SHA256": content_sha256_hex_only(digest),
        # Provenance a consumer can read without unzipping — the two coordinates that identify
        # exactly what they downloaded.
        "X-Apiome-Version-Record-Id": gated.source.version_record_id,
        "X-Apiome-Kit-Schema": KIT_SCHEMA_VERSION,
    }
    if _if_none_match_hit(if_none_match, etag):
        return Response(status_code=304, headers=headers)
    headers["Content-Length"] = str(kit.content_length)
    return Response(content=kit.content, media_type=KIT_MEDIA_TYPE, headers=headers)


__all__ = ["router", "kit_filename"]
