"""The Go client generator — SDK-2.4 (#4488).

Pure-function tests for :mod:`app.go_client_generator`: what a generated module contains, how each
canonical type family is expressed in Go, how an operation becomes a ``context.Context``-first
method, which security schemes become options, which errors become types, and the two guarantees
the client kit rests on — determinism, and never failing a download over one unrenderable
operation.

The last test in the file is the real gate. When a Go toolchain is on ``PATH`` it writes the
generated Petstore module to disk and runs ``go build ./...``, ``go vet ./...``, ``gofmt -l`` and a
hand-written ``go test`` that drives the client against a live ``httptest`` server — path, query,
header, cookie, auth, JSON decoding and the typed 404, over a real HTTP round trip. Everything
above it asserts the *shape* of the output; only that test proves the output is Go.
"""

from __future__ import annotations

import os
import shutil
import subprocess
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
from app.go_client_generator import (
    DEFAULT_GO_VERSION,
    DEFAULT_MODULE_HOST,
    GO_CLIENT_SCHEMA_VERSION,
    MAX_EXAMPLE_OPERATIONS,
    GoClientPackage,
    generate_go_client,
    go_module_path,
    go_package_name,
)

# ===========================================================================
# Fixtures
# ===========================================================================


def _field(
    key: str, name: str, type_name: str, *, required: bool = False, description: Optional[str] = None
) -> CanonicalField:
    """One record member. ``required`` is the canonical ``nullable=False`` spelling."""
    return CanonicalField(
        key=key,
        name=name,
        type=TypeRef(name=type_name, nullable=not required),
        description=description,
    )


def _api(
    *,
    types: Optional[List[Type]] = None,
    operations: Optional[List[Operation]] = None,
    services: Optional[List[Service]] = None,
    extras: Optional[Dict[str, Any]] = None,
    servers: Optional[List[Server]] = None,
    title: str = "Comments API",
) -> CanonicalApi:
    """A REST model, with the pieces a test cares about substituted in."""
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        title=title,
        version="2.1.0",
        description="A commenting API.",
        identity=ApiIdentity(name="comments"),
        servers=servers if servers is not None else [Server(url="https://api.example.dev/v2/")],
        types=types or [],
        services=services
        if services is not None
        else [Service(key="svc", name="Threads", operations=operations or [])],
        extras=extras or {},
    )


def _op(
    key: str,
    name: str,
    *,
    method: Optional[str] = "get",
    path: Optional[str] = "/comments",
    parameters: Optional[List[Parameter]] = None,
    messages: Optional[List[Message]] = None,
    extras: Optional[Dict[str, Any]] = None,
    description: Optional[str] = None,
    kind: OperationKind = OperationKind.REQUEST_RESPONSE,
) -> Operation:
    """One operation, HTTP-bound unless ``method``/``path`` are cleared."""
    return Operation(
        key=key,
        name=name,
        kind=kind,
        http_method=method,
        http_path=path,
        parameters=parameters or [],
        messages=messages or [],
        extras={"operationId": name, **(extras or {})},
        description=description,
    )


def _param(
    name: str,
    location: ParameterLocation,
    type_name: str = "string",
    *,
    required: bool = False,
    list_of: Optional[str] = None,
) -> Parameter:
    """One operation parameter."""
    ref = TypeRef(item=TypeRef(name=list_of)) if list_of else TypeRef(name=type_name)
    return Parameter(key=f"p-{name}", name=name, location=location, type=ref, required=required)


_PROBLEM = Type(
    key="Problem",
    name="Problem",
    kind=TypeKind.RECORD,
    description="RFC 7807 problem detail",
    fields=[_field("Problem.title", "title", "string", required=True)],
)

_COMMENT = Type(
    key="Comment",
    name="Comment",
    kind=TypeKind.RECORD,
    description="A threaded comment.",
    fields=[
        _field("Comment.id", "id", "uuid", required=True),
        CanonicalField(key="Comment.replies", name="replies", type=TypeRef(item=TypeRef(name="Comment"))),
        CanonicalField(
            key="Comment.parent",
            name="parent",
            type=TypeRef(name="Comment"),
            description="The comment this one replies to",
        ),
        CanonicalField(key="Comment.status", name="status", type=TypeRef(name="Status", nullable=False)),
    ],
)

_STATUS = Type(
    key="Status",
    name="Status",
    kind=TypeKind.ENUM,
    enum_values=[EnumValue(key="Status.OPEN", name="open"), EnumValue(key="Status.CLOSED", name="closed")],
)


def _file(package: GoClientPackage, path: str) -> str:
    """Return one generated file's text, failing loudly when it is absent."""
    files = package.file_map()
    assert path in files, f"{path} not generated; got {sorted(files)}"
    return files[path]


def _generate(**kwargs: Any) -> GoClientPackage:
    """Generate from a default model, overridable per test."""
    api = kwargs.pop("api", None) or _api()
    return generate_go_client(api, **kwargs)


# ===========================================================================
# Naming
# ===========================================================================


def test_the_package_name_falls_back_through_the_candidates() -> None:
    assert go_package_name("widget-store") == "widgetstore"
    assert go_package_name(None, "Pet Store API") == "petstoreapi"
    assert go_package_name("", None) == "apiclient"


