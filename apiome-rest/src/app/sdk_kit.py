"""The public client kit — SDK-3.3 (#4493).

A consumer who lands on a published spec in the browse portal wants one thing: something they
can unzip and run. This module builds it — a deterministic ``sdk.client-kit.v1`` archive holding
the contract, a README, and one runnable snippet per operation per language.

**Why a kit and not a generated library.** The original SDK-3.3 scope served "the latest
generated artifact" from the SDK-1.1 artifact store. That ticket, the generator SPI (SDK-1.2),
both language generators (SDK-2.1/2.2) and the dashboard/CLI surfaces (SDK-3.1/3.2) were all
closed **not-planned**, so there is no artifact to serve and no generator to make one. What did
ship is the SDK-2.3 snippet service, which renders runnable per-operation code straight from the
persisted canonical model. This module packages that output: the kit is what SDK-3.3 can honestly
deliver today, and it is built at request time rather than stored, so there is no artifact
lifecycle to retain, expire or invalidate.

Three properties are load-bearing.

**It is byte-deterministic.** Every entry is written through :func:`app.zip_bundle.write_zip_entry`
with a pinned timestamp, entries are emitted in a fixed order, and the snippets inherit
:mod:`app.snippet_render`'s fixed-defaults, seed-0 synthesis. The same revision plus the same
branding therefore produce the same bytes, which is what lets the route serve a content-addressed
``ETag`` and what lets a consumer diff two downloads meaningfully.

**It never refuses over one bad operation.** A gRPC method or a GraphQL field has no HTTP binding
and no snippet is defined for it. Those are recorded in the manifest's ``skipped`` list with a
reason and left out of the archive — a kit covering an API's twelve REST operations is worth
shipping even when its two subscriptions cannot be rendered.

**Its work is bounded.** A spec with thousands of operations would otherwise render thousands of
snippets on an anonymous, unauthenticated request. :data:`MAX_KIT_OPERATIONS` caps it and the
manifest says so, rather than the request quietly taking a minute.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .canonical_model import CanonicalApi, Operation
from .sdk_generation_settings import ResolvedBranding
from .snippet_render import (
    INSTALL_LINES,
    SUPPORTED_LANGS,
    SnippetPlaceholder,
    SnippetRenderError,
    render_snippet,
)
from .zip_bundle import write_zip_entry

__all__ = [
    "KIT_MEDIA_TYPE",
    "KIT_SCHEMA_VERSION",
    "LANGUAGE_FILE_EXTENSIONS",
    "LANGUAGE_LABELS",
    "MAX_KIT_OPERATIONS",
    "PACKAGE_INSTALL_COMMANDS",
    "ClientKit",
    "KitCoordinates",
    "KitSummary",
    "build_client_kit",
    "summarize_kit",
    "kit_filename",
    "package_install_command",
    "spec_filename",
]

#: The addressable shape of the archive's ``manifest.json``.
KIT_SCHEMA_VERSION = "sdk.client-kit.v1"

#: What the download is served as.
KIT_MEDIA_TYPE = "application/zip"

#: How many operations a kit renders at most.
#:
#: The kit is built per request on an anonymous route, and rendering is three snippets per
#: operation, so an unbounded spec is unbounded work for an unauthenticated caller. The cap is
#: generous enough that no realistic published API hits it, and the manifest records truncation so
#: a consumer of a very large API is told rather than silently short-changed.
MAX_KIT_OPERATIONS = 250

#: Human label per canonical language, for the README's section headings.
LANGUAGE_LABELS: Dict[str, str] = {
    "ts": "TypeScript / JavaScript",
    "python": "Python",
    "curl": "cURL",
}

#: File extension per canonical language, for the snippet files.
LANGUAGE_FILE_EXTENSIONS: Dict[str, str] = {"ts": "ts", "python": "py", "curl": "sh"}

#: Fenced-block language tag per canonical language, for the README.
_MARKDOWN_FENCE: Dict[str, str] = {"ts": "ts", "python": "python", "curl": "bash"}

#: How a resolved package name is installed, per ecosystem (SDK-3.4 reports the names).
PACKAGE_INSTALL_COMMANDS: Dict[str, str] = {
    "npm": "npm install {name}",
    "pypi": "pip install {name}",
}

#: Source formats whose captured document is neither JSON nor YAML, mapped to their conventional
#: extension. Anything not listed here is sniffed (JSON → ``.json``, otherwise ``.yaml``), which is
#: right for the OpenAPI/AsyncAPI/Arazzo/JSON-Schema family that makes up nearly every kit.
_SPEC_EXTENSIONS: Dict[str, str] = {
    "graphql": "graphql",
    "grpc": "proto",
    "protobuf": "proto",
    "wsdl": "wsdl",
    "xsd": "xsd",
    "wit": "wit",
    "cddl": "cddl",
    "avro-idl": "avdl",
    "sql": "sql",
    "raml": "raml",
    "apiblueprint": "apib",
}

#: Characters kept in a snippet filename; everything else becomes a separator. Case is preserved —
#: ``getWidget.ts`` is what a consumer expects to find, not ``getwidget.ts``.
_SLUG_UNSAFE = re.compile(r"[^A-Za-z0-9]+")

#: Characters kept in the download filename, which mirrors browse's export naming
#: (``widgets-1.0.0-asyncapi.yaml``) and so keeps the dots of a version label.
_FILENAME_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class KitCoordinates:
    """Which published revision a kit was built for.

    Attributes:
        tenant_slug: The owning tenant's slug, as the browse URL named it.
        project_slug: The project (artifact) slug.
        version_slug: The version label the URL addressed.
        version_record_id: The resolved revision (``versions.id``) — the provenance that matters,
            because a version label can be re-published while a revision id cannot.
        version_label: The revision's source-declared version label, when it has one.
    """

    tenant_slug: str
    project_slug: str
    version_slug: str
    version_record_id: str
    version_label: Optional[str] = None


@dataclass(frozen=True)
class ClientKit:
    """A built kit: its bytes plus what a route needs to describe them.

    Attributes:
        content: The archive bytes, ready to serve as ``application/zip``.
        filename: The download filename.
        manifest: The manifest that was written into the archive, so a route can report the
            operation counts without re-opening the zip.
    """

    content: bytes
    filename: str
    manifest: Dict[str, Any]

    @property
    def content_length(self) -> int:
        """The archive's size in bytes."""
        return len(self.content)


