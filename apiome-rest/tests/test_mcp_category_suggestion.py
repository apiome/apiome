"""Tests for MCP auto-categorization suggestions (V2-MCP-23.4 / MCAT-9.4, #3694).

Covers the pure keyword heuristic (:mod:`app.mcp_category_suggestion`), the gated Claude step
(:mod:`app.mcp_category_llm`, with ``urlopen`` faked) and both suggestion routes (``db`` mocked). The
acceptance criterion — a plausible category for fixture servers, never applied without confirmation —
is pinned by the fixture-server test and the "never writes" route tests.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest
from fastapi.testclient import TestClient

from app import mcp_category_llm
from app.auth import validate_authentication
from app.main import app
from app.mcp_category_suggestion import (
    CATEGORY_KEYWORDS,
    MIN_SUGGESTION_SCORE,
    builtin_vocabulary,
    category_keywords,
    suggest_categories,
    tokenize,
    tools_from_capability_items,
)
from app.mcp_categorization import BUILTIN_CATEGORIES

client = TestClient(app)

_TENANT = "11111111-1111-1111-1111-111111111111"
_JWT = {"auth_type": "jwt", "tenant_id": _TENANT, "user_id": "22222222-2222-2222-2222-222222222222"}
_ENDPOINT_ID = "33333333-3333-3333-3333-333333333333"
_VERSION_ID = "44444444-4444-4444-4444-444444444444"

_FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "mcp_category_suggestion" / "servers.json").read_text()
)["servers"]


@pytest.fixture(autouse=True)
def _default_auth():
    """Authenticate every request as a JWT for ``_TENANT``."""
    app.dependency_overrides[validate_authentication] = lambda: _JWT
    yield
    app.dependency_overrides.pop(validate_authentication, None)


# --- Tokenizing & vocabulary ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("createPullRequest", ["create", "pull", "request"]),
        ("create_pull_request", ["create", "pull", "request"]),
        ("create-pull-request", ["create", "pull", "request"]),
        ("Run SQL queries", ["run", "sql", "query"]),
        ("listFiles", ["list", "file"]),
        ("HTTPServer", ["http", "server"]),
        ("status class", ["status", "class"]),
        (None, []),
        ("", []),
    ],
)
def test_tokenize(text, expected):
    assert tokenize(text) == expected


def test_lexicon_covers_every_builtin_but_other():
    slugs = {slug for slug, _ in BUILTIN_CATEGORIES}
    assert set(CATEGORY_KEYWORDS) == slugs - {"other"}


def test_lexicon_keywords_are_single_words():
    for slug, words in CATEGORY_KEYWORDS.items():
        for word in words:
            assert len(tokenize(word)) == 1, (slug, word)


@pytest.mark.parametrize("name, expected", [("list_postgres_tables", "databases"), ("get_kubernetes_pods", "cloud-infrastructure")])
def test_lexicon_words_ending_in_s_still_match(name, expected):
    assert suggest_categories({}, [{"name": name}])[0].slug == expected


def test_tenant_category_keywords_come_from_slug_and_label():
    assert category_keywords({"slug": "weather", "label": "Weather & climate"}) == ("weather", "climate")


def test_builtin_keywords_ignore_label_words():
    keywords = category_keywords({"slug": "databases", "label": "Databases", "builtin": True})
    assert "sql" in keywords and "postgre" in keywords and "database" in keywords


def test_tools_from_capability_items_keeps_tools_only():
    items = [
        {"item_type": "tool", "name": "a"},
        {"item_type": "resource", "name": "b"},
        {"item_type": "prompt", "name": "c"},
    ]
    assert [t["name"] for t in tools_from_capability_items(items)] == ["a"]


# --- Heuristic ------------------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", _FIXTURES, ids=[f["server"]["name"] for f in _FIXTURES])
def test_fixture_servers_get_a_plausible_category(fixture):
    suggestions = suggest_categories(fixture["server"], fixture["tools"])
    assert suggestions, "expected at least one suggestion"
    assert suggestions[0].slug == fixture["expected"]
    assert suggestions[0].matched_keywords
    assert 0 < suggestions[0].confidence <= 1


def test_no_signal_means_no_suggestion():
    tools = [{"name": "frobnicate", "description": "Does the thing."}]
    assert suggest_categories({"name": "Widget"}, tools) == []


def test_other_is_never_suggested():
    vocab = [{"slug": "other", "label": "Other sql database", "builtin": False}]
    assert suggest_categories({}, [{"name": "run_sql"}], vocab) == []


def test_a_single_description_hit_is_below_the_threshold():
    tools = [{"name": "frobnicate", "description": "Uses sql."}]
    assert MIN_SUGGESTION_SCORE > 1
    assert suggest_categories({}, tools) == []


def test_tool_names_outweigh_descriptions():
    tools = [{"name": "send_email", "description": "Attach a file to the outgoing mail."}]
    top = suggest_categories({}, tools)[0]
    assert top.slug == "communication"


def test_each_word_counts_once_per_field():
    tools = [{"name": "file_file_file_file"}, {"name": "send_email"}]
    scores = {s.slug: s.score for s in suggest_categories({}, tools)}
    assert scores["files-storage"] == scores["communication"]


def test_tenant_categories_are_matched_and_ranked():
    vocab = builtin_vocabulary() + [{"slug": "weather", "label": "Weather", "builtin": False}]
    tools = [
        {"name": "get_weather", "description": "Current weather for a city."},
        {"name": "get_forecast", "description": "Weather forecast for the week."},
    ]
    suggestions = suggest_categories({"name": "Weather"}, tools, vocab)
    assert suggestions[0].slug == "weather"
    assert suggestions[0].builtin is False


def test_ties_break_in_lookup_order():
    vocab = [
        {"slug": "b-cat", "label": "Alpha"},
        {"slug": "a-cat", "label": "Alpha"},
    ]
    suggestions = suggest_categories({}, [{"name": "alpha_tool"}], vocab)
    assert [s.slug for s in suggestions] == ["b-cat", "a-cat"]


def test_limit_and_confidence_bounds():
    tools = [
        {"name": "run_sql"},
        {"name": "send_email"},
        {"name": "read_file"},
        {"name": "web_search"},
    ]
    suggestions = suggest_categories({}, tools, limit=2)
    assert len(suggestions) == 2
    assert sum(s.confidence for s in suggest_categories({}, tools, limit=10)) <= 1.0001


def test_strong_single_category_is_confident():
    fixture = next(f for f in _FIXTURES if f["expected"] == "databases")
    top = suggest_categories(fixture["server"], fixture["tools"])[0]
    assert top.confidence >= 0.5


# --- Claude step ----------------------------------------------------------------------------------


class _FakeResponse:
    """A minimal ``urlopen`` context manager returning a canned body."""

    def __init__(self, body, status=200):
        self._body = body if isinstance(body, str) else json.dumps(body)
        self.status = status
        self.reason = "OK" if status == 200 else "Error"

    def read(self):
        return self._body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _answer(category, reason="Its tools run SQL.", **extra):
    body = {
        "model": "claude-opus-5-5",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": json.dumps({"category": category, "reason": reason})}],
    }
    body.update(extra)
    return body


@pytest.fixture
def _llm_on(monkeypatch):
    """Enable the Claude step with a fake key."""
    monkeypatch.setattr(mcp_category_llm.settings, "mcp_ai_categorization_enabled", True)
    monkeypatch.setattr(mcp_category_llm.settings, "anthropic_api_key", "sk-test")
    monkeypatch.setattr(mcp_category_llm.settings, "mcp_ai_categorization_model", "claude-opus-5-5")


def test_claude_off_by_default_never_calls(monkeypatch):
    monkeypatch.setattr(mcp_category_llm.settings, "mcp_ai_categorization_enabled", False)
    monkeypatch.setattr(mcp_category_llm.settings, "anthropic_api_key", "sk-test")
    with patch.object(mcp_category_llm, "urlopen") as mock_open:
        assert mcp_category_llm.suggest_category_with_claude({}, [], builtin_vocabulary()) is None
    mock_open.assert_not_called()


def test_claude_without_key_never_calls(monkeypatch):
    monkeypatch.setattr(mcp_category_llm.settings, "mcp_ai_categorization_enabled", True)
    monkeypatch.setattr(mcp_category_llm.settings, "anthropic_api_key", None)
    with patch.object(mcp_category_llm, "urlopen") as mock_open:
        assert mcp_category_llm.suggest_category_with_claude({}, [], builtin_vocabulary()) is None
    mock_open.assert_not_called()


def test_claude_request_constrains_to_vocabulary(_llm_on):
    captured = {}

    def _fake(request, timeout):
        captured["body"] = json.loads(request.data)
        captured["headers"] = {k.lower(): v for k, v in request.header_items()}
        return _FakeResponse(_answer("databases"))

    with patch.object(mcp_category_llm, "urlopen", _fake):
        pick = mcp_category_llm.suggest_category_with_claude(
            {"name": "Postgres"}, [{"name": "run_query"}], builtin_vocabulary()
        )

    assert pick is not None and pick.slug == "databases" and pick.model == "claude-opus-5-5"
    body = captured["body"]
    assert body["model"] == "claude-opus-5-5"
    schema = body["output_config"]["format"]["schema"]
    assert schema["properties"]["category"]["enum"] == [s for s, _ in BUILTIN_CATEGORIES]
    assert schema["additionalProperties"] is False
    assert "thinking" not in body
    assert body["fallbacks"] == "default"
    assert captured["headers"]["anthropic-beta"] == "server-side-fallback-2026-07-01"
    assert captured["headers"]["x-api-key"] == "sk-test"


def test_claude_fallback_omitted_for_other_models(_llm_on, monkeypatch):
    monkeypatch.setattr(mcp_category_llm.settings, "mcp_ai_categorization_model", "claude-haiku-5-5")
    body = mcp_category_llm.build_request_body({}, [], builtin_vocabulary(), "claude-haiku-5-5")
    assert "fallbacks" not in body


@pytest.mark.parametrize(
    "response",
    [
        _FakeResponse(_answer("made-up")),
        _FakeResponse(_answer("databases", stop_reason="refusal")),
        _FakeResponse({"content": [{"type": "text", "text": "not json"}]}),
        _FakeResponse({"content": []}),
        _FakeResponse("garbage"),
        _FakeResponse(_answer("databases"), status=500),
    ],
)
def test_claude_bad_answers_are_none(_llm_on, response):
    with patch.object(mcp_category_llm, "urlopen", return_value=response):
        assert mcp_category_llm.suggest_category_with_claude({}, [], builtin_vocabulary()) is None


@pytest.mark.parametrize(
    "error", [URLError("down"), HTTPError("u", 429, "Too Many", {}, None), OSError("reset")]
)
def test_claude_transport_errors_are_none(_llm_on, error):
    with patch.object(mcp_category_llm, "urlopen", side_effect=error):
        assert mcp_category_llm.suggest_category_with_claude({}, [], builtin_vocabulary()) is None


def test_claude_empty_vocabulary_never_calls(_llm_on):
    with patch.object(mcp_category_llm, "urlopen") as mock_open:
        assert mcp_category_llm.suggest_category_with_claude({}, [], []) is None
    mock_open.assert_not_called()


def test_prompt_lists_categories_and_bounds_tools():
    tools = [{"name": f"tool_{i}", "description": "x" * 1000} for i in range(70)]
    prompt = mcp_category_llm.build_category_prompt(
        {"name": "Entry", "server_title": "Server"},
        tools,
        [{"slug": "databases", "label": "Databases", "description": "SQL and NoSQL"}],
    )
    assert "- databases: Databases - SQL and NoSQL" in prompt
    assert "Server name: Server" in prompt and "Catalog entry name: Entry" in prompt
    assert "... and 10 more tools" in prompt
    assert "x" * 301 not in prompt


def test_prompt_for_a_server_without_tools():
    prompt = mcp_category_llm.build_category_prompt({}, [], builtin_vocabulary())
    assert "This server exposes no tools." in prompt


# --- Routes ---------------------------------------------------------------------------------------


def _endpoint(category=None, version_id=_VERSION_ID, **extra):
    row = {
        "id": _ENDPOINT_ID,
        "tenant_id": _TENANT,
        "name": "Postgres",
        "category": category,
        "current_version_id": version_id,
    }
    row.update(extra)
    return row


def _wire_db(mdb, endpoint=None, tools=None):
    """Point the mocked ``db`` at one endpoint with the Postgres fixture's tools."""
    fixture = next(f for f in _FIXTURES if f["expected"] == "databases")
    mdb.get_mcp_endpoint.return_value = endpoint or _endpoint()
    mdb.list_mcp_categories.return_value = builtin_vocabulary()
    mdb.get_mcp_endpoint_version.return_value = {
        "id": _VERSION_ID,
        "server_name": "postgres-mcp",
        "server_title": None,
        "instructions": None,
    }
    mdb.get_mcp_capability_items.return_value = [
        {"item_type": "tool", **t} for t in (tools if tools is not None else fixture["tools"])
    ]


