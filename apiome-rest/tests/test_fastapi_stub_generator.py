"""The FastAPI server stub generator — SDK-2.5 (#4490).

Pure-function tests for :mod:`app.fastapi_stub_generator`: what a generated project contains, how
each canonical type family is expressed in pydantic, how an operation becomes a validated route,
and the determinism the client kit rests on.

The last section is the real gate. It writes the generated project to disk, imports it, boots it
under ``TestClient`` and drives it — proving the four things the ticket asked for over a real
request/response cycle: the server boots, an unimplemented operation answers ``501``, a request
that violates the contract is rejected with a structured problem document *before* any handler
runs, and an implemented handler serves. FastAPI and pydantic are this service's own dependencies,
so that gate always runs; the ``mypy`` check that proves a wrong handler signature is a type error
runs only where a ``mypy`` is on ``PATH``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from typing import Any, Dict, List, Optional

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    EnumValue,
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
from app.fastapi_stub_generator import (
    DEFAULT_PACKAGE_NAME,
    FASTAPI_STUB_SCHEMA_VERSION,
    VALIDATION_STATUS,
    FastApiStubProject,
    fastapi_package_name,
    generate_fastapi_stub,
)
from app.server_stub_plan import build_server_stub_plan

# ===========================================================================
# Fixtures
# ===========================================================================


def _member(name: str, type_name: str, *, required: bool = False, item: Optional[str] = None,
            description: Optional[str] = None, constraints: Optional[Constraints] = None) -> CanonicalField:
    """One record member. ``required`` is the canonical ``nullable=False`` spelling."""
    ref = (
        TypeRef(name="list", item=TypeRef(name=item), nullable=not required)
        if item is not None
        else TypeRef(name=type_name, nullable=not required)
    )
    return CanonicalField(
        key=f"X.{name}", name=name, type=ref, description=description, constraints=constraints
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


def _api(
    *,
    types: Optional[List[Type]] = None,
    operations: Optional[List[Operation]] = None,
    services: Optional[List[Service]] = None,
    servers: Optional[List[Server]] = None,
    title: str = "Widgets API",
) -> CanonicalApi:
    """A REST model with the pieces a test cares about substituted in."""
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        title=title,
        version="1.0.0",
        description="A widget API.",
        identity=ApiIdentity(name="widgets"),
        servers=servers if servers is not None else [Server(url="https://api.example.dev/v2")],
        types=types or [],
        services=services
        if services is not None
        else [Service(key="svc", name="widgets", operations=operations or [])],
    )


def _generate(api: CanonicalApi, **kwargs: Any) -> FastApiStubProject:
    """Plan and generate in one step, the way the kit does."""
    return generate_fastapi_stub(build_server_stub_plan(api), **kwargs)


def _text(project: FastApiStubProject, relative: str) -> str:
    """Return one generated file's text, addressed inside the package."""
    return project.file_map()[f"{project.package_name}/{relative}"]


# ===========================================================================
# Packaging
# ===========================================================================


def test_the_package_name_is_derived_and_always_says_server() -> None:
    """A stub unpacked beside the client package of the same API must not shadow it."""
    assert fastapi_package_name("Pet Store") == "pet_store_server"
    assert fastapi_package_name(None, "widgets-server") == "widgets_server"
    assert fastapi_package_name(None, None) == DEFAULT_PACKAGE_NAME


def test_a_project_carries_the_files_a_consumer_needs_to_run_it() -> None:
    project = _generate(_api(operations=[_op("GET /widgets", "listWidgets")]))
    paths = set(project.file_map())
    assert "pyproject.toml" in paths
    assert "README.md" in paths
    for relative in ("__init__.py", "app.py", "main.py", "models.py", "errors.py", "handlers.py"):
        assert f"{project.package_name}/{relative}" in paths
    assert f"{project.package_name}/routers/widgets.py" in paths
    assert project.route_count == 1


def test_the_files_are_returned_in_path_order() -> None:
    project = _generate(_api(operations=[_op("GET /widgets", "listWidgets")]))
    paths = [item.path for item in project.files]
    assert paths == sorted(paths)


