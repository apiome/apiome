"""Message pacts compared with AsyncAPI — PFX-3.6 (#6936).

The golden corpus under ``tests/golden/pact_asyncapi_compare`` carries the intended verdicts: Pact 3
message pacts and Pact 4 asynchronous messages against an AsyncAPI 3.0 and an AsyncAPI 2.6 provider,
covering every failure, warning and fidelity class of the message comparison (two are only reachable
with a purpose-built document and are covered by the unit tests below). See that directory's README.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

from app.pact_asyncapi_compare import (
    MAX_TRIED_MESSAGES,
    MESSAGE_FAILURE_CLASSES,
    MESSAGE_FIDELITY_CLASSES,
    MESSAGE_WARNING_CLASSES,
    compare_pact_to_asyncapi,
    is_asyncapi_document,
)
from app.pact_asyncapi_index import AsyncApiIndex, address_matches
from app.pact_oas_compare import compare_pact_to_oas
from app.pact_oas_result import MAX_INTERACTION_FINDINGS, PactOasCompareError

CORPUS = Path(__file__).parent / "golden" / "pact_asyncapi_compare"
CASES: List[Dict[str, Any]] = json.loads((CORPUS / "cases.json").read_text())
ORDERS = "providers/orders-3.0.yaml"
LIGHTS = "providers/streetlights-2.6.json"
UPDATE = os.environ.get("UPDATE_PACT_ASYNCAPI_GOLDENS") == "1"

#: Codes only a purpose-built document reaches; each has its own unit test below.
UNIT_ONLY = {"message.ambiguous", "findings-truncated"}


def _load(relative: str) -> Any:
    """Read a corpus document, JSON or YAML by its extension."""
    text = (CORPUS / relative).read_text()
    return yaml.safe_load(text) if relative.endswith((".yaml", ".yml")) else json.loads(text)


def _without_detail(node: Any) -> Any:
    """Drop the validator's own wording, which belongs to the jsonschema release."""
    if isinstance(node, dict):
        return {key: _without_detail(value) for key, value in node.items() if key != "detail"}
    if isinstance(node, list):
        return [_without_detail(item) for item in node]
    return node


def _codes(result: Dict[str, Any], kind: str) -> List[str]:
    """Every distinct code of one list across interactions."""
    return sorted({item["code"] for one in result["interactions"] for item in one[kind]})


def _pact(*messages: Dict[str, Any]) -> Dict[str, Any]:
    """A Pact 3 message pact."""
    return {
        "consumer": {"name": "c"},
        "provider": {"name": "p"},
        "messages": list(messages),
        "metadata": {"pactSpecification": {"version": "3.0.0"}},
    }


def _orders() -> Dict[str, Any]:
    return _load(ORDERS)


# =============================================================================================
# The corpus
# =============================================================================================


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_corpus_case_has_its_intended_verdict(case: Dict[str, Any]) -> None:
    result = compare_pact_to_asyncapi(_load(case["pact"]), _load(case["provider"])).to_dict()

    assert result["verdict"] == case["verdict"]
    assert result["success"] is (case["verdict"] != "fail")
    assert _codes(result, "failures") == case["failureCodes"]
    assert _codes(result, "fidelity") == case["fidelityCodes"]
    assert _codes(result, "warnings") == case["warningCodes"]

    path = CORPUS / "expected" / f"{case['id']}.json"
    actual = _without_detail(result)
    if UPDATE:
        path.write_text(json.dumps(actual, indent=2) + "\n")
    assert path.exists(), f"no golden for {case['id']}; record it with UPDATE_PACT_ASYNCAPI_GOLDENS=1"
    assert actual == json.loads(path.read_text())


def test_corpus_covers_every_verdict_both_asyncapi_majors_and_both_pact_versions() -> None:
    assert len({case["id"] for case in CASES}) == len(CASES)
    assert {case["verdict"] for case in CASES} == {"pass", "partial", "fail"}
    for case in CASES:
        assert case["id"].startswith(f"{case['verdict']}-")
    assert {case["provider"] for case in CASES} == {ORDERS, LIGHTS}
    majors = {_load(case["pact"])["metadata"]["pactSpecification"]["version"][0] for case in CASES}
    assert majors == {"3", "4"}


def test_corpus_and_unit_tests_cover_every_class() -> None:
    def seen(key: str) -> set:
        return {code for case in CASES for code in case[key]}

    assert seen("failureCodes") | (UNIT_ONLY & set(MESSAGE_FAILURE_CLASSES)) == set(MESSAGE_FAILURE_CLASSES)
    assert seen("warningCodes") == set(MESSAGE_WARNING_CLASSES)
    assert seen("fidelityCodes") | (UNIT_ONLY & set(MESSAGE_FIDELITY_CLASSES)) == set(MESSAGE_FIDELITY_CLASSES)