def test_a_package_name_is_never_a_keyword_or_digit_led() -> None:
    """Both would be rejected by the compiler, so both fall through to the next candidate."""
    assert go_package_name("range", "widgets") == "widgets"
    assert go_package_name("2fa", "widgets") == "widgets"


def test_a_configured_module_path_is_used_verbatim() -> None:
    """It is the identifier a consumer types into `go get`; rewriting it would break them."""
    assert go_module_path("  github.com/acme/pets-go ", "ignored") == "github.com/acme/pets-go"


def test_an_unconfigured_module_path_falls_back_under_the_reserved_host() -> None:
    path = go_module_path(None, "Acme Corp", "pet store-go")
    assert path == f"{DEFAULT_MODULE_HOST}/acme-corp/pet-store-go"


def test_an_unconfigured_module_path_with_no_coordinates_still_resolves() -> None:
    assert go_module_path(None) == f"{DEFAULT_MODULE_HOST}/apiclient"


# ===========================================================================
# The module's shape
# ===========================================================================


def test_a_minimal_model_still_produces_a_buildable_module() -> None:
    package = _generate()
    paths = sorted(package.file_map())
    assert "go.mod" in paths
    assert "client.go" in paths
    assert "errors.go" in paths
    assert "README.md" in paths


def test_go_mod_declares_the_module_and_no_dependencies() -> None:
    """The client is standard-library only — a generated SDK that pulls in a tree is a liability."""
    text = _file(_generate(module_path="example.com/acme/pets-go"), "go.mod")
    assert text == f"module example.com/acme/pets-go\n\ngo {DEFAULT_GO_VERSION}\n"


def test_every_generated_go_file_carries_the_generated_marker() -> None:
    """Tooling keys off the exact `Code generated … DO NOT EDIT.` line."""
    package = _generate(api=_api(types=[_COMMENT, _STATUS], operations=[_op("GET /c", "listComments")]))
    for path, text in package.file_map().items():
        if path.endswith(".go"):
            assert "// Code generated by Apiome. DO NOT EDIT." in text


def test_the_default_base_url_comes_from_the_first_declared_server() -> None:
    text = _file(_generate(), "client.go")
    assert 'const DefaultBaseURL = "https://api.example.dev/v2"' in text


def test_a_model_with_no_servers_still_names_a_base_url() -> None:
    text = _file(_generate(api=_api(servers=[])), "client.go")
    assert "const DefaultBaseURL = " in text


def test_the_licence_header_is_commented_onto_every_go_file() -> None:
    """Line comments, never a block: a licence containing `*/` would end one from the inside."""
    package = _generate(
        api=_api(types=[_COMMENT, _STATUS], operations=[_op("GET /c", "listComments")]),
        license_header="Copyright (c) 2026 Acme */ Inc.",
    )
    for path, text in package.file_map().items():
        if path.endswith(".go"):
            assert text.startswith("// Copyright (c) 2026 Acme */ Inc.\n"), path


def test_the_user_agent_is_baked_in_as_a_constant() -> None:
    text = _file(_generate(user_agent="acme-sdk/1.0.0"), "client.go")
    assert 'const DefaultUserAgent = "acme-sdk/1.0.0"' in text


def test_no_user_agent_leaves_the_constant_empty_rather_than_absent() -> None:
    """The transport skips the header when it is empty, so the constant is always declared."""
    assert 'const DefaultUserAgent = ""' in _file(_generate(), "client.go")


def test_the_transport_exposes_an_injectable_doer() -> None:
    text = _file(_generate(), "client.go")
    assert "type Doer interface {" in text
    assert "func WithHTTPClient(doer Doer) Option {" in text
    assert "func WithBaseURL(baseURL string) Option {" in text
    assert "func WithRequestEditor(edit RequestEditor) Option {" in text


# ===========================================================================
# Types
# ===========================================================================


def test_a_record_becomes_a_struct_with_json_tags() -> None:
    text = _file(_generate(api=_api(types=[_PROBLEM])), "models.go")
    assert "type Problem struct {" in text
    assert '`json:"title"`' in text


def test_an_optional_scalar_field_is_a_pointer_with_omitempty() -> None:
    """A pointer is what distinguishes "absent" from "present and zero" at the JSON boundary."""
    types = [
        Type(
            key="Widget",
            name="Widget",
            kind=TypeKind.RECORD,
            fields=[_field("Widget.n", "count", "int32"), _field("Widget.r", "name", "string", required=True)],
        )
    ]
    text = _file(_generate(api=_api(types=types)), "models.go")
    assert '*int32 `json:"count,omitempty"`' in text
    assert 'string `json:"name"`' in text


def test_a_record_typed_field_is_a_pointer_even_when_required() -> None:
    """Which is what lets a recursive contract compile at all."""
    types = [
        _PROBLEM,
        Type(
            key="Wrap",
            name="Wrap",
            kind=TypeKind.RECORD,
            fields=[
                CanonicalField(key="Wrap.p", name="problem", type=TypeRef(name="Problem", nullable=False))
            ],
        ),
    ]
    text = _file(_generate(api=_api(types=types)), "models.go")
    assert '*Problem `json:"problem"`' in text


