#!/usr/bin/env python3
"""End-to-end golden-path smoke test for the objectified spine (RC1-0.1, #3608).

Drives one runnable "golden path" across the whole product, exiting non-zero on the
first failed step so it works as a CI regression net and an executable definition of
"the product works":

    import OpenAPI -> edit a class & a path -> lint -> cut a version -> publish
                  -> view in browse -> export OpenAPI + download via CLI -> query via MCP

The steps hit the same REST endpoints the UI calls (so the "edit in the UI" step is
exercised through the API), invoke the real ``objectified`` CLI for the export/download
step, and speak the MCP streamable-HTTP protocol for the final query. See
``docs/GOLDEN_PATH.md`` for the matching manual checklist.

Configuration (all optional; defaults match ``docker compose up`` + dev seed):

    OBJECTIFIED_REST_URL   REST base URL                (default http://localhost:8000)
    OBJECTIFIED_MCP_URL    MCP streamable-HTTP endpoint (default http://localhost:8765/mcp)
    OBJECTIFIED_TENANT     Seeded tenant slug           (default acme-corp)
    OBJECTIFIED_API_KEY    Seeded dev API key           (default sk_devseed0000...0000)
    OBJECTIFIED_CLI_CMD    Command to run the CLI       (default "objectified"; shlex-split)
    GOLDEN_PATH_FIXTURE    OpenAPI document to import    (default fixtures/petstore.openapi.yaml)
    GOLDEN_PATH_TIMEOUT    Per-request timeout seconds   (default 60)

Exit codes: 0 = full path green; 1 = a step failed (details on stderr).
"""

from __future__ import annotations

import base64
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

# openapi-spec-validator backs the "lint" step; it ships with objectified-cli's deps.
from openapi_spec_validator import validate as validate_openapi  # type: ignore

REST_URL = os.environ.get("OBJECTIFIED_REST_URL", "http://localhost:8000").rstrip("/")
MCP_URL = os.environ.get("OBJECTIFIED_MCP_URL", "http://localhost:8765/mcp").rstrip("/")
TENANT = os.environ.get("OBJECTIFIED_TENANT", "acme-corp")
API_KEY = os.environ.get(
    "OBJECTIFIED_API_KEY",
    "sk_devseed00000000000000000000000000000000000000000000000000000000",
)
CLI_CMD = shlex.split(os.environ.get("OBJECTIFIED_CLI_CMD", "objectified"))
FIXTURE = Path(
    os.environ.get(
        "GOLDEN_PATH_FIXTURE",
        str(Path(__file__).parent / "fixtures" / "petstore.openapi.yaml"),
    )
)
TIMEOUT = float(os.environ.get("GOLDEN_PATH_TIMEOUT", "60"))

# A per-run project slug keeps the smoke test idempotent and safe to run repeatedly
# (and in parallel) against a persistent database: each run imports into its own
# project, and every assertion keys off the project id returned by the import.
_RUN_ID = os.environ.get("GOLDEN_PATH_RUN_ID") or format(int(time.time()), "x")
PROJECT_SLUG = os.environ.get("GOLDEN_PATH_PROJECT_SLUG", f"golden-path-petstore-{_RUN_ID}")
PROJECT_NAME = f"Golden Path Petstore {_RUN_ID}"
IMPORT_VERSION = "1.0.0"
EDIT_MARKER = "Edited by the golden-path smoke test."


class SmokeError(RuntimeError):
    """A golden-path step failed; the message is printed and the process exits 1."""


# --------------------------------------------------------------------------- output


def step(msg: str) -> None:
    print(f"\n▶ {msg}", flush=True)


def ok(msg: str) -> None:
    print(f"  ✓ {msg}", flush=True)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeError(message)


def _detail(resp: httpx.Response) -> str:
    body = resp.text
    try:
        body = json.dumps(resp.json())
    except Exception:
        pass
    return f"HTTP {resp.status_code} {resp.request.method} {resp.request.url}\n    {body[:600]}"


# ------------------------------------------------------------------------- REST glue


class Rest:
    def __init__(self, client: httpx.Client) -> None:
        self.c = client
        self.h = {"X-API-Key": API_KEY}

    def get(self, path: str, **kw: Any) -> httpx.Response:
        return self.c.get(f"{REST_URL}{path}", headers=self.h, **kw)

    def post(self, path: str, **kw: Any) -> httpx.Response:
        return self.c.post(f"{REST_URL}{path}", headers=self.h, **kw)

    def put(self, path: str, **kw: Any) -> httpx.Response:
        return self.c.put(f"{REST_URL}{path}", headers=self.h, **kw)

    def ok_json(self, resp: httpx.Response, *expected: int) -> Any:
        if resp.status_code not in (expected or (200,)):
            raise SmokeError(_detail(resp))
        return resp.json()


