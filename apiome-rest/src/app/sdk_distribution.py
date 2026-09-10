"""Publishable distributions — SDK-4.1 (#4495).

Downloading a zip is not how SDKs are consumed at scale: a team expects ``npm install @acme/api``
and ``pip install acme-api``. This module turns one published revision into the *artifact a
registry accepts* — an npm tarball and a PyPI source distribution — from exactly the material the
SDK-3.3 client kit already builds (:mod:`app.sdk_kit`): the contract verbatim, a README, and one
runnable snippet per operation.

**Why the kit's material and not a generated client.** SDK-4.1's stated dependency was "EPIC-2
stable" — the TypeScript (#4485) and Python (#4486) client generators. Both were closed
**not-planned**, along with the generator SPI (#4482) and the SDK-1.1 job service and artifact
store (#4481) this was to be a step on. What did ship is the SDK-2.3 snippet renderer, the SDK-2.4
Go client generator and the SDK-2.5 server stubs. So the pipeline publishes what exists, and it is
deliberately shaped so that it publishes whatever exists *later* without changing: a distribution
is assembled from a list of files plus metadata, and when a real TypeScript client generator lands
it becomes another contributor to that list rather than a second pipeline.

**What a consumer gets.** Each package installs as a working module: it exposes the contract it
was built from, the provenance of the revision that produced it, and the operation index — so a
consumer can `import` the package and point their own tooling at the spec, and every runnable
snippet ships beside it. The npm package additionally carries typings.

Three properties are load-bearing.

**It is byte-deterministic.** Every file is text, every archive entry goes through
:func:`app.tar_bundle.build_tar_gz` with pinned timestamps and ownership, and the snippets inherit
:mod:`app.snippet_render`'s fixed-defaults, seed-0 synthesis. The same revision, branding and
version therefore produce the same bytes — which is what lets a dry-run report the digest the real
publish will upload, and what lets a consumer rebuild and compare.

**Provenance rides in package metadata, not beside it.** ``package.json`` carries an ``apiome``
object and PyPI's core metadata carries ``Project-URL``/keyword entries naming the revision id,
the version line, the generator versions and the settings fingerprint. An installed package can
therefore be traced back to the spec revision that produced it with nothing but the package
manager — which is the acceptance criterion, and the reason the manifest is not the only copy.

**Nothing secret is ever in here.** A distribution is built from a contract and its branding; the
registry token is used by :mod:`app.sdk_registry_client` at upload time and never reaches this
module.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pprint import pformat
from typing import Any, Dict, List, Optional

from .canonical_model import CanonicalApi
from .sdk_generation_settings import ResolvedBranding
from .sdk_kit import (
    KIT_SCHEMA_VERSION,
    KitCoordinates,
    RenderedOperation,
    render_kit_operations,
    spec_filename,
)
from .sdk_publish_version import NPM_ECOSYSTEM, PUBLISH_ECOSYSTEMS, PYPI_ECOSYSTEM
from .snippet_render import INSTALL_LINES
from .tar_bundle import build_tar_gz

__all__ = [
    "DISTRIBUTION_SCHEMA_VERSION",
    "ECOSYSTEM_LANGUAGES",
    "Distribution",
    "DistributionError",
    "DistributionFile",
    "build_distribution",
    "distribution_filename",
    "npm_tarball_filename",
    "python_module_stem",
    "pypi_module_name",
    "pypi_normalized_name",
    "pypi_sdist_filename",
]

#: The addressable shape of the ``apiome`` provenance object both distributions carry.
DISTRIBUTION_SCHEMA_VERSION = "sdk.distribution.v1"

#: Which snippet language each ecosystem ships. A Python package carrying TypeScript examples is
#: noise; the contract itself is in both, and that is what a consumer codegens from.
ECOSYSTEM_LANGUAGES: Dict[str, str] = {NPM_ECOSYSTEM: "ts", PYPI_ECOSYSTEM: "python"}

#: File extension per shipped language.
_LANGUAGE_EXTENSIONS: Dict[str, str] = {"ts": "ts", "python": "py"}

#: Everything outside this set is collapsed to ``_`` when deriving a Python module name.
_PY_UNSAFE = re.compile(r"[^0-9a-z_]+")

#: PEP 503 name normalisation: runs of ``-``, ``_`` and ``.`` are one ``-``, case-folded.
_PYPI_SEPARATORS = re.compile(r"[-_.]+")

#: What may appear in a tarball filename stem.
_FILENAME_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

#: Python keywords that a project slug could otherwise turn into an unimportable module name. The
#: list is short on purpose — only the ones a real API name plausibly collides with.
_PY_RESERVED = frozenset(
    {"import", "class", "from", "none", "true", "false", "global", "lambda", "return", "async"}
)

#: Cap on the description copied into package metadata. npm renders the first line of a long
#: description in search results and PyPI's ``Summary`` is a single line by specification.
_SUMMARY_MAX_CHARS = 200


class DistributionError(ValueError):
    """Raised when a distribution cannot be built.

    Carries a message written for the person publishing: what was missing and what to configure.
    """


@dataclass(frozen=True)
class DistributionFile:
    """One file inside a distribution.

    Attributes:
        path: Archive-relative path, including the format's root directory.
        text: UTF-8 content.
        subject: What the file is (``metadata``, ``readme``, ``contract``, ``module``, or an
            operation id), so a dry-run report can say what it would publish without the bytes.
    """

    path: str
    text: str
    subject: str

    @property
    def size_bytes(self) -> int:
        """The file's UTF-8 length."""
        return len(self.text.encode("utf-8"))

    @property
    def sha256(self) -> str:
        """Hex digest of the file's UTF-8 bytes."""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Distribution:
    """A built, registry-ready artifact.

    Attributes:
        ecosystem: ``npm`` or ``pypi``.
        package_name: The name the registry will index it under (SDK-3.4 resolved).
        package_version: The version, from :mod:`app.sdk_publish_version`.
        filename: The archive filename the registry expects.
        content: The archive bytes.
        media_type: What to upload it as.
        files: Everything inside, for the dry-run report.
        metadata: The ecosystem's own metadata document — the parsed ``package.json`` for npm, the
            core-metadata field map for PyPI. The upload transport sends this, so a caller never
            re-derives it from the archive.
        provenance: The ``apiome`` provenance object embedded in that metadata.
        operation_count: How many operations shipped snippets.
        skipped: Operations no snippet is defined for, with the reason.
        truncated: Whether the API declares more renderable operations than one package carries
            (:data:`app.sdk_kit.MAX_KIT_OPERATIONS`). Reported rather than hidden: a package that
            silently omitted operations would be worse than one that says it did.
    """

    ecosystem: str
    package_name: str
    package_version: str
    filename: str
    content: bytes
    media_type: str
    files: List[DistributionFile]
    metadata: Dict[str, Any]
    provenance: Dict[str, Any]
    operation_count: int
    skipped: List[Dict[str, str]] = field(default_factory=list)
    truncated: bool = False

    @property
    def content_length(self) -> int:
        """The archive's size in bytes."""
        return len(self.content)

    @property
    def sha256(self) -> str:
        """Hex SHA-256 over the archive bytes — what the run ledger records."""
        return hashlib.sha256(self.content).hexdigest()