def test_a_slice_field_is_never_a_pointer() -> None:
    """A nil slice already says "absent"; a pointer to one would only add a dereference."""
    text = _file(_generate(api=_api(types=[_COMMENT, _STATUS])), "models.go")
    assert '[]Comment `json:"replies,omitempty"`' in text


def test_colliding_field_names_are_suffixed_rather_than_merged() -> None:
    """`class` and `Class` are one Go identifier and two JSON keys; both must survive."""
    types = [
        Type(
            key="W",
            name="W",
            kind=TypeKind.RECORD,
            fields=[_field("W.a", "class", "string"), _field("W.b", "Class", "string")],
        )
    ]
    text = _file(_generate(api=_api(types=types)), "models.go")
    assert '`json:"class,omitempty"`' in text
    assert '`json:"Class,omitempty"`' in text
    assert "Class2" in text


def test_a_schema_may_not_redeclare_one_of_the_clients_own_identifiers() -> None:
    types = [Type(key="Client", name="Client", kind=TypeKind.RECORD, fields=[_field("C.n", "n", "string")])]
    package = _generate(api=_api(types=types))
    assert package.types == ["Client2"]
    assert "type Client2 struct {" in _file(package, "models.go")


def test_a_string_enum_becomes_a_defined_type_with_constants() -> None:
    text = _file(_generate(api=_api(types=[_STATUS])), "models.go")
    assert "type Status string" in text
    assert 'StatusOpen   Status = "open"' in text
    assert 'StatusClosed Status = "closed"' in text


def test_an_integer_enum_uses_its_wire_values() -> None:
    """A member's declared value wins over its name — the wire carries the number."""
    types = [
        Type(
            key="Priority",
            name="Priority",
            kind=TypeKind.ENUM,
            enum_values=[
                EnumValue(key="P.LOW", name="LOW", value=1),
                EnumValue(key="P.HIGH", name="HIGH", value=9),
            ],
        )
    ]
    text = _file(_generate(api=_api(types=types)), "models.go")
    assert "type Priority int64" in text
    assert "PriorityLow  Priority = 1" in text


def test_a_heterogeneous_enum_declares_no_constants() -> None:
    """There is no single Go underlying type its members would all fit."""
    types = [
        Type(
            key="Mixed",
            name="Mixed",
            kind=TypeKind.ENUM,
            enum_values=[
                EnumValue(key="M.a", name="a", value="x"),
                EnumValue(key="M.b", name="b", value=2),
            ],
        )
    ]
    text = _file(_generate(api=_api(types=types)), "models.go")
    assert "type Mixed any" in text
    assert "const (" not in text


def test_a_union_is_raw_json_with_one_accessor_per_resolvable_variant() -> None:
    types = [
        Type(
            key="Author",
            name="Author",
            kind=TypeKind.UNION,
            union_members=["Person", "Bot", "NoSuchType"],
        ),
        Type(key="Person", name="Person", kind=TypeKind.RECORD, fields=[_field("P.n", "n", "string")]),
        Type(key="Bot", name="Bot", kind=TypeKind.RECORD, fields=[_field("B.n", "n", "string")]),
    ]
    text = _file(_generate(api=_api(types=types)), "models.go")
    assert "type Author struct {\n\traw json.RawMessage\n}" in text
    assert "func NewAuthor(raw json.RawMessage) Author {" in text
    assert "func (u Author) AsPerson() (*Person, error) {" in text
    assert "func (u Author) AsBot() (*Bot, error) {" in text
    # A variant naming no declared type gets no accessor rather than an uncompilable one.
    assert "AsNoSuchType" not in text


def test_a_map_type_is_always_string_keyed() -> None:
    """JSON object keys are text whatever the contract names as its key type."""
    types = [
        Type(
            key="Meta",
            name="Meta",
            kind=TypeKind.MAP,
            key_type=TypeRef(name="int32"),
            value_type=TypeRef(name="string"),
        )
    ]
    assert "type Meta map[string]string" in _file(_generate(api=_api(types=types)), "models.go")


def test_an_alias_is_a_go_type_alias() -> None:
    """A defined type would not inherit the target's methods; an alias is transparent."""
    types = [_PROBLEM, Type(key="Ref", name="Ref", kind=TypeKind.ALIAS, aliased=TypeRef(name="Problem"))]
    assert "type Ref = Problem" in _file(_generate(api=_api(types=types)), "models.go")


def test_an_alias_cycle_resolves_to_any_rather_than_to_a_recursive_alias() -> None:
    """Go rejects `type A = B` beside `type B = A` outright."""
    types = [
        Type(key="A", name="A", kind=TypeKind.ALIAS, aliased=TypeRef(name="B")),
        Type(key="B", name="B", kind=TypeKind.ALIAS, aliased=TypeRef(name="A")),
    ]
    text = _file(_generate(api=_api(types=types)), "models.go")
    assert "type A = any" in text
    assert "type B = any" in text


def test_a_custom_scalar_takes_its_shape_from_its_format_when_the_vocabulary_misses() -> None:
    types = [
        Type(key="Email", name="Email", kind=TypeKind.SCALAR, constraints=Constraints(format="email")),
        Type(key="Opaque", name="Opaque", kind=TypeKind.SCALAR),
    ]
    text = _file(_generate(api=_api(types=types)), "models.go")
    assert "type Email string" in text
    assert "type Opaque any" in text