# -------------------------------------------------------------------------- MCP glue


class McpClient:
    """Minimal MCP streamable-HTTP client: initialize handshake then tools/call."""

    def __init__(self, client: httpx.Client, url: str) -> None:
        self.c = client
        self.url = url
        self.session_id: Optional[str] = None
        self._next_id = 0
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

    @staticmethod
    def _parse(resp: httpx.Response) -> Optional[Dict[str, Any]]:
        if "text/event-stream" in resp.headers.get("content-type", ""):
            for line in resp.text.splitlines():
                if line.startswith("data:"):
                    return json.loads(line[5:].strip())
            return None
        return resp.json()

    def _post(self, payload: Dict[str, Any]) -> httpx.Response:
        headers = dict(self.headers)
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        return self.c.post(self.url, headers=headers, json=payload)

    def initialize(self) -> None:
        self._next_id += 1
        resp = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "golden-path-smoke", "version": "1.0"},
                },
            }
        )
        if resp.status_code != 200:
            raise SmokeError(_detail(resp))
        self.session_id = resp.headers.get("mcp-session-id")
        require(bool(self.session_id), "MCP initialize did not return a session id")
        notified = self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        if notified.status_code not in (200, 202):
            raise SmokeError(_detail(notified))

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self._next_id += 1
        resp = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }
        )
        if resp.status_code != 200:
            raise SmokeError(_detail(resp))
        body = self._parse(resp) or {}
        if body.get("error"):
            raise SmokeError(f"MCP tool {name} returned error: {body['error']}")
        result = body.get("result", {})
        if result.get("isError"):
            raise SmokeError(f"MCP tool {name} reported isError: {result}")
        # Prefer the parsed structuredContent; fall back to the JSON text block.
        if "structuredContent" in result:
            return result["structuredContent"]
        content = result.get("content") or []
        if content and content[0].get("type") == "text":
            return json.loads(content[0]["text"])
        return result


# ----------------------------------------------------------------------------- steps


def wait_healthy(rest: Rest, mcp_base: str) -> None:
    step("Health: REST and MCP are up")
    deadline = time.time() + 90
    rest_ok = mcp_ok = False
    while time.time() < deadline and not (rest_ok and mcp_ok):
        if not rest_ok:
            try:
                rest_ok = rest.get("/health").status_code == 200
            except httpx.HTTPError:
                pass
        if not mcp_ok:
            try:
                mcp_ok = httpx.get(f"{mcp_base}/health", timeout=5).status_code == 200
            except httpx.HTTPError:
                pass
        if not (rest_ok and mcp_ok):
            time.sleep(1)
    require(rest_ok, f"REST /health never became ready at {REST_URL}")
    require(mcp_ok, f"MCP /health never became ready at {mcp_base}")
    ok("REST and MCP healthy")


def import_openapi(rest: Rest) -> Dict[str, str]:
    step("Import an OpenAPI document")
    require(FIXTURE.is_file(), f"fixture not found: {FIXTURE}")
    document = FIXTURE.read_bytes()
    body = {
        "metadata": {
            "source_kind": "openapi-3",
            "project": {"name": PROJECT_NAME, "slug": PROJECT_SLUG},
            "version": {"version_id": IMPORT_VERSION},
            "options": {},
        },
        "document_base64": base64.b64encode(document).decode("ascii"),
        "filename": FIXTURE.name,
        "content_type": "application/yaml",
    }
    started = rest.ok_json(rest.post(f"/v1/tenants/{TENANT}/imports", json=body), 202)
    job_id = started["job_id"]
    ok(f"import job {job_id} accepted")

    deadline = time.time() + TIMEOUT
    state = "queued"
    final: Dict[str, Any] = {}
    terminal = {"completed", "failed", "pending-approval", "canceled", "rolled-back"}
    while time.time() < deadline:
        final = rest.ok_json(rest.get(f"/v1/tenants/{TENANT}/imports/{job_id}"))
        state = final["state"]
        if state in terminal:
            break
        time.sleep(0.25)
    require(state == "completed", f"import did not complete (state={state}): {final.get('events')}")
    ok("import worker completed")

    committed = rest.ok_json(rest.post(f"/v1/tenants/{TENANT}/imports/{job_id}/commit"))
    project_id = committed["project_id"]
    version_record_id = committed["version_record_id"]
    require(committed.get("project_slug") == PROJECT_SLUG, f"unexpected project slug: {committed}")
    ok(f"import committed: project={project_id} version={version_record_id} ({committed['version_id']})")
    return {"project_id": project_id, "version_record_id": version_record_id}


