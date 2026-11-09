"""The ``apiome mcp`` lifecycle checked against the REST contract — V2-MCP-EPIC-25 (#3648).

The epic's four children (#3703 register/list/show, #3704 discover + poll, #3705 lint + score,
#3706 test/invoke) each test their command against ``pytest-httpx`` mocks whose payloads were
written by hand. Nothing checked those payloads — or the requests the CLI sends — against the
canonical contract, ``apiome-rest/openapi.json``, so the CLI and REST could drift apart with every
test still green.

This suite runs the whole lifecycle in order — ``register --bearer`` → ``list`` → ``show`` →
``discover`` (polling) → ``lint --min-grade --fail-on-policy`` → ``test`` — through one mock that
routes every request through :class:`RestContract`:

* the method and path must be a documented operation;
* a JSON request body must validate against the operation's request schema;
* the mocked answer must validate against the operation's documented response schema for that
  status, so the CLI is exercised only on payloads REST can actually send.

REST request models accept each field's snake_case name as well as the camelCase alias the
OpenAPI documents (``AliasChoices`` in ``apiome-rest/src/app/models.py``); the CLI sends
snake_case, so a request body is checked after mapping a snake_case key to its documented camelCase
property, exactly as REST would read it.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import jsonschema
import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS
from apiome_cli.main import app
from helpers import strip_ansi

#: The canonical REST contract (repository checkout: ``<root>/apiome-rest/openapi.json``).
OPENAPI_PATH = Path(__file__).resolve().parents[2] / "apiome-rest" / "openapi.json"

BASE_URL = "http://localhost:8000"
TENANT = "acme"
TENANT_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
ENDPOINT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
JOB_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
VERSION_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
SECRET = "sk-contract-0001"

runner = CliRunner()

pytestmark = pytest.mark.skipif(
    not OPENAPI_PATH.exists(), reason="apiome-rest/openapi.json not in this checkout"
)


# ===========================================================================
# The contract
# ===========================================================================


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


class ContractViolation(AssertionError):
    """A request or a mocked response that the OpenAPI document does not allow."""


class RestContract:
    """Match requests to OpenAPI operations and validate bodies against their schemas."""

    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec
        self.routes: list[tuple[re.Pattern[str], str]] = []
        for template in spec["paths"]:
            pattern = re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(template))
            self.routes.append((re.compile(f"^{pattern}$"), template))

    def operation(self, method: str, path: str) -> tuple[str, dict[str, Any]]:
        """Return ``(path template, operation)`` for a request, or raise when undocumented.

        A literal template wins over one with parameters, as in the server's router.
        """
        matches = [template for pattern, template in self.routes if pattern.match(path)]
        matches.sort(key=lambda template: template.count("{"))
        for template in matches:
            operation = self.spec["paths"][template].get(method.lower())
            if operation is not None:
                return template, operation
        raise ContractViolation(f"{method} {path} is not a documented operation")

    def _validator(self, schema: dict[str, Any]) -> jsonschema.Draft202012Validator:
        # Refs are "#/components/schemas/…": resolve them against a root that carries components.
        return jsonschema.Draft202012Validator(
            {**schema, "components": self.spec["components"]}
        )

    def _resolve(self, schema: dict[str, Any]) -> dict[str, Any]:
        ref = schema.get("$ref")
        if not ref:
            return schema
        return self.spec["components"]["schemas"][ref.rsplit("/", 1)[-1]]

    def check_request(self, method: str, path: str, body: Any) -> None:
        """Validate a request body against the operation's ``application/json`` schema."""
        template, operation = self.operation(method, path)
        schema = (
            operation.get("requestBody", {})
            .get("content", {})
            .get("application/json", {})
            .get("schema")
        )
        if body is None:
            if schema is not None and operation["requestBody"].get("required"):
                raise ContractViolation(f"{method} {template} requires a body")
            return
        if schema is None:
            raise ContractViolation(f"{method} {template} takes no JSON body")
        properties = self._resolve(schema).get("properties", {})
        aliased = {
            (
                _camel(key)
                if key not in properties and _camel(key) in properties
                else key
            ): value
            for key, value in body.items()
        }
        errors = sorted(self._validator(schema).iter_errors(aliased), key=str)
        if errors:
            raise ContractViolation(f"{method} {template} request: {errors[0].message}")

    def check_response(self, method: str, path: str, status: int, payload: Any) -> None:
        """Validate a mocked answer against the operation's documented response for ``status``."""
        template, operation = self.operation(method, path)
        documented = operation["responses"].get(str(status))
        if documented is None:
            raise ContractViolation(
                f"{method} {template} does not document HTTP {status}"
            )
        schema = documented.get("content", {}).get("application/json", {}).get("schema")
        if schema is None:
            return
        errors = sorted(self._validator(schema).iter_errors(payload), key=str)
        if errors:
            location = "/".join(str(part) for part in errors[0].absolute_path)
            raise ContractViolation(
                f"{method} {template} {status} response at '{location}': {errors[0].message}"
            )


