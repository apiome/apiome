"""The Express/TypeScript server stub generator — SDK-2.5 (#4490).

Pure-function tests for :mod:`app.express_stub_generator`: what a generated project contains, how
each canonical type family is expressed in TypeScript, how an operation becomes a validated route,
and the determinism the client kit rests on.

The last section is the gate. Where a TypeScript compiler is reachable it type-checks the
project's **dependency-free core** — ``models.ts``, ``schemas.ts``, ``validation.ts``,
``runtime.ts`` and ``handlers.ts``, which import nothing outside the project — under ``strict``,
proves that a handler implemented with the wrong signature is a compile error, and then (where
``node`` is also present) compiles the validator to JavaScript and *runs* it against a fake
request, proving that a contract-violating request is rejected with a structured problem document
and a valid one is not. The route, app and server files are excluded from that check on purpose:
they are the only three that import Express, and requiring ``@types/express`` would make this
repository's test suite depend on an npm install.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
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
from app.express_stub_generator import (
    DEFAULT_PACKAGE_NAME,
    EXPRESS_STUB_SCHEMA_VERSION,
    VALIDATION_STATUS,
    ExpressStubProject,
    express_package_name,
    generate_express_stub,
)
from app.server_stub_plan import build_server_stub_plan

#: The generated files that import nothing outside the project, and so can be type-checked and run
#: without installing Express.
CORE_FILES = (
    "src/runtime.ts",
    "src/validation.ts",
    "src/models.ts",
    "src/schemas.ts",
    "src/handlers.ts",
)


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


def _generate(api: CanonicalApi, **kwargs: Any) -> ExpressStubProject:
    """Plan and generate in one step, the way the kit does."""
    return generate_express_stub(build_server_stub_plan(api), **kwargs)


# ===========================================================================
# Packaging
# ===========================================================================


def test_the_npm_name_is_derived_and_always_says_server() -> None:
    """A tenant's configured npm name is their *client* package; a server may not share it."""
    assert express_package_name("Pet Store") == "pet-store-server"
    assert express_package_name("@acme/widgets") == "@acme/widgets-server"
    assert express_package_name("widgets-server") == "widgets-server"
    assert express_package_name(None, None) == DEFAULT_PACKAGE_NAME


def test_a_project_carries_the_files_a_consumer_needs_to_run_it() -> None:
    project = _generate(_api(operations=[_op("GET /widgets", "listWidgets")]))
    paths = set(project.file_map())
    assert {"package.json", "tsconfig.json", "README.md", *CORE_FILES} <= paths
    assert {"src/app.ts", "src/server.ts", "src/routes/widgets.ts"} <= paths
    assert project.route_count == 1


def test_the_package_declares_express_and_a_strict_tsconfig() -> None:
    project = _generate(_api(operations=[_op("GET /widgets", "listWidgets")]))
    package = json.loads(project.file_map()["package.json"])
    assert package["dependencies"]["express"].startswith("^5")
    assert package["scripts"]["typecheck"] == "tsc --noEmit"
    tsconfig = json.loads(project.file_map()["tsconfig.json"])
    assert tsconfig["compilerOptions"]["strict"] is True
    assert tsconfig["compilerOptions"]["noImplicitOverride"] is True


def test_only_the_routing_layer_imports_express() -> None:
    """The dependency-free core is what lets the contract be checked without a web framework."""
    project = _generate(_api(operations=[_op("GET /widgets", "listWidgets")]))
    importers = {
        item.path for item in project.files if "from 'express'" in item.text
    }
    assert importers == {"src/app.ts", "src/routes/widgets.ts"}
    for path in CORE_FILES:
        assert "express" not in project.file_map()[path]