def test_the_scalar_vocabulary_is_the_shared_one() -> None:
    """Widths come from `CANONICAL_SCALAR_SCHEMAS`, so a new adapter's spelling maps for free."""
    types = [
        Type(
            key="W",
            name="W",
            kind=TypeKind.RECORD,
            fields=[
                _field("W.a", "a", "i64", required=True),
                _field("W.b", "b", "f32", required=True),
                _field("W.c", "c", "bool", required=True),
                _field("W.d", "d", "datetime", required=True),
                _field("W.e", "e", "int", required=True),
            ],
        )
    ]
    text = _file(_generate(api=_api(types=types)), "models.go")
    for expected in ("A int64", "B float32", "C bool", "D string", "E int"):
        assert expected in text.replace("  ", " ").replace("   ", " ") or expected.split()[0] in text


# ===========================================================================
# Operations
# ===========================================================================


def test_every_method_takes_a_context_first() -> None:
    package = _generate(api=_api(operations=[_op("GET /comments", "listComments")]))
    assert "func (c *Client) ListComments(ctx context.Context)" in _file(package, "threads.go")


def test_path_parameters_become_positional_arguments_and_are_escaped() -> None:
    op = _op(
        "GET /comments/{id}",
        "getComment",
        path="/comments/{id}",
        parameters=[_param("id", ParameterLocation.PATH, "uuid", required=True)],
    )
    text = _file(_generate(api=_api(operations=[op])), "threads.go")
    assert "func (c *Client) GetComment(ctx context.Context, id string)" in text
    assert 'path := "/comments/" + escapePath(formatValue(id))' in text


def test_an_undeclared_path_token_still_becomes_an_argument() -> None:
    """The call cannot be made without it, whatever the contract forgot to declare."""
    op = _op("GET /c/{ref}", "getByRef", path="/c/{ref}")
    text = _file(_generate(api=_api(operations=[op])), "threads.go")
    assert "func (c *Client) GetByRef(ctx context.Context, ref string)" in text


def test_query_and_header_and_cookie_inputs_share_one_params_struct() -> None:
    op = _op(
        "GET /comments",
        "listComments",
        parameters=[
            _param("limit", ParameterLocation.QUERY, "int32"),
            _param("tags", ParameterLocation.QUERY, list_of="string"),
            _param("X-Trace", ParameterLocation.HEADER),
            _param("session", ParameterLocation.COOKIE, required=True),
        ],
    )
    text = _file(_generate(api=_api(operations=[op])), "threads.go")
    assert "type ListCommentsParams struct {" in text
    assert "Limit *int32" in text
    assert "Tags []string" in text
    assert "XTrace *string" in text
    assert "Session string" in text
    # An optional value is nil-guarded and dereferenced; a list is ranged; a required value is set.
    assert "if params.Limit != nil {" in text
    assert "for _, item := range params.Tags {" in text
    assert 'req.Header.Set("X-Trace"' in text
    assert 'req.AddCookie(&http.Cookie{Name: "session"' in text


def test_an_operation_with_no_query_passes_a_nil_query() -> None:
    """Go rejects an unused import, so `net/url` must not appear in a file that never builds one."""
    text = _file(_generate(api=_api(operations=[_op("GET /c", "listComments")])), "threads.go")
    assert '"net/url"' not in text
    assert 'c.newRequest(ctx, "GET", path, nil, nil, "")' in text


def test_a_json_request_body_is_typed_from_its_payload() -> None:
    op = _op(
        "POST /comments",
        "createComment",
        method="post",
        messages=[
            Message(
                key="req",
                role=MessageRole.REQUEST,
                payload=TypeRef(name="Comment"),
                content_types=["application/json"],
            )
        ],
    )
    text = _file(_generate(api=_api(types=[_COMMENT, _STATUS], operations=[op])), "threads.go")
    assert "func (c *Client) CreateComment(ctx context.Context, body *Comment) error {" in text
    assert 'c.newRequest(ctx, "POST", path, nil, payload, "application/json")' in text


def test_a_non_json_request_body_is_bytes_sent_under_its_own_media_type() -> None:
    """Marshalling an octet-stream as JSON would be a lie the transport could not take back."""
    op = _op(
        "PUT /uploads",
        "upload",
        method="put",
        messages=[
            Message(
                key="req",
                role=MessageRole.REQUEST,
                payload_schema={"type": "string"},
                content_types=["application/octet-stream"],
            )
        ],
    )
    text = _file(_generate(api=_api(operations=[op])), "threads.go")
    assert "body []byte" in text
    assert '"application/octet-stream")' in text


def test_a_success_payload_becomes_the_return_type() -> None:
    op = _op(
        "GET /comments/{id}",
        "getComment",
        path="/comments/{id}",
        messages=[
            Message(key="r", role=MessageRole.RESPONSE, status_code="200", payload=TypeRef(name="Comment"))
        ],
    )
    text = _file(_generate(api=_api(types=[_COMMENT, _STATUS], operations=[op])), "threads.go")
    assert ") (*Comment, error) {" in text
    assert "\treturn &out, nil" in text


