"""Round-trip text diff — MFX-43.4 (#4364).

The round-trip comparison (IXH-4.4) gains a text diff: the emitted artifact beside the same
target re-emitted from the re-imported model, i.e. what the artifact becomes after one more
import + export. Pinned here:

* a single-document target carries both texts, flagged ``identical`` when nothing moved;
* a re-emit that differs shows the difference in the texts (the emitter is patched to change);
* a multi-file bundle, a binary artifact, a document over the size cap and a failing re-emit each
  give ``text_diff: null`` with a reason — never an error, and the model diff is unaffected;
* a skipped (``unsupported``) or failed re-import carries neither;
* the route serializes it.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from test_export_roundtrip import _imported_api, _source

import app.export_roundtrip as rt
from app.auth import validate_authentication
from app.emitter import EmitResult, EmittedFile, load_builtin_emitters
from app.export_roundtrip import TEXT_DIFF_MAX_BYTES, build_text_diff, run_export_roundtrip
from app.import_source import ImportSourceError, load_builtin_import_sources
from app.main import app
from app.roundtrip_matrix import MatrixCellStatus


@pytest.fixture(autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


def _single(content, path: str = "openapi.json") -> EmitResult:
    return EmitResult(files=[EmittedFile(path=path, content=content, media_type="application/json")],
                      media_type="application/json")


def test_a_single_document_round_trip_carries_both_texts() -> None:
    result = run_export_roundtrip(_source(), "openapi")
    assert result.status is MatrixCellStatus.PASS
    diff = result.text_diff
    assert diff is not None and result.text_diff_reason is None
    assert diff.filename and diff.emitted and diff.reemitted
    assert '"Round Trip Probe"' in diff.emitted
    assert diff.identical is (diff.emitted == diff.reemitted)


def test_a_reemit_that_differs_shows_in_the_texts() -> None:
    original = rt.emit_canonical

    def drifting(api, target, *, opts=None, persistence=None):
        out = original(api, target, opts=opts, persistence=persistence)
        doc = out.files[0].content
        if isinstance(doc, dict):
            doc = {**doc, "info": {**doc["info"], "title": "Drifted"}}
        return EmitResult(files=[EmittedFile(path=out.files[0].path, content=doc,
                                             media_type=out.files[0].media_type)], media_type=out.media_type)

    with patch.object(rt, "emit_canonical", drifting):
        result = run_export_roundtrip(_source(), "openapi")
    diff = result.text_diff
    assert diff is not None and not diff.identical
    assert '"Round Trip Probe"' in diff.emitted and '"Drifted"' in diff.reemitted


def test_a_bundle_has_no_text_diff_but_says_why() -> None:
    emitted = EmitResult(files=[EmittedFile(path="a.proto", content="x"), EmittedFile(path="b.proto", content="y")],
                         media_type="text/plain")
    diff, reason = build_text_diff(emitted, _imported_api(), "openapi-3.1", multi_file=True)
    assert diff is None and "multi-file bundle" in reason


def test_a_binary_artifact_has_no_text_diff() -> None:
    diff, reason = build_text_diff(_single(b"\x00\x01"), _imported_api(), "openapi-3.1", multi_file=False)
    assert diff is None and "binary" in reason


def test_an_oversized_artifact_has_no_text_diff() -> None:
    big = "x" * (TEXT_DIFF_MAX_BYTES + 1)
    diff, reason = build_text_diff(_single(big), _imported_api(), "openapi-3.1", multi_file=False)
    assert diff is None and "too large" in reason


def test_a_failing_reemit_is_a_reason_not_an_error() -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("emitter exploded")

    with patch.object(rt, "emit_canonical", boom):
        diff, reason = build_text_diff(_single("{}"), _imported_api(), "openapi-3.1", multi_file=False)
    assert diff is None and "could not be emitted again: emitter exploded" in reason


def test_an_unsupported_target_carries_no_text_diff() -> None:
    result = run_export_roundtrip(_source(), "sample")
    assert result.status is MatrixCellStatus.UNSUPPORTED
    assert result.text_diff is None and result.text_diff_reason is None


def test_a_failed_reimport_carries_no_text_diff() -> None:
    with patch.object(rt, "reimport_emitted", side_effect=ImportSourceError("nope")):
        result = run_export_roundtrip(_source(), "openapi")
    assert result.status is MatrixCellStatus.FAIL
    assert result.text_diff is None and result.text_diff_reason is None


def test_the_route_serializes_the_text_diff() -> None:
    client = TestClient(app)
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": "test-tenant-id", "user_id": "test-user-id", "auth_method": "jwt"}
    try:
        with patch("app.export_routes.load_export_source", return_value=_source()):
            response = client.post("/v1/export/test-tenant/roundtrip", json={"artifact": "a1", "target": "openapi"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body["text_diff"]) == {"filename", "media_type", "emitted", "reemitted", "identical"}
    assert body["text_diff_reason"] is None