# -------------------------------------------------------------------------------------------
# Names
# -------------------------------------------------------------------------------------------


def pypi_normalized_name(name: str) -> str:
    """Normalise a PyPI project name per PEP 503.

    Args:
        name: The configured package name.

    Returns:
        Lower-cased with every run of ``-``, ``_`` or ``.`` collapsed to a single ``-`` — the form
        PyPI compares names by, so ``Acme.Widgets`` and ``acme-widgets`` are one project.
    """
    return _PYPI_SEPARATORS.sub("-", (name or "").strip()).lower()


def python_module_stem(slug: str) -> str:
    """Make an operation slug importable as a Python module.

    Snippet files are shipped inside the distribution's package, so their names have to be legal
    module names: lower-case, no hyphens, not starting with a digit.

    Args:
        slug: The operation slug (``getWidget``, ``list-widgets``, ``2fa-verify``).

    Returns:
        A legal module stem (``getwidget``, ``list_widgets``, ``op_2fa_verify``).
    """
    candidate = _PY_UNSAFE.sub("_", (slug or "").strip().lower()).strip("_")
    if not candidate:
        return "operation"
    if candidate[0].isdigit() or candidate in _PY_RESERVED:
        return f"op_{candidate}"
    return candidate


def pypi_module_name(name: str) -> str:
    """Derive the importable module name a PyPI distribution ships.

    Args:
        name: The configured package name (``acme-widgets``).

    Returns:
        A legal Python identifier (``acme_widgets``). A name that would start with a digit, or that
        collides with a keyword, gains an ``api_`` prefix rather than producing a module nothing
        can import.
    """
    candidate = _PY_UNSAFE.sub("_", pypi_normalized_name(name).replace("-", "_")).strip("_")
    if not candidate:
        return "api_client"
    if candidate[0].isdigit() or candidate in _PY_RESERVED:
        return f"api_{candidate}"
    return candidate