def test_every_generated_module_carries_the_do_not_edit_banner() -> None:
    project = _generate(_api(operations=[_op("GET /widgets", "listWidgets")]))
    for item in project.files:
        if item.path.endswith(".py"):
            assert "# Code generated by Apiome. DO NOT EDIT" in item.text


def test_a_licence_header_is_commented_onto_every_module_and_quoted_in_the_readme() -> None:
    project = _generate(
        _api(operations=[_op("GET /widgets", "listWidgets")]),
        license_header="Copyright (c) 2026 Acme */ Inc.",
    )
    assert _text(project, "app.py").startswith("# Copyright (c) 2026 Acme */ Inc.")
    assert "Copyright (c) 2026 Acme */ Inc." in project.file_map()["README.md"]


# ===========================================================================
# Models
# ===========================================================================


def test_a_record_becomes_a_pydantic_model_with_required_and_optional_members() -> None:
    project = _generate(
        _api(
            types=[
                Type(
                    key="Widget",
                    name="Widget",
                    kind=TypeKind.RECORD,
                    description="A widget.",
                    fields=[
                        _member("id", "i64", required=True),
                        _member("name", "string", description="Its name."),
                    ],
                )
            ]
        )
    )
    models = _text(project, "models.py")
    assert "class Widget(BaseModel):" in models
    assert '"""A widget."""' in models
    # A required member is declared with no default at all: `= ...` means the same to pydantic but
    # does not read as Python.
    assert "    id: int\n" in models
    assert 'name: Optional[str] = Field(default=None, description="Its name.")' in models


def test_a_member_whose_wire_name_is_not_a_python_identifier_is_aliased() -> None:
    project = _generate(
        _api(types=[Type(key="W", name="W", kind=TypeKind.RECORD, fields=[_member("from", "string")])])
    )
    assert 'from_: Optional[str] = Field(default=None, alias="from")' in _text(project, "models.py")
    # ``populate_by_name`` is what lets a handler construct the model with the name its own
    # signature reads.
    assert "populate_by_name=True" in _text(project, "models.py")


def test_a_string_enum_becomes_a_python_enum_over_its_wire_values() -> None:
    project = _generate(
        _api(
            types=[
                Type(
                    key="Status",
                    name="Status",
                    kind=TypeKind.ENUM,
                    enum_values=[
                        EnumValue(key="a", name="available", value="available"),
                        EnumValue(key="b", name="sold out", value="sold-out"),
                    ],
                )
            ]
        )
    )
    models = _text(project, "models.py")
    assert "class Status(str, Enum):" in models
    assert '    AVAILABLE = "available"' in models
    assert '    SOLD_OUT = "sold-out"' in models


def test_an_integer_enum_takes_an_int_base() -> None:
    project = _generate(
        _api(
            types=[
                Type(
                    key="Code",
                    name="Code",
                    kind=TypeKind.ENUM,
                    enum_values=[EnumValue(key="a", name="ok", value=1), EnumValue(key="b", name="bad", value=2)],
                )
            ]
        )
    )
    assert "class Code(int, Enum):" in _text(project, "models.py")


def test_a_heterogeneous_enum_degrades_to_any_rather_than_rejecting_its_members() -> None:
    project = _generate(
        _api(
            types=[
                Type(
                    key="Odd",
                    name="Odd",
                    kind=TypeKind.ENUM,
                    enum_values=[EnumValue(key="a", name="one", value="one"), EnumValue(key="b", name="two", value=2)],
                )
            ]
        )
    )
    assert "Odd = Any" in _text(project, "models.py")


def test_a_map_and_an_alias_become_type_aliases() -> None:
    project = _generate(
        _api(
            types=[
                Type(key="Widget", name="Widget", kind=TypeKind.RECORD, fields=[]),
                Type(key="Bag", name="Bag", kind=TypeKind.MAP, value_type=TypeRef(name="Widget")),
                Type(key="Widgets", name="Widgets", kind=TypeKind.ALIAS,
                     aliased=TypeRef(name="list", item=TypeRef(name="Widget"))),
            ]
        )
    )
    models = _text(project, "models.py")
    assert 'Bag = Dict[str, "Widget"]' in models
    assert 'Widgets = List["Widget"]' in models


