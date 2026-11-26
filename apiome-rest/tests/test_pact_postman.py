"""Pact → Postman Collection v2.1 — PFX-4.7 (#6944).

:func:`app.pact_postman.pact_to_postman` with Pact 2, 3 and 4 documents:

* every collection validates against the vendored Postman v2.1.0 JSON Schema and re-parses;
* requests carry method, ``{{baseUrl}}`` URL, query, headers and the example body as recorded;
* saved examples carry the expected status, headers and body;
* test scripts check status, headers and body (Pact's default rules), and run in Node with a
  stub ``pm`` when Node is installed;
* every entry the collection cannot carry is a notice with a code, outcome, pointer and reason —
  message, gRPC and invalid interactions, non-text bodies, matching rules, generators, provider
  states.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from typing import Any, Dict, List

import pytest

from app.pact_postman import (
    BASE_URL_VARIABLE,
    CODE_BODY_NOT_ASSERTED,
    CODE_GENERATORS_NOT_APPLIED,
    CODE_GRPC_LEFT_OUT,
    CODE_INTERACTION_INVALID,
    CODE_MATCHING_RULES_NOT_ASSERTED,
    CODE_MESSAGE_LEFT_OUT,
    CODE_PROVIDER_STATES,
    CODE_REQUEST_BODY_LEFT_OUT,
    OUTCOME_INFO,
    OUTCOME_LEFT_OUT,
    OUTCOME_NOT_APPLIED,
    OUTCOME_NOT_ASSERTED,
    POSTMAN_SCHEMA_URL,
    pact_to_postman,
)
from app.postman_emitter import validate_postman_collection


def _v2_pact() -> Dict[str, Any]:
    return {
        "consumer": {"name": "Web"},
        "provider": {"name": "Orders"},
        "interactions": [
            {
                "description": "a request for order 42",
                "providerState": "order 42 exists",
                "request": {
                    "method": "get",
                    "path": "/orders/42",
                    "query": "expand=items&expand=customer",
                    "headers": {"Accept": "application/json"},
                },
                "response": {
                    "status": 200,
                    "headers": {"Content-Type": "application/json; charset=utf-8"},
                    "body": {"id": 42, "items": [{"sku": "A-1"}]},
                },
            }
        ],
        "metadata": {"pactSpecification": {"version": "2.0.0"}},
    }


def _v4_pact(*interactions: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "consumer": {"name": "Web"},
        "provider": {"name": "Orders"},
        "interactions": list(interactions),
        "metadata": {"pactSpecification": {"version": "4.0"}},
    }


def _v4_http(**overrides: Any) -> Dict[str, Any]:
    interaction: Dict[str, Any] = {
        "type": "Synchronous/HTTP",
        "description": "create an order",
        "providerStates": [{"name": "a customer exists", "params": {"id": 7}}],
        "request": {
            "method": "POST",
            "path": "/orders",
            "query": {"dryRun": ["true"]},
            "headers": {"X-Trace": ["a", "b"]},
            "body": {"content": {"sku": "A-1", "qty": 2}, "contentType": "application/json", "encoded": False},
        },
        "response": {
            "status": 201,
            "headers": {"Location": ["/orders/9"]},
            "body": {"content": {"id": 9}, "contentType": "application/json", "encoded": False},
        },
    }
    interaction.update(overrides)
    return interaction


def _notice_codes(export: Any) -> List[str]:
    return [notice.code for notice in export.notices]


def _item(export: Any, index: int = 0) -> Dict[str, Any]:
    return export.collection["item"][index]


# --- the collection --------------------------------------------------------------------------


def test_a_v2_pact_writes_a_valid_v2_1_collection() -> None:
    export = pact_to_postman(_v2_pact(), consumer="Web", provider="Orders", description="From a pact.")
    text = json.dumps(export.collection)
    validate_postman_collection(text)
    info = export.collection["info"]
    assert info == {"name": "Pact: Web → Orders", "schema": POSTMAN_SCHEMA_URL, "description": "From a pact."}
    assert (export.interaction_count, export.exported_count, export.left_out_count) == (1, 1, 0)


def test_the_request_is_sent_as_the_pact_records_it() -> None:
    request = _item(pact_to_postman(_v2_pact(), consumer="Web", provider="Orders"))["request"]
    assert request["method"] == "GET"
    assert request["url"] == {
        "raw": "{{baseUrl}}/orders/42?expand=items&expand=customer",
        "host": ["{{baseUrl}}"],
        "path": ["orders", "42"],
        "query": [{"key": "expand", "value": "items"}, {"key": "expand", "value": "customer"}],
    }
    assert request["header"] == [{"key": "Accept", "value": "application/json"}]
    assert request["description"] == "Given: order 42 exists"
    assert "body" not in request


def test_a_v4_request_carries_its_body_content_type_and_joined_headers() -> None:
    export = pact_to_postman(_v4_pact(_v4_http()), consumer="Web", provider="Orders")
    validate_postman_collection(json.dumps(export.collection))
    request = _item(export)["request"]
    assert request["url"]["raw"] == "{{baseUrl}}/orders?dryRun=true"
    assert request["header"] == [
        {"key": "X-Trace", "value": "a, b"},
        {"key": "Content-Type", "value": "application/json"},
    ]
    assert json.loads(request["body"]["raw"]) == {"sku": "A-1", "qty": 2}
    assert request["body"]["options"] == {"raw": {"language": "json"}}


def test_query_values_are_encoded_in_the_raw_url() -> None:
    pact = _v4_pact(_v4_http(request={"method": "GET", "path": "/search", "query": {"q": ["a b&c"]}}))
    url = _item(pact_to_postman(pact, consumer="Web", provider="Orders"))["request"]["url"]
    assert url["raw"] == "{{baseUrl}}/search?q=a%20b%26c"
    assert url["query"] == [{"key": "q", "value": "a b&c"}]


def test_the_base_url_variable_is_the_option_or_empty_to_fill_in() -> None:
    filled = pact_to_postman(_v2_pact(), consumer="Web", provider="Orders", base_url="http://localhost:8080/")
    assert filled.collection["variable"] == [{"key": BASE_URL_VARIABLE, "value": "http://localhost:8080"}]
    empty = pact_to_postman(_v2_pact(), consumer="Web", provider="Orders")
    assert empty.collection["variable"][0]["value"] == ""
    assert "fill in" in empty.collection["variable"][0]["description"]


def test_an_interaction_without_a_description_is_named_by_method_and_path() -> None:
    interaction = _v4_http()
    del interaction["description"]
    assert _item(pact_to_postman(_v4_pact(interaction), consumer="Web", provider="Orders"))["name"] == "POST /orders"


def test_the_saved_example_carries_the_expected_response() -> None:
    example = _item(pact_to_postman(_v2_pact(), consumer="Web", provider="Orders"))["response"][0]
    assert example["code"] == 200
    assert example["status"] == "OK"
    assert example["header"] == [{"key": "Content-Type", "value": "application/json; charset=utf-8"}]
    assert json.loads(example["body"]) == {"id": 42, "items": [{"sku": "A-1"}]}
    assert example["_postman_previewlanguage"] == "json"
    assert example["originalRequest"]["method"] == "GET"


def test_a_text_body_is_saved_as_text() -> None:
    interaction = _v4_http(
        response={"status": 200, "body": {"content": "<ok/>", "contentType": "application/xml", "encoded": False}}
    )
    example = _item(pact_to_postman(_v4_pact(interaction), consumer="Web", provider="Orders"))["response"][0]
    assert example["body"] == "<ok/>"
    assert example["_postman_previewlanguage"] == "xml"
    assert {"key": "Content-Type", "value": "application/xml"} in example["header"]


# --- test scripts ----------------------------------------------------------------------------


def test_scripts_check_status_headers_and_body() -> None:
    item = _item(pact_to_postman(_v2_pact(), consumer="Web", provider="Orders"))
    script = "\n".join(item["event"][0]["script"]["exec"])
    assert item["event"][0]["listen"] == "test"
    assert "pm.response.to.have.status(200)" in script
    assert "split(';')[0].trim().toLowerCase()).to.eql(\"application/json\")" in script
    assert "function pactMatches" in script
    assert 'pactMatches({"id": 42, "items": [{"sku": "A-1"}]}, pm.response.json())' in script


def test_tests_off_writes_no_scripts() -> None:
    item = _item(pact_to_postman(_v2_pact(), consumer="Web", provider="Orders", tests=False))
    assert "event" not in item


def test_an_explicitly_empty_response_body_must_be_empty() -> None:
    interaction = _v4_http(response={"status": 204, "body": {"content": ""}})
    script = "\n".join(_item(pact_to_postman(_v4_pact(interaction), consumer="Web", provider="Orders"))["event"][0]
                       ["script"]["exec"])
    assert "body is empty" in script
    assert "pactMatches" not in script


def _run_script(lines: List[str], status: int, headers: Dict[str, str], body: str) -> List[Dict[str, Any]]:
    """Run a test script in Node with a stub ``pm``; return each test's name and outcome."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    harness = (
        "const results = [];\n"
        "const status = " + json.dumps(status) + ";\n"
        "const headers = " + json.dumps({k.lower(): v for k, v in headers.items()}) + ";\n"
        "const text = " + json.dumps(body) + ";\n"
        "function expect(actual) { return {\n"
        "  to: { eql: function (want) { if (JSON.stringify(actual) !== JSON.stringify(want))"
        " throw new Error('expected ' + JSON.stringify(want) + ' got ' + JSON.stringify(actual)); },\n"
        "        be: { get true() { if (actual !== true) throw new Error('not true'); } } } }; }\n"
        "const pm = {\n"
        "  test: function (name, fn) { try { fn(); results.push({name, ok: true}); }"
        " catch (e) { results.push({name, ok: false}); } },\n"
        "  expect: expect,\n"
        "  response: {\n"
        "    to: { have: { status: function (s) { if (s !== status) throw new Error('status'); } } },\n"
        "    headers: { get: function (n) { return headers[n.toLowerCase()]; } },\n"
        "    json: function () { return JSON.parse(text); },\n"
        "    text: function () { return text; },\n"
        "  },\n"
        "};\n" + "\n".join(lines) + "\nconsole.log(JSON.stringify(results));\n"
    )
    out = subprocess.run([node, "-e", harness], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout)


