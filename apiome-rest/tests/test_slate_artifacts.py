"""Digest, signing and manifest rules for Slate artifacts — APX-3.1 (private-suite#2456).

Acceptance criterion 1 is that every build has content/source/config digests and an
immutable release id. These tests pin the properties that make those digests worth having:
they are stable across irrelevant variation, they are sensitive to relevant variation, they
cannot collide across purposes, and the signature over them cannot be forged or relabelled.
"""

from __future__ import annotations

import pytest

from app.slate_artifacts import (
    DIGEST_PATTERN,
    ArtifactDigests,
    SlateArtifactError,
    build_manifest,
    compute_config_digest,
    compute_content_digest,
    compute_source_digest,
    is_valid_digest,
    sign_digests,
    verify_signature,
)

KEY = "test-signing-key"
KEY_ID = "test-key-1"


def digests(
    content: bytes = b"<html>index</html>",
    source: dict | None = None,
    config: dict | None = None,
) -> ArtifactDigests:
    """Build a valid digest triple for tests."""
    return ArtifactDigests(
        content=compute_content_digest({"index.html": content}),
        source=compute_source_digest(source or {"catalogRevision": "rev-1"}),
        config=compute_config_digest(config or {"theme": "default"}),
    )


class TestDigestForm:
    def test_every_digest_matches_the_stored_and_wire_form(self):
        d = digests()
        for value in (d.content, d.source, d.config):
            assert DIGEST_PATTERN.match(value), value

    def test_is_valid_digest_rejects_non_strings_and_wrong_shapes(self):
        assert not is_valid_digest(None)
        assert not is_valid_digest(12345)
        assert not is_valid_digest("sha256:tooshort")
        assert not is_valid_digest("md5:" + "a" * 64)
        # Uppercase hex is not the canonical form; accepting it would let one artifact
        # have two spellings of the same identity.
        assert not is_valid_digest("sha256:" + "A" * 64)

    def test_a_malformed_digest_is_refused_at_construction(self):
        with pytest.raises(SlateArtifactError) as exc:
            ArtifactDigests(content="not-a-digest", source="x", config="y")
        assert exc.value.code == "malformed_digest"

    def test_digests_are_frozen_because_they_are_an_identity(self):
        d = digests()
        with pytest.raises(Exception):
            d.content = "sha256:" + "0" * 64  # type: ignore[misc]


class TestContentDigest:
    def test_identical_bytes_produce_an_identical_digest(self):
        files = {"a.html": b"one", "b.html": b"two"}
        assert compute_content_digest(files) == compute_content_digest(dict(files))

    def test_file_insertion_order_does_not_change_the_digest(self):
        # An identical rebuild on another machine must land on the same identity, or every
        # promotion would look like new bytes.
        first = compute_content_digest({"a.html": b"one", "b.html": b"two"})
        second = compute_content_digest({"b.html": b"two", "a.html": b"one"})
        assert first == second

    def test_changing_any_byte_changes_the_digest(self):
        assert compute_content_digest({"a.html": b"one"}) != compute_content_digest(
            {"a.html": b"onE"}
        )

    def test_renaming_a_file_changes_the_digest(self):
        assert compute_content_digest({"a.html": b"x"}) != compute_content_digest(
            {"b.html": b"x"}
        )

    def test_path_boundaries_are_unambiguous(self):
        # Without length-prefixed paths these two layouts could fold to the same hash input.
        assert compute_content_digest({"ab": b"", "c": b""}) != compute_content_digest(
            {"a": b"", "bc": b""}
        )

    def test_adding_a_file_changes_the_digest(self):
        base = {"a.html": b"one"}
        assert compute_content_digest(base) != compute_content_digest(
            {**base, "b.html": b"two"}
        )

    def test_an_empty_artifact_is_refused_rather_than_given_an_identity(self):
        with pytest.raises(SlateArtifactError) as exc:
            compute_content_digest({})
        assert exc.value.code == "empty_content"


class TestSourceAndConfigDigests:
    def test_key_order_does_not_change_a_source_digest(self):
        assert compute_source_digest({"a": 1, "b": 2}) == compute_source_digest(
            {"b": 2, "a": 1}
        )

    def test_changing_an_input_changes_the_source_digest(self):
        assert compute_source_digest({"rev": 1}) != compute_source_digest({"rev": 2})

    def test_changing_config_changes_the_config_digest(self):
        assert compute_config_digest({"theme": "a"}) != compute_config_digest(
            {"theme": "b"}
        )

    def test_source_and_config_digests_are_domain_separated(self):
        # The same mapping hashed for two different purposes must not collide, or a config
        # change could be engineered to look like no change at all.
        payload = {"same": "value"}
        assert compute_source_digest(payload) != compute_config_digest(payload)

    def test_content_digest_is_domain_separated_from_the_others(self):
        d = digests()
        assert len({d.content, d.source, d.config}) == 3


