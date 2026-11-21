"""The diff family's cached reads against Postgres — COA-5.6 (#7082).

Runs :func:`app.compatibility_engine.read_revision_openapi` on the real rendered document cache
(V403/V404, ``db`` store backend), using the fixtures of ``test_rendered_documents_db``:

* a cold read renders and stores each side; the document equals what :func:`openapi_for_revision`
  generates directly;
* a warm diff of two revisions issues no class, property or path query (no generation), and its
  classification equals the classification of the directly generated documents;
* a revision compared with itself has equal digests.

Skips when no database with V404 is reachable.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import pytest

from app.change_taxonomy import classify_openapi_changes
from app.compatibility_engine import CACHE_HIT, CACHE_MISS, openapi_for_revision, read_revision_openapi, same_document
from tests.test_content_stamp_db import env as stamp_env  # noqa: F401 - the seeded tenant/project/revision
from tests.test_original_documents_db import ctx as documents_ctx  # noqa: F401 - adds the db-backed store
from tests.test_rendered_documents_db import _CONTENT_TABLES, _add_property, _seed_order, _touching
from tests.test_rendered_documents_db import ctx as rendered_ctx  # noqa: F401 - seeded revision + query log

pytestmark = pytest.mark.requires_db


@pytest.fixture
def ctx(rendered_ctx: Dict[str, Any]):  # noqa: F811
    """The rendered-document fixture, with the diff family's database handle and store pointed at it."""
    with patch("app.compatibility_engine.db", rendered_ctx["db"]), patch(
        "app.rendered_documents.get_document_store", return_value=rendered_ctx["store"]
    ):
        yield rendered_ctx


def _two_revisions(ctx: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """The seeded 1.0.0 revision and a 1.1.0 head that adds a property; return both rows."""
    db = ctx["db"]
    _seed_order(ctx)
    head_id = str(db.create_version(ctx["project"], ctx["user"], "1.1.0")["id"])
    order = _seed_order(ctx, head_id)
    _add_property(ctx, order, "total", {"type": "number"})
    return db.get_version_by_id(ctx["version"], ctx["tenant"]), db.get_version_by_id(head_id, ctx["tenant"])


def _read(ctx: Dict[str, Any], row: Dict[str, Any]):
    return read_revision_openapi(row, ctx["tenant_slug"], ctx["tenant"])


def test_a_cold_read_stores_the_document_openapi_for_revision_generates(ctx) -> None:
    base, head = _two_revisions(ctx)

    for row in (base, head):
        cold = _read(ctx, row)
        assert cold.cache == CACHE_MISS and cold.sha256
        assert cold.spec == openapi_for_revision(row, ctx["tenant_slug"], ctx["tenant"])
        assert _read(ctx, row).cache == CACHE_HIT


def test_a_warm_diff_does_no_generation_and_classifies_the_same(ctx) -> None:
    base, head = _two_revisions(ctx)
    _read(ctx, base), _read(ctx, head)
    ctx["queries"].clear()

    warm_base, warm_head = _read(ctx, base), _read(ctx, head)

    assert (warm_base.cache, warm_head.cache) == (CACHE_HIT, CACHE_HIT)
    assert _touching(ctx, *_CONTENT_TABLES) == []
    assert not same_document(warm_base, warm_head)
    direct = classify_openapi_changes(
        openapi_for_revision(base, ctx["tenant_slug"], ctx["tenant"]),
        openapi_for_revision(head, ctx["tenant_slug"], ctx["tenant"]),
    )
    cached = classify_openapi_changes(warm_base.spec, warm_head.spec)
    assert cached.model_dump() == direct.model_dump()
    assert any("total" in change.pointer for change in cached.changes)


def test_a_revision_compared_with_itself_has_equal_digests(ctx) -> None:
    base, _head = _two_revisions(ctx)
    assert same_document(_read(ctx, base), _read(ctx, base))
