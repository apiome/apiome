"""DCW-2.4 (private-suite#2365) — the worker import snapshot hook stores a scrubbed snapshot, best-effort."""

from __future__ import annotations

import base64
from unittest.mock import patch

from app.spec_import_engine import _record_worker_import_snapshot

DOC = "openapi: 3.1.0\ninfo:\n  title: Pets\n  x-token: ghp_abcdefghijklmnopqrstuvwxyz0123456789\npaths: {}\n"


def _payload(text: str = DOC) -> dict:
    return {
        "tenant_id": "t1",
        "user_id": "u1",
        "filename": "pets.yaml",
        "document_base64": base64.b64encode(text.encode()).decode(),
    }


def _run(payload, *, mode="enforce"):
    from app.intake_scrub_policy import ScrubResolution

    with (
        patch("app.database.db") as db,
        patch("app.compatibility_engine.openapi_for_revision", return_value={"openapi": "3.1.0", "paths": {}}),
        patch("app.intake_scrub_policy.resolve_scrub_mode", return_value=ScrubResolution(mode=mode)),
        patch("app.intake_scrub_policy.load_tenant_scrub_policy", return_value=None),
    ):
        db.get_version_by_id.return_value = {"id": "v1", "project_id": "p1"}
        _record_worker_import_snapshot("t1", "acme", "v1", payload)
        return db


def test_stores_scrubbed_text_file_digest_and_the_canonical_document():
    db = _run(_payload())
    kwargs = db.record_import_snapshot.call_args.kwargs
    assert kwargs["version_id"] == "v1"
    assert kwargs["source_file"] == "pets.yaml"
    assert kwargs["source_format"] == "yaml"
    assert kwargs["source_digest"].startswith("sha256:")
    assert kwargs["canonical_document"] == {"openapi": "3.1.0", "paths": {}}
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in kwargs["source_text"]


def test_warn_only_keeps_the_text_as_uploaded():
    from app.intake_scrub_policy import MODE_WARN_ONLY

    db = _run(_payload(), mode=MODE_WARN_ONLY)
    assert db.record_import_snapshot.call_args.kwargs["source_text"] == DOC


def test_json_sources_are_marked_json():
    db = _run(_payload('{"openapi": "3.1.0", "paths": {}}'))
    assert db.record_import_snapshot.call_args.kwargs["source_format"] == "json"


def test_a_document_that_is_not_openapi_records_nothing():
    db = _run(_payload("asyncapi: 2.6.0\nchannels: {}\n"))
    db.record_import_snapshot.assert_not_called()


def test_a_failure_never_raises():
    with patch("app.database.db") as db:
        db.get_version_by_id.side_effect = RuntimeError("db down")
        _record_worker_import_snapshot("t1", "acme", "v1", _payload())
        db.record_import_snapshot.assert_not_called()