def npm_tarball_filename(name: str, version: str) -> str:
    """The tarball filename npm itself produces for a package.

    Args:
        name: The package name, possibly scoped (``@acme/widgets``).
        version: The version being published.

    Returns:
        ``acme-widgets-1.4.0.tgz`` — the scope's ``@`` dropped and its ``/`` flattened to ``-``,
        which is exactly what ``npm pack`` writes.
    """
    stem = (name or "").lstrip("@").replace("/", "-")
    return f"{_FILENAME_UNSAFE.sub('-', stem)}-{_FILENAME_UNSAFE.sub('-', version)}.tgz"


def pypi_sdist_filename(name: str, version: str) -> str:
    """The sdist filename PyPI expects (PEP 625).

    Args:
        name: The package name.
        version: The version being published.

    Returns:
        ``acme_widgets-1.4.0.tar.gz`` — the PEP 503 normalised name with ``-`` replaced by ``_``.
    """
    stem = pypi_normalized_name(name).replace("-", "_")
    return f"{_FILENAME_UNSAFE.sub('_', stem)}-{_FILENAME_UNSAFE.sub('-', version)}.tar.gz"


def distribution_filename(ecosystem: str, name: str, version: str) -> str:
    """The archive filename for one ecosystem.

    Args:
        ecosystem: ``npm`` or ``pypi``.
        name: The package name.
        version: The version being published.

    Returns:
        The filename.

    Raises:
        DistributionError: If the ecosystem is not publishable.
    """
    if ecosystem == NPM_ECOSYSTEM:
        return npm_tarball_filename(name, version)
    if ecosystem == PYPI_ECOSYSTEM:
        return pypi_sdist_filename(name, version)
    raise DistributionError(
        f"{ecosystem!r} is not a publishable ecosystem ({', '.join(PUBLISH_ECOSYSTEMS)})"
    )


# -------------------------------------------------------------------------------------------
# Shared content
# -------------------------------------------------------------------------------------------


def _summary(api: CanonicalApi, coordinates: KitCoordinates) -> str:
    """A one-line package summary, from the API's own title.

    Args:
        api: The canonical model.
        coordinates: The revision's coordinates, for the fallback name.

    Returns:
        A single line, never longer than :data:`_SUMMARY_MAX_CHARS`.
    """
    title = (api.title or coordinates.project_slug or "API").strip()
    text = f"{title} — API contract, usage snippets and provenance, generated by Apiome."
    collapsed = " ".join(text.split())
    if len(collapsed) <= _SUMMARY_MAX_CHARS:
        return collapsed
    return collapsed[: _SUMMARY_MAX_CHARS - 1].rstrip() + "…"


def _provenance(
    *,
    coordinates: KitCoordinates,
    package_name: str,
    package_version: str,
    ecosystem: str,
    release_series: str,
    regen_counter: int,
    source_format: Optional[str],
    settings_fingerprint: Optional[str],
    apiome_version: Optional[str],
    spec_path: Optional[str],
    truncated: bool,
) -> Dict[str, Any]:
    """Build the provenance object embedded in the package's own metadata.

    This is the acceptance criterion "published package metadata contains provenance", so it names
    the things an incident actually needs: which *revision* (not merely which label — a label can
    be re-published), which version line and release series produced this number, and which
    generator wrote the contents.

    Args:
        coordinates: The revision the package was built from.
        package_name: The published name.
        package_version: The published version.
        ecosystem: ``npm`` or ``pypi``.
        release_series: The series the regen counter was allocated under.
        regen_counter: Which release of that series this is.
        source_format: The captured contract's format key.
        settings_fingerprint: The SDK-3.4 settings digest in force.
        apiome_version: The API version that built it.
        spec_path: Where the contract sits inside the package.
        truncated: Whether the package carries fewer snippets than the API has operations.

    Returns:
        The provenance mapping. JSON-serialisable and ordered for readability.
    """
    return {
        "schemaVersion": DISTRIBUTION_SCHEMA_VERSION,
        "tenant": coordinates.tenant_slug,
        "project": coordinates.project_slug,
        "versionSlug": coordinates.version_slug,
        "versionLine": coordinates.version_label,
        "versionRecordId": coordinates.version_record_id,
        "ecosystem": ecosystem,
        "packageName": package_name,
        "packageVersion": package_version,
        "releaseSeries": release_series,
        "regenCounter": regen_counter,
        "sourceFormat": source_format,
        "specPath": spec_path,
        "renderer": f"app.snippet_render/{KIT_SCHEMA_VERSION}",
        "settingsFingerprint": settings_fingerprint,
        "apiomeVersion": apiome_version,
        "truncated": truncated,
    }


