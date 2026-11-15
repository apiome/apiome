"""The generator compatibility manifest, ``apiome.sdk.compat-manifest/v1`` — SGD-2.1 (#4735).

Before a team adopts a generated artifact — the snippets, the Go client, a server stub, the Terraform
provider, the MCP server — it needs to know whether that artifact faithfully represents its API
version. This module answers in one machine-readable document, built from the **same SDK kit** a
consumer downloads (:func:`app.sdk_kit.build_client_kit`), so the manifest can never describe a
different artifact than the one shipped:

* **constructs** — what the version contains: operations (and how many have an HTTP binding),
  types by kind, security schemes, servers, streaming operations and pagination-style parameters;
* **artifacts** — one entry per generated artifact with its generator and digests, its operation
  coverage, its runtime and dependencies (read from the generated ``go.mod`` / ``pyproject.toml`` /
  ``package.json``), the auth schemes it supports and the ones it does not, how it treats
  pagination, and its **findings**;
* **findings** — every construct an artifact leaves out or cannot represent, each with a stable
  ``code``, the generator's ``reason`` and an ``action`` saying what to change. Nothing is dropped
  silently: an operation a generator skipped, an auth scheme it has no option for, a generator that
  failed, and an operation cap are all findings;
* **digests** — the source (the captured contract), the options (the SDK settings fingerprint),
  each generator (name, schema version and Apiome version) and each artifact (its files' sha256);
* **semver** — the published revision's classified changelog (CTG-3.1) against its baseline, the
  bump that classification requires, the bump the version labels declare, and whether they agree.

The manifest is a pure function of its inputs — no clock, no I/O — so the same revision, settings
and Apiome version always produce the same document (the route serves its digest as an ``ETag``).
The schema is versioned by ``schema_version``; ``schemas/sdk-compat-manifest.v1.json`` is generated
from :class:`SdkCompatManifest` and a test fails when the two drift.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import tomllib
import zipfile
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .canonical_model import CanonicalApi, Operation, ParameterLocation, StreamingMode
from .canonical_security import declared_security_schemes
from .snippet_render import INSTALL_LINES, SUPPORTED_LANGS

__all__ = [
    "ACTIONS",
    "FINDING_CODES",
    "PAGINATION_PARAMETER_NAMES",
    "SCHEMA_VERSION",
    "ChangelogInfo",
    "SdkCompatManifest",
    "build_compat_manifest",
    "classify_bump",
    "manifest_etag",
]

#: The manifest's schema name and version.
SCHEMA_VERSION = "apiome.sdk.compat-manifest/v1"

# ---------------------------------------------------------------------------------------------
# Findings vocabulary
# ---------------------------------------------------------------------------------------------

#: An operation has no HTTP method and path (a GraphQL field, a gRPC method, an event).
CODE_NO_HTTP_BINDING = "operation-no-http-binding"
#: An operation is beyond the generator's operation cap.
CODE_OVER_LIMIT = "operation-over-limit"
#: An operation was left out for another reason (the generator's ``reason`` says which).
CODE_OPERATION_SKIPPED = "operation-skipped"
#: The kit carries only the first operations of a large API.
CODE_TRUNCATED = "operations-truncated"
#: A declared security scheme the artifact has no option or setting for.
CODE_AUTH_UNSUPPORTED = "auth-scheme-unsupported"
#: The generator failed; the artifact is not in the kit.
CODE_NOT_GENERATED = "artifact-not-generated"
#: A Terraform readiness finding (``terraform.*`` from the provider planner) other than a binding.
CODE_TERRAFORM = "terraform-readiness"

#: What to do about each finding — the same sentence everywhere the manifest is rendered.
ACTIONS: Dict[str, str] = {
    CODE_NO_HTTP_BINDING: (
        "Give the operation an HTTP method and path in the source (an OpenAPI path item), or call it "
        "through its own protocol — this artifact only generates HTTP calls."
    ),
    CODE_OVER_LIMIT: (
        "Split the API into smaller projects, or generate this artifact for the operations you need — "
        "the kit carries a bounded number of operations."
    ),
    CODE_OPERATION_SKIPPED: "Read the reason and change the operation in the source; it is left out of this artifact.",
    CODE_TRUNCATED: (
        "Only the first operations are generated. Split the API into smaller projects to cover the rest."
    ),
    CODE_AUTH_UNSUPPORTED: (
        "Send this credential yourself — add the header to a snippet, or use the client's generic hook "
        "(Go: WithHeader or WithRequestEditor) — or declare an apiKey or HTTP bearer/basic scheme the "
        "generator supports."
    ),
    CODE_NOT_GENERATED: (
        "Fix the error in the source and regenerate; the rest of the kit is unaffected."
    ),
    CODE_TERRAFORM: "Follow the message: change the operations so they map onto Terraform resources.",
}

#: Every finding code, in the order a renderer groups them.
FINDING_CODES: Tuple[str, ...] = tuple(ACTIONS)

#: Query-parameter names that mark a paginated operation. No generator follows pages for you; the
#: manifest says so wherever one of these appears.
PAGINATION_PARAMETER_NAMES = frozenset(
    {
        "after", "before", "continuation", "continuation_token", "cursor", "ending_before", "limit",
        "marker", "next", "next_page_token", "next_token", "offset", "page", "page_number",
        "page_size", "page_token", "pagenumber", "pagesize", "pagetoken", "per_page", "perpage",
        "start", "starting_after",
    }
)

Severity = Literal["error", "warning", "info"]
Bump = Literal["major", "minor", "patch"]


# ---------------------------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SdkCompatFinding(_Strict):
    """One construct an artifact leaves out or cannot represent."""

    code: str = Field(description="Stable code: " + ", ".join(f"`{c}`" for c in FINDING_CODES) + ".")
    severity: Severity
    artifact: str = Field(description="The artifact id the finding is about.")
    element: Literal["operation", "auth-scheme", "artifact"] = Field(description="What kind of thing is left out.")
    subject: str = Field(description="The operation id, the scheme name, or the artifact id.")
    key: Optional[str] = Field(default=None, description="The operation's canonical key, for an operation.")
    reason: str = Field(description="Why, as the generator reported it.")
    action: str = Field(description="What to change so the construct is represented.")


class SdkCompatGenerator(_Strict):
    name: str
    schema_version: str
    digest: str = Field(description="sha256 of name, schema version and Apiome version.")


class SdkCompatCoverage(_Strict):
    operations: int = Field(ge=0, description="Operations the artifact carries.")
    of: int = Field(ge=0, description="Operations the version declares.")


class SdkCompatRuntime(_Strict):
    language_version: Optional[str] = Field(default=None, description="`go 1.21`, `python >=3.10`, `node >=18`.")
    dependencies: List[str] = Field(default_factory=list, description="Third-party dependencies, `name version`.")


class SdkCompatAuth(_Strict):
    supported: List[str] = Field(default_factory=list)
    unsupported: List[str] = Field(default_factory=list)


class SdkCompatPagination(_Strict):
    mode: Literal["manual", "none"] = Field(
        description="`manual`: page parameters are passed through and you request each page; `none`: no "
        "pagination parameters in the version."
    )
    parameters: List[str] = Field(default_factory=list)


class SdkCompatArtifact(_Strict):
    id: str
    kind: Literal["snippets", "client", "server-stub", "terraform-provider", "mcp-server"]
    language: str
    directory: str
    included: bool
    generator: SdkCompatGenerator
    digest: Optional[str] = Field(default=None, description="sha256 over the artifact's files; null when not generated.")
    coverage: SdkCompatCoverage
    runtime: Optional[SdkCompatRuntime] = None
    auth: Optional[SdkCompatAuth] = Field(default=None, description="Null where auth does not apply (server stubs).")
    pagination: Optional[SdkCompatPagination] = Field(default=None, description="Null where the artifact makes no calls.")
    findings: List[SdkCompatFinding] = Field(default_factory=list)


class SdkCompatConstructs(_Strict):
    operations: int
    http_operations: int
    streaming_operations: int
    types: Dict[str, int] = Field(default_factory=dict, description="Named types by kind.")
    security_schemes: List[str] = Field(default_factory=list)
    servers: int
    pagination_parameters: List[str] = Field(default_factory=list)


class SdkCompatApi(_Strict):
    title: Optional[str] = None
    version: Optional[str] = None
    paradigm: str
    format: str


class SdkCompatSource(_Strict):
    version_record_id: str
    version_label: Optional[str] = None
    source_format: Optional[str] = None
    digest: str = Field(description="sha256 of the captured contract (or of the canonical model when none).")


class SdkCompatOptions(_Strict):
    digest: str = Field(description="The SDK settings fingerprint the artifacts were generated with.")
    package_names: Dict[str, str] = Field(default_factory=dict)
    user_agent_set: bool
    license_header_set: bool


class SdkCompatSemver(_Strict):
    classification: Literal["breaking", "non-breaking", "docs-only", "unknown"] = Field(
        description="The classified changelog against the baseline; `unknown` for a draft or an unclassified revision."
    )
    baseline_version: Optional[str] = None
    required_bump: Optional[Bump] = Field(default=None, description="What the classification requires.")
    declared_bump: Optional[Literal["major", "minor", "patch", "none", "unknown"]] = Field(
        default=None, description="What the version labels declare."
    )
    consistent: Optional[bool] = Field(default=None, description="Whether the declared bump covers the required one.")


class SdkCompatManifest(_Strict):
    """The generator compatibility manifest for one revision."""

    schema_version: Literal["apiome.sdk.compat-manifest/v1"] = SCHEMA_VERSION
    api: SdkCompatApi
    source: SdkCompatSource
    options: SdkCompatOptions
    constructs: SdkCompatConstructs
    artifacts: List[SdkCompatArtifact]
    findings_count: int = Field(ge=0)
    semver: SdkCompatSemver


@dataclass(frozen=True)
class ChangelogInfo:
    """What the route read about the revision's classified changelog.

    Attributes:
        max_severity: The changelog's ``max_severity`` (``breaking``, ``non-breaking``, ``docs-only``),
            or ``None`` when the revision has no changelog.
        baseline_version: The baseline revision's version label.
    """

    max_severity: Optional[str] = None
    baseline_version: Optional[str] = None


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _generator(name: str, schema_version: str, apiome_version: Optional[str]) -> SdkCompatGenerator:
    return SdkCompatGenerator(
        name=name, schema_version=schema_version, digest=_sha256(f"{name}\n{schema_version}\n{apiome_version or ''}")
    )


def _artifact_digest(files: Sequence[Mapping[str, Any]], prefix: str) -> Optional[str]:
    """sha256 over the ``path\\tsha256`` lines of the files under ``prefix`` (``None`` when there are none)."""
    lines = sorted(f"{f['path']}\t{f['sha256']}" for f in files if str(f["path"]).startswith(prefix))
    return _sha256("\n".join(lines)) if lines else None


_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")
_BUMP_RANK = {"none": 0, "patch": 1, "minor": 2, "major": 3}


def classify_bump(version: Optional[str], baseline: Optional[str]) -> Literal["major", "minor", "patch", "none", "unknown"]:
    """The bump two version labels declare.

    Args:
        version: The revision's label (``1.4.0``, ``v2.0.0-beta.1``).
        baseline: The baseline's label.

    Returns:
        ``major``, ``minor``, ``patch``, ``none`` (same numbers), or ``unknown`` when either is not
        ``MAJOR.MINOR.PATCH``-shaped.
    """
    a = _SEMVER.match((version or "").strip())
    b = _SEMVER.match((baseline or "").strip())
    if not a or not b:
        return "unknown"
    new, old = tuple(int(x) for x in a.groups()), tuple(int(x) for x in b.groups())
    if new[0] != old[0]:
        return "major"
    if new[1] != old[1]:
        return "minor"
    if new[2] != old[2]:
        return "patch"
    return "none"


def _semver(version_label: Optional[str], changelog: Optional[ChangelogInfo]) -> SdkCompatSemver:
    severity = (changelog.max_severity if changelog else None) or ""
    if severity not in ("breaking", "non-breaking", "docs-only"):
        return SdkCompatSemver(classification="unknown", baseline_version=changelog.baseline_version if changelog else None)
    required: Bump = {"breaking": "major", "non-breaking": "minor", "docs-only": "patch"}[severity]  # type: ignore[assignment]
    declared = classify_bump(version_label, changelog.baseline_version)
    consistent = None if declared == "unknown" else _BUMP_RANK[declared] >= _BUMP_RANK[required]
    return SdkCompatSemver(
        classification=severity,  # type: ignore[arg-type]
        baseline_version=changelog.baseline_version,
        required_bump=required,
        declared_bump=declared,
        consistent=consistent,
    )


def _operations(api: CanonicalApi) -> List[Operation]:
    return [op for service in api.services for op in service.operations]


def _pagination_parameters(ops: Iterable[Operation]) -> List[str]:
    names = {
        param.name
        for op in ops
        for param in op.parameters
        if param.location == ParameterLocation.QUERY and param.name.lower() in PAGINATION_PARAMETER_NAMES
    }
    return sorted(names)


def _constructs(api: CanonicalApi) -> SdkCompatConstructs:
    ops = _operations(api)
    kinds: Dict[str, int] = {}
    for type_ in api.types:
        kind = str(getattr(type_.kind, "value", type_.kind))
        kinds[kind] = kinds.get(kind, 0) + 1
    return SdkCompatConstructs(
        operations=len(ops),
        http_operations=sum(1 for op in ops if op.http_method and op.http_path),
        streaming_operations=sum(1 for op in ops if op.streaming != StreamingMode.NONE),
        types=dict(sorted(kinds.items())),
        security_schemes=sorted(declared_security_schemes(api)),
        servers=len(api.servers),
        pagination_parameters=_pagination_parameters(ops),
    )


def _read(archive: Optional[zipfile.ZipFile], path: str) -> Optional[str]:
    if archive is None:
        return None
    try:
        return archive.read(path).decode("utf-8")
    except KeyError:
        return None


def _go_runtime(go_mod: Optional[str]) -> Optional[SdkCompatRuntime]:
    """Read the Go version and ``require`` lines of a generated ``go.mod``."""
    if go_mod is None:
        return None
    version = None
    deps: List[str] = []
    in_block = False
    for raw in go_mod.splitlines():
        line = raw.split("//", 1)[0].strip()
        if line.startswith("go "):
            version = line
        elif line.startswith("require ("):
            in_block = True
        elif in_block and line == ")":
            in_block = False
        elif in_block and line:
            deps.append(" ".join(line.split()[:2]))
        elif line.startswith("require "):
            deps.append(" ".join(line.split()[1:3]))
    return SdkCompatRuntime(language_version=version, dependencies=sorted(deps))


def _python_runtime(pyproject: Optional[str]) -> Optional[SdkCompatRuntime]:
    if pyproject is None:
        return None
    try:
        project = tomllib.loads(pyproject).get("project", {})
    except tomllib.TOMLDecodeError:
        return SdkCompatRuntime()
    requires = project.get("requires-python")
    return SdkCompatRuntime(
        language_version=f"python {requires}" if requires else None,
        dependencies=sorted(str(d) for d in project.get("dependencies", [])),
    )


def _node_runtime(package_json: Optional[str]) -> Optional[SdkCompatRuntime]:
    if package_json is None:
        return None
    try:
        data = json.loads(package_json)
    except json.JSONDecodeError:
        return SdkCompatRuntime()
    node = (data.get("engines") or {}).get("node")
    deps = data.get("dependencies") or {}
    return SdkCompatRuntime(
        language_version=f"node {node}" if node else None,
        dependencies=sorted(f"{name} {version}" for name, version in deps.items()),
    )


class _Findings:
    """Builds findings for one artifact, classifying skipped operations against the model."""

    def __init__(self, artifact: str, ops_by_key: Mapping[str, Operation]) -> None:
        self.artifact = artifact
        self.ops_by_key = ops_by_key
        self.items: List[SdkCompatFinding] = []

    def add(self, code: str, element: str, subject: str, reason: str, *, key: Optional[str] = None, severity: Severity = "warning") -> None:
        self.items.append(
            SdkCompatFinding(
                code=code,
                severity=severity,
                artifact=self.artifact,
                element=element,  # type: ignore[arg-type]
                subject=subject,
                key=key,
                reason=reason,
                action=ACTIONS[code],
            )
        )

    def skipped(self, items: Iterable[Mapping[str, Any]], *, id_field: str = "operation_id") -> None:
        for item in items:
            key = item.get("key")
            op = self.ops_by_key.get(key or "")
            reason = str(item.get("reason") or "")
            if op is not None and not (op.http_method and op.http_path):
                code = CODE_NO_HTTP_BINDING
            elif "limit" in reason.lower():
                code = CODE_OVER_LIMIT
            else:
                code = CODE_OPERATION_SKIPPED
            self.add(code, "operation", str(item.get(id_field) or key or ""), reason, key=key)

    def unsupported_auth(self, schemes: Iterable[str]) -> None:
        for scheme in schemes:
            self.add(
                CODE_AUTH_UNSUPPORTED,
                "auth-scheme",
                str(scheme),
                f"The contract declares the '{scheme}' security scheme and this artifact has no option for it.",
            )

    def not_generated(self, error: Optional[str]) -> None:
        self.add(
            CODE_NOT_GENERATED,
            "artifact",
            self.artifact,
            error or "The generator could not produce this artifact.",
            severity="error",
        )


# ---------------------------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------------------------


def build_compat_manifest(
    api: CanonicalApi,
    kit_manifest: Mapping[str, Any],
    kit_content: Optional[bytes],
    *,
    source_text: Optional[str],
    settings_fingerprint: Optional[str],
    package_names: Mapping[str, str],
    user_agent: Optional[str],
    license_header: Optional[str],
    changelog: Optional[ChangelogInfo],
) -> SdkCompatManifest:
    """Build the compatibility manifest for the artifacts of one SDK kit.

    Args:
        api: The revision's canonical model (the one the kit was built from).
        kit_manifest: :attr:`app.sdk_kit.ClientKit.manifest`.
        kit_content: The kit archive, read for each artifact's dependency files; ``None`` skips them.
        source_text: The captured contract, for the source digest.
        settings_fingerprint: The SDK settings fingerprint (the options digest).
        package_names: The resolved package names.
        user_agent: The resolved user agent, if any.
        license_header: The resolved licence header, if any.
        changelog: The revision's classified changelog, if any.

    Returns:
        The manifest.
    """
    provenance = kit_manifest.get("provenance") or {}
    apiome_version = provenance.get("apiome_version")
    files: List[Mapping[str, Any]] = list(kit_manifest.get("files") or [])
    archive = zipfile.ZipFile(io.BytesIO(kit_content)) if kit_content else None
    ops = _operations(api)
    ops_by_key = {op.key: op for op in ops}
    total = len(ops)
    pagination_params = _pagination_parameters(ops)
    pagination = SdkCompatPagination(mode="manual" if pagination_params else "none", parameters=pagination_params)
    schemes = sorted(declared_security_schemes(api))
    artifacts: List[SdkCompatArtifact] = []

    # Snippets — one artifact per language.
    snippet_ops = int(kit_manifest.get("operation_count") or 0)
    for lang in SUPPORTED_LANGS:
        findings = _Findings(f"snippets-{lang}", ops_by_key)
        findings.skipped(kit_manifest.get("skipped") or [])
        # Snippets carry only auth declared as header parameters; a security scheme is never
        # rendered (app.snippet_render's documented limitation), so each one is a finding.
        findings.unsupported_auth(schemes)
        if kit_manifest.get("truncated"):
            findings.add(
                CODE_TRUNCATED,
                "artifact",
                f"snippets-{lang}",
                f"The kit renders {snippet_ops} of {kit_manifest.get('total_operation_count')} operations.",
            )
        install = INSTALL_LINES.get(lang)
        artifacts.append(
            SdkCompatArtifact(
                id=f"snippets-{lang}",
                kind="snippets",
                language=lang,
                directory=f"snippets/{lang}",
                included=snippet_ops > 0,
                generator=_generator("app.snippet_render", str(kit_manifest.get("schema_version")), apiome_version),
                digest=_artifact_digest(files, f"snippets/{lang}/"),
                coverage=SdkCompatCoverage(operations=snippet_ops, of=total),
                runtime=SdkCompatRuntime(dependencies=[install.split()[-1]] if install else []),
                auth=SdkCompatAuth(supported=[], unsupported=schemes),
                pagination=pagination,
                findings=findings.items,
            )
        )

    # Go client.
    go = kit_manifest.get("go_client") or {}
    findings = _Findings("go-client", ops_by_key)
    if go.get("included"):
        findings.skipped(go.get("skipped") or [])
        findings.unsupported_auth(go.get("unsupported_auth") or [])
    else:
        findings.not_generated(go.get("error"))
    artifacts.append(
        SdkCompatArtifact(
            id="go-client",
            kind="client",
            language="go",
            directory=str(go.get("directory") or "go"),
            included=bool(go.get("included")),
            generator=_generator("app.go_client_generator", str(go.get("schema_version")), apiome_version),
            digest=_artifact_digest(files, f"{go.get('directory') or 'go'}/"),
            coverage=SdkCompatCoverage(operations=int(go.get("method_count") or 0), of=total),
            runtime=_go_runtime(_read(archive, f"{go.get('directory') or 'go'}/go.mod")),
            auth=SdkCompatAuth(
                supported=sorted(set(schemes) - set(go.get("unsupported_auth") or [])) if go.get("included") else [],
                unsupported=sorted(go.get("unsupported_auth") or []),
            ),
            pagination=pagination,
            findings=findings.items,
        )
    )

    # Server stubs — one artifact per target.
    stubs = kit_manifest.get("server_stubs") or {}
    targets = {t.get("target"): t for t in stubs.get("targets") or []}
    for target, language, runtime_file, reader in (
        ("fastapi", "python", "pyproject.toml", _python_runtime),
        ("express", "node", "package.json", _node_runtime),
    ):
        entry = targets.get(target) or {}
        directory = str(entry.get("directory") or f"server/{target}")
        findings = _Findings(f"server-{target}", ops_by_key)
        if stubs.get("included"):
            findings.skipped(stubs.get("skipped") or [])
        else:
            findings.not_generated(stubs.get("error"))
        artifacts.append(
            SdkCompatArtifact(
                id=f"server-{target}",
                kind="server-stub",
                language=language,
                directory=directory,
                included=bool(stubs.get("included")),
                generator=_generator(
                    "app.server_stub_generator", str(entry.get("schema_version") or stubs.get("schema_version")), apiome_version
                ),
                digest=_artifact_digest(files, f"{directory}/"),
                coverage=SdkCompatCoverage(operations=int(stubs.get("route_count") or 0), of=total),
                runtime=reader(_read(archive, f"{directory}/{runtime_file}")),
                findings=findings.items,
            )
        )

    # Terraform provider.
    tf = kit_manifest.get("terraform_provider") or {}
    findings = _Findings("terraform-provider", ops_by_key)
    covered: set = set()
    if tf.get("included"):
        for resource in tf.get("resources") or []:
            covered.update(v for v in (resource.get("operations") or {}).values() if v)
        covered.update(d.get("operation_id") for d in tf.get("data_sources") or [] if d.get("operation_id"))
        for warning in tf.get("warnings") or []:
            code = CODE_NO_HTTP_BINDING if warning.get("code") == "terraform.no-http-binding" else CODE_TERRAFORM
            about_operation = bool(warning.get("operation_id") or warning.get("key"))
            findings.add(
                code,
                "operation" if about_operation else "artifact",
                str(warning.get("operation_id") or warning.get("key") or "terraform-provider"),
                str(warning.get("message") or ""),
                key=warning.get("key"),
                severity="info" if warning.get("severity") == "info" else "warning",
            )
    else:
        findings.not_generated(tf.get("error"))
    tf_dir = str(tf.get("directory") or "terraform")
    tf_auth = sorted({str(a.get("scheme")) for a in tf.get("auth") or [] if a.get("scheme")})
    artifacts.append(
        SdkCompatArtifact(
            id="terraform-provider",
            kind="terraform-provider",
            language="go",
            directory=tf_dir,
            included=bool(tf.get("included")),
            generator=_generator("app.terraform_provider_generator", str(tf.get("schema_version")), apiome_version),
            digest=_artifact_digest(files, f"{tf_dir}/"),
            coverage=SdkCompatCoverage(operations=len(covered), of=total),
            runtime=_go_runtime(_read(archive, f"{tf_dir}/go.mod")),
            auth=SdkCompatAuth(supported=tf_auth, unsupported=sorted(set(schemes) - set(tf_auth))) if tf.get("included") else SdkCompatAuth(),
            pagination=pagination,
            findings=findings.items,
        )
    )

    # MCP server.
    mcp = kit_manifest.get("mcp_server") or {}
    findings = _Findings("mcp-server", ops_by_key)
    if mcp.get("included"):
        findings.skipped(mcp.get("skipped") or [], id_field="name")
        findings.unsupported_auth(mcp.get("unsupported_auth") or [])
    else:
        findings.not_generated(mcp.get("error"))
    mcp_dir = str(mcp.get("directory") or "mcp")
    mcp_auth = sorted(
        {str(a.get("scheme") if isinstance(a, Mapping) else a) for a in mcp.get("auth") or []} - {"None"}
    )
    artifacts.append(
        SdkCompatArtifact(
            id="mcp-server",
            kind="mcp-server",
            language="node",
            directory=mcp_dir,
            included=bool(mcp.get("included")),
            generator=_generator("app.mcp_server_generator", str(mcp.get("schema_version")), apiome_version),
            digest=_artifact_digest(files, f"{mcp_dir}/"),
            coverage=SdkCompatCoverage(operations=int(mcp.get("tool_count") or 0), of=total),
            runtime=_node_runtime(_read(archive, f"{mcp_dir}/package.json")),
            auth=SdkCompatAuth(supported=mcp_auth, unsupported=sorted(mcp.get("unsupported_auth") or [])),
            pagination=pagination,
            findings=findings.items,
        )
    )

    source_digest = _sha256(source_text) if source_text else _sha256(api.model_dump_json())
    options_digest = settings_fingerprint or _sha256(
        json.dumps(
            {"package_names": dict(package_names), "user_agent": user_agent, "license_header": license_header},
            sort_keys=True,
        )
    )
    version_label = provenance.get("version_label") or (kit_manifest.get("api") or {}).get("version")
    return SdkCompatManifest(
        api=SdkCompatApi(
            title=api.title,
            version=api.version,
            paradigm=str(getattr(api.paradigm, "value", api.paradigm)),
            format=api.format,
        ),
        source=SdkCompatSource(
            version_record_id=str(provenance.get("version_record_id") or ""),
            version_label=version_label,
            source_format=provenance.get("source_format"),
            digest=source_digest,
        ),
        options=SdkCompatOptions(
            digest=options_digest,
            package_names=dict(sorted(package_names.items())),
            user_agent_set=bool(user_agent),
            license_header_set=bool(license_header),
        ),
        constructs=_constructs(api),
        artifacts=artifacts,
        findings_count=sum(len(a.findings) for a in artifacts),
        semver=_semver(version_label, changelog),
    )


def manifest_etag(manifest: SdkCompatManifest) -> str:
    """A strong ``ETag`` for a manifest: the sha256 of its canonical JSON."""
    canonical = json.dumps(manifest.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return '"' + hashlib.sha256(canonical.encode("utf-8")).hexdigest() + '"'