def edit_class(rest: Rest, version_record_id: str) -> str:
    step("Edit a class (via the REST endpoint the UI uses)")
    classes: List[Dict[str, Any]] = rest.ok_json(
        rest.get(f"/v1/classes/{TENANT}", params={"version_id": version_record_id})
    )
    require(len(classes) >= 1, "import produced no classes to edit")
    # Document every class: publication requires a description on each (server gate),
    # and this is exactly the "edit a class" the golden path describes.
    primary = next((c for c in classes if c["name"] == "Pet"), classes[0])
    for cls in classes:
        desc = EDIT_MARKER if cls["id"] == primary["id"] else f"{cls['name']} object."
        updated = rest.ok_json(rest.put(f"/v1/classes/{TENANT}/{cls['id']}", json={"description": desc}))
        require(updated["description"] == desc, f"class description did not persist for {cls['name']}")
    ok(f"edited {len(classes)} class description(s); primary='{primary['name']}'")
    return primary["name"]


def edit_path(rest: Rest, version_record_id: str) -> str:
    step("Edit a path (via the REST endpoint the UI uses)")
    paths: List[Dict[str, Any]] = rest.ok_json(rest.get(f"/v1/paths/{TENANT}/{version_record_id}"))
    require(len(paths) >= 1, "import produced no paths to edit")
    target = paths[0]
    marker = {"goldenPath": "edited", "note": EDIT_MARKER}
    updated = rest.ok_json(
        rest.put(f"/v1/paths/{TENANT}/{version_record_id}/{target['id']}", json={"metadata": marker})
    )
    require(updated.get("metadata") == marker, f"path metadata did not persist: {updated}")
    ok(f"edited path '{target['pathname']}'")
    return str(target["pathname"])


def cut_version(rest: Rest, project_id: str, base_revision_id: str) -> Dict[str, str]:
    step("Cut a version (push a new revision via the versioning endpoint)")
    request = {
        "baseRevisionId": base_revision_id,
        "bump_strategy": "minor",
        "short_message": "Golden path: cut a new version",
        "source_version_id": base_revision_id,  # copy classes forward into the new revision
    }
    created = rest.post(f"/v1/versions/{TENANT}/{project_id}", json=request)
    # On a STALE_HEAD (409) retry once against the server-reported current head.
    if created.status_code == 409:
        head = (created.json().get("detail") or {}).get("currentHead")
        require(bool(head), _detail(created))
        request["baseRevisionId"] = request["source_version_id"] = head
        created = rest.post(f"/v1/versions/{TENANT}/{project_id}", json=request)
    new_version = rest.ok_json(created)
    require(new_version["version_id"] != IMPORT_VERSION, "cut did not bump the version line")
    ok(f"cut version {new_version['version_id']} (record {new_version['id']})")
    return {"version_record_id": new_version["id"], "version_id": new_version["version_id"]}


def publish_version(rest: Rest, project_id: str, version_record_id: str) -> None:
    step("Publish the version")
    published = rest.ok_json(
        rest.post(
            f"/v1/versions/{TENANT}/{project_id}/{version_record_id}/publish",
            json={
                "visibility": "public",
                "short_message": "Golden path: publish the release",
                "changelog": "Published by the end-to-end golden-path smoke test.",
            },
        )
    )
    require(published.get("published") is True, f"version not marked published: {published}")
    require(published.get("visibility") == "public", f"version not public: {published}")
    ok("version published (public)")


def lint_published_spec(rest: Rest, project_slug: str, version_id: str, edited_class: str) -> Dict[str, Any]:
    step("Lint: validate the reconstructed OpenAPI of the published version")
    spec = rest.ok_json(rest.get(f"/v1/schema/{TENANT}/{project_slug}/{version_id}"))
    validate_openapi(spec)  # raises on a structurally invalid document
    schemas = (spec.get("components") or {}).get("schemas") or {}
    require(edited_class in schemas, f"edited class '{edited_class}' missing from reconstructed spec")
    require(bool(spec.get("paths")), "reconstructed spec has no paths")
    ok(f"reconstructed OpenAPI is valid ({len(schemas)} schemas, {len(spec['paths'])} paths)")
    return spec