@dataclass(frozen=True)
class KitSummary:
    """How much of an API a kit would cover, without building one.

    The info route needs three numbers to draw a panel; rendering every snippet in every language
    to count them would do the download's whole job for a call that discards the result.

    Attributes:
        operation_count: Operations the kit will carry snippets for.
        total_operation_count: Operations the API declares.
        truncated: Whether the API has more renderable operations than one kit carries.
    """

    operation_count: int
    total_operation_count: int
    truncated: bool


def summarize_kit(api: CanonicalApi) -> KitSummary:
    """Count what a kit for ``api`` would contain, without rendering anything.

    Eligibility is exactly :func:`app.snippet_render.synthesize_request`'s precondition — an
    operation needs an HTTP method and path — so the counts match what
    :func:`build_client_kit` actually writes.

    Args:
        api: The canonical model a kit would be built from.

    Returns:
        The :class:`KitSummary`.
    """
    total = 0
    renderable = 0
    for op in api.operations():
        total += 1
        if _is_renderable(op):
            renderable += 1
    return KitSummary(
        operation_count=min(renderable, MAX_KIT_OPERATIONS),
        total_operation_count=total,
        truncated=renderable > MAX_KIT_OPERATIONS,
    )


def _is_renderable(op: Operation) -> bool:
    """Whether a snippet is defined for this operation (it has an HTTP binding)."""
    return bool(op.http_method and op.http_path)


