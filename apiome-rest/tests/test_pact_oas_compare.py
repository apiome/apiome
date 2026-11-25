"""Cross-contract comparison engine — PFX-2.2 (#6926).

The golden corpus under ``tests/golden/pact_oas_compare`` carries the acceptance criteria:
at least 60 pact / OpenAPI pairs with intended verdicts (pass, every failure class, partial),
pacts written by pact-js, pact-jvm and pact-go, deterministic output, and a 1 MB pact compared
in under two seconds. See that directory's README for how the corpus is laid out and changed.
"""

from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

from app.pact_oas_compare import (
    FAILURE_CLASSES,
    FIDELITY_CLASSES,
    MAX_INTERACTION_FINDINGS,
    WARNING_CLASSES,
    PactOasCompareError,
    compare_pact_to_oas,
)

CORPUS = Path(__file__).parent / "golden" / "pact_oas_compare"
CASES: List[Dict[str, Any]] = json.loads((CORPUS / "cases.json").read_text())
FOREIGN = sorted(path.name for path in (CORPUS / "foreign").glob("*.json"))
LEDGER = "providers/ledger-api-3.0.yaml"
UPDATE = os.environ.get("UPDATE_PACT_OAS_GOLDENS") == "1"


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


def _assert_golden(name: str, result: Dict[str, Any]) -> None:
    """Compare a comparison's output with its recorded golden (or record it)."""
    path = CORPUS / "expected" / f"{name}.json"
    actual = _without_detail(result)
    if UPDATE:
        path.write_text(json.dumps(actual, indent=2) + "\n")
    assert path.exists(), f"no golden for {name}; record it with UPDATE_PACT_OAS_GOLDENS=1"
    assert actual == json.loads(path.read_text())


def _codes(result: Dict[str, Any], kind: str) -> List[str]:
    """Every distinct code of one list (failures, warnings, fidelity) across interactions."""
    return sorted({item["code"] for one in result["interactions"] for item in one[kind]})


# =============================================================================================
# The corpus
# =============================================================================================


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_corpus_case_has_its_intended_verdict(case: Dict[str, Any]) -> None:
    result = compare_pact_to_oas(_load(case["pact"]), _load(case["provider"])).to_dict()

    assert result["verdict"] == case["verdict"]
    assert result["success"] is (case["verdict"] != "fail")
    assert _codes(result, "failures") == case["failureCodes"]
    assert _codes(result, "fidelity") == case["fidelityCodes"]
    assert _codes(result, "warnings") == case["warningCodes"]
    assert result["summary"]["failureCodes"] == case["failureCodes"]
    _assert_golden(case["id"], result)


def test_corpus_is_large_enough_and_covers_every_verdict() -> None:
    assert len(CASES) >= 60
    assert len({case["id"] for case in CASES}) == len(CASES)
    assert {case["verdict"] for case in CASES} == {"pass", "partial", "fail"}
    for case in CASES:
        assert case["id"].startswith(f"{case['verdict']}-")
    assert {case["provider"] for case in CASES} == {LEDGER, "providers/storefront-3.1.json"}


def test_corpus_covers_every_failure_warning_and_fidelity_class() -> None:
    def seen(key: str) -> set:
        return {code for case in CASES for code in case[key]}

    assert seen("failureCodes") == set(FAILURE_CLASSES)
    assert seen("warningCodes") == set(WARNING_CLASSES)
    assert seen("fidelityCodes") == set(FIDELITY_CLASSES)


def test_corpus_covers_every_pact_specification_version() -> None:
    majors = {_load(case["pact"])["metadata"]["pactSpecification"]["version"][0] for case in CASES}
    assert majors == {"1", "2", "3", "4"}


def test_every_pact_and_golden_belongs_to_a_case() -> None:
    ids = {case["id"] for case in CASES}
    assert {path.stem for path in (CORPUS / "pacts").glob("*.json")} == ids
    recorded = {path.stem for path in (CORPUS / "expected").glob("*.json")}
    assert recorded == ids | {f"foreign-{Path(name).stem}" for name in FOREIGN}


# =============================================================================================
# Foreign fixtures: pacts written by pact-js, pact-jvm and pact-go
# =============================================================================================


def test_foreign_fixtures_come_from_the_three_libraries() -> None:
    tools = set()
    for name in FOREIGN:
        tools |= set(_load(f"foreign/{name}")["metadata"]) - {"pactSpecification", "pactRust"}
    assert tools == {"pact-js", "pact-jvm", "pact-go"}