class TestSigning:
    def test_a_signature_verifies_against_its_own_digests(self):
        d = digests()
        assert verify_signature(d, sign_digests(d, key=KEY, key_id=KEY_ID), key=KEY, key_id=KEY_ID)

    def test_signing_is_deterministic(self):
        d = digests()
        assert sign_digests(d, key=KEY, key_id=KEY_ID) == sign_digests(
            d, key=KEY, key_id=KEY_ID
        )

    def test_a_signature_does_not_verify_under_a_different_key(self):
        d = digests()
        sig = sign_digests(d, key=KEY, key_id=KEY_ID)
        assert not verify_signature(d, sig, key="another-key", key_id=KEY_ID)

    def test_a_signature_cannot_be_relabelled_to_another_key_id(self):
        # The key id is inside the signed payload precisely so this fails.
        d = digests()
        sig = sign_digests(d, key=KEY, key_id=KEY_ID)
        assert not verify_signature(d, sig, key=KEY, key_id="rotated-key-2")

    def test_tampering_with_any_digest_invalidates_the_signature(self):
        d = digests()
        sig = sign_digests(d, key=KEY, key_id=KEY_ID)
        for swapped in (
            ArtifactDigests(content=digests(b"other").content, source=d.source, config=d.config),
            ArtifactDigests(content=d.content, source=compute_source_digest({"rev": 9}), config=d.config),
            ArtifactDigests(content=d.content, source=d.source, config=compute_config_digest({"theme": "z"})),
        ):
            assert not verify_signature(swapped, sig, key=KEY, key_id=KEY_ID)

    def test_an_empty_signature_never_verifies(self):
        d = digests()
        assert not verify_signature(d, "", key=KEY, key_id=KEY_ID)

    def test_an_empty_key_never_verifies(self):
        d = digests()
        sig = sign_digests(d, key=KEY, key_id=KEY_ID)
        assert not verify_signature(d, sig, key="", key_id=KEY_ID)

    def test_signing_without_a_key_is_refused_rather_than_producing_an_unsigned_artifact(self):
        with pytest.raises(SlateArtifactError) as exc:
            sign_digests(digests(), key="", key_id=KEY_ID)
        assert exc.value.code == "missing_signing_key"


class TestManifest:
    def test_manifest_records_digests_generator_and_inventory(self):
        d = digests()
        manifest = build_manifest(
            digests=d,
            generator="slate",
            generator_version="1.4.0",
            routes=["/b", "/a"],
            size_bytes=2048,
        )
        assert manifest["digests"] == d.as_dict()
        assert manifest["generator"] == {"name": "slate", "version": "1.4.0"}
        assert manifest["sizeBytes"] == 2048
        assert manifest["schemaVersion"] == 1

    def test_routes_are_sorted_so_identical_builds_do_not_produce_false_diffs(self):
        manifest = build_manifest(
            digests=digests(),
            generator="slate",
            generator_version="1.4.0",
            routes=["/z", "/a", "/m"],
            size_bytes=1,
        )
        assert manifest["routes"] == ["/a", "/m", "/z"]

    def test_page_count_is_derived_from_routes_rather_than_supplied(self):
        # A manifest whose page count can disagree with its route list is a manifest that
        # can lie about invalidation scope.
        manifest = build_manifest(
            digests=digests(),
            generator="slate",
            generator_version="1.4.0",
            routes=["/a", "/b", "/c"],
            size_bytes=1,
        )
        assert manifest["pageCount"] == 3

    def test_dependencies_and_inputs_default_to_empty_rather_than_absent(self):
        manifest = build_manifest(
            digests=digests(),
            generator="slate",
            generator_version="1.4.0",
            routes=["/a"],
            size_bytes=1,
        )
        assert manifest["dependencies"] == []
        assert manifest["sourceInputs"] == {}
        assert manifest["config"] == {}

    def test_manifest_is_json_serializable(self):
        import json

        manifest = build_manifest(
            digests=digests(),
            generator="slate",
            generator_version="1.4.0",
            routes=["/a"],
            size_bytes=1,
            dependencies=[{"name": "markdown-it", "version": "14.0.0"}],
        )
        assert json.loads(json.dumps(manifest))["dependencies"][0]["name"] == "markdown-it"