@dataclass
class _Entry:
    """One file staged for the archive, before it is written."""

    path: str
    text: str
    subject: Optional[str] = None


@dataclass
class _RenderedOperation:
    """One operation's snippets, staged for both the archive and the README."""

    op: Operation
    slug: str
    identifier: str
    method: str
    path: str
    summary: Optional[str]
    #: lang → (install line, code)
    snippets: Dict[str, Tuple[Optional[str], str]] = field(default_factory=dict)
    #: The substitutable tokens the snippets carry. Synthesis is language-independent, so one
    #: language's list describes them all.
    placeholders: List[SnippetPlaceholder] = field(default_factory=list)


def package_install_command(ecosystem: str, name: str) -> Optional[str]:
    """Return the shell command that installs ``name`` from ``ecosystem``.

    Args:
        ecosystem: A key from :data:`app.sdk_generation_settings.ECOSYSTEMS`.
        name: The resolved package name.

    Returns:
        The install command, or ``None`` for an ecosystem with no known command.
    """
    template = PACKAGE_INSTALL_COMMANDS.get(ecosystem)
    return template.format(name=name) if template and name else None


def kit_filename(coordinates: KitCoordinates) -> str:
    """The download filename for a kit, e.g. ``widgets-1.0.0-sdk.zip``.

    Args:
        coordinates: The revision the kit was built for.

    Returns:
        A stable, human-readable filename.
    """
    project = _filename_safe(coordinates.project_slug) or "api"
    version = _filename_safe(coordinates.version_slug) or "latest"
    return f"{project}-{version}-sdk.zip"


def spec_filename(source_format: Optional[str], source_text: Optional[str]) -> str:
    """The in-archive name for the captured source document.

    The format key decides it for the text formats that are neither JSON nor YAML; everything else
    is sniffed, because the JSON/YAML family shares one format key per *specification*, not per
    serialization (an ``openapi`` revision may have been captured as either).

    Args:
        source_format: The captured source's format key, when the row declared one.
        source_text: The captured document, used for the JSON sniff.

    Returns:
        A filename such as ``spec.json``, ``spec.yaml`` or ``spec.graphql``.
    """
    key = (source_format or "").strip().lower()
    for known, extension in _SPEC_EXTENSIONS.items():
        # Format keys carry a version suffix (``openapi-3.1``, ``asyncapi-3``), so match on the
        # family rather than on equality.
        if key == known or key.startswith(f"{known}-"):
            return f"spec.{extension}"
    stripped = (source_text or "").lstrip()
    if stripped[:1] in {"{", "["}:
        return "spec.json"
    return "spec.yaml"


def _slug(value: str) -> str:
    """Make a value safe as a filename stem, collapsing runs of unsafe characters to ``-``."""
    return _SLUG_UNSAFE.sub("-", (value or "").strip()).strip("-")


def _filename_safe(value: str) -> str:
    """Make a value safe inside a download filename, keeping dots so ``1.0.0`` survives."""
    return _FILENAME_UNSAFE.sub("-", (value or "").strip()).strip("-.")


def _operation_identifier(op: Operation) -> str:
    """The id a consumer would address this operation by.

    Mirrors :func:`app.snippet_render.find_operation`'s precedence, so an id printed in the kit is
    one the public snippet route actually resolves.
    """
    return op.extras.get("operationId") or op.name or op.key


def _operation_slug(op: Operation, taken: Dict[str, int]) -> str:
    """A unique, deterministic filename stem for one operation.

    Args:
        op: The operation to name.
        taken: Stems already used, mapped to how many times — mutated in place.

    Returns:
        The stem, suffixed ``-2``, ``-3``… when an earlier operation already claimed it.
    """
    base = _slug(_operation_identifier(op))
    if not base:
        base = _slug(f"{op.http_method or 'op'} {op.http_path or op.key}") or "operation"
    # Uniqueness is tracked case-insensitively: `getWidget` and `getwidget` are two names on a
    # case-sensitive filesystem and one file on a Mac or Windows one, and a kit that loses an
    # operation when it is unzipped is worse than one with a `-2` in it.
    fold = base.casefold()
    seen = taken.get(fold, 0) + 1
    taken[fold] = seen
    return base if seen == 1 else f"{base}-{seen}"