@pytest.mark.parametrize("name", FOREIGN)
def test_foreign_pact_is_compared_without_failures(name: str) -> None:
    pact = _load(f"foreign/{name}")
    result = compare_pact_to_oas(pact, _load(LEDGER)).to_dict()

    assert result["summary"]["interactions"] == len(pact["interactions"])
    assert result["summary"]["failures"] == 0
    assert all(one["operation"] is not None for one in result["interactions"])
    # Every rule the library wrote is accounted for: verified, unverified or not mapped.
    rules = result["summary"]["matchingRules"]
    assert rules["total"] == rules["verified"] + rules["unverified"] + rules["notMapped"] > 0
    assert rules["unverified"] + rules["notMapped"] == sum(
        note["code"].startswith("matching-rule")
        for one in result["interactions"]
        for note in one["fidelity"]
    )
    _assert_golden(f"foreign-{Path(name).stem}", result)


def test_foreign_verdicts() -> None:
    verdicts = {
        name: compare_pact_to_oas(_load(f"foreign/{name}"), _load(LEDGER)).verdict
        for name in FOREIGN
    }
    assert verdicts == {
        "pact-go-v4.json": "partial",  # decimal rules have no mapping
        "pact-js-v3.json": "partial",  # datetime and decimal rules, a path regex
        "pact-js-v4.json": "pass",  # every rule is proven by the provider's schema
        "pact-jvm-v3.json": "partial",  # a timestamp rule and its generator
    }


# =============================================================================================
# Determinism and purity
# =============================================================================================


def _reversed_keys(node: Any) -> Any:
    """The same JSON document with every object's keys in the opposite order."""
    if isinstance(node, dict):
        return {key: _reversed_keys(node[key]) for key in reversed(list(node))}
    if isinstance(node, list):
        return [_reversed_keys(item) for item in node]
    return node


@pytest.mark.parametrize(
    "pact_path",
    [
        "foreign/pact-jvm-v3.json",
        "pacts/fail-39-several-classes.json",
        "pacts/fail-31-response-unknown-in-array.json",
    ],
)
def test_output_is_deterministic(pact_path: str) -> None:
    pact, oas = _load(pact_path), _load(LEDGER)
    first = json.dumps(compare_pact_to_oas(pact, oas).to_dict())

    assert json.dumps(compare_pact_to_oas(pact, oas).to_dict()) == first
    # Key order in either document is not part of the answer.
    shuffled = compare_pact_to_oas(_reversed_keys(pact), _reversed_keys(oas)).to_dict()
    assert json.dumps(shuffled) == first


def test_inputs_are_not_modified() -> None:
    pact, oas = _load("foreign/pact-js-v3.json"), _load(LEDGER)
    pact_before, oas_before = copy.deepcopy(pact), copy.deepcopy(oas)

    compare_pact_to_oas(pact, oas)

    assert pact == pact_before
    assert oas == oas_before


def test_one_megabyte_pact_compares_in_under_two_seconds() -> None:
    base = _load("foreign/pact-jvm-v3.json")
    interactions: List[Dict[str, Any]] = []
    size = 0
    while size < 1_000_000:
        for interaction in base["interactions"]:
            clone = copy.deepcopy(interaction)
            clone["description"] = f"{clone['description']} #{len(interactions)}"
            interactions.append(clone)
            size += len(json.dumps(clone))
    pact = {**base, "interactions": interactions}
    assert len(json.dumps(pact)) >= 1_000_000
    oas = _load(LEDGER)

    started = time.perf_counter()
    result = compare_pact_to_oas(pact, oas)
    elapsed = time.perf_counter() - started

    assert len(result.interactions) == len(interactions)
    assert result.verdict == "partial"
    assert elapsed < 2.0, f"1 MB pact took {elapsed:.2f}s"


# =============================================================================================
# The shape of a result
# =============================================================================================


def test_failure_carries_pact_and_openapi_pointers() -> None:
    result = compare_pact_to_oas(
        _load("pacts/fail-30-response-unknown-nested.json"), _load(LEDGER)
    ).to_dict()
    (failure,) = result["interactions"][0]["failures"]

    assert failure["code"] == "response.body.unknown-property"
    assert failure["pactPointer"] == "/interactions/0/response/body/customer/email"
    # Operation-anchored, in the CTG-1.1 vocabulary ...
    assert failure["oasPointer"] == (
        "/paths/~1invoices~1{invoiceId}/get/responses/200/content/application~1json/schema"
        "/properties/customer/unevaluatedProperties"
    )
    # ... and the schema that would have to declare it, once the $ref is followed.
    assert failure["resolvedPointer"] == "/components/schemas/Party"
    assert "email" in failure["message"]
    assert failure["detail"]