def test_the_body_check_follows_pacts_default_rules_when_run() -> None:
    lines = _item(pact_to_postman(_v2_pact(), consumer="Web", provider="Orders"))["event"][0]["script"]["exec"]
    good = json.dumps({"id": 42, "extra": True, "items": [{"sku": "A-1", "name": "x"}]})
    passed = _run_script(lines, 200, {"Content-Type": "application/json"}, good)
    assert all(result["ok"] for result in passed), passed

    longer = json.dumps({"id": 42, "items": [{"sku": "A-1"}, {"sku": "B-2"}]})
    failed = {r["name"]: r["ok"] for r in _run_script(lines, 200, {"Content-Type": "application/json"}, longer)}
    assert failed["body matches the pact"] is False

    wrong = {r["name"]: r["ok"] for r in _run_script(lines, 500, {"Content-Type": "text/plain"}, good)}
    assert wrong["status is 200"] is False
    assert wrong["header Content-Type"] is False


# --- notices ---------------------------------------------------------------------------------


def test_message_interactions_are_left_out_with_a_reason() -> None:
    pact = _v4_pact(
        _v4_http(),
        {"type": "Asynchronous/Messages", "description": "an order event", "contents": {"content": {}}},
    )
    pact["messages"] = [{"description": "v3 message", "contents": {}}]
    export = pact_to_postman(pact, consumer="Web", provider="Orders")
    left_out = [n for n in export.notices if n.code == CODE_MESSAGE_LEFT_OUT]
    assert [(n.pointer, n.outcome, n.description) for n in left_out] == [
        ("/interactions/1", OUTCOME_LEFT_OUT, "an order event"),
        ("/messages/0", OUTCOME_LEFT_OUT, "v3 message"),
    ]
    assert (export.interaction_count, export.exported_count, export.left_out_count) == (3, 1, 2)