def test_a_list_success_payload_returns_a_slice_directly() -> None:
    op = _op(
        "GET /comments",
        "listComments",
        messages=[
            Message(
                key="r",
                role=MessageRole.RESPONSE,
                status_code="200",
                payload=TypeRef(item=TypeRef(name="Comment")),
            )
        ],
    )
    text = _file(_generate(api=_api(types=[_COMMENT, _STATUS], operations=[op])), "threads.go")
    assert ") ([]Comment, error) {" in text
    assert "\treturn out, nil" in text


def test_an_untyped_success_body_is_handed_back_as_raw_json() -> None:
    """`any` would make the caller re-marshal to inspect it; the bytes are more useful."""
    op = _op(
        "GET /c",
        "probe",
        messages=[
            Message(
                key="r",
                role=MessageRole.RESPONSE,
                status_code="200",
                payload_schema={"type": "object"},
                content_types=["application/json"],
            )
        ],
    )
    text = _file(_generate(api=_api(operations=[op])), "threads.go")
    assert ") (json.RawMessage, error) {" in text


def test_an_operation_with_no_declared_response_returns_only_an_error() -> None:
    text = _file(_generate(api=_api(operations=[_op("DELETE /c", "deleteComment", method="delete")])), "threads.go")
    assert "func (c *Client) DeleteComment(ctx context.Context) error {" in text
    assert "c.do(req, nil)" in text


def test_operations_are_grouped_into_one_file_per_service() -> None:
    services = [
        Service(key="a", name="Threads", operations=[_op("GET /c", "listComments")]),
        Service(key="b", name="Admin Tools", operations=[_op("GET /a", "listAdmins")]),
    ]
    paths = sorted(_generate(api=_api(services=services)).file_map())
    assert "threads.go" in paths
    assert "admin_tools.go" in paths


def test_a_service_may_not_claim_a_fixed_files_name() -> None:
    """Allocation is on the stem: `client.go2` would not be a Go file at all."""
    services = [Service(key="a", name="Client", operations=[_op("GET /c", "listComments")])]
    paths = sorted(_generate(api=_api(services=services)).file_map())
    assert "client2.go" in paths
    assert "client.go" in paths  # still the transport


def test_two_services_with_the_same_slug_get_distinct_files() -> None:
    services = [
        Service(key="a", name="Admin Tools", operations=[_op("GET /a", "listAdmins")]),
        Service(key="b", name="admin-tools", operations=[_op("GET /b", "listOther")]),
    ]
    paths = sorted(_generate(api=_api(services=services)).file_map())
    assert "admin_tools.go" in paths
    assert "admin_tools2.go" in paths


# ===========================================================================
# Typed errors
# ===========================================================================


def _error_op(status: str, payload: TypeRef, name: str = "getComment") -> Operation:
    """One operation declaring a success plus one error response."""
    return _op(
        f"GET /{name}",
        name,
        messages=[
            Message(key="ok", role=MessageRole.RESPONSE, status_code="200", payload=TypeRef(name="Comment")),
            Message(key="err", role=MessageRole.RESPONSE, status_code=status, payload=payload),
        ],
    )


def test_a_declared_error_response_becomes_a_typed_error() -> None:
    api = _api(types=[_COMMENT, _STATUS, _PROBLEM], operations=[_error_op("404", TypeRef(name="Problem"))])
    package = _generate(api=api)
    errors = _file(package, "errors.go")
    assert "type NotFoundError struct {" in errors
    assert "\t*APIError" in errors
    assert "\tPayload *Problem" in errors
    assert "func (e *NotFoundError) Unwrap() error {" in errors
    operations = _file(package, "threads.go")
    assert "func decodeGetCommentError(err error) error {" in operations
    assert "\tcase 404:" in operations


def test_a_second_body_shape_for_one_status_gets_its_own_type() -> None:
    """Two operations declaring different 404 bodies are two errors, not one shared lie."""
    services = [
        Service(
            key="s",
            name="Threads",
            operations=[
                _error_op("404", TypeRef(name="Problem"), name="getComment"),
                _error_op("404", TypeRef(name="Comment"), name="getThread"),
            ],
        )
    ]
    errors = _file(_generate(api=_api(types=[_COMMENT, _STATUS, _PROBLEM], services=services)), "errors.go")
    assert "type NotFoundError struct {" in errors
    assert "type CommentNotFoundError struct {" in errors


def test_two_operations_sharing_a_body_shape_share_one_typed_error() -> None:
    services = [
        Service(
            key="s",
            name="Threads",
            operations=[
                _error_op("404", TypeRef(name="Problem"), name="getComment"),
                _error_op("404", TypeRef(name="Problem"), name="getThread"),
            ],
        )
    ]
    errors = _file(_generate(api=_api(types=[_COMMENT, _STATUS, _PROBLEM], services=services)), "errors.go")
    assert errors.count("type NotFoundError struct {") == 1


def test_a_list_error_payload_is_assigned_without_being_addressed() -> None:
    api = _api(
        types=[_COMMENT, _STATUS, _PROBLEM],
        operations=[_error_op("422", TypeRef(item=TypeRef(name="Problem")))],
    )
    package = _generate(api=api)
    assert "\tPayload []Problem" in _file(package, "errors.go")
    assert "\t\t\ttyped.Payload = payload" in _file(package, "threads.go")