def _render_operations(
    api: CanonicalApi, branding: ResolvedBranding
) -> Tuple[List[_RenderedOperation], List[Dict[str, str]], KitSummary]:
    """Render every eligible operation in every language.

    The cap counts *renderable* operations only, so a model's non-HTTP operations never consume
    kit capacity — which is what keeps these counts identical to :func:`summarize_kit`'s.

    Args:
        api: The canonical model to render from.
        branding: The tenant's resolved SDK-3.4 branding, stamped onto every snippet.

    Returns:
        ``(rendered, skipped, summary)`` — the rendered operations in declaration order, one
        record per operation no snippet is defined for, and the counts for the manifest.
    """
    rendered: List[_RenderedOperation] = []
    skipped: List[Dict[str, str]] = []
    taken: Dict[str, int] = {}
    total = 0
    omitted = 0

    for op in api.operations():
        total += 1
        if _is_renderable(op) and len(rendered) >= MAX_KIT_OPERATIONS:
            omitted += 1
            continue
        identifier = _operation_identifier(op)
        snippets: Dict[str, Tuple[Optional[str], str]] = {}
        placeholders: List[SnippetPlaceholder] = []
        failure: Optional[str] = None
        for lang in SUPPORTED_LANGS:
            try:
                render = render_snippet(
                    api,
                    op,
                    lang,
                    user_agent=branding.user_agent,
                    license_header=branding.license_header,
                )
            except SnippetRenderError as exc:
                # No HTTP binding — the same 422 condition the snippet route reports. One skipped
                # operation must not cost the consumer the rest of the kit.
                failure = str(exc)
                break
            snippets[lang] = (render.install, render.code)
            placeholders = render.placeholders
        if failure is not None:
            skipped.append({"operation_id": identifier, "key": op.key, "reason": failure})
            continue
        rendered.append(
            _RenderedOperation(
                op=op,
                slug=_operation_slug(op, taken),
                identifier=identifier,
                method=(op.http_method or "").upper(),
                path=op.http_path or "",
                summary=op.description,
                snippets=snippets,
                placeholders=placeholders,
            )
        )
    return (
        rendered,
        skipped,
        KitSummary(
            operation_count=len(rendered),
            total_operation_count=total,
            truncated=omitted > 0,
        ),
    )


def _package_lines(branding: ResolvedBranding) -> List[Tuple[str, str, Optional[str]]]:
    """Return ``(ecosystem, name, install command)`` for each resolved package name."""
    return [
        (ecosystem, name, package_install_command(ecosystem, name))
        for ecosystem, name in sorted(branding.package_names.items())
    ]


def _placeholder_legend(rendered: List[_RenderedOperation]) -> List[Tuple[str, str]]:
    """Collect the distinct placeholder tokens across the kit, for the README's legend.

    Built from the renderer's structured placeholder records rather than by scanning the emitted
    code: the code contains other upper-case words (HTTP methods, header names) that a text scan
    could not tell from a token the reader is meant to substitute.

    Args:
        rendered: The operations whose snippets are in the kit.

    Returns:
        ``(token, description)`` pairs, ordered by token.
    """
    tokens: Dict[str, str] = {}
    for entry in rendered:
        for placeholder in entry.placeholders:
            if placeholder.token in tokens:
                continue
            if placeholder.kind == "secret":
                where = f" {placeholder.location}" if placeholder.location else ""
                tokens[placeholder.token] = f"credential for `{placeholder.name}`{where}"
            else:
                tokens[placeholder.token] = f"{placeholder.kind} `{placeholder.name}`"
    return sorted(tokens.items())


