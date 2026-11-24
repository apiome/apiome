#!/usr/bin/env python3
"""Pact Broker API conformance suite — PFX-1.8 (#6921).

Runs the official Pact tooling against a running Apiome and fails on the first step whose result
differs from what the Pact Broker would give:

1. **pact-broker CLI** (``pactfoundation/pact-cli``, Docker): ``create-environment`` →
   ``publish`` → verify (the image's ``pact-provider-verifier``, publishing results) →
   ``record-deployment`` → ``can-i-deploy`` (yes, then no for an unverified version) →
   ``create-version-tag``, ``record-release``, ``record-support-ended``, ``record-undeployment``,
   ``describe-environment``, ``list-environments``, ``create-webhook``,
   ``create-or-update-webhook`` — and one unsupported command, which must end on Apiome's
   documented 501, not a 404.
2. **Golden transcripts**: the HAL documents a client reads along the way (index, pacticipant,
   version, pact, for-verification, verification result, environments, matrix, can-i-deploy, a
   webhook and a 501), normalised (host, UUIDs, timestamps) and compared with ``golden/*.json``; the CLI's
   output is compared with ``golden/cli-*.txt``.
3. **pact-js** (``--clients pact-js``, Docker ``node``): a PactV3 consumer test writes a pact, the
   CLI publishes it, and pact-js's ``Verifier`` (the Rust core) fetches it with selectors and
   publishes its result.
4. **pact-jvm** (``--clients pact-jvm``, Docker ``gradle``): a JUnit 5 consumer test writes a pact,
   the Gradle plugin's ``pactPublish`` publishes it, and a JUnit 5 provider test verifies it from
   the broker and publishes its result.

Each client then asks ``can-i-deploy`` for its consumer, which must say yes.

The suite expects a **fresh** database (it uses fixed pacticipant names so its transcripts are
stable); ``run.sh`` brings one up. Only the standard library is used.

Usage::

    python3 scripts/pact_conformance/conformance.py \\
        --rest-url http://localhost:8000 --tenant acme-corp --api-key sk_devseed000… \\
        [--clients cli,pact-js,pact-jvm] [--update-golden]

Exit codes: 0 green; 1 a step failed (details on stderr); 2 bad arguments.
"""

from __future__ import annotations

import argparse
import base64
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
GOLDEN_DIR = HERE / "golden"
CATALOG = REPO_ROOT / "apiome-rest" / "src" / "app" / "pact_broker_compat.py"

#: The official images, pinned by digest so a transcript only changes when we choose to.
PACT_CLI_IMAGE = os.environ.get(
    "PACT_CLI_IMAGE",
    "pactfoundation/pact-cli@sha256:72f1df83a7c42abd02e69a0fa21c3adc037d72c2852daa9f2910bb35617b207b",
)
NODE_IMAGE = os.environ.get("PACT_NODE_IMAGE", "node:22.20.0-bookworm")
GRADLE_IMAGE = os.environ.get("PACT_GRADLE_IMAGE", "gradle:8.14.3-jdk17")

ENVIRONMENT = "conformance-production"
CONSUMER, PROVIDER = "ConformanceWeb", "ConformanceAPI"
#: Where the suite's webhooks point. They are created, read and deleted; nothing is ever sent.
WEBHOOK_URL = "https://example.com/hooks/pact"
WEBHOOK_UUID = "6922c0de-0000-4000-8000-000000000001"
JS_CONSUMER, JS_PROVIDER = "ConformanceJsWeb", "ConformanceJsAPI"
JVM_CONSUMER, JVM_PROVIDER = "ConformanceJvmWeb", "ConformanceJvmAPI"

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?")
_HTTP_DATE = re.compile(r"[A-Z][a-z]{2}, \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2} GMT")
#: The for-verification link's metadata segment: base64 of a query naming a consumer version id.
_METADATA = re.compile(r"/metadata/([A-Za-z0-9_-]+={0,2})")


def _readable_metadata(match: "re.Match[str]") -> str:
    """Decode a ``/metadata/<base64>`` segment so its volatile ids can be normalised."""
    token = match.group(1)
    try:
        decoded = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("ascii")
    except (ValueError, UnicodeDecodeError):
        return match.group(0)
    return "/metadata/<" + _UUID.sub("{uuid}", decoded) + ">"


