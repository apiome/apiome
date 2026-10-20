"""Tests for ``apiome import a2a`` and its well-known discovery (MFI-18.1, #3974).

The ``a2a`` verb rides the registry-driven adapter import (MFI-1.4) like any registered
source, and adds ``--discover AGENT_URL``, which resolves the agent's Agent Card from
``/.well-known/agent-card.json`` (falling back to ``/.well-known/agent.json``) before
importing it. The REST service is mocked; the card bytes must reach it verbatim under
``source_kind: a2a``.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from apiome_cli.import_.a2a import discover_agent_card_url, well_known_agent_card_urls
from apiome_cli.main import app
from helpers import strip_ansi

runner = CliRunner()

_CARD_PATH = (
    Path(__file__).resolve().parents[2]
    / "apiome-ui/examples/a2a/02-typical-travel-concierge.json"
)
_CARD_BYTES = _CARD_PATH.read_bytes()

_AGENT = "https://travel.agents.example.com"
_CARD_URL = f"{_AGENT}/.well-known/agent-card.json"
_LEGACY_URL = f"{_AGENT}/.well-known/agent.json"

_SOURCES_URL = "http://localhost:8000/v1/import/sources"
_IMPORT_URL = "http://localhost:8000/v1/tenants/acme-corp/imports"
_JOB_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_URL = f"http://localhost:8000/v1/tenants/acme-corp/imports/{_JOB_ID}"

_A2A_SOURCE = {
    "key": "a2a",
    "label": "A2A Agent Card",
    "description": "Import an A2A (Agent2Agent) Agent Card.",
    "icon": "bot-message-square",
    "paradigm": "agent",
    "input_kinds": ["file", "url", "paste", "discovery", "fileset"],
    "supports_live_discovery": True,
    "formats": ["a2a"],
}

_PREVIEW_SUMMARY = {
    "source": "a2a",
    "paradigm": "agent",
    "format": "a2a",
    "fingerprint": "sha256:a2a123",
    "counts": {"services": 1, "operations": 4, "types": 0, "channels": 0},
    "lint": {
        "score": 100,
        "grade": "A",
        "report_fingerprint": "a2alintfp",
        "findings": 0,
        "severity_counts": {},
    },
    "dry_run": False,
    "incremental_mode": False,
    "persisted": False,
}


@pytest.fixture(autouse=True)
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 import commands require an API key and tenant scope."""
    monkeypatch.setenv("APIOME_API_KEY", "test-import-key")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_sources(httpx_mock: object) -> None:
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_SOURCES_URL, method="GET", json={"sources": [_A2A_SOURCE]}
    )


def _mock_import_completed(httpx_mock: object) -> None:
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_IMPORT_URL,
        method="POST",
        status_code=202,
        json={"job_id": _JOB_ID, "state": "pending"},
    )
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_JOB_URL,
        method="GET",
        json={"state": "completed", "job_id": _JOB_ID, "summary": _PREVIEW_SUMMARY},
    )


def _post_body(httpx_mock: object) -> dict:
    for request in httpx_mock.get_requests():  # type: ignore[attr-defined]
        if request.method == "POST" and str(request.url) == _IMPORT_URL:
            return json.loads(request.content.decode("utf-8"))
    raise AssertionError("no spec-import POST recorded")


# ---------------------------------------------------------------------------
# well_known_agent_card_urls / discover_agent_card_url
# ---------------------------------------------------------------------------


def test_well_known_urls_drop_the_path_and_try_current_then_legacy() -> None:
    assert well_known_agent_card_urls(f"{_AGENT}/a2a/v1?x=1") == [_CARD_URL, _LEGACY_URL]


def test_a_direct_card_url_is_used_as_is() -> None:
    url = f"{_AGENT}/cards/agent-card.json"
    assert well_known_agent_card_urls(url) == [url]


@pytest.mark.parametrize("bad", ["", "ftp://agent.example.com", "https://", "agent.example.com"])
def test_bad_agent_urls_are_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        well_known_agent_card_urls(bad)


def _client(routes: dict) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        status = routes.get(str(request.url), 404)
        return httpx.Response(status, text="{}")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_discover_prefers_the_current_path() -> None:
    with _client({_CARD_URL: 200, _LEGACY_URL: 200}) as client:
        assert discover_agent_card_url(_AGENT, client=client) == _CARD_URL


