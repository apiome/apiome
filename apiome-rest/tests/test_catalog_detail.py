"""Unit tests for the catalog detail helpers (MFI-23.9, #4018).

These pin the *pure* derivations behind the catalog item detail + source-material surfaces —
``derive_catalog_summary`` / ``derive_catalog_source`` / ``resolve_source_payload`` — without a
database or an HTTP client. They cover the metadata-shape tolerance (camel/snake, nested counts),
the file/url/paste/discovery kind inference, and the three /source outcomes (content / redirect /
nothing).
"""

from app.catalog_detail import (
    derive_catalog_source,
    derive_catalog_summary,
    resolve_source_payload,
)


# ---------------------------------------------------------------------------
# derive_catalog_summary
# ---------------------------------------------------------------------------
def test_summary_reads_nested_counts():
    """Counts under a nested ``counts`` bag are read (the ImportRoutingDecision shape)."""
    fmd = {"counts": {"services": 1, "operations": 5, "types": 9, "channels": 2}}
    assert derive_catalog_summary(fmd) == {
        "services": 1, "operations": 5, "types": 9, "channels": 2,
    }


def test_summary_reads_flat_and_camel_aliases():
    """Flat ``operationCount`` / snake ``type_count`` style keys are tolerated at the root."""
    fmd = {"operationCount": 3, "type_count": 4, "channels": 0}
    out = derive_catalog_summary(fmd)
    assert out["operations"] == 3
    assert out["types"] == 4
    assert out["channels"] == 0
    assert out["services"] is None


def test_summary_all_none_when_absent_or_not_a_dict():
    """No metadata (or a non-dict) yields all-None counts, never an error."""
    for value in (None, {}, [], "nope", {"counts": "bad"}):
        assert derive_catalog_summary(value) == {
            "services": None, "operations": None, "types": None, "channels": None,
        }


def test_summary_ignores_bool_counts():
    """A boolean is never accepted as a count (bool is an int subclass)."""
    assert derive_catalog_summary({"operations": True})["operations"] is None


# ---------------------------------------------------------------------------
# derive_catalog_source
# ---------------------------------------------------------------------------
def test_source_file_with_inline_content_is_downloadable():
    """A file source carrying inline content is downloadable with content."""
    src = derive_catalog_source(
        {"sourceLabel": "petstore.yaml", "inputKind": "file", "sourceContent": "openapi: 3.1.0"},
        None,
    )
    assert src["kind"] == "file"
    assert src["label"] == "petstore.yaml"
    assert src["has_content"] is True
    assert src["downloadable"] is True
    assert src["uri"] is None


def test_source_url_is_downloadable_via_redirect():
    """A URL source (no content) is downloadable and exposes the uri."""
    src = derive_catalog_source({"sourceUrl": "https://api.example.com/openapi.json"}, None)
    assert src["kind"] == "url"
    assert src["uri"] == "https://api.example.com/openapi.json"
    assert src["has_content"] is False
    assert src["downloadable"] is True


def test_source_kind_inferred_from_url_label():
    """When no explicit kind is recorded, an http(s) label infers the url kind."""
    src = derive_catalog_source({"sourceLabel": "https://example.com/spec"}, None)
    assert src["kind"] == "url"
    assert src["uri"] == "https://example.com/spec"


def test_source_falls_back_to_generic_metadata_bag():
    """Provenance in the generic ``metadata`` bag is read when format_metadata lacks it."""
    src = derive_catalog_source(None, {"source_kind": "discovery"})
    assert src["kind"] == "discovery"
    assert src["downloadable"] is False


def test_source_empty_when_nothing_recorded():
    """No provenance at all → an empty, non-downloadable descriptor (no error)."""
    src = derive_catalog_source(None, None)
    assert src == {
        "kind": None, "label": None, "uri": None,
        "has_content": False, "downloadable": False,
    }


# ---------------------------------------------------------------------------
# resolve_source_payload
# ---------------------------------------------------------------------------
def test_payload_content_mode_types_and_names_the_download():
    """Inline content resolves to a content payload typed + named from the format/label."""
    item = {
        "slug": "acme",
        "source_format": "graphql",
        "format_metadata": {"sourceText": "type Query { ping: String }"},
    }
    payload = resolve_source_payload(item)
    assert payload["mode"] == "content"
    assert payload["content"].startswith("type Query")
    assert payload["media_type"] == "application/graphql"
    # No file-like label → slug + format extension.
    assert payload["filename"] == "acme.graphql"


def test_payload_filename_prefers_file_like_label():
    """A file-like label (with extension) wins over the slug-derived name, path-stripped."""
    item = {
        "slug": "acme",
        "source_format": "openapi-3.1",
        "format_metadata": {"fileName": "specs/petstore.yaml", "content": "openapi: 3.1.0"},
    }
    payload = resolve_source_payload(item)
    assert payload["filename"] == "petstore.yaml"
    assert payload["media_type"] == "application/json"


def test_payload_redirect_mode_when_only_url():
    """Only a URL recorded → a redirect payload to that URL."""
    item = {"slug": "acme", "format_metadata": {"sourceUri": "https://example.com/a.json"}}
    payload = resolve_source_payload(item)
    assert payload == {"mode": "redirect", "url": "https://example.com/a.json"}


def test_payload_none_when_uncaptured():
    """Neither content nor URL → None (the route 404s)."""
    item = {"slug": "acme", "format_metadata": {"package": "acme.v1"}, "metadata": {}}
    assert resolve_source_payload(item) is None
