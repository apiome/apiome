"""Tests for the MCP server generator — SDK-4.5 (#4499).

Most tests read the generated files as text. The gate at the end needs ``node`` and a TypeScript
compiler and is skipped without them: it compiles the generated, dependency-free core (everything
but ``src/server.ts``, the one file that imports the MCP SDK) under ``--strict`` and drives
``listTools`` / ``callTool`` against a local HTTP server — so the tool list, the input-schema
refusals and the requests that reach the API are proved by running the generated code.

The whole server has also been run by hand: ``npm install && npm run build`` in a generated
``mcp/`` directory, launched over stdio by the MCP SDK's own ``Client``, calling the SIM mock
(``apiome-mock run`` serving the Petstore fixture with ``X-Mock-Session``).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import pytest
import yaml
from corpus_loader import load_corpus

from app.mcp_operation_binding import binding_for
from app.mcp_server_generator import (
    DEFAULT_ENV_PREFIX,
    DEFAULT_PACKAGE_NAME,
    MCP_SERVER_SCHEMA_VERSION,
    McpServerPackage,
    generate_mcp_server,
    mcp_env_prefix,
    mcp_server_package_name,
)
from app.mcp_server_runtime import MCP_SDK_VERSION, RUNTIME_FILES
from app.mcp_tool_mapping import compile_mcp_tools
from app.openapi_normalizer import OpenApiNormalizer

#: The generated files that import nothing outside the project.
CORE_FILES = (
    "src/types.ts",
    "src/validate.ts",
    "src/request.ts",
    "src/contract.ts",
    "src/config.ts",
    "src/handlers.ts",
)


def _petstore_document() -> Dict[str, Any]:
    """The corpus Petstore fixture."""
    [entry] = load_corpus(format="openapi", feature="openapi-3.0-petstore")
    return yaml.safe_load(entry.read_text())


def _secured_document() -> Dict[str, Any]:
    """A small contract with one scheme of every supported kind, and one unsupported."""
    return {
        "openapi": "3.0.3",
        "info": {"title": "Widgets", "version": "2.1.0"},
        "servers": [{"url": "https://widgets.example.com/api"}],
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer"},
                "keyAuth": {"type": "apiKey", "in": "query", "name": "api_key"},
                "basicAuth": {"type": "http", "scheme": "basic"},
                "mtls": {"type": "mutualTLS"},
            }
        },
        "security": [{"bearerAuth": []}],
        "paths": {
            "/widgets/{widgetId}": {
                "get": {
                    "operationId": "getWidget",
                    "summary": "Get a widget",
                    "parameters": [
                        {"name": "widgetId", "in": "path", "required": True, "schema": {"type": "string"}},
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }


def _generate(document: Optional[Dict[str, Any]] = None, **options: Any) -> McpServerPackage:
    """Generate the server for ``document`` (default: the Petstore fixture)."""
    api = OpenApiNormalizer().normalize(document if document is not None else _petstore_document())
    return generate_mcp_server(api, **options)


def _contract_literal(text: str, name: str) -> Any:
    """Read one ``export const <name>… = <JSON>;`` literal back out of ``src/contract.ts``."""
    match = re.search(rf"export const {name}(?::[^=]+)? = (.*?)(?: as const)?;\n", text, re.DOTALL)
    assert match, name
    return json.loads(match.group(1))


# ===========================================================================
# Shape
# ===========================================================================


def test_the_project_has_its_files() -> None:
    files = _generate().file_map()
    assert set(files) == {
        ".env.example",
        "README.md",
        "package.json",
        "tsconfig.json",
        "src/contract.ts",
        *RUNTIME_FILES,
    }


def test_the_files_are_sorted_and_end_with_a_newline() -> None:
    package = _generate()
    paths = [item.path for item in package.files]
    assert paths == sorted(paths)
    assert all(item.text.endswith("\n") for item in package.files)


def test_generation_is_byte_deterministic() -> None:
    assert _generate(revision="r1").file_map() == _generate(revision="r1").file_map()


def test_the_package_is_an_esm_project_on_the_pinned_sdk() -> None:
    package = json.loads(_generate(package_name="petstore").file_map()["package.json"])
    assert package["name"] == "petstore-mcp-server"
    assert package["version"] == "1.0.0"
    assert package["type"] == "module"
    assert package["bin"] == {"petstore-mcp-server": "dist/server.js"}
    assert package["dependencies"]["@modelcontextprotocol/sdk"] == f"^{MCP_SDK_VERSION}"
    assert "zod" in package["dependencies"]
    assert package["scripts"]["build"] == "tsc"
    tsconfig = json.loads(_generate().file_map()["tsconfig.json"])
    assert tsconfig["compilerOptions"]["strict"] is True
    assert tsconfig["compilerOptions"]["module"] == "NodeNext"


def test_a_version_npm_rejects_falls_back() -> None:
    document = _secured_document()
    document["info"]["version"] = "2024-01-01"
    package = json.loads(_generate(document).file_map()["package.json"])
    assert package["version"] == "0.1.0"


def test_the_server_file_starts_with_its_shebang_even_under_a_licence() -> None:
    files = _generate(license_header="Copyright Acme").file_map()
    server = files["src/server.ts"]
    assert server.startswith("#!/usr/bin/env node\n// Copyright Acme\n")
    for path in CORE_FILES:
        assert files[path].startswith("// Copyright Acme\n"), path
    assert "Copyright Acme" in files["README.md"]


# ===========================================================================
# Names
# ===========================================================================


@pytest.mark.parametrize(
    ("candidates", "expected"),
    [
        (("widgets",), "widgets-mcp-server"),
        (("@acme/widgets",), "@acme/widgets-mcp-server"),
        (("widgets-mcp-server",), "widgets-mcp-server"),
        ((None, "", "Acme Widgets API"), "acme-widgets-api-mcp-server"),
        (("123",), DEFAULT_PACKAGE_NAME),
    ],
)
def test_package_names(candidates: tuple, expected: str) -> None:
    assert mcp_server_package_name(*candidates) == expected


@pytest.mark.parametrize(
    ("candidates", "expected"),
    [
        (("acme-widgets",), "ACME_WIDGETS"),
        (("9lives", "Pet Store"), "PET_STORE"),
        ((None,), DEFAULT_ENV_PREFIX),
    ],
)
def test_env_prefixes(candidates: tuple, expected: str) -> None:
    assert mcp_env_prefix(*candidates) == expected


# ===========================================================================
# Tools
# ===========================================================================


def test_one_tool_per_operation_with_the_compilers_input_schema() -> None:
    """The tools are exactly the AGX-1.1 toolset: same names, schemas and descriptions."""
    api = OpenApiNormalizer().normalize(_petstore_document())
    package = generate_mcp_server(api)
    toolset = compile_mcp_tools(api)
    tools = _contract_literal(package.file_map()["src/contract.ts"], "TOOLS")

    assert [tool["name"] for tool in tools] == [tool.name for tool in toolset.tools]
    assert {tool.name for tool in package.tools} == {
        "listPets",
        "createPet",
        "getPetById",
        "updatePet",
        "deletePet",
    }
    for entry, compiled in zip(tools, toolset.tools):
        assert entry["inputSchema"] == compiled.input_schema
        assert entry.get("description") == compiled.description
        assert entry["operation"] == compiled.operation


def test_each_tool_carries_the_shared_binding() -> None:
    """Where an argument goes is :func:`binding_for`'s answer, the managed proxy's too."""
    api = OpenApiNormalizer().normalize(_petstore_document())
    operations = {op.key: op for op in api.operations()}
    tools = _contract_literal(generate_mcp_server(api).file_map()["src/contract.ts"], "TOOLS")
    for entry in tools:
        expected = binding_for(api, operations[entry["operation"]])
        binding = entry["binding"]
        assert binding["method"] == expected.method
        assert binding["path"] == expected.path_template
        assert binding["bodyMode"] == expected.body_mode
        assert binding["bodyMediaType"] == expected.body_media_type
        assert [p["name"] for p in binding["parameters"]] == [p.name for p in expected.parameters]

    by_name = {entry["name"]: entry["binding"] for entry in tools}
    assert by_name["getPetById"]["parameters"][0] == {
        "name": "petId",
        "location": "path",
        "style": "simple",
        "explode": False,
        "allowReserved": False,
        "required": True,
    }
    assert by_name["createPet"]["bodyMode"] == "flat"
    assert by_name["createPet"]["bodyMediaType"] == "application/json"


def test_the_readme_lists_every_tool() -> None:
    package = _generate()
    readme = package.file_map()["README.md"]
    for tool in package.tools:
        assert f"| `{tool.name}` | `{tool.method} {tool.path}` |" in readme
    assert '"mcpServers"' in readme
    assert "dist/server.js" in readme


def test_the_tool_cap_reports_what_it_leaves_out() -> None:
    package = _generate(max_operations=2)
    assert len(package.tools) == 2
    assert len(package.skipped) == 3
    assert all("first 2 operations" in item.reason for item in package.skipped)
    assert "## Not included" in package.file_map()["README.md"]
    assert len(_contract_literal(package.file_map()["src/contract.ts"], "TOOLS")) == 2


def test_provenance_names_the_revision_and_generator() -> None:
    files = _generate(revision="rev-42").file_map()
    provenance = _contract_literal(files["src/contract.ts"], "PROVENANCE")
    assert provenance["revision"] == "rev-42"
    assert provenance["generator"] == f"app.mcp_server_generator/{MCP_SERVER_SCHEMA_VERSION}"
    assert "revision `rev-42`" in files["README.md"]


# ===========================================================================
# Configuration and auth
# ===========================================================================


def test_security_schemes_become_environment_variables() -> None:
    package = _generate(_secured_document(), env_prefix="WIDGETS")
    by_scheme = {entry.scheme: entry for entry in package.auth}
    assert by_scheme["bearerAuth"].env == ("WIDGETS_TOKEN",)
    assert by_scheme["keyAuth"].env == ("WIDGETS_API_KEY",)
    assert (by_scheme["keyAuth"].location, by_scheme["keyAuth"].parameter) == ("query", "api_key")
    assert by_scheme["basicAuth"].env == ("WIDGETS_USERNAME", "WIDGETS_PASSWORD")
    assert package.unsupported_auth == ("mtls",)

    auth = _contract_literal(package.file_map()["src/contract.ts"], "AUTH")
    assert {entry["scheme"]: entry["env"] for entry in auth} == {
        "bearerAuth": ["WIDGETS_TOKEN"],
        "keyAuth": ["WIDGETS_API_KEY"],
        "basicAuth": ["WIDGETS_USERNAME", "WIDGETS_PASSWORD"],
    }
    readme = package.file_map()["README.md"]
    assert "`WIDGETS_TOKEN`" in readme and "`mtls`" in readme


def test_the_artifact_carries_no_credential_values() -> None:
    package = _generate(_secured_document(), env_prefix="WIDGETS")
    example = package.file_map()[".env.example"]
    for variable in ("WIDGETS_TOKEN", "WIDGETS_API_KEY", "WIDGETS_USERNAME", "WIDGETS_PASSWORD", "WIDGETS_HEADERS"):
        assert f"\n{variable}=\n" in example, variable
    assert "WIDGETS_BASE_URL=https://widgets.example.com/api\n" in example
    readme = package.file_map()["README.md"]
    assert '"WIDGETS_TOKEN": "<your credential>"' in readme


def test_the_default_base_url_is_the_first_absolute_server() -> None:
    assert _generate(_secured_document()).base_url == "https://widgets.example.com/api"
    relative = _secured_document()
    relative["servers"] = [{"url": "/api"}]
    package = _generate(relative, env_prefix="WIDGETS")
    assert package.base_url is None
    assert _contract_literal(package.file_map()["src/contract.ts"], "DEFAULT_BASE_URL") is None
    assert "(**required**: the contract names none)" in package.file_map()["README.md"]


def test_the_user_agent_defaults_to_the_package() -> None:
    files = _generate(_secured_document()).file_map()
    assert _contract_literal(files["src/contract.ts"], "USER_AGENT") == "widgets-mcp-server/2.1.0"
    branded = _generate(_secured_document(), user_agent="acme-agent/1").file_map()
    assert _contract_literal(branded["src/contract.ts"], "USER_AGENT") == "acme-agent/1"


# ===========================================================================
# The gate: the generated core compiles, and its tools run
# ===========================================================================


def _typescript_compiler() -> Optional[str]:
    """Return a ``tsc`` entry point, or ``None`` when this machine has no TypeScript.

    ``PATH`` first, then a ``node_modules`` above this file (a monorepo checkout). Never ``npx``:
    a test that downloads a compiler fails for reasons unrelated to the generator.
    """
    binary = shutil.which("tsc")
    if binary:
        return binary
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "node_modules" / "typescript" / "bin" / "tsc"
        if candidate.exists():
            return str(candidate)
    return None


_GATE_AVAILABLE = _typescript_compiler() is not None and shutil.which("node") is not None


def _compile_core(package: McpServerPackage, root: Path) -> None:
    """Write ``package`` to ``root`` and compile its dependency-free core to ``root/dist``.

    ``DOM`` stands in for ``@types/node``: the core uses only the web globals Node also has
    (``fetch``, ``FormData``, ``AbortSignal``, ``TextEncoder``, ``btoa``).
    """
    for path, text in package.file_map().items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    compiler = _typescript_compiler()
    assert compiler is not None
    command = [compiler] if not compiler.endswith("bin/tsc") else [shutil.which("node") or "node", compiler]
    flags = ("--outDir", "dist", "--strict", "--noUncheckedIndexedAccess", "--target", "ES2022",
             "--module", "NodeNext", "--moduleResolution", "NodeNext", "--lib", "ES2022,DOM",
             "--skipLibCheck")
    compiled = subprocess.run([*command, *flags, *CORE_FILES], cwd=root, capture_output=True, text=True)
    assert compiled.returncode == 0, f"tsc failed:\n{compiled.stdout}{compiled.stderr}"


class _FakeApi(BaseHTTPRequestHandler):
    """Records every request and answers with a pet (``/v1/pets/404`` answers 404)."""

    seen: List[Dict[str, Any]] = []

    def _answer(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else ""
        _FakeApi.seen.append(
            {
                "method": self.command,
                "url": self.path,
                "body": body,
                "contentType": self.headers.get("Content-Type"),
                "userAgent": self.headers.get("User-Agent"),
                "session": self.headers.get("X-Mock-Session"),
            }
        )
        status = 404 if self.path.startswith("/v1/pets/404") else 200
        payload = json.dumps({"id": 7, "name": "Rex"}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = do_PUT = do_DELETE = _answer  # noqa: N815 - http.server's naming.

    def log_message(self, *args: Any) -> None:  # noqa: D401 - silence the default logging.
        """Keep the test output clean."""


@pytest.fixture()
def fake_api() -> Iterator[str]:
    """A local HTTP server standing in for the API; yields its ``/v1`` base URL."""
    _FakeApi.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeApi)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()


_DRIVER = """
import { callTool, listTools } from "./dist/handlers.js";
import { loadConfig } from "./dist/config.js";

