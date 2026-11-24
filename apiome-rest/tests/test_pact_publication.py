"""What a valid pact is, and how one is addressed — PFX-1.2 (#6915).

Pure checks of :mod:`app.pact_publication`: parsing, the located refusals of an invalid document,
the content address, and the envelope of a bulk publish.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict

import pytest

from app.pact_publication import (
    CODE_PACT_INVALID,
    CODE_PACT_TOO_LARGE,
    CODE_PUBLISH_INVALID,
    CODE_PUBLISH_UNSUPPORTED,
    ContractToPublish,
    PactPublicationError,
    decode_contract_content,
    pact_content_sha,
    pact_record_from_row,
    parse_pact,
    prepare_pact,
    validate_pact_document,
)


def _pact(**overrides: Any) -> Dict[str, Any]:
    document: Dict[str, Any] = {
        "consumer": {"name": "Billing Service"},
        "provider": {"name": "Ledger API"},
        "interactions": [
            {
                "description": "a request for an invoice",
                "request": {"method": "GET", "path": "/invoices/42"},
                "response": {"status": 200, "body": {"id": 42}},
            }
        ],
        "metadata": {"pactSpecification": {"version": "2.0.0"}},
    }
    document.update(overrides)
    return document


def _refusal(document: Any) -> PactPublicationError:
    with pytest.raises(PactPublicationError) as refused:
        validate_pact_document(document)
    return refused.value


# --- parsing -----------------------------------------------------------------------------------


def test_parse_accepts_a_json_object() -> None:
    assert parse_pact(b'{"interactions": []}', max_bytes=100) == {"interactions": []}


@pytest.mark.parametrize("raw", [b"not json", b"[1, 2]", b'"text"', b"\xff\xfe"])
def test_parse_refuses_anything_but_a_json_object_at_the_root(raw: bytes) -> None:
    with pytest.raises(PactPublicationError) as refused:
        parse_pact(raw, max_bytes=100)
    assert (refused.value.code, refused.value.pointer) == (CODE_PACT_INVALID, "")


def test_parse_refuses_a_document_nested_too_deeply() -> None:
    raw = b'{"interactions": ' + b"[" * 100_000 + b"]" * 100_000 + b"}"
    with pytest.raises(PactPublicationError) as refused:
        parse_pact(raw, max_bytes=len(raw))
    assert (refused.value.code, refused.value.pointer) == (CODE_PACT_INVALID, "")


def test_parse_refuses_an_oversized_document_by_name() -> None:
    with pytest.raises(PactPublicationError) as refused:
        parse_pact(b"{" + b" " * 200 + b"}", max_bytes=100)
    assert refused.value.code == CODE_PACT_TOO_LARGE
    assert "202 bytes" in str(refused.value)


# --- validation --------------------------------------------------------------------------------


def test_each_specification_generation_is_a_pact() -> None:
    v1 = {
        "interactions": [{"description": "d", "request": {"method": "get", "path": "/"}, "response": {"status": 200}}]
    }
    v3_messages = {
        "messages": [{"description": "paid", "contents": {}}],
        "metadata": {"pactSpecification": {"version": "3.0.0"}},
    }
    v4 = {
        "interactions": [
            {
                "type": "Synchronous/HTTP",
                "description": "d",
                "request": {"method": "GET", "path": "/"},
                "response": {"status": 200},
            },
            {"type": "Asynchronous/Messages", "description": "m", "contents": {}},
            {"type": "Synchronous/Messages", "description": "rpc", "request": {"contents": {}}, "response": []},
        ],
        "metadata": {"pactSpecification": {"version": "4.0"}},
    }
    assert validate_pact_document(v1) == 1
    assert validate_pact_document(v3_messages) == 1
    assert validate_pact_document(v4) == 3
    assert validate_pact_document({"interactions": []}) == 0


@pytest.mark.parametrize(
    ("change", "pointer"),
    [
        ({"consumer": "Billing"}, "/consumer"),
        ({"consumer": {"name": ""}}, "/consumer/name"),
        ({"provider": {"name": 7}}, "/provider/name"),
        ({"metadata": []}, "/metadata"),
        ({"interactions": {}}, "/interactions"),
        ({"interactions": ["text"]}, "/interactions/0"),
        ({"interactions": [{"description": "d", "response": {}}]}, "/interactions/0/request"),
        ({"interactions": [{"request": {"path": "/"}, "response": {}}]}, "/interactions/0/request/method"),
        ({"interactions": [{"request": {"method": "GET", "path": 5}, "response": {}}]}, "/interactions/0/request/path"),
        ({"interactions": [{"request": {"method": "GET"}}]}, "/interactions/0/response"),
        (
            {"interactions": [{"request": {"method": "GET"}, "response": {"status": "200"}}]},
            "/interactions/0/response/status",
        ),
        (
            {"interactions": [{"request": {"method": "GET"}, "response": {"status": True}}]},
            "/interactions/0/response/status",
        ),
        ({"messages": "none"}, "/messages"),
        ({"messages": [None]}, "/messages/0"),
    ],
)
def test_an_invalid_pact_names_the_place(change: Dict[str, Any], pointer: str) -> None:
    refusal = _refusal(_pact(**change))
    assert (refusal.code, refusal.pointer) == (CODE_PACT_INVALID, pointer)
    assert str(refusal).startswith(pointer)


def test_the_second_broken_interaction_is_the_one_named() -> None:
    good = _pact()["interactions"][0]
    refusal = _refusal(_pact(interactions=[good, good, {"request": {}, "response": {}}]))
    assert refusal.pointer == "/interactions/2/request/method"


def test_a_document_with_neither_array_is_refused_at_the_root() -> None:
    refusal = _refusal({"consumer": {"name": "a"}, "provider": {"name": "b"}})
    assert refusal.pointer == ""
    assert "(document root)" in str(refusal)


# --- content address ---------------------------------------------------------------------------


def test_the_sha_ignores_metadata_noise_and_key_order() -> None:
    first = _pact()
    second = json.loads(json.dumps(_pact(), sort_keys=True))
    second["metadata"]["pact-js"] = {"version": "13.1.0"}
    second["consumer"] = {"name": "billing-service"}
    assert pact_content_sha(first) == pact_content_sha(second)
    assert len(pact_content_sha(first)) == 64


def test_the_sha_follows_interactions_their_order_and_the_specification() -> None:
    base = _pact()
    other = {"description": "another", "request": {"method": "GET", "path": "/b"}, "response": {"status": 200}}
    one = base["interactions"][0]
    shas = {
        pact_content_sha(base),
        pact_content_sha(_pact(interactions=[one, other])),
        pact_content_sha(_pact(interactions=[other, one])),
        pact_content_sha(_pact(metadata={"pactSpecification": {"version": "3.0.0"}})),
        pact_content_sha({"messages": base["interactions"]}),
    }
    assert len(shas) == 5


# --- prepare -----------------------------------------------------------------------------------


def test_prepare_takes_the_names_the_document_gives() -> None:
    pact = prepare_pact(
        json.dumps(_pact()).encode(), consumer_name="billing-service", provider_name="ledger-api", max_bytes=10_000
    )
    assert (pact.consumer_name, pact.provider_name) == ("Billing Service", "Ledger API")
    assert (pact.specification_version, pact.interaction_count) == ("2.0.0", 1)
    assert pact.document == _pact()
    assert pact.sha == pact_content_sha(_pact())


def test_prepare_falls_back_to_the_requested_names() -> None:
    pact = prepare_pact(b'{"interactions": []}', consumer_name="Web", provider_name="Api", max_bytes=100)
    assert (pact.consumer_name, pact.provider_name, pact.specification_version) == ("Web", "Api", None)


@pytest.mark.parametrize(
    ("consumer", "provider", "pointer"),
    [("Web", "Ledger API", "/consumer/name"), ("Billing Service", "Tax", "/provider/name")],
)
def test_prepare_refuses_a_document_for_someone_else(consumer: str, provider: str, pointer: str) -> None:
    with pytest.raises(PactPublicationError) as refused:
        prepare_pact(json.dumps(_pact()).encode(), consumer_name=consumer, provider_name=provider, max_bytes=10_000)
    assert (refused.value.code, refused.value.pointer) == (CODE_PACT_INVALID, pointer)


# --- bulk envelope -----------------------------------------------------------------------------


def _contract(**overrides: Any) -> ContractToPublish:
    payload = {
        "consumerName": "Billing Service",
        "providerName": "Ledger API",
        "content": base64.b64encode(b'{"interactions": []}').decode(),
    }
    payload.update(overrides)
    return ContractToPublish(**payload)


def test_contract_content_is_decoded() -> None:
    assert decode_contract_content(_contract(), 0) == b'{"interactions": []}'
    assert decode_contract_content(_contract(onConflict="overwrite", contentType="application/json; charset=utf-8"), 0)


@pytest.mark.parametrize(
    ("overrides", "code", "pointer"),
    [
        ({"specification": "oas"}, CODE_PUBLISH_UNSUPPORTED, "/contracts/3/specification"),
        ({"contentType": "application/yaml"}, CODE_PUBLISH_UNSUPPORTED, "/contracts/3/contentType"),
        ({"onConflict": "merge"}, CODE_PUBLISH_UNSUPPORTED, "/contracts/3/onConflict"),
        ({"content": "not base64!"}, CODE_PUBLISH_INVALID, "/contracts/3/content"),
    ],
)
def test_an_unusable_contract_is_refused_where_it_is(overrides: Dict[str, Any], code: str, pointer: str) -> None:
    with pytest.raises(PactPublicationError) as refused:
        decode_contract_content(_contract(**overrides), 3)
    assert (refused.value.code, refused.value.pointer) == (code, pointer)


# --- records -----------------------------------------------------------------------------------


def test_a_row_becomes_a_record() -> None:
    record = pact_record_from_row(
        {
            "consumer_slug": "billing-service",
            "consumer_name": "Billing Service",
            "provider_slug": "ledger-api",
            "provider_name": "Ledger API",
            "consumer_version": "1.0.0",
            "sha": "a" * 64,
            "content": json.dumps({"interactions": []}),
            "specification_version": None,
            "interaction_count": 0,
            "revision": 2,
        }
    )
    assert record.content == {"interactions": []}
    assert (record.revision, record.created_at) == (2, None)
