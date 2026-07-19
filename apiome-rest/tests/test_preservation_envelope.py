"""Preservation envelope golden corpus and operations — DCW-2.1 (private-suite#2352).

Acceptance coverage:

* supported, unsupported-but-valid, and ``x-*`` values round-trip semantically
  unchanged over the OAS 3.1 and supported 3.2 golden fixtures;
* the corpus covers unknown fields under arrays, ``$ref`` siblings, move and
  canonical-delete, and null/false/empty extension values;
* canonical and preserved claims for the same pointer are rejected
  deterministically;
* array insertion/reordering, pointer moves, canonical deletions, and
  collisions behave deterministically;
* semantic fingerprints report the intentionally excluded lexical differences.
"""

from pathlib import Path

import pytest
import yaml

from app.preservation_envelope import (
    ENVELOPE_VERSION,
    PreservationClaim,
    PreservationEnvelope,
    apply_envelope,
    delete_canonical_subtree,
    extract_envelope,
    format_pointer,
    move_claims,
    parse_pointer,
    pointer_exists,
    semantic_fingerprint,
    validate_envelope,
)

FIXTURES = Path(__file__).parent / "fixtures" / "preservation"


def _load(name: str):
    return yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def golden_31():
    return _load("golden-3.1-source.yaml"), _load("golden-3.1-canonical.yaml")


@pytest.fixture(scope="module")
def golden_32():
    return _load("golden-3.2-source.yaml"), _load("golden-3.2-canonical.yaml")


class TestPointerUtils:
    def test_parse_and_format_round_trip(self):
        for pointer in ["", "/a", "/a/0/b", "/paths/~1widgets/get", "/odd~0key"]:
            assert format_pointer(parse_pointer(pointer)) == pointer

    def test_escaping(self):
        assert parse_pointer("/paths/~1widgets") == ["paths", "/widgets"]
        assert parse_pointer("/a~0b") == ["a~b"]

    def test_invalid_pointer_raises(self):
        with pytest.raises(ValueError):
            parse_pointer("no-slash")

    def test_pointer_exists(self):
        doc = {"a": [{"b": None}]}
        assert pointer_exists(doc, "/a/0/b")  # a stored null still exists
        assert not pointer_exists(doc, "/a/1")
        assert not pointer_exists(doc, "/missing")


class TestGoldenRoundTrip:
    """merge(extract(source)) must equal the source semantically, both dialects."""

    def _round_trip(self, source, canonical, dialect):
        envelope = extract_envelope(source, canonical, dialect)
        report = validate_envelope(envelope, canonical)
        assert report.ok, [e.model_dump() for e in report.errors]
        merged, errors = apply_envelope(canonical, envelope)
        assert errors == []
        assert merged == source
        assert (
            semantic_fingerprint(merged).fingerprint
            == semantic_fingerprint(source).fingerprint
        )
        return envelope

    def test_31_round_trip(self, golden_31):
        source, canonical = golden_31
        envelope = self._round_trip(source, canonical, "3.1.0")
        pointers = {c.pointer for c in envelope.claims}
        # Unknown fields under array elements.
        assert "/servers/0/x-region" in pointers
        assert "/tags/0/x-display-order" in pointers
        # $ref sibling.
        assert (
            "/components/schemas/Widget/properties/legacyRef/x-deprecated-alias"
            in pointers
        )
        # Unsupported-but-valid families.
        assert "/webhooks" in pointers
        assert "/components/links" in pointers
        assert "/paths/~1widgets/get/callbacks" in pointers
        # null / false / empty extension values, preserved verbatim.
        claims = {c.pointer: c.value for c in envelope.claims}
        assert claims["/info/x-audience"] is None
        assert claims["/paths/~1widgets/get/x-internal"] is False
        assert claims["/components/schemas/Widget/x-empty-annotations"] == {}
        assert claims["/components/schemas/Widget/x-empty-list"] == []

    def test_32_round_trip(self, golden_32):
        source, canonical = golden_32
        envelope = self._round_trip(source, canonical, "3.2.0")
        pointers = {c.pointer for c in envelope.claims}
        assert "/$self" in pointers
        assert "/paths/~1widgets/query" in pointers
        assert "/tags/0/kind" in pointers
        assert "/tags/1/parent" in pointers
        claims = {c.pointer: c.value for c in envelope.claims}
        assert claims["/components/schemas/Widget/x-storage-hint"] is None

    def test_extraction_does_not_mutate_inputs(self, golden_31):
        source, canonical = golden_31
        import copy

        source_snapshot = copy.deepcopy(source)
        canonical_snapshot = copy.deepcopy(canonical)
        extract_envelope(source, canonical, "3.1.0")
        assert source == source_snapshot
        assert canonical == canonical_snapshot

    def test_provenance_metadata_stamped(self, golden_31):
        source, canonical = golden_31
        envelope = extract_envelope(
            source,
            canonical,
            "3.1.0",
            source_file="openapi.yaml",
            source_digest="sha256:abc",
        )
        assert envelope.claims
        assert all(c.source_file == "openapi.yaml" for c in envelope.claims)
        assert all(c.source_digest == "sha256:abc" for c in envelope.claims)

    def test_envelope_version_stamped(self, golden_31):
        source, canonical = golden_31
        envelope = extract_envelope(source, canonical, "3.1.0")
        assert envelope.envelope_version == ENVELOPE_VERSION


