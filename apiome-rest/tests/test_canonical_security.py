"""Where a canonical model records authentication — SDK-2.4 (#4488).

:mod:`app.canonical_security` is the extraction of a rule three emitters were each about to spell
out: the canonical model has no first-class security field, importers write auth into ``extras``
in two shapes, and those two shapes mean different things. These tests pin the distinction, since
losing it would make a generated client assert a requirement no contract stated.
"""

from __future__ import annotations

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Operation,
    OperationKind,
    Service,
)
from app.canonical_security import (
    AUTH_SCHEME_HEADERS,
    declared_security_schemes,
    operation_security_schemes,
)


def _api(*, api_extras=None, op_extras=None) -> CanonicalApi:
    """A one-operation model with auth recorded at the chosen scope."""
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="widgets"),
        extras=api_extras or {},
        services=[
            Service(
                key="svc",
                name="svc",
                operations=[
                    Operation(
                        key="GET /widgets",
                        name="listWidgets",
                        kind=OperationKind.REQUEST_RESPONSE,
                        http_method="get",
                        http_path="/widgets",
                        extras=op_extras or {},
                    )
                ],
            )
        ],
    )


def _operation(api: CanonicalApi) -> Operation:
    return api.services[0].operations[0]


def test_an_operation_declared_scheme_is_scoped_to_the_operation() -> None:
    api = _api(op_extras={"security": ["bearer"]})
    assert operation_security_schemes(api, _operation(api)) == (["bearer"], "operation")


def test_a_model_inferred_scheme_is_scoped_to_the_api() -> None:
    """"Observed somewhere" is a weaker statement than "required here", and stays weaker."""
    api = _api(api_extras={"inferred_auth_schemes": ["apiKey"]})
    assert operation_security_schemes(api, _operation(api)) == (["apiKey"], "api")


def test_an_operations_own_declaration_wins_over_the_models_observation() -> None:
    api = _api(api_extras={"inferred_auth_schemes": ["apiKey"]}, op_extras={"security": ["bearer"]})
    assert operation_security_schemes(api, _operation(api)) == (["bearer"], "operation")


def test_record_shaped_entries_are_read_and_deduplicated_in_order() -> None:
    """A gateway import writes ``{"scheme": …}`` records; an OpenAPI one writes bare names."""
    api = _api(op_extras={"security": [{"scheme": "bearer"}, "apiKey", {"scheme": "bearer"}, 7]})
    assert operation_security_schemes(api, _operation(api)) == (["bearer", "apiKey"], "operation")


def test_nothing_declared_reads_as_an_empty_api_scoped_list() -> None:
    api = _api()
    assert operation_security_schemes(api, _operation(api)) == ([], "api")


def test_declared_schemes_merge_both_shapes_and_sort() -> None:
    """A different, weaker question: which schemes does this API mention at all."""
    api = _api(api_extras={"inferred_auth_schemes": ["oauth2"]}, op_extras={"security": ["bearer"]})
    assert declared_security_schemes(api) == ["bearer", "oauth2"]


def test_declared_schemes_read_an_inferred_map_by_its_keys() -> None:
    api = _api(api_extras={"inferred_auth_schemes": {"basic": {"seen": 3}}})
    assert declared_security_schemes(api) == ["basic"]


def test_every_header_carrying_scheme_names_a_header_and_a_value() -> None:
    for scheme, (name, value) in AUTH_SCHEME_HEADERS.items():
        assert name and value, scheme