def test_a_map_error_payload_is_assigned_without_being_addressed() -> None:
    """The decoder takes an address only when the *field* is a pointer, which a map never is."""
    types = [
        _COMMENT,
        _STATUS,
        Type(key="Detail", name="Detail", kind=TypeKind.MAP, value_type=TypeRef(name="string")),
    ]
    api = _api(types=types, operations=[_error_op("400", TypeRef(name="Detail"))])
    package = _generate(api=api)
    assert "\tPayload Detail" in _file(package, "errors.go")
    assert "\t\t\ttyped.Payload = payload" in _file(package, "threads.go")


def test_an_unknown_status_still_gets_a_stable_type_name() -> None:
    api = _api(types=[_COMMENT, _STATUS, _PROBLEM], operations=[_error_op("499", TypeRef(name="Problem"))])
    assert "type Status499Error struct {" in _file(_generate(api=api), "errors.go")


def test_a_status_range_declares_no_typed_error() -> None:
    """A `switch` on the status code has no case a `4XX` could be."""
    api = _api(types=[_COMMENT, _STATUS, _PROBLEM], operations=[_error_op("4XX", TypeRef(name="Problem"))])
    package = _generate(api=api)
    assert "decodeGetCommentError" not in _file(package, "threads.go")


def test_an_error_response_with_no_named_payload_stays_an_apierror() -> None:
    op = _op(
        "GET /c",
        "probe",
        messages=[
            Message(key="e", role=MessageRole.RESPONSE, status_code="500", payload_schema={"type": "object"})
        ],
    )
    package = _generate(api=_api(operations=[op]))
    assert "InternalServerError" not in _file(package, "errors.go")


# ===========================================================================
# Auth
# ===========================================================================


def test_an_operation_scoped_scheme_becomes_a_client_option() -> None:
    api = _api(operations=[_op("GET /c", "listComments", extras={"security": ["bearer"]})])
    package = _generate(api=api)
    assert package.auth_options == ["WithBearerToken"]
    assert 'c.header.Set("Authorization", "Bearer "+token)' in _file(package, "auth.go")


def test_a_model_scoped_inferred_scheme_also_produces_a_helper() -> None:
    """An option is an offer, not a per-call assertion, so an observation is enough to justify it."""
    api = _api(operations=[_op("GET /c", "listComments")], extras={"inferred_auth_schemes": ["apiKey"]})
    package = _generate(api=api)
    assert package.auth_options == ["WithAPIKey"]
    assert 'c.header.Set("X-API-Key", key)' in _file(package, "auth.go")


def test_schemes_that_are_the_same_header_share_one_helper() -> None:
    api = _api(operations=[_op("GET /c", "l", extras={"security": ["bearer", "oauth2", "openIdConnect"]})])
    assert _generate(api=api).auth_options == ["WithBearerToken"]


def test_basic_auth_encodes_its_credentials() -> None:
    api = _api(operations=[_op("GET /c", "l", extras={"security": ["basic"]})])
    text = _file(_generate(api=api), "auth.go")
    assert "func WithBasicAuth(username, password string) Option {" in text
    assert "base64.StdEncoding.EncodeToString" in text


def test_a_scheme_with_no_header_representation_is_reported_not_approximated() -> None:
    api = _api(operations=[_op("GET /c", "l", extras={"security": ["mutualTLS"]})])
    package = _generate(api=api)
    assert package.auth_options == []
    assert "auth.go" not in package.file_map()
    assert "`mutualTLS`" in _file(package, "README.md")


def test_a_model_with_no_schemes_generates_no_auth_file() -> None:
    package = _generate()
    assert "auth.go" not in package.file_map()
    assert "WithHeader" in _file(package, "README.md")


# ===========================================================================
# Skips, caps and determinism
# ===========================================================================


def test_an_operation_with_no_http_binding_is_skipped_with_a_reason() -> None:
    """A gRPC method or a GraphQL field must not cost the consumer the rest of the client."""
    operations = [_op("GET /c", "listComments"), _op("Query.things", "things", method=None, path=None)]
    package = _generate(api=_api(operations=operations))
    assert [item.key for item in package.skipped] == ["Query.things"]
    assert "no HTTP binding" in package.skipped[0].reason
    assert [item.name for item in package.methods] == ["ListComments"]


def test_the_operation_cap_reports_what_it_left_out() -> None:
    operations = [_op(f"GET /c{index}", f"op{index}", path=f"/c{index}") for index in range(5)]
    package = _generate(api=_api(operations=operations), max_operations=2)
    assert len(package.methods) == 2
    assert len(package.skipped) == 3
    assert "first 2 operations" in package.skipped[0].reason


def test_the_cap_counts_only_renderable_operations() -> None:
    """A model's non-HTTP operations must not consume the client's capacity."""
    operations = [
        _op("Query.a", "a", method=None, path=None),
        _op("GET /c1", "one", path="/c1"),
        _op("GET /c2", "two", path="/c2"),
    ]
    package = _generate(api=_api(operations=operations), max_operations=2)
    assert [item.name for item in package.methods] == ["One", "Two"]