@lru_cache(maxsize=1)
def _contract() -> RestContract:
    return RestContract(json.loads(OPENAPI_PATH.read_text(encoding="utf-8")))


class ContractServer:
    """One ``pytest-httpx`` callback that answers through the contract and records each call."""

    def __init__(self, contract: RestContract) -> None:
        self.contract = contract
        #: ``(METHOD, path template) → list of (status, payload)``, answered in order (last repeats).
        self.answers: dict[tuple[str, str], list[tuple[int, Any]]] = {}
        self.calls: list[tuple[str, str, Any]] = []
        self.violations: list[str] = []

    def answer(
        self, method: str, template: str, payload: Any, status: int = 200
    ) -> None:
        self.answers.setdefault((method, template), []).append((status, payload))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        method = request.method
        path = urlsplit(str(request.url)).path
        body = json.loads(request.content) if request.content else None
        try:
            template, _ = self.contract.operation(method, path)
            self.contract.check_request(method, path, body)
            queue = self.answers[(method, template)]
            status, payload = queue.pop(0) if len(queue) > 1 else queue[0]
            self.contract.check_response(method, path, status, payload)
        except (ContractViolation, KeyError) as exc:
            self.violations.append(f"{method} {path}: {exc}")
            return httpx.Response(599, json={"detail": str(exc)})
        self.calls.append((method, template, body))
        return httpx.Response(status, json=payload)


@pytest.fixture
def server(httpx_mock: Any, monkeypatch: pytest.MonkeyPatch) -> ContractServer:
    monkeypatch.setenv("APIOME_API_KEY", "obj_test_workspace_key")
    monkeypatch.setenv("APIOME_BASE_URL", BASE_URL)
    monkeypatch.setenv("APIOME_TENANT_ID", TENANT)
    contract_server = ContractServer(_contract())
    httpx_mock.add_callback(contract_server, is_reusable=True, is_optional=True)
    return contract_server


# ===========================================================================
# Payloads REST sends (each is validated against the contract when served)
# ===========================================================================

EP = "/v1/mcp/{tenant_slug}/endpoints"
EP_ONE = EP + "/{endpoint_id}"


def _endpoint(**overrides: Any) -> dict[str, Any]:
    endpoint = {
        "id": ENDPOINT_ID,
        "tenant_id": TENANT_ID,
        "name": "Weather MCP",
        "slug": "weather-mcp",
        "endpoint_url": "https://mcp.example.com/mcp",
        "transport": "streamable_http",
        "description": None,
        "category": None,
        "visibility": "private",
        "published": False,
        "enabled": True,
        "discovery_cadence_seconds": None,
        "last_discovered_at": None,
        "last_discovery_status": None,
        "consecutive_failures": 0,
        "next_discovery_after": None,
        "quarantined": False,
        "quarantined_at": None,
        "quarantine_reason": None,
        "current_version_id": None,
        "added_via": "manual",
        "created_at": "2026-11-08T12:00:00Z",
        "updated_at": None,
    }
    endpoint.update(overrides)
    return endpoint


def _job_status(state: str) -> dict[str, Any]:
    done = state == "completed"
    return {
        "success": True,
        "job": {
            "job_id": JOB_ID,
            "endpoint_id": ENDPOINT_ID,
            "tenant_id": TENANT_ID,
            "state": state,
            "trigger": "manual",
            "terminal": done,
            "created_at": "2026-11-08T12:00:00Z",
            "started_at": "2026-11-08T12:00:01Z",
            "finished_at": "2026-11-08T12:00:03Z" if done else None,
            "duration_ms": 2000 if done else None,
            "version_id": VERSION_ID if done else None,
            "changed": True if done else None,
            "error": None,
            "error_detail": None,
            "result": {"version_seq": 1, "version_tag": "2026.11.08-a", "changed": True}
            if done
            else {},
            "status_path": f"/v1/mcp/{TENANT}/endpoints/{ENDPOINT_ID}/jobs/{JOB_ID}",
        },
    }


