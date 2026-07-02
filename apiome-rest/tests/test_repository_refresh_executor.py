"""Spec-faithful auto-refresh hydration tests (RAR-4.1, #3527).

Deterministic, DB-free unit tests over ``app.repository_refresh_executor``. They
pin the RAR-4.1 contract on the REST side: a refresh job row enqueued by the
RAR-3.2 sweep is hydrated into worker metadata stamped with the synthetic
``repository_auto_import`` source kind, carrying the stored spec snapshot
(source descriptor + verbatim options blob) so the worker replays the original
import instead of importer defaults.

The headline test is the golden fixture: the options blob captured at first import
round-trips byte-identically into the worker metadata.
"""

import pytest

from app.models import (
    REPOSITORY_AUTO_IMPORT_SOURCE_KIND,
    SpecImportProjectTarget,
    SpecImportVersionTarget,
)
from app.repository_refresh_executor import (
    build_auto_refresh_import_metadata,
    build_refresh_provenance_from_job,
    build_stored_spec_from_refresh_job,
)

# Non-default options the user submitted at first import, in the verbatim camelCase
# shape persisted to ``repository_import_spec.options_json`` — naming convention +
# class prefix + type mapping, the advanced options the acceptance criteria call out.
ORIGINAL_OPTIONS = {
    "selectedSchemas": ["Pet"],
    "applyNamingConvention": True,
    "classNamingConvention": "camelCase",
    "classPrefix": "Api",
    "typeMapping": {"string": {"type": "string", "format": "text"}},
    "generateExamples": True,
}


def _refresh_job_row(**overrides):
    """A refresh job row as ``enqueue_repository_refresh_job`` returns it."""
    row = {
        "id": "refresh-1",
        "tenant_id": "t1",
        "repository_id": "repo-1",
        "import_spec_id": "spec-1",
        "branch": "main",
        "path": "specs/petstore.json",
        "project_id": "proj-1",
        "source_kind": "openapi-3",
        "format_override": "swagger",
        "content_type": "application/json",
        "options_json": dict(ORIGINAL_OPTIONS),
        "spec_schema_version": 1,
    }
    row.update(overrides)
    return row


def _project():
    return SpecImportProjectTarget(name="Petstore", slug="petstore")


def _version():
    return SpecImportVersionTarget(version_id="1.0.1")


def test_golden_fixture_options_round_trip_into_worker_metadata():
    """The stored options blob is replayed verbatim — the acceptance criterion."""
    meta = build_auto_refresh_import_metadata(
        _refresh_job_row(),
        project=_project(),
        version=_version(),
        existing_project_id="proj-1",
    )

    assert meta.source_kind == REPOSITORY_AUTO_IMPORT_SOURCE_KIND
    assert meta.existing_project_id == "proj-1"
    assert meta.repository_import_spec is not None
    spec = meta.repository_import_spec
    # Verbatim, byte-identical option application vs the original import.
    assert spec.options == ORIGINAL_OPTIONS
    # The source descriptor is carried so the worker routes/parses identically.
    assert spec.source_kind == "openapi-3"
    assert spec.format_override == "swagger"
    assert spec.content_type == "application/json"


def test_stored_spec_from_job_row_maps_descriptor_and_options():
    spec = build_stored_spec_from_refresh_job(_refresh_job_row())
    assert spec.source_kind == "openapi-3"
    assert spec.format_override == "swagger"
    assert spec.content_type == "application/json"
    assert spec.options["classPrefix"] == "Api"
    assert spec.spec_schema_version == 1


def test_options_json_accepts_a_json_encoded_string():
    """A cursor that surfaces JSONB as text is decoded transparently."""
    import json

    row = _refresh_job_row(options_json=json.dumps(ORIGINAL_OPTIONS))
    spec = build_stored_spec_from_refresh_job(row)
    assert spec.options == ORIGINAL_OPTIONS


def test_missing_options_blob_replays_as_empty_defaults():
    for empty in (None, "", "   ", {}):
        spec = build_stored_spec_from_refresh_job(_refresh_job_row(options_json=empty))
        assert spec.options == {}


def test_absent_spec_schema_version_falls_back_to_current():
    spec = build_stored_spec_from_refresh_job(_refresh_job_row(spec_schema_version=None))
    assert spec.spec_schema_version == 1


def test_missing_source_kind_is_a_clear_error():
    with pytest.raises(ValueError, match="missing source_kind"):
        build_stored_spec_from_refresh_job(_refresh_job_row(source_kind=None))
    with pytest.raises(ValueError, match="missing source_kind"):
        build_stored_spec_from_refresh_job(_refresh_job_row(source_kind="  "))


def test_invalid_options_json_string_is_rejected():
    with pytest.raises(ValueError):
        build_stored_spec_from_refresh_job(_refresh_job_row(options_json="not-json"))
    with pytest.raises(ValueError, match="JSON object"):
        build_stored_spec_from_refresh_job(_refresh_job_row(options_json="[1, 2, 3]"))


# --- RAR-4.2: refresh provenance (#3528) -----------------------------------

_COMMIT_SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
_COMMITTED_AT = "2026-06-22T10:00:00Z"


def test_provenance_maps_remote_commit_signals_and_parent():
    """The new version's provenance carries the prior version + source commit."""
    row = _refresh_job_row(
        remote_commit_sha=_COMMIT_SHA, remote_committed_at=_COMMITTED_AT
    )
    prov = build_refresh_provenance_from_job(row, parent_version_id="prior-version-uuid")
    assert prov.parent_version_id == "prior-version-uuid"
    assert prov.source_commit_sha == _COMMIT_SHA
    assert prov.source_committed_at == _COMMITTED_AT


def test_provenance_first_revision_has_no_parent():
    """A refresh producing the first revision in a project records a null parent."""
    row = _refresh_job_row(
        remote_commit_sha=_COMMIT_SHA, remote_committed_at=_COMMITTED_AT
    )
    prov = build_refresh_provenance_from_job(row, parent_version_id=None)
    assert prov.parent_version_id is None
    assert prov.source_commit_sha == _COMMIT_SHA


def test_provenance_blanks_are_normalized_to_none():
    """Blank/whitespace commit signals and parent collapse to None, not empty strings."""
    row = _refresh_job_row(remote_commit_sha="   ", remote_committed_at=None)
    prov = build_refresh_provenance_from_job(row, parent_version_id="  ")
    assert prov.parent_version_id is None
    assert prov.source_commit_sha is None
    assert prov.source_committed_at is None


def test_metadata_carries_refresh_provenance():
    """build_auto_refresh_import_metadata attaches the RAR-4.2 provenance."""
    row = _refresh_job_row(
        remote_commit_sha=_COMMIT_SHA, remote_committed_at=_COMMITTED_AT
    )
    meta = build_auto_refresh_import_metadata(
        row,
        project=_project(),
        version=_version(),
        existing_project_id="proj-1",
        parent_version_id="prior-version-uuid",
    )
    assert meta.refresh_provenance is not None
    assert meta.refresh_provenance.parent_version_id == "prior-version-uuid"
    assert meta.refresh_provenance.source_commit_sha == _COMMIT_SHA
    assert meta.refresh_provenance.source_committed_at == _COMMITTED_AT
    # The spec-faithful payload (RAR-4.1) is still present alongside provenance.
    assert meta.repository_import_spec is not None