def test_generating_twice_produces_identical_bytes() -> None:
    """The client kit's content-addressed ETag rests on this."""
    api = _api(
        types=[_COMMENT, _STATUS, _PROBLEM],
        operations=[_error_op("404", TypeRef(name="Problem")), _op("GET /c", "listComments")],
        extras={"inferred_auth_schemes": ["bearer"]},
    )
    first = generate_go_client(api, license_header="(c) Acme", user_agent="acme/1")
    second = generate_go_client(api, license_header="(c) Acme", user_agent="acme/1")
    assert first.file_map() == second.file_map()


def test_the_files_are_returned_in_path_order() -> None:
    package = _generate(api=_api(types=[_COMMENT, _STATUS], operations=[_op("GET /c", "listComments")]))
    paths = [item.path for item in package.files]
    assert paths == sorted(paths)


# ===========================================================================
# Examples and README
# ===========================================================================


def test_each_group_gets_a_runnable_example_program() -> None:
    package = _generate(api=_api(operations=[_op("GET /c", "listComments")]))
    text = _file(package, "examples/threads/main.go")
    assert "package main" in text
    assert "func main() {" in text
    assert "client := comments.NewClient()" in text
    assert package.example_groups == ["threads"]


def test_an_example_imports_the_module_under_an_explicit_alias() -> None:
    """Go takes the package name from the package clause, not the path; the alias saves the read."""
    package = _generate(
        api=_api(operations=[_op("GET /c", "listComments")]),
        module_path="example.com/acme/comments-go",
    )
    text = _file(package, "examples/threads/main.go")
    assert '\tcomments "example.com/acme/comments-go"' in text


def test_an_example_stops_at_the_call_limit_and_names_the_remainder() -> None:
    count = MAX_EXAMPLE_OPERATIONS + 3
    operations = [_op(f"GET /c{index}", f"op{index}", path=f"/c{index}") for index in range(count)]
    text = _file(_generate(api=_api(operations=operations)), "examples/threads/main.go")
    assert text.count("log.Fatalf") == MAX_EXAMPLE_OPERATIONS
    assert "3 further `Threads` operation(s)" in text


def test_a_group_with_no_http_operations_gets_no_example() -> None:
    services = [Service(key="a", name="Events", operations=[_op("Query.x", "x", method=None, path=None)])]
    package = _generate(api=_api(services=services))
    assert package.example_groups == []
    assert not [path for path in package.file_map() if path.startswith("examples/")]


def test_the_readme_documents_install_operations_and_the_generated_shapes() -> None:
    api = _api(types=[_COMMENT, _STATUS], operations=[_op("GET /comments", "listComments")])
    text = _file(_generate(api=api, module_path="example.com/acme/comments-go"), "README.md")
    assert "go get example.com/acme/comments-go" in text
    assert "| `GET` | `/comments` | `ListComments` |" in text
    assert GO_CLIENT_SCHEMA_VERSION in text


def test_the_readme_names_the_operations_that_got_no_method() -> None:
    operations = [_op("GET /c", "listComments"), _op("Query.things", "things", method=None, path=None)]
    text = _file(_generate(api=_api(operations=operations)), "README.md")
    assert "## Not included" in text
    assert "`Query.things`" in text


# ===========================================================================
# The compile gate
# ===========================================================================

#: A hand-written Go test that drives the generated client against a live `httptest` server. It is
#: the closest a unit test gets to the ticket's "live call against the mock succeeds": a real HTTP
#: round trip over localhost, asserting the wire shape the generated code produced.
_ROUNDTRIP_TEST = '''package comments

import (
\t"context"
\t"encoding/json"
\t"errors"
\t"net/http"
\t"net/http/httptest"
\t"sync"
\t"testing"
)

func TestGeneratedClientRoundTrip(t *testing.T) {
\tvar mu sync.Mutex
\tvar seen *http.Request

\tserver := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
\t\tmu.Lock()
\t\tseen = r.Clone(context.Background())
\t\tmu.Unlock()
\t\tw.Header().Set("Content-Type", "application/json")
\t\tif r.URL.Path == "/comments/abc" {
\t\t\t_ = json.NewEncoder(w).Encode(map[string]any{"id": "abc", "status": "open"})
\t\t\treturn
\t\t}
\t\tw.WriteHeader(http.StatusNotFound)
\t\t_ = json.NewEncoder(w).Encode(map[string]any{"title": "missing"})
\t}))
\tdefer server.Close()

\tclient := NewClient(WithBaseURL(server.URL), WithBearerToken("t0ken"))

\tgot, err := client.GetComment(context.Background(), "abc", &GetCommentParams{
\t\tSession: "s1",
\t\tTags:    []string{"replies"},
\t})
\tif err != nil {
\t\tt.Fatalf("GetComment: %v", err)
\t}
\tif got.ID != "abc" {
\t\tt.Fatalf("id = %q", got.ID)
\t}
\tif got.Status != StatusOpen {
\t\tt.Fatalf("status = %q", got.Status)
\t}

\tmu.Lock()
\treq := seen
\tmu.Unlock()
\tif req.Header.Get("Authorization") != "Bearer t0ken" {
\t\tt.Fatalf("authorization = %q", req.Header.Get("Authorization"))
\t}
\tif req.Header.Get("User-Agent") != DefaultUserAgent {
\t\tt.Fatalf("user-agent = %q", req.Header.Get("User-Agent"))
\t}
\tif req.URL.Query().Get("tags") != "replies" {
\t\tt.Fatalf("query = %q", req.URL.RawQuery)
\t}
\tif cookie, cerr := req.Cookie("session"); cerr != nil || cookie.Value != "s1" {
\t\tt.Fatalf("cookie = %v %v", cookie, cerr)
\t}

\tif _, err = client.GetComment(context.Background(), "nope", nil); err == nil {
\t\tt.Fatal("expected the 404 to be an error")
\t}
\tvar notFound *NotFoundError
\tif !errors.As(err, &notFound) {
\t\tt.Fatalf("expected *NotFoundError, got %#v", err)
\t}
\tif notFound.Payload == nil || notFound.Payload.Title != "missing" {
\t\tt.Fatalf("payload = %#v", notFound.Payload)
\t}
\tif notFound.StatusCode != http.StatusNotFound {
\t\tt.Fatalf("status = %d", notFound.StatusCode)
\t}
\tif _, ok := AsAPIError(err); !ok {
\t\tt.Fatal("AsAPIError did not reach through the typed error")
\t}
}
'''