def test_a_grpc_plugin_call_is_left_out() -> None:
    grpc = {"type": "Synchronous/Messages", "transport": "grpc", "description": "GetOrder"}
    export = pact_to_postman(_v4_pact(grpc), consumer="Web", provider="Orders")
    assert _notice_codes(export) == [CODE_GRPC_LEFT_OUT]
    assert export.collection["item"] == []


def test_an_interaction_without_a_method_is_left_out() -> None:
    export = pact_to_postman(_v4_pact(_v4_http(request={"path": "/x"})), consumer="Web", provider="Orders")
    assert _notice_codes(export) == [CODE_INTERACTION_INVALID]
    assert export.notices[0].pointer == "/interactions/0"


def test_a_binary_request_body_leaves_the_interaction_out() -> None:
    binary = base64.b64encode(b"\xff\xfe\x00").decode()
    interaction = _v4_http(request={
        "method": "PUT", "path": "/files", "body": {"content": binary, "contentType": "image/png", "encoded": "base64"},
    })
    export = pact_to_postman(_v4_pact(interaction), consumer="Web", provider="Orders")
    assert export.notices[0].code == CODE_REQUEST_BODY_LEFT_OUT
    assert export.notices[0].outcome == OUTCOME_LEFT_OUT
    assert "not text" in export.notices[0].message
    assert export.exported_count == 0