class TestValidation:
    CANONICAL = {"openapi": "3.1.0", "info": {"title": "T", "version": "1"}}

    def _envelope(self, *claims):
        return PreservationEnvelope(dialect="3.1.0", claims=list(claims))

    def test_collision_with_canonical_rejected_deterministically(self):
        envelope = self._envelope(
            PreservationClaim(pointer="/info/title", value="X"),
            PreservationClaim(pointer="/openapi", value="9.9.9"),
        )
        first = validate_envelope(envelope, self.CANONICAL)
        second = validate_envelope(envelope, self.CANONICAL)
        assert not first.ok
        assert [e.model_dump() for e in first.errors] == [
            e.model_dump() for e in second.errors
        ]
        assert [e.code for e in first.errors] == [
            "PRESERVATION_POINTER_COLLISION",
            "PRESERVATION_POINTER_COLLISION",
        ]
        # Deterministic order: shallower pointers sort first.
        assert [e.pointer for e in first.errors] == ["/openapi", "/info/title"]

    def test_unsupported_dialect_rejected(self):
        envelope = PreservationEnvelope(dialect="2.0", claims=[])
        report = validate_envelope(envelope, self.CANONICAL)
        assert not report.ok
        assert report.errors[0].code == "PRESERVATION_DIALECT_UNSUPPORTED"

    def test_duplicate_pointer_rejected(self):
        envelope = self._envelope(
            PreservationClaim(pointer="/x-a", value=1),
            PreservationClaim(pointer="/x-a", value=2),
        )
        report = validate_envelope(envelope, self.CANONICAL)
        assert not report.ok
        assert any(e.code == "PRESERVATION_DUPLICATE_POINTER" for e in report.errors)

    def test_nested_claim_rejected(self):
        envelope = self._envelope(
            PreservationClaim(pointer="/x-cfg", value={"a": 1}),
            PreservationClaim(pointer="/x-cfg/b", value=2),
        )
        report = validate_envelope(envelope, self.CANONICAL)
        assert not report.ok
        assert any(e.code == "PRESERVATION_NESTED_CLAIM" for e in report.errors)

    def test_root_and_malformed_pointers_rejected(self):
        envelope = self._envelope(
            PreservationClaim(pointer="", value={}),
            PreservationClaim(pointer="oops", value={}),
        )
        report = validate_envelope(envelope, self.CANONICAL)
        assert not report.ok
        assert all(e.code == "PRESERVATION_POINTER_INVALID" for e in report.errors)

    def test_oversized_envelope_rejected(self, monkeypatch):
        from app import preservation_envelope as mod
        from app.oas_resource_limits import OasResourceLimitValues

        monkeypatch.setattr(
            mod,
            "resource_limit_values",
            lambda: OasResourceLimitValues(
                max_document_bytes=64,
                max_alias_count=100,
                max_nesting_depth=256,
                max_yaml_documents_per_source=1,
            ),
        )
        envelope = self._envelope(
            PreservationClaim(pointer="/x-big", value={"blob": "y" * 200})
        )
        report = validate_envelope(envelope, self.CANONICAL)
        assert not report.ok
        assert any(e.code == "PRESERVATION_ENVELOPE_TOO_LARGE" for e in report.errors)

    def test_classifications_reported(self):
        envelope = self._envelope(
            PreservationClaim(pointer="/x-a", value=1),
            PreservationClaim(pointer="/webhooks/hook", value={}),
        )
        report = validate_envelope(envelope, self.CANONICAL)
        assert report.ok
        classes = {c.pointer: c.capability for c in report.classifications}
        assert classes["/x-a"] == "preserved-read-only"
        assert classes["/webhooks/hook"] == "preserved-read-only"


