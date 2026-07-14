"""SBOM ingestion and lockfile-derived inventory (CLX-3.2, #4856).

The property that matters most: an inventory carries **coordinates only**. There is no code path
here that retains source or file content, and a malformed component is *counted*, never silently
dropped — a parse failure must not look like a clean, dependency-free artifact.
"""

from __future__ import annotations

import pytest

from app.mcp_sbom import (
    FORMAT_CYCLONEDX,
    FORMAT_MANIFEST,
    FORMAT_SPDX,
    ORIGIN_DERIVED,
    ORIGIN_SUPPLIED,
    SbomFormatError,
    derive_inventory,
    parse_cyclonedx,
    parse_sbom,
    parse_spdx,
)


def _cyclonedx(components):
    return {"bomFormat": "CycloneDX", "specVersion": "1.5", "components": components}


def test_cyclonedx_reads_coordinates():
    inv = parse_cyclonedx(
        _cyclonedx(
            [
                {
                    "name": "left-pad",
                    "version": "1.3.0",
                    "purl": "pkg:npm/left-pad@1.3.0",
                    "licenses": [{"license": {"id": "MIT"}}],
                    "scope": "required",
                }
            ]
        )
    )
    assert inv.sbom_format == FORMAT_CYCLONEDX
    assert inv.origin == ORIGIN_SUPPLIED
    assert inv.component_count == 1
    c = inv.components[0]
    assert (c.name, c.version, c.purl, c.license) == (
        "left-pad",
        "1.3.0",
        "pkg:npm/left-pad@1.3.0",
        "MIT",
    )


def test_cyclonedx_skips_unnamed_components_and_counts_them():
    inv = parse_cyclonedx(_cyclonedx([{"version": "1.0"}, {"name": "ok", "version": "2.0"}]))
    assert inv.component_count == 1
    assert inv.skipped_components == 1


def test_cyclonedx_wrong_format_rejected():
    with pytest.raises(SbomFormatError):
        parse_cyclonedx({"bomFormat": "SPDX"})


def test_spdx_reads_purl_and_normalizes_noassertion():
    doc = {
        "spdxVersion": "SPDX-2.3",
        "packages": [
            {
                "name": "requests",
                "versionInfo": "2.31.0",
                "licenseDeclared": "Apache-2.0",
                "externalRefs": [
                    {
                        "referenceType": "purl",
                        "referenceLocator": "pkg:pypi/requests@2.31.0",
                    }
                ],
            },
            {"name": "mystery", "versionInfo": "NOASSERTION", "licenseDeclared": "NOASSERTION"},
        ],
    }
    inv = parse_spdx(doc)
    assert inv.sbom_format == FORMAT_SPDX
    reqs = next(c for c in inv.components if c.name == "requests")
    assert reqs.purl == "pkg:pypi/requests@2.31.0"
    mystery = next(c for c in inv.components if c.name == "mystery")
    # NOASSERTION is normalized away rather than stored as a license/version.
    assert mystery.version is None
    assert mystery.license is None


def test_parse_sbom_detects_format():
    assert parse_sbom(_cyclonedx([])).sbom_format == FORMAT_CYCLONEDX
    assert parse_sbom({"spdxVersion": "SPDX-2.3", "packages": []}).sbom_format == FORMAT_SPDX
    with pytest.raises(SbomFormatError):
        parse_sbom({"nope": True})


def test_derive_inventory_from_lockfiles():
    inv, unparsed = derive_inventory(
        {
            "requirements.txt": "requests==2.31.0\nflask>=2\n# comment\n",
            "go.mod": "module x\nrequire example.com/m v1.2.3\n",
        }
    )
    assert inv.origin == ORIGIN_DERIVED
    assert inv.sbom_format == FORMAT_MANIFEST
    purls = inv.purls()
    assert "pkg:pypi/requests@2.31.0" in purls
    assert "pkg:golang/example.com/m@v1.2.3" in purls
    # flask has no exact pin -> not recorded (a guessed version would attach real CVEs to a version
    # nobody installed).
    assert not any("flask" in p for p in purls)
    assert unparsed == ()


def test_derive_inventory_reports_unparsable_manifests():
    inv, unparsed = derive_inventory(
        {"package-lock.json": "{ not json", "Cargo.lock": "unsupported"}
    )
    # An inventory derived from files it could not read is visibly partial.
    assert "package-lock.json" in unparsed
    assert "Cargo.lock" in unparsed


def test_scanned_manifests_are_paths_only():
    inv, _ = derive_inventory({"services/api/requirements.txt": "requests==2.31.0\n"})
    assert inv.scanned_manifests == ("services/api/requirements.txt",)


def test_inventory_is_deterministic_and_fingerprint_order_independent():
    a = parse_cyclonedx(_cyclonedx([{"name": "b", "version": "1"}, {"name": "a", "version": "2"}]))
    b = parse_cyclonedx(_cyclonedx([{"name": "a", "version": "2"}, {"name": "b", "version": "1"}]))
    assert a.fingerprint() == b.fingerprint()
    assert [c.name for c in a.components] == ["a", "b"]


def test_inventory_dict_has_no_source_fields():
    inv = parse_cyclonedx(_cyclonedx([{"name": "x", "version": "1", "purl": "pkg:npm/x@1"}]))
    payload = inv.as_dict()
    serialized = str(payload)
    for forbidden in ("source", "content", "code", "text"):
        # component dicts only carry name/version/purl/license/scope
        assert all(
            forbidden not in comp for comp in payload["components"][0]
        ), f"component leaked a '{forbidden}' field: {serialized}"
