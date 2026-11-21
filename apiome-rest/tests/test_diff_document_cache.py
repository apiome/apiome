"""The diff family reads stored documents — COA-5.6 (#7082).

Classified diff, the compatibility check, its oasdiff evidence and the version changelog read each
side with :func:`app.compatibility_engine.read_revision_openapi`, the rendered document cache of
COA-5.5. These tests check, without a database:

* a cache hit is served from the stored bytes and does no generation; a miss and a revision the
  cache cannot serve fall back as documented;
* equal rendered digests answer "no changes" without classifying (classified diff, compatibility
  check, changelog);
* ``X-Apiome-Document-Cache`` names ``hit`` / ``miss`` per side, on JSON, Markdown and 409 replies;
* across the CTG-1.4 diff corpus (``tests/fixtures/diff``) the classified diff served from stored
  bytes is identical to the response built from the generated documents before this change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
import yaml
from fastapi import HTTPException
from fastapi.testclient import TestClient
from revision_reads import as_read, reads

from app.auth import validate_authentication
from app.compatibility_engine import (
    CACHE_HIT,
    CACHE_MISS,
    DOCUMENT_CACHE_HEADER,
    RevisionOpenApi,
    document_cache_header,
    read_revision_openapi,
    same_document,
)
from app.main import app
from app.publication_changelog import generate_version_changelog_on_publish
from app.rendered_documents import KIND_OPENAPI, RenderedDocument
from app.spec_snapshot import render_spec_bytes, sha256_hex

client = TestClient(app)

_AUTH = {"tenant_id": "tenant-1", "user_id": "user-1", "auth_method": "jwt"}
_PROJECT = {"id": "proj-1", "tenant_id": "tenant-1", "slug": "pets", "description": "d", "metadata": "{}"}
_BASE = {"id": "base-rev", "project_id": "proj-1", "version_id": "1.0.0"}
_HEAD = {"id": "head-rev", "project_id": "proj-1", "version_id": "1.1.0"}

_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Pets", "version": "1.0.0"},
    "paths": {
        "/pets": {"get": {"responses": {"200": {"description": "ok"}}}},
        "/pets/{id}": {"get": {"responses": {"200": {"description": "ok"}}}},
    },
}
_HEAD_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Pets", "version": "1.1.0"},
    "paths": {"/pets": {"get": {"responses": {"200": {"description": "ok"}}}}},
}

_DIFF_CORPUS = Path(__file__).resolve().parent / "fixtures" / "diff"


def _rendered(version_id: str, spec: Dict[str, Any], *, cached: bool) -> RenderedDocument:
    """A rendered document of ``spec``, as the COA-5.5 cache returns it."""
    content = render_spec_bytes(spec)
    return RenderedDocument(
        tenant_id="tenant-1",
        version_id=version_id,
        kind=KIND_OPENAPI,
        sha256=sha256_hex(content),
        size_bytes=len(content),
        content_stamp=1,
        generator="apiome-openapi",
        generator_version="1+test",
        cached=cached,
        stored=True,
        _content=content,
    )


class _FakeCache:
    """Stands in for :func:`app.rendered_documents.rendered_document`, keyed by revision id."""

    def __init__(self, documents: Dict[str, Dict[str, Any]], *, hits: Optional[set] = None) -> None:
        self.documents = documents
        self.hits = set(documents) if hits is None else hits
        self.calls: List[str] = []

    def __call__(self, revision: Any, kind: str = KIND_OPENAPI, *, tenant_id: str, **_kwargs: Any):
        assert kind == KIND_OPENAPI and tenant_id == "tenant-1"
        self.calls.append(str(revision))
        spec = self.documents.get(str(revision))
        if spec is None:
            return None
        return _rendered(str(revision), spec, cached=str(revision) in self.hits)


@pytest.fixture
def authed():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _diff_db(*versions: Dict[str, Any]) -> MagicMock:
    """A classified-diff database mock that resolves ``versions`` by label."""
    db = MagicMock()
    db.user_has_permission.return_value = True
    db.get_project_by_slug.return_value = _PROJECT
    by_label = {v["version_id"]: v for v in versions}
    db.get_version_by_version_id.side_effect = lambda _pid, label, _tid: by_label.get(label)
    db.get_version_by_id.side_effect = lambda rid, _tid: next((v for v in versions if v["id"] == rid), None)
    db.get_revision_source_row.return_value = {"source_format": "openapi"}
    db.list_prior_revisions_for_transitive_check.return_value = []
    return db


def _post_diff(body: Dict[str, Any], *, accept: Optional[str] = None):
    headers = {"Accept": accept} if accept else {}
    return client.post("/v1/diff/acme/classified", json=body, headers=headers)


_PAIR = {"base": {"project": "pets", "version": "1.0.0"}, "head": {"project": "pets", "version": "1.1.0"}}


# ───────────────────────────── read_revision_openapi ─────────────────────────────


def test_a_hit_is_parsed_from_the_stored_bytes_without_generating() -> None:
    cache = _FakeCache({"base-rev": _SPEC})
    with patch("app.compatibility_engine.rendered_document", cache), patch(
        "app.compatibility_engine.openapi_for_revision"
    ) as generate:
        read = read_revision_openapi(_BASE, "acme", "tenant-1")

    generate.assert_not_called()
    assert read.spec == _SPEC
    assert read.cache == CACHE_HIT
    assert read.sha256 == sha256_hex(render_spec_bytes(_SPEC))
    assert cache.calls == ["base-rev"]


def test_a_miss_reports_miss_and_keeps_the_digest() -> None:
    cache = _FakeCache({"base-rev": _SPEC}, hits=set())
    with patch("app.compatibility_engine.rendered_document", cache):
        read = read_revision_openapi(_BASE, "acme", "tenant-1")
    assert (read.cache, read.sha256) == (CACHE_MISS, sha256_hex(render_spec_bytes(_SPEC)))


def test_each_read_hands_out_its_own_document() -> None:
    cache = _FakeCache({"base-rev": _SPEC})
    with patch("app.compatibility_engine.rendered_document", cache):
        first = read_revision_openapi(_BASE, "acme", "tenant-1")
        first.spec["paths"].clear()
        second = read_revision_openapi(_BASE, "acme", "tenant-1")
    assert second.spec == _SPEC


def test_a_revision_the_cache_cannot_serve_is_generated_directly() -> None:
    with patch("app.compatibility_engine.rendered_document", return_value=None), patch(
        "app.compatibility_engine.openapi_for_revision", return_value=_SPEC
    ) as generate:
        read = read_revision_openapi(_BASE, "acme", "tenant-1")
    generate.assert_called_once_with(_BASE, "acme", "tenant-1")
    assert read == RevisionOpenApi(spec=_SPEC, sha256=None, cache=CACHE_MISS)


def test_a_failing_cached_render_falls_back_to_direct_generation() -> None:
    with patch("app.compatibility_engine.rendered_document", side_effect=ValueError("NaN")), patch(
        "app.compatibility_engine.openapi_for_revision", return_value=_SPEC
    ) as generate:
        read = read_revision_openapi(_BASE, "acme", "tenant-1")
    generate.assert_called_once()
    assert read.sha256 is None and read.spec == _SPEC


def test_the_direct_path_still_raises_its_404() -> None:
    with patch("app.compatibility_engine.rendered_document", return_value=None), patch(
        "app.compatibility_engine.openapi_for_revision",
        side_effect=HTTPException(status_code=404, detail="Project not found for revision"),
    ):
        with pytest.raises(HTTPException) as raised:
            read_revision_openapi(_BASE, "acme", "tenant-1")
    assert raised.value.status_code == 404


# ───────────────────────────── same_document / header ─────────────────────────────


def test_only_equal_cache_digests_are_the_same_document() -> None:
    assert same_document(as_read(_SPEC, sha256="a"), as_read(_HEAD_SPEC, sha256="a"))
    assert not same_document(as_read(_SPEC, sha256="a"), as_read(_SPEC, sha256="b"))
    # A document generated outside the cache has no digest and never matches.
    assert not same_document(as_read(_SPEC), as_read(_SPEC))


def test_the_header_names_each_side_and_folds_the_priors() -> None:
    hit, miss = as_read(_SPEC, cache=CACHE_HIT), as_read(_SPEC, cache=CACHE_MISS)
    assert document_cache_header([("base", hit), ("head", miss)]) == "base=hit, head=miss"
    assert document_cache_header([("base", hit), ("head", hit), ("prior", hit), ("prior", hit)]) == (
        "base=hit, head=hit, prior=hit"
    )
    assert document_cache_header([("base", hit), ("prior", miss), ("prior", hit)]) == "base=hit, prior=miss"
    assert document_cache_header([]) is None


# ───────────────────────────── classified diff ─────────────────────────────


def test_classified_diff_reads_both_sides_from_the_cache_and_says_so(authed) -> None:
    cache = _FakeCache({"base-rev": _SPEC, "head-rev": _HEAD_SPEC}, hits={"base-rev"})
    with patch("app.classified_diff_routes.db", _diff_db(_BASE, _HEAD)), patch(
        "app.compatibility_engine.rendered_document", cache
    ), patch("app.compatibility_engine.openapi_for_revision") as generate:
        r = _post_diff(_PAIR)

    assert r.status_code == 200, r.text
    generate.assert_not_called()
    assert cache.calls == ["base-rev", "head-rev"]
    assert r.headers[DOCUMENT_CACHE_HEADER] == "base=hit, head=miss"
    assert any(c["ruleId"] == "ctg.path_removed" for c in r.json()["changes"])


def test_equal_digests_answer_no_changes_without_classifying(authed) -> None:
    same = dict(_SPEC)
    cache = _FakeCache({"base-rev": same, "head-rev": same})
    with patch("app.classified_diff_routes.db", _diff_db(_BASE, _HEAD)), patch(
        "app.compatibility_engine.rendered_document", cache
    ), patch("app.classified_diff_routes.classify_openapi_changes") as classify:
        r = _post_diff(_PAIR)

    assert r.status_code == 200, r.text
    classify.assert_not_called()
    data = r.json()
    assert data["changes"] == [] and data["maxSeverity"] is None
    assert data["counts"]["total"] == 0
    assert r.headers[DOCUMENT_CACHE_HEADER] == "base=hit, head=hit"


def test_the_markdown_reply_carries_the_header_too(authed) -> None:
    cache = _FakeCache({"base-rev": _SPEC, "head-rev": _HEAD_SPEC})
    with patch("app.classified_diff_routes.db", _diff_db(_BASE, _HEAD)), patch(
        "app.compatibility_engine.rendered_document", cache
    ):
        r = _post_diff(_PAIR, accept="text/markdown")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")
    assert r.headers[DOCUMENT_CACHE_HEADER] == "base=hit, head=hit"


def test_an_inline_head_lists_only_the_base(authed) -> None:
    cache = _FakeCache({"base-rev": _SPEC})
    with patch("app.classified_diff_routes.db", _diff_db(_BASE)), patch(
        "app.compatibility_engine.rendered_document", cache
    ):
        r = _post_diff({"base": _PAIR["base"], "head": {"inline": yaml.safe_dump(_HEAD_SPEC)}})
    assert r.status_code == 200, r.text
    assert r.headers[DOCUMENT_CACHE_HEADER] == "base=hit"


def test_a_transitive_diff_reads_every_prior_from_the_cache(authed) -> None:
    older = {"id": "old-rev", "project_id": "proj-1", "version_id": "0.9.0"}
    db = _diff_db(_BASE, _HEAD, older)
    db.list_prior_revisions_for_transitive_check.return_value = [older]
    cache = _FakeCache({"base-rev": _SPEC, "head-rev": _HEAD_SPEC, "old-rev": _SPEC}, hits={"base-rev", "head-rev"})
    with patch("app.classified_diff_routes.db", db), patch("app.compatibility_engine.rendered_document", cache):
        r = _post_diff({**_PAIR, "transitive": True})
    assert r.status_code == 200, r.text
    assert cache.calls == ["base-rev", "head-rev", "old-rev"]
    assert r.headers[DOCUMENT_CACHE_HEADER] == "base=hit, head=hit, prior=miss"


def _corpus_cases() -> List[Any]:
    """Every OpenAPI-mode case of the CTG-1.4 diff corpus."""
    cases = []
    case_dirs = [p for p in _DIFF_CORPUS.iterdir() if (p / "base.yaml").is_file() and (p / "head.yaml").is_file()]
    for case in sorted(case_dirs):
        base = yaml.safe_load((case / "base.yaml").read_text(encoding="utf-8"))
        head = yaml.safe_load((case / "head.yaml").read_text(encoding="utf-8"))
        cases.append(pytest.param(base, head, id=case.name))
    return cases


@pytest.mark.parametrize(("base", "head"), _corpus_cases())
def test_the_diff_corpus_classifies_identically_from_stored_bytes(authed, base, head) -> None:
    db = _diff_db(_BASE, _HEAD)
    # Before COA-5.6: each side was the generated document itself.
    with patch("app.classified_diff_routes.db", db), patch(
        "app.classified_diff_routes.read_revision_openapi", side_effect=reads(base, head)
    ):
        before = _post_diff(_PAIR)
    # Now: each side is parsed from the rendered bytes the document store keeps.
    cache = _FakeCache({"base-rev": base, "head-rev": head})
    with patch("app.classified_diff_routes.db", db), patch("app.compatibility_engine.rendered_document", cache):
        after = _post_diff(_PAIR)

    assert before.status_code == after.status_code == 200
    assert after.json() == before.json()


def test_the_diff_corpus_is_not_empty() -> None:
    assert len(_corpus_cases()) >= 10


# ───────────────────────────── compatibility check ─────────────────────────────


_COMPAT_BASE = {"id": "11111111-1111-1111-1111-111111111111", "project_id": "proj-1", "version_id": "1.0.0"}
_COMPAT_HEAD = {"id": "22222222-2222-2222-2222-222222222222", "project_id": "proj-1", "version_id": "1.1.0"}


def _compat_db() -> MagicMock:
    db = MagicMock()
    db.get_project_by_id.return_value = {**_PROJECT, "metadata": {}}
    rows = {r["id"]: r for r in (_COMPAT_BASE, _COMPAT_HEAD)}
    db.get_version_by_id.side_effect = lambda rid, _tid: rows.get(rid)
    db.get_revision_source_row.return_value = {"source_format": "openapi"}
    db.list_prior_revisions_for_transitive_check.return_value = []
    return db


def _post_compat(cache: _FakeCache, body: Optional[Dict[str, Any]] = None):
    payload = {"baseRevisionId": _COMPAT_BASE["id"], "headRevisionId": _COMPAT_HEAD["id"], **(body or {})}
    with patch("app.compatibility_routes.db", _compat_db()), patch(
        "app.compatibility_routes.canonical_model_for_revision", lambda *_a: None
    ), patch("app.compatibility_routes.enforce_permission"), patch(
        "app.compatibility_routes.capture_oasdiff_compatibility_evidence"
    ), patch("app.compatibility_engine.rendered_document", cache), patch(
        "app.compatibility_engine.openapi_for_revision"
    ) as generate:
        response = client.post("/v1/versions/acme/proj-1/compatibility", json=payload)
    generate.assert_not_called()
    return response


def test_the_compatibility_check_reads_the_cache_and_sends_the_header(authed) -> None:
    cache = _FakeCache({_COMPAT_BASE["id"]: _SPEC, _COMPAT_HEAD["id"]: _HEAD_SPEC}, hits={_COMPAT_HEAD["id"]})
    r = _post_compat(cache)
    assert r.status_code == 200, r.text
    assert r.json()["overall"] == "breaking"
    assert r.headers[DOCUMENT_CACHE_HEADER] == "base=miss, head=hit"


def test_the_compatibility_check_skips_the_engine_for_equal_digests(authed) -> None:
    cache = _FakeCache({_COMPAT_BASE["id"]: _SPEC, _COMPAT_HEAD["id"]: _SPEC})
    with patch("app.compatibility_routes.CompatibilityCheckEngine.run") as run:
        r = _post_compat(cache)
    assert r.status_code == 200, r.text
    run.assert_not_called()
    assert r.json()["overall"] == "safe" and r.json()["findings"] == []


def test_a_409_reply_carries_the_header(authed) -> None:
    cache = _FakeCache({_COMPAT_BASE["id"]: _SPEC, _COMPAT_HEAD["id"]: _HEAD_SPEC})
    r = _post_compat(cache, {"policy": {"http409WhenBreaking": True}})
    assert r.status_code == 409
    assert r.headers[DOCUMENT_CACHE_HEADER] == "base=hit, head=hit"


# ───────────────────────────── version changelog ─────────────────────────────


def _publish_changelog(base_read: RevisionOpenApi, head_read: RevisionOpenApi) -> MagicMock:
    """Run the publish changelog hook with the two reads; return the database mock."""
    candidate = {"id": "cand", "version_id": "2.0.0", "published": True}
    baseline = {"id": "base", "version_id": "1.0.0", "published": True}
    with patch("app.publication_changelog.db") as mdb, patch(
        "app.publication_changelog.read_revision_openapi", side_effect=[base_read, head_read]
    ), patch("app.publication_changelog.classify_openapi_changes") as classify:
        mdb.get_version_by_id.side_effect = lambda vid, _tid: {"cand": candidate, "base": baseline}.get(vid)
        mdb.get_prior_published_baseline_revision_id.return_value = "base"
        generate_version_changelog_on_publish(
            tenant_slug="ten", tenant_id="tid", project_id="pid", published_revision_id="cand", actor_id="uid"
        )
    mdb.classify = classify
    return mdb


def test_the_changelog_of_an_unchanged_document_is_empty_without_classifying() -> None:
    mdb = _publish_changelog(as_read(_SPEC, sha256="same"), as_read(_SPEC, sha256="same"))
    mdb.classify.assert_not_called()
    kwargs = mdb.upsert_version_changelog.call_args[1]
    assert kwargs["status"] == "ready" and kwargs["max_severity"] is None
    assert kwargs["changelog_json"]["entries"] == []


def test_the_changelog_classifies_different_documents() -> None:
    mdb = _publish_changelog(as_read(_SPEC, sha256="a"), as_read(_HEAD_SPEC, sha256="b"))
    assert mdb.classify.call_args[0] == (_SPEC, _HEAD_SPEC)