def test_required_mismatch_names_the_missing_properties() -> None:
    result = compare_pact_to_oas(
        _load("pacts/fail-15-request-required-mismatch.json"), _load(LEDGER)
    ).to_dict()
    (failure,) = result["interactions"][0]["failures"]

    assert failure["code"] == "request.body.required-mismatch"
    assert "'currency', 'lines'" in failure["message"]
    assert failure["resolvedPointer"] == "/components/schemas/InvoiceCreate/required"
    assert failure["keyword"] == "required"


def test_pact_4_failure_points_inside_the_body_content() -> None:
    result = compare_pact_to_oas(_load("pacts/fail-37-v4-body-pointer.json"), _load(LEDGER))

    assert [failure.pact_pointer for failure in result.failures] == [
        "/interactions/0/response/body/content/balance"
    ]


def test_parameter_failure_uses_the_classifier_parameter_identity() -> None:
    result = compare_pact_to_oas(_load("pacts/fail-04-path-parameter-invalid.json"), _load(LEDGER))
    (failure,) = result.failures

    assert failure.oas_pointer == "/paths/~1invoices~1{invoiceId}/get/parameters/path:invoiceId"
    assert failure.resolved_pointer == "/components/parameters/InvoiceId/schema/type"


def test_interaction_lists_the_checks_that_ran() -> None:
    result = compare_pact_to_oas(_load("pacts/pass-06-type-rule-response-v2.json"), _load(LEDGER))
    (interaction,) = result.interactions

    assert interaction.checks == [
        "request.operation",
        "request.path-parameters",
        "request.query",
        "request.headers",
        "request.body",
        "response.status",
        "response.headers",
        "response.body",
        "response.matching-rules",
    ]
    assert interaction.operation == {
        "method": "get",
        "path": "/invoices/{invoiceId}",
        "pointer": "/paths/~1invoices~1{invoiceId}/get",
        "operationId": "getInvoice",
    }
    assert interaction.matching_rules == {
        "total": 3,
        "verified": 3,
        "unverified": 0,
        "notMapped": 0,
    }


def test_unresolved_operation_stops_the_checks_but_keeps_the_rules() -> None:
    pact = _load("pacts/fail-02-operation-unknown.json")
    pact["interactions"][0]["response"]["matchingRules"] = {"$.body.id": {"match": "type"}}

    (interaction,) = compare_pact_to_oas(pact, _load(LEDGER)).interactions

    assert interaction.checks == ["request.operation", "response.matching-rules"]
    assert interaction.operation is None
    # The rule could not be checked, and says so rather than disappearing.
    (note,) = interaction.fidelity
    assert (note.code, note.reason) == ("matching-rule-unverified", "no-provider-schema")


def test_findings_beyond_the_cap_are_counted_not_dropped() -> None:
    result = compare_pact_to_oas(_load("pacts/fail-38-findings-truncated.json"), _load(LEDGER))
    (interaction,) = result.interactions

    assert len(interaction.failures) <= MAX_INTERACTION_FINDINGS
    (note,) = interaction.fidelity
    assert note.code == "findings-truncated"
    assert note.message.split()[0].isdigit()


def test_summary_counts_add_up() -> None:
    result = compare_pact_to_oas(
        _load("pacts/fail-36-mixed-interactions.json"), _load(LEDGER)
    ).to_dict()
    summary = result["summary"]

    assert [summary[key] for key in ("interactions", "passed", "partial", "failed")] == [2, 1, 0, 1]
    assert [one["verdict"] for one in result["interactions"]] == ["pass", "fail"]
    assert result["consumer"] == "corpus-consumer"
    assert result["pactSpecification"] == "2.0.0"
    assert result["oasVersion"] == "3.0.3"


# =============================================================================================
# Inputs that cannot be compared
# =============================================================================================


@pytest.mark.parametrize(
    "pact, oas, message",
    [
        ([], {"openapi": "3.1.0"}, "pact is not a JSON object"),
        ({}, "openapi: 3.1.0", "provider contract is not a JSON object"),
        ({}, {"swagger": "2.0"}, "not an OpenAPI 3.x document"),
        ({}, {"openapi": 3.1}, "not an OpenAPI 3.x document"),
    ],
)
def test_inputs_that_are_not_a_pact_and_an_openapi_document_are_refused(
    pact: Any, oas: Any, message: str
) -> None:
    with pytest.raises(PactOasCompareError, match=message):
        compare_pact_to_oas(pact, oas)


