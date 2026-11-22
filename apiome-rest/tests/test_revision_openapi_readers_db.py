"""Features read a warm revision without generating, against Postgres — COA-5.14 (#7090).

The acceptance criterion: lint, mock start, merge preview and publish on a warm revision issue no
class or property query. Each test warms the revisions it reads, clears the query log of
``test_rendered_documents_db``'s fixture, runs the feature on the real tables and the ``db``
store backend, and asserts that nothing touched the class, property, path or operation tables.

* lint — :func:`app.lint_routes.build_lint_report`;
* mock start — the document :func:`app.mock_routes._build_spec_for_version` hands the mock;
* merge preview — ``POST …/version-branches/merge-preview``
  (:func:`app.version_merge_routes.version_branch_merge_preview`);
* publish — :func:`app.version_publish_prechecks.enforce_publish_prechecks`. Its "every class
  has a description" gate reads the class list once; that is the gate's own query, not a render,
  so the test allows exactly that one and no property, path or operation query.

Two more tests cover what the cache must not change: the cached document equals the directly
generated one, and a component-pin override is rendered every time and never stored.

Skips when no database with V404 is reachable.
"""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
from typing import Any, Dict, Iterator
from unittest.mock import patch

import pytest

from app.compatibility_engine import openapi_for_revision
from app.models import VersionBranchMergePreviewRequest, VersionPublishRequest
from app.rendered_documents import KIND_OPENAPI, build_live_spec, rendered_document
from tests.test_content_stamp_db import env as stamp_env  # noqa: F401 - the seeded tenant/project/revision
from tests.test_original_documents_db import ctx as documents_ctx  # noqa: F401 - adds the db-backed store
from tests.test_rendered_documents_db import _CONTENT_TABLES, _add_property, _seed_order, _touching
from tests.test_rendered_documents_db import ctx as rendered_ctx  # noqa: F401 - seeded revision + query log

pytestmark = pytest.mark.requires_db

#: Modules whose ``db`` handle the features under test read through.
_DB_MODULES = (
    "app.compatibility_engine",
    "app.lint_routes",
    "app.mock_routes",
    "app.version_merge_routes",
    "app.version_publish_prechecks",
)


@pytest.fixture
def ctx(rendered_ctx: Dict[str, Any]) -> Iterator[Dict[str, Any]]:  # noqa: F811
    """The rendered-document fixture, with every feature's database handle and store pointed at it."""
    with ExitStack() as stack:
        for module in _DB_MODULES:
            stack.enter_context(patch(f"{module}.db", rendered_ctx["db"]))
        stack.enter_context(patch("app.rendered_documents.get_document_store", return_value=rendered_ctx["store"]))
        yield rendered_ctx


def _row(ctx: Dict[str, Any], version: str) -> Dict[str, Any]:
    return ctx["db"].get_version_by_id(version, ctx["tenant"])


def _warm(ctx: Dict[str, Any], *versions: str) -> None:
    """Render and store each revision's document, then forget the queries that took."""
    for version in versions:
        document = rendered_document(version, KIND_OPENAPI, tenant_id=ctx["tenant"], database=ctx["db"])
        assert document is not None and document.stored
    ctx["queries"].clear()


def _head(ctx: Dict[str, Any], label: str = "1.1.0") -> str:
    """A second revision of the project that adds a property; return its ``versions.id``."""
    head_id = str(ctx["db"].create_version(ctx["project"], ctx["user"], label)["id"])
    order = _seed_order(ctx, head_id)
    _add_property(ctx, order, "total", {"type": "number"})
    return head_id


def _content_queries(ctx: Dict[str, Any]) -> list:
    return _touching(ctx, *_CONTENT_TABLES)


def test_the_cached_document_is_the_one_the_generator_builds(ctx) -> None:
    _seed_order(ctx)
    row = ctx["db"].get_version_by_slugs(ctx["tenant_slug"], ctx["project_slug"], "1.0.0")
    direct, _counts = build_live_spec(ctx["db"], row, ctx["tenant_slug"], ctx["project_slug"], "1.0.0")

    cold = openapi_for_revision(_row(ctx, ctx["version"]), ctx["tenant_slug"], ctx["tenant"])
    ctx["queries"].clear()
    warm = openapi_for_revision(_row(ctx, ctx["version"]), ctx["tenant_slug"], ctx["tenant"])

    assert cold == direct and warm == direct
    assert _content_queries(ctx) == []