def test_every_pact_and_golden_belongs_to_a_case() -> None:
    ids = {case["id"] for case in CASES}
    assert {path.stem for path in (CORPUS / "pacts").glob("*.json")} == ids
    assert {path.stem for path in (CORPUS / "expected").glob("*.json")} == ids


@pytest.mark.parametrize("case", CASES[:6], ids=[case["id"] for case in CASES[:6]])
def test_output_is_deterministic_and_inputs_are_untouched(case: Dict[str, Any]) -> None:
    pact, provider = _load(case["pact"]), _load(case["provider"])
    before = (copy.deepcopy(pact), copy.deepcopy(provider))
    first = json.dumps(compare_pact_to_asyncapi(pact, provider).to_dict())
    second = json.dumps(compare_pact_to_asyncapi(pact, provider).to_dict())
    assert first == second
    assert (pact, provider) == before


# =============================================================================================
# Resolution
# =============================================================================================


def test_resolved_message_names_channel_address_key_pointers_and_action() -> None:
    result = compare_pact_to_asyncapi(_load("pacts/pass-01-v3-topic-with-template.json"), _orders())
    (interaction,) = result.interactions
    assert interaction.operation is None
    assert interaction.message == {
        "channel": "orderCreated",
        "address": "orders.{region}.created",
        "message": "OrderCreated",
        "pointer": "/channels/orderCreated/messages/OrderCreated",
        "resolvedPointer": "/components/messages/OrderCreated",
        "action": "send",
    }
    assert interaction.checks == [
        "message.channel",
        "message.content-type",
        "message.metadata",
        "message.body",
        "message.matching-rules",
    ]


def test_description_matches_title_ignoring_case() -> None:
    pact = _pact({"description": "ORDER CREATED", "contents": {"id": 1, "status": "new"}})
    (interaction,) = compare_pact_to_asyncapi(pact, _orders()).interactions
    assert interaction.message["message"] == "OrderCreated"
    assert interaction.verdict == "pass"


def test_unknown_channel_points_at_the_metadata_key() -> None:
    result = compare_pact_to_asyncapi(_load("pacts/fail-01-channel-unknown.json"), _orders())
    (finding,) = result.failures
    assert (finding.code, finding.pact_pointer, finding.oas_pointer) == (
        "message.channel.unknown",
        "/messages/0/metadata/topic",
        "/channels",
    )
    assert result.interactions[0].checks == ["message.channel"]


def test_not_sent_points_at_the_received_message() -> None:
    result = compare_pact_to_asyncapi(_load("pacts/fail-03-not-sent.json"), _orders())
    (finding,) = result.failures
    assert finding.oas_pointer == "/channels/paymentRequests/messages/PaymentRequested"


def test_a_document_without_messages_fails_every_message() -> None:
    document = {"asyncapi": "3.0.0", "info": {"title": "t", "version": "1"}}
    result = compare_pact_to_asyncapi(_pact({"description": "x", "contents": {}}), document)
    assert [finding.code for finding in result.failures] == ["message.unknown"]


def test_too_many_candidates_is_ambiguous_not_tried_one_by_one() -> None:
    messages = {f"M{n}": {"payload": {"type": "object"}} for n in range(MAX_TRIED_MESSAGES + 1)}
    document = {
        "asyncapi": "3.0.0",
        "info": {"title": "t", "version": "1"},
        "channels": {"all": {"address": "all", "messages": messages}},
    }
    result = compare_pact_to_asyncapi(_pact({"description": "x", "contents": {}}), document)
    assert [finding.code for finding in result.failures] == ["message.ambiguous"]


def test_contents_resolution_keeps_the_first_accepting_message_in_document_order() -> None:
    pact = _pact({"description": "x", "metadata": {"topic": "orders.events"}, "contents": {"orderId": 1}})
    (interaction,) = compare_pact_to_asyncapi(pact, _orders()).interactions
    # Both payloads accept {"orderId": 1} once `required` is lifted; the first one wins.
    assert interaction.message["message"] == "OrderShipped"
    assert [note.code for note in interaction.fidelity] == ["message-resolved-by-contents"]


def test_v3_document_without_operations_reads_every_message_as_direction_undeclared() -> None:
    document = _orders()
    del document["operations"]
    pact = _pact({"description": "OrderCreated", "contents": {"id": 1, "status": "new"}})
    (interaction,) = compare_pact_to_asyncapi(pact, document).interactions
    assert interaction.message["action"] is None
    assert [note.code for note in interaction.fidelity] == ["message-direction-undeclared"]