class TestApplyDeterminism:
    def test_array_insertions_apply_in_ascending_numeric_order(self):
        # Canonical kept elements A and C; source had X at 1 and Y at 3 (and 10 > 2
        # ordering must be numeric, not lexicographic).
        canonical = {"arr": ["A", "C"]}
        envelope = PreservationEnvelope(
            dialect="3.1.0",
            claims=[
                PreservationClaim(pointer="/arr/3", value="Y"),
                PreservationClaim(pointer="/arr/1", value="X"),
            ],
        )
        merged, errors = apply_envelope(canonical, envelope)
        assert errors == []
        assert merged["arr"] == ["A", "X", "C", "Y"]

    def test_numeric_order_beats_lexicographic(self):
        canonical = {"arr": list("abcdefghij")}
        envelope = PreservationEnvelope(
            dialect="3.1.0",
            claims=[
                PreservationClaim(pointer="/arr/10", value="K"),
                PreservationClaim(pointer="/arr/2", value="C2"),
            ],
        )
        merged, errors = apply_envelope(canonical, envelope)
        assert errors == []
        assert merged["arr"][2] == "C2"
        assert merged["arr"][10] == "K"

    def test_out_of_range_insertion_clamps_to_append(self):
        canonical = {"arr": ["A"]}
        envelope = PreservationEnvelope(
            dialect="3.1.0",
            claims=[PreservationClaim(pointer="/arr/7", value="Z")],
        )
        merged, errors = apply_envelope(canonical, envelope)
        assert errors == []
        assert merged["arr"] == ["A", "Z"]

    def test_missing_intermediate_containers_created_by_segment_shape(self):
        merged, errors = apply_envelope(
            {},
            PreservationEnvelope(
                dialect="3.1.0",
                claims=[PreservationClaim(pointer="/x-list/0/name", value="n")],
            ),
        )
        assert errors == []
        assert merged == {"x-list": [{"name": "n"}]}

    def test_collision_is_all_or_nothing(self):
        canonical = {"info": {"title": "T"}}
        envelope = PreservationEnvelope(
            dialect="3.1.0",
            claims=[
                PreservationClaim(pointer="/x-ok", value=1),
                PreservationClaim(pointer="/info/title", value="X"),
            ],
        )
        merged, errors = apply_envelope(canonical, envelope)
        assert [e.code for e in errors] == ["PRESERVATION_POINTER_COLLISION"]
        # Nothing applied: the returned document equals the canonical input.
        assert merged == canonical

    def test_apply_never_mutates_canonical_input(self):
        canonical = {"info": {"title": "T"}}
        import copy

        snapshot = copy.deepcopy(canonical)
        apply_envelope(
            canonical,
            PreservationEnvelope(
                dialect="3.1.0",
                claims=[PreservationClaim(pointer="/x-a", value=1)],
            ),
        )
        assert canonical == snapshot

    def test_descend_through_scalar_is_collision(self):
        canonical = {"info": "scalar"}
        merged, errors = apply_envelope(
            canonical,
            PreservationEnvelope(
                dialect="3.1.0",
                claims=[PreservationClaim(pointer="/info/x-a", value=1)],
            ),
        )
        assert [e.code for e in errors] == ["PRESERVATION_POINTER_COLLISION"]
        assert merged == canonical


