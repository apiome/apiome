"""Refresh URL-sourced imports — the pure rules (RAR-6.1, #3538).

Pins: URLs are stored http/https only, lower-cased, without a fragment or credentials; the
conditional headers carry the stored validators; a 304 skips; a 200 is gated by the newer-than
comparator on Last-Modified and the checksum (same content or an older Last-Modified skips, a
newer document refreshes); a lineage with no anchors only records them; the divergence guard
holds an edited version; and the refresh request replays the stored spec onto the project.
"""

from __future__ import annotations

import base64
import hashlib

import pytest

from app.models import REPOSITORY_AUTO_IMPORT_SOURCE_KIND
from app.url_import_refresh import (
    REASON_BASELINE,
    REASON_NOT_MODIFIED,
    UrlImportError,
    build_refresh_request,
    checksum_bytes,
    conditional_headers,
    decide_check,
    divergence_for,
    normalize_url,
    parse_http_date,
    version_content_checksum,
)

_OLD = "Wed, 21 Oct 2026 07:28:00 GMT"
_NEW = "Thu, 29 Oct 2026 09:00:00 GMT"
_DOC = b'{"openapi":"3.1.0"}'


# --- URLs and headers -----------------------------------------------------------------------


def test_a_url_is_normalized():
    assert normalize_url("  HTTPS://Specs.Example.com/api/openapi.json?v=2#top ") == (
        "https://specs.example.com/api/openapi.json?v=2"
    )
    assert normalize_url("http://example.com") == "http://example.com/"


@pytest.mark.parametrize(
    "url",
    ["ftp://example.com/a.json", "file:///etc/passwd", "https://user:secret@example.com/a.json", "not a url", ""],
)
def test_unrefreshable_urls_are_refused(url):
    with pytest.raises(UrlImportError):
        normalize_url(url)


def test_conditional_headers_carry_the_stored_validators():
    assert conditional_headers('"abc"', _OLD) == {"If-None-Match": '"abc"', "If-Modified-Since": _OLD}
    assert conditional_headers(None, " ") == {}


def test_http_dates_parse_or_are_none():
    assert parse_http_date(_OLD).year == 2026
    assert parse_http_date("yesterday") is None and parse_http_date(None) is None


# --- freshness gate -------------------------------------------------------------------------


def _decide(status=200, body=_DOC, response_lm=None, stored_lm=_OLD, stored_sum="old"):
    return decide_check(
        status_code=status,
        body=body,
        response_last_modified=response_lm,
        stored_last_modified=stored_lm,
        stored_checksum=stored_sum,
    )


def test_not_modified_skips():
    decision = _decide(status=304, body=None)
    assert (decision.refresh, decision.record_anchors, decision.reason) == (False, False, REASON_NOT_MODIFIED)


def test_a_newer_document_refreshes():
    decision = _decide(response_lm=_NEW)
    assert decision.refresh and decision.reason == "newer-content"
    assert decision.checksum == hashlib.sha256(_DOC).hexdigest()


def test_the_same_document_does_not_refresh():
    decision = _decide(response_lm=_NEW, stored_sum=checksum_bytes(_DOC))
    assert not decision.refresh and decision.reason == "idempotent"


def test_an_older_last_modified_is_stale_guarded():
    decision = _decide(response_lm=_OLD, stored_lm=_NEW)
    assert not decision.refresh and decision.reason == "stale"


def test_without_last_modified_the_checksum_decides():
    assert _decide(stored_lm=None).reason == "checksum-fallback-changed"
    assert not _decide(stored_lm=None, stored_sum=checksum_bytes(_DOC)).refresh


def test_no_anchors_records_a_baseline_without_importing():
    decision = _decide(stored_lm=None, stored_sum=None)
    assert (decision.refresh, decision.record_anchors, decision.reason) == (False, True, REASON_BASELINE)


# --- divergence gate ------------------------------------------------------------------------


def test_an_edited_version_holds_the_refresh():
    assert divergence_for("a", "b").should_hold
    assert not divergence_for("a", "a").should_hold
    assert not divergence_for(None, "b").should_hold  # no baseline: nothing proves an edit


def test_the_version_checksum_is_stable_and_content_sensitive():
    one = version_content_checksum({"openapi": "3.1.0", "paths": {}})
    assert one == version_content_checksum({"openapi": "3.1.0", "paths": {}})
    assert one != version_content_checksum({"openapi": "3.1.0", "paths": {"/a": {}}})


# --- refresh request ------------------------------------------------------------------------


def test_the_refresh_request_replays_the_stored_spec_onto_the_project():
    row = {
        "project_id": "11111111-1111-4111-8111-111111111111",
        "url": "https://example.com/specs/orders.yaml",
        "source_kind": "openapi",
        "format_override": "swagger",
        "content_type": "application/yaml",
        "options_json": {"classPrefix": "Ord", "dryRun": True},
        "spec_schema_version": 1,
        "last_version_id": "22222222-2222-4222-8222-222222222222",
        "project_name": "Orders",
        "project_slug": "orders",
    }
    request = build_refresh_request(row, content=_DOC, version_label="2026-10-30T14:03Z", content_type="text/plain")
    meta = request.metadata
    assert meta.source_kind == REPOSITORY_AUTO_IMPORT_SOURCE_KIND
    assert (meta.project.project_id, meta.project.name, meta.project.slug) == (row["project_id"], "Orders", "orders")
    assert meta.version.version_id == "2026-10-30T14:03Z"
    stored = meta.repository_import_spec
    descriptor = (stored.source_kind, stored.format_override, stored.content_type)
    assert descriptor == ("openapi", "swagger", "application/yaml")
    assert stored.options == {"classPrefix": "Ord", "onVersionConflict": "create-version"}
    assert meta.refresh_provenance.parent_version_id == row["last_version_id"]
    assert base64.standard_b64decode(request.document_base64) == _DOC
    assert (request.filename, request.content_type) == ("orders.yaml", "application/yaml")


def test_the_response_type_is_used_when_none_was_stored():
    row = {"project_id": "p", "url": "https://example.com/", "options_json": None, "last_version_id": None}
    request = build_refresh_request(row, content=_DOC, version_label="v", content_type="application/json")
    assert request.content_type == "application/json" and request.filename == "spec"
    assert request.metadata.refresh_provenance.parent_version_id is None