def test_a_bare_reference_alias_is_ordered_after_what_it_names() -> None:
    """A module-level assignment is evaluated eagerly, unlike an annotation."""
    project = _generate(
        _api(
            types=[
                Type(key="Second", name="Second", kind=TypeKind.ALIAS, aliased=TypeRef(name="First")),
                Type(key="First", name="First", kind=TypeKind.ALIAS,
                     aliased=TypeRef(name="list", item=TypeRef(name="string"))),
            ]
        )
    )
    models = _text(project, "models.py")
    assert models.index("First = List[str]") < models.index("Second = First")


def test_every_model_is_rebuilt_so_a_recursive_contract_resolves() -> None:
    project = _generate(
        _api(
            types=[
                Type(
                    key="Node",
                    name="Node",
                    kind=TypeKind.RECORD,
                    fields=[_member("children", "", item="Node")],
                )
            ]
        )
    )
    models = _text(project, "models.py")
    assert "_model.model_rebuild(raise_errors=False)" in models
    assert "children: Optional[List[Node]]" in models


def test_a_constraint_is_written_in_pydantics_own_keywords() -> None:
    project = _generate(
        _api(
            types=[
                Type(
                    key="W",
                    name="W",
                    kind=TypeKind.RECORD,
                    fields=[
                        _member("count", "i32", constraints=Constraints(minimum=1, maximum=10)),
                        _member("code", "string", constraints=Constraints(min_length=2, pattern="^[a-z]+$")),
                    ],
                )
            ]
        )
    )
    models = _text(project, "models.py")
    # Integral bounds keep an integer spelling: `le=10.0` on an int field reads as a float bound.
    assert "ge=1, le=10" in models
    assert 'min_length=2, pattern="^[a-z]+$"' in models


# ===========================================================================
# Handlers
# ===========================================================================


def test_a_group_gets_a_typed_protocol_and_a_501_answering_base() -> None:
    project = _generate(_api(operations=[_op("GET /widgets", "listWidgets")]))
    handlers = _text(project, "handlers.py")
    assert "class WidgetsHandlers(Protocol):" in handlers
    assert "class NotImplementedWidgetsHandlers:" in handlers
    assert 'raise OperationNotImplemented("listWidgets", "GET", "/widgets")' in handlers
    assert project.handler_classes == ("WidgetsHandlers",)


def test_every_handler_argument_is_keyword_only() -> None:
    """A contract that later adds a parameter must not silently rebind an existing one."""
    project = _generate(
        _api(
            operations=[
                _op(
                    "GET /widgets/{id}",
                    "getWidget",
                    path="/widgets/{id}",
                    parameters=[
                        Parameter(key="q", name="limit", location=ParameterLocation.QUERY, type=TypeRef(name="i32"))
                    ],
                )
            ]
        )
    )
    assert "async def get_widget(self, *, id: str, limit: Optional[int] = None) -> None:" in _text(
        project, "handlers.py"
    )


def test_a_handler_returns_the_contracts_success_payload() -> None:
    project = _generate(
        _api(
            types=[Type(key="Widget", name="Widget", kind=TypeKind.RECORD, fields=[])],
            operations=[
                _op(
                    "GET /widgets",
                    "listWidgets",
                    messages=[
                        Message(
                            key="r",
                            role=MessageRole.RESPONSE,
                            status_code="200",
                            payload=TypeRef(name="list", item=TypeRef(name="Widget")),
                        )
                    ],
                )
            ],
        )
    )
    assert "-> List[Widget]:" in _text(project, "handlers.py")


def test_a_non_json_body_reaches_the_handler_as_bytes() -> None:
    project = _generate(
        _api(
            operations=[
                _op(
                    "POST /widgets",
                    "upload",
                    method="post",
                    messages=[
                        Message(
                            key="req",
                            role=MessageRole.REQUEST,
                            payload=TypeRef(name="bytes"),
                            content_types=["application/octet-stream"],
                            required=True,
                        )
                    ],
                )
            ]
        )
    )
    assert "body: bytes" in _text(project, "handlers.py")


