"""Unit tests for the import pipeline ingestion layer (#3460).

Covers ``parse_document`` (JSON/YAML) and ``ingest_source`` for each intake
method. The URL and git fetchers are the only network/subprocess boundary, so
they are mocked here; everything else runs in-process.
"""

from unittest.mock import patch

import pytest

from app import import_ingestion
from app.import_ingestion import (
    IngestionError,
    ingest_source,
    parse_document,
)

# ===========================================================================
# parse_document
# ===========================================================================


def test_parse_document_json_object():
    doc = parse_document('{"type": "object", "title": "X"}')
    assert doc["type"] == "object"
    assert doc["title"] == "X"


def test_parse_document_yaml_object():
    doc = parse_document("type: object\ntitle: X\n")
    assert doc == {"type": "object", "title": "X"}


def test_parse_document_empty_raises():
    with pytest.raises(IngestionError, match="empty"):
        parse_document("   ")


def test_parse_document_non_mapping_raises():
    # A JSON array is valid JSON but not a top-level object/mapping.
    with pytest.raises(IngestionError, match="mapping"):
        parse_document('["a", "b"]')


def test_parse_document_invalid_text_raises():
    with pytest.raises(IngestionError, match="not valid JSON or YAML"):
        # Unbalanced braces / bad indentation that neither parser accepts.
        parse_document("{ not: valid: : :")


# ===========================================================================
# ingest_source — paste / file
# ===========================================================================


def test_ingest_paste_returns_parsed_document():
    result = ingest_source("paste", content='{"type": "string"}')
    assert result.document == {"type": "string"}
    assert result.text == '{"type": "string"}'


def test_ingest_file_uses_label_as_resolved_label():
    result = ingest_source(
        "file", content='{"type": "string"}', source_label="money.json"
    )
    assert result.resolved_label == "money.json"


def test_ingest_paste_without_content_raises():
    with pytest.raises(IngestionError, match="requires non-empty 'content'"):
        ingest_source("paste", content=None)


def test_ingest_invalid_method_raises():
    with pytest.raises(IngestionError, match="Invalid source_method"):
        ingest_source("carrier-pigeon", content="{}")


# ===========================================================================
# ingest_source — url
# ===========================================================================


def test_ingest_url_fetches_and_parses():
    with patch.object(
        import_ingestion, "_fetch_url_text", return_value='{"type": "object"}'
    ) as m:
        result = ingest_source("url", url="https://example.com/schema.json")
    m.assert_called_once()
    assert result.document == {"type": "object"}
    assert result.resolved_label == "https://example.com/schema.json"


def test_ingest_url_without_url_raises():
    with pytest.raises(IngestionError, match="requires a 'url'"):
        ingest_source("url", url=None)


def test_fetch_url_rejects_non_http_scheme():
    with pytest.raises(IngestionError, match="only http/https"):
        import_ingestion._fetch_url_text("ftp://example.com/x", max_bytes=1000)


def test_fetch_url_rejects_internal_address_ssrf():
    # SSRF guard (#3612): a URL resolving to the cloud metadata IP must be
    # rejected before any connection is attempted.
    from app import ssrf_guard

    with patch.object(ssrf_guard, "_resolve_host_ips", lambda host: ["169.254.169.254"]):
        with pytest.raises(IngestionError, match="non-public"):
            import_ingestion._fetch_url_text("http://metadata.internal/", max_bytes=1000)


# ===========================================================================
# ingest_source — git
# ===========================================================================


def test_ingest_git_fetches_and_parses():
    with patch.object(
        import_ingestion, "_fetch_git_text", return_value="type: object\n"
    ) as m:
        result = ingest_source(
            "git",
            git={"repo_url": "https://github.com/acme/types", "path": "money.yaml"},
        )
    m.assert_called_once()
    assert result.document == {"type": "object"}
    assert "github.com/acme/types#money.yaml" in result.resolved_label


def test_ingest_git_without_locator_raises():
    with pytest.raises(IngestionError, match="requires a 'git' locator"):
        ingest_source("git", git=None)


def test_fetch_git_requires_repo_and_path():
    with pytest.raises(IngestionError, match="requires both 'repo_url' and 'path'"):
        import_ingestion._fetch_git_text({"repo_url": "https://github.com/a/b"}, max_bytes=1000)


def test_fetch_git_rejects_non_github_host():
    with pytest.raises(IngestionError, match="github.com"):
        import_ingestion._fetch_git_text(
            {"repo_url": "https://gitlab.com/a/b", "path": "x.json"}, max_bytes=1000
        )


def test_fetch_git_delegates_to_github_fetcher():
    with patch.object(
        import_ingestion, "fetch_github_repository_file_text", return_value=("{}", False)
    ) as m:
        text = import_ingestion._fetch_git_text(
            {"repo_url": "https://github.com/acme/types", "path": "a/b.json", "ref": "dev"},
            max_bytes=5000,
        )
    assert text == "{}"
    # owner, repo, path, ref forwarded correctly.
    args, kwargs = m.call_args
    assert args[0] == "acme" and args[1] == "types"
    assert args[2] == "a/b.json" and args[3] == "dev"


def test_fetch_git_truncated_raises():
    with patch.object(
        import_ingestion, "fetch_github_repository_file_text", return_value=("partial", True)
    ):
        with pytest.raises(IngestionError, match="exceeds"):
            import_ingestion._fetch_git_text(
                {"repo_url": "https://github.com/acme/types", "path": "big.json"},
                max_bytes=10,
            )