def test_a_licence_header_is_commented_onto_every_module_and_quoted_in_the_readme() -> None:
    project = _generate(
        _api(operations=[_op("GET /widgets", "listWidgets")]),
        license_header="Copyright (c) 2026 Acme */ Inc.",
    )
    assert project.file_map()["src/app.ts"].startswith("// Copyright (c) 2026 Acme */ Inc.")
    assert "Copyright (c) 2026 Acme */ Inc." in project.file_map()["README.md"]


def test_a_description_containing_a_comment_terminator_cannot_escape_its_block() -> None:
    """A `*/` inside a doc comment would turn the rest of the file into syntax errors."""
    project = _generate(
        _api(
            types=[
                Type(
                    key="W",
                    name="W",
                    kind=TypeKind.RECORD,
                    description="Ends a block */ and keeps going.",
                    fields=[],
                )
            ]
        )
    )
    models = project.file_map()["src/models.ts"]
    assert "Ends a block" in models
    assert models.count("*/") == models.count("/**")


# ===========================================================================
# Models
# ===========================================================================


def test_a_record_becomes_an_interface_with_optional_members_marked() -> None:
    project = _generate(
        _api(
            types=[
                Type(
                    key="Widget",
                    name="Widget",
                    kind=TypeKind.RECORD,
                    fields=[_member("id", "i64", required=True), _member("name", "string")],
                )
            ]
        )
    )
    models = project.file_map()["src/models.ts"]
    assert "export interface Widget {" in models
    assert "  id: number;" in models
    assert "  name?: string;" in models


def test_a_member_keeps_its_wire_name_and_is_quoted_when_it_has_to_be() -> None:
    """Renaming a property would make the stub's models disagree with the JSON it accepts."""
    project = _generate(
        _api(types=[Type(key="W", name="W", kind=TypeKind.RECORD, fields=[_member("x-trace-id", "string")])])
    )
    assert "  'x-trace-id'?: string;" in project.file_map()["src/models.ts"]


def test_an_enum_becomes_a_literal_union_and_a_values_constant() -> None:
    project = _generate(
        _api(
            types=[
                Type(
                    key="Status",
                    name="Status",
                    kind=TypeKind.ENUM,
                    enum_values=[
                        EnumValue(key="a", name="available", value="available"),
                        EnumValue(key="b", name="sold", value="sold"),
                    ],
                )
            ]
        )
    )
    models = project.file_map()["src/models.ts"]
    assert "export type Status = 'available' | 'sold';" in models
    assert "export const StatusValues = ['available', 'sold'] as const;" in models


def test_a_list_of_a_union_is_parenthesized() -> None:
    """`A | B[]` is a union with an array in it, not an array of the union."""
    project = _generate(
        _api(
            types=[
                Type(key="Alpha", name="Alpha", kind=TypeKind.RECORD, fields=[]),
                Type(key="Beta", name="Beta", kind=TypeKind.RECORD, fields=[]),
                Type(key="Either", name="Either", kind=TypeKind.UNION, union_members=["Alpha", "Beta"]),
                Type(key="Many", name="Many", kind=TypeKind.ALIAS,
                     aliased=TypeRef(name="list", item=TypeRef(name="Either"))),
                Type(key="Holder", name="Holder", kind=TypeKind.RECORD,
                     fields=[_member("items", "", item="Either")]),
            ]
        )
    )
    models = project.file_map()["src/models.ts"]
    assert "export type Either = Alpha | Beta;" in models
    assert "  items?: Either[];" in models
    assert "export type Many = Either[];" in models


def test_a_map_becomes_a_record_over_its_value_type() -> None:
    project = _generate(
        _api(
            types=[
                Type(key="Widget", name="Widget", kind=TypeKind.RECORD, fields=[]),
                Type(key="Bag", name="Bag", kind=TypeKind.MAP, value_type=TypeRef(name="Widget")),
            ]
        )
    )
    assert "export type Bag = Record<string, Widget>;" in project.file_map()["src/models.ts"]


# ===========================================================================
# Schemas
# ===========================================================================


