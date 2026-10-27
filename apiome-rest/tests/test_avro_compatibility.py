"""Tests for the Avro compatibility engine — MFI-12.4 (#3785).

``fixtures/avro_compatibility/recordings.json`` holds a live Confluent Schema Registry's verbose
answers to ``POST /compatibility/…`` for every case in ``cases.json`` (recorded by
``scripts/record_avro_compatibility_fixtures.py``). The engine must give the same verdict and the
same messages for each, offline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.avro_compatibility import (
    LEVELS,
    AvroCompatibilityError,
    ParsedSchema,
    can_read,
    check_compatibility,
    confluent_messages,
    directions_for,
    parse_schema_text,
    schema_of_document,
)
from app.avro_import_source import AvroImportSource

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "avro_compatibility"
_CASES = {case["id"]: case for case in json.loads((_FIXTURES / "cases.json").read_text())["cases"]}
_RECORDED = json.loads((_FIXTURES / "recordings.json").read_text())


def _schema(raw: Any) -> ParsedSchema:
    return parse_schema_text(json.dumps(raw))


def _recorded_checks() -> List[Any]:
    return [
        pytest.param(case_id, key, verdict, id=f"{case_id}:{key}")
        for case_id, verdicts in _RECORDED["recordings"].items()
        for key, verdict in verdicts.items()
    ]


def _normalized(messages: List[str]) -> List[Any]:
    """Messages with the ``oldSchema`` text parsed, so JSON spacing does not matter."""
    out: List[Any] = []
    for message in messages:
        prefix = "{oldSchema: '"
        out.append(("oldSchema", json.loads(message[len(prefix) : -2])) if message.startswith(prefix) else message)
    return out


# ===========================================================================
# Replay of the live registry's verdicts
# ===========================================================================


def test_the_recordings_cover_every_case_and_level():
    assert _RECORDED["registry"]
    for case_id, case in _CASES.items():
        recorded = _RECORDED["recordings"][case_id]
        assert set(case["levels"]) <= set(recorded)


@pytest.mark.parametrize("case_id, key, recorded", _recorded_checks())
def test_matches_the_registry_dry_run(case_id: str, key: str, recorded: Dict[str, Any]):
    case = _CASES[case_id]
    level, _, explicit = key.partition("@")
    versions = case["versions"][: int(explicit)] if explicit else case["versions"]
    verdict = check_compatibility(
        level, _schema(case["candidate"]), [_schema(v) for v in versions], only_latest=bool(explicit)
    )
    assert verdict.is_compatible is recorded["is_compatible"]
    failed = verdict.failed_version
    messages = confluent_messages(
        verdict,
        old_version=None if failed is None else failed + 1,
        old_schema=None if failed is None else json.dumps(versions[failed]),
    )
    assert _normalized(messages) == _normalized(recorded["messages"])


# ===========================================================================
# Acceptance: add / remove a field per mode
# ===========================================================================

_V1 = {"type": "record", "name": "User", "fields": [{"name": "id", "type": "long"}, {"name": "name", "type": "string"}]}


def _with(fields: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {**_V1, "fields": fields}


@pytest.mark.parametrize(
    "candidate, backward, forward",
    [
        (_with(_V1["fields"] + [{"name": "email", "type": "string", "default": ""}]), True, True),
        (_with(_V1["fields"] + [{"name": "email", "type": "string"}]), False, True),
        (_with(_V1["fields"][:1]), True, False),
    ],
    ids=["add-with-default", "add-without-default", "remove-without-default"],
)
def test_add_and_remove_field_per_mode(candidate, backward: bool, forward: bool):
    old, new = _schema(_V1), _schema(candidate)
    assert check_compatibility("BACKWARD", new, [old]).is_compatible is backward
    assert check_compatibility("FORWARD", new, [old]).is_compatible is forward
    assert check_compatibility("FULL", new, [old]).is_compatible is (backward and forward)
    assert check_compatibility("NONE", new, [old]).is_compatible


def test_transitive_checks_every_prior_version():
    v1 = _schema({"type": "record", "name": "T", "fields": [{"name": "id", "type": "long"}]})
    v2 = _schema(
        {
            "type": "record",
            "name": "T",
            "fields": [{"name": "id", "type": "long"}, {"name": "x", "type": "int", "default": 0}],
        }
    )
    candidate = _schema(
        {"type": "record", "name": "T", "fields": [{"name": "id", "type": "long"}, {"name": "x", "type": "int"}]}
    )
    assert check_compatibility("BACKWARD", candidate, [v1, v2]).is_compatible
    verdict = check_compatibility("BACKWARD_TRANSITIVE", candidate, [v1, v2])
    assert not verdict.is_compatible
    assert verdict.failed_version == 0
    assert check_compatibility("BACKWARD_TRANSITIVE", candidate, [v1, v2], only_latest=True).is_compatible


# ===========================================================================
# Engine details
# ===========================================================================


def test_levels_and_directions():
    assert directions_for("NONE") == ((), False)
    assert directions_for("FULL_TRANSITIVE") == (("backward", "forward"), True)
    assert directions_for("FORWARD") == (("forward",), False)
    assert len(LEVELS) == 7
    with pytest.raises(AvroCompatibilityError):
        directions_for("SIDEWAYS")


def test_a_first_version_needs_no_check():
    assert check_compatibility("FULL_TRANSITIVE", _schema(_V1), []).is_compatible


def test_a_recursive_record_terminates():
    node = {
        "type": "record",
        "name": "Node",
        "fields": [{"name": "v", "type": "int"}, {"name": "next", "type": ["null", "Node"], "default": None}],
    }
    assert can_read(_schema(node), _schema(node)) == []


def test_an_incompatibility_names_its_record_and_field():
    old = _schema({"type": "record", "name": "R", "namespace": "n", "fields": [{"name": "a", "type": "string"}]})
    new = _schema({"type": "record", "name": "R", "namespace": "n", "fields": [{"name": "a", "type": "int"}]})
    (found,) = can_read(new, old)
    assert (found.type, found.location, found.record, found.field) == ("TYPE_MISMATCH", "/fields/0/type", "n.R", "a")


def test_a_relative_reader_alias_matches_the_writers_full_name():
    old = _schema({"type": "record", "name": "Old", "namespace": "n", "fields": []})
    new = _schema({"type": "record", "name": "New", "namespace": "n", "aliases": ["Old"], "fields": []})
    assert can_read(new, old) == []
    assert [f.type for f in can_read(old, new)] == ["NAME_MISMATCH"]


def test_primitive_schemas_and_promotions():
    assert can_read(parse_schema_text('"long"'), parse_schema_text('"int"')) == []
    assert [f.type for f in can_read(parse_schema_text('"int"'), parse_schema_text('"long"'))] == ["TYPE_MISMATCH"]


@pytest.mark.parametrize("text", ["not json", '{"type": "record"}', '"nonsense"'])
def test_an_invalid_schema_is_refused(text: str):
    with pytest.raises(AvroCompatibilityError):
        parse_schema_text(text)


def test_idl_types_are_compared_like_avsc():
    source = AvroImportSource()
    idl = source.parse(
        "namespace com.example;\nrecord Address { string city; }\nrecord User { long id; Address home; }\n",
        source_label="user.avdl",
    )
    avsc = parse_schema_text(
        json.dumps(
            {
                "type": "record",
                "name": "User",
                "namespace": "com.example",
                "fields": [
                    {"name": "id", "type": "long"},
                    {
                        "name": "home",
                        "type": {"type": "record", "name": "Address", "fields": [{"name": "city", "type": "string"}]},
                    },
                ],
            }
        )
    )
    user = schema_of_document(idl, "com.example.User")
    assert can_read(user, avsc) == [] and can_read(avsc, user) == []
    with pytest.raises(AvroCompatibilityError):
        schema_of_document(idl, "com.example.Missing")
