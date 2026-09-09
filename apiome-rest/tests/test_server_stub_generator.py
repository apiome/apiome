"""The server stub facade — SDK-2.5 (#4490).

Tests for :mod:`app.server_stub_generator`, the one entry point over both generators. The
per-target detail lives in :mod:`tests.test_fastapi_stub_generator` and
:mod:`tests.test_express_stub_generator`; what is checked here is what only the facade can
promise — that both projects come out of *one* plan, and so route the same operations, name the
same models and report the same skips.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Server,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.server_stub_generator import (
    EXPRESS_DIRECTORY,
    FASTAPI_DIRECTORY,
    SERVER_STUB_SCHEMA_VERSION,
    generate_server_stubs,
)


def _member(name: str, type_name: str, *, required: bool = False) -> CanonicalField:
    """One record member. ``required`` is the canonical ``nullable=False`` spelling."""
    return CanonicalField(
        key=f"X.{name}", name=name, type=TypeRef(name=type_name, nullable=not required)
    )


def _op(
    key: str,
    name: str,
    *,
    method: Optional[str] = "get",
    path: Optional[str] = "/widgets",
    parameters: Optional[List[Parameter]] = None,
    messages: Optional[List[Message]] = None,
    extras: Optional[Dict[str, Any]] = None,
) -> Operation:
    """One operation, HTTP-bound unless ``method``/``path`` are cleared."""
    return Operation(
        key=key,
        name=name,
        kind=OperationKind.REQUEST_RESPONSE,
        http_method=method,
        http_path=path,
        parameters=parameters or [],
        messages=messages or [],
        extras={"operationId": name, **(extras or {})},
    )


def _api(operations: Optional[List[Operation]] = None, types: Optional[List[Type]] = None) -> CanonicalApi:
    """A REST model with one group of operations."""
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        title="Widgets API",
        version="1.0.0",
        identity=ApiIdentity(name="widgets"),
        servers=[Server(url="https://api.example.dev/v2")],
        types=types or [],
        services=[Service(key="svc", name="widgets", operations=operations or [])],
    )


_DEFAULT_API = _api(
    types=[
        Type(
            key="Widget",
            name="Widget",
            kind=TypeKind.RECORD,
            fields=[_member("id", "i64", required=True), _member("name", "string")],
        )
    ],
    operations=[
        _op(
            "GET /widgets/{id}",
            "getWidget",
            path="/widgets/{id}",
            parameters=[
                Parameter(
                    key="p", name="id", location=ParameterLocation.PATH, type=TypeRef(name="i64"), required=True
                )
            ],
            messages=[
                Message(key="r", role=MessageRole.RESPONSE, status_code="200", payload=TypeRef(name="Widget"))
            ],
        ),
        _op("Query.things", "things", method=None, path=None),
    ],
)


def test_both_projects_are_returned_under_their_own_directories() -> None:
    bundle = generate_server_stubs(_DEFAULT_API)
    paths = set(bundle.file_map())
    assert f"{FASTAPI_DIRECTORY}/{bundle.fastapi.package_name}/app.py" in paths
    assert f"{EXPRESS_DIRECTORY}/src/app.ts" in paths
    assert all(
        path.startswith((f"{FASTAPI_DIRECTORY}/", f"{EXPRESS_DIRECTORY}/")) for path in paths
    )


def test_the_files_are_returned_in_path_order() -> None:
    bundle = generate_server_stubs(_DEFAULT_API)
    paths = [item.path for item in bundle.files]
    assert paths == sorted(paths)


def test_both_projects_route_the_same_operations() -> None:
    """One plan, so the two skeletons cannot disagree about what the contract contains."""
    bundle = generate_server_stubs(_DEFAULT_API)
    assert bundle.route_count == 1 == bundle.fastapi.route_count == bundle.express.route_count
    assert bundle.fastapi.routers == bundle.express.routers == ("widgets",)
    assert bundle.fastapi.handler_classes == bundle.express.handler_interfaces == ("WidgetsHandlers",)


def test_a_schema_is_named_the_same_in_both_languages() -> None:
    """"The Widget model" being called Widget in both stubs is the shared-plan payoff."""
    bundle = generate_server_stubs(_DEFAULT_API)
    assert bundle.fastapi.model_classes == bundle.express.model_types == ("Widget",)
    assert "class Widget(BaseModel):" in bundle.file_map()[
        f"{FASTAPI_DIRECTORY}/{bundle.fastapi.package_name}/models.py"
    ]
    assert "export interface Widget {" in bundle.file_map()[f"{EXPRESS_DIRECTORY}/src/models.ts"]


def test_an_operation_with_no_http_binding_is_skipped_once_for_both() -> None:
    bundle = generate_server_stubs(_DEFAULT_API)
    assert [item.operation_id for item in bundle.skipped] == ["things"]
    for readme in (f"{FASTAPI_DIRECTORY}/README.md", f"{EXPRESS_DIRECTORY}/README.md"):
        assert "Query.things" in bundle.file_map()[readme]


def test_the_cap_applies_to_both_projects_at_once() -> None:
    api = _api(operations=[_op(f"GET /w/{index}", f"op{index}", path=f"/w/{index}") for index in range(4)])
    bundle = generate_server_stubs(api, max_operations=2)
    assert bundle.route_count == 2
    assert [item.operation_id for item in bundle.skipped] == ["op2", "op3"]
    assert bundle.plan.truncated is True


def test_the_package_names_are_the_callers_to_choose() -> None:
    bundle = generate_server_stubs(
        _DEFAULT_API, python_package_name="acme_widgets_server", npm_package_name="@acme/widgets-server"
    )
    assert bundle.fastapi.package_name == "acme_widgets_server"
    assert bundle.express.package_name == "@acme/widgets-server"
    assert f"{FASTAPI_DIRECTORY}/acme_widgets_server/app.py" in bundle.file_map()


def test_a_licence_header_reaches_both_projects() -> None:
    bundle = generate_server_stubs(_DEFAULT_API, license_header="Copyright (c) 2026 Acme, Inc.")
    files = bundle.file_map()
    assert files[f"{EXPRESS_DIRECTORY}/src/app.ts"].startswith("// Copyright (c) 2026 Acme, Inc.")
    assert files[f"{FASTAPI_DIRECTORY}/{bundle.fastapi.package_name}/app.py"].startswith(
        "# Copyright (c) 2026 Acme, Inc."
    )


def test_generating_twice_produces_identical_bytes() -> None:
    first = generate_server_stubs(_DEFAULT_API, license_header="Copyright 2026")
    second = generate_server_stubs(_DEFAULT_API, license_header="Copyright 2026")
    assert first.file_map() == second.file_map()


def test_the_schema_version_is_addressable() -> None:
    assert SERVER_STUB_SCHEMA_VERSION == "sdk.server-stubs.v1"