def test_the_registry_keeps_references_rather_than_inlining_them() -> None:
    """Inlining a self-referential type would not terminate."""
    project = _generate(
        _api(types=[Type(key="Node", name="Node", kind=TypeKind.RECORD, fields=[_member("child", "Node")])])
    )
    schemas = project.file_map()["src/schemas.ts"]
    assert "kind: 'ref'" in schemas
    assert "ref: 'Node'" in schemas


def test_an_operation_descriptor_names_every_parameter_and_where_it_travels() -> None:
    project = _generate(
        _api(
            operations=[
                _op(
                    "GET /widgets/{id}",
                    "getWidget",
                    path="/widgets/{id}",
                    parameters=[
                        Parameter(key="p", name="id", location=ParameterLocation.PATH,
                                  type=TypeRef(name="i64"), required=True),
                        Parameter(key="h", name="X-Request-Id", location=ParameterLocation.HEADER,
                                  type=TypeRef(name="string")),
                    ],
                )
            ]
        )
    )
    schemas = project.file_map()["src/schemas.ts"]
    assert "in: 'path'" in schemas
    assert "in: 'header'" in schemas
    assert "target: 'xRequestId'" in schemas


def test_constraints_reach_the_descriptor_in_the_validators_own_vocabulary() -> None:
    project = _generate(
        _api(
            operations=[
                _op(
                    "GET /widgets",
                    "listWidgets",
                    parameters=[
                        Parameter(key="q", name="limit", location=ParameterLocation.QUERY,
                                  type=TypeRef(name="i32"), constraints=Constraints(minimum=1, maximum=100))
                    ],
                )
            ]
        )
    )
    schemas = project.file_map()["src/schemas.ts"]
    assert "minimum: 1," in schemas
    assert "maximum: 100," in schemas


def test_a_non_json_body_is_marked_for_pass_through() -> None:
    project = _generate(
        _api(
            operations=[
                _op(
                    "POST /widgets",
                    "upload",
                    method="post",
                    messages=[
                        Message(key="req", role=MessageRole.REQUEST, payload=TypeRef(name="bytes"),
                                content_types=["application/octet-stream"], required=True)
                    ],
                )
            ]
        )
    )
    assert "validate: false," in project.file_map()["src/schemas.ts"]
    assert "  body: Uint8Array;" in project.file_map()["src/handlers.ts"]


# ===========================================================================
# Handlers and routes
# ===========================================================================


def test_a_group_gets_a_typed_interface_and_a_501_answering_base() -> None:
    project = _generate(_api(operations=[_op("GET /widgets", "listWidgets")]))
    handlers = project.file_map()["src/handlers.ts"]
    assert "export interface WidgetsHandlers {" in handlers
    assert "export class NotImplementedWidgetsHandlers implements WidgetsHandlers {" in handlers
    assert "throw new NotImplementedError('listWidgets', 'GET', '/widgets');" in handlers
    assert project.handler_interfaces == ("WidgetsHandlers",)


def test_an_operation_with_no_input_gets_a_request_type_that_permits_none() -> None:
    project = _generate(_api(operations=[_op("GET /widgets", "listWidgets")]))
    assert "export type ListWidgetsRequest = Record<string, never>;" in project.file_map()["src/handlers.ts"]


def test_a_route_validates_before_it_delegates() -> None:
    project = _generate(_api(operations=[_op("GET /widgets", "listWidgets")]))
    route = project.file_map()["src/routes/widgets.ts"]
    validate_at = route.index("validateRequest(operations['listWidgets'])")
    delegate_at = route.index("handlers.listWidgets(")
    assert validate_at < delegate_at
    assert "takeValidated<ListWidgetsRequest>(req)" in route


def test_a_path_template_is_registered_in_expresss_own_spelling() -> None:
    project = _generate(_api(operations=[_op("GET /widgets/{id}", "getWidget", path="/widgets/{id}")]))
    assert "router.get(\n    '/widgets/:id'," in project.file_map()["src/routes/widgets.ts"]


