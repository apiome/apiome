"""Tests for the compatibility rule catalogue and ``GET /v1/compatibility/rules`` — XPC-4.5 (#5749).

Acceptance: the catalogue lists every ``rule_id`` XPC-4.1–4.4 emit, and the docs page is generated
from it. Completeness is checked against the four classifier corpora: every rule id any corpus case
produces, under every mode and category, must resolve to a catalogue entry.
"""

from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

import pytest
from fastapi.testclient import TestClient

from app.asyncapi_diff import AsyncApiBreakingChangeClassifier
from app.asyncapi_normalizer import AsyncApiNormalizer
from app.auth import acceptable_scopes_for_request, validate_session_credentials
from app.avro_breaking import AvroBreakingChangeClassifier
from app.avro_import_source import AvroImportSource
from app.compatibility_rule_catalogue import (
    CATALOGUE_DOC_END,
    CATALOGUE_DOC_START,
    catalogue,
    entries_for_format,
    find_entry,
    render_catalogue_markdown,
    replace_catalogue_section,
)
from app.diff import diff
from app.jsonschema_breaking import JsonSchemaBreakingChangeClassifier
from app.jsonschema_import_source import JsonSchemaImportSource
from app.main import app
from app.proto_breaking import ProtobufBreakingChangeClassifier
from app.proto_breaking_rules import CATEGORY_ORDER
from app.proto_normalizer import ProtoNormalizer

_TESTS = Path(__file__).resolve().parent
_FIXTURES = _TESTS / "fixtures"
_DOCS_PAGE = _TESTS.parent.parent / "apiome-docs" / "docs" / "govern" / "compatibility-modes.md"
_MODES = ("BACKWARD", "FORWARD", "FULL")
#: Prefixes of the rule ids XPC-4.1–4.4 own (the format-agnostic baseline's ids are not theirs).
_XPC_PREFIXES = ("avro-compatibility.", "jsonschema.", "protobuf.", "asyncapi.", "asyncapi-diff.", "buf-breaking.")

client = TestClient(app)


def _rule_ids(result: Any) -> Set[str]:
    return {c.rule_id for c in result.classifications} | {f.rule_id for f in result.unattributed}


def _xpc(rule_ids: Iterable[str]) -> Set[str]:
    return {r for r in rule_ids if r.startswith(_XPC_PREFIXES)}


def _cases(name: str) -> List[Dict[str, Any]]:
    return json.loads((_FIXTURES / name / "cases.json").read_text())["cases"]


def _jsonschema_ids() -> Set[str]:
    source = JsonSchemaImportSource()
    found: Set[str] = set()
    for case in _cases("jsonschema_compatibility"):
        old = source.normalize(source.parse(json.dumps(case["old"])))
        new = source.normalize(source.parse(json.dumps(case["new"])))
        for mode in _MODES:
            found |= _rule_ids(JsonSchemaBreakingChangeClassifier(mode).classify(diff(old, new), old, new))
    return _xpc(found)


def _avro_ids() -> Set[str]:
    source = AvroImportSource()

    def model(schema: Any) -> Any:
        text = schema if isinstance(schema, str) else json.dumps(schema)
        return source.normalize(source.parse(text, source_label="schema.avsc"))

    found: Set[str] = set()
    for case in _cases("avro_compatibility"):
        old, new = model(case["versions"][-1]), model(case["candidate"])
        for mode in _MODES:
            found |= _rule_ids(AvroBreakingChangeClassifier(mode).classify(diff(old, new), old, new))
    return _xpc(found)


def _protobuf_ids() -> Set[str]:
    recordings = json.loads((_FIXTURES / "proto_breaking_categories" / "recordings.json").read_text())
    normalizer = ProtoNormalizer()
    found: Set[str] = set()
    for case in _cases("proto_breaking_categories"):
        descriptors = recordings[case["id"]]["descriptors"]
        old = normalizer.normalize(base64.b64decode(descriptors["old"]))
        new = normalizer.normalize(base64.b64decode(descriptors["new"]))
        for category in CATEGORY_ORDER:
            found |= _rule_ids(ProtobufBreakingChangeClassifier(category).classify(diff(old, new), old, new))
    return _xpc(found)


def _asyncapi_ids() -> Set[str]:
    found: Set[str] = set()
    for case in _cases("asyncapi_compatibility"):
        old = AsyncApiNormalizer().normalize(copy.deepcopy(case["old"]))
        new = AsyncApiNormalizer().normalize(copy.deepcopy(case["new"]))
        for mode in _MODES:
            found |= _rule_ids(AsyncApiBreakingChangeClassifier(mode).classify(diff(old, new), old, new))
        found |= {e["rule_id"] for e in case["expect"]}
    return _xpc(found)


@pytest.mark.parametrize(
    "collect",
    [_jsonschema_ids, _avro_ids, _protobuf_ids, _asyncapi_ids],
    ids=["json-schema", "avro", "protobuf", "asyncapi"],
)
def test_every_rule_id_a_corpus_emits_is_in_the_catalogue(collect: Any) -> None:
    emitted = collect()
    assert emitted, "the corpus produced no rule ids"
    missing = sorted(r for r in emitted if find_entry(r) is None)
    assert missing == []


def test_rule_ids_are_unique() -> None:
    ids = [e.rule_id for e in catalogue()]
    assert len(ids) == len(set(ids))