class ConformanceError(RuntimeError):
    """A step did not behave as the Pact Broker would; the message says how."""


def step(message: str) -> None:
    """Announce a step."""
    print(f"\n▶ {message}", flush=True)


def ok(message: str) -> None:
    """Report a passed check."""
    print(f"  ✓ {message}", flush=True)


def require(condition: bool, message: str) -> None:
    """Fail the suite unless ``condition`` holds."""
    if not condition:
        raise ConformanceError(message)


@dataclass
class Config:
    """Where Apiome is and what to run.

    Attributes:
        rest_url: Apiome's REST origin, e.g. ``http://localhost:8000``.
        tenant: The tenant slug whose broker is exercised.
        api_key: A workspace API key of that tenant (sent as a bearer token, as Pact tools do).
        clients: Which client families to run (``cli``, ``pact-js``, ``pact-jvm``).
        update_golden: Rewrite the golden files instead of comparing with them.
        provider_port: Port of the provider stub the verifiers replay against.
    """

    rest_url: str
    tenant: str
    api_key: str
    clients: Sequence[str]
    update_golden: bool = False
    provider_port: int = 8790
    mismatches: List[str] = field(default_factory=list)

    @property
    def broker_url(self) -> str:
        """The broker base URL every Pact tool is given."""
        return f"{self.rest_url}/v1/tenants/{self.tenant}/pact-broker"

    @property
    def provider_url(self) -> str:
        """The provider stub's base URL."""
        return f"http://127.0.0.1:{self.provider_port}"


# ---------------------------------------------------------------------------------------------
# HTTP and golden transcripts
# ---------------------------------------------------------------------------------------------


