"""Reading a source broker from the server — PFX-8.16 (#7313).

No network: the source is an httpx mock transport (``tests/pact_migration_fakes.py``).
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from app.pact_migration_plan import KINDS, Plan
from app.pact_migration_source import (
    CODE_SOURCE_INVALID,
    CODE_SOURCE_REFUSED,
    CODE_SOURCE_UNREADABLE,
    SourceBroker,
    SourceError,
    fetch_document,
    product_of,
    read_source,
)
from tests.pact_migration_fakes import SOURCE, FakeSource, documents

TOKEN = "s3cr3t-read-token"


def _broker(source: FakeSource, **credentials: Any) -> SourceBroker:
    return SourceBroker(SOURCE, transport=source.transport(), **(credentials or {"token": TOKEN}))


def test_everything_is_read_with_get_and_the_token() -> None:
    source = FakeSource()
    plan = Plan()
    with _broker(source) as broker:
        to_fetch = read_source(broker, plan)
    assert {request.method for request in source.requests} == {"GET"}
    assert {request.headers["authorization"] for request in source.requests} == {f"Bearer {TOKEN}"}
    assert {kind: len(plan.records[kind]) for kind in KINDS} == {
        "pacticipant": 2,
        "environment": 1,
        "version": 4,
        "pact": 3,
        "verification": 3,
        "deployment": 1,
        "release": 0,
        "webhook": 1,
    }
    assert len(to_fetch) == 6


def test_basic_auth_is_sent_when_there_is_no_token() -> None:
    source = FakeSource()
    with _broker(source, username="ci", password="pw") as broker:
        assert broker.count_pacticipants() == 2
    assert source.requests[0].headers["authorization"].startswith("Basic ")


def test_a_link_to_another_origin_is_followed_on_the_source_host() -> None:
    """The token never leaves the host the user named, whatever a link says."""
    source = FakeSource()
    plan = Plan()
    with _broker(source) as broker:
        to_fetch = read_source(broker, plan, kinds={"pact"})
        key, record = plan.records["pact"][0]
        assert to_fetch[key].startswith("http://internal.broker:9292/")
        assert fetch_document(broker, record, to_fetch[key], plan) is None
    assert {request.url.host for request in source.requests} == {"broker.example.com"}
    assert {request.url.scheme for request in source.requests} == {"https"}
    assert record["content"]["consumer"] == {"name": "Web"} and "_links" not in record["content"]


def test_only_what_the_chosen_kinds_need_is_asked() -> None:
    source = FakeSource()
    plan = Plan()
    with _broker(source) as broker:
        read_source(broker, plan, kinds={"environment"})
    assert source.paths() == ["/environments"]
    assert [kind for kind in KINDS if plan.records[kind]] == ["environment"]


def test_a_document_the_source_no_longer_has_is_a_reason_not_an_error() -> None:
    docs = documents()
    del docs["/pacts/provider/API/consumer/Web/version/1"]
    source = FakeSource(docs)
    plan = Plan()
    with _broker(source) as broker:
        to_fetch = read_source(broker, plan, kinds={"pact"})
        key, record = plan.records["pact"][0]
        problem = fetch_document(broker, record, to_fetch[key], plan)
    assert problem is not None and "404" in problem


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_sign_in_names_the_host_and_never_the_token(status: int) -> None:
    source = FakeSource({"/pacticipants": status})
    with _broker(source) as broker, pytest.raises(SourceError) as caught:
        broker.count_pacticipants()
    assert caught.value.code == CODE_SOURCE_REFUSED and caught.value.http_status == status
    assert str(caught.value) == f"Could not sign in to broker.example.com ({status}). Check the token."
    assert TOKEN not in str(caught.value)


def test_a_refused_basic_sign_in_says_which_credential() -> None:
    source = FakeSource({"/pacticipants": 401})
    with _broker(source, username="ci", password="pw") as broker, pytest.raises(SourceError) as caught:
        broker.count_pacticipants()
    assert str(caught.value).endswith("Check the username and password.")


def test_a_host_that_is_not_a_broker_is_unreadable() -> None:
    source = FakeSource({"/pacticipants": 500})
    with _broker(source) as broker, pytest.raises(SourceError) as caught:
        broker.count_pacticipants()
    assert caught.value.code == CODE_SOURCE_UNREADABLE and "HTTP 500" in str(caught.value)


def test_a_token_that_may_not_list_secrets_does_not_fail_the_read() -> None:
    docs: Dict[str, Any] = documents()
    docs["/secrets"] = 403
    plan = Plan()
    with _broker(FakeSource(docs)) as broker:
        read_source(broker, plan, kinds={"webhook"})
    assert len(plan.records["webhook"]) == 1


def test_pactflow_secrets_are_listed_for_re_entry() -> None:
    docs: Dict[str, Any] = documents()
    docs["/secrets"] = {"_embedded": {"secrets": [{"name": "CI_TOKEN"}]}}
    plan = Plan()
    with _broker(FakeSource(docs)) as broker:
        read_source(broker, plan, kinds={"webhook"})
    assert [(finding.kind, finding.subject) for finding in plan.findings if finding.kind == "secret"] == [
        ("secret", "CI_TOKEN")
    ]


@pytest.mark.parametrize(
    "url",
    [
        "ftp://broker.example.com",
        "file:///etc/passwd",
        "https://user:pw@broker.example.com",
        "http://169.254.169.254/latest",
        "http://127.0.0.1:9292",
        "not a url",
    ],
)
def test_a_url_the_server_must_not_read_is_refused_before_any_request(url: str) -> None:
    with pytest.raises(SourceError) as caught:
        SourceBroker(url, token=TOKEN)
    assert caught.value.code == CODE_SOURCE_INVALID and TOKEN not in str(caught.value)


def test_an_answer_over_the_size_limit_is_refused_not_held_in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.pact_migration_source.MAX_DOCUMENT_BYTES", 64)
    source = FakeSource()
    with _broker(source) as broker, pytest.raises(SourceError) as caught:
        broker.count_pacticipants()
    assert caught.value.code == CODE_SOURCE_UNREADABLE and "was not read" in str(caught.value)


def test_an_answer_that_is_not_json_is_unreadable() -> None:
    source = FakeSource({"/pacticipants": ["not", "an", "object"]})
    with _broker(source) as broker, pytest.raises(SourceError) as caught:
        broker.count_pacticipants()
    assert caught.value.code == CODE_SOURCE_UNREADABLE and "not a JSON object" in str(caught.value)


def test_the_product_is_read_from_the_host() -> None:
    assert product_of("https://acme.pactflow.io") == "PactFlow"
    assert product_of("https://pactflow.io.evil.example") == "Pact Broker"
    assert product_of("https://broker.example.com/pact") == "Pact Broker"