def view_in_browse(rest: Rest, project_slug: str, version_id: str) -> None:
    step("View in browse (public directory)")
    listing = rest.ok_json(rest.get(f"/v1/browse/tenants/{TENANT}/projects/{project_slug}/versions"))
    versions = listing.get("versions") if isinstance(listing, dict) else listing
    require(isinstance(versions, list) and versions, f"browse returned no versions: {listing}")
    labels = {str(v.get("version") or v.get("version_id")) for v in versions}
    require(version_id in labels, f"published version {version_id} not visible in browse: {labels}")
    ok(f"version {version_id} is browsable ({len(versions)} published version(s))")


def export_via_cli(project_slug: str, version_id: str, edited_class: str) -> None:
    step("Export OpenAPI + download via the CLI")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "exported.openapi.json"
        cmd = [
            *CLI_CMD,
            "--base-url",
            REST_URL,
            "spec",
            "export",
            "--tenant",
            TENANT,
            "--project",
            project_slug,
            "--version",
            version_id,
            "--format",
            "openapi",
            "--output",
            str(out),
        ]
        env = {**os.environ, "OBJECTIFIED_API_KEY": API_KEY, "OBJECTIFIED_LOAD_DOTENV": "0"}
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            raise SmokeError(
                f"CLI export failed (exit {proc.returncode})\n"
                f"    cmd: {' '.join(shlex.quote(c) for c in cmd)}\n"
                f"    stdout: {proc.stdout[:400]}\n    stderr: {proc.stderr[:600]}"
            )
        require(out.is_file() and out.stat().st_size > 0, "CLI did not write an export file")
        spec = json.loads(out.read_text())
        validate_openapi(spec)
        schemas = (spec.get("components") or {}).get("schemas") or {}
        require(edited_class in schemas, f"CLI export missing edited class '{edited_class}'")
        ok(f"CLI downloaded a valid OpenAPI document ({out.stat().st_size} bytes)")


def query_via_mcp(client: httpx.Client, project_id: str) -> None:
    step("Query via MCP")
    mcp = McpClient(client, MCP_URL)
    mcp.initialize()
    ping = mcp.call_tool("ping")
    require(ping.get("db_ok") is True, f"MCP ping reports db not ok: {ping}")
    ok(f"MCP ping ok (service={ping.get('service')} v{ping.get('version')})")

    specs = mcp.call_tool("spec.list", {"limit": 50})
    spec_projects = {str(i.get("project_id")) for i in specs.get("items", [])}
    require(
        project_id in spec_projects,
        f"published project {project_id} not visible via MCP spec.list: {spec_projects}",
    )
    ok(f"MCP spec.list surfaces the published spec ({len(specs.get('items', []))} item(s))")

    projects = mcp.call_tool("project.list", {"limit": 50})
    listed = {str(i.get("project_id")) for i in projects.get("items", [])}
    require(project_id in listed, f"project {project_id} not visible via MCP project.list: {listed}")
    ok("MCP project.list surfaces the project")


def main() -> int:
    print("=== objectified golden-path smoke test (#3608) ===")
    print(f"REST: {REST_URL}   MCP: {MCP_URL}   tenant: {TENANT}")
    mcp_base = MCP_URL[: -len("/mcp")] if MCP_URL.endswith("/mcp") else MCP_URL
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            rest = Rest(client)
            wait_healthy(rest, mcp_base)
            imported = import_openapi(rest)
            edited_class = edit_class(rest, imported["version_record_id"])
            edit_path(rest, imported["version_record_id"])
            # Exercise the version-cut (push) endpoint as a distinct spine capability.
            # The released artifact is the imported, edited revision: in this product a
            # revision's paths are authored on that revision and are not carried across a
            # cut, so the imported revision is the one that holds the full path set.
            cut_version(rest, imported["project_id"], imported["version_record_id"])
            publish_version(rest, imported["project_id"], imported["version_record_id"])
            lint_published_spec(rest, PROJECT_SLUG, IMPORT_VERSION, edited_class)
            view_in_browse(rest, PROJECT_SLUG, IMPORT_VERSION)
            export_via_cli(PROJECT_SLUG, IMPORT_VERSION, edited_class)
            query_via_mcp(client, imported["project_id"])
    except SmokeError as exc:
        print(f"\n✗ GOLDEN PATH FAILED: {exc}", file=sys.stderr, flush=True)
        return 1
    except Exception as exc:  # noqa: BLE001 - surface anything unexpected as a failure
        print(f"\n✗ GOLDEN PATH ERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1
    print("\n✅ GOLDEN PATH GREEN — every step passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
