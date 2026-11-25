"""Unit tests for :mod:`app.pact_graphql` — PFX-3.7 (#6937).

A GraphQL operation recorded as an HTTP interaction is recognised by its document, in each shape
GraphQL-over-HTTP allows (JSON ``POST``, ``GET`` with query parameters, ``application/graphql``);
a ``query`` member that is not GraphQL is ordinary data, unless the path says GraphQL — then it is
reported as unreadable rather than guessed at.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from app.pact_graphql import GRAPHQL_MEDIA_TYPE, read_graphql_request

_QUERY = "query UserById($id: ID!) { user(id: $id) { id name } }"


def _read(
    body: Any,
    *,
    method: str = "POST",
    path: str = "/graphql",
    media_type: Optional[str] = "application/json",
    query: Optional[Dict[str, List[str]]] = None,
):
    return read_graphql_request(method, path, body, media_type, query or {})


def test_a_json_post_is_read_with_its_variables_and_name() -> None:
    operation, problem = _read({"query": _QUERY, "variables": {"id": "7"}, "operationName": "UserById"})
    assert problem is None and operation is not None
    assert (operation.operation_name, operation.operation_type, operation.field) == ("UserById", "query", "user")
    assert operation.variables == {"id": "7"} and operation.query == _QUERY


def test_a_mutation_is_typed_as_one() -> None:
    operation, _ = _read({"query": 'mutation { createUser(name: "Ada") { id } }'})
    assert operation is not None
    assert (operation.operation_type, operation.operation_name, operation.field) == ("mutation", "", "createUser")


def test_a_get_with_query_parameters_is_read_and_its_variables_parsed() -> None:
    operation, problem = _read(
        None,
        method="GET",
        media_type=None,
        query={"query": [_QUERY], "variables": ['{"id": "7"}'], "operationName": ["UserById"]},
    )
    assert problem is None and operation is not None and operation.variables == {"id": "7"}


def test_an_application_graphql_body_is_read() -> None:
    operation, _ = _read("{ me { id } }", media_type=GRAPHQL_MEDIA_TYPE)
    assert operation is not None and (operation.operation_type, operation.field) == ("query", "me")


def test_a_fragment_only_root_selection_has_no_field() -> None:
    operation, _ = _read({"query": "query Q { ...Root } fragment Root on Query { me { id } }"})
    assert operation is not None and operation.field == ""


def test_the_named_operation_of_several_is_chosen() -> None:
    document = "query A { a } mutation B { b }"
    operation, _ = _read({"query": document, "operationName": "B"})
    assert operation is not None and (operation.operation_type, operation.field) == ("mutation", "b")


@pytest.mark.parametrize(
    "body, method, path, media_type",
    [
        ({"query": "pets near me"}, "POST", "/search", "application/json"),
        ({"q": _QUERY}, "POST", "/graphql", "application/json"),
        ("{ me { id } }", "POST", "/graphql", "text/plain"),
        (None, "GET", "/graphql", None),
        ({"query": "fragment F on Query { me }"}, "POST", "/search", "application/json"),
        (["not", "an", "object"], "POST", "/graphql", "application/json"),
    ],
)
def test_a_request_that_is_not_graphql_is_left_alone(body: Any, method: str, path: str, media_type: Any) -> None:
    assert _read(body, method=method, path=path, media_type=media_type) == (None, None)


@pytest.mark.parametrize(
    "body, fragment",
    [
        ({"query": "pets near me"}, "not a GraphQL document"),
        ({"query": "fragment F on Query { me }"}, "defines no operation"),
        ({"query": "query A { a } query B { b }"}, "several operations"),
        ({"query": _QUERY, "operationName": "Nope"}, "names no operation"),
        ({"query": _QUERY, "variables": "{not json"}, "not JSON"),
        ({"query": _QUERY, "variables": [1, 2]}, "not an object"),
    ],
)
def test_an_unreadable_graphql_request_is_reported_with_the_reason(body: Dict[str, Any], fragment: str) -> None:
    operation, problem = _read(body, path="/api/graphql/")
    assert operation is None and problem is not None and fragment in problem


def test_a_subscription_is_read_as_one_for_the_compiler_to_leave_out() -> None:
    operation, _ = _read({"query": "subscription { onEvent { id } }"})
    assert operation is not None and operation.operation_type == "subscription"
