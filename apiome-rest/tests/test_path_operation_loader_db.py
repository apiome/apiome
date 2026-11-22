"""Set-based path and canonical loaders vs the per-row ones, on the import corpus — DBP-1.6 (#7189).

Every valid document of the import corpus (``apiome-ui/examples``) is written to a revision and
read back twice: with the per-row loaders the change replaced (``tests/legacy_loaders.py``) and
with the set-based ones. The two must be identical — the same rows, keys, order and content-type
order — and so must the OpenAPI document generated from them, byte for byte.

* paths: every valid OpenAPI entry, written through the source-apply write plan;
* canonical model: every valid entry of every format whose adapter normalizes it here.

Skips when no database with V403 is reachable (see ``tests/test_content_stamp_db.py``).
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Iterator, List, Set

import pytest
import yaml

from app.canonical_persistence import dump_canonical_tree, load_canonical_api, persist_canonical_api
from app.import_source import get_import_source
from app.openapi_generator import generate_openapi_spec
from app.rendered_documents import render_spec_bytes
from app.source_change_apply import build_canonical_writes
from tests.corpus_loader import ValidityClass, load_corpus
from tests.legacy_loaders import (
    legacy_load_canonical_api,
    legacy_operations_for_path,
    legacy_paths_for_version,
)
from tests.test_content_stamp_db import env  # noqa: F401 - the seeded tenant/project/revision

pytestmark = pytest.mark.requires_db


@pytest.fixture
def ctx(env: Dict[str, Any]) -> Iterator[Dict[str, Any]]:  # noqa: F811
    """The seeded revision; the paths written here are removed before ``env`` drops the classes.

    (Deleting a class nulls its content rows' ``class_id``, which the content checks refuse.)
    """
    yield env
    env["conn"].rollback()
    with env["conn"].cursor() as cur:
        cur.execute(
            "DELETE FROM apiome.version_path WHERE version_id IN "
            "(SELECT id FROM apiome.versions WHERE project_id = %s::uuid)",
            (env["project"],),
        )
    env["conn"].commit()

_VALID = [entry for entry in load_corpus() if entry.validity_class == ValidityClass.VALID]
_OPENAPI = [entry for entry in _VALID if entry.format == "openapi"]


def _dump(value: Any) -> str:
    """The loader output as text: keys in insertion order, values the way the API writes them."""
    return json.dumps(value, default=str)


def _document(entry: Any) -> Dict[str, Any]:
    """The corpus entry parsed (YAML is a superset of JSON)."""
    return yaml.safe_load(entry.read_text())


def _write_paths(ctx: Dict[str, Any], document: Dict[str, Any]) -> str:
    """A new revision holding ``document``'s relational rows; return its ``versions.id``."""
    db = ctx["db"]
    version = str(db.create_version(ctx["project"], ctx["user"], f"r-{uuid.uuid4().hex[:8]}")["id"])
    writes = build_canonical_writes(document)
    # The paths are what is compared. Class properties are left out: the write plan files them in
    # the project-wide property table, which refuses a name two classes of one document share.
    # The classes themselves stay, so content $refs still resolve to a class (and its name). See
    # :func:`_storable` for the rows the schema's checks would refuse.
    writes = writes.model_copy(
        update={
            "classes": [c.model_copy(update={"properties": []}) for c in writes.classes],
            "paths": [_storable(path, {c.name for c in writes.classes}) for path in writes.paths],
        }
    )
    with ctx["conn"].cursor() as cur:
        db._cursor_write_canonical_rows(cur, ctx["project"], version, writes)
    ctx["conn"].commit()
    return version


def _storable(path: Any, class_names: Set[str]) -> Any:
    """``path`` with what the schema's checks require filled in, so any corpus document stores.

    A response row needs a class, an inline schema or ``data`` (``check_response_schema_defined``)
    and a content row a class or an inline schema (``request_body_content_schema_check``); the
    write plan leaves a description-only response, or a ``$ref`` to a schema the document does
    not define, without one. Such content rows get an empty inline schema and such responses
    ``{"headers": {}}`` as ``data`` — the loaders under test read them like any other row.
    """

    def content(c: Any) -> Any:
        if c.inline_schema is None and (c.ref_class_name is None or c.ref_class_name not in class_names):
            return c.model_copy(update={"inline_schema": {}, "ref_class_name": None})
        return c

    def response(r: Any) -> Any:
        contents = [content(c) for c in r.contents]
        # The writer stores an empty ``data`` as NULL, so the filler carries one (empty) key.
        return r.model_copy(update={"contents": contents, "data": r.data or {"headers": {}}})

    operations = [
        op.model_copy(update={"request_body": op.request_body.model_copy(
            update={"contents": [content(c) for c in op.request_body.contents]}
        )})
        if op.request_body is not None
        else op
        for op in path.operations
    ]
    return path.model_copy(update={"operations": operations, "responses": [response(r) for r in path.responses]})


def _render(paths: List[Dict[str, Any]]) -> bytes:
    """The OpenAPI document generated from ``paths`` (no classes), as the cache stores it."""
    return render_spec_bytes(generate_openapi_spec("t", "p", "1.0.0", [], {}, paths_data=paths))


@pytest.mark.parametrize("entry", _OPENAPI, ids=lambda entry: str(entry.path))
def test_the_path_loaders_match_the_per_operation_loaders(ctx, entry) -> None:
    db = ctx["db"]
    version = _write_paths(ctx, _document(entry))

    legacy = legacy_paths_for_version(db, version)
    loaded = db.load_paths_for_version(version)
    assert _dump(loaded) == _dump(legacy)
    assert _render(loaded) == _render(legacy)

    # The source-apply read, on a transaction's cursor.
    with ctx["conn"].cursor() as cur:
        assert _dump(db._cursor_paths_data(cur, version)) == _dump(legacy)
    ctx["conn"].rollback()

    # The Studio canvas read, one path at a time.
    for path in legacy:
        assert _dump(db.get_operations_with_details_for_path(path["id"])) == _dump(
            legacy_operations_for_path(db, path["id"])
        )


def test_the_corpus_exercises_every_part_of_an_operation(ctx) -> None:
    """The parity above is only as good as the corpus: it must carry every detail table."""
    db = ctx["db"]
    seen = {"operations": 0, "descriptions": 0, "parameters": 0, "requestBodies": 0, "responses": 0}
    for entry in _OPENAPI:
        for path in db.load_paths_for_version(_write_paths(ctx, _document(entry))):
            for op in path["operations"]:
                seen["operations"] += 1
                seen["descriptions"] += op["description"] is not None
                seen["parameters"] += bool(op["parameters"])
                seen["requestBodies"] += op["requestBody"] is not None
                seen["responses"] += bool(op["responses"])
    assert all(count > 0 for count in seen.values()), seen


def test_content_types_keep_their_stored_order(ctx) -> None:
    media = ["text/plain", "application/xml", "application/json", "application/x-www-form-urlencoded"]
    document = {
        "openapi": "3.1.0",
        "info": {"title": "Order", "version": "1"},
        "paths": {
            "/things": {
                "post": {
                    "requestBody": {"content": {m: {"schema": {"type": "string"}} for m in media}},
                    "responses": {
                        "200": {"description": "OK", "content": {m: {"schema": {"type": "string"}} for m in media}}
                    },
                }
            }
        },
    }
    db = ctx["db"]
    version = _write_paths(ctx, document)

    def stored(table: str, parent: str) -> List[str]:
        with ctx["conn"].cursor() as cur:
            cur.execute(
                f"SELECT c.media_type FROM apiome.{table} c JOIN apiome.{parent} p ON p.id = c.{parent}_id "
                f"JOIN apiome.version_path vp ON vp.id = p.version_path_id WHERE vp.version_id = %s ORDER BY c.ctid",
                (version,),
            )
            return [row["media_type"] for row in cur.fetchall()]

    def check() -> None:
        [path] = db.load_paths_for_version(version)
        [op] = path["operations"]
        assert [c["media_type"] for c in op["requestBody"]["content_types"]] == stored(
            "shared_path_request_body_content", "shared_path_request_body"
        )
        assert [c["media_type"] for c in op["responses"][0]["content_types"]] == stored(
            "shared_path_response_content", "shared_path_response"
        )
        assert sorted(c["media_type"] for c in op["requestBody"]["content_types"]) == sorted(media)
        assert _dump(path) == _dump(legacy_paths_for_version(db, version)[0])

    check()
    # An update writes a new row version at the end of the table; both loaders follow it.
    with ctx["conn"].cursor() as cur:
        cur.execute(
            "UPDATE apiome.shared_path_request_body_content SET examples = '[]'::jsonb WHERE media_type = %s "
            "AND shared_path_request_body_id IN (SELECT rb.id FROM apiome.shared_path_request_body rb "
            "JOIN apiome.version_path vp ON vp.id = rb.version_path_id WHERE vp.version_id = %s)",
            (media[0], version),
        )
    ctx["conn"].commit()
    check()


def test_a_revision_without_paths_reads_one_statement(ctx) -> None:
    from app.statement_stats import CountingDictCursor, capture

    ctx["conn"].cursor_factory = CountingDictCursor
    with capture() as stats:
        assert ctx["db"].load_paths_for_version(ctx["version"]) == []
    assert stats.count == 1


def _normalized(entry: Any) -> Any:
    """The entry's canonical model, or skip when its adapter cannot normalize it here."""
    try:
        adapter = get_import_source(entry.adapter_key or entry.format)
        return adapter.normalize(adapter.parse(entry.read_text(), source_label=entry.path.rsplit("/", 1)[-1]))
    except Exception as exc:  # noqa: BLE001 - toolchain-bound or multi-file entries
        pytest.skip(f"{entry.path} does not normalize here: {type(exc).__name__}")


@pytest.mark.parametrize("entry", _VALID, ids=lambda entry: str(entry.path))
def test_the_canonical_loader_matches_the_per_parent_loader(ctx, entry) -> None:
    model = _normalized(entry)
    db = ctx["db"]
    version = str(db.create_version(ctx["project"], ctx["user"], f"c-{uuid.uuid4().hex[:8]}")["id"])
    try:
        persist_canonical_api(db, tenant_id=ctx["tenant"], creator_id=ctx["user"], version_id=version, model=model)
    except Exception as exc:  # noqa: BLE001 - the write side is not under test here
        ctx["conn"].rollback()
        pytest.skip(f"{entry.path} does not persist here: {type(exc).__name__}")

    loaded = load_canonical_api(db, tenant_id=ctx["tenant"], version_id=version)
    legacy = legacy_load_canonical_api(db, tenant_id=ctx["tenant"], version_id=version)
    assert loaded is not None and legacy is not None
    assert _dump(dump_canonical_tree(loaded)) == _dump(dump_canonical_tree(legacy))


def test_the_canonical_loader_ignores_rows_of_a_replaced_artifact(ctx) -> None:
    """Re-persisting soft-deletes the old artifact: its children must not leak into the new one."""
    [entry] = [e for e in _OPENAPI if e.path.startswith("openapi/01-")]
    model = _normalized(entry)
    db = ctx["db"]
    for _ in range(2):
        persist_canonical_api(
            db, tenant_id=ctx["tenant"], creator_id=ctx["user"], version_id=ctx["version"], model=model
        )
    loaded = load_canonical_api(db, tenant_id=ctx["tenant"], version_id=ctx["version"])
    assert _dump(dump_canonical_tree(loaded)) == _dump(
        dump_canonical_tree(legacy_load_canonical_api(db, tenant_id=ctx["tenant"], version_id=ctx["version"]))
    )
    assert loaded.services == model.services