LINT_REPORT = {
    "success": True,
    "endpointId": ENDPOINT_ID,
    "versionId": VERSION_ID,
    "versionSeq": 1,
    "versionTag": "2026.11.08-a",
    "score": 88,
    "grade": "B",
    "findings": [
        {
            "id": "f-1",
            "path": "tools/forecast",
            "category": "documentation",
            "rule": "mcp-tool-description",
            "severity": "warning",
            "message": "Tool 'forecast' has a one-word description.",
        }
    ],
    "ruleHits": {"mcp-tool-description": 1},
    "severityCounts": {"warning": 1},
    "reportFingerprint": "sha256:abc",
    "source": "stored",
    "scoredAt": "2026-11-08T12:00:03Z",
    "algorithmId": "mcp-score-v1",
}

LINT_POLICY = {
    "policyVersion": {
        "id": "pv-1",
        "guideId": "g-1",
        "versionNumber": 3,
        "contentFingerprint": "sha256:p",
    },
    "evaluation": {
        "subjectType": "mcp_version",
        "subjectId": VERSION_ID,
        "policyVersionId": "pv-1",
        "policyContentFingerprint": "sha256:p",
        "passed": True,
    },
    "findings": [],
}

TEST_RESULT = {
    "success": True,
    "endpointId": ENDPOINT_ID,
    "itemType": "tool",
    "itemName": "forecast",
    "method": "tools/call",
    "target": "forecast",
    "completed": True,
    "isError": False,
    "content": [{"type": "text", "text": "Sunny, 21 °C"}],
    "structuredContent": None,
    "latencyMs": 142.0,
    "error": None,
    "authOverrideApplied": False,
    "invocationId": "inv-1",
}


def _invoke(*args: str) -> Any:
    return runner.invoke(app, list(args))


# ===========================================================================
# The lifecycle
# ===========================================================================


def test_mcp_lifecycle_matches_the_rest_contract(server: ContractServer) -> None:
    current = _endpoint(current_version_id=VERSION_ID, last_discovery_status="success")
    server.answer("POST", EP, {"success": True, "endpoint": _endpoint()}, status=201)
    server.answer(
        "PUT",
        EP_ONE + "/credentials",
        {
            "success": True,
            "credential": {
                "endpoint_id": ENDPOINT_ID,
                "auth_type": "bearer",
                "configured": True,
                "masked_secret": "••••••••",
                "key_version": 1,
                "oauth_metadata": {},
            },
        },
    )
    server.answer("GET", EP, {"success": True, "endpoints": [current]})
    server.answer("GET", EP_ONE, {"success": True, "endpoint": current})
    server.answer(
        "POST",
        EP_ONE + "/discover",
        {
            "success": True,
            "deduplicated": False,
            "job": {
                "id": JOB_ID,
                "endpoint_id": ENDPOINT_ID,
                "tenant_id": TENANT_ID,
                "state": "queued",
                "trigger": "manual",
                "result": {},
            },
        },
        status=202,
    )
    server.answer("GET", EP_ONE + "/jobs/{job_id}", _job_status("running"))
    server.answer("GET", EP_ONE + "/jobs/{job_id}", _job_status("completed"))
    server.answer("GET", EP_ONE + "/versions/{version_id}/lint", LINT_REPORT)
    server.answer("GET", EP_ONE + "/versions/{version_id}/lint/policy", LINT_POLICY)
    server.answer("POST", EP_ONE + "/test", TEST_RESULT)

    registered = _invoke(
        "mcp",
        "register",
        "--name",
        "Weather MCP",
        "--url",
        "https://mcp.example.com/mcp",
        "--bearer",
        SECRET,
    )
    listed = _invoke("mcp", "list")
    shown = _invoke("mcp", "show", ENDPOINT_ID)
    discovered = _invoke("mcp", "discover", ENDPOINT_ID, "--poll-interval", "0.1")
    linted = _invoke("mcp", "lint", ENDPOINT_ID, "--min-grade", "C", "--fail-on-policy")
    tested = _invoke(
        "mcp", "test", ENDPOINT_ID, "--tool", "forecast", "--arg", "city=Oslo"
    )

    assert server.violations == []
    for result in (registered, listed, shown, discovered, linted, tested):
        assert result.exit_code == EXIT_SUCCESS, strip_ansi(result.output)

    sent = [(method, template) for method, template, _ in server.calls]
    assert sent == [
        ("POST", EP),
        ("PUT", EP_ONE + "/credentials"),
        ("GET", EP),
        ("GET", EP_ONE),
        ("POST", EP_ONE + "/discover"),
        ("GET", EP_ONE + "/jobs/{job_id}"),
        ("GET", EP_ONE + "/jobs/{job_id}"),
        ("GET", EP_ONE + "/versions/{version_id}/lint"),
        ("GET", EP_ONE),
        ("GET", EP_ONE + "/versions/{version_id}/lint"),
        ("GET", EP_ONE + "/versions/{version_id}/lint/policy"),
        ("POST", EP_ONE + "/test"),
    ]
    bodies = {
        template: body for method, template, body in server.calls if body is not None
    }
    assert bodies[EP_ONE + "/credentials"] == {
        "auth_type": "bearer",
        "payload": {"token": SECRET},
    }
    assert bodies[EP_ONE + "/test"]["arguments"] == {"city": "Oslo"}

    assert SECRET not in registered.output
    assert "Weather MCP" in strip_ansi(listed.output)
    assert VERSION_ID in strip_ansi(discovered.output)
    assert "88" in strip_ansi(linted.output) and "B" in strip_ansi(linted.output)
    assert "Sunny, 21 °C" in strip_ansi(tested.output)


