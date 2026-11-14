"""The MCP server generator — SDK-4.5 (#4499).

Turns a published contract into a **runnable MCP server**: a TypeScript project an MCP client
(Claude Desktop, an IDE, an agent runtime) launches over stdio, whose tools are the contract's
operations and whose tool calls are real HTTP requests to the API.

**One mapping.** Tools are not derived here. :func:`app.mcp_tool_mapping.compile_mcp_tools`
(AGX-1.1) owns the operation → tool mapping — the name, the description, the ``inputSchema`` built
from the parameters and the request body — and :func:`app.mcp_operation_binding.binding_for` owns
the way back, from a tool's arguments to the request. The managed MCP proxy (AGX-2.1) and the MCP
tool-definition export (MFX-32.1) compile through the same two functions, so a tool is called the
same thing and takes the same arguments wherever an agent meets it. This module adds the
packaging: the generated ``src/contract.ts``, the fixed runtime of :mod:`app.mcp_server_runtime`,
``package.json``, ``tsconfig.json``, ``.env.example`` and a README.

**No secrets in the artifact.** Each security scheme becomes environment variables
(``<PREFIX>_TOKEN``, ``<PREFIX>_API_KEY``, ``<PREFIX>_USERNAME`` / ``<PREFIX>_PASSWORD``), named by
the same mapping the SDK-4.4 Terraform provider uses for its settings
(:func:`app.terraform_provider_plan.plan_auth_settings`). The generated code names the variables and
never a value; ``.env.example`` lists them empty.

**Three properties are load-bearing.**

*It is byte-deterministic.* The toolset is order-normalized and every file is rendered from it in a
fixed order, so the client kit that carries the server keeps its content-addressed ``ETag``.

*Bad arguments never reach the API.* Every call is checked against the tool's input schema by the
generated validator first; a call that fails is answered with the problems and nothing is sent.

*It never refuses over one bad operation.* An operation with no HTTP binding (a gRPC method, a
GraphQL field) has no request to send; it is reported in ``skipped`` and the README, and the rest
of the server is generated.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Tuple

from .canonical_model import CanonicalApi, Operation
from .mcp_operation_binding import OperationBinding, OperationNotInvocableError, binding_for
from .mcp_server_runtime import (
    MCP_SDK_VERSION,
    NODE_ENGINE,
    NODE_TYPES_VERSION,
    RUNTIME_FILES,
    TYPESCRIPT_VERSION,
    ZOD_VERSION,
)
from .mcp_tool_mapping import MCP_TOOL_MAPPING_VERSION, compile_mcp_tools
from .server_stub_plan import StubFile, words
from .snippet_render import license_comment_block, resolve_server_base
from .terraform_provider_plan import plan_auth_settings

__all__ = [
    "DEFAULT_ENV_PREFIX",
    "DEFAULT_MAX_TOOLS",
    "DEFAULT_PACKAGE_NAME",
    "MCP_SERVER_SCHEMA_VERSION",
    "McpServerAuth",
    "McpServerPackage",
    "McpServerSkipped",
    "McpServerTool",
    "generate_mcp_server",
    "mcp_env_prefix",
    "mcp_server_package_name",
]

#: The addressable shape of the generated project, recorded in the kit manifest.
MCP_SERVER_SCHEMA_VERSION = "sdk.mcp-server.v1"

#: npm package name used when nothing usable can be derived from the contract.
DEFAULT_PACKAGE_NAME = "api-mcp-server"

#: Environment-variable prefix used when nothing usable can be derived from the contract.
DEFAULT_ENV_PREFIX = "API"

#: How many tools a server carries at most; the rest are reported in ``skipped``.
DEFAULT_MAX_TOOLS = 250

#: The suffix every package name carries: a tenant's configured ``npm`` name (SDK-3.4) is their
#: *client* library, and the server must not be published at the same address.
_PACKAGE_SUFFIX = "-mcp-server"

#: A version npm accepts (``1.2.3``, ``1.2.3-beta.1``).
_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


# ===========================================================================
# Result shape
# ===========================================================================


@dataclass(frozen=True)
class McpServerTool:
    """One tool the generated server offers.

    Attributes:
        name: The MCP tool name.
        operation_key: The contract operation it calls (``GET /pets/{petId}``).
        method: The HTTP method.
        path: The operation path template.
    """

    name: str
    operation_key: str
    method: str
    path: str


@dataclass(frozen=True)
class McpServerSkipped:
    """A tool the generated server does not offer, and why.

    Attributes:
        name: The tool name the compiler gave it.
        operation_key: The contract operation.
        reason: Why it is left out.
    """

    name: str
    operation_key: str
    reason: str


@dataclass(frozen=True)
class McpServerAuth:
    """One security scheme, as environment variables.

    Attributes:
        scheme: The scheme's name in the contract.
        kind: ``bearer`` / ``basic`` / ``api_key``.
        location: Where the credential travels: ``header`` / ``query`` / ``cookie``.
        parameter: The header, query parameter or cookie name.
        env: The variables it reads — one, or ``(username, password)`` for Basic.
        description: The contract's prose for the scheme.
    """

    scheme: str
    kind: str
    location: str
    parameter: str
    env: Tuple[str, ...]
    description: Optional[str] = None


@dataclass(frozen=True)
class McpServerPackage:
    """A complete generated MCP server project.

    Attributes:
        package_name: The npm package name in ``package.json``.
        server_name: The name the server reports in the MCP ``initialize`` handshake, and the key
            the README's client registration uses.
        env_prefix: The prefix of every environment variable the server reads.
        base_url: The default base URL (the contract's first absolute server), or ``None`` when the
            consumer must set ``<PREFIX>_BASE_URL``.
        files: Every generated file, ordered by path.
        tools: The tools it offers, in contract order.
        skipped: The tools it does not offer, with reasons.
        auth: The security schemes it reads credentials for.
        unsupported_auth: Security schemes it cannot send a credential for.
        sdk_version: The ``@modelcontextprotocol/sdk`` release it is built on.
    """

    package_name: str
    server_name: str
    env_prefix: str
    base_url: Optional[str]
    files: Tuple[StubFile, ...] = ()
    tools: Tuple[McpServerTool, ...] = ()
    skipped: Tuple[McpServerSkipped, ...] = ()
    auth: Tuple[McpServerAuth, ...] = ()
    unsupported_auth: Tuple[str, ...] = ()
    sdk_version: str = MCP_SDK_VERSION

    @property
    def env_vars(self) -> Tuple[str, ...]:
        """Every environment variable the server reads, in README order."""
        names = [f"{self.env_prefix}_BASE_URL", f"{self.env_prefix}_HEADERS"]
        for entry in self.auth:
            names.extend(entry.env)
        return tuple(names)

    def file_map(self) -> Dict[str, str]:
        """Return ``path → text`` for every file, for callers that stage an archive."""
        return {item.path: item.text for item in self.files}


# ===========================================================================
# Names
# ===========================================================================


def mcp_server_package_name(*candidates: Optional[str]) -> str:
    """Derive the npm package name from the first usable candidate.

    Args:
        *candidates: Names to try in order — typically a tenant's configured npm name, then the
            project slug, then the API title.

    Returns:
        A legal npm name, always suffixed ``-mcp-server`` (``widgets`` → ``widgets-mcp-server``). A
        scope the tenant configured is kept: ``@acme/widgets`` becomes ``@acme/widgets-mcp-server``.
    """
    for candidate in candidates:
        text = (candidate or "").strip().lower()
        scope = ""
        if text.startswith("@") and "/" in text:
            scope, _, text = text.partition("/")
            scope += "/"
        parts = words(text)
        if parts and not parts[0][0].isdigit():
            stem = "-".join(parts)
            return scope + (stem if stem.endswith(_PACKAGE_SUFFIX) else f"{stem}{_PACKAGE_SUFFIX}")
    return DEFAULT_PACKAGE_NAME


def mcp_env_prefix(*candidates: Optional[str]) -> str:
    """Derive the environment-variable prefix from the first usable candidate.

    Args:
        *candidates: Names to try in order — typically the project slug, then the API title.

    Returns:
        An upper-snake prefix that starts with a letter (``acme-widgets`` → ``ACME_WIDGETS``).
    """
    for candidate in candidates:
        parts = words(candidate)
        if parts and parts[0][0].isalpha():
            return "_".join(parts).upper()
    return DEFAULT_ENV_PREFIX


def _npm_version(version: Optional[str]) -> str:
    """The contract's version when npm accepts it, else ``0.1.0``."""
    text = (version or "").strip().lstrip("vV")
    return text if _SEMVER.match(text) else "0.1.0"


def _default_base_url(api: CanonicalApi) -> Optional[str]:
    """The contract's first server, when it is an absolute http(s) URL with every variable resolved."""
    url, placeholders = resolve_server_base(api)
    if placeholders or not re.match(r"^https?://", url, re.IGNORECASE):
        return None
    return url


# ===========================================================================
# Rendering
# ===========================================================================


def _binding_literal(binding: OperationBinding) -> Dict[str, Any]:
    """The ``OperationBinding`` object ``src/contract.ts`` declares for one tool."""
    return {
        "method": binding.method,
        "path": binding.path_template,
        "parameters": [
            {
                "name": parameter.name,
                "location": parameter.location,
                "style": parameter.style,
                "explode": parameter.explode,
                "allowReserved": parameter.allow_reserved,
                "required": parameter.required,
            }
            for parameter in binding.parameters
        ],
        "bodyMode": binding.body_mode,
        "bodyRequired": binding.body_required,
        "bodyMediaType": binding.body_media_type,
        "accept": binding.accept,
    }


def _ts_literal(value: Any) -> str:
    """A JSON value as a TypeScript expression (JSON is one)."""
    return json.dumps(value, indent=2, ensure_ascii=False)


def _with_license(text: str, license_block: Optional[str]) -> str:
    """Prefix a TypeScript module with the licence block, after a shebang line if it has one."""
    if not license_block:
        return text
    if text.startswith("#!"):
        shebang, _, rest = text.partition("\n")
        return f"{shebang}\n{license_block}\n\n{rest}"
    return f"{license_block}\n\n{text}"


def _render_contract(
    *,
    server: Dict[str, str],
    env_prefix: str,
    base_url: Optional[str],
    user_agent: str,
    auth: List[McpServerAuth],
    tools: List[Dict[str, Any]],
    provenance: Dict[str, Any],
) -> str:
    """Render ``src/contract.ts``: everything about this contract the fixed runtime reads."""
    auth_literal = [
        {
            "scheme": entry.scheme,
            "kind": entry.kind,
            "location": entry.location,
            "parameter": entry.parameter,
            "env": list(entry.env),
        }
        for entry in auth
    ]
    lines = [
        "/**",
        " * This contract's tools, security schemes and defaults — generated by Apiome; do not edit.",
        " * Regenerate the server from the published contract instead.",
        " */",
        'import type { AuthEntry, ToolEntry } from "./types.js";',
        "",
        "/** What the server reports in the MCP `initialize` handshake. */",
        f"export const SERVER = {_ts_literal(server)} as const;",
        "",
        "/** The environment variables the configuration is read from. */",
        "export const ENV = "
        + _ts_literal({"baseUrl": f"{env_prefix}_BASE_URL", "headers": f"{env_prefix}_HEADERS"})
        + " as const;",
        "",
        "/** The base URL used when the environment sets none: the contract's first server. */",
        f"export const DEFAULT_BASE_URL: string | null = {_ts_literal(base_url)};",
        "",
        "/** Sent as `User-Agent` on every request. */",
        f"export const USER_AGENT = {_ts_literal(user_agent)};",
        "",
        "/** The contract's security schemes, each read from its own environment variables. */",
        f"export const AUTH: AuthEntry[] = {_ts_literal(auth_literal)};",
        "",
        "/** One tool per contract operation: its input schema and where each argument goes. */",
        f"export const TOOLS: ToolEntry[] = {_ts_literal(tools)};",
        "",
        "/** Which revision and generator produced this server. */",
        f"export const PROVENANCE = {_ts_literal(provenance)} as const;",
        "",
    ]
    return "\n".join(lines)


def _render_package_json(package: str, version: str, title: str, server_name: str) -> str:
    """Render ``package.json``: an ESM project with a ``bin`` so ``npx`` can launch it."""
    document = {
        "name": package,
        "version": version,
        "private": True,
        "description": f"MCP server for {title}, generated by Apiome.",
        "type": "module",
        "main": "dist/server.js",
        "bin": {server_name: "dist/server.js"},
        "files": ["dist"],
        "engines": {"node": NODE_ENGINE},
        "scripts": {
            "build": "tsc",
            "start": "node dist/server.js",
            "typecheck": "tsc --noEmit",
        },
        "dependencies": {
            "@modelcontextprotocol/sdk": f"^{MCP_SDK_VERSION}",
            "zod": f"^{ZOD_VERSION}",
        },
        "devDependencies": {
            "@types/node": f"^{NODE_TYPES_VERSION}",
            "typescript": f"^{TYPESCRIPT_VERSION}",
        },
    }
    return json.dumps(document, indent=2) + "\n"


def _render_tsconfig() -> str:
    """Render ``tsconfig.json``: strict, Node ESM."""
    document = {
        "compilerOptions": {
            "target": "ES2022",
            "module": "NodeNext",
            "moduleResolution": "NodeNext",
            "lib": ["ES2022"],
            "types": ["node"],
            "strict": True,
            "noImplicitOverride": True,
            "noUncheckedIndexedAccess": True,
            "forceConsistentCasingInFileNames": True,
            "skipLibCheck": True,
            "outDir": "dist",
            "rootDir": "src",
        },
        "include": ["src"],
    }
    return json.dumps(document, indent=2) + "\n"


def _auth_value_hint(entry: McpServerAuth, variable: str) -> str:
    """What one credential variable holds, for the README."""
    if entry.kind == "bearer":
        return "the bearer token (sent as `Authorization: Bearer …`)"
    if entry.kind == "basic":
        return "the user name" if variable == entry.env[0] else "the password"
    return f"the API key (sent in the `{entry.parameter}` {entry.location})"


def _render_env_example(package: McpServerPackage) -> str:
    """Render ``.env.example``: every variable, credentials empty."""
    prefix = package.env_prefix
    lines = [
        "# Environment for the generated MCP server. Copy the values into your MCP client's",
        "# server entry (its `env` block); never commit real credentials.",
        "",
        "# The API's base URL" + (" (defaults to the contract's first server)." if package.base_url else "."),
        f"{prefix}_BASE_URL={package.base_url or ''}",
        "",
        '# Extra headers for every request, as JSON, e.g. {"X-Mock-Session": "demo"} for the Apiome mock.',
        f"{prefix}_HEADERS=",
    ]
    for entry in package.auth:
        lines += ["", f"# Security scheme `{entry.scheme}` ({entry.kind})."]
        lines += [f"{variable}=" for variable in entry.env]
    return "\n".join(lines) + "\n"


def _first_sentence(text: Optional[str]) -> str:
    """The first line of a description, for a README table cell."""
    first = (text or "").strip().split("\n", 1)[0].strip()
    return first.replace("|", "\\|")


def _render_readme(
    package: McpServerPackage,
    *,
    title: str,
    descriptions: Dict[str, Optional[str]],
    license_header: Optional[str],
    revision: Optional[str],
) -> str:
    """Render the project's ``README.md``: install, configure, register, and the tool list."""
    prefix = package.env_prefix
    count = len(package.tools)
    lines: List[str] = [
        f"# {title} — MCP server",
        "",
        f"A [Model Context Protocol](https://modelcontextprotocol.io) server for **{title}**, generated by "
        f"Apiome from the published contract. It offers {count} "
        + ("tool" if count == 1 else "tools")
        + " — one per operation — and every tool call is a real request to the API. Arguments are "
        "checked against the tool's input schema first; a call that does not fit is refused and "
        "nothing is sent.",
        "",
    ]
    if license_header:
        lines += ["## Licence", "", "```", license_header.strip(), "```", ""]
    lines += [
        "## Install",
        "",
        f"Node.js 20 or later. The server is built on `@modelcontextprotocol/sdk` {package.sdk_version} "
        "and talks to its client over stdio.",
        "",
        "```bash",
        "npm install",
        "npm run build",
        "```",
        "",
        "## Configure",
        "",
        "Everything is read from environment variables — the generated code holds no credentials.",
        "`.env.example` lists every variable.",
        "",
        "| Variable | Holds |",
        "| --- | --- |",
        f"| `{prefix}_BASE_URL` | The API's base URL"
        + (f" (default `{package.base_url}`)" if package.base_url else " (**required**: the contract names none)")
        + " |",
        f'| `{prefix}_HEADERS` | Extra headers for every request, as JSON: `{{"X-Mock-Session": "demo"}}` |',
    ]
    for entry in package.auth:
        for variable in entry.env:
            lines.append(f"| `{variable}` | Scheme `{entry.scheme}`: {_auth_value_hint(entry, variable)} |")
    lines.append("")
    if package.auth:
        lines += [
            "A scheme whose variables are unset is not sent, so the API answers those calls as an "
            "anonymous caller.",
            "",
        ]
    if package.unsupported_auth:
        lines += [
            "No credential can be sent for "
            + ", ".join(f"`{name}`" for name in package.unsupported_auth)
            + f"; if the API accepts a header instead, put it in `{prefix}_HEADERS`.",
            "",
        ]

    env_block: Dict[str, str] = {f"{prefix}_BASE_URL": package.base_url or "https://api.example.com"}
    for entry in package.auth:
        for variable in entry.env:
            env_block[variable] = "<your credential>"
    registration = {
        "mcpServers": {
            package.server_name: {
                "command": "node",
                "args": ["/absolute/path/to/mcp/dist/server.js"],
                "env": env_block,
            }
        }
    }
    lines += [
        "## Register it with a client",
        "",
        "Add the server to your client's MCP configuration — `mcp.json`, `.mcp.json`, or "
        "`claude_desktop_config.json` — with the path to the built `dist/server.js`:",
        "",
        "```json",
        json.dumps(registration, indent=2),
        "```",
        "",
        f"To try it against the API's Apiome mock, set `{prefix}_BASE_URL` to the mock's URL and "
        f'`{prefix}_HEADERS` to `{{"X-Mock-Session": "demo"}}` so the mock remembers what you create.',
        "",
        "## Tools",
        "",
        "| Tool | Operation | Description |",
        "| --- | --- | --- |",
    ]
    for tool in package.tools:
        lines.append(
            f"| `{tool.name}` | `{tool.method} {tool.path}` | {_first_sentence(descriptions.get(tool.name))} |"
        )
    lines.append("")
    if package.skipped:
        lines += ["## Not included", ""]
        lines += [f"- `{item.name}` (`{item.operation_key}`) — {item.reason}" for item in package.skipped]
        lines.append("")
    lines += [
        "## Files",
        "",
        "- `src/contract.ts` — this API's tools, input schemas and security schemes (generated).",
        "- `src/server.ts` — the stdio server; the only file that imports the MCP SDK.",
        "- `src/handlers.ts`, `src/validate.ts`, `src/request.ts`, `src/config.ts`, `src/types.ts` — "
        "the call layer: schema checks, request building, configuration.",
        "",
        "---",
        "",
        f"Apiome MCP server `{MCP_SERVER_SCHEMA_VERSION}`"
        + (f" · revision `{revision}`" if revision else "")
        + f" · tool mapping v{MCP_TOOL_MAPPING_VERSION}.",
        "",
    ]
    return "\n".join(lines)


# ===========================================================================
# Generation
# ===========================================================================


def _operations_by_key(api: CanonicalApi) -> Dict[str, Operation]:
    """Every operation of the model, by canonical key."""
    return {operation.key: operation for service in api.services for operation in service.operations}


def _plan_auth(api: CanonicalApi, env_prefix: str) -> Tuple[List[McpServerAuth], List[str]]:
    """The contract's security schemes as environment variables, plus the unsupported ones."""
    settings, unsupported = plan_auth_settings(api)
    auth = [
        McpServerAuth(
            scheme=setting.scheme,
            kind=setting.kind,
            location=setting.location,
            parameter=setting.parameter,
            env=tuple(f"{env_prefix}_{attribute.upper()}" for attribute in setting.attributes),
            description=setting.description,
        )
        for setting in settings
    ]
    return auth, unsupported


def generate_mcp_server(
    api: CanonicalApi,
    *,
    package_name: Optional[str] = None,
    env_prefix: Optional[str] = None,
    license_header: Optional[str] = None,
    user_agent: Optional[str] = None,
    revision: Optional[str] = None,
    max_operations: int = DEFAULT_MAX_TOOLS,
) -> McpServerPackage:
    """Generate a runnable MCP server project for one published contract.

    The result is a pure function of its arguments: nothing here reads the clock, the environment
    or the filesystem.

    Args:
        api: The revision's canonical model.
        package_name: A name to derive the npm package name from (suffixed ``-mcp-server``).
            Defaults to the API's title.
        env_prefix: The environment-variable prefix. Defaults to one derived from the API's title.
        license_header: A tenant's resolved licence text (SDK-3.4), as a comment block at the top of
            every source file and quoted in the README.
        user_agent: The ``User-Agent`` every request carries. Defaults to ``<package>/<version>``.
        revision: The revision id the server was generated from, recorded as provenance.
        max_operations: How many tools the server carries at most; the rest are reported.

    Returns:
        The :class:`McpServerPackage`.

    Raises:
        app.mcp_tool_mapping.McpToolMappingError: The compiler produced an invalid tool — an
            internal invariant, raised rather than shipping a server an MCP client would reject.
    """
    title = (api.title or "").strip() or "API"
    package = mcp_server_package_name(package_name, title)
    server_name = package.rsplit("/", 1)[-1]
    prefix = env_prefix or mcp_env_prefix(title)
    version = _npm_version(api.version)
    base_url = _default_base_url(api)
    agent = user_agent or f"{server_name}/{version}"
    license_block = license_comment_block(license_header, "ts")

    toolset = compile_mcp_tools(api)
    operations = _operations_by_key(api)
    tools: List[McpServerTool] = []
    skipped: List[McpServerSkipped] = []
    entries: List[Dict[str, Any]] = []
    descriptions: Dict[str, Optional[str]] = {}
    for definition in toolset.tools:
        if len(tools) >= max_operations:
            skipped.append(
                McpServerSkipped(
                    definition.name,
                    definition.operation,
                    f"the server carries the first {max_operations} operations",
                )
            )
            continue
        operation = operations.get(definition.operation)
        try:
            if operation is None:
                raise OperationNotInvocableError(definition.operation)
            binding = binding_for(api, operation)
        except OperationNotInvocableError:
            skipped.append(
                McpServerSkipped(definition.name, definition.operation, "it has no HTTP method and path to call")
            )
            continue
        tools.append(McpServerTool(definition.name, definition.operation, binding.method, binding.path_template))
        descriptions[definition.name] = definition.description
        entry: Dict[str, Any] = {"name": definition.name}
        if definition.description:
            entry["description"] = definition.description
        entry["inputSchema"] = definition.input_schema
        entry["operation"] = definition.operation
        entry["binding"] = _binding_literal(binding)
        entries.append(entry)

    auth, unsupported = _plan_auth(api, prefix)
    result = McpServerPackage(
        package_name=package,
        server_name=server_name,
        env_prefix=prefix,
        base_url=base_url,
        tools=tuple(tools),
        skipped=tuple(skipped),
        auth=tuple(auth),
        unsupported_auth=tuple(unsupported),
    )

    contract = _render_contract(
        server={"name": server_name, "title": title, "version": version},
        env_prefix=prefix,
        base_url=base_url,
        user_agent=agent,
        auth=auth,
        tools=entries,
        provenance={
            "generator": f"app.mcp_server_generator/{MCP_SERVER_SCHEMA_VERSION}",
            "toolMappingVersion": MCP_TOOL_MAPPING_VERSION,
            "revision": revision,
        },
    )
    files: List[StubFile] = [StubFile(path="src/contract.ts", text=_with_license(contract, license_block))]
    files += [StubFile(path=path, text=_with_license(text, license_block)) for path, text in RUNTIME_FILES.items()]
    files += [
        StubFile(path="package.json", text=_render_package_json(package, version, title, server_name)),
        StubFile(path="tsconfig.json", text=_render_tsconfig()),
        StubFile(path=".env.example", text=_render_env_example(result)),
        StubFile(
            path="README.md",
            text=_render_readme(
                result, title=title, descriptions=descriptions, license_header=license_header, revision=revision
            ),
        ),
    ]
    files.sort(key=lambda item: item.path)
    return replace(result, files=tuple(files))
