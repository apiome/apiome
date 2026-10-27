"""Tests for Avro Parsing Canonical Form and semantic hashes — MFI-12.1 (#3782).

Acceptance: PCF and semantic hashes are computed; a ``doc``-only change flips the semantic hash
but not the PCF. The PCF is checked byte for byte against fastavro's implementation across the
``.avsc`` corpus, and CRC-64-AVRO against the Avro specification's test vector.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pytest
from fastavro.schema import fingerprint as fastavro_fingerprint
from fastavro.schema import to_parsing_canonical_form as fastavro_pcf

from app.avro_fingerprint import (
    PCF_ALGORITHM,
    AvroPcfHasher,
    crc64_avro,
    document_fingerprint,
    fingerprint_types,
    parsing_canonical_form,
    semantic_form,
)
from app.avro_import_source import AvroImportSource
from app.breaking_change import classify_models
from app.diff import diff
from app.fingerprint import UNHASHED_EXTRAS, canonical_payload, fingerprint, get_fingerprint_hasher
from app.versioning import PreviousVersion, VersionAction, decide_version

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_AVSC = sorted((_EXAMPLES / "avro").glob("*.avsc"))
_AVDL = sorted((_EXAMPLES / "avro-idl").glob("0*.avdl"))

_SOURCE = AvroImportSource()


def _user(**field_overrides: Any) -> Dict[str, Any]:
    """A small record whose ``email`` field the tests edit."""
    email: Dict[str, Any] = {"name": "email", "type": ["null", "string"], "default": None}
    email.update(field_overrides)
    return {
        "type": "record",
        "name": "User",
        "namespace": "com.example",
        "doc": "A user.",
        "fields": [
            {"name": "id", "type": "long"},
            email,
            {"name": "status", "type": {"type": "enum", "name": "Status", "symbols": ["ACTIVE", "GONE"]}},
            {"name": "previous", "type": ["null", "Status"], "default": None},
        ],
    }


def _parse(schema: Dict[str, Any]):
    return _SOURCE.parse(json.dumps(schema), source_label="user.avsc")


def _idl(name: str):
    return _SOURCE.parse((_EXAMPLES / "avro-idl" / name).read_text(encoding="utf-8"), source_label=name)


def _root(schema: Dict[str, Any]):
    fp = document_fingerprint(_parse(schema))
    assert fp is not None
    return fp


# ===========================================================================
# CRC-64-AVRO and PCF against the specification and fastavro
# ===========================================================================


def test_crc64_avro_matches_the_specification_vector():
    # Avro's schema-tests.txt: the PCF "null" fingerprints to 7195948357588979594.
    assert crc64_avro(b'"null"') == 7195948357588979594


@pytest.mark.parametrize("path", _AVSC, ids=[p.name for p in _AVSC])
def test_pcf_matches_fastavro_across_the_corpus(path: Path):
    fp = document_fingerprint(_SOURCE.parse(path.read_text(encoding="utf-8"), source_label=path.name))
    reference = fastavro_pcf(json.loads(path.read_text(encoding="utf-8")))
    assert fp is not None
    assert fp.canonical_form == reference
    assert fp.sha256 == fastavro_fingerprint(reference, "SHA-256")
    # fastavro prints the CRC in the little-endian byte order of the single-object header.
    assert bytes.fromhex(fp.crc64)[::-1].hex() == fastavro_fingerprint(reference, "CRC-64-AVRO")


def test_pcf_transformations():
    pcf = parsing_canonical_form(
        {
            "type": "record",
            "name": "R",
            "namespace": "n",
            "doc": "stripped",
            "aliases": ["Old"],
            "fields": [
                {"name": "a", "type": {"type": "int"}, "doc": "x", "default": 1, "order": "descending"},
                {"name": "t", "type": {"type": "long", "logicalType": "timestamp-millis"}},
                {"name": "e", "type": {"type": "enum", "name": "E", "symbols": ["X"], "default": "X"}},
                {"name": "e2", "type": "E"},
                {"name": "o", "type": {"name": "O", "namespace": "other", "type": "fixed", "size": 16}},
                {"name": "m", "type": {"values": "string", "type": "map"}},
            ],
        }
    )
    assert pcf == (
        '{"name":"n.R","type":"record","fields":['
        '{"name":"a","type":"int"},'  # [PRIMITIVES] + [STRIP]
        '{"name":"t","type":"long"},'  # logicalType stripped
        '{"name":"e","type":{"name":"n.E","type":"enum","symbols":["X"]}},'  # [FULLNAMES]
        '{"name":"e2","type":"n.E"},'  # inlined once, then by full name
        '{"name":"o","type":{"name":"other.O","type":"fixed","size":16}},'
        '{"name":"m","type":{"type":"map","values":"string"}}]}'  # [ORDER]
    )


def test_a_named_reference_with_attributes_reduces_to_the_reference():
    store = {"n.D": {"type": "fixed", "name": "D", "size": 4}}
    schema = {
        "type": "record",
        "name": "R",
        "namespace": "n",
        "fields": [{"name": "w", "type": {"type": "D", "logicalType": "duration"}}],
    }
    assert parsing_canonical_form(schema, store=store) == (
        '{"name":"n.R","type":"record","fields":[{"name":"w","type":{"name":"n.D","type":"fixed","size":4}}]}'
    )
    assert '"logicalType":"duration"' in semantic_form(schema, store=store)


# ===========================================================================
# Acceptance: doc-only flips the semantic hash, not the PCF
# ===========================================================================


def test_a_doc_only_change_flips_the_semantic_hash_but_not_the_pcf():
    before = _root(_user())
    edited = _user(doc="The user's contact address.")
    edited["doc"] = "A user of the platform."
    after = _root(edited)
    assert after.sha256 == before.sha256
    assert after.crc64 == before.crc64
    assert after.semantic_sha256 != before.semantic_sha256


@pytest.mark.parametrize(
    "overrides",
    [{"default": "x@example.com", "type": ["string", "null"]}, {"aliases": ["mail"]}, {"order": "ignore"}],
    ids=["default", "aliases", "order"],
)
def test_evolution_attributes_flip_the_semantic_hash_but_not_the_pcf(overrides: Dict[str, Any]):
    before = _root(_user())
    after = _root(_user(**overrides))
    if "type" not in overrides:
        assert after.sha256 == before.sha256
    assert after.semantic_sha256 != before.semantic_sha256


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s["fields"][0].update(type="int"),
        lambda s: s["fields"].reverse(),
        lambda s: s["fields"][2]["type"]["symbols"].append("NEW"),
        lambda s: s.update(name="Account"),
    ],
    ids=["retype", "reorder", "symbol", "rename"],
)
def test_wire_changes_flip_both(mutate):
    schema = _user()
    before = _root(schema)
    changed = copy.deepcopy(schema)
    mutate(changed)
    after = _root(changed)
    assert after.sha256 != before.sha256
    assert after.crc64 != before.crc64
    assert after.semantic_sha256 != before.semantic_sha256


def test_key_order_and_whitespace_change_nothing():
    schema = _user()
    a = _parse(schema)
    b = _SOURCE.parse(json.dumps(dict(reversed(list(schema.items()))), indent=4), source_label="user.avsc")
    assert fingerprint_types(a) == fingerprint_types(b)


# ===========================================================================
# IDL
# ===========================================================================


def test_idl_and_avsc_of_the_same_schema_share_a_pcf():
    idl = _SOURCE.parse(
        "namespace com.example;\nrecord User { long id; union { null, string } email = null; }\n",
        source_label="user.avdl",
    )
    avsc = _parse(
        {
            "type": "record",
            "name": "User",
            "namespace": "com.example",
            "fields": [{"name": "id", "type": "long"}, {"name": "email", "type": ["null", "string"], "default": None}],
        }
    )
    assert document_fingerprint(idl).sha256 == document_fingerprint(avsc).sha256
    assert document_fingerprint(idl).semantic_sha256 == document_fingerprint(avsc).semantic_sha256


@pytest.mark.parametrize("path", _AVDL, ids=[p.name for p in _AVDL])
def test_every_idl_type_is_fingerprinted_with_its_references_inlined(path: Path):
    document = _SOURCE.parse(path.read_text(encoding="utf-8"), source_label=path.name)
    fps = fingerprint_types(document)
    assert [fp.name for fp in fps] == sorted(
        f"{t.namespace}.{t.name}" if t.namespace else t.name for t in document.types
    )
    for fp in fps:
        assert json.loads(fp.canonical_form)["name"] == fp.name
        assert len(fp.crc64) == 16 and len(fp.sha256) == 64 and len(fp.semantic_sha256) == 64
    if document.protocol is not None:
        assert document_fingerprint(document) is None


def test_an_idl_reference_to_a_sibling_type_is_inlined():
    document = _idl("03-composition-named-type-reuse.avdl")
    party = next(fp for fp in fingerprint_types(document) if fp.name.endswith(".Party"))
    pcf = party.canonical_form
    # Address is inlined at its first use and referenced by full name afterwards.
    assert pcf.count('"name":"com.example.crm.Address","type":"record"') == 1
    assert '"items":"com.example.crm.Address"' in pcf


def test_an_error_type_keeps_its_kind():
    document = _idl("02-typical-orders-protocol.avdl")
    error = next(fp for fp in fingerprint_types(document) if fp.name.endswith("OrderNotFound"))
    assert json.loads(error.canonical_form)["type"] == "error"


# ===========================================================================
# The catalog model: extras, version fingerprint, format hash, diff
# ===========================================================================


def _model(schema: Dict[str, Any]):
    return _SOURCE.normalize(_parse(schema))


def test_the_model_records_pcf_and_semantic_hashes_per_type():
    model = _model(_user())
    root = _root(_user())
    assert set(model.extras["avro_pcf"]) == {"com.example.User", "com.example.Status"}
    assert model.extras["avro_pcf"]["com.example.User"] == {"crc64": root.crc64, "sha256": root.sha256}
    assert model.extras["avro_semantic_hashes"]["com.example.User"] == root.semantic_sha256


def test_the_format_hash_is_the_root_pcf_sha256():
    assert get_fingerprint_hasher("avro") is AvroPcfHasher
    result = fingerprint(_model(_user()))
    assert result.format_hash == _root(_user()).sha256
    assert result.format_algorithm == PCF_ALGORITHM


def test_a_protocol_has_no_format_hash():
    path = _EXAMPLES / "avro-idl" / "02-typical-orders-protocol.avdl"
    result = fingerprint(_SOURCE.normalize(_SOURCE.parse(path.read_text(), source_label=path.name)))
    assert result.format_hash is None
    assert result.format_algorithm is None


def test_the_semantic_hashes_are_kept_out_of_the_version_fingerprint():
    assert "avro_semantic_hashes" in UNHASHED_EXTRAS
    payload = canonical_payload(_model(_user()))
    assert "avro_semantic_hashes" not in payload["extras"]
    assert "avro_pcf" in payload["extras"]


def test_a_doc_only_edit_mints_no_version_and_is_not_breaking():
    before = _model(_user())
    edited = _user(doc="The user's contact address.")
    edited["doc"] = "A user of the platform."
    after = _model(edited)
    assert after.extras["avro_semantic_hashes"] != before.extras["avro_semantic_hashes"]

    previous = PreviousVersion(
        version_tag="2026-10-27T10:00Z", fingerprint=fingerprint(before).fingerprint, model=before
    )
    decision = decide_version(after, previous=previous, when=datetime(2026, 10, 27, 11, tzinfo=timezone.utc))
    assert decision.action == VersionAction.SKIP
    assert diff(before, after).changes == []
    assert classify_models(before, after).breaking is False


def test_a_field_reorder_mints_a_version():
    """Field order is the binary layout: the canonical model sorts fields, the PCF does not."""
    before = _model(_user())
    reordered = _user()
    reordered["fields"].reverse()
    after = _model(reordered)
    assert fingerprint(after).fingerprint != fingerprint(before).fingerprint
