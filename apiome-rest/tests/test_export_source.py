"""Tests for the export-source loader — (tenant, artifact, version) → canonical model — MFX-2.5 (#3842).

Pins :func:`app.export_source.load_export_source`:

* version resolution — a null selector uses the latest revision; a version label is mapped to its
  revision; a revision UUID is used directly;
* tenant/artifact scoping — a projection for a different artifact, or a missing revision, is 404;
* failure mapping — a source with nothing to reconstruct surfaces the convert path's 422.

The DB and the reconstruction (:func:`app.catalog_conversion.build_conversion_source`) are faked —
their own logic is covered elsewhere — so these tests pin only the loader's resolution + mapping.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi
from app.conversion_job import ConversionError, ConversionSource
from app.export_source import ExportSourceError, load_export_source

_REV_UUID = "11111111-1111-4111-8111-111111111111"


def _api() -> CanonicalApi:
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="widgets"),
    )


def _conversion_source() -> ConversionSource:
    return ConversionSource(api=_api(), source_project_id="artifact-1")


def _projection(artifact_id: str = "artifact-1") -> dict:
    return {
        "id": artifact_id,
        "project_slug": "widgets",
        "version_label": "1.0.0",
        "source_format": "graphql",
        "protocol": None,
        "format_metadata": {"sourceContent": "type Query { ping: String }"},
        "tool_versions": {},
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# Version resolution
# ---------------------------------------------------------------------------
def test_load_latest_when_version_omitted():
    """A null version selector resolves to the artifact's latest revision."""
    with patch("app.export_source.db") as db, patch(
        "app.export_source.build_conversion_source", return_value=_conversion_source()
    ):
        db.get_latest_revision_id_for_project.return_value = _REV_UUID
        db.get_version_source_projection.return_value = _projection()
        source = load_export_source("tenant-1", "artifact-1", None)

    db.get_latest_revision_id_for_project.assert_called_once_with("artifact-1", "tenant-1")
    assert source.version_record_id == _REV_UUID
    assert source.artifact_id == "artifact-1"
    assert source.version_label == "1.0.0"


def test_load_by_version_label_maps_to_revision():
    """A non-UUID version selector is resolved via the version-label lookup."""
    with patch("app.export_source.db") as db, patch(
        "app.export_source.build_conversion_source", return_value=_conversion_source()
    ):
        db.get_version_by_version_id.return_value = {"id": _REV_UUID}
        db.get_version_source_projection.return_value = _projection()
        source = load_export_source("tenant-1", "artifact-1", "1.0.0")

    db.get_version_by_version_id.assert_called_once_with("artifact-1", "1.0.0", "tenant-1")
    db.get_latest_revision_id_for_project.assert_not_called()
    assert source.version_record_id == _REV_UUID


def test_load_by_revision_uuid_skips_label_lookup():
    """A UUID version selector is used directly as the revision id (no label lookup)."""
    with patch("app.export_source.db") as db, patch(
        "app.export_source.build_conversion_source", return_value=_conversion_source()
    ):
        db.get_version_source_projection.return_value = _projection()
        source = load_export_source("tenant-1", "artifact-1", _REV_UUID)

    db.get_version_by_version_id.assert_not_called()
    db.get_latest_revision_id_for_project.assert_not_called()
    db.get_version_source_projection.assert_called_once_with(_REV_UUID, "tenant-1")
    assert source.version_record_id == _REV_UUID


# ---------------------------------------------------------------------------
# Not-found scoping (404)
# ---------------------------------------------------------------------------
def test_404_when_artifact_has_no_versions():
    with patch("app.export_source.db") as db:
        db.get_latest_revision_id_for_project.return_value = None
        with pytest.raises(ExportSourceError) as exc:
            load_export_source("tenant-1", "artifact-1", None)
    assert exc.value.status_code == 404


def test_404_when_version_label_not_found():
    with patch("app.export_source.db") as db:
        db.get_version_by_version_id.return_value = None
        with pytest.raises(ExportSourceError) as exc:
            load_export_source("tenant-1", "artifact-1", "9.9.9")
    assert exc.value.status_code == 404


def test_404_when_projection_missing():
    with patch("app.export_source.db") as db:
        db.get_version_source_projection.return_value = None
        with pytest.raises(ExportSourceError) as exc:
            load_export_source("tenant-1", "artifact-1", _REV_UUID)
    assert exc.value.status_code == 404


def test_404_when_revision_belongs_to_other_artifact():
    """A revision that resolves to a different artifact than requested is 404, not cross-served."""
    with patch("app.export_source.db") as db:
        db.get_version_source_projection.return_value = _projection(artifact_id="other-artifact")
        with pytest.raises(ExportSourceError) as exc:
            load_export_source("tenant-1", "artifact-1", _REV_UUID)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Reconstruction failure mapping (422)
# ---------------------------------------------------------------------------
def test_422_when_source_cannot_be_reconstructed():
    """A revision with no captured source surfaces the convert path's 422."""
    with patch("app.export_source.db") as db, patch(
        "app.export_source.build_conversion_source",
        side_effect=ConversionError("no captured source", status_code=422),
    ):
        db.get_version_source_projection.return_value = _projection()
        with pytest.raises(ExportSourceError) as exc:
            load_export_source("tenant-1", "artifact-1", _REV_UUID)
    assert exc.value.status_code == 422
