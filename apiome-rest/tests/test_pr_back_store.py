"""PR-back storage — REPO-5.8 (#2793).

The SQL each store function sends and how rows come back, over a scripted ``execute_query``:
settings round trip, the pre-REPO-5.7 ``tenant_repository_imports`` fallback for a project's
source files, and entity provenance.
"""

from __future__ import annotations

from typing import Any, List, Tuple
from unittest.mock import patch

from app import pr_back_store
from app.pr_back import PrBackSettings, SourceFile

TENANT = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
REPO = "66666666-6666-4666-8666-666666666666"


class _Script:
    """Answers queries in order and records them."""

    def __init__(self, *answers: List[dict]) -> None:
        self.answers = list(answers)
        self.calls: List[Tuple[str, Any]] = []

    def __call__(self, query: str, params: Any = None) -> List[dict]:
        self.calls.append((" ".join(query.split()), params))
        return self.answers.pop(0) if self.answers else []


def test_settings_read_and_absent():
    script = _Script([{"repository_id": REPO, "project_policy": "deny", "project_ids": [PROJECT]}], [])
    with patch.object(pr_back_store.db, "execute_query", script):
        assert pr_back_store.get_settings(TENANT, REPO) == PrBackSettings("deny", (PROJECT,))
        assert pr_back_store.get_settings(TENANT, REPO) is None
    assert script.calls[0][1] == (REPO, TENANT)
    assert "tenant_id = %s::uuid" in script.calls[0][0]


def test_save_settings_upserts_within_the_tenant():
    script = _Script([{"repository_id": REPO}])
    settings = PrBackSettings("allow", (PROJECT,), "main", "t", ("octocat",))
    with patch.object(pr_back_store.db, "execute_query", script):
        assert pr_back_store.save_settings(TENANT, REPO, settings, "u1") == {"repository_id": REPO}
    query, params = script.calls[0]
    assert "ON CONFLICT (repository_id) DO UPDATE" in query
    assert "WHERE apiome.repository_pr_back_settings.tenant_id = EXCLUDED.tenant_id" in query
    assert params == (REPO, TENANT, "allow", [PROJECT], "main", "t", ["octocat"], "u1")


def test_project_sources_prefer_v301_rows():
    rows = [{"id": "s1", "repository_id": REPO, "branch": "main", "path": "a.yaml", "precedence": 1}]
    script = _Script(rows)
    with patch.object(pr_back_store.db, "execute_query", script):
        assert pr_back_store.project_sources(TENANT, PROJECT) == [SourceFile("s1", REPO, "main", "a.yaml", 1)]
    assert len(script.calls) == 1


def test_project_sources_fall_back_to_the_latest_import():
    script = _Script([], [{"repository_id": REPO, "branch": "dev", "path": "openapi.json"}])
    with patch.object(pr_back_store.db, "execute_query", script):
        assert pr_back_store.project_sources(TENANT, PROJECT) == [SourceFile(None, REPO, "dev", "openapi.json", 1)]
    assert "tenant_repository_imports" in script.calls[1][0]
    with patch.object(pr_back_store.db, "execute_query", _Script([], [])):
        assert pr_back_store.project_sources(TENANT, PROJECT) == []


def test_entity_sources_and_names():
    script = _Script(
        [
            {"entity_kind": "path", "entity_key": "/a", "source_id": "s1"},
            {"entity_kind": "class", "entity_key": "A", "source_id": None},
        ],
        [{"id": PROJECT.upper(), "name": "Shop"}],
    )
    with patch.object(pr_back_store.db, "execute_query", script):
        assert pr_back_store.entity_sources("v1") == {("path", "/a"): "s1", ("class", "A"): None}
        assert pr_back_store.unknown_project_ids(TENANT, [PROJECT, "other"]) == ["other"]
    assert pr_back_store.project_names(TENANT, []) == {}