def _build_readme(
    api: CanonicalApi,
    coordinates: KitCoordinates,
    branding: ResolvedBranding,
    rendered: List[_RenderedOperation],
    skipped: List[Dict[str, str]],
    spec_name: str,
    summary: KitSummary,
) -> str:
    """Compose the kit's ``README.md``.

    Args:
        api: The canonical model, for the API's title and version.
        coordinates: The revision the kit was built for.
        branding: The tenant's resolved branding (package names, licence header).
        rendered: The operations whose snippets are in the archive.
        skipped: Operations left out, with reasons.
        spec_name: The in-archive filename of the captured contract.
        summary: The kit's operation counts, for the truncation note.

    Returns:
        The README's Markdown text.
    """
    title = api.title or coordinates.project_slug
    version = coordinates.version_label or coordinates.version_slug
    lines: List[str] = [
        f"# {title} — client kit",
        "",
        f"Runnable examples for every operation of **{coordinates.project_slug}** "
        f"version **{version}**, generated by Apiome from the published contract.",
        "",
    ]
    if api.description:
        lines += [api.description.strip(), ""]

    if branding.license_header:
        lines += ["## Licence", "", "```", branding.license_header.strip(), "```", ""]

    packages = _package_lines(branding)
    if packages:
        lines += ["## Packages", ""]
        for ecosystem, name, command in packages:
            lines.append(f"- **{ecosystem}** — `{name}`" + (f" · `{command}`" if command else ""))
        lines.append("")

    lines += ["## Requirements", ""]
    for lang in SUPPORTED_LANGS:
        install = INSTALL_LINES.get(lang)
        label = LANGUAGE_LABELS.get(lang, lang)
        lines.append(f"- **{label}** — " + (f"`{install}`" if install else "nothing to install"))
    lines.append("")

    legend = _placeholder_legend(rendered)
    if legend:
        lines += [
            "## Placeholders",
            "",
            "Replace these before running anything. `$`-prefixed tokens are credentials — supply "
            "them from your environment rather than pasting them into a file.",
            "",
        ]
        lines += [f"- `{token}` — {description}" for token, description in legend]
        lines.append("")

    lines += [
        "## Contents",
        "",
        f"- `{spec_name}` — the published contract, exactly as its author wrote it.",
        "- `manifest.json` — what this kit contains and which revision it came from.",
        "- `snippets/<language>/<operation>.<ext>` — one runnable example per operation.",
        "",
        "## Operations",
        "",
    ]
    if summary.truncated:
        lines += [
            f"> This API declares {summary.total_operation_count} operations; the kit carries "
            f"the first {MAX_KIT_OPERATIONS}. Use the API's own reference for the rest.",
            "",
        ]

    for entry in rendered:
        heading = f"{entry.method} {entry.path}".strip() or entry.identifier
        lines += [f"### {heading}", ""]
        if entry.identifier and entry.identifier != heading:
            lines += [f"`{entry.identifier}`", ""]
        if entry.summary:
            lines += [entry.summary.strip(), ""]
        for lang in SUPPORTED_LANGS:
            staged = entry.snippets.get(lang)
            if staged is None:
                continue
            install, code = staged
            lines += [f"**{LANGUAGE_LABELS.get(lang, lang)}**", ""]
            if install:
                lines += ["```bash", install, "```", ""]
            lines += [f"```{_MARKDOWN_FENCE.get(lang, '')}", code, "```", ""]

    if skipped:
        lines += [
            "## Not included",
            "",
            "These operations have no HTTP binding, so no request snippet is defined for them:",
            "",
        ]
        lines += [f"- `{item['key']}` — {item['reason']}" for item in skipped]
        lines.append("")

    lines += [
        "---",
        "",
        f"Apiome client kit `{KIT_SCHEMA_VERSION}` · revision `{coordinates.version_record_id}`.",
        "",
    ]
    return "\n".join(lines)