def test_lint_on_a_warm_revision_queries_no_class_or_property(ctx) -> None:
    from app.lint_routes import build_lint_report

    _seed_order(ctx)
    row = _row(ctx, ctx["version"])
    _warm(ctx, ctx["version"])

    report = asyncio.run(build_lint_report(row, ctx["project"], ctx["tenant_slug"], ctx["tenant"]))

    assert report.grade
    assert _content_queries(ctx) == []


def test_lint_against_a_base_on_warm_revisions_queries_no_class_or_property(ctx) -> None:
    from app.lint_routes import build_lint_report

    _seed_order(ctx)
    head_id = _head(ctx)
    base, head = _row(ctx, ctx["version"]), _row(ctx, head_id)
    _warm(ctx, ctx["version"], head_id)

    asyncio.run(
        build_lint_report(
            head, ctx["project"], ctx["tenant_slug"], ctx["tenant"], base_version=base, resolved_base_id=str(base["id"])
        )
    )

    assert _content_queries(ctx) == []


def test_starting_a_mock_from_a_warm_version_queries_no_class_or_property(ctx) -> None:
    from app.mock_routes import _build_spec_for_version

    _seed_order(ctx)
    _warm(ctx, ctx["version"])
    version = ctx["db"].get_version_by_slugs(ctx["tenant_slug"], ctx["project_slug"], "1.0.0")
    ctx["queries"].clear()

    spec = _build_spec_for_version(version, ctx["tenant_slug"], ctx["project_slug"], "1.0.0")

    assert "Order" in spec["components"]["schemas"]
    assert _content_queries(ctx) == []


def _drop_branches(ctx: Dict[str, Any]) -> None:
    """Remove the project's branches, which would otherwise keep the fixture's revisions alive."""
    ctx["conn"].rollback()
    with ctx["conn"].cursor() as cur:
        cur.execute("DELETE FROM apiome.version_branches WHERE project_id = %s::uuid", (ctx["project"],))
    ctx["conn"].commit()


def test_a_merge_preview_of_warm_revisions_queries_no_class_or_property(ctx) -> None:
    from app.version_merge_routes import version_branch_merge_preview

    db = ctx["db"]
    _seed_order(ctx)
    head_id = _head(ctx)
    try:
        for name, tip in (("main-line", ctx["version"]), ("feature", head_id)):
            made = db.create_version_branch_from_revision(ctx["project"], ctx["tenant"], name, tip, ctx["user"])
            if not made.get("success"):
                pytest.skip(f"cannot seed branches: {made.get('error')}")
        _warm(ctx, ctx["version"], head_id)
        body = VersionBranchMergePreviewRequest(source_branch_name="feature", target_branch_name="main-line")
        with patch.object(db, "compute_merge_base_revision_id", return_value=ctx["version"]), patch(
            "app.version_merge_routes.enforce_permission"
        ):
            preview = asyncio.run(
                version_branch_merge_preview(
                    ctx["tenant_slug"], ctx["project"], body, {"tenant_id": ctx["tenant"], "user_id": ctx["user"]}
                )
            )
    finally:
        _drop_branches(ctx)

    assert preview["mergeBaseVersionId"] == ctx["version"]
    assert _content_queries(ctx) == []


def test_publish_prechecks_on_a_warm_revision_query_no_class_or_property(ctx) -> None:
    from app.version_publish_prechecks import enforce_publish_prechecks

    _seed_order(ctx)
    row = _row(ctx, ctx["version"])
    _warm(ctx, ctx["version"])

    try:
        enforce_publish_prechecks(
            tenant_slug=ctx["tenant_slug"],
            tenant_id=ctx["tenant"],
            project_id=ctx["project"],
            existing=row,
            request=VersionPublishRequest(),
        )
    except Exception as exc:  # noqa: BLE001 - a gate may refuse the seeded draft; the reads still ran
        from fastapi import HTTPException

        assert isinstance(exc, HTTPException), exc

    assert any("apiome.version_documents" in query for query in ctx["queries"])
    # The document is not generated: no property, path or operation row is read. The one class
    # query left is the "every class has a description" gate, which reads the class list itself.
    assert _touching(ctx, "apiome.class_properties", "apiome.version_path", "apiome.path_operation") == []
    assert len(_touching(ctx, "apiome.classes")) == 1


def test_a_pin_override_is_rendered_each_time_and_never_stored(ctx) -> None:
    _seed_order(ctx)
    row = _row(ctx, ctx["version"])
    _warm(ctx, ctx["version"])

    spec = openapi_for_revision(row, ctx["tenant_slug"], ctx["tenant"], component_pin_rows=[])

    assert "Order" in spec["components"]["schemas"]
    assert _content_queries(ctx) != []
    assert not any("INSERT INTO apiome.version_documents" in query for query in ctx["queries"])