def test_a_required_security_scheme_is_documented_not_enforced() -> None:
    """A stub that invented an auth check would assert a policy the contract did not state."""
    project = _generate(
        _api(operations=[_op("GET /widgets", "listWidgets", extras={"security": ["bearer"]})])
    )
    handlers = _text(project, "handlers.py")
    assert "requires authentication" in handlers
    assert "implementation's responsibility" in handlers


# ===========================================================================
# Routers
# ===========================================================================


def test_a_route_declares_every_parameter_with_its_location_class() -> None:
    project = _generate(
        _api(
            operations=[
                _op(
                    "GET /widgets/{id}",
                    "getWidget",
                    path="/widgets/{id}",
                    parameters=[
                        Parameter(key="p", name="id", location=ParameterLocation.PATH, type=TypeRef(name="i64"),
                                  required=True),
                        Parameter(key="q", name="limit", location=ParameterLocation.QUERY, type=TypeRef(name="i32")),
                        Parameter(key="h", name="X-Request-Id", location=ParameterLocation.HEADER,
                                  type=TypeRef(name="string")),
                        Parameter(key="c", name="session", location=ParameterLocation.COOKIE,
                                  type=TypeRef(name="string")),
                    ],
                )
            ]
        )
    )
    router = _text(project, "routers/widgets.py")
    assert "id: Annotated[int, Path()]" in router
    assert "limit: Annotated[Optional[int], Query()] = None" in router
    assert 'x_request_id: Annotated[Optional[str], Header(alias="X-Request-Id")] = None' in router
    assert "session: Annotated[Optional[str], Cookie()] = None" in router


def test_a_route_delegates_to_the_handler_and_nothing_else() -> None:
    project = _generate(_api(operations=[_op("GET /widgets", "listWidgets")]))
    router = _text(project, "routers/widgets.py")
    assert "await handlers.list_widgets()" in router
    assert "def build_router(handlers: WidgetsHandlers) -> APIRouter:" in router


def test_a_response_with_no_payload_sends_no_body() -> None:
    """A 204 that carries a body is not a 204."""
    project = _generate(
        _api(operations=[_op("DELETE /widgets/{id}", "deleteWidget", method="delete", path="/widgets/{id}")])
    )
    router = _text(project, "routers/widgets.py")
    assert "response_class=Response," in router
    assert "status_code=204," in router
    assert "return Response(status_code=204)" in router


def test_declared_error_responses_reach_the_generated_openapi() -> None:
    project = _generate(
        _api(
            operations=[
                _op(
                    "GET /widgets",
                    "listWidgets",
                    messages=[Message(key="e", role=MessageRole.ERROR, status_code="404", description="No widget")],
                )
            ]
        )
    )
    assert 'responses={404: {"description": "No widget"}},' in _text(project, "routers/widgets.py")


def test_the_app_mounts_every_router_under_the_contracts_base_path() -> None:
    project = _generate(_api(operations=[_op("GET /widgets", "listWidgets")]))
    app = _text(project, "app.py")
    assert 'BASE_PATH = "/v2"' in app
    assert "prefix=BASE_PATH" in app
    assert "widgets or NotImplementedWidgetsHandlers()" in app


def test_the_app_installs_both_problem_handlers() -> None:
    project = _generate(_api(operations=[_op("GET /widgets", "listWidgets")]))
    app = _text(project, "app.py")
    assert "add_exception_handler(RequestValidationError, validation_exception_handler)" in app
    assert "add_exception_handler(OperationNotImplemented, not_implemented_exception_handler)" in app
    assert f"VALIDATION_STATUS = {VALIDATION_STATUS}" in _text(project, "errors.py")


# ===========================================================================
# Degradation and determinism
# ===========================================================================


def test_a_contract_with_no_http_operation_still_produces_a_runnable_project() -> None:
    project = _generate(_api(operations=[_op("Query.things", "things", method=None, path=None)]))
    assert project.route_count == 0
    assert "no router is mounted" in _text(project, "app.py")
    assert "nothing to implement" in project.file_map()["README.md"]