def test_a_response_with_no_payload_sends_no_body() -> None:
    project = _generate(
        _api(operations=[_op("DELETE /widgets/{id}", "deleteWidget", method="delete", path="/widgets/{id}")])
    )
    route = project.file_map()["src/routes/widgets.ts"]
    assert "res.status(204).end();" in route
    assert "const result" not in route


def test_the_app_mounts_every_router_under_the_contracts_base_path() -> None:
    project = _generate(_api(operations=[_op("GET /widgets", "listWidgets")]))
    app = project.file_map()["src/app.ts"]
    assert "export const BASE_PATH = '/v2';" in app
    assert "app.use(BASE_PATH, widgetsRouter(handlers.widgets ?? new NotImplementedWidgetsHandlers()));" in app
    assert "app.use(errorMiddleware);" in app


# ===========================================================================
# Degradation and determinism
# ===========================================================================


def test_a_contract_with_no_http_operation_still_produces_a_compilable_project() -> None:
    project = _generate(_api(operations=[_op("Query.things", "things", method=None, path=None)]))
    assert project.route_count == 0
    assert "no router is mounted" in project.file_map()["src/app.ts"]
    assert "export {};" in project.file_map()["src/handlers.ts"]


def test_the_readme_names_the_operations_that_got_no_route() -> None:
    project = _generate(
        _api(operations=[_op("GET /widgets", "listWidgets"), _op("Query.things", "things", method=None, path=None)])
    )
    readme = project.file_map()["README.md"]
    assert "## Not generated" in readme
    assert "Query.things" in readme
    assert EXPRESS_STUB_SCHEMA_VERSION in readme


def test_generating_twice_produces_identical_bytes() -> None:
    api = _api(
        types=[Type(key="Widget", name="Widget", kind=TypeKind.RECORD, fields=[_member("id", "i64", required=True)])],
        operations=[_op("GET /widgets/{id}", "getWidget", path="/widgets/{id}")],
    )
    assert _generate(api, license_header="c").file_map() == _generate(api, license_header="c").file_map()


# ===========================================================================
# The gate: the generated core type-checks, and the validator it holds runs
# ===========================================================================


def _typescript_compiler() -> Optional[str]:
    """Return a ``tsc`` entry point, or ``None`` when this machine has no TypeScript.

    Looked for on ``PATH`` first, then in a ``node_modules`` above this file — which is where a
    checkout of this monorepo keeps it. ``npx`` is deliberately not used: it would download a
    compiler on a machine that has none, and a test that reaches the network is a test that fails
    for reasons unrelated to the generator.
    """
    binary = shutil.which("tsc")
    if binary:
        return binary
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "node_modules" / "typescript" / "bin" / "tsc"
        if candidate.exists():
            return str(candidate)
    return None


def _run_tsc(root: Path, *arguments: str) -> subprocess.CompletedProcess:
    """Run the located compiler over ``arguments`` inside ``root``."""
    compiler = _typescript_compiler()
    assert compiler is not None
    command = [compiler] if os.access(compiler, os.X_OK) and not compiler.endswith("bin/tsc") else [
        shutil.which("node") or "node",
        compiler,
    ]
    return subprocess.run([*command, *arguments], cwd=root, capture_output=True, text=True)


