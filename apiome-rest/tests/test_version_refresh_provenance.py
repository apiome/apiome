"""Version refresh-provenance model + migration guard tests (RAR-4.2, #3528).

Deterministic, DB-free unit tests pinning the RAR-4.2 contract on the REST side:
a version exposes its refresh provenance (source commit + committed-at) over the
version API, version creation accepts those signals, and the migration that adds
the backing columns survives accidental edits.
"""

from pathlib import Path

from app.models import (
    RepositoryRefreshProvenance,
    VersionCreateRequest,
    VersionSchema,
)

_MIGRATION = "apiome-db/scripts/V110__refresh_provenance_on_schema_revisions_r.sql"

_COMMIT_SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
_COMMITTED_AT = "2026-06-22T10:00:00Z"


# --- Version API surfacing -------------------------------------------------

def test_version_schema_surfaces_provenance_from_db_row():
    """A db row's snake_case provenance columns surface on the version API."""
    row = {
        "id": "v2",
        "project_id": "p1",
        "version_id": "1.0.1",
        "parent_version_id": "v1",
        "source_commit_sha": _COMMIT_SHA,
        "source_committed_at": _COMMITTED_AT,
    }
    schema = VersionSchema.model_validate(row)
    assert schema.parent_version_id == "v1"
    assert schema.source_commit_sha == _COMMIT_SHA
    assert schema.source_committed_at == _COMMITTED_AT


def test_version_schema_serializes_provenance_as_camelcase():
    """The version API wire shape exposes provenance as camelCase (RAR-4.2)."""
    schema = VersionSchema.model_validate(
        {
            "id": "v2",
            "project_id": "p1",
            "version_id": "1.0.1",
            "source_commit_sha": _COMMIT_SHA,
            "source_committed_at": _COMMITTED_AT,
        }
    )
    wire = schema.model_dump(by_alias=True)
    assert wire["sourceCommitSha"] == _COMMIT_SHA
    assert wire["sourceCommittedAt"] == _COMMITTED_AT


def test_version_schema_provenance_defaults_to_none():
    """Hand-authored revisions (no provenance columns) report null provenance."""
    schema = VersionSchema.model_validate(
        {"id": "v1", "project_id": "p1", "version_id": "1.0.0"}
    )
    assert schema.source_commit_sha is None
    assert schema.source_committed_at is None


# --- Version creation request ---------------------------------------------

def test_version_create_request_accepts_camelcase_provenance():
    req = VersionCreateRequest.model_validate(
        {
            "baseRevisionId": "",
            "sourceCommitSha": _COMMIT_SHA,
            "sourceCommittedAt": _COMMITTED_AT,
        }
    )
    assert req.source_commit_sha == _COMMIT_SHA
    assert req.source_committed_at == _COMMITTED_AT


def test_version_create_request_accepts_snakecase_provenance():
    req = VersionCreateRequest.model_validate(
        {
            "base_revision_id": "",
            "source_commit_sha": _COMMIT_SHA,
            "source_committed_at": _COMMITTED_AT,
        }
    )
    assert req.source_commit_sha == _COMMIT_SHA
    assert req.source_committed_at == _COMMITTED_AT


def test_version_create_request_provenance_optional():
    req = VersionCreateRequest.model_validate({"baseRevisionId": ""})
    assert req.source_commit_sha is None
    assert req.source_committed_at is None


# --- Provenance model ------------------------------------------------------

def test_repository_refresh_provenance_round_trips():
    prov = RepositoryRefreshProvenance(
        parent_version_id="v1",
        source_commit_sha=_COMMIT_SHA,
        source_committed_at=_COMMITTED_AT,
    )
    assert prov.parent_version_id == "v1"
    assert prov.source_commit_sha == _COMMIT_SHA
    assert prov.source_committed_at == _COMMITTED_AT


# --- Migration guard -------------------------------------------------------

_REQUIRED_FRAGMENTS = (
    "ALTER TABLE versions",
    "ADD COLUMN IF NOT EXISTS source_commit_sha VARCHAR(64)",
    "ADD COLUMN IF NOT EXISTS source_committed_at TIMESTAMPTZ",
    "idx_versions_source_commit_sha",
    "WHERE source_commit_sha IS NOT NULL",
)


def test_migration_adds_provenance_columns(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    missing = [frag for frag in _REQUIRED_FRAGMENTS if frag not in text]
    assert not missing, f"Migration missing expected fragments: {missing}"
