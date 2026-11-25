"""Unit tests for the pact → contract-suite compiler — PFX-3.1 (#6931).

:func:`app.contract_suite_pact.compile_pact_suite` is pure, so every property is checked on parsed
pacts directly:

* one ``pact_interaction`` case per HTTP interaction, the request exactly as recorded across Pact
  specifications 1–4, the expected response, provider states, matching rules and generators in
  the ``pact`` block;
* the manifest is byte-identical per (pact version, options) — metadata and key order never
  change the digest, options and content always do;
* nothing is dropped silently: every interaction of every corpus pact is either a case or listed
  under ``unsupported``, and each degraded or unsupported reading has its finding.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.contract_runner import status_code_matches
from app.contract_suite import (
    CASE_SOURCE_PACT_INTERACTION,
    CASE_SOURCES,
    CODE_NO_CASES_COMPILED,
    CODE_OPERATION_LIMIT_REACHED,
    CODE_OPERATION_NOT_SELECTED,
    CODE_PACT_BODY_UNREADABLE,
    CODE_PACT_EMBEDDED_MATCHER,
    CODE_PACT_INTERACTION_MALFORMED,
    CODE_PACT_MATCHING_RULE_UNSUPPORTED,
    CODE_PACT_PLUGIN_INTERACTION,
    CODE_PACT_PROVIDER_STATE,
    CODE_PACT_PROVIDER_STATE_UNREADABLE,
    CODE_PACT_REQUEST_GENERATOR,
    CODE_PACT_RESPONSE_GENERATOR,
    CODE_PACT_SPECIFICATION_ASSUMED,
    CODE_STATUS_UNDECLARED,
    CODE_UNSUPPORTED_OPERATION_KIND,
    CONTRACT_SUITE_COMPILER_VERSION,
    CONTRACT_SUITE_SCHEMA_VERSION,
    FINDING_DEGRADED,
    FINDING_INFO,
    FINDING_UNSUPPORTED,
    OUTCOME_CLIENT_ERROR,
    OUTCOME_SUCCESS,
    SUITE_FINDING_CODES,
    ContractSuiteManifest,
    PactSuiteOptions,
    SuiteSourceInfo,
    canonical_manifest_bytes,
    manifest_digest,
)
from app.contract_suite_pact import KNOWN_MATCHERS, ORIGIN_PACT, STATUS_CLASSES, compile_pact_suite
from app.pact_publication import pact_content_sha

_CORPUS = Path(__file__).parent / "golden" / "pact_oas_compare" / "pacts"


def _pact(interactions: List[Dict[str, Any]], version: str = "3.0.0", **extra: Any) -> Dict[str, Any]:
    document: Dict[str, Any] = {
        "consumer": {"name": "billing"},
        "provider": {"name": "ledger"},
        "interactions": interactions,
        "metadata": {"pactSpecification": {"version": version}},
    }
    document.update(extra)
    return document


def _get(description: str = "get invoice", path: str = "/invoices/1042", **extra: Any) -> Dict[str, Any]:
    interaction: Dict[str, Any] = {
        "description": description,
        "providerStates": [{"name": "invoice 1042 exists", "params": {"id": 1042}}],
        "request": {"method": "get", "path": path, "headers": {"Accept": "application/json"}},
        "response": {
            "status": 200,
            "headers": {"Content-Type": "application/json"},
            "body": {"id": 1042, "number": "INV-1042"},
            "matchingRules": {"body": {"$.id": {"matchers": [{"match": "integer"}]}}},
        },
    }
    interaction.update(extra)
    return interaction


def _compile(document: Dict[str, Any], **options: Any) -> ContractSuiteManifest:
    return compile_pact_suite(
        document,
        consumer="billing",
        provider="ledger",
        options=PactSuiteOptions(**options) if options else None,
    )


def _codes(manifest: ContractSuiteManifest) -> List[str]:
    return [finding.code for finding in manifest.findings]


# =============================================================================================
# The case
# =============================================================================================


def test_one_http_interaction_becomes_one_attributed_pact_case() -> None:
    manifest = _compile(_pact([_get()]))

    assert [case.source for case in manifest.cases] == [CASE_SOURCE_PACT_INTERACTION]
    case = manifest.cases[0]
    assert case.operation_key == "GET /invoices/1042"
    assert case.operation_name == case.title == "get invoice"
    assert case.synthetic is False
    assert case.protocol == "http"
    assert case.source_pointer == "/interactions/0"
    assert case.case_id.startswith("case_")
    assert case.tags == ["pact"]
    assert "invoice 1042 exists" in case.description


def test_the_request_is_carried_exactly_as_recorded() -> None:
    interaction = _get(
        request={
            "method": "POST",
            "path": "/invoices",
            "query": {"expand": ["lines", "customer"], "dryRun": ["true"]},
            "headers": {"Content-Type": "application/json; charset=utf-8", "X-Trace": "t-1"},
            "body": {"number": "INV-1"},
        }
    )
    case = _compile(_pact([interaction])).cases[0]

    request = case.request
    assert (request.method, request.path, request.path_template) == ("POST", "/invoices", "/invoices")
    assert request.has_body is True
    assert request.body == {"number": "INV-1"}
    assert request.media_type == "application/json"
    assert [(p.location, p.name, p.value) for p in request.parameters] == [
        ("query", "dryRun", "true"),
        ("query", "expand", "lines"),
        ("query", "expand", "customer"),
        ("header", "Content-Type", "application/json; charset=utf-8"),
        ("header", "X-Trace", "t-1"),
    ]
    assert {p.origin for p in request.parameters} == {ORIGIN_PACT}


def test_a_pact_2_query_string_is_read_like_a_pact_3_object() -> None:
    v2 = _get(request={"method": "GET", "path": "/invoices", "query": "status=open&status=paid&page=2"})
    v3 = _get(request={"method": "GET", "path": "/invoices", "query": {"status": ["open", "paid"], "page": ["2"]}})

    first = _compile(_pact([v2], version="2.0.0")).cases[0].request.parameters
    second = _compile(_pact([v3])).cases[0].request.parameters
    assert first == second


def test_a_pact_4_body_object_is_unwrapped_and_its_header_lists_joined() -> None:
    interaction = {
        "type": "Synchronous/HTTP",
        "key": "abc123",
        "description": "create",
        "pending": True,
        "request": {
            "method": "POST",
            "path": "/invoices",
            "headers": {"Accept": ["application/json", "text/plain"]},
            "body": {"content": {"number": "INV-2"}, "contentType": "application/json", "encoded": False},
        },
        "response": {
            "status": 201,
            "body": {"content": "eyJpZCI6IDd9", "contentType": "application/json", "encoded": "base64"},
        },
    }
    case = _compile(_pact([interaction], version="4.0")).cases[0]

    assert case.request.body == {"number": "INV-2"}
    assert case.request.media_type == "application/json"
    assert case.request.parameters[0].value == "application/json, text/plain"
    assert case.pact is not None
    assert case.pact.key == "abc123"
    assert case.pact.interaction_type == "Synchronous/HTTP"
    assert case.pact.pending is True
    assert case.tags == ["pact", "pending"]
    assert case.source_detail == "abc123"
    assert case.pact.response.body == {"id": 7}
    assert case.pact.response.media_type == "application/json"
    assert case.pact.response.body_pointer == "/interactions/0/response/body/content"


def test_a_text_body_is_sent_as_text() -> None:
    interaction = _get(
        request={"method": "PUT", "path": "/notes/1", "headers": {"Content-Type": "text/plain"}, "body": "hello"}
    )
    request = _compile(_pact([interaction])).cases[0].request
    assert (request.body, request.media_type) == ("hello", "text/plain")


def test_an_interaction_without_a_body_sends_none() -> None:
    request = _compile(_pact([_get()])).cases[0].request
    assert request.has_body is False
    assert request.body is None and request.media_type is None


# =============================================================================================
# The expectation
# =============================================================================================


def test_the_expected_response_is_carried_with_its_rules() -> None:
    case = _compile(_pact([_get()])).cases[0]

    assert case.expect.status_codes == ["200"]
    assert case.expect.status_declared is True
    assert case.expect.outcome == OUTCOME_SUCCESS
    assert case.expect.response_schema_id is None
    response = case.pact.response
    assert response.status == 200
    assert response.headers == {"Content-Type": "application/json"}
    assert response.body == {"id": 1042, "number": "INV-1042"}
    assert response.media_type == "application/json"
    assert [(r.category, r.path, r.match) for r in response.matching_rules] == [("body", "$.id", "integer")]
    assert response.matching_rules[0].pointer == "/interactions/0/response/matchingRules/body/$.id/matchers/0"


def test_a_4xx_response_expects_a_client_error() -> None:
    interaction = _get(response={"status": 404, "body": {"error": "not found"}})
    case = _compile(_pact([interaction])).cases[0]
    assert case.expect.status_codes == ["404"]
    assert case.expect.outcome == OUTCOME_CLIENT_ERROR


@pytest.mark.parametrize(
    ("status", "tokens"),
    [
        ("success", ["2XX"]),
        ("clientError", ["4XX"]),
        ("nonError", ["1XX", "2XX", "3XX"]),
        ("error", ["4XX", "5XX"]),
        ([201, 200], ["200", "201"]),
    ],
)
def test_a_pact_4_status_code_rule_widens_the_status(status: Any, tokens: List[str]) -> None:
    interaction = {
        "type": "Synchronous/HTTP",
        "description": "get",
        "request": {"method": "GET", "path": "/x"},
        "response": {
            "status": 200,
            "matchingRules": {"status": {"combine": "AND", "matchers": [{"match": "statusCode", "status": status}]}},
        },
    }
    case = _compile(_pact([interaction], version="4.0")).cases[0]
    assert case.expect.status_codes == tokens
    assert CODE_PACT_MATCHING_RULE_UNSUPPORTED not in _codes(_compile(_pact([interaction], version="4.0")))


def test_every_status_class_is_a_token_the_runner_matches() -> None:
    for name, tokens in STATUS_CLASSES.items():
        assert any(status_code_matches(code, tokens) for code in range(100, 600)), name


def test_an_unreadable_status_code_rule_keeps_the_exact_status_and_says_so() -> None:
    interaction = {
        "description": "get",
        "request": {"method": "GET", "path": "/x"},
        "response": {
            "status": 200,
            "matchingRules": {"status": {"matchers": [{"match": "statusCode", "status": "sometimes"}]}},
        },
    }
    manifest = _compile(_pact([interaction], version="4.0"))
    assert manifest.cases[0].expect.status_codes == ["200"]
    assert CODE_PACT_MATCHING_RULE_UNSUPPORTED in _codes(manifest)


def test_a_response_without_a_status_expects_200_and_reports_it() -> None:
    manifest = _compile(_pact([_get(response={"body": {"ok": True}})]))
    case = manifest.cases[0]
    assert case.expect.status_codes == ["200"]
    assert case.expect.status_declared is False
    assert case.pact.response.status is None
    assert CODE_STATUS_UNDECLARED in _codes(manifest)


# =============================================================================================
# Provider states
# =============================================================================================


def test_provider_states_are_carried_with_params_and_reported_once() -> None:
    manifest = _compile(_pact([_get(), _get("get again", "/invoices/1042?x")]))

    assert [state.model_dump() for state in manifest.cases[0].pact.provider_states] == [
        {"name": "invoice 1042 exists", "params": {"id": 1042}}
    ]
    states = [f for f in manifest.findings if f.code == CODE_PACT_PROVIDER_STATE]
    assert len(states) == 1
    assert states[0].level == FINDING_INFO
    assert states[0].pointer == "/interactions/0/providerStates/0"


@pytest.mark.parametrize("spelling", ["providerState", "provider_state"])
def test_a_pact_1_or_2_provider_state_is_read(spelling: str) -> None:
    interaction = _get()
    del interaction["providerStates"]
    interaction[spelling] = "an invoice exists"
    case = _compile(_pact([interaction], version="2.0.0")).cases[0]
    assert [state.name for state in case.pact.provider_states] == ["an invoice exists"]
    assert case.pact.provider_states[0].params == {}


def test_a_nameless_provider_state_is_reported_not_kept() -> None:
    manifest = _compile(_pact([_get(providerStates=[{"params": {"id": 1}}, {"name": "ready"}])]))
    assert [state.name for state in manifest.cases[0].pact.provider_states] == ["ready"]
    unreadable = [f for f in manifest.findings if f.code == CODE_PACT_PROVIDER_STATE_UNREADABLE]
    assert unreadable and unreadable[0].pointer == "/interactions/0/providerStates/0"


# =============================================================================================
# Matching rules and generators
# =============================================================================================


def test_pact_2_rules_are_read_into_the_same_shape() -> None:
    interaction = _get(response={"status": 200, "body": {"id": 1}, "matchingRules": {"$.body.id": {"match": "type"}}})
    rule = _compile(_pact([interaction], version="2.0.0")).cases[0].pact.response.matching_rules[0]
    assert (rule.category, rule.path, rule.match, rule.combine) == ("body", "$.id", "type", "AND")
    assert rule.matcher == {"match": "type"}


def test_request_rules_are_carried_and_the_example_is_sent() -> None:
    interaction = _get(
        request={
            "method": "GET",
            "path": "/invoices/1042",
            "matchingRules": {"path": {"matchers": [{"match": "regex", "regex": "/invoices/\\d+"}]}},
        }
    )
    case = _compile(_pact([interaction])).cases[0]
    assert case.request.path == "/invoices/1042"
    assert [(r.category, r.match) for r in case.pact.request_matching_rules] == [("path", "regex")]


@pytest.mark.parametrize(
    ("rules", "fragment"),
    [
        ({"body": {"$.id": {"matchers": [{"match": "fuzzy"}]}}}, "'fuzzy'"),
        ({"body": {"id[": {"matchers": [{"match": "type"}]}}}, "not a JSONPath"),
        ({"cookies": {"a": {"matchers": [{"match": "type"}]}}}, "part of the message"),
    ],
)
def test_a_rule_no_verifier_can_apply_is_carried_and_reported(rules: Dict[str, Any], fragment: str) -> None:
    manifest = _compile(_pact([_get(response={"status": 200, "body": {"id": 1}, "matchingRules": rules})]))
    assert len(manifest.cases[0].pact.response.matching_rules) == 1
    reported = [f for f in manifest.findings if f.code == CODE_PACT_MATCHING_RULE_UNSUPPORTED]
    assert reported and fragment in reported[0].message
    assert reported[0].level == FINDING_DEGRADED


def test_every_documented_matcher_is_known() -> None:
    for kind in ("type", "regex", "include", "decimal", "eachkey", "arraycontains", "statuscode", "semver"):
        assert kind in KNOWN_MATCHERS


def test_generators_are_carried_and_reported_by_side() -> None:
    document = json.loads((_CORPUS / "partial-13-generators.json").read_text())
    manifest = _compile(document)
    pact = manifest.cases[0].pact

    assert [(g.category, g.path, g.type) for g in pact.request_generators] == [("path", "", "ProviderState")]
    assert [(g.category, g.path, g.type) for g in pact.response.generators] == [("body", "$.id", "RandomInt")]
    request = next(f for f in manifest.findings if f.code == CODE_PACT_REQUEST_GENERATOR)
    response = next(f for f in manifest.findings if f.code == CODE_PACT_RESPONSE_GENERATOR)
    assert request.level == FINDING_DEGRADED and "provider state" in request.message
    assert response.level == FINDING_INFO
    assert request.pointer == "/interactions/0/request/generators/path"


def test_embedded_pact_1_matchers_are_stripped_and_reported() -> None:
    document = json.loads((_CORPUS / "partial-22-embedded-ruby-matchers.json").read_text())
    manifest = _compile(document)
    assert manifest.cases[0].pact.response.body == {"id": 1042, "number": "INV-1042"}
    assert CODE_PACT_EMBEDDED_MATCHER in _codes(manifest)


# =============================================================================================
# Unsupported interactions
# =============================================================================================


def test_message_interactions_are_listed_as_unsupported() -> None:
    v4 = _pact(
        [_get(), {"type": "Asynchronous/Messages", "description": "invoice created", "contents": {}}],
        version="4.0",
    )
    manifest = _compile(v4)
    assert len(manifest.cases) == 1
    assert [(u.operation_key, u.code) for u in manifest.unsupported] == [
        ("/interactions/1", CODE_UNSUPPORTED_OPERATION_KIND)
    ]
    finding = next(f for f in manifest.findings if f.code == CODE_UNSUPPORTED_OPERATION_KIND)
    assert finding.level == FINDING_UNSUPPORTED and "PFX-3.6" in finding.message


def test_a_pact_3_message_pact_compiles_no_cases_and_says_why() -> None:
    document = json.loads((_CORPUS / "partial-21-message-pact-v3.json").read_text())
    manifest = _compile(document)
    assert manifest.cases == []
    assert manifest.unsupported
    assert {CODE_UNSUPPORTED_OPERATION_KIND, CODE_NO_CASES_COMPILED} <= set(_codes(manifest))


def test_a_plugin_interaction_is_unsupported() -> None:
    plugin = _get(type="Synchronous/HTTP", pluginConfiguration={"protobuf": {"descriptorKey": "x"}})
    manifest = _compile(_pact([plugin], version="4.0"))
    assert manifest.cases == []
    assert manifest.unsupported[0].code == CODE_PACT_PLUGIN_INTERACTION
    assert manifest.unsupported[0].operation_key == "GET /invoices/1042"


@pytest.mark.parametrize(
    "interaction",
    [
        "not an object",
        {"description": "no request", "response": {"status": 200}},
        {"description": "no method", "request": {"path": "/x"}, "response": {"status": 200}},
        {"description": "bad path", "request": {"method": "GET", "path": 7}, "response": {}},
    ],
)
def test_a_malformed_interaction_is_unsupported(interaction: Any) -> None:
    manifest = _compile(_pact([interaction]))
    assert manifest.cases == []
    assert manifest.unsupported[0].code == CODE_PACT_INTERACTION_MALFORMED
    assert manifest.unsupported[0].operation_key == "/interactions/0"


def test_an_undecodable_request_body_is_unsupported_and_a_response_body_degraded() -> None:
    bad = {"content": "////", "contentType": "application/json", "encoded": "base64"}
    request_side = _get(request={"method": "POST", "path": "/x", "body": bad})
    response_side = _get(response={"status": 200, "body": bad})

    first = _compile(_pact([request_side], version="4.0"))
    assert first.cases == [] and first.unsupported[0].code == CODE_PACT_BODY_UNREADABLE

    second = _compile(_pact([response_side], version="4.0"))
    assert len(second.cases) == 1
    assert second.cases[0].pact.response.has_body is True
    assert second.cases[0].pact.response.body is None
    degraded = next(f for f in second.findings if f.code == CODE_PACT_BODY_UNREADABLE)
    assert degraded.level == FINDING_DEGRADED


def test_a_pact_with_no_interactions_reports_no_cases() -> None:
    manifest = _compile(_pact([]))
    assert manifest.cases == [] and CODE_NO_CASES_COMPILED in _codes(manifest)


@pytest.mark.parametrize(
    ("metadata", "level"),
    [({}, FINDING_INFO), ({"pactSpecification": {"version": "9.0"}}, FINDING_DEGRADED)],
)
def test_a_missing_or_unknown_specification_is_reported(metadata: Dict[str, Any], level: str) -> None:
    document = _pact([_get()])
    document["metadata"] = metadata
    finding = next(f for f in _compile(document).findings if f.code == CODE_PACT_SPECIFICATION_ASSUMED)
    assert finding.level == level


def test_every_interaction_of_the_corpus_is_a_case_or_unsupported() -> None:
    pacts = sorted(_CORPUS.glob("*.json"))
    assert len(pacts) > 50
    for path in pacts:
        document = json.loads(path.read_text())
        total = len(document.get("interactions", [])) + len(document.get("messages", []))
        manifest = _compile(document)
        assert len(manifest.cases) + len(manifest.unsupported) == total, path.name
        assert manifest.pact.interaction_count == total
        assert set(_codes(manifest)) <= set(SUITE_FINDING_CODES), path.name


# =============================================================================================
# Options
# =============================================================================================


def test_interactions_can_be_selected_by_description_or_key() -> None:
    keyed = _get("by key", "/b", key="k-2")
    manifest = _compile(_pact([_get("first", "/a"), keyed, _get("third", "/c")]), interactions=["k-2", "first", "nope"])

    assert [case.title for case in manifest.cases] == ["first", "by key"]
    missing = [f for f in manifest.findings if f.code == CODE_OPERATION_NOT_SELECTED]
    assert len(missing) == 1 and "'nope'" in missing[0].message


def test_max_interactions_truncates_and_reports() -> None:
    manifest = _compile(_pact([_get(f"i{n}", f"/p{n}") for n in range(5)]), max_interactions=3)
    assert len(manifest.cases) == 3
    assert manifest.counts["operations_skipped"] == 2
    assert CODE_OPERATION_LIMIT_REACHED in _codes(manifest)


def test_option_order_does_not_change_the_digest() -> None:
    document = _pact([_get("a", "/a"), _get("b", "/b")])
    first = _compile(document, interactions=["a", "b"])
    second = _compile(document, interactions=["b", "a", "a"])
    assert first.digest == second.digest
    assert first.pact.options.interactions == ["a", "b"]


def test_options_reject_unknown_fields_and_out_of_range_caps() -> None:
    with pytest.raises(ValueError):
        PactSuiteOptions(seed=1)  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        PactSuiteOptions(max_interactions=0)


# =============================================================================================
# The manifest and its digest
# =============================================================================================


def test_the_manifest_identifies_its_pact_version() -> None:
    document = _pact([_get()])
    manifest = _compile(document)

    assert manifest.schema_version == CONTRACT_SUITE_SCHEMA_VERSION == 4
    assert manifest.compiler_version == CONTRACT_SUITE_COMPILER_VERSION == 4
    assert manifest.options is None
    assert manifest.protocol == "http"
    assert manifest.api.name == "ledger" and manifest.api.format == "pact-3.0.0"
    assert manifest.pact.model_dump() == {
        "consumer": "billing",
        "provider": "ledger",
        "pact_version_sha": pact_content_sha(document),
        "specification_version": "3.0.0",
        "interaction_count": 1,
        "options": {"interactions": None, "max_interactions": 500},
    }
    assert manifest.counts[CASE_SOURCE_PACT_INTERACTION] == 1
    assert set(CASE_SOURCES) <= set(manifest.counts)
    assert [(op.key, op.case_count) for op in manifest.operations] == [("GET /invoices/1042", 1)]


def test_the_digest_is_sha256_over_the_canonical_bytes() -> None:
    manifest = _compile(_pact([_get()]))
    assert manifest.digest.startswith("sha256:") and len(manifest.digest) == 71
    assert manifest.digest == manifest_digest(manifest)
    reread = ContractSuiteManifest.model_validate_json(canonical_manifest_bytes(manifest))
    assert canonical_manifest_bytes(reread) == canonical_manifest_bytes(manifest)


def test_the_same_pact_version_compiles_byte_identically() -> None:
    document = _pact([_get("b", "/b"), _get("a", "/a")])
    # A second consumer version publishing the same content: other metadata, other key order.
    republished = json.loads(json.dumps(document, sort_keys=True))
    republished["metadata"]["pact-js"] = {"version": "12.1.0"}
    republished["consumer"] = {"name": "Billing (renamed in file)"}
    assert pact_content_sha(republished) == pact_content_sha(document)

    assert canonical_manifest_bytes(_compile(document)) == canonical_manifest_bytes(_compile(republished))


def test_a_content_change_changes_the_digest() -> None:
    document = _pact([_get()])
    changed = copy.deepcopy(document)
    changed["interactions"][0]["response"]["status"] = 201
    assert _compile(document).digest != _compile(changed).digest


def test_cases_are_grouped_by_operation_then_pact_order() -> None:
    manifest = _compile(_pact([_get("z", "/b"), _get("y", "/a"), _get("x", "/b")]))
    assert [(case.operation_key, case.title) for case in manifest.cases] == [
        ("GET /a", "y"),
        ("GET /b", "z"),
        ("GET /b", "x"),
    ]
    assert len({case.case_id for case in manifest.cases}) == 3


def test_the_source_is_echoed() -> None:
    source = SuiteSourceInfo(kind="pact", reference="pact/ledger/billing/" + "a" * 64)
    manifest = compile_pact_suite(_pact([_get()]), consumer="billing", provider="ledger", source=source)
    assert manifest.source == source
