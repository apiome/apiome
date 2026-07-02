"""Tests for the catalog → conversion source loader — MFI-22.6 (#4007).

The convert endpoint rebuilds a :class:`~app.conversion_job.ConversionSource` from a stored catalog
item before previewing or committing a conversion. These cover that reconstruction glue
(:mod:`app.catalog_conversion`) with real adapters and no DB:

* adapter resolution copes with the *canonical format* a revision stores not matching the adapter's
  registry key (``protobuf`` → ``grpc``, ``asyncapi-3`` → ``asyncapi``), falls back to content
  sniffing, and errors on a truly unknown source;
* :func:`build_conversion_source` re-parses the captured source into a canonical model with the right
  provenance coordinates, and raises a mapped :class:`ConversionError` when there is no captured
  source or the source cannot be parsed.
"""

from __future__ import annotations

import pytest

from app.catalog_conversion import build_conversion_source, resolve_conversion_adapter
from app.conversion_job import ConversionError

# A tiny, well-formed GraphQL SDL that the graphql adapter parses + normalizes end-to-end.
_GRAPHQL_SDL = "type Query { ping: String }"


# ---------------------------------------------------------------------------
# resolve_conversion_adapter
# ---------------------------------------------------------------------------
def test_resolve_adapter_by_registry_key():
    """A format that *is* an adapter key resolves directly (graphql → graphql)."""
    assert resolve_conversion_adapter("graphql", "x").key == "graphql"


def test_resolve_adapter_by_advertised_format():
    """A canonical format that is not the key resolves via the adapter's formats (protobuf → grpc)."""
    assert resolve_conversion_adapter("protobuf", "x").key == "grpc"


def test_resolve_adapter_asyncapi_versioned_format():
    """A versioned canonical format resolves via formats membership (asyncapi-3 → asyncapi)."""
    assert resolve_conversion_adapter("asyncapi-3", "x").key == "asyncapi"


def test_resolve_adapter_sniffs_when_format_missing():
    """With no usable source_format, resolution sniffs the raw content (GraphQL SDL → graphql)."""
    assert resolve_conversion_adapter(None, _GRAPHQL_SDL).key == "graphql"


def test_resolve_adapter_unknown_format_raises_400():
    """An unrecognizable format with unsniffable content is a 400 ConversionError."""
    with pytest.raises(ConversionError) as exc:
        resolve_conversion_adapter("totally-made-up", "not any known format ~~~")
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# build_conversion_source
# ---------------------------------------------------------------------------
def _item(**overrides):
    base = {
        "id": "cat-1",
        "source_format": "graphql",
        "protocol": None,
        "tool_versions": {"graphql-lib": "1.2"},
        "format_metadata": {"sourceContent": _GRAPHQL_SDL, "sourceLabel": "schema.graphql"},
    }
    base.update(overrides)
    return base


def test_build_source_reconstructs_canonical_model():
    """A captured source is re-parsed into a canonical model with source provenance carried through."""
    source = build_conversion_source(_item(), source_version_id="rev-1")
    assert source.api.format == "graphql"
    assert source.source_project_id == "cat-1"
    assert source.source_version_id == "rev-1"
    assert source.source_format == "graphql"
    assert source.source_tool_versions == {"graphql-lib": "1.2"}
    # The model has real content the emitter can project.
    assert source.api.services


def test_build_source_defaults_format_from_model_when_unrecorded():
    """When the revision recorded no source_format, the model's own format backfills it."""
    item = _item(source_format=None)
    source = build_conversion_source(item, source_version_id="rev-1")
    assert source.source_format == "graphql"


def test_build_source_no_captured_content_raises_422():
    """A catalog item with no captured source material is a 422 (nothing to convert)."""
    item = _item(format_metadata={"package": "acme.v1"})  # provenance, but no source text/url
    with pytest.raises(ConversionError) as exc:
        build_conversion_source(item)
    assert exc.value.status_code == 422
    assert "no captured source" in str(exc.value).lower()


def test_build_source_url_only_is_not_convertible_422():
    """A URL-only source (no inline content captured) cannot be reconstructed inline → 422."""
    item = _item(format_metadata={"sourceUrl": "https://example.com/schema.graphql"})
    with pytest.raises(ConversionError) as exc:
        build_conversion_source(item)
    assert exc.value.status_code == 422


def test_build_source_unparseable_content_raises_422():
    """Captured content the adapter cannot parse maps to a 422 ConversionError (not a 500)."""
    item = _item(format_metadata={"sourceContent": "@@@ not graphql @@@"})
    with pytest.raises(ConversionError) as exc:
        build_conversion_source(item)
    assert exc.value.status_code == 422