def _operation_index(rendered: List[RenderedOperation], lang: str) -> List[Dict[str, str]]:
    """The operation table both packages expose to their consumers.

    Args:
        rendered: The rendered operations.
        lang: The language whose snippet paths to name.

    Returns:
        One entry per operation, in declaration order.
    """
    extension = _LANGUAGE_EXTENSIONS[lang]
    return [
        {
            "operationId": entry.identifier,
            "method": entry.method,
            "path": entry.path,
            "snippet": (
                f"snippets/{python_module_stem(entry.slug)}.py"
                if lang == "python"
                else f"snippets/{entry.slug}.{extension}"
            ),
        }
        for entry in rendered
    ]


def _readme(
    *,
    api: CanonicalApi,
    coordinates: KitCoordinates,
    package_name: str,
    package_version: str,
    ecosystem: str,
    rendered: List[RenderedOperation],
    skipped: List[Dict[str, str]],
    spec_path: str,
    provenance: Dict[str, Any],
    license_header: Optional[str],
    truncated: bool,
) -> str:
    """Render the package README.

    Args:
        api: The canonical model.
        coordinates: The revision coordinates.
        package_name: The published name.
        package_version: The published version.
        ecosystem: ``npm`` or ``pypi``.
        rendered: The operations shipping snippets.
        skipped: Operations with no snippet, with reasons.
        spec_path: Where the contract sits inside the package.
        provenance: The provenance object, rendered as a table.
        license_header: The tenant's SDK-3.4 licence text, when configured.
        truncated: Whether snippets were capped.

    Returns:
        The README markdown.
    """
    lang = ECOSYSTEM_LANGUAGES[ecosystem]
    fence = "ts" if lang == "ts" else "python"
    install = (
        f"npm install {package_name}"
        if ecosystem == NPM_ECOSYSTEM
        else f"pip install {package_name}"
    )
    title = (api.title or coordinates.project_slug or "API").strip()

    lines: List[str] = [f"# {package_name}", ""]
    lines.append(
        f"`{package_name}@{package_version}` — the **{title}** contract, its runnable "
        f"{'TypeScript' if lang == 'ts' else 'Python'} usage snippets, and the provenance of the "
        "exact revision they were generated from."
    )
    lines.extend(["", "## Install", "", "```bash", install, "```", ""])

    dependency = INSTALL_LINES.get(lang)
    if dependency:
        lines.extend(
            [
                "The snippets call the API over "
                f"`{dependency.split()[-1]}`; install it alongside:",
                "",
                "```bash",
                dependency,
                "```",
                "",
            ]
        )

    lines.extend(
        [
            "## What is in the package",
            "",
            "| Path | What it is |",
            "| --- | --- |",
            f"| `{spec_path}` | The API contract, verbatim as published. |",
            f"| `snippets/` | One runnable snippet per operation ({len(rendered)}). |",
            "| Package metadata | The provenance table below, machine-readable. |",
            "",
        ]
    )

    if rendered:
        first = rendered[0]
        snippet = first.snippets.get(lang)
        if snippet is not None:
            lines.extend(
                [
                    f"## Example — `{first.identifier}`",
                    "",
                    f"```{fence}",
                    snippet[1].rstrip("\n"),
                    "```",
                    "",
                ]
            )
        lines.extend(["## Operations", "", "| Operation | Method | Path |", "| --- | --- | --- |"])
        for entry in rendered:
            path = entry.path.replace("|", "\\|")
            lines.append(f"| `{entry.identifier}` | `{entry.method}` | `{path}` |")
        lines.append("")

    if truncated:
        lines.extend(
            [
                "> **This API is larger than one package's snippet budget.** The packaged "
                f"contract describes every operation; only the first {len(rendered)} carry a "
                "generated snippet.",
                "",
            ]
        )

    if skipped:
        lines.extend(
            [
                "## Not covered",
                "",
                "These operations have no HTTP binding, so no request snippet is defined for "
                "them. The contract still describes them in full.",
                "",
            ]
        )
        for item in skipped:
            lines.append(f"- `{item.get('operation_id', '?')}` — {item.get('reason', '')}")
        lines.append("")

    lines.extend(["## Provenance", "", "| Field | Value |", "| --- | --- |"])
    for key, value in provenance.items():
        if value is None:
            continue
        lines.append(f"| `{key}` | `{value}` |")
    lines.extend(
        [
            "",
            "This package was generated from a single published revision. `versionRecordId` "
            "identifies that revision exactly — a version *line* can be re-published, a revision "
            "cannot — so an installed package always traces back to the contract it came from.",
            "",
        ]
    )

    if license_header:
        lines.extend(["## Licence", "", license_header.strip(), ""])

    return "\n".join(lines).rstrip("\n") + "\n"