def test_the_readme_names_the_operations_that_got_no_route() -> None:
    project = _generate(
        _api(operations=[_op("GET /widgets", "listWidgets"), _op("Query.things", "things", method=None, path=None)])
    )
    readme = project.file_map()["README.md"]
    assert "## Not generated" in readme
    assert "Query.things" in readme
    assert FASTAPI_STUB_SCHEMA_VERSION in readme


def test_generating_twice_produces_identical_bytes() -> None:
    api = _api(
        types=[Type(key="Widget", name="Widget", kind=TypeKind.RECORD, fields=[_member("id", "i64", required=True)])],
        operations=[_op("GET /widgets/{id}", "getWidget", path="/widgets/{id}")],
    )
    first = _generate(api, license_header="Copyright 2026")
    second = _generate(api, license_header="Copyright 2026")
    assert first.file_map() == second.file_map()


# ===========================================================================
# The gate: the generated project boots, validates and answers
# ===========================================================================


def _gate_api() -> CanonicalApi:
    """A Petstore-shaped contract exercising every route feature at once."""
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        title="Petstore",
        version="1.0.0",
        description="A pet store.",
        identity=ApiIdentity(name="petstore"),
        servers=[Server(url="https://api.example.dev/v2")],
        types=[
            Type(
                key="Status",
                name="Status",
                kind=TypeKind.ENUM,
                enum_values=[
                    EnumValue(key="a", name="available", value="available"),
                    EnumValue(key="b", name="sold", value="sold"),
                ],
            ),
            Type(
                key="Pet",
                name="Pet",
                kind=TypeKind.RECORD,
                description="A pet in the store.",
                fields=[
                    _member("id", "i64", required=True),
                    _member("name", "string", required=True, description="The pet's name."),
                    _member("status", "Status"),
                    _member("tags", "", item="string"),
                    _member("from", "string"),
                ],
            ),
        ],
        services=[Service(key="pets", name="pets", operations=[
            _op(
                "GET /pets",
                "listPets",
                path="/pets",
                parameters=[
                    Parameter(
                        key="q",
                        name="limit",
                        location=ParameterLocation.QUERY,
                        type=TypeRef(name="i32"),
                        constraints=Constraints(minimum=1, maximum=100),
                        description="How many to return.",
                    )
                ],
                messages=[
                    Message(
                        key="r",
                        role=MessageRole.RESPONSE,
                        status_code="200",
                        payload=TypeRef(name="list", item=TypeRef(name="Pet")),
                    )
                ],
                extras={"summary": "List pets"},
            ),
            _op(
                "POST /pets",
                "createPet",
                method="post",
                path="/pets",
                messages=[
                    Message(
                        key="req",
                        role=MessageRole.REQUEST,
                        payload=TypeRef(name="Pet"),
                        content_types=["application/json"],
                        required=True,
                    ),
                    Message(key="res", role=MessageRole.RESPONSE, status_code="201", payload=TypeRef(name="Pet")),
                ],
            ),
            _op(
                "GET /pets/{petId}",
                "getPet",
                path="/pets/{petId}",
                parameters=[
                    Parameter(key="p", name="petId", location=ParameterLocation.PATH, type=TypeRef(name="i64"),
                              required=True)
                ],
                messages=[Message(key="r", role=MessageRole.RESPONSE, status_code="200", payload=TypeRef(name="Pet"))],
            ),
            _op("DELETE /pets/{petId}", "deletePet", method="delete", path="/pets/{petId}",
                parameters=[Parameter(key="p", name="petId", location=ParameterLocation.PATH,
                                      type=TypeRef(name="i64"), required=True)]),
        ])],
    )


@pytest.fixture()
def gate_project(tmp_path):
    """Write the generated Petstore project to disk and put it on ``sys.path``.

    The import is undone afterwards: leaving a generated ``petstore_server`` in
    :data:`sys.modules` would leak into any later test that generated one of its own.
    """
    project = _generate(_gate_api(), license_header="Copyright (c) 2026 Acme */ Inc.")
    for item in project.files:
        target = tmp_path / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.text)
    sys.path.insert(0, str(tmp_path))
    try:
        yield project, tmp_path
    finally:
        sys.path.remove(str(tmp_path))
        for name in [key for key in sys.modules if key.split(".")[0] == project.package_name]:
            del sys.modules[name]