def test_v3_operation_listing_messages_covers_only_those() -> None:
    document = _orders()
    shipped = {"$ref": "#/channels/orderEvents/messages/OrderShipped"}
    document["operations"]["publishOrderEvents"]["messages"] = [shipped]
    document["operations"]["receiveCancellations"] = {
        "action": "receive",
        "channel": {"$ref": "#/channels/orderEvents"},
        "messages": [{"$ref": "#/channels/orderEvents/messages/OrderCancelled"}],
    }
    index = AsyncApiIndex(document)
    actions = {message.key: message.action for message in index.messages if message.channel == "orderEvents"}
    assert actions == {"OrderShipped": "send", "OrderCancelled": "receive"}


def test_v2_subscribe_sends_publish_receives_and_one_of_branches_are_listed() -> None:
    index = AsyncApiIndex(_load(LIGHTS))
    listed = [(message.key, message.action, message.pointer) for message in index.messages]
    assert listed == [
        (
            "lightMeasured",
            "send",
            "/channels/smartylighting~1streetlights~1{streetlightId}~1lighting~1measured/subscribe/message",
        ),
        (
            "turnOnOff",
            "receive",
            "/channels/smartylighting~1streetlights~1{streetlightId}~1command~1turnon/publish/message",
        ),
        (
            "dimLight",
            "send",
            "/channels/smartylighting~1streetlights~1{streetlightId}~1command~1alerts/subscribe/message/oneOf/0",
        ),
        (
            "lampFailure",
            "send",
            "/channels/smartylighting~1streetlights~1{streetlightId}~1command~1alerts/subscribe/message/oneOf/1",
        ),
    ]


@pytest.mark.parametrize(
    ("address", "value", "matches"),
    [
        ("orders.{region}.created", "orders.eu.created", True),
        ("orders.{region}.created", "orders..created", False),
        ("a/{id}/b", "a/1/2/b", False),
        ("a/{id}/b", "a/1/b", True),
        ("plain", "plain", True),
        ("plain", "plainer", False),
        ("a.(b)", "a.(b)", True),
        (None, "x", False),
    ],
)
def test_address_templates(address: Any, value: str, matches: bool) -> None:
    assert address_matches(address, value) is matches


# =============================================================================================
# Checks
# =============================================================================================


def test_content_type_mismatch_points_at_the_metadata_and_the_default() -> None:
    result = compare_pact_to_asyncapi(_load("pacts/fail-04-content-type.json"), _orders())
    (finding,) = result.failures
    assert (finding.pact_pointer, finding.oas_pointer) == ("/messages/0/metadata/contentType", "/defaultContentType")


def test_pact_4_content_type_mismatch_points_at_the_contents() -> None:
    pact = {
        "consumer": {"name": "c"},
        "provider": {"name": "p"},
        "metadata": {"pactSpecification": {"version": "4.0"}},
        "interactions": [
            {
                "type": "Asynchronous/Messages",
                "description": "lightMeasured",
                "contents": {"content": "<x/>", "contentType": "application/xml", "encoded": False},
            }
        ],
    }
    (finding,) = compare_pact_to_asyncapi(pact, _load(LIGHTS)).failures
    assert finding.code == "message.content-type.mismatch"
    assert finding.pact_pointer == "/interactions/0/contents"
    assert finding.oas_pointer.endswith("/subscribe/message/contentType")
    assert finding.resolved_pointer == "/components/messages/lightMeasured/contentType"


def test_metadata_failure_names_the_header_schema() -> None:
    result = compare_pact_to_asyncapi(_load("pacts/fail-05-metadata-invalid.json"), _orders())
    pointers = sorted((finding.pact_pointer, finding.oas_pointer, finding.keyword) for finding in result.failures)
    assert pointers == [
        (
            "/messages/0/metadata/attempt",
            "/channels/orderCreated/messages/OrderCreated/headers/properties/attempt",
            "minimum",
        ),
        (
            "/messages/0/metadata/traceId",
            "/channels/orderCreated/messages/OrderCreated/headers/properties/traceId",
            "pattern",
        ),
    ]


def test_destination_and_content_type_are_not_read_as_headers() -> None:
    pact = _pact(
        {
            "description": "OrderCreated",
            "metadata": {"Topic": "orders.eu.created", "Content-Type": "application/json"},
            "contents": {"id": 1, "status": "new"},
        }
    )
    (interaction,) = compare_pact_to_asyncapi(pact, _orders()).interactions
    assert interaction.warnings == []
    assert interaction.verdict == "pass"


def test_body_failures_carry_message_anchored_and_resolved_pointers() -> None:
    result = compare_pact_to_asyncapi(_load("pacts/fail-06-body-schema.json"), _orders())
    found = sorted((f.pact_pointer, f.oas_pointer, f.resolved_pointer) for f in result.failures)
    assert found == [
        (
            "/messages/0/contents/id",
            "/channels/orderCreated/messages/OrderCreated/payload/properties/id/type",
            "/components/schemas/Order/properties/id/type",
        ),
        (
            "/messages/0/contents/status",
            "/channels/orderCreated/messages/OrderCreated/payload/properties/status/enum",
            "/components/schemas/Order/properties/status/enum",
        ),
    ]