def _gate_api() -> CanonicalApi:
    """A Petstore-shaped contract exercising every generated construct at once."""
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        title="Petstore",
        version="1.0.0",
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
                fields=[
                    _member("id", "i64", required=True),
                    _member("name", "string", required=True),
                    _member("status", "Status"),
                    _member("tags", "", item="string"),
                ],
            ),
        ],
        services=[
            Service(
                key="pets",
                name="pets",
                operations=[
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
                            )
                        ],
                        messages=[
                            Message(key="r", role=MessageRole.RESPONSE, status_code="200",
                                    payload=TypeRef(name="list", item=TypeRef(name="Pet")))
                        ],
                    ),
                    _op(
                        "POST /pets",
                        "createPet",
                        method="post",
                        path="/pets",
                        messages=[
                            Message(key="req", role=MessageRole.REQUEST, payload=TypeRef(name="Pet"),
                                    content_types=["application/json"], required=True),
                            Message(key="res", role=MessageRole.RESPONSE, status_code="201",
                                    payload=TypeRef(name="Pet")),
                        ],
                    ),
                    _op(
                        "GET /pets/{petId}",
                        "getPet",
                        path="/pets/{petId}",
                        parameters=[
                            Parameter(key="p", name="petId", location=ParameterLocation.PATH,
                                      type=TypeRef(name="i64"), required=True)
                        ],
                        messages=[Message(key="r", role=MessageRole.RESPONSE, status_code="200",
                                          payload=TypeRef(name="Pet"))],
                    ),
                ],
            )
        ],
    )


@pytest.fixture()
def gate_root(tmp_path) -> Path:
    """Write the generated Petstore project to a temporary directory."""
    project = _generate(_gate_api(), license_header="Copyright (c) 2026 Acme */ Inc.")
    for item in project.files:
        target = tmp_path / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.text)
    return tmp_path


_TSC_FLAGS = (
    "--noEmit",
    "--strict",
    "--noImplicitOverride",
    "--target",
    "ES2022",
    "--module",
    "commonjs",
    "--moduleResolution",
    "node",
    "--lib",
    "ES2022",
    "--skipLibCheck",
)


@pytest.mark.skipif(_typescript_compiler() is None, reason="no TypeScript compiler available")
def test_the_generated_core_type_checks_under_strict(gate_root: Path) -> None:
    """The gate: the emitted TypeScript is TypeScript, with `strict` on."""
    result = _run_tsc(gate_root, *_TSC_FLAGS, *CORE_FILES)
    assert result.returncode == 0, f"tsc failed:\n{result.stdout}{result.stderr}"


@pytest.mark.skipif(_typescript_compiler() is None, reason="no TypeScript compiler available")
def test_a_handler_implemented_with_the_wrong_signature_is_a_compile_error(gate_root: Path) -> None:
    """The typed-interface promise, checked by the tool a consumer would check it with."""
    (gate_root / "src" / "wrong.ts").write_text(
        "import { NotImplementedPetsHandlers } from './handlers';\n"
        "\n"
        "export class Broken extends NotImplementedPetsHandlers {\n"
        "  override async getPet(request: { nope: string }): Promise<string> {\n"
        "    return request.nope;\n"
        "  }\n"
        "}\n"
    )
    result = _run_tsc(gate_root, *_TSC_FLAGS, *CORE_FILES, "src/wrong.ts")
    assert result.returncode != 0, "a wrong handler signature compiled"
    assert "getPet" in result.stdout


@pytest.mark.skipif(_typescript_compiler() is None, reason="no TypeScript compiler available")
def test_a_correct_implementation_type_checks(gate_root: Path) -> None:
    """The other half of the promise: the signature the generator documents is the right one."""
    (gate_root / "src" / "right.ts").write_text(
        "import { NotImplementedPetsHandlers, type GetPetRequest, type GetPetResponse } from './handlers';\n"
        "\n"
        "export class Works extends NotImplementedPetsHandlers {\n"
        "  override async getPet(request: GetPetRequest): Promise<GetPetResponse> {\n"
        "    return { id: request.petId, name: 'Rex' };\n"
        "  }\n"
        "}\n"
    )
    result = _run_tsc(gate_root, *_TSC_FLAGS, *CORE_FILES, "src/right.ts")
    assert result.returncode == 0, f"tsc failed:\n{result.stdout}{result.stderr}"