def broker_call(
    config: Config, method: str, path: str, body: Optional[Dict[str, Any]] = None
) -> Tuple[int, Dict[str, Any]]:
    """Call the broker as a Pact client does (bearer token, HAL accept header).

    Args:
        config: The run's configuration.
        method: HTTP method.
        path: Path under the broker base URL (``""`` for the index), query string included.
        body: JSON body, if any.

    Returns:
        The status code and the decoded JSON body (``{}`` when there is none).
    """
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        config.broker_url + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Accept": "application/hal+json, application/json",
            **({"Content-Type": "application/json"} if data is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    return status, (json.loads(raw) if raw.strip() else {})


def normalise(config: Config, value: Any) -> Any:
    """Make a document comparable across runs: the origin, UUIDs and timestamps become tokens.

    Args:
        config: The run's configuration (its origin is replaced by ``{rest}``).
        value: A decoded JSON value or a string.

    Returns:
        The same structure with volatile strings replaced.
    """
    if isinstance(value, dict):
        return {key: normalise(config, item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalise(config, item) for item in value]
    if isinstance(value, str):
        text = value.replace(config.rest_url, "{rest}").replace(config.provider_url, "{provider}")
        text = _METADATA.sub(_readable_metadata, text)
        text = _HTTP_DATE.sub("{http-date}", text)
        return _TIMESTAMP.sub("{timestamp}", _UUID.sub("{uuid}", text))
    return value


def check_golden(config: Config, name: str, content: str) -> None:
    """Compare one transcript with ``golden/<name>``, or rewrite it with ``--update-golden``.

    A mismatch is collected, not raised, so one run reports every drifted transcript.

    Args:
        config: The run's configuration.
        name: File name under ``golden/``.
        content: The normalised transcript.
    """
    path = GOLDEN_DIR / name
    if config.update_golden:
        GOLDEN_DIR.mkdir(exist_ok=True)
        path.write_text(content, encoding="utf-8")
        ok(f"golden/{name} written")
        return
    expected = path.read_text(encoding="utf-8") if path.exists() else None
    if expected == content:
        ok(f"golden/{name} matches")
        return
    actual = path.with_suffix(path.suffix + ".actual")
    actual.write_text(content, encoding="utf-8")
    config.mismatches.append(name)
    print(f"  ✗ golden/{name} differs — the response is in {actual.relative_to(REPO_ROOT)}", flush=True)


def golden_http(
    config: Config, name: str, method: str, path: str, body: Optional[Dict[str, Any]] = None, expect: int = 200
) -> Dict[str, Any]:
    """Call the broker, check the status, and compare the normalised exchange with its golden.

    Args:
        config: The run's configuration.
        name: The transcript's base name (``golden/<name>.json``).
        method: HTTP method.
        path: Path under the broker base URL.
        body: JSON body, if any.
        expect: The status the Pact Broker would answer.

    Returns:
        The decoded response body.
    """
    status, document = broker_call(config, method, path, body)
    require(status == expect, f"{method} {path}: expected {expect}, got {status}: {json.dumps(document)[:600]}")
    transcript = {
        "request": {"method": method, "path": normalise(config, path), **({"body": body} if body else {})},
        "response": {"status": status, "body": normalise(config, document)},
    }
    check_golden(config, f"{name}.json", json.dumps(transcript, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return document


# ---------------------------------------------------------------------------------------------
# Docker-run tools
# ---------------------------------------------------------------------------------------------


def docker(args: Sequence[str], *, expect: int = 0, label: str) -> str:
    """Run a container on the host network and check its exit code.

    Args:
        args: Arguments after ``docker run --rm --network host``.
        expect: The exit code the tool must end with.
        label: What the step is, for the error message.

    Returns:
        The tool's combined output with ANSI colours removed.
    """
    command = ["docker", "run", "--rm", "--network", "host", *args]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=1800)
    output = _ANSI.sub("", completed.stdout + completed.stderr)
    if completed.returncode != expect:
        raise ConformanceError(f"{label}: exit {completed.returncode}, expected {expect}\n{output[-4000:]}")
    return output


def pact_broker(config: Config, *args: str, expect: int = 0, golden: Optional[str] = None) -> str:
    """Run one ``pact-broker`` CLI command against Apiome, as a pipeline would.

    Args:
        config: The run's configuration.
        args: The command and its options.
        expect: The exit code the Pact Broker would cause.
        golden: When given, the output is compared with ``golden/cli-<golden>.txt``.

    Returns:
        The command's output.
    """
    output = docker(
        [
            "-v",
            f"{HERE / 'pacts'}:/pacts:ro",
            "-e",
            f"PACT_BROKER_BASE_URL={config.broker_url}",
            "-e",
            f"PACT_BROKER_TOKEN={config.api_key}",
            PACT_CLI_IMAGE,
            "pact-broker",
            *args,
        ],
        expect=expect,
        label=f"pact-broker {args[0]}",
    )
    ok(f"pact-broker {' '.join(args[:1])} → exit {expect}")
    if golden:
        check_golden(config, f"cli-{golden}.txt", normalise(config, output.rstrip()) + "\n")
    return output


# ---------------------------------------------------------------------------------------------
# The provider the verifiers replay against
# ---------------------------------------------------------------------------------------------


class _Provider(http.server.BaseHTTPRequestHandler):
    """A tiny provider honouring every interaction in ``pacts/`` and the client examples."""

    ROUTES = {
        "/health": {"status": "ok"},
        "/orders/1": {"id": 1, "status": "open", "total": 12.5},
    }

    def do_GET(self) -> None:  # noqa: N802 — the http.server hook name
        body = self.ROUTES.get(self.path.split("?")[0])
        self._send(200 if body is not None else 404, body or {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 — provider-state set-up calls
        self._send(200, {})

    def _send(self, status: int, body: Dict[str, Any]) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_: Any) -> None:  # keep the suite's output readable
        return


def start_provider(port: int) -> http.server.HTTPServer:
    """Serve the provider stub on a background thread.

    Args:
        port: The port to listen on (127.0.0.1).

    Returns:
        The running server; call ``shutdown()`` when done.
    """
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), _Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# ---------------------------------------------------------------------------------------------
# Suites
# ---------------------------------------------------------------------------------------------


def check_client_version() -> None:
    """The CLI image must carry the client version the compatibility catalog names."""
    match = re.search(r'PACT_BROKER_CLIENT_VERSION = "([^"]+)"', CATALOG.read_text(encoding="utf-8"))
    require(match is not None, f"no PACT_BROKER_CLIENT_VERSION in {CATALOG}")
    output = docker([PACT_CLI_IMAGE, "pact-broker", "version"], label="pact-broker version").strip()
    require(output == match.group(1), f"pact-cli has pact_broker-client {output}; the catalog says {match.group(1)}")
    ok(f"pact_broker-client {output} — the version app/pact_broker_compat.py tracks")


def environment_uuid(config: Config) -> str:
    """The UUID of the suite's environment, read the way ``record-deployment`` reads it."""
    status, document = broker_call(config, "GET", "/environments")
    require(status == 200, f"GET /environments: {status}")
    for environment in document.get("_embedded", {}).get("environments", []):
        if environment.get("name") == ENVIRONMENT:
            return environment["uuid"]
    raise ConformanceError(f"environment {ENVIRONMENT} is not listed")


def run_cli_suite(config: Config) -> None:
    """The ``pact-broker`` CLI flow, with golden transcripts of what clients read."""
    step("Index")
    index = golden_http(config, "index", "GET", "")
    require("pb:publish-contracts" in index["_links"], "the index has no pb:publish-contracts")

    step("pact-broker create-environment / list-environments")
    pact_broker(config, "create-environment", "--name", ENVIRONMENT, "--display-name", "Production", "--production")
    pact_broker(config, "list-environments", golden="list-environments")

    step("pact-broker publish (consumer 1.0.0 on main)")
    pact_broker(
        config,
        "publish",
        "/pacts/v1",
        "--consumer-app-version",
        "1.0.0",
        "--branch",
        "main",
        "--build-url",
        "https://ci.example.com/web/1",
        golden="publish",
    )
    golden_http(config, "pacticipant", "GET", f"/pacticipants/{CONSUMER}")
    golden_http(config, "pacticipant-version", "GET", f"/pacticipants/{CONSUMER}/versions/1.0.0")
    golden_http(config, "latest-pact", "GET", f"/pacts/provider/{PROVIDER}/consumer/{CONSUMER}/latest")
    golden_http(
        config,
        "for-verification",
        "POST",
        f"/pacts/provider/{PROVIDER}/for-verification",
        {
            "consumerVersionSelectors": [{"mainBranch": True}, {"deployedOrReleased": True}],
            "providerVersionBranch": "main",
            "includePendingStatus": True,
        },
    )

    step("pact-provider-verifier (provider 1.0.0 on main, publishing results)")
    docker(
        [
            PACT_CLI_IMAGE,
            "pact-provider-verifier",
            "--pact-broker-base-url",
            config.broker_url,
            "--broker-token",
            config.api_key,
            "--provider",
            PROVIDER,
            "--provider-base-url",
            config.provider_url,
            "--provider-states-setup-url",
            f"{config.provider_url}/_pact/provider-states",
            "--provider-app-version",
            "1.0.0",
            "--provider-version-branch",
            "main",
            "--consumer-version-selector",
            '{"mainBranch": true}',
            "--enable-pending",
            "--publish-verification-results",
        ],
        label="pact-provider-verifier",
    )
    ok("verified and published")
    status, pact = broker_call(config, "GET", f"/pacts/provider/{PROVIDER}/consumer/{CONSUMER}/latest")
    require(status == 200, f"latest pact: {status}")
    sha = pact["_links"]["pb:pact-version"]["href"].rstrip("/").rsplit("/", 1)[-1]
    golden_http(
        config,
        "verification-result",
        "GET",
        f"/pacts/provider/{PROVIDER}/consumer/{CONSUMER}/pact-version/{sha}/verification-results/latest",
    )

    step("pact-broker record-deployment + can-i-deploy")
    pact_broker(
        config, "record-deployment", "--pacticipant", PROVIDER, "--version", "1.0.0", "--environment", ENVIRONMENT
    )
    pact_broker(
        config,
        "can-i-deploy",
        "--pacticipant",
        CONSUMER,
        "--version",
        "1.0.0",
        "--to-environment",
        ENVIRONMENT,
        golden="can-i-deploy-yes",
    )
    golden_http(
        config,
        "matrix",
        "GET",
        f"/matrix?q[][pacticipant]={CONSUMER}&q[][version]=1.0.0&latestby=cvp&environment={ENVIRONMENT}",
    )
    golden_http(
        config,
        "can-i-deploy",
        "GET",
        f"/can-i-deploy?pacticipant={CONSUMER}&version=1.0.0&environment={ENVIRONMENT}",
    )

    step("An unverified consumer version cannot be deployed")
    pact_broker(config, "publish", "/pacts/v2", "--consumer-app-version", "1.1.0", "--branch", "feat/total")
    pact_broker(
        config,
        "can-i-deploy",
        "--pacticipant",
        CONSUMER,
        "--version",
        "1.1.0",
        "--to-environment",
        ENVIRONMENT,
        expect=1,
        golden="can-i-deploy-no",
    )

    step("Tags, releases, undeployment, describe-environment")
    pact_broker(config, "create-version-tag", "--pacticipant", CONSUMER, "--version", "1.0.0", "--tag", "prod")
    pact_broker(
        config, "record-deployment", "--pacticipant", CONSUMER, "--version", "1.0.0", "--environment", ENVIRONMENT
    )
    uuid = environment_uuid(config)
    golden_http(config, "currently-deployed", "GET", f"/environments/{uuid}/deployed-versions/currently-deployed")
    pact_broker(config, "record-undeployment", "--pacticipant", CONSUMER, "--environment", ENVIRONMENT)
    pact_broker(config, "record-release", "--pacticipant", PROVIDER, "--version", "1.0.0", "--environment", ENVIRONMENT)
    pact_broker(
        config, "record-support-ended", "--pacticipant", PROVIDER, "--version", "1.0.0", "--environment", ENVIRONMENT
    )
    pact_broker(config, "describe-environment", "--uuid", uuid, golden="describe-environment")

    step("pact-broker create-webhook / create-or-update-webhook")
    # `create-webhook` posts to the index's pb:webhooks; `create-or-update-webhook --uuid` puts to
    # pb:webhook. The Authorization header is a secret: it must read back redacted.
    webhook = (WEBHOOK_URL, "--request", "POST", "--header", "Authorization: Bearer conformance-token")
    pact_broker(
        config,
        "create-webhook",
        *webhook,
        "--contract-content-changed",
        "--description",
        "conformance",
        golden="create-webhook",
    )
    declared = (
        "create-or-update-webhook",
        *webhook,
        "--uuid",
        WEBHOOK_UUID,
        "--provider",
        PROVIDER,
        "--contract-requiring-verification-published",
        "--data",
        '{"pactUrl": "${pactbroker.pactUrl}", "providerVersion": "${pactbroker.providerVersionNumber}"}',
        "--description",
        "conformance declared",
    )
    created = pact_broker(config, *declared)
    require("created" in created, f"create-or-update-webhook did not create the webhook: {created}")
    updated = pact_broker(config, *declared)
    require("updated" in updated, f"create-or-update-webhook did not update the webhook: {updated}")
    document = golden_http(config, "webhook", "GET", f"/webhooks/{WEBHOOK_UUID}")
    require(
        document["request"]["headers"]["Authorization"] == "**********",
        f"the webhook's Authorization header is not redacted: {document['request']}",
    )
    # Remove both again, so the pacts the other clients publish do not send anything to WEBHOOK_URL.
    status, listing = broker_call(config, "GET", "/webhooks")
    require(status == 200, f"GET /webhooks: {status}")
    links = listing["_links"]["pb:webhooks"]
    require(len(links) == 2, f"expected the two webhooks of this step, got {links}")
    for link in links:
        deleted, _ = broker_call(config, "DELETE", link["href"][len(config.broker_url) :])
        require(deleted == 204, f"DELETE {link['href']}: {deleted}")
    ok("both webhooks created, read back redacted and deleted")

    step("Labels and a version delete (PFX-1.11)")
    # Labels in the Pact Broker's shape; a delete is soft in Apiome, but answers as the broker does.
    golden_http(config, "label", "PUT", f"/pacticipants/{CONSUMER}/labels/team-web", expect=201)
    golden_http(config, "labels", "GET", "/labels")
    golden_http(config, "pacticipants-with-label", "GET", "/pacticipants/label/team-web")
    deleted, _ = broker_call(config, "DELETE", f"/pacticipants/{CONSUMER}/labels/team-web")
    require(deleted == 204, f"DELETE label: {deleted}")
    recorded, _ = broker_call(config, "PUT", f"/pacticipants/{CONSUMER}/branches/scratch/versions/0.0.1-scratch", {})
    require(recorded in (200, 201), f"PUT scratch version: {recorded}")
    deleted, _ = broker_call(config, "DELETE", f"/pacticipants/{CONSUMER}/versions/0.0.1-scratch")
    require(deleted == 204, f"DELETE version: {deleted}")
    gone, _ = broker_call(config, "GET", f"/pacticipants/{CONSUMER}/versions/0.0.1-scratch")
    require(gone == 404, f"a deleted version is still readable: {gone}")
    ok("label added, listed and removed; a version deleted and gone")

    step("Unsupported endpoints: no index relation for the CLI, a documented 501 by URL")
    # The CLI reaches every resource through an index relation, and the index only advertises
    # what Apiome serves — so a command for a missing feature stops, saying the broker lacks it,
    # before it sends a request. A client that builds the URL itself gets the 501.
    output = pact_broker(
        config, "delete-branch", "--branch", "main", "--pacticipant", CONSUMER, expect=1, golden="unsupported"
    )
    require(
        "does not support deleting branches" in output,
        f"delete-branch did not stop on the missing relation: {output}",
    )
    golden_http(
        config, "not-implemented", "GET", f"/pacts/provider/{PROVIDER}/consumer/{CONSUMER}/latest/badge", expect=501
    )
    golden_http(config, "not-implemented-partial", "PUT", f"/pacticipants/{CONSUMER}", {"mainBranch": "main"}, expect=501)
    golden_http(config, "not-implemented-unknown", "GET", "/no/such/resource", expect=501)


def run_pact_js_suite(config: Config, work: Path) -> None:
    """pact-js: a PactV3 consumer test, CLI publish, the Rust-core ``Verifier`` publishing results."""
    step("pact-js consumer test (PactV3) → pact file")
    project = work / "pact-js"
    shutil.copytree(HERE / "pact-js", project)
    user = f"{os.getuid()}:{os.getgid()}"
    common = ["-u", user, "-e", "HOME=/tmp", "-v", f"{project}:/work", "-w", "/work", NODE_IMAGE]
    docker([*common, "npm", "install", "--no-audit", "--no-fund"], label="npm install")
    docker([*common, "node", "consumer.mjs"], label="pact-js consumer")
    ok("pact written")
    pact_broker_dir(config, project / "pacts", JS_CONSUMER)

    step("pact-js Verifier (provider 1.0.0, publishing results)")
    docker(
        [
            "-e",
            f"PACT_BROKER_BASE_URL={config.broker_url}",
            "-e",
            f"PACT_BROKER_TOKEN={config.api_key}",
            "-e",
            f"PROVIDER_BASE_URL={config.provider_url}",
            *common,
            "node",
            "provider.mjs",
        ],
        label="pact-js verifier",
    )
    ok("verified and published")
    deploy_and_check(config, JS_CONSUMER, JS_PROVIDER)


def run_pact_jvm_suite(config: Config, work: Path) -> None:
    """pact-jvm: a JUnit 5 consumer test, Gradle ``pactPublish``, a JUnit 5 provider test."""
    step("pact-jvm consumer test → pactPublish → provider verification")
    project = work / "pact-jvm"
    shutil.copytree(HERE / "pact-jvm", project)
    docker(
        [
            "-u",
            f"{os.getuid()}:{os.getgid()}",
            "-e",
            "GRADLE_USER_HOME=/work/.gradle-home",
            "-e",
            f"PACT_BROKER_BASE_URL={config.broker_url}",
            "-e",
            f"PACT_BROKER_TOKEN={config.api_key}",
            "-e",
            f"PROVIDER_PORT={config.provider_port}",
            "-v",
            f"{project}:/work",
            "-w",
            "/work",
            GRADLE_IMAGE,
            "gradle",
            "--no-daemon",
            "--console=plain",
            "conformance",
        ],
        label="pact-jvm",
    )
    ok("published with pactPublish, verified and published results")
    deploy_and_check(config, JVM_CONSUMER, JVM_PROVIDER)


def pact_broker_dir(config: Config, pacts: Path, consumer: str) -> None:
    """Publish a client's pact directory with the CLI (pact-js has no publisher of its own)."""
    docker(
        [
            "-v",
            f"{pacts}:/client-pacts:ro",
            "-e",
            f"PACT_BROKER_BASE_URL={config.broker_url}",
            "-e",
            f"PACT_BROKER_TOKEN={config.api_key}",
            PACT_CLI_IMAGE,
            "pact-broker",
            "publish",
            "/client-pacts",
            "--consumer-app-version",
            "1.0.0",
            "--branch",
            "main",
        ],
        label=f"publish {consumer}",
    )
    ok(f"{consumer} 1.0.0 published")


def deploy_and_check(config: Config, consumer: str, provider: str) -> None:
    """Record the provider in the environment, then can-i-deploy the consumer must say yes."""
    pact_broker(
        config, "record-deployment", "--pacticipant", provider, "--version", "1.0.0", "--environment", ENVIRONMENT
    )
    pact_broker(
        config, "can-i-deploy", "--pacticipant", consumer, "--version", "1.0.0", "--to-environment", ENVIRONMENT
    )


def parse_args(argv: Optional[Sequence[str]] = None) -> Config:
    """Read the command line (each option falls back to an ``APIOME_*`` environment variable)."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rest-url", default=os.environ.get("APIOME_REST_URL", "http://localhost:8000"))
    parser.add_argument("--tenant", default=os.environ.get("APIOME_TENANT", "acme-corp"))
    parser.add_argument(
        "--api-key",
        default=os.environ.get("APIOME_API_KEY", "sk_devseed00000000000000000000000000000000000000000000000000000000"),
    )
    parser.add_argument("--clients", default=os.environ.get("PACT_CONFORMANCE_CLIENTS", "cli,pact-js,pact-jvm"))
    parser.add_argument("--provider-port", type=int, default=int(os.environ.get("PACT_PROVIDER_PORT", "8790")))
    parser.add_argument("--update-golden", action="store_true", help="Rewrite golden/ instead of comparing.")
    args = parser.parse_args(argv)
    clients = [name.strip() for name in args.clients.split(",") if name.strip()]
    unknown = set(clients) - {"cli", "pact-js", "pact-jvm"}
    if unknown:
        parser.error(f"unknown client(s): {', '.join(sorted(unknown))}")
    if "cli" not in clients:
        parser.error("the cli suite creates the environment the others deploy to; keep it in --clients")
    return Config(
        rest_url=args.rest_url.rstrip("/"),
        tenant=args.tenant,
        api_key=args.api_key,
        clients=clients,
        update_golden=args.update_golden,
        provider_port=args.provider_port,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the suite; return the process exit code."""
    config = parse_args(argv)
    print(f"Broker: {config.broker_url}   clients: {', '.join(config.clients)}")
    provider = start_provider(config.provider_port)
    try:
        with tempfile.TemporaryDirectory(prefix="pact-conformance-") as tmp:
            step("Tracked client version")
            check_client_version()
            run_cli_suite(config)
            if "pact-js" in config.clients:
                run_pact_js_suite(config, Path(tmp))
            if "pact-jvm" in config.clients:
                run_pact_jvm_suite(config, Path(tmp))
    except ConformanceError as exc:
        print(f"\n✗ {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        provider.shutdown()
    if config.mismatches:
        print(
            f"\n✗ {len(config.mismatches)} golden transcript(s) differ: {', '.join(config.mismatches)}. "
            "If the change is intended, rerun with --update-golden and commit golden/.",
            file=sys.stderr,
        )
        return 1
    print("\n✓ Pact Broker conformance suite green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
