"""Scanner verification for OA1 (#3498) — OpenAPI 3.2 files are still classified.

``detected_kind_from_path`` keys on the filename, not the document version, so an
OpenAPI 3.2.0 file is expected to yield ``openapi-candidate`` with no code change.
This test pins that behaviour so a future filename-classification change does not
silently drop 3.2 specs before they reach the importer.
"""

import pytest

from app.repository_file_scan import detected_kind_from_path


@pytest.mark.parametrize(
    "path",
    [
        "openapi.yaml",
        "openapi.yml",
        "openapi.json",
        "api/openapi-3.2.0.yaml",
        "specs/my-openapi.json",
        "swagger.yaml",
    ],
)
def test_openapi_filenames_are_candidates_regardless_of_version(path: str) -> None:
    # Filename-only classification: version (3.0/3.1/3.2) is irrelevant here.
    assert detected_kind_from_path(path) == "openapi-candidate"


def test_non_openapi_filenames_are_not_openapi_candidates() -> None:
    assert detected_kind_from_path("arazzo.yaml") == "arazzo-candidate"
    assert detected_kind_from_path("README.md") is None
