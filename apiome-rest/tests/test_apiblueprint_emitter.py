"""API Blueprint emitter — MFX-18.1 (#3905).

Covers, in order:

* the document envelope (``FORMAT`` / ``HOST`` metadata first, title, generated comment,
  description) and what it cannot carry (version, extra servers, server variables);
* data structures: records in field-number order with ``required`` members, samples, defaults and
  escaped names; enums, unions, aliases, maps and scalars as named types; MSON-safe names; the MSON
  primitives; constraints dropped;
* resources and actions: path parameters on the resource, query parameters in the action's URI
  template, request and response bodies, statuses, inline schemas;
* what is not carried and reported, by the writer and by :class:`ApiblueprintFidelityRulePack`;
* the refusal for a source with nothing to describe;
* emitted-output validation (:func:`app.export_validation.validate_emitted_artifact`), through the
  API Blueprint reader and through drafter;
* the acceptance check: every API Blueprint corpus file round-trips unchanged, and corpus exports
  from other formats re-parse as API Blueprint (and carry no drafter error when it is present).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

import pytest

from app.apiblueprint_emitter import ApiblueprintEmitOptions, ApiblueprintEmitter, mson_scalar
from app.apiblueprint_import_source import ApiblueprintImportSource
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Constraints,
    EnumValue,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Server,
    ServerVariable,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitPreconditionError, EmitResult, LossKind
from app.export_service import ExportError, emit_canonical
from app.export_validation import validate_emitted_artifact
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import canonical_diff
from app.lossiness import LossinessKind
from app.roundtrip_matrix import reconcile, reimport_emitted

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"


# ===========================================================================
# Helpers
# ===========================================================================


def _api(**kw) -> CanonicalApi:
    """A small model; keyword arguments override its parts."""
    defaults = dict(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="Pets"),
        title="Pets",
        services=[Service(key="default", name="default", operations=kw.pop("operations", []))],
        types=kw.pop("types", []),
    )
    defaults.update(kw)
    return CanonicalApi(**defaults)


def _field(type_key: str, name: str, type_name: str = "string", *, number=None, nullable=False, **kw) -> CanonicalField:
    return CanonicalField(
        key=f"{type_key}.{name}", name=name, type=TypeRef(name=type_name, nullable=nullable), field_number=number, **kw
    )


def _op(method: str, path: str, *, name: str | None = None, **kw) -> Operation:
    key = f"{method} {path}"
    return Operation(
        key=key, name=name or key, kind=OperationKind.REQUEST_RESPONSE, http_method=method, http_path=path, **kw
    )


def _param(op: str, name: str, location: ParameterLocation, type_name: str = "string", **kw) -> Parameter:
    return Parameter(key=f"{op}#{location.value}.{name}", name=name, location=location,
                     type=TypeRef(name=type_name), **kw)


def _response(op: str, status: str | None, payload: str | None = None, **kw) -> Message:
    return Message(key=f"{op}#response.{status}", role=MessageRole.RESPONSE, status_code=status,
                   payload=TypeRef(name=payload) if payload else None, **kw)


def _emit(api: CanonicalApi, **opts) -> EmitResult:
    return ApiblueprintEmitter().emit(api, opts=ApiblueprintEmitOptions(**opts) if opts else None)


def _text(result: EmitResult) -> str:
    return result.files[0].content


def _subjects(result: EmitResult) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for loss in result.losses:
        out.setdefault(loss.subject, []).append(loss.pointer or "")
    return out


def _verdicts(api: CanonicalApi) -> Dict[str, List[LossinessKind]]:
    out: Dict[str, List[LossinessKind]] = {}
    for item in compute_lossiness_for_emitter(api, ApiblueprintEmitter()).items:
        out.setdefault(item.construct_key, []).append(item.kind)
    return out


def _reread(result: EmitResult) -> CanonicalApi:
    return reimport_emitted(ApiblueprintImportSource(), result, multi_file=False)


def _corpus_api(path: Path) -> CanonicalApi:
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    fmt = {".apib": "apiblueprint", ".raml": "raml", ".wadl": "wadl", ".wsdl": "wsdl", ".yaml": "openapi",
           ".proto": "protobuf", ".graphql": "graphql", ".json": "json-schema"}
    return build_conversion_source(
        {"id": "item-1", "name": path.stem, "source_format": fmt[path.suffix],
         "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")}}
    ).api


def _pet() -> Type:
    return Type(key="Pet", name="Pet", kind=TypeKind.RECORD, description="A pet.", fields=[
        _field("Pet", "name", number=2),
        _field("Pet", "id", "double", number=1),
        _field("Pet", "tag", number=3, nullable=True, description="Free-form tag."),
    ])


def _pets_api() -> CanonicalApi:
    list_op = _op("GET", "/pets", name="List pets", description="Every pet.",
                  parameters=[_param("GET /pets", "limit", ParameterLocation.QUERY, "double", required=False,
                                     description="Most to return.")],
                  messages=[Message(key="GET /pets#response.200", role=MessageRole.RESPONSE, status_code="200",
                                    payload=TypeRef(item=TypeRef(name="Pet")), content_types=["application/json"])])
    get_op = _op("GET", "/pets/{id}", name="Get a pet",
                 parameters=[_param("GET /pets/{id}", "id", ParameterLocation.PATH, required=True,
                                    description="Pet id.")],
                 messages=[_response("GET /pets/{id}", "200", "Pet", content_types=["application/json"]),
                           _response("GET /pets/{id}", "404")])
    create = _op("POST", "/pets", name="Add a pet",
                 messages=[Message(key="POST /pets#request", role=MessageRole.REQUEST, payload=TypeRef(name="Pet"),
                                   content_types=["application/json"]),
                           _response("POST /pets", "201", "Pet", content_types=["application/json"])])
    return _api(operations=[list_op, get_op, create], types=[_pet()],
                servers=[Server(url="https://pets.example.com")], description="The pet store.")


# ===========================================================================
# Document
# ===========================================================================


def test_metadata_comes_first_and_the_document_parses() -> None:
    text = _text(_emit(_pets_api()))
    lines = text.splitlines()
    assert lines[:2] == ["FORMAT: 1A", "HOST: https://pets.example.com"]
    assert lines[3] == "# Pets"
    assert "<!-- Generated by Apiome from Pets -->" in lines
    assert "The pet store." in lines
    again = _reread(_emit(_pets_api()))
    assert again.title == "Pets" and again.description == "The pet store."


def test_comment_can_be_left_out() -> None:
    assert "<!--" not in _text(_emit(_pets_api(), include_comments=False))


def test_a_comment_cannot_close_early() -> None:
    api = _pets_api().model_copy(update={"identity": ApiIdentity(name="a --> b")})
    assert "<!-- Generated by Apiome from a -> b -->" in _text(_emit(api))


def test_what_the_envelope_cannot_carry_is_reported() -> None:
    api = _pets_api().model_copy(update={
        "version": "2.0",
        "servers": [Server(url="https://{region}.example.com", variables=[ServerVariable(name="region", default="eu")]),
                    Server(url="https://backup.example.com")],
    })
    subjects = _subjects(_emit(api))
    assert {"version-dropped", "servers-dropped", "server-variables-dropped"} <= set(subjects)
    assert _verdicts(api)[""] == [LossinessKind.APPROX]


def test_a_missing_title_is_synthesized_and_reported() -> None:
    api = _api(title=None, identity=ApiIdentity(name="Shop"), types=[_pet()])
    assert "# Shop" in _text(_emit(api)).splitlines()
    assert "title-synthesized" in _subjects(_emit(api))
    assert LossinessKind.SYNTH in _verdicts(api)[""]


def test_an_api_blueprint_source_keeps_its_own_metadata() -> None:
    api = _api(format="apiblueprint", types=[_pet()], extras={"apib_format_version": "1A9", "apib_host": "/v1"})
    assert _text(_emit(api)).splitlines()[:2] == ["FORMAT: 1A9", "HOST: /v1"]


# ===========================================================================
# Data structures
# ===========================================================================


def test_record_keeps_field_number_order_required_members_and_descriptions() -> None:
    text = _text(_emit(_api(types=[_pet()])))
    block = text.split("# Data Structures\n\n", 1)[1]
    assert block.splitlines()[:6] == [
        "## Pet (object)",
        "",
        "A pet.",
        "",
        "+ id (number, required)",
        "+ name (string, required)",
    ]
    assert "+ tag (string) - Free-form tag." in block


def test_field_numbers_that_are_not_positions_are_reported() -> None:
    api = _api(types=[Type(key="T", name="T", kind=TypeKind.RECORD, fields=[_field("T", "a", number=5)])])
    assert "field-number-dropped" in _subjects(_emit(api))
    assert LossinessKind.DROP in _verdicts(api)["T.a"]


def test_defaults_are_nested_and_read_back_typed() -> None:
    record = Type(key="Page", name="Page", kind=TypeKind.RECORD, fields=[
        _field("Page", "size", "double", number=1, default=20),
        _field("Page", "sort", number=2, default="name asc"),
        _field("Page", "open", "bool", number=3, default=True),
    ])
    text = _text(_emit(_api(types=[record])))
    assert "+ size (number, required)\n    + Default: 20" in text
    assert "    + Default: `name asc`" in text
    again = {f.name: f.default for f in _reread(_emit(_api(types=[record]))).types[0].fields}
    assert again == {"size": 20, "sort": "name asc", "open": True}


def test_a_structured_default_is_not_written_and_is_reported() -> None:
    record = Type(key="T", name="T", kind=TypeKind.RECORD, fields=[_field("T", "tags", number=1, default=["a"])])
    result = _emit(_api(types=[record]))
    assert "Default" not in _text(result)
    assert "default-dropped" in _subjects(result)


def test_property_names_that_are_not_words_are_escaped_and_read_back() -> None:
    record = Type(key="Order", name="Order", kind=TypeKind.RECORD, fields=[_field("Order", "order-id", number=1)])
    result = _emit(_api(types=[record]))
    assert "+ `order-id` (string, required)" in _text(result)
    assert [f.name for f in _reread(result).types[0].fields] == ["order-id"]


def test_enum_union_alias_map_and_scalar_types() -> None:
    types = [
        _pet(),
        Type(key="Status", name="Status", kind=TypeKind.ENUM,
             enum_values=[EnumValue(key="Status.open", name="open", value=0),
                          EnumValue(key="Status.in-flight", name="in flight", value=1)]),
        Type(key="Owner", name="Owner", kind=TypeKind.UNION, union_members=["Pet", "string"]),
        Type(key="PetId", name="PetId", kind=TypeKind.ALIAS, aliased=TypeRef(name="i64")),
        Type(key="Pets", name="Pets", kind=TypeKind.ALIAS, aliased=TypeRef(item=TypeRef(name="Pet"))),
        Type(key="Best", name="Best", kind=TypeKind.ALIAS, aliased=TypeRef(name="Pet")),
        Type(key="Labels", name="Labels", kind=TypeKind.MAP, key_type=TypeRef(name="string"),
             value_type=TypeRef(name="string")),
        Type(key="Instant", name="Instant", kind=TypeKind.SCALAR),
    ]
    result = _emit(_api(types=types))
    text = _text(result)
    for expected in ("## Status (enum)\n+ open\n+ `in flight`",
                     "## Owner (enum)\n+ (Pet)\n+ (string)",
                     "## PetId (number)",
                     "## Pets (array)\n+ (Pet)",
                     "## Best (Pet)",
                     "## Labels (object)",
                     "## Instant (string)"):
        assert expected in text, expected
    subjects = _subjects(result)
    assert {"union-as-enum", "alias-as-named-type", "map-as-object", "scalar-as-named-type"} <= set(subjects)
    again = {t.name: t for t in _reread(result).types}
    assert [v.name for v in again["Status"].enum_values] == ["open", "in flight"]
    verdicts = _verdicts(_api(types=types))
    assert verdicts["Labels"] == [LossinessKind.APPROX]
    assert verdicts["Owner"] == [LossinessKind.DROP]  # the capability rule: no discriminated unions


def test_enum_numbers_and_value_docs_are_reported() -> None:
    enum = Type(key="E", name="E", kind=TypeKind.ENUM,
                enum_values=[EnumValue(key="E.a", name="a", value=7, description="Seven.")])
    assert {"enum-values-dropped", "enum-docs-dropped"} <= set(_subjects(_emit(_api(types=[enum]))))


def test_type_names_are_made_mson_safe_and_unique() -> None:
    types = [
        Type(key="com.acme.Order", name="com.acme.Order", kind=TypeKind.RECORD, fields=[_field("O", "a", number=1)]),
        Type(key="string", name="string", kind=TypeKind.RECORD, fields=[_field("S", "a", number=1)]),
        Type(key="Holder", name="Holder", kind=TypeKind.RECORD,
             fields=[_field("Holder", "order", "com.acme.Order", number=1)]),
    ]
    result = _emit(_api(types=types))
    text = _text(result)
    assert "## com_acme_Order (object)" in text and "## string2 (object)" in text
    assert "+ order (com_acme_Order, required)" in text
    assert "type-renamed" in _subjects(result)
    assert {t.name for t in _reread(result).types} == {"com_acme_Order", "string2", "Holder"}


def test_an_undeclared_or_untyped_value_is_written_as_string_and_reported() -> None:
    record = Type(key="T", name="T", kind=TypeKind.RECORD, fields=[
        _field("T", "x", "Mystery", number=1),
        CanonicalField(key="T.y", name="y", type=TypeRef(), field_number=2),
    ])
    result = _emit(_api(types=[record]))
    assert "+ x (string, required)" in _text(result) and "+ y (string)" in _text(result)
    assert {"unknown-type", "untyped-value"} <= set(_subjects(result))


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("string", ("string", True)),
        ("double", ("number", True)),
        ("bool", ("boolean", True)),
        ("boolean", ("boolean", False)),
        ("i64", ("number", False)),
        ("uint8", ("number", False)),
        ("date-time", ("string", False)),
        ("bytes", ("string", False)),
        ("object", ("object", True)),
    ],
)
def test_mson_scalar(name: str, expected) -> None:
    assert mson_scalar(name) == expected


def test_mson_scalar_unknowns() -> None:
    assert mson_scalar(None) is None
    assert mson_scalar("Pet") is None


def test_widened_scalars_are_reported_but_mson_spellings_are_not() -> None:
    record = Type(key="T", name="T", kind=TypeKind.RECORD,
                  fields=[_field("T", "a", "i32", number=1), _field("T", "b", "boolean", number=2)])
    losses = [loss for loss in _emit(_api(types=[record])).losses if loss.subject == "scalar-widened"]
    assert [loss.pointer for loss in losses] == ["T.a"]


def test_constraints_are_dropped_by_the_writer_and_the_rule_pack() -> None:
    record = Type(key="T", name="T", kind=TypeKind.RECORD, fields=[
        _field("T", "code", number=1, constraints=Constraints(pattern="^[A-Z]+$", max_length=8)),
    ])
    api = _api(types=[record])
    result = _emit(api)
    assert "pattern" not in _text(result) and "8" not in _text(result)
    loss = next(loss for loss in result.losses if loss.subject == "constraints-dropped")
    assert loss.kind is LossKind.NA and "max_length, pattern" in loss.detail
    assert LossinessKind.DROP in _verdicts(api)["T.code"]


# ===========================================================================
# Resources and actions
# ===========================================================================


def test_resources_actions_parameters_and_bodies() -> None:
    text = _text(_emit(_pets_api()))
    assert text.index("## Pets [/pets]") < text.index("## Pets [/pets/{id}]")
    assert "### List pets [GET /pets{?limit}]\n\nEvery pet.\n\n+ Parameters\n" \
           "    + limit (number, optional) - Most to return." in text
    assert "+ Response 200 (application/json)\n    + Attributes (array[Pet])" in text
    assert "## Pets [/pets/{id}]\n\n+ Parameters\n    + id (string, required) - Pet id." in text
    assert "+ Request (application/json)\n    + Attributes (Pet)" in text
    assert "+ Response 404\n" in text


def test_the_reader_reads_the_actions_back() -> None:
    again = {op.key: op for op in _reread(_emit(_pets_api())).operations()}
    assert set(again) == {"GET /pets", "GET /pets/{id}", "POST /pets"}
    listing = again["GET /pets"]
    assert listing.name == "List pets" and listing.description == "Every pet."
    limit = listing.parameters[0]
    assert (limit.name, limit.location, limit.required, limit.type.name) == (
        "limit", ParameterLocation.QUERY, False, "double"
    )
    response = listing.messages[0]
    assert response.status_code == "200" and response.payload.item.name == "Pet"
    assert [m.status_code for m in again["GET /pets/{id}"].messages] == ["200", "404"]


def test_a_clean_api_blueprint_shape_reports_only_the_document() -> None:
    api = _pets_api().model_copy(update={"format": "apiblueprint"})
    assert _subjects(_emit(api)) == {}


def test_dropped_operations_and_channels_are_reported() -> None:
    api = _api(
        operations=[
            _op("GET", "/a", name="first"),
            _op("GET", "/a", name="second").model_copy(update={"key": "second"}),
            Operation(key="rpc", name="rpc", kind=OperationKind.REQUEST_RESPONSE),
            Operation(key="evt", name="evt", kind=OperationKind.PUBLISH, http_method="POST", http_path="/e"),
        ],
        channels=[Channel(key="orders", name="orders", address="orders")],
    )
    result = _emit(api)
    dropped = _subjects(result)["operation-dropped"]
    assert set(dropped) == {"second", "rpc", "evt"}
    assert "channel-dropped" in _subjects(result)
    verdicts = _verdicts(api)
    assert verdicts["second"] == [LossinessKind.DROP] and verdicts["rpc"] == [LossinessKind.DROP]
    assert _text(result).count("### ") == 1


def test_operation_losses_are_reported() -> None:
    op = _op(
        "GET", "/a", name="Get [a]", deprecated=True, tags=["x"],
        parameters=[_param("GET /a", "X-Trace", ParameterLocation.HEADER),
                    _param("GET /a", "session", ParameterLocation.COOKIE),
                    _param("GET /a", "q", ParameterLocation.QUERY, constraints=Constraints(min_length=2))],
        messages=[_response("GET /a", "4XX"), _response("GET /a", "200", "string", description="OK",
                                                         headers=[_field("h", "ETag")]),
                  _response("GET /a", "200").model_copy(update={"key": "dup"})],
        extras={"x_vendor": 1},
    )
    api = _api(operations=[op])
    result = _emit(api)
    assert {
        "parameter-dropped", "constraints-dropped", "status-range-dropped", "headers-dropped",
        "response-description-dropped", "response-dropped", "operation-renamed", "deprecated-dropped",
        "tags-dropped", "operation-details-dropped",
    } <= set(_subjects(result))
    assert "### Get a [GET /a{?q}]" in _text(result)
    assert _verdicts(api)["GET /a"] == [LossinessKind.APPROX]


def test_a_response_with_no_status_is_written_as_200_and_a_request_gets_a_media_type() -> None:
    op = _op("POST", "/a", messages=[
        Message(key="POST /a#request", role=MessageRole.REQUEST, payload=TypeRef(name="string")),
        Message(key="POST /a#response", role=MessageRole.RESPONSE),
    ])
    result = _emit(_api(operations=[op]))
    assert "+ Request (application/json)" in _text(result) and "+ Response 200\n" in _text(result)
    assert {"status-synthesized", "media-type-synthesized"} <= set(_subjects(result))
    assert "+ Request (text/plain)" in _text(_emit(_api(operations=[op]), media_type="text/plain"))


def test_path_parameters_are_declared_once_per_resource() -> None:
    ops = [
        _op("GET", "/a/{id}", parameters=[_param("GET /a/{id}", "id", ParameterLocation.PATH, required=True)]),
        _op("PUT", "/a/{id}", parameters=[_param("PUT /a/{id}", "id", ParameterLocation.PATH, "double",
                                                 required=True)]),
    ]
    result = _emit(_api(operations=ops))
    assert _text(result).count("+ id (") == 1
    assert _subjects(result)["parameter-merged"] == ["PUT /a/{id}"]


def test_a_path_parameter_the_template_lacks_is_written_on_its_action() -> None:
    op = _op("GET", "/a", parameters=[_param("GET /a", "page", ParameterLocation.PATH, "double", required=False)])
    text = _text(_emit(_api(operations=[op])))
    assert "### GET /a [GET]\n\n+ Parameters\n    + page (number, optional)" in text


def test_parameter_defaults_are_nested() -> None:
    op = _op("GET", "/a", parameters=[_param("GET /a", "limit", ParameterLocation.QUERY, "double", default=10)])
    result = _emit(_api(operations=[op]))
    assert "    + limit (number, optional)\n        + Default: 10" in _text(result)
    assert _reread(result).operations()[0].parameters[0].default == 10


def test_an_inline_schema_body_is_a_schema_section() -> None:
    op = _op("GET", "/a", messages=[
        Message(key="GET /a#response.200", role=MessageRole.RESPONSE, status_code="200",
                payload_schema={"type": "object"}, content_types=["application/json"]),
    ])
    result = _emit(_api(operations=[op]))
    assert "    + Schema\n\n            {\n              \"type\": \"object\"\n            }" in _text(result)
    assert "inline-schema" in _subjects(result)


def test_a_path_without_a_slash_gets_one() -> None:
    assert "## A [/a]" in _text(_emit(_api(operations=[_op("GET", "a")])))


def test_source_details_and_services_are_reported() -> None:
    api = _pets_api().model_copy(update={"extras": {"x": 1}, "identity": ApiIdentity(name="pets", namespace="acme")})
    assert {"document-details-dropped", "identity-dropped", "services-merged"} <= set(_subjects(_emit(api)))


def test_a_source_with_nothing_to_describe_is_refused() -> None:
    api = _api(operations=[Operation(key="rpc", name="rpc", kind=OperationKind.REQUEST_RESPONSE)])
    with pytest.raises(EmitPreconditionError):
        _emit(api)
    with pytest.raises(ExportError) as excinfo:
        emit_canonical(api, "apiblueprint")
    assert excinfo.value.status_code == 422
    assert "needs at least one HTTP operation or one type" in str(excinfo.value)


def test_types_alone_are_enough() -> None:
    assert "## Pet (object)" in _text(emit_canonical(_api(types=[_pet()]), "apiblueprint"))


# ===========================================================================
# Emitted-output validation
# ===========================================================================


@pytest.fixture
def no_drafter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.apiblueprint_drafter.drafter_available", lambda: False)


async def test_validation_reparses_without_drafter(no_drafter) -> None:
    api = _pets_api()
    verdict = await validate_emitted_artifact("apiblueprint", _emit(api), api=api)
    assert (verdict.applicable, verdict.validated, verdict.valid) == (True, True, True)


async def test_validation_rejects_a_broken_document_without_drafter(no_drafter) -> None:
    api = _pets_api()
    result = _emit(api)
    not_a_blueprint = result.files[0].model_copy(update={"content": "# Not a blueprint\n"})
    broken = result.model_copy(update={"files": [not_a_blueprint]})
    verdict = await validate_emitted_artifact("apiblueprint", broken, api=api)
    assert verdict.failed
    assert verdict.findings[0].file == "Pets.apib"


async def test_drafter_errors_reject_and_warnings_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _pets_api()
    result = _emit(api)
    monkeypatch.setattr("app.apiblueprint_drafter.drafter_available", lambda: True)
    reports = {
        "warning": [{"severity": "warning", "code": 6, "message": "action is missing a response"}],
        "error": [{"severity": "error", "code": 4, "message": "base type 'X' is not defined", "line": 9,
                   "column": 1}],
    }
    for name, report in reports.items():
        monkeypatch.setattr("app.apiblueprint_drafter.run_drafter", lambda text, r=report: r)
        verdict = await validate_emitted_artifact("apiblueprint", result, api=api)
        if name == "warning":
            assert verdict.valid and verdict.validated
        else:
            assert verdict.failed
            finding = verdict.findings[0]
            assert (finding.message, finding.file, finding.line, finding.column, finding.keyword) == (
                "base type 'X' is not defined", "Pets.apib", 9, 1, "4"
            )


# ===========================================================================
# Acceptance: API Blueprint round trips; other formats export to API Blueprint that re-parses
# ===========================================================================

_APIB_CORPUS = sorted((_EXAMPLES / "api-blueprint").glob("*.apib"))


@pytest.mark.parametrize("path", _APIB_CORPUS, ids=lambda p: p.name)
def test_api_blueprint_corpus_round_trips(path: Path) -> None:
    api = _corpus_api(path)
    result = _emit(api)
    assert result.losses == []
    diff = canonical_diff(api, _reread(result))
    assert diff.entries == []
    outcome = reconcile(diff, compute_lossiness_for_emitter(api, ApiblueprintEmitter()))
    assert outcome.ok


_CORPUS = [
    _EXAMPLES / "openapi" / "07-nullable-types.yaml",
    _EXAMPLES / "openapi" / "22-advanced-oneof-polymorphism.yaml",
    _EXAMPLES / "openapi" / "30-openapi-3.0-petstore.yaml",
    _EXAMPLES / "protobuf" / "02-grpc-service.proto",
    _EXAMPLES / "graphql" / "06-union-types.graphql",
    _EXAMPLES / "wsdl" / "02-order-service.wsdl",
    _EXAMPLES / "raml" / "01-simple-api.raml",
]


@pytest.mark.parametrize("path", _CORPUS, ids=lambda p: p.name)
async def test_corpus_export_reparses_as_api_blueprint(path: Path, no_drafter) -> None:
    api = _corpus_api(path)
    result = emit_canonical(api, "apiblueprint")
    assert re.match(r"FORMAT: 1A\n", result.files[0].content)
    verdict = await validate_emitted_artifact("apiblueprint", result, api=api)
    assert verdict.validated and verdict.valid, verdict.errors
    # Every loss the writer reports concerns something the fidelity report also names.
    report_keys = {item.construct_key for item in compute_lossiness_for_emitter(api, ApiblueprintEmitter()).items
                   if item.kind is not LossinessKind.OK}
    for loss in result.losses:
        assert loss.pointer in report_keys or loss.pointer.rsplit(".", 1)[0] in report_keys, loss


@pytest.mark.parametrize("path", [*_CORPUS, *_APIB_CORPUS], ids=lambda p: p.name)
def test_corpus_export_has_no_drafter_errors(path: Path) -> None:
    from app.apiblueprint_drafter import drafter_available, run_drafter

    if not drafter_available():
        pytest.skip("the drafter toolchain is not available here")
    emitted = emit_canonical(_corpus_api(path), "apiblueprint").files[0]
    assert [a for a in run_drafter(emitted.content) if a["severity"] == "error"] == []