def test_the_generated_project_boots_validates_and_answers(gate_project) -> None:
    """The gate: everything the ticket asked for, over a real request/response cycle.

    Boot proves the modules import and the models build; the 501 proves an unimplemented
    operation is still routed; the two rejections prove the generated signatures validate the
    request before any handler runs; the last two prove an implementation is actually served.
    """
    from fastapi.testclient import TestClient

    project, _root = gate_project
    package = __import__(project.package_name)
    models = __import__(f"{project.package_name}.models", fromlist=["Pet"])

    client = TestClient(package.create_app())

    unimplemented = client.get("/v2/pets")
    assert unimplemented.status_code == 501
    assert unimplemented.headers["content-type"].startswith("application/problem+json")
    assert unimplemented.json()["operationId"] == "listPets"

    bad_query = client.get("/v2/pets", params={"limit": "not-a-number"})
    assert bad_query.status_code == VALIDATION_STATUS
    assert bad_query.json()["errors"][0]["location"] == "query"
    assert bad_query.json()["errors"][0]["field"] == "limit"

    out_of_range = client.get("/v2/pets", params={"limit": 500})
    assert out_of_range.status_code == VALIDATION_STATUS

    missing_field = client.post("/v2/pets", json={"name": "Rex"})
    assert missing_field.status_code == VALIDATION_STATUS
    assert missing_field.json()["errors"][0] == {
        "location": "body",
        "field": "id",
        "message": "Field required",
        "type": "missing",
    }

    bad_enum = client.post("/v2/pets", json={"id": 1, "name": "Rex", "status": "nope"})
    assert bad_enum.status_code == VALIDATION_STATUS

    class Service(package.NotImplementedPetsHandlers):
        """One implemented operation, so the served path is exercised too."""

        async def get_pet(self, *, pet_id: int):
            return models.Pet(id=pet_id, name="Rex", from_="shelter")

        async def delete_pet(self, *, pet_id: int) -> None:
            return None

    served = TestClient(package.create_app(pets=Service()))
    found = served.get("/v2/pets/7")
    assert found.status_code == 200
    # The alias is what puts the member back on the wire under the name the contract published.
    assert found.json() == {"id": 7, "name": "Rex", "status": None, "tags": None, "from": "shelter"}

    deleted = served.delete("/v2/pets/7")
    assert deleted.status_code == 204
    assert deleted.content == b""

    bad_path = served.get("/v2/pets/not-an-int")
    assert bad_path.status_code == VALIDATION_STATUS
    assert bad_path.json()["errors"][0]["location"] == "path"


def test_the_generated_openapi_republishes_the_contracts_own_paths(gate_project) -> None:
    """A stub that served different paths than the contract would not be a stub of it."""
    from fastapi.testclient import TestClient

    project, _root = gate_project
    package = __import__(project.package_name)
    document = TestClient(package.create_app()).get("/openapi.json").json()
    assert sorted(document["paths"]) == ["/v2/pets", "/v2/pets/{petId}"]
    assert document["paths"]["/v2/pets"]["get"]["operationId"] == "listPets"
    assert document["info"]["title"] == "Petstore"


_WRONG_SIGNATURE = '''
from petstore_server import NotImplementedPetsHandlers


class Broken(NotImplementedPetsHandlers):
    async def get_pet(self, *, wrong_name: str) -> str:
        return wrong_name
'''


@pytest.mark.skipif(shutil.which("mypy") is None, reason="no mypy on PATH")
def test_a_handler_implemented_with_the_wrong_signature_is_a_type_error(gate_project) -> None:
    """The typed-interface promise, checked by the tool a consumer would check it with."""
    _project, root = gate_project
    (root / "wrong_impl.py").write_text(textwrap.dedent(_WRONG_SIGNATURE).lstrip())
    result = subprocess.run(
        [shutil.which("mypy") or "mypy", "--ignore-missing-imports", "wrong_impl.py"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, result.stdout
    assert "get_pet" in result.stdout