def test_discover_falls_back_to_the_legacy_path() -> None:
    with _client({_LEGACY_URL: 200}) as client:
        assert discover_agent_card_url(_AGENT, client=client) == _LEGACY_URL


def test_discover_stops_at_a_non_404_error() -> None:
    with (
        _client({_CARD_URL: 503, _LEGACY_URL: 200}) as client,
        pytest.raises(OSError, match="HTTP 503"),
    ):
        discover_agent_card_url(_AGENT, client=client)


def test_discover_reports_when_no_card_exists() -> None:
    with _client({}) as client, pytest.raises(OSError, match="No Agent Card found"):
        discover_agent_card_url(_AGENT, client=client)


# ---------------------------------------------------------------------------
# apiome import a2a
# ---------------------------------------------------------------------------


def test_import_a2a_file_dispatches_to_the_a2a_adapter(httpx_mock: object) -> None:
    _mock_sources(httpx_mock)
    _mock_import_completed(httpx_mock)

    result = runner.invoke(app, ["import", "a2a", str(_CARD_PATH)])
    assert result.exit_code == 0, result.output

    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "a2a"
    assert base64.b64decode(body["document_base64"]) == _CARD_BYTES
    text = strip_ansi(result.output)
    assert "Paradigm: agent" in text
    assert "Lint score: 100 (A)" in text


def test_import_a2a_discover_fetches_the_well_known_card(httpx_mock: object) -> None:
    _mock_sources(httpx_mock)
    # Probe during discovery, then the import's own fetch of the resolved URL.
    httpx_mock.add_response(url=_CARD_URL, method="GET", content=_CARD_BYTES)  # type: ignore[attr-defined]
    httpx_mock.add_response(url=_CARD_URL, method="GET", content=_CARD_BYTES)  # type: ignore[attr-defined]
    _mock_import_completed(httpx_mock)

    result = runner.invoke(app, ["import", "a2a", "--discover", _AGENT, "--dry-run"])
    assert result.exit_code == 0, result.output

    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "a2a"
    assert body["metadata"]["options"]["dry_run"] is True
    assert base64.b64decode(body["document_base64"]) == _CARD_BYTES
    assert f"Discovered Agent Card at {_CARD_URL}" in strip_ansi(result.output)


def test_import_a2a_discover_falls_back_to_agent_json(httpx_mock: object) -> None:
    _mock_sources(httpx_mock)
    httpx_mock.add_response(url=_CARD_URL, method="GET", status_code=404)  # type: ignore[attr-defined]
    httpx_mock.add_response(url=_LEGACY_URL, method="GET", content=_CARD_BYTES)  # type: ignore[attr-defined]
    httpx_mock.add_response(url=_LEGACY_URL, method="GET", content=_CARD_BYTES)  # type: ignore[attr-defined]
    _mock_import_completed(httpx_mock)

    result = runner.invoke(app, ["import", "a2a", "--discover", _AGENT])
    assert result.exit_code == 0, result.output
    assert _post_body(httpx_mock)["metadata"]["source_kind"] == "a2a"


def test_import_a2a_discover_with_no_card_fails(httpx_mock: object) -> None:
    httpx_mock.add_response(url=_CARD_URL, method="GET", status_code=404)  # type: ignore[attr-defined]
    httpx_mock.add_response(url=_LEGACY_URL, method="GET", status_code=404)  # type: ignore[attr-defined]

    result = runner.invoke(app, ["import", "a2a", "--discover", _AGENT])
    assert result.exit_code != 0
    assert "No Agent Card found" in strip_ansi(result.output)


def test_import_a2a_rejects_discover_with_another_input() -> None:
    result = runner.invoke(app, ["import", "a2a", str(_CARD_PATH), "--discover", _AGENT])
    assert result.exit_code == 2
    assert "Provide only one input" in strip_ansi(result.output)


def test_import_a2a_rejects_a_bad_agent_url() -> None:
    result = runner.invoke(app, ["import", "a2a", "--discover", "agent.example.com"])
    assert result.exit_code == 2
    assert "http or https" in strip_ansi(result.output)