def _assert_no_writes(mdb):
    """Suggestion routes must never change the endpoint or its tags."""
    for name in ("update_mcp_endpoint", "replace_mcp_endpoint_tags", "create_mcp_category"):
        getattr(mdb, name).assert_not_called()


def test_suggestion_route_returns_heuristic_pick_without_applying():
    with patch("app.mcp_categorization_routes.db") as mdb:
        _wire_db(mdb)
        res = client.get(f"/v1/mcp/acme/endpoints/{_ENDPOINT_ID}/category-suggestion")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["suggested_category"] == "databases"
    assert body["method"] == "heuristic"
    assert body["applied"] is False
    assert body["current_category"] is None
    assert body["tool_count"] == 3
    assert body["suggestions"][0]["matched_keywords"]
    assert body["llm"] is None
    mdb.get_mcp_endpoint.assert_called_once_with(_TENANT, _ENDPOINT_ID)
    mdb.list_mcp_categories.assert_called_once_with(_TENANT)
    _assert_no_writes(mdb)


def test_suggestion_route_404_for_another_tenant():
    with patch("app.mcp_categorization_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        res = client.get(f"/v1/mcp/acme/endpoints/{uuid.uuid4()}/category-suggestion")
    assert res.status_code == 404


def test_suggestion_route_without_surface_scores_the_name():
    with patch("app.mcp_categorization_routes.db") as mdb:
        _wire_db(mdb, endpoint=_endpoint(version_id=None, name="Slack bridge"))
        res = client.get(f"/v1/mcp/acme/endpoints/{_ENDPOINT_ID}/category-suggestion")
    body = res.json()
    assert body["version_id"] is None and body["tool_count"] == 0
    assert body["suggested_category"] == "communication"
    assert "no discovered surface" in body["detail"]
    mdb.get_mcp_capability_items.assert_not_called()


def test_suggestion_route_no_signal():
    with patch("app.mcp_categorization_routes.db") as mdb:
        _wire_db(mdb, endpoint=_endpoint(name="Widget"), tools=[{"name": "frobnicate"}])
        mdb.get_mcp_endpoint_version.return_value = {"id": _VERSION_ID}
        res = client.get(f"/v1/mcp/acme/endpoints/{_ENDPOINT_ID}/category-suggestion")
    body = res.json()
    assert body["suggested_category"] is None and body["suggestions"] == []
    assert "choose one manually" in body["detail"]


def test_suggestion_route_use_llm_when_disabled_falls_back(monkeypatch):
    monkeypatch.setattr(mcp_category_llm.settings, "mcp_ai_categorization_enabled", False)
    with patch("app.mcp_categorization_routes.db") as mdb, patch(
        "app.mcp_categorization_routes.suggest_category_with_claude"
    ) as claude:
        _wire_db(mdb)
        res = client.get(f"/v1/mcp/acme/endpoints/{_ENDPOINT_ID}/category-suggestion?use_llm=true")
    body = res.json()
    assert body["method"] == "heuristic" and body["suggested_category"] == "databases"
    assert "not enabled" in body["detail"]
    claude.assert_not_called()


def test_suggestion_route_use_llm_pick_wins_but_is_not_applied(_llm_on):
    pick = mcp_category_llm.ClaudeCategorySuggestion(
        slug="data-analytics", rationale="It reports on data.", model="claude-opus-5-5"
    )
    with patch("app.mcp_categorization_routes.db") as mdb, patch(
        "app.mcp_categorization_routes.suggest_category_with_claude", return_value=pick
    ):
        _wire_db(mdb)
        res = client.get(f"/v1/mcp/acme/endpoints/{_ENDPOINT_ID}/category-suggestion?use_llm=true")
    body = res.json()
    assert body["method"] == "llm"
    assert body["suggested_category"] == "data-analytics"
    assert body["llm"] == {
        "slug": "data-analytics",
        "label": "Data & analytics",
        "rationale": "It reports on data.",
        "model": "claude-opus-5-5",
    }
    assert body["suggestions"][0]["slug"] == "databases"
    assert body["applied"] is False and body["ai_categorization_enabled"] is True
    _assert_no_writes(mdb)


def test_suggestion_route_use_llm_failure_keeps_heuristic(_llm_on):
    with patch("app.mcp_categorization_routes.db") as mdb, patch(
        "app.mcp_categorization_routes.suggest_category_with_claude", return_value=None
    ):
        _wire_db(mdb)
        res = client.get(f"/v1/mcp/acme/endpoints/{_ENDPOINT_ID}/category-suggestion?use_llm=true")
    body = res.json()
    assert body["method"] == "heuristic" and body["suggested_category"] == "databases"
    assert "unavailable" in body["detail"]


def test_queue_lists_uncategorized_only_by_default():
    endpoints = [
        _endpoint(id="e1", name="Postgres"),
        _endpoint(id="e2", name="Slack", category="communication"),
        _endpoint(id="e3", name="Files", category="  "),
    ]
    with patch("app.mcp_categorization_routes.db") as mdb:
        _wire_db(mdb)
        mdb.list_mcp_endpoints.return_value = endpoints
        res = client.get("/v1/mcp/acme/category-suggestions")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 2 and body["applied"] is False
    assert [i["endpoint_id"] for i in body["items"]] == ["e1", "e3"]
    assert body["items"][0]["suggested_category"] == "databases"
    mdb.list_mcp_endpoints.assert_called_once_with(_TENANT)
    _assert_no_writes(mdb)


def test_queue_include_categorized_and_limit():
    endpoints = [_endpoint(id=f"e{i}", category="other") for i in range(5)]
    with patch("app.mcp_categorization_routes.db") as mdb:
        _wire_db(mdb)
        mdb.list_mcp_endpoints.return_value = endpoints
        res = client.get("/v1/mcp/acme/category-suggestions?include_categorized=true&limit=2")
    body = res.json()
    assert body["total"] == 5 and len(body["items"]) == 2
    assert body["items"][0]["current_category"] == "other"


@pytest.mark.parametrize("limit", [0, 51])
def test_queue_limit_bounds(limit):
    with patch("app.mcp_categorization_routes.db"):
        res = client.get(f"/v1/mcp/acme/category-suggestions?limit={limit}")
    assert res.status_code == 422


def test_queue_never_calls_claude():
    with patch("app.mcp_categorization_routes.db") as mdb, patch(
        "app.mcp_categorization_routes.suggest_category_with_claude"
    ) as claude:
        _wire_db(mdb)
        mdb.list_mcp_endpoints.return_value = [_endpoint()]
        client.get("/v1/mcp/acme/category-suggestions")
    claude.assert_not_called()


def test_suggestion_routes_require_auth():
    app.dependency_overrides.pop(validate_authentication, None)
    res = client.get("/v1/mcp/acme/category-suggestions")
    assert res.status_code in (401, 403)