def _python_literal(value: Any) -> str:
    """Render a JSON-shaped value as a **Python** literal.

    ``json.dumps`` is not usable for generated Python: JSON spells the empty value ``null``, which
    Python parses as a *name* — so a module embedding it compiles cleanly and then raises
    ``NameError`` the first time anyone imports it. :func:`pprint.pformat` renders the same data as
    ``None`` / ``True`` / ``False`` and is deterministic, which the archive's byte-determinism
    needs.

    Args:
        value: A JSON-shaped value (dicts, lists, strings, numbers, booleans, ``None``).

    Returns:
        Source text that evaluates to ``value``.
    """
    return pformat(value, indent=4, width=96, sort_dicts=False)


def _comment(text: str, prefix: str) -> str:
    """Comment a licence header for one language.

    Args:
        text: The header text.
        prefix: The line-comment prefix (``// `` or ``# ``).

    Returns:
        The commented block with a trailing blank line, or ``""`` for empty text.
    """
    stripped = (text or "").strip()
    if not stripped:
        return ""
    body = "\n".join(f"{prefix}{line}".rstrip() for line in stripped.splitlines())
    return f"{body}\n\n"


# -------------------------------------------------------------------------------------------
# npm
# -------------------------------------------------------------------------------------------


def _npm_package_json(
    *,
    package_name: str,
    package_version: str,
    summary: str,
    api: CanonicalApi,
    provenance: Dict[str, Any],
    spec_path: str,
    operations: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Build the ``package.json`` document.

    Args:
        package_name: The published name.
        package_version: The published version.
        summary: One-line description.
        api: The canonical model, for keywords.
        provenance: The ``apiome`` object embedded verbatim.
        spec_path: Where the contract sits inside the package.
        operations: The operation index the module re-exports.

    Returns:
        The document, key-ordered so the serialised file is stable.
    """
    keywords = ["apiome", "openapi", "api", "sdk"]
    if api.format:
        keywords.append(str(api.format))
    return {
        "name": package_name,
        "version": package_version,
        "description": summary,
        "license": "SEE LICENSE IN README.md",
        "main": "index.js",
        "types": "index.d.ts",
        "type": "commonjs",
        "sideEffects": False,
        "keywords": sorted(set(keywords)),
        "files": ["index.js", "index.d.ts", "README.md", spec_path, "snippets/"],
        "engines": {"node": ">=18"},
        "apiome": {**provenance, "operations": operations},
    }


def _npm_index_js(spec_path: str, provenance: Dict[str, Any], operations: List[Dict[str, str]]) -> str:
    """The package's CommonJS entry point.

    It resolves the shipped contract from disk rather than inlining it, so requiring the package
    costs nothing and a consumer who wants the spec asks for it by name.

    Args:
        spec_path: Where the contract sits inside the package.
        provenance: The provenance object.
        operations: The operation index.

    Returns:
        The module source.
    """
    return (
        "'use strict';\n"
        "// Generated by Apiome (SDK-4.1). Do not edit by hand — regenerate and republish.\n"
        "\n"
        "const path = require('path');\n"
        "const fs = require('fs');\n"
        "\n"
        f"const provenance = {json.dumps(provenance, indent=2, ensure_ascii=False)};\n"
        "\n"
        f"const operations = {json.dumps(operations, indent=2, ensure_ascii=False)};\n"
        "\n"
        f"const specPath = path.join(__dirname, {json.dumps(spec_path)});\n"
        "\n"
        "/** Read the published API contract this package was generated from. */\n"
        "function readSpec() {\n"
        "  return fs.readFileSync(specPath, 'utf8');\n"
        "}\n"
        "\n"
        "module.exports = { provenance, operations, specPath, readSpec };\n"
    )


def _npm_index_dts(spec_path: str) -> str:
    """The package's TypeScript declarations.

    Args:
        spec_path: Named only in the doc comment; the declaration itself is a plain string.

    Returns:
        The ``.d.ts`` source.
    """
    return (
        "// Generated by Apiome (SDK-4.1). Do not edit by hand — regenerate and republish.\n"
        "\n"
        "/** Where this package came from: the exact published revision and how it was built. */\n"
        "export interface ApiomeProvenance {\n"
        "  schemaVersion: string;\n"
        "  tenant: string;\n"
        "  project: string;\n"
        "  versionSlug: string;\n"
        "  versionLine: string | null;\n"
        "  versionRecordId: string;\n"
        "  ecosystem: string;\n"
        "  packageName: string;\n"
        "  packageVersion: string;\n"
        "  releaseSeries: string;\n"
        "  regenCounter: number;\n"
        "  sourceFormat: string | null;\n"
        "  specPath: string | null;\n"
        "  renderer: string;\n"
        "  settingsFingerprint: string | null;\n"
        "  apiomeVersion: string | null;\n"
        "}\n"
        "\n"
        "/** One operation of the published contract, and the snippet that calls it. */\n"
        "export interface ApiomeOperation {\n"
        "  operationId: string;\n"
        "  method: string;\n"
        "  path: string;\n"
        "  snippet: string;\n"
        "}\n"
        "\n"
        "export declare const provenance: ApiomeProvenance;\n"
        "export declare const operations: ApiomeOperation[];\n"
        f"/** Absolute path to the packaged contract (`{spec_path}`). */\n"
        "export declare const specPath: string;\n"
        "/** Read the published API contract this package was generated from. */\n"
        "export declare function readSpec(): string;\n"
    )


# -------------------------------------------------------------------------------------------
# PyPI
# -------------------------------------------------------------------------------------------


def _pypi_pyproject(
    *, package_name: str, package_version: str, summary: str, module: str, api: CanonicalApi
) -> str:
    """Build ``pyproject.toml`` for the sdist.

    A setuptools backend with an explicit package list and package data — an sdist that builds a
    wheel dropping its own contract would be worse than useless.

    Args:
        package_name: The published name.
        package_version: The published version.
        summary: One-line description.
        module: The importable module name.
        api: The canonical model, for keywords.

    Returns:
        The TOML source.
    """
    keywords = sorted({"apiome", "openapi", "api", "sdk", str(api.format or "api")})
    keyword_list = ", ".join(json.dumps(word) for word in keywords)
    return (
        "# Generated by Apiome (SDK-4.1). Do not edit by hand — regenerate and republish.\n"
        "[build-system]\n"
        'requires = ["setuptools>=68"]\n'
        'build-backend = "setuptools.build_meta"\n'
        "\n"
        "[project]\n"
        f"name = {json.dumps(package_name)}\n"
        f"version = {json.dumps(package_version)}\n"
        f"description = {json.dumps(summary)}\n"
        f'readme = "README.md"\n'
        'requires-python = ">=3.9"\n'
        f"keywords = [{keyword_list}]\n"
        "\n"
        "[tool.setuptools]\n"
        f'packages = [{json.dumps(module)}, {json.dumps(module + ".snippets")}]\n'
        "\n"
        "[tool.setuptools.package-data]\n"
        f'{json.dumps(module)} = ["spec/*"]\n'
    )


def _pypi_core_metadata(
    *, package_name: str, package_version: str, summary: str, provenance: Dict[str, Any]
) -> Dict[str, Any]:
    """Build the PyPI core-metadata field map (Metadata-Version 2.1).

    Provenance rides as ``Project-URL`` entries — the only core-metadata field that is a free
    key/value list, and the one a consumer sees rendered on the project page and in
    ``importlib.metadata``.

    Args:
        package_name: The published name.
        package_version: The published version.
        summary: One-line description.
        provenance: The provenance object.

    Returns:
        A field map. ``project_urls`` and ``keywords`` are lists; everything else is a string.
    """
    urls = [
        f"Apiome {key}, {value}"
        for key, value in provenance.items()
        if value is not None and key not in {"schemaVersion", "packageName", "packageVersion"}
    ]
    return {
        "metadata_version": "2.1",
        "name": package_name,
        "version": package_version,
        "summary": summary,
        "description_content_type": "text/markdown",
        "keywords": "apiome,openapi,api,sdk",
        "requires_python": ">=3.9",
        "project_urls": urls,
    }


def _pypi_pkg_info(metadata: Dict[str, Any], description: str) -> str:
    """Render ``PKG-INFO`` from the core-metadata field map.

    Args:
        metadata: The field map from :func:`_pypi_core_metadata`.
        description: The long description (the README), written as the message body.

    Returns:
        The ``PKG-INFO`` text.
    """
    lines = [
        f"Metadata-Version: {metadata['metadata_version']}",
        f"Name: {metadata['name']}",
        f"Version: {metadata['version']}",
        f"Summary: {metadata['summary']}",
        f"Keywords: {metadata['keywords']}",
        f"Requires-Python: {metadata['requires_python']}",
        f"Description-Content-Type: {metadata['description_content_type']}",
    ]
    lines.extend(f"Project-URL: {url}" for url in metadata["project_urls"])
    # Core metadata puts the long description in the message body, after one blank line.
    return "\n".join(lines) + "\n\n" + description


def _pypi_init_py(
    *,
    module: str,
    package_version: str,
    provenance: Dict[str, Any],
    operations: List[Dict[str, str]],
    spec_name: str,
    license_header: Optional[str],
) -> str:
    """The package's ``__init__.py``.

    Args:
        module: The module name (used in the docstring).
        package_version: Exposed as ``__version__``.
        provenance: Exposed as ``PROVENANCE``.
        operations: Exposed as ``OPERATIONS``.
        spec_name: The contract's filename inside the module's ``spec/`` directory.
        license_header: The tenant's SDK-3.4 licence text.

    Returns:
        The module source.
    """
    header = _comment(license_header or "", "# ")
    return (
        f'"""{module} — the published API contract, its usage snippets, and their provenance.\n'
        "\n"
        "Generated by Apiome (SDK-4.1). Do not edit by hand — regenerate and republish.\n"
        '"""\n'
        "\n"
        f"{header}"
        "from pathlib import Path\n"
        "\n"
        f"__version__ = {json.dumps(package_version)}\n"
        "\n"
        "#: Where this package came from: the exact published revision and how it was built.\n"
        f"PROVENANCE = {_python_literal(provenance)}\n"
        "\n"
        "#: One entry per operation of the published contract.\n"
        f"OPERATIONS = {_python_literal(operations)}\n"
        "\n"
        "#: Absolute path to the packaged contract.\n"
        f"SPEC_PATH = Path(__file__).resolve().parent / \"spec\" / {spec_name!r}\n"
        "\n"
        "\n"
        "def read_spec() -> str:\n"
        '    """Return the published API contract this package was generated from."""\n'
        '    return SPEC_PATH.read_text(encoding="utf-8")\n'
    )