class TestMoveClaims:
    def _envelope(self):
        return PreservationEnvelope(
            dialect="3.1.0",
            claims=[
                PreservationClaim(pointer="/paths/~1old/get/x-a", value=1),
                PreservationClaim(pointer="/paths/~1old/x-b", value=2),
                PreservationClaim(pointer="/x-untouched", value=3),
            ],
        )

    def test_move_relocates_subtree_claims(self):
        moved, errors = move_claims(self._envelope(), "/paths/~1old", "/paths/~1new")
        assert errors == []
        pointers = {c.pointer for c in moved.claims}
        assert pointers == {
            "/paths/~1new/get/x-a",
            "/paths/~1new/x-b",
            "/x-untouched",
        }

    def test_move_collision_leaves_envelope_unchanged(self):
        envelope = PreservationEnvelope(
            dialect="3.1.0",
            claims=[
                PreservationClaim(pointer="/x-a", value=1),
                PreservationClaim(pointer="/x-b", value=2),
            ],
        )
        moved, errors = move_claims(envelope, "/x-a", "/x-b")
        assert [e.code for e in errors] == ["PRESERVATION_DUPLICATE_POINTER"]
        assert moved == envelope

    def test_move_root_rejected(self):
        _, errors = move_claims(self._envelope(), "", "/x-target")
        assert [e.code for e in errors] == ["PRESERVATION_POINTER_INVALID"]


class TestCanonicalDelete:
    def test_delete_drops_subtree_claims_and_reports_them(self):
        envelope = PreservationEnvelope(
            dialect="3.1.0",
            claims=[
                PreservationClaim(pointer="/paths/~1w/get/x-a", value=1),
                PreservationClaim(pointer="/x-keep", value=2),
            ],
        )
        pruned, dropped = delete_canonical_subtree(envelope, "/paths/~1w")
        assert [c.pointer for c in pruned.claims] == ["/x-keep"]
        assert [c.pointer for c in dropped] == ["/paths/~1w/get/x-a"]

    def test_array_element_delete_rebases_higher_indices(self):
        envelope = PreservationEnvelope(
            dialect="3.1.0",
            claims=[
                PreservationClaim(pointer="/servers/0/x-a", value="stays"),
                PreservationClaim(pointer="/servers/1/x-b", value="dropped-with-parent"),
                PreservationClaim(pointer="/servers/2/x-c", value="rebases-to-1"),
                PreservationClaim(pointer="/servers/10/x-d", value="rebases-to-9"),
            ],
        )
        pruned, dropped = delete_canonical_subtree(envelope, "/servers/1")
        assert {c.pointer for c in pruned.claims} == {
            "/servers/0/x-a",
            "/servers/1/x-c",
            "/servers/9/x-d",
        }
        assert [c.pointer for c in dropped] == ["/servers/1/x-b"]

    def test_delete_is_deterministic_and_non_mutating(self):
        envelope = PreservationEnvelope(
            dialect="3.1.0",
            claims=[PreservationClaim(pointer="/servers/2/x-c", value=1)],
        )
        before = envelope.model_dump()
        first = delete_canonical_subtree(envelope, "/servers/1")
        second = delete_canonical_subtree(envelope, "/servers/1")
        assert first[0].model_dump() == second[0].model_dump()
        assert envelope.model_dump() == before

    def test_delete_root_rejected(self):
        with pytest.raises(ValueError):
            delete_canonical_subtree(
                PreservationEnvelope(dialect="3.1.0", claims=[]), ""
            )


class TestSemanticFingerprint:
    def test_key_order_is_excluded_lexical_difference(self):
        a = {"b": 1, "a": {"y": 2, "x": 3}}
        b = {"a": {"x": 3, "y": 2}, "b": 1}
        assert semantic_fingerprint(a).fingerprint == semantic_fingerprint(b).fingerprint

    def test_yaml_lexical_variants_hash_identically(self):
        plain = yaml.safe_load("title: Hello\ncount: 3\n")
        quoted = yaml.safe_load('count: !!int "3"\ntitle: "Hello"  # comment\n')
        assert (
            semantic_fingerprint(plain).fingerprint
            == semantic_fingerprint(quoted).fingerprint
        )

    def test_semantic_change_flips_fingerprint(self):
        assert (
            semantic_fingerprint({"a": 1}).fingerprint
            != semantic_fingerprint({"a": 2}).fingerprint
        )

    def test_exclusions_always_reported(self):
        result = semantic_fingerprint({"a": 1})
        assert result.lexical_exclusions == [
            "comments",
            "anchors",
            "key-order",
            "quoting",
            "whitespace",
            "multi-file-layout",
        ]
        assert result.algorithm == "sha256-oas-semantic-v1"

    def test_null_false_empty_are_distinct_semantics(self):
        variants = [{"x-a": None}, {"x-a": False}, {"x-a": {}}, {"x-a": []}, {}]
        digests = {semantic_fingerprint(v).fingerprint for v in variants}
        assert len(digests) == len(variants)