def test_every_data_schema_rule_has_a_severity_per_mode_and_protobuf_per_category() -> None:
    for entry in catalogue():
        if entry.family == "protobuf":
            assert entry.severities is None
            assert set(entry.category_severities or {}) == {"WIRE", "WIRE_JSON", "PACKAGE", "FILE"}
        else:
            assert set(entry.severities or {}) == {"BACKWARD", "FORWARD", "FULL", "NONE"}
            # NONE never breaks.
            assert (entry.severities or {})["NONE"] != "breaking"
        assert entry.description


def test_direction_decides_the_severity_per_mode() -> None:
    added = find_entry("jsonschema.backward.required-added")
    removed = find_entry("jsonschema.forward.required-removed")
    review = find_entry("jsonschema.review.ref-changed")
    assert added and added.severities == {"BACKWARD": "breaking", "FORWARD": "dangerous", "FULL": "breaking", "NONE": "dangerous"}
    assert removed and removed.severities == {"BACKWARD": "dangerous", "FORWARD": "breaking", "FULL": "breaking", "NONE": "dangerous"}
    assert review and set((review.severities or {}).values()) == {"dangerous"}


def test_asyncapi_sides_follow_the_mode() -> None:
    removed = find_entry("asyncapi.consumer.message-removed")
    added = find_entry("asyncapi.producer.message-added")
    assert removed and removed.severities == {"BACKWARD": "breaking", "FORWARD": "dangerous", "FULL": "breaking", "NONE": "dangerous"}
    assert added and added.severities == {"BACKWARD": "safe", "FORWARD": "dangerous", "FULL": "dangerous", "NONE": "safe"}


def test_protobuf_rules_name_their_home_category() -> None:
    json_name = find_entry("protobuf.wire_json.json-name-changed")
    assert json_name and json_name.category == "WIRE_JSON"
    assert json_name.category_severities == {"WIRE": "safe", "WIRE_JSON": "breaking", "PACKAGE": "breaking", "FILE": "breaking"}


def test_buf_rule_ids_resolve_to_their_family() -> None:
    entry = find_entry("protobuf.buf-breaking.field_same_json_name")
    assert entry is not None and entry.is_family


def test_entries_for_format_accepts_a_family_or_a_format_key() -> None:
    asyncapi = entries_for_format("asyncapi-3")
    assert any(e.rule_id.startswith("asyncapi.") for e in asyncapi)
    # AsyncAPI payloads reuse the JSON Schema, Avro and Protobuf rules.
    assert any(e.rule_id.startswith("jsonschema.") for e in asyncapi)
    assert entries_for_format("json-schema") == entries_for_format("JSONSCHEMA")
    assert entries_for_format("raml") == []
    assert entries_for_format(None) == catalogue()


# ===========================================================================
# The endpoint
# ===========================================================================


@pytest.fixture
def authed():
    app.dependency_overrides[validate_session_credentials] = lambda: {"user_id": "u-1"}
    yield
    app.dependency_overrides.pop(validate_session_credentials, None)


def test_rules_endpoint_requires_credentials() -> None:
    app.dependency_overrides.pop(validate_session_credentials, None)
    assert client.get("/v1/compatibility/rules").status_code == 401


def test_ci_and_registry_read_keys_may_fetch_the_catalogue() -> None:
    assert set(acceptable_scopes_for_request("GET", "/v1/compatibility/rules?format=avro")) == {
        "diff:read",
        "registry:read",
    }


def test_rules_endpoint_lists_the_catalogue(authed: None) -> None:
    r = client.get("/v1/compatibility/rules")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["modes"] == ["BACKWARD", "FORWARD", "FULL", "NONE"]
    assert body["categories"] == ["WIRE", "WIRE_JSON", "PACKAGE", "FILE"]
    assert body["defaults"] == {"mode": "BACKWARD", "transitive": False, "category": "WIRE_JSON"}
    assert len(body["rules"]) == len(catalogue())
    by_id = {rule["ruleId"]: rule for rule in body["rules"]}
    assert by_id["protobuf.wire_json.json-name-changed"]["categorySeverities"]["WIRE"] == "safe"
    assert by_id["avro-compatibility.reader-field-missing-default-value"]["severities"]["NONE"] == "dangerous"


def test_rules_endpoint_filters_by_format(authed: None) -> None:
    body = client.get("/v1/compatibility/rules", params={"format": "protobuf"}).json()
    assert body["format"] == "protobuf"
    assert body["rules"] and {rule["family"] for rule in body["rules"]} == {"protobuf"}
    assert client.get("/v1/compatibility/rules", params={"format": "raml"}).json()["rules"] == []


# ===========================================================================
# The docs page
# ===========================================================================


def test_the_docs_page_carries_the_generated_catalogue() -> None:
    page = _DOCS_PAGE.read_text(encoding="utf-8")
    assert CATALOGUE_DOC_START in page and CATALOGUE_DOC_END in page
    assert replace_catalogue_section(page) == page, (
        "The rule catalogue in compatibility-modes.md is stale; regenerate it with "
        "`uv run python scripts/generate_compatibility_rule_catalogue.py`"
    )


def test_rendered_catalogue_lists_every_rule() -> None:
    rendered = render_catalogue_markdown()
    for entry in catalogue():
        assert f"`{entry.rule_id}" in rendered


def test_replace_catalogue_section_requires_the_markers() -> None:
    with pytest.raises(ValueError):
        replace_catalogue_section("# no markers here\n")