# -------------------------------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------------------------------


def build_distribution(
    api: CanonicalApi,
    *,
    ecosystem: str,
    coordinates: KitCoordinates,
    branding: ResolvedBranding,
    package_name: str,
    package_version: str,
    release_series: str,
    regen_counter: int,
    source_text: Optional[str] = None,
    source_format: Optional[str] = None,
    settings_fingerprint: Optional[str] = None,
    apiome_version: Optional[str] = None,
) -> Distribution:
    """Build the registry-ready distribution for one revision and one ecosystem.

    Args:
        api: The revision's canonical model.
        ecosystem: ``npm`` or ``pypi``.
        coordinates: The revision the package is built from.
        branding: The tenant's resolved SDK-3.4 settings; its licence header is stamped on the
            generated source and its user-agent onto every snippet.
        package_name: The resolved package name (SDK-3.4). Passed in rather than re-resolved so
            the caller's dry-run and its publish cannot disagree.
        package_version: The version, from :mod:`app.sdk_publish_version`.
        release_series: The series the counter was allocated under, recorded as provenance.
        regen_counter: Which release of that series this is.
        source_text: The captured contract. Required — a package whose whole purpose is to carry
            the contract cannot be built without it.
        source_format: The contract's format key, used to name its file.
        settings_fingerprint: The merged SDK-3.4 settings digest, recorded as provenance.
        apiome_version: The API version that built it.

    Returns:
        The :class:`Distribution`. Building twice from equal arguments yields identical bytes.

    Raises:
        DistributionError: If the ecosystem is not publishable or no contract was captured.
    """
    if ecosystem not in PUBLISH_ECOSYSTEMS:
        raise DistributionError(
            f"{ecosystem!r} is not a publishable ecosystem ({', '.join(PUBLISH_ECOSYSTEMS)})"
        )
    if not (source_text or "").strip():
        raise DistributionError(
            "This revision has no captured contract, so there is nothing to package. Re-import "
            "the version and publish again."
        )

    lang = ECOSYSTEM_LANGUAGES[ecosystem]
    rendered, skipped, counts = render_kit_operations(api, branding)
    spec_name = spec_filename(source_format, source_text)
    summary = _summary(api, coordinates)
    operations = _operation_index(rendered, lang)

    if ecosystem == NPM_ECOSYSTEM:
        root = "package"
        spec_path = f"spec/{spec_name}"
    else:
        module = pypi_module_name(package_name)
        root = f"{pypi_normalized_name(package_name).replace('-', '_')}-{package_version}"
        spec_path = f"{module}/spec/{spec_name}"

    provenance = _provenance(
        coordinates=coordinates,
        package_name=package_name,
        package_version=package_version,
        ecosystem=ecosystem,
        release_series=release_series,
        regen_counter=regen_counter,
        source_format=source_format,
        settings_fingerprint=settings_fingerprint,
        apiome_version=apiome_version,
        spec_path=spec_path,
        truncated=counts.truncated,
    )
    readme = _readme(
        api=api,
        coordinates=coordinates,
        package_name=package_name,
        package_version=package_version,
        ecosystem=ecosystem,
        rendered=rendered,
        skipped=skipped,
        spec_path=spec_path,
        provenance=provenance,
        license_header=branding.license_header,
        truncated=counts.truncated,
    )

    files: List[DistributionFile] = []
    if ecosystem == NPM_ECOSYSTEM:
        metadata = _npm_package_json(
            package_name=package_name,
            package_version=package_version,
            summary=summary,
            api=api,
            provenance=provenance,
            spec_path=spec_path,
            operations=operations,
        )
        files.extend(
            [
                DistributionFile(
                    "package.json",
                    json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
                    "metadata",
                ),
                DistributionFile("README.md", readme, "readme"),
                DistributionFile(
                    "index.js", _npm_index_js(spec_path, provenance, operations), "module"
                ),
                DistributionFile("index.d.ts", _npm_index_dts(spec_path), "module"),
                DistributionFile(spec_path, source_text or "", "contract"),
            ]
        )
        for entry in rendered:
            snippet = entry.snippets.get(lang)
            if snippet is None:
                continue
            code = snippet[1]
            files.append(
                DistributionFile(
                    f"snippets/{entry.slug}.ts",
                    code if code.endswith("\n") else f"{code}\n",
                    entry.identifier,
                )
            )
    else:
        module = pypi_module_name(package_name)
        metadata = _pypi_core_metadata(
            package_name=package_name,
            package_version=package_version,
            summary=summary,
            provenance=provenance,
        )
        files.extend(
            [
                DistributionFile("PKG-INFO", _pypi_pkg_info(metadata, readme), "metadata"),
                DistributionFile(
                    "pyproject.toml",
                    _pypi_pyproject(
                        package_name=package_name,
                        package_version=package_version,
                        summary=summary,
                        module=module,
                        api=api,
                    ),
                    "metadata",
                ),
                DistributionFile("README.md", readme, "readme"),
                DistributionFile(
                    f"{module}/__init__.py",
                    _pypi_init_py(
                        module=module,
                        package_version=package_version,
                        provenance=provenance,
                        operations=operations,
                        spec_name=spec_name,
                        license_header=branding.license_header,
                    ),
                    "module",
                ),
                DistributionFile(
                    f"{module}/snippets/__init__.py",
                    '"""Runnable request snippets, one module per operation."""\n',
                    "module",
                ),
                DistributionFile(spec_path, source_text or "", "contract"),
            ]
        )
        for entry in rendered:
            snippet = entry.snippets.get(lang)
            if snippet is None:
                continue
            code = snippet[1]
            files.append(
                DistributionFile(
                    f"{module}/snippets/{python_module_stem(entry.slug)}.py",
                    code if code.endswith("\n") else f"{code}\n",
                    entry.identifier,
                )
            )

    files.sort(key=lambda item: item.path)
    content = build_tar_gz((f"{root}/{item.path}", item.text) for item in files)

    return Distribution(
        ecosystem=ecosystem,
        package_name=package_name,
        package_version=package_version,
        filename=distribution_filename(ecosystem, package_name, package_version),
        content=content,
        media_type="application/gzip",
        files=files,
        metadata=metadata,
        provenance=provenance,
        operation_count=len(rendered),
        skipped=skipped,
        truncated=counts.truncated,
    )