def test_required_is_not_held_against_the_consumer() -> None:
    pact = _pact({"description": "OrderCreated", "contents": {"customer": "acme"}})
    assert compare_pact_to_asyncapi(pact, _orders()).verdict == "pass"


def test_multi_format_json_schema_payload_is_validated() -> None:
    document = _orders()
    document["components"]["messages"]["OrderCreated"]["payload"] = {
        "schemaFormat": "application/schema+json;version=draft-07",
        "schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
    }
    pact = _pact({"description": "OrderCreated", "contents": {"id": "x"}})
    (finding,) = compare_pact_to_asyncapi(pact, document).failures
    assert finding.oas_pointer == "/channels/orderCreated/messages/OrderCreated/payload/schema/properties/id/type"


def test_failures_beyond_the_cap_are_counted_not_dropped() -> None:
    contents = {"id": 1, "status": "new", **{f"extra{n}": n for n in range(MAX_INTERACTION_FINDINGS + 5)}}
    pact = _pact({"description": "OrderCreated", "contents": contents})
    (interaction,) = compare_pact_to_asyncapi(pact, _orders()).interactions
    assert len(interaction.failures) == MAX_INTERACTION_FINDINGS
    assert {finding.code for finding in interaction.failures} == {"message.body.unknown-property"}
    assert [note.code for note in interaction.fidelity] == ["findings-truncated"]
    assert interaction.fidelity[0].message.startswith("5 more failure(s)")


def test_runaway_nesting_costs_one_message_not_the_run() -> None:
    deep: Any = 1
    for _ in range(3000):
        deep = {"a": deep}
    pact = _pact(
        {"description": "OrderCreated", "contents": deep},
        {"description": "OrderCreated", "contents": {"id": 1, "status": "new"}},
    )
    result = compare_pact_to_asyncapi(pact, _orders())
    assert result.interactions[1].verdict == "pass"
    assert any(note.code == "body-not-compared" for note in result.interactions[0].fidelity)


# =============================================================================================
# Inputs and the OpenAPI side
# =============================================================================================


@pytest.mark.parametrize(
    ("pact", "contract", "message"),
    [
        ([], {"asyncapi": "3.0.0"}, "the pact is not a JSON object"),
        ({}, [], "the provider contract is not a JSON object"),
        ({}, {"openapi": "3.1.0"}, "not an AsyncAPI 2.x or 3.x document"),
        ({}, {"asyncapi": "1.2.0"}, "not an AsyncAPI 2.x or 3.x document"),
    ],
)
def test_inputs_that_are_not_a_pact_and_an_asyncapi_document_are_refused(
    pact: Any, contract: Any, message: str
) -> None:
    with pytest.raises(PactOasCompareError, match=message):
        compare_pact_to_asyncapi(pact, contract)


def test_serialization_names_the_contract_type_and_asyncapi_version() -> None:
    payload = compare_pact_to_asyncapi(_pact(), _orders()).to_dict()
    assert (payload["contractType"], payload["asyncapiVersion"]) == ("asyncapi", "3.0.0")
    assert "oasVersion" not in payload


def test_openapi_serialization_is_unchanged() -> None:
    oas = {"openapi": "3.1.0", "info": {"title": "t", "version": "1"}, "paths": {}}
    payload = compare_pact_to_oas({"interactions": []}, oas).to_dict()
    assert payload["oasVersion"] == "3.1.0"
    assert "contractType" not in payload and "asyncapiVersion" not in payload


def test_is_asyncapi_document() -> None:
    assert is_asyncapi_document({"asyncapi": "3.0.0"}) is True
    assert is_asyncapi_document({"openapi": "3.1.0"}) is False
    assert is_asyncapi_document(None) is False


# =============================================================================================
# The published rule set
# =============================================================================================

RULES_PAGE = (
    Path(__file__).resolve().parents[2] / "apiome-docs" / "docs" / "ship" / "pact-broker" / "comparison-rules.mdx"
)


@pytest.mark.skipif(not RULES_PAGE.exists(), reason="the docs site is not in this checkout")
def test_comparison_rules_page_lists_every_message_code() -> None:
    page = RULES_PAGE.read_text()
    documented = [*MESSAGE_FAILURE_CLASSES, *MESSAGE_WARNING_CLASSES, *MESSAGE_FIDELITY_CLASSES]
    assert [name for name in documented if f"`{name}`" not in page] == []
    tables = (MESSAGE_FAILURE_CLASSES, MESSAGE_WARNING_CLASSES, MESSAGE_FIDELITY_CLASSES)
    for description in (text for table in tables for text in table.values()):
        assert description in page
