from app.repositories.manifest import (
    RepositoryDiscoveryCandidate,
    build_repository_file_rows,
    parse_repo_manifest,
)


def test_parse_repo_manifest_validates_against_schema() -> None:
    outcome = parse_repo_manifest(
        """
version: 1
defaults:
  pollIntervalSec: 86400
  branches: [main]
specs:
  - path: services/orders/openapi.yaml
    format: openapi_3_1
    pollIntervalSec: 300
ignore:
  - "**/node_modules/**"
"""
    )

    assert outcome.manifest_error_row is None
    assert outcome.manifest is not None
    assert outcome.manifest.defaults.poll_interval_sec == 86400
    assert outcome.manifest.specs[0].format == "openapi_3_1"


def test_parse_repo_manifest_returns_manifest_error_row_but_allows_scan_to_continue() -> None:
    outcome = parse_repo_manifest(
        """
version: 2
specs:
  - path: service.yaml
"""
    )

    assert outcome.manifest is None
    assert outcome.manifest_error_row is not None
    assert outcome.manifest_error_row.path == ".objectified/repo.yaml"
    assert outcome.manifest_error_row.status == "manifest_error"
    assert outcome.manifest_error_row.metadata is not None
    assert "schema validation failed" in outcome.manifest_error_row.metadata["error"]

    rows = build_repository_file_rows(
        discoveries=[RepositoryDiscoveryCandidate(path="service.yaml", detected_format="openapi_3_0")],
        manifest=None,
        branch_poll_interval_sec=120,
        manifest_error_row=outcome.manifest_error_row,
    )
    assert [row.status for row in rows] == ["manifest_error", "discovered"]
    assert rows[1].path == "service.yaml"


def test_manifest_spec_format_and_poll_interval_override_detection_and_branch_defaults() -> None:
    outcome = parse_repo_manifest(
        """
version: 1
defaults:
  pollIntervalSec: 600
specs:
  - path: apis/openapi.yaml
    format: asyncapi_3
    pollIntervalSec: 30
  - path: apis/events.yaml
"""
    )
    assert outcome.manifest is not None

    rows = build_repository_file_rows(
        discoveries=[
            RepositoryDiscoveryCandidate(path="apis/openapi.yaml", detected_format="openapi_3_0"),
            RepositoryDiscoveryCandidate(path="apis/events.yaml", detected_format="asyncapi_2"),
            RepositoryDiscoveryCandidate(path="apis/unlisted.yaml", detected_format="json_schema"),
        ],
        manifest=outcome.manifest,
        branch_poll_interval_sec=120,
    )
    by_path = {row.path: row for row in rows}

    # Per-spec format override wins over scanner phase-B detection.
    assert by_path["apis/openapi.yaml"].format == "asyncapi_3"
    # Per-spec pollIntervalSec wins over branch-level interval.
    assert by_path["apis/openapi.yaml"].poll_interval_sec == 30
    # Missing per-spec pollIntervalSec falls back to branch-level interval.
    assert by_path["apis/events.yaml"].poll_interval_sec == 120
    # Files omitted from manifest still appear as untracked discoveries.
    assert by_path["apis/unlisted.yaml"].tracked is False
    assert by_path["apis/unlisted.yaml"].format == "json_schema"
