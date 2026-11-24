"""Pact badges — PFX-1.10 (#6923): the status rules, the drawings and the public routes."""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.pact_badge import (
    FAILING,
    UNKNOWN,
    VERIFIED,
    badge_svg,
    combine_statuses,
    pact_status,
    shields_endpoint,
)

client = TestClient(app)
_STORE = "app.pact_badge_routes"
_PROJECT = {"id": "proj-1", "tenant_id": "ten-1"}
_BASE = "/v1/browse/tenants/acme/projects/ledger/pact-badges"


@pytest.mark.parametrize(("success", "expected"), [(True, VERIFIED), (False, FAILING), (None, UNKNOWN)])
def test_a_pact_takes_the_state_of_its_newest_result(success: Any, expected: str) -> None:
    assert pact_status(success) == expected


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], UNKNOWN),
        ([VERIFIED], VERIFIED),
        ([VERIFIED, VERIFIED], VERIFIED),
        ([VERIFIED, UNKNOWN], UNKNOWN),
        ([UNKNOWN], UNKNOWN),
        ([VERIFIED, FAILING, UNKNOWN], FAILING),
    ],
)
def test_a_pacticipant_is_only_verified_when_every_pact_is(statuses: List[str], expected: str) -> None:
    assert combine_statuses(statuses) == expected


def test_the_svg_names_the_label_and_status() -> None:
    svg = badge_svg("pact: ledger-api", VERIFIED)
    assert svg.startswith("<svg") and 'aria-label="pact: ledger-api: verified"' in svg
    assert "#2ea44f" in svg and ">verified</text>" in svg


def test_the_svg_escapes_the_label_and_drops_control_characters() -> None:
    svg = badge_svg('<script>"x"</script>\x00\n', FAILING)
    assert "<script>" not in svg and "\x00" not in svg and "&lt;script&gt;" in svg


def test_a_long_label_is_cut_and_an_unknown_status_is_drawn_unknown() -> None:
    svg = badge_svg("a" * 500, "bogus")
    assert "…" in svg and ">unknown</text>" in svg


def test_the_shields_document_follows_the_endpoint_schema() -> None:
    assert shields_endpoint("pact: x", FAILING) == {
        "schemaVersion": 1,
        "label": "pact: x",
        "message": "failing",
        "color": "red",
    }
    assert shields_endpoint("p", "bogus")["message"] == UNKNOWN


def _patched(**stores: Any):
    """Patch the routes' store calls (``find_public_project`` defaults to the public project)."""
    stores.setdefault("find_public_project", _PROJECT)
    patches = [patch(f"{_STORE}.{name}", return_value=value) for name, value in stores.items()]

    class _All:
        def __enter__(self) -> None:
            for item in patches:
                item.start()

        def __exit__(self, *_: Any) -> None:
            for item in patches:
                item.stop()

    return _All()


def test_a_pacticipant_badge_is_an_svg_that_can_be_cached() -> None:
    with _patched(pacticipant_badge={"slug": "ledger-api", "name": "Ledger", "status": VERIFIED, "pacts": 2}):
        response = client.get(f"{_BASE}/pacticipants/ledger-api/badge.svg")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert "max-age=300" in response.headers["cache-control"]
    assert "verified" in response.text


def test_a_pacticipant_shields_document() -> None:
    with _patched(pacticipant_badge={"slug": "ledger-api", "name": "Ledger", "status": FAILING, "pacts": 1}):
        response = client.get(f"{_BASE}/pacticipants/ledger-api/shields.json")
    assert response.json() == {"schemaVersion": 1, "label": "pact: ledger-api", "message": "failing", "color": "red"}


def test_a_pact_badge_and_shields() -> None:
    found: Dict[str, Any] = {"provider_slug": "ledger-api", "consumer_slug": "web", "status": UNKNOWN}
    with _patched(pair_badge=found):
        svg = client.get(f"{_BASE}/pacts/provider/ledger-api/consumer/web/badge.svg")
        shields = client.get(f"{_BASE}/pacts/provider/ledger-api/consumer/web/shields.json")
    assert svg.status_code == 200 and "unknown" in svg.text
    assert shields.json()["message"] == UNKNOWN and shields.json()["color"] == "lightgrey"


@pytest.mark.parametrize(
    "path",
    [
        "/pacticipants/x/badge.svg",
        "/pacticipants/x/shields.json",
        "/pacts/provider/p/consumer/c/badge.svg",
        "/pacts/provider/p/consumer/c/shields.json",
        "",
    ],
)
def test_a_private_project_is_a_uniform_404(path: str) -> None:
    with _patched(find_public_project=None):
        response = client.get(_BASE + path)
    assert response.status_code == 404 and response.json()["detail"] == "No pact badge found."


@pytest.mark.parametrize(
    "path",
    ["/pacticipants/x/badge.svg", "/pacticipants/x/shields.json"],
)
def test_an_unbound_pacticipant_is_the_same_404(path: str) -> None:
    with _patched(pacticipant_badge=None):
        response = client.get(_BASE + path)
    assert response.status_code == 404 and response.json()["detail"] == "No pact badge found."


def test_an_unbound_pair_is_the_same_404() -> None:
    with _patched(pair_badge=None):
        assert client.get(f"{_BASE}/pacts/provider/p/consumer/c/badge.svg").status_code == 404
        assert client.get(f"{_BASE}/pacts/provider/p/consumer/c/shields.json").status_code == 404


def test_the_project_status_lists_pacticipants_with_badge_urls() -> None:
    item = {"slug": "ledger-api", "name": "Ledger", "status": VERIFIED, "pacts": 1}
    with _patched(project_statuses=[item]):
        body = client.get(_BASE).json()
    [entry] = body["pacticipants"]
    assert entry["status"] == VERIFIED
    assert entry["badge_url"].endswith(f"{_BASE}/pacticipants/ledger-api/badge.svg")
    assert entry["shields_url"].endswith("/pacticipants/ledger-api/shields.json")


def test_a_project_with_nothing_bound_has_an_empty_list() -> None:
    with _patched(project_statuses=[]):
        assert client.get(_BASE).json()["pacticipants"] == []
