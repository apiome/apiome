"""Declared versus observed — RDG-1.8 (#5765).

``app.consumer_runtime_edges`` is pure, so the acceptance criteria that are about the report itself
are proven here on a fixed ``usage_daily`` fixture:

* the report is deterministic — the same rows in any order give byte-identical output;
* two bindings of one consumer (a key and a user agent) add up to that one consumer;
* an ``undeclared`` consumer with traffic shows ``used_undeclared`` operations;
* unattributed calls appear under ``anonymous`` and nowhere else.
"""

from __future__ import annotations

from datetime import date
from typing import List

from app.consumer_contract import ConsumerContractOperation, ConsumerContractSurface
from app.consumer_runtime_edges import (
    CONTRACT_DECLARED,
    CONTRACT_NONE,
    CONTRACT_UNDECLARED,
    RuntimeConsumer,
    UsageRow,
    build_runtime,
    build_runtime_report,
    parse_operation_key,
)

SINCE = date(2026, 9, 19)
UNTIL = date(2026, 10, 18)
BILLING = "11111111-1111-4111-8111-111111111111"
SEARCH = "22222222-2222-4222-8222-222222222222"

LIST_PETS = "/paths/~1pets/get"
GET_PET = "/paths/~1pets~1{petId}/get"
CREATE_PET = "/paths/~1pets/post"
ORDERS = "/paths/~1users~1{userId}~1orders/get"


def _surface(*pointers: str) -> ConsumerContractSurface:
    operations = []
    for pointer in pointers:
        method, path = parse_operation_key(pointer)
        operations.append(ConsumerContractOperation(method=method, path=path, pointer=pointer))
    return ConsumerContractSurface(operations=operations)


#: The fixture: billing calls through two bindings (rows already joined to its consumer id), search
#: has no contract, and some calls are unattributed.
ROWS: List[UsageRow] = [
    UsageRow(BILLING, LIST_PETS, calls=600, errors=6, last_seen=date(2026, 10, 17)),
    UsageRow(BILLING, LIST_PETS, calls=400, errors=0, last_seen=date(2026, 10, 18)),
    UsageRow(BILLING, ORDERS, calls=25, errors=5, last_seen=date(2026, 10, 2)),
    UsageRow(SEARCH, GET_PET, calls=90, errors=0, last_seen=date(2026, 10, 10)),
    UsageRow(None, CREATE_PET, calls=12, errors=1, last_seen=date(2026, 10, 11)),
    UsageRow(None, LIST_PETS, calls=3, errors=0, last_seen=date(2026, 10, 1)),
]

CONSUMERS = [
    RuntimeConsumer(BILLING, "billing-service", "Billing", _surface(LIST_PETS, GET_PET)),
    RuntimeConsumer(SEARCH, "search", "Search", None),
]


def test_parse_operation_key_unescapes_the_template() -> None:
    assert parse_operation_key(ORDERS) == ("get", "/users/{userId}/orders")
    assert parse_operation_key("/paths/~1a~0b/put") == ("put", "/a~b")
    assert parse_operation_key("not-a-pointer") == ("", "not-a-pointer")


def test_a_declared_consumer_gets_all_three_sides() -> None:
    report = build_runtime(CONSUMERS[0], ROWS, since=SINCE, until=UNTIL)
    assert report.contract_state == CONTRACT_DECLARED
    assert [op.operation_key for op in report.declared_and_used] == [LIST_PETS]
    assert [op.operation_key for op in report.declared_unused] == [GET_PET]
    assert [op.operation_key for op in report.used_undeclared] == [ORDERS]
    assert report.declared_unused[0].calls == 0 and report.declared_unused[0].last_seen_day is None
    undeclared = report.used_undeclared[0]
    assert (undeclared.method, undeclared.path, undeclared.calls, undeclared.errors) == (
        "get",
        "/users/{userId}/orders",
        25,
        5,
    )


def test_two_bindings_of_one_consumer_add_up_to_one_consumer() -> None:
    report = build_runtime(CONSUMERS[0], ROWS, since=SINCE, until=UNTIL)
    used = report.declared_and_used[0]
    assert used.calls == 1000 and used.errors == 6
    assert used.last_seen_day == "2026-10-18"
    assert report.summary.calls == 1025
    assert report.summary.last_seen_day == "2026-10-18"


def test_an_undeclared_consumer_with_traffic_shows_used_undeclared() -> None:
    report = build_runtime(CONSUMERS[1], ROWS, since=SINCE, until=UNTIL)
    assert report.contract_state == CONTRACT_UNDECLARED
    assert report.declared_and_used == [] and report.declared_unused == []
    assert [op.operation_key for op in report.used_undeclared] == [GET_PET]
    assert report.summary.used_undeclared == 1


def test_unattributed_calls_are_anonymous_and_only_anonymous() -> None:
    reports = build_runtime_report(CONSUMERS, ROWS, since=SINCE, until=UNTIL)
    assert [r.slug for r in reports] == ["billing-service", "search", "anonymous"]
    anonymous = reports[-1]
    assert anonymous.consumer_id is None and anonymous.contract_state == CONTRACT_NONE
    assert [op.operation_key for op in anonymous.used_undeclared] == [LIST_PETS, CREATE_PET]
    assert anonymous.summary.calls == 15
    # The anonymous LIST_PETS calls are not billing's.
    assert reports[0].declared_and_used[0].calls == 1000


def test_anonymous_is_listed_even_with_no_unattributed_traffic() -> None:
    reports = build_runtime_report(CONSUMERS, [r for r in ROWS if r.consumer_id], since=SINCE, until=UNTIL)
    assert reports[-1].slug == "anonymous" and reports[-1].summary.calls == 0


def test_a_consumer_with_no_traffic_has_every_declaration_unused() -> None:
    report = build_runtime(CONSUMERS[0], [], since=SINCE, until=UNTIL)
    assert report.summary.declared_unused == 2 and report.summary.calls == 0
    assert report.summary.last_seen_day is None


def test_the_report_is_deterministic_for_a_fixed_fixture() -> None:
    first = [r.model_dump_json() for r in build_runtime_report(CONSUMERS, ROWS, since=SINCE, until=UNTIL)]
    shuffled = list(reversed(ROWS))
    second = [r.model_dump_json() for r in build_runtime_report(CONSUMERS, shuffled, since=SINCE, until=UNTIL)]
    assert first == second
    report = build_runtime(CONSUMERS[0], ROWS, since=SINCE, until=UNTIL)
    assert (report.since_day, report.until_day) == ("2026-09-19", "2026-10-18")


def test_lists_are_sorted_by_path_then_method() -> None:
    rows = [
        UsageRow(SEARCH, "/paths/~1b/get", 1, 0, UNTIL),
        UsageRow(SEARCH, "/paths/~1a/post", 1, 0, UNTIL),
        UsageRow(SEARCH, "/paths/~1a/get", 1, 0, UNTIL),
    ]
    report = build_runtime(CONSUMERS[1], rows, since=SINCE, until=UNTIL)
    assert [(op.path, op.method) for op in report.used_undeclared] == [("/a", "get"), ("/a", "post"), ("/b", "get")]


def test_zero_call_rows_are_ignored() -> None:
    report = build_runtime(CONSUMERS[1], [UsageRow(SEARCH, GET_PET, 0, 0, UNTIL)], since=SINCE, until=UNTIL)
    assert report.used_undeclared == []