def build_client_kit(
    api: CanonicalApi,
    *,
    coordinates: KitCoordinates,
    branding: ResolvedBranding,
    source_text: Optional[str] = None,
    source_format: Optional[str] = None,
    settings_fingerprint: Optional[str] = None,
    apiome_version: Optional[str] = None,
) -> ClientKit:
    """Build the downloadable client kit for one published revision.

    Args:
        api: The revision's canonical model.
        coordinates: The slug/revision coordinates the kit was requested at.
        branding: The tenant's resolved SDK-3.4 settings — its user-agent is stamped on every
            request, its licence header on every snippet, its package names into the README.
        source_text: The captured contract, included verbatim when present.
        source_format: The captured contract's format key, used to name its file.
        settings_fingerprint: The merged settings' fingerprint, recorded as provenance so a
            changed kit can be attributed to changed branding rather than to a changed API.
        apiome_version: The API version that built the kit.

    Returns:
        The :class:`ClientKit`. Building it twice from the same arguments yields identical bytes.
    """
    rendered, skipped, summary = _render_operations(api, branding)
    spec_name = spec_filename(source_format, source_text)

    entries: List[_Entry] = []
    for entry in rendered:
        for lang, (_install, code) in sorted(entry.snippets.items()):
            extension = LANGUAGE_FILE_EXTENSIONS.get(lang, "txt")
            entries.append(
                _Entry(
                    path=f"snippets/{lang}/{entry.slug}.{extension}",
                    # A trailing newline: these are source files, and a consumer's tooling will
                    # add one anyway — better that the bytes never change under them.
                    text=code if code.endswith("\n") else f"{code}\n",
                    subject=entry.identifier,
                )
            )
    if source_text:
        entries.append(_Entry(path=spec_name, text=source_text, subject="contract"))

    readme = _build_readme(
        api,
        coordinates,
        branding,
        rendered,
        skipped,
        spec_name,
        summary,
    )
    entries.append(_Entry(path="README.md", text=readme, subject="readme"))
    entries.sort(key=lambda item: item.path)

    manifest = {
        "schema_version": KIT_SCHEMA_VERSION,
        "api": {
            "title": api.title,
            "version": api.version,
            "paradigm": str(getattr(api.paradigm, "value", api.paradigm)),
            "format": api.format,
        },
        "tenant_slug": coordinates.tenant_slug,
        "project_slug": coordinates.project_slug,
        "version_slug": coordinates.version_slug,
        "languages": list(SUPPORTED_LANGS),
        "package_names": dict(sorted(branding.package_names.items())),
        "operation_count": summary.operation_count,
        "total_operation_count": summary.total_operation_count,
        "truncated": summary.truncated,
        "operations": [
            {
                "operation_id": entry.identifier,
                "key": entry.op.key,
                "method": entry.method,
                "path": entry.path,
                "slug": entry.slug,
            }
            for entry in rendered
        ],
        "skipped": skipped,
        "provenance": {
            "version_record_id": coordinates.version_record_id,
            "version_label": coordinates.version_label,
            "source_format": source_format,
            "renderer": f"app.snippet_render/{KIT_SCHEMA_VERSION}",
            "apiome_version": apiome_version,
            "settings_fingerprint": settings_fingerprint,
        },
        "files": [
            {
                "path": entry.path,
                "size_bytes": len(entry.text.encode("utf-8")),
                "sha256": hashlib.sha256(entry.text.encode("utf-8")).hexdigest(),
                "subject": entry.subject,
            }
            for entry in entries
        ],
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for entry in entries:
            write_zip_entry(archive, entry.path, entry.text)
        # The manifest is written last and never lists itself, matching the export bundle's rule
        # (a table of contents that contained its own digest could never be verified).
        write_zip_entry(
            archive, "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False)
        )

    return ClientKit(
        content=buffer.getvalue(),
        filename=kit_filename(coordinates),
        manifest=manifest,
    )