const config = loadConfig(process.env);
const results = {
  tools: listTools(),
  get: await callTool("getPetById", { petId: 7 }, config),
  wrongType: await callTool("getPetById", { petId: "seven" }, config),
  missing: await callTool("getPetById", {}, config),
  outOfRange: await callTool("listPets", { limit: 500 }, config),
  list: await callTool("listPets", { limit: 5, tags: ["a", "b c"] }, config),
  create: await callTool("createPet", { id: 9, name: "Rex", tag: "dog" }, config),
  notFound: await callTool("getPetById", { petId: 404 }, config),
  unknown: await callTool("nope", {}, config),
};
let configError = null;
try {
  loadConfig({ PETSTORE_BASE_URL: "ftp://example.com" });
} catch (error) {
  configError = error.message;
}
results.configError = configError;
console.log(JSON.stringify(results));
"""


@pytest.mark.skipif(not _GATE_AVAILABLE, reason="no TypeScript compiler or node available")
def test_the_generated_server_lists_validates_and_calls(tmp_path: Path, fake_api: str) -> None:
    """The gate: the generated core compiles under --strict and its tools behave.

    * ``tools/list`` has one tool per operation with the compiler's input schema;
    * arguments that do not fit a tool's schema are refused, and **no request is sent**;
    * a conforming call is a real request: path, query and body serialized as the contract says,
      with the user agent and the env-configured extra header;
    * an HTTP error status is a tool error, not a crash.
    """
    package = _generate(env_prefix="PETSTORE")
    _compile_core(package, tmp_path)

    (tmp_path / "drive.mjs").write_text(_DRIVER)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PETSTORE_BASE_URL": fake_api,
        "PETSTORE_HEADERS": '{"X-Mock-Session": "gate"}',
    }
    run = subprocess.run(
        [shutil.which("node") or "node", "drive.mjs"], cwd=tmp_path, capture_output=True, text=True, env=env
    )
    assert run.returncode == 0, run.stderr
    results = json.loads(run.stdout)

    listed = {tool["name"]: tool for tool in results["tools"]}
    assert set(listed) == {tool.name for tool in package.tools}
    assert listed["getPetById"]["inputSchema"]["required"] == ["petId"]

    assert results["get"] == {"content": [{"type": "text", "text": '{\n  "id": 7,\n  "name": "Rex"\n}'}]}
    for refused in ("wrongType", "missing", "outOfRange"):
        assert results[refused]["isError"] is True, refused
        assert results[refused]["content"][0]["text"].startswith("Invalid arguments — nothing was sent:"), refused
    assert "petId: must be an integer, not a string" in results["wrongType"]["content"][0]["text"]
    assert "petId: is required" in results["missing"]["content"][0]["text"]
    assert "limit: must be at most 100" in results["outOfRange"]["content"][0]["text"]
    assert results["notFound"]["isError"] is True
    assert results["notFound"]["content"][0]["text"].startswith("HTTP 404")
    assert results["unknown"] == {"content": [{"type": "text", "text": "Unknown tool: nope."}], "isError": True}
    assert results["configError"] == "PETSTORE_BASE_URL must be an http:// or https:// URL."

    # Only the conforming calls reached the API — the refused ones sent nothing.
    seen = _FakeApi.seen
    assert [(item["method"], item["url"]) for item in seen] == [
        ("GET", "/v1/pets/7"),
        ("GET", "/v1/pets?limit=5&tags=a&tags=b%20c"),
        ("POST", "/v1/pets"),
        ("GET", "/v1/pets/404"),
    ]
    create = seen[2]
    assert json.loads(create["body"]) == {"id": 9, "name": "Rex", "tag": "dog"}
    assert create["contentType"] == "application/json"
    assert all(item["session"] == "gate" for item in seen)
    assert all(item["userAgent"] == f"{package.server_name}/1.0.0" for item in seen)


_AUTH_DRIVER = """
import { loadConfig } from "./dist/config.js";
const config = loadConfig({
  WIDGETS_TOKEN: "t0k",
  WIDGETS_API_KEY: "k&y",
  WIDGETS_USERNAME: "ann",
  WIDGETS_PASSWORD: "pw",
});
const anonymous = loadConfig({});
console.log(JSON.stringify({ config, anonymous }));
"""


@pytest.mark.skipif(not _GATE_AVAILABLE, reason="no TypeScript compiler or node available")
def test_credentials_come_only_from_the_environment(tmp_path: Path) -> None:
    """Each scheme reads its own variables and sends its credential where the contract says."""
    package = _generate(_secured_document(), env_prefix="WIDGETS")
    _compile_core(package, tmp_path)
    (tmp_path / "drive.mjs").write_text(_AUTH_DRIVER)
    run = subprocess.run([shutil.which("node") or "node", "drive.mjs"], cwd=tmp_path, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    results = json.loads(run.stdout)

    config = results["config"]
    assert config["baseUrl"] == "https://widgets.example.com/api"
    assert config["schemes"] == ["bearerAuth", "keyAuth", "basicAuth"]
    # Bearer and Basic share the Authorization header; the later scheme in the contract wins.
    assert config["headers"]["Authorization"] == "Basic YW5uOnB3"
    assert config["query"] == ["api_key=k%26y"]
    assert results["anonymous"]["schemes"] == []
    assert "Authorization" not in results["anonymous"]["headers"]