_DRIVER = """
const { validateOperationRequest } = require('./out/validation');
const { operations } = require('./out/schemas');

function request(overrides) {
  return { method: 'GET', params: {}, query: {}, headers: {}, ...overrides };
}

const results = {
  validQuery: validateOperationRequest(operations.listPets, request({ query: { limit: '25' } })),
  badQuery: validateOperationRequest(operations.listPets, request({ query: { limit: 'abc' } })),
  outOfRange: validateOperationRequest(operations.listPets, request({ query: { limit: '500' } })),
  missingPath: validateOperationRequest(operations.getPet, request({ params: {} })),
  badPath: validateOperationRequest(operations.getPet, request({ params: { petId: 'nope' } })),
  goodPath: validateOperationRequest(operations.getPet, request({ params: { petId: '7' } })),
  missingBodyField: validateOperationRequest(
    operations.createPet,
    request({ method: 'POST', body: { name: 'Rex' } }),
  ),
  badEnum: validateOperationRequest(
    operations.createPet,
    request({ method: 'POST', body: { id: 1, name: 'Rex', status: 'nope' } }),
  ),
  goodBody: validateOperationRequest(
    operations.createPet,
    request({ method: 'POST', body: { id: 1, name: 'Rex', status: 'sold', tags: ['a'] } }),
  ),
};
console.log(JSON.stringify(results));
"""


@pytest.mark.skipif(
    _typescript_compiler() is None or shutil.which("node") is None,
    reason="no TypeScript compiler or node available",
)
def test_the_generated_validator_rejects_what_the_contract_rejects(gate_root: Path) -> None:
    """The gate that matters most: the validation is not just typed, it runs and it is right.

    The validator is compiled to JavaScript and driven directly with fake requests, so this proves
    the *generated rules* — not a hand-written middleware — reject a bad type, an out-of-range
    value, a missing required path parameter, a missing required body member and a value outside a
    declared enum, while letting a conforming request through with its values coerced.
    """
    compiled = _run_tsc(
        gate_root,
        "--outDir",
        "out",
        "--strict",
        "--target",
        "ES2022",
        "--module",
        "commonjs",
        "--moduleResolution",
        "node",
        "--lib",
        "ES2022",
        "--skipLibCheck",
        *CORE_FILES,
    )
    assert compiled.returncode == 0, f"tsc failed:\n{compiled.stdout}{compiled.stderr}"

    (gate_root / "drive.js").write_text(_DRIVER)
    run = subprocess.run(
        [shutil.which("node") or "node", "drive.js"], cwd=gate_root, capture_output=True, text=True
    )
    assert run.returncode == 0, run.stderr
    results = json.loads(run.stdout)

    assert results["validQuery"] == {"ok": True, "value": {"limit": 25}}
    assert results["goodPath"] == {"ok": True, "value": {"petId": 7}}
    assert results["goodBody"]["ok"] is True

    assert results["badQuery"]["ok"] is False
    assert results["badQuery"]["errors"] == [
        {"location": "query", "field": "limit", "message": "must be an integer"}
    ]
    assert results["outOfRange"]["errors"] == [
        {"location": "query", "field": "limit", "message": "must be <= 100"}
    ]
    assert results["missingPath"]["errors"] == [
        {"location": "path", "field": "petId", "message": "is required"}
    ]
    assert results["badPath"]["ok"] is False
    assert results["missingBodyField"]["errors"] == [
        {"location": "body", "field": "id", "message": "is required"}
    ]
    assert results["badEnum"]["errors"] == [
        {"location": "body", "field": "status", "message": "must be one of available, sold"}
    ]


def test_the_two_stubs_agree_on_the_status_a_violation_is_answered_with() -> None:
    """Two stubs generated from one contract must not disagree about what a violation is."""
    from app.fastapi_stub_generator import VALIDATION_STATUS as FASTAPI_STATUS

    assert VALIDATION_STATUS == FASTAPI_STATUS