def test_a_binary_response_body_is_not_saved_or_asserted() -> None:
    binary = base64.b64encode(b"\xff\xfe\x00").decode()
    interaction = _v4_http(response={
        "status": 200, "body": {"content": binary, "contentType": "image/png", "encoded": "base64"},
    })
    export = pact_to_postman(_v4_pact(interaction), consumer="Web", provider="Orders")
    assert CODE_BODY_NOT_ASSERTED in _notice_codes(export)
    item = _item(export)
    assert "body" not in item["response"][0]
    assert "pactMatches" not in "\n".join(item["event"][0]["script"]["exec"])


@pytest.mark.parametrize(
    "rules, expected_paths",
    [
        ({"body": {"$.id": {"matchers": [{"match": "type"}]}}}, ["$.id"]),
        ({"$.body.id": {"match": "type"}}, ["$.body.id"]),
        ({"header": {"Location": {"matchers": [{"match": "regex", "regex": "/orders/\\d+"}]}}}, ["header location"]),
    ],
)
def test_values_governed_by_matching_rules_are_not_asserted(rules: Dict[str, Any], expected_paths: List[str]) -> None:
    interaction = _v4_http()
    interaction["response"]["matchingRules"] = rules
    export = pact_to_postman(_v4_pact(interaction), consumer="Web", provider="Orders")
    notice = next(n for n in export.notices if n.code == CODE_MATCHING_RULES_NOT_ASSERTED)
    assert notice.outcome == OUTCOME_NOT_ASSERTED
    assert list(notice.paths) == expected_paths
    script = "\n".join(_item(export)["event"][0]["script"]["exec"])
    if any(path.startswith("$") for path in expected_paths):
        assert "pactMatches" not in script
        assert "Location" in script
    else:
        assert "pactMatches" in script
        assert "header Location" not in script
    # The saved example keeps the recorded values either way.
    assert json.loads(_item(export)["response"][0]["body"]) == {"id": 9}


def test_request_generators_are_reported_not_applied() -> None:
    interaction = _v4_http()
    interaction["request"]["generators"] = {"body": {"$.sku": {"type": "RandomString"}}}
    export = pact_to_postman(_v4_pact(interaction), consumer="Web", provider="Orders")
    notice = next(n for n in export.notices if n.code == CODE_GENERATORS_NOT_APPLIED)
    assert notice.outcome == OUTCOME_NOT_APPLIED
    assert notice.paths == ("body",)


def test_provider_states_are_listed_once_last() -> None:
    second = _v4_http(description="second", providerStates=[{"name": "a customer exists"}, {"name": "stock is low"}])
    export = pact_to_postman(_v4_pact(_v4_http(), second), consumer="Web", provider="Orders")
    notice = export.notices[-1]
    assert (notice.code, notice.outcome, notice.pointer) == (CODE_PROVIDER_STATES, OUTCOME_INFO, "")
    assert notice.paths == ("a customer exists", "stock is low")
    assert _item(export, 1)["request"]["description"] == "Given: a customer exists; stock is low"


def test_a_clean_pact_without_states_has_no_notices() -> None:
    interaction = _v4_http()
    del interaction["providerStates"]
    assert pact_to_postman(_v4_pact(interaction), consumer="Web", provider="Orders").notices == []


def test_notice_json_omits_empty_paths() -> None:
    export = pact_to_postman(
        _v4_pact({"type": "Asynchronous/Messages", "description": "evt"}), consumer="Web", provider="Orders"
    )
    assert export.notices[0].as_json() == {
        "code": CODE_MESSAGE_LEFT_OUT,
        "outcome": OUTCOME_LEFT_OUT,
        "pointer": "/interactions/0",
        "message": "a message interaction has no HTTP request for Postman to send",
        "description": "evt",
    }


def test_a_v3_pact_with_states_and_v3_rules_validates() -> None:
    pact = {
        "consumer": {"name": "Web"},
        "provider": {"name": "Orders"},
        "interactions": [
            {
                "description": "list orders",
                "providerStates": [{"name": "orders exist"}],
                "request": {"method": "GET", "path": "/orders", "query": {"page": ["1"]}},
                "response": {
                    "status": 200,
                    "headers": {"Content-Type": "application/json"},
                    "body": [{"id": 1}],
                    "matchingRules": {"body": {"$": {"matchers": [{"match": "type", "min": 1}]}}},
                },
            }
        ],
        "metadata": {"pactSpecification": {"version": "3.0.0"}},
    }
    export = pact_to_postman(pact, consumer="Web", provider="Orders")
    validate_postman_collection(json.dumps(export.collection))
    assert _notice_codes(export) == [CODE_MATCHING_RULES_NOT_ASSERTED, CODE_PROVIDER_STATES]