def _compile_gate_api() -> CanonicalApi:
    """A model exercising every shape the compile gate is meant to catch."""
    return _api(
        types=[_COMMENT, _STATUS, _PROBLEM],
        operations=[
            _op(
                "GET /comments/{id}",
                "getComment",
                path="/comments/{id}",
                description="Fetch one comment",
                extras={"security": ["bearer"]},
                parameters=[
                    _param("id", ParameterLocation.PATH, "uuid", required=True),
                    _param("tags", ParameterLocation.QUERY, list_of="string"),
                    _param("X-Trace", ParameterLocation.HEADER),
                    _param("session", ParameterLocation.COOKIE, required=True),
                ],
                messages=[
                    Message(
                        key="ok",
                        role=MessageRole.RESPONSE,
                        status_code="200",
                        payload=TypeRef(name="Comment"),
                    ),
                    Message(
                        key="nf",
                        role=MessageRole.RESPONSE,
                        status_code="404",
                        payload=TypeRef(name="Problem"),
                    ),
                ],
            ),
            _op(
                "POST /comments",
                "createComment",
                method="post",
                messages=[
                    Message(
                        key="req",
                        role=MessageRole.REQUEST,
                        payload=TypeRef(name="Comment"),
                        content_types=["application/json"],
                    ),
                    Message(
                        key="ok",
                        role=MessageRole.RESPONSE,
                        status_code="201",
                        payload=TypeRef(name="Comment"),
                    ),
                ],
            ),
            _op("DELETE /comments/{id}", "deleteComment", method="delete", path="/comments/{id}"),
            _op("Query.things", "things", method=None, path=None),
        ],
    )


def _go_toolchain() -> Optional[str]:
    """Return the ``go`` binary, or ``None`` when this machine has no toolchain."""
    return shutil.which("go")


@pytest.mark.skipif(_go_toolchain() is None, reason="no Go toolchain on PATH")
def test_the_generated_client_builds_vets_formats_and_answers_a_live_call(tmp_path) -> None:
    """The gate: the generated module is Go, and the Go it is does what the contract said.

    Four checks in one, because they share an expensive setup: ``go build`` proves it compiles
    (which is what an unused import or a recursive value type would break), ``go vet`` proves it is
    not obviously wrong, ``gofmt -l`` proves it is formatted the way Go is written, and ``go test``
    drives it against a live ``httptest`` server so the path, query, cookie, auth header, user-agent,
    JSON decoding and the typed 404 are all exercised over a real HTTP round trip.
    """
    package = generate_go_client(
        _compile_gate_api(),
        module_path="example.com/apiome/comments-go",
        package_name="comments",
        license_header="Copyright (c) 2026 Acme */ Inc.",
        user_agent="acme-sdk/1.0.0",
    )
    module = tmp_path / "module"
    for item in package.files:
        target = module / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.text)
    (module / "roundtrip_test.go").write_text(_ROUNDTRIP_TEST)

    environment = {
        **os.environ,
        "GOPATH": str(tmp_path / "gopath"),
        "GOCACHE": str(tmp_path / "gocache"),
        # The module has no requirements, so nothing needs fetching — and a test that reached the
        # network would fail for reasons that have nothing to do with the generator.
        "GOPROXY": "off",
        "GOFLAGS": "-mod=mod",
    }
    for command in (["build", "./..."], ["vet", "./..."], ["test", "./..."]):
        result = subprocess.run(
            [_go_toolchain(), *command],
            cwd=module,
            capture_output=True,
            text=True,
            env=environment,
        )
        assert result.returncode == 0, f"go {' '.join(command)} failed:\n{result.stdout}{result.stderr}"

    # gofmt ships beside the go binary; a toolchain without it simply does not get this check.
    gofmt_binary = os.path.join(os.path.dirname(_go_toolchain() or ""), "gofmt")
    if os.path.exists(gofmt_binary):
        gofmt = subprocess.run(
            [gofmt_binary, "-l", "."], cwd=module, capture_output=True, text=True, env=environment
        )
        assert gofmt.returncode == 0, gofmt.stderr
        assert gofmt.stdout.strip() == "", f"not gofmt-clean:\n{gofmt.stdout}"