def test_document_without_paths_fails_every_interaction_by_name() -> None:
    pact = _load("pacts/pass-01-get-invoice-v2.json")
    result = compare_pact_to_oas(pact, {"openapi": "3.1.0", "info": {"title": "t", "version": "1"}})

    assert result.verdict == "fail"
    assert [f.code for f in result.failures] == ["request.operation.unknown"]


def test_malformed_provider_schema_degrades_to_not_compared() -> None:
    oas = {
        "openapi": "3.1.0",
        "paths": {
            "/things": {
                "get": {
                    "parameters": [{"name": "n", "in": "query", "schema": {"type": 17}}],
                    "responses": {
                        "200": {"content": {"application/json": {"schema": {"type": "strnig"}}}}
                    },
                }
            }
        },
    }
    pact = {
        "interactions": [
            {
                "description": "things",
                "request": {"method": "GET", "path": "/things", "query": "n=1"},
                "response": {"status": 200, "body": {"a": 1}},
            }
        ]
    }

    result = compare_pact_to_oas(pact, oas)

    assert result.verdict == "partial"
    assert {note.code for note in result.fidelity} == {"schema-not-usable"}


def test_pointer_with_reserved_characters_resolves() -> None:
    oas = {
        "openapi": "3.0.3",
        "paths": {
            "/a b%/{x}": {
                "get": {
                    "parameters": [
                        {"name": "x", "in": "path", "required": True, "schema": {"type": "integer"}}
                    ],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"n#": {"type": "integer"}},
                                    }
                                }
                            }
                        }
                    },
                }
            }
        },
    }
    pact = {
        "interactions": [
            {
                "description": "odd path",
                "request": {"method": "GET", "path": "/a b%/7"},
                "response": {"status": 200, "body": {"n#": "seven"}},
            }
        ]
    }

    (failure,) = compare_pact_to_oas(pact, oas).failures

    assert failure.code == "response.body.schema-mismatch"
    assert failure.resolved_pointer.endswith("/schema/properties/n#/type")


def test_runaway_nesting_costs_one_interaction_not_the_run() -> None:
    deep: Any = 1
    for _ in range(3000):
        deep = {"a": deep}
    pact = _load("pacts/pass-01-get-invoice-v2.json")
    pact["interactions"].append(
        {
            "description": "deep",
            "request": {"method": "GET", "path": "/invoices/1042"},
            "response": {"status": 200, "body": deep},
        }
    )

    result = compare_pact_to_oas(pact, _load(LEDGER))

    assert [one.verdict for one in result.interactions] == ["pass", "partial"]
    assert [(n.code, n.reason) for n in result.fidelity] == [("body-not-compared", "too-deep")]


# =============================================================================================
# The published rule set
# =============================================================================================

RULES_PAGE = (
    Path(__file__).resolve().parents[2]
    / "apiome-docs"
    / "docs"
    / "ship"
    / "pact-broker"
    / "comparison-rules.mdx"
)


@pytest.mark.skipif(not RULES_PAGE.exists(), reason="the docs site is not in this checkout")
def test_comparison_rules_page_lists_every_code_matcher_and_reason() -> None:
    """The page is the table of every rule and mapping; a new code must be explained there."""
    from app.pact_matching_rules import MATCHER_MAPPINGS, NOT_MAPPED_REASONS, UNVERIFIED_REASONS

    page = RULES_PAGE.read_text()
    documented = [*FAILURE_CLASSES, *WARNING_CLASSES, *FIDELITY_CLASSES]
    documented += [*UNVERIFIED_REASONS, *NOT_MAPPED_REASONS]
    for mapping in MATCHER_MAPPINGS:
        documented += mapping.matcher.split(" / ")
        if mapping.constraint is not None:
            assert f"`{mapping.constraint}`" in page, mapping.matcher

    missing = [name for name in documented if f"`{name}`" not in page]
    assert missing == []
    for description in (*FAILURE_CLASSES.values(), *FIDELITY_CLASSES.values()):
        assert description in page


def test_parameter_text_that_is_no_number_is_validated_as_text() -> None:
    pact = _load("pacts/pass-02-list-query-string-v2.json")
    pact["interactions"][0]["request"]["query"] = "limit=" + "9" * 5000

    (failure,) = compare_pact_to_oas(pact, _load(LEDGER)).failures

    assert (failure.code, failure.keyword) == ("request.query.invalid", "type")
