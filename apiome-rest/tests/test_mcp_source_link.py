"""Source reference parsing, canonicalization, and pin strength (CLX-3.2, #4856).

The central property under test is that pin strength is *derived from the reference*, never asserted
by the caller: a source is ``digest_pinned`` only when its reference actually carries an immutable
digest, and ``unverified`` otherwise. The V172 CHECK constraint depends on this being true.
"""

from __future__ import annotations

import pytest

from app.mcp_source_link import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    PROVENANCE_ATTESTED,
    SOURCE_GIT,
    SOURCE_IMAGE,
    SOURCE_PACKAGE,
    SOURCE_REGISTRY,
    VERIFICATION_ATTESTED,
    VERIFICATION_PINNED,
    VERIFICATION_UNVERIFIED,
    SourceReferenceError,
    confidence_for_link,
    link_from_row,
    parse_source_reference,
)

_COMMIT = "a" * 40


def test_git_branch_is_unverified():
    link = parse_source_reference(SOURCE_GIT, "https://github.com/acme/srv", revision="main")
    assert link.verification_state == VERIFICATION_UNVERIFIED
    assert link.digest is None
    assert not link.is_pinned


def test_git_full_commit_pins():
    link = parse_source_reference(SOURCE_GIT, "https://github.com/acme/srv", revision=_COMMIT)
    assert link.verification_state == VERIFICATION_PINNED
    assert link.digest == _COMMIT
    assert link.digest_algorithm == "sha1"


def test_git_short_sha_does_not_pin():
    # An abbreviated sha is ambiguous, and an ambiguous pin is not a pin.
    link = parse_source_reference(SOURCE_GIT, "https://github.com/acme/srv", revision="a1b2c3d")
    assert link.verification_state == VERIFICATION_UNVERIFIED


def test_git_locator_canonicalizes_scp_and_git_suffix():
    scp = parse_source_reference(SOURCE_GIT, "git@github.com:Acme/Srv.git", revision="main")
    https = parse_source_reference(SOURCE_GIT, "https://github.com/Acme/Srv", revision="main")
    assert scp.locator == https.locator == "https://github.com/Acme/Srv"


def test_git_locator_strips_embedded_credentials():
    link = parse_source_reference(
        SOURCE_GIT, "https://user:token@github.com/acme/srv", revision="main"
    )
    assert "token" not in link.locator
    assert link.locator == "https://github.com/acme/srv"


def test_git_rejects_file_scheme():
    # A source reference is a public coordinate, not a path into the host running Apiome.
    with pytest.raises(SourceReferenceError):
        parse_source_reference(SOURCE_GIT, "file:///etc/passwd")


def test_package_exact_version_pins():
    link = parse_source_reference(SOURCE_PACKAGE, "pkg:npm/left-pad@1.3.0")
    assert link.verification_state == VERIFICATION_PINNED
    assert link.purl == "pkg:npm/left-pad@1.3.0"


def test_package_range_does_not_pin():
    link = parse_source_reference(SOURCE_PACKAGE, "pkg:npm/left-pad@^1.3.0")
    assert link.verification_state == VERIFICATION_UNVERIFIED


def test_package_dist_tag_does_not_pin():
    link = parse_source_reference(SOURCE_PACKAGE, "pkg:npm/left-pad@latest")
    assert link.verification_state == VERIFICATION_UNVERIFIED


def test_package_requires_purl():
    with pytest.raises(SourceReferenceError):
        parse_source_reference(SOURCE_PACKAGE, "left-pad@1.0.0")


def test_image_digest_pins_and_tag_does_not():
    pinned = parse_source_reference(
        SOURCE_IMAGE, "ghcr.io/acme/srv@sha256:" + "b" * 64
    )
    assert pinned.verification_state == VERIFICATION_PINNED
    assert pinned.digest == "sha256:" + "b" * 64

    tagged = parse_source_reference(SOURCE_IMAGE, "ghcr.io/acme/srv:v1")
    assert tagged.verification_state == VERIFICATION_UNVERIFIED
    assert tagged.revision == "v1"


def test_image_registry_port_is_not_a_tag():
    link = parse_source_reference(SOURCE_IMAGE, "registry:5000/acme/srv:v2")
    assert link.locator == "registry:5000/acme/srv:v2"
    assert link.revision == "v2"


def test_image_bad_digest_algorithm_rejected():
    with pytest.raises(SourceReferenceError):
        parse_source_reference(SOURCE_IMAGE, "acme/srv@md5:deadbeef")


def test_registry_digest_revision_pins():
    link = parse_source_reference(
        SOURCE_REGISTRY, "io.acme/server", revision="sha256:" + "c" * 64
    )
    assert link.verification_state == VERIFICATION_PINNED


def test_attested_only_upgrades_a_pinned_link():
    # An attestation over a moving reference still does not tell you which artifact is running.
    unpinned = parse_source_reference(
        SOURCE_GIT, "https://github.com/acme/srv", revision="main", attested=True
    )
    assert unpinned.verification_state == VERIFICATION_UNVERIFIED

    pinned = parse_source_reference(
        SOURCE_GIT, "https://github.com/acme/srv", revision=_COMMIT, attested=True
    )
    assert pinned.verification_state == VERIFICATION_ATTESTED


def test_provenance_is_carried_never_inferred():
    link = parse_source_reference(
        SOURCE_GIT,
        "https://github.com/acme/srv",
        revision=_COMMIT,
        provenance=PROVENANCE_ATTESTED,
    )
    assert link.provenance == PROVENANCE_ATTESTED


def test_confidence_downgrades_for_unpinned_source():
    unpinned = parse_source_reference(SOURCE_GIT, "https://github.com/acme/srv", revision="main")
    pinned = parse_source_reference(SOURCE_GIT, "https://github.com/acme/srv", revision=_COMMIT)
    assert confidence_for_link(unpinned) == CONFIDENCE_MEDIUM
    assert confidence_for_link(pinned) == CONFIDENCE_HIGH
    # Surface evidence (no source) is always reproducible from the stored snapshot.
    assert confidence_for_link(None) == CONFIDENCE_HIGH


def test_link_round_trips_through_row():
    link = parse_source_reference(SOURCE_GIT, "https://github.com/acme/srv", revision=_COMMIT)
    row = {**link.as_dict(), "id": "x"}
    rebuilt = link_from_row(row)
    assert rebuilt == link


def test_parsing_is_deterministic():
    a = parse_source_reference(SOURCE_PACKAGE, "pkg:npm/%40scope/pkg@2.0.0")
    b = parse_source_reference(SOURCE_PACKAGE, "pkg:npm/%40scope/pkg@2.0.0")
    assert a == b


def test_unknown_kind_and_provenance_rejected():
    with pytest.raises(SourceReferenceError):
        parse_source_reference("svn", "https://x")
    with pytest.raises(SourceReferenceError):
        parse_source_reference(SOURCE_GIT, "https://github.com/a/b", provenance="trust-me")