def test_json_output_passes_the_rest_payload_through(server: ContractServer) -> None:
    server.answer(
        "GET",
        EP_ONE,
        {"success": True, "endpoint": _endpoint(current_version_id=VERSION_ID)},
    )
    server.answer("GET", EP_ONE + "/versions/{version_id}/lint", LINT_REPORT)

    shown = _invoke("--json", "mcp", "show", ENDPOINT_ID)
    linted = _invoke("--json", "mcp", "lint", ENDPOINT_ID)

    assert server.violations == []
    assert json.loads(shown.output)["endpoint"]["id"] == ENDPOINT_ID
    assert json.loads(linted.output)["score"] == 88


def test_gates_fail_on_contract_shaped_answers(server: ContractServer) -> None:
    """A low grade, a tool error and a failed discovery all exit non-zero."""
    failed = _job_status("completed")
    failed["job"].update(
        state="failed", version_id=None, error="auth_required", result={}
    )
    server.answer(
        "GET",
        EP_ONE,
        {"success": True, "endpoint": _endpoint(current_version_id=VERSION_ID)},
    )
    server.answer(
        "GET",
        EP_ONE + "/versions/{version_id}/lint",
        {**LINT_REPORT, "score": 41, "grade": "F"},
    )
    server.answer("POST", EP_ONE + "/test", {**TEST_RESULT, "isError": True})
    server.answer(
        "POST",
        EP_ONE + "/discover",
        {
            "job": {
                "id": JOB_ID,
                "endpoint_id": ENDPOINT_ID,
                "tenant_id": TENANT_ID,
                "state": "queued",
                "trigger": "manual",
            }
        },
        status=202,
    )
    server.answer("GET", EP_ONE + "/jobs/{job_id}", failed)

    assert (
        _invoke("mcp", "lint", ENDPOINT_ID, "--min-grade", "B").exit_code == EXIT_ERROR
    )
    assert (
        _invoke("mcp", "test", ENDPOINT_ID, "--tool", "forecast").exit_code
        == EXIT_ERROR
    )
    assert (
        _invoke("mcp", "discover", ENDPOINT_ID, "--poll-interval", "0.1").exit_code
        != EXIT_SUCCESS
    )
    assert server.violations == []


# ===========================================================================
# The guard itself
# ===========================================================================


def test_the_contract_rejects_drift() -> None:
    """An undocumented route, a bad request body and an off-contract answer are all caught."""
    contract = _contract()
    endpoint_path = f"/v1/mcp/{TENANT}/endpoints/{ENDPOINT_ID}"

    with pytest.raises(ContractViolation, match="not a documented operation"):
        contract.operation("GET", f"{endpoint_path}/nonexistent")
    with pytest.raises(ContractViolation, match="request"):
        contract.check_request(
            "POST", f"/v1/mcp/{TENANT}/endpoints", {"name": "x"}
        )  # no endpoint_url
    contract.check_request(
        "POST",
        f"/v1/mcp/{TENANT}/endpoints",
        {"name": "x", "endpoint_url": "https://x"},
    )
    with pytest.raises(ContractViolation, match="response"):
        contract.check_response(
            "GET",
            endpoint_path,
            200,
            {"success": True, "endpoint": {"id": ENDPOINT_ID}},
        )
    with pytest.raises(ContractViolation, match="does not document HTTP 418"):
        contract.check_response("GET", endpoint_path, 418, {})
