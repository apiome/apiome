"""Cap'n Proto schema emitter — MFX-30.2 (#4179).

Covers, in order:

* :mod:`app.capnproto_names` — the compiler's naming rules;
* :mod:`app.capnproto_identity` — file ids and the ordinal allocator (contiguous, stable, retired
  members kept as placeholders of the same layout);
* :class:`app.capnproto_emitter.CapnpEmitter` — every canonical kind, and stability across
  re-exports through the field-identity store;
* the export-service wiring (``capnproto`` store key) and the export validator;
* the acceptance check — the emitted ``.capnp`` compiles under ``capnp`` (when it is installed;
  the image bundles it, locally point ``APIOME_CAPNP_BIN`` at a binary).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock, patch

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
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.capnproto_compile import (
    CAPNP_TOOL_KEY,
    CapnpCompileError,
    CapnpFile,
    compile_capnp_schema,
)
from app.capnproto_emitter import CapnpEmitOptions, CapnpEmitter
from app.capnproto_identity import (
    FILE_ID_KEY,
    Layout,
    OrdinalAllocator,
    file_id_from_store,
    file_id_to_store,
    format_file_id,
    layout_key,
    parse_file_id,
    synthesize_file_id,
)
from app.capnproto_names import NameScope, member_identifier, type_identifier
from app.capnproto_normalizer import CapnpNormalizer
from app.capnproto_parser import parse_capnproto
from app.catalog_conversion import build_conversion_source
from app.emitter import LossKind
from app.export_service import ExportPersistenceContext, emit_canonical
from app.export_validation import validate_emitted_artifact
from app.toolchain_packaging import probe_tool

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_CAPNP_AVAILABLE = bool(getattr(probe_tool(CAPNP_TOOL_KEY), "available", False))
_needs_capnp = pytest.mark.skipif(
    not _CAPNP_AVAILABLE, reason="capnp is not resolvable here (bundled in the image)"
)


# ===========================================================================
# Helpers
# ===========================================================================


def _field(name: str, type_name: str | None = None, *, fmt: str | None = None, **kw) -> CanonicalField:
    return CanonicalField(
        key=f"User.{name}",
        name=name,
        type=kw.pop("ref", None) or TypeRef(name=type_name),
        constraints=Constraints(format=fmt) if fmt else None,
        **kw,
    )


def _api(types: List[Type], services: List[Service] = (), *, name: str = "Users") -> CanonicalApi:
    return CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format="openapi",
        identity=ApiIdentity(name=name),
        types=list(types),
        services=list(services),
    )


def _user(*fields: CanonicalField) -> Type:
    return Type(key="User", name="User", kind=TypeKind.RECORD, fields=list(fields))


def _emit(api: CanonicalApi, store: Dict[str, int] | None = None):
    """Emit with ``store`` as the persisted map, then write the new rows back into it."""
    result = CapnpEmitter().emit(
        api, opts=CapnpEmitOptions(persisted_field_numbers=dict(store or {}))
    )
    if store is not None:
        store.update(result.field_identity_assignments)
    return result


def _text(result) -> str:
    return str(result.files[0].content)


def _block(text: str, keyword: str, name: str) -> str:
    """The body of ``<keyword> <name> { … }`` (top-level, no nested braces)."""
    match = re.search(rf"^{keyword} {name} \{{\n(.*?)^\}}", text, re.MULTILINE | re.DOTALL)
    assert match, f"{keyword} {name} not found in:\n{text}"
    return match.group(1)


def _ordinals(text: str, keyword: str, name: str) -> Dict[str, int]:
    """``member → @N`` for every member line of a top-level declaration."""
    return {
        m.group(1): int(m.group(2))
        for m in re.finditer(r"^\s+(\w+) @(\d+)", _block(text, keyword, name), re.MULTILINE)
    }


def _openapi_api(path: Path) -> CanonicalApi:
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {
            "id": "item-1",
            "name": path.stem,
            "source_format": "openapi",
            "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")},
        }
    ).api


def _capnp_api(name: str) -> CanonicalApi:
    text = (_EXAMPLES / "capnproto" / name).read_text(encoding="utf-8")
    return CapnpNormalizer().normalize(parse_capnproto(text))


# ===========================================================================
# app.capnproto_names
# ===========================================================================


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Pet", "Pet"),
        ("pet_store", "PetStore"),
        ("HTTP_ERROR", "HttpError"),
        ("HTTPError", "HTTPError"),
        ("order-line", "OrderLine"),
        ("2xx", "T2xx"),
        ("Text", "TextType"),  # never shadow a built-in
        ("List", "ListType"),
        ("___", "Type"),
    ],
)
def test_type_identifier(raw: str, expected: str) -> None:
    assert type_identifier(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("name", "name"),
        ("first_name", "firstName"),
        ("Name", "name"),
        ("ID", "id"),
        ("HTTPCode", "httpCode"),
        ("ACTIVE", "active"),
        ("STATUS_UNSPECIFIED", "statusUnspecified"),
        ("X-Request-ID", "xRequestId"),
        ("in-stock", "inStock"),
        ("2xx", "v2xx"),
        ("", "field"),
    ],
)
def test_member_identifier(raw: str, expected: str) -> None:
    assert member_identifier(raw) == expected


def test_name_scope_suffixes_repeats() -> None:
    scope = NameScope()
    assert [scope.claim("firstName") for _ in range(3)] == ["firstName", "firstName2", "firstName3"]


# ===========================================================================
# app.capnproto_identity — file ids
# ===========================================================================


def test_synthesized_file_id_is_valid_and_deterministic() -> None:
    first = synthesize_file_id("acme/Users")
    assert first == synthesize_file_id("acme/Users")
    assert first != synthesize_file_id("acme/Orders")
    assert first >> 63 == 1  # capnp refuses an id without its top bit
    assert parse_file_id(format_file_id(first)) == first


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0xbf5147cbbecf40c1", 0xBF5147CBBECF40C1),
        ("@0xbf5147cbbecf40c1", 0xBF5147CBBECF40C1),
        ("bf5147cbbecf40c1", 0xBF5147CBBECF40C1),
        ("0x0f5147cbbecf40c1", None),  # top bit clear
        ("0xnothex", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_file_id(value, expected) -> None:
    assert parse_file_id(value) == expected


def test_file_id_store_round_trip_fits_a_signed_bigint() -> None:
    file_id = synthesize_file_id("x")
    stored = file_id_to_store(file_id)
    assert 0 <= stored < 2**63
    assert file_id_from_store(stored) == file_id
    assert file_id_from_store(-1) is None
    assert file_id_from_store("1") is None
    with pytest.raises(ValueError):
        file_id_to_store(5)


# ===========================================================================
# app.capnproto_identity — OrdinalAllocator
# ===========================================================================


def _allocate(names: List[str], store: Dict[str, int], *, scope: str = "User", **sources):
    allocator = OrdinalAllocator(scope, store)
    for name in names:
        allocator.add(name, name, source_ordinal=sources.get(name), layout=Layout.POINTER)
    slots = allocator.finish()
    store.update(allocator.new_assignments)
    return slots, allocator.new_assignments


def test_allocator_numbers_from_zero_in_declaration_order() -> None:
    slots, new = _allocate(["a", "b", "c"], {})
    assert [(s.ordinal, s.name) for s in slots] == [(0, "a"), (1, "b"), (2, "c")]
    assert all(s.synthesized for s in slots)
    assert new == {
        "User.a": 0,
        "User.b": 1,
        "User.c": 2,
        layout_key("User.a"): int(Layout.POINTER),
        layout_key("User.b"): int(Layout.POINTER),
        layout_key("User.c"): int(Layout.POINTER),
    }


def test_allocator_reuses_stored_ordinals_and_appends_new_members() -> None:
    store: Dict[str, int] = {}
    _allocate(["a", "b"], store)
    slots, new = _allocate(["c", "b", "a"], store)  # reordered, plus a new member
    assert {s.name: s.ordinal for s in slots} == {"a": 0, "b": 1, "c": 2}
    assert new == {"User.c": 2, layout_key("User.c"): int(Layout.POINTER)}


def test_allocator_keeps_a_removed_members_ordinal_as_a_placeholder() -> None:
    store: Dict[str, int] = {}
    _allocate(["a", "b", "c"], store)
    slots, new = _allocate(["a", "c", "d"], store)
    by_ordinal = {s.ordinal: s for s in slots}
    assert by_ordinal[1].placeholder and by_ordinal[1].retired and by_ordinal[1].name == "b"
    assert by_ordinal[1].layout is Layout.POINTER
    assert by_ordinal[3].name == "d"  # never reuses the retired @1
    assert "User.d" in new and "User.b" not in new


def test_allocator_prefers_source_ordinals_and_fills_their_gaps() -> None:
    slots, new = _allocate(["a", "b"], {}, a=0, b=2)
    assert [(s.ordinal, s.name, s.placeholder) for s in slots] == [
        (0, "a", False),
        (1, "reserved1", True),
        (2, "b", False),
    ]
    assert not slots[0].synthesized
    assert new == {}  # source ordinals are never stored


def test_allocator_replaces_a_stored_ordinal_the_source_now_uses() -> None:
    store = {"User.b": 0}
    slots, new = _allocate(["a", "b"], store, a=0)
    assert {s.name: s.ordinal for s in slots} == {"a": 0, "b": 1}
    assert new["User.b"] == 1


def test_allocator_ignores_rows_of_a_nested_scope() -> None:
    store = {"User.a": 0, "User.Address.street": 1}
    slots, _ = _allocate(["a"], store)
    assert [s.name for s in slots] == ["a"]  # Address's row is not a retired User member


def test_allocator_ignores_out_of_range_stored_ordinals() -> None:
    """A corrupt row (beyond Cap'n Proto's 16-bit ordinals) never produces a run of placeholders."""
    slots, new = _allocate(["a"], {"User.a": 2**40, "User.gone": 70_000, "User.neg": -1})
    assert [(s.ordinal, s.name) for s in slots] == [(0, "a")]
    assert new["User.a"] == 0


def test_allocator_records_a_changed_layout() -> None:
    store: Dict[str, int] = {}
    allocator = OrdinalAllocator("User", store)
    allocator.add("a", "a", layout=Layout.BITS32)
    allocator.finish()
    store.update(allocator.new_assignments)
    allocator = OrdinalAllocator("User", store)
    allocator.add("a", "a", layout=Layout.BITS64)
    allocator.finish()
    assert allocator.new_assignments == {layout_key("User.a"): int(Layout.BITS64)}


# ===========================================================================
# CapnpEmitter — output per kind
# ===========================================================================


def test_record_fields_get_contiguous_ordinals_and_capnp_types() -> None:
    api = _api(
        [
            _user(
                _field("id", "integer", fmt="int64"),
                _field("first_name", "string"),
                _field("age", "integer"),
                _field("score", "number"),
                _field("active", "boolean"),
                _field("tags", ref=TypeRef(item=TypeRef(name="string"))),
                _field("blob", "bytes"),
            )
        ]
    )
    text = _text(_emit(api))
    body = _block(text, "struct", "User")
    assert body.splitlines() == [
        "  id @0 :Int64;",
        "  firstName @1 :Text;",
        "  age @2 :Int32;",
        "  score @3 :Float64;",
        "  active @4 :Bool;",
        "  tags @5 :List(Text);",
        "  blob @6 :Data;",
    ]
    assert re.search(r"^@0x[0-9a-f]{16};$", text, re.MULTILINE)


def test_enum_values_become_lower_camel_enumerants() -> None:
    status = Type(
        key="Status",
        name="status",
        kind=TypeKind.ENUM,
        enum_values=[
            EnumValue(key="Status.ACTIVE", name="ACTIVE", value="active"),
            EnumValue(key="Status.in-review", name="in-review"),
            EnumValue(key="Status.ON_HOLD", name="ON_HOLD", value=7),
        ],
    )
    text = _text(_emit(_api([_user(_field("status", "Status")), status])))
    assert _ordinals(text, "enum", "Status") == {"active": 0, "inReview": 1, "onHold": 2}
    assert "status @0 :Status;" in text


def test_union_becomes_a_struct_holding_an_unnamed_union() -> None:
    card = Type(key="Card", name="Card", kind=TypeKind.RECORD)
    bank = Type(key="BankAccount", name="BankAccount", kind=TypeKind.RECORD)
    method = Type(
        key="PaymentMethod",
        name="PaymentMethod",
        kind=TypeKind.UNION,
        union_members=["Card", "BankAccount", "string"],
    )
    text = _text(_emit(_api([card, bank, method])))
    assert (
        "struct PaymentMethod {\n  union {\n    card @0 :Card;\n    bankAccount @1 :BankAccount;\n"
        "    text @2 :Text;\n  }\n}" in text
    )


def test_single_variant_union_is_a_plain_struct_with_a_loss() -> None:
    card = Type(key="Card", name="Card", kind=TypeKind.RECORD)
    only = Type(key="OnlyCard", name="OnlyCard", kind=TypeKind.UNION, union_members=["Card"])
    result = _emit(_api([card, only]))
    assert "struct OnlyCard {\n  card @0 :Card;\n}" in _text(result)
    assert any(loss.subject == "single-member-union" for loss in result.losses)


def test_map_alias_and_scalar_types() -> None:
    labels = Type(
        key="Labels",
        name="Labels",
        kind=TypeKind.MAP,
        key_type=TypeRef(name="string"),
        value_type=TypeRef(name="integer"),
    )
    alias = Type(key="Names", name="Names", kind=TypeKind.ALIAS, aliased=TypeRef(item=TypeRef(name="string")))
    email = Type(key="email", name="email", kind=TypeKind.SCALAR)
    # A named scalar whose spelling plus format picks the width (``integer`` + ``int64``).
    wide = Type(
        key="Wide", name="integer", kind=TypeKind.SCALAR, constraints=Constraints(format="int64")
    )
    text = _text(_emit(_api([labels, alias, email, wide])))
    assert "struct Labels {\n  entries @0 :List(Entry);\n\n  struct Entry {\n    key @0 :Text;" in text
    assert "    value @1 :Int32;" in text
    assert "using Names = List(Text);" in text
    assert "using Email = Text;" in text
    assert "using Integer = Int64;" in text


def test_names_are_renamed_to_the_compiler_rules_and_kept_unique() -> None:
    text_type = Type(key="Text", name="Text", kind=TypeKind.RECORD, fields=[_field("x", "string")])
    api = _api(
        [
            _user(
                _field("first_name", "string"),
                _field("firstName", "string"),
                _field("body", "Text"),
            ),
            text_type,
        ]
    )
    text = _text(_emit(api))
    assert _ordinals(text, "struct", "User") == {"firstName": 0, "firstName2": 1, "body": 2}
    assert "body @2 :TextType;" in text
    assert "struct TextType {" in text


def test_untyped_values_and_lists_of_them() -> None:
    api = _api([_user(_field("data", ref=TypeRef()), _field("items", ref=TypeRef(item=TypeRef())))])
    result = _emit(api)
    assert "data @0 :AnyPointer;" in _text(result)
    assert "items @1 :AnyList;" in _text(result)  # List(AnyPointer) does not compile
    assert any(loss.subject == "untyped-value" for loss in result.losses)


def test_unknown_type_names_become_text_with_a_loss() -> None:
    result = _emit(_api([_user(_field("when", "date-time"))]))
    assert "when @0 :Text;" in _text(result)
    assert any(loss.subject == "unmapped-type" for loss in result.losses)


def _pet_service() -> Service:
    get_pet = Operation(
        key="GET /pets/{petId}",
        name="getPetById",
        kind=OperationKind.REQUEST_RESPONSE,
        parameters=[
            Parameter(
                key="GET /pets/{petId}#path.petId",
                name="petId",
                location=ParameterLocation.PATH,
                type=TypeRef(name="integer"),
                constraints=Constraints(format="int64"),
            )
        ],
        messages=[
            Message(key="GET#response.200", role=MessageRole.RESPONSE, payload=TypeRef(name="User")),
            Message(key="GET#response.404", role=MessageRole.ERROR),
        ],
    )
    create = Operation(
        key="POST /pets",
        name="POST /pets",
        kind=OperationKind.REQUEST_RESPONSE,
        messages=[Message(key="POST#request", role=MessageRole.REQUEST, payload=TypeRef(name="User"))],
    )
    event = Operation(key="petAdded", name="petAdded", kind=OperationKind.PUBLISH)
    return Service(key="default", name="default", operations=[get_pet, create, event])


def test_services_become_interfaces_with_numbered_methods() -> None:
    result = _emit(_api([_user(_field("id", "string"))], [_pet_service()]))
    text = _text(result)
    assert _block(text, "interface", "Default").splitlines() == [
        "  getPetById @0 (petId :Int64) -> (result :User);",
        "  postPets @1 (arg :User) -> ();",
    ]
    subjects = {loss.subject for loss in result.losses}
    assert {"errors-dropped", "event-operation-dropped"} <= subjects


def test_capability_profile_supports_unions_and_field_identity() -> None:
    profile = CapnpEmitter.capability_profile()
    assert profile.unions and profile.field_identity and not profile.events


# ===========================================================================
# CapnpEmitter — stability across re-exports (the acceptance criterion)
# ===========================================================================


def _user_api(*names: str) -> CanonicalApi:
    kinds = {"id": "integer", "name": "string", "email": "string", "age": "integer", "nick": "string"}
    return _api([_user(*[_field(n, kinds[n]) for n in names])])


def test_re_export_is_byte_identical_and_persists_nothing_new() -> None:
    store: Dict[str, int] = {}
    first = _emit(_user_api("id", "name", "email"), store)
    assert FILE_ID_KEY in first.field_identity_assignments
    second = _emit(_user_api("id", "name", "email"), store)
    assert _text(second) == _text(first)
    assert second.field_identity_assignments == {}


def test_file_id_is_stable_even_when_the_api_is_renamed() -> None:
    store: Dict[str, int] = {}
    first = _text(_emit(_user_api("id"), store))
    renamed = _api([_user(_field("id", "integer"))], name="Customers")
    second = _text(_emit(renamed, store))
    file_id = re.compile(r"^@(0x[0-9a-f]{16});$", re.MULTILINE)
    assert file_id.search(first).group(1) == file_id.search(second).group(1)
    assert file_id_from_store(store[FILE_ID_KEY]) == parse_file_id(file_id.search(first).group(1))


def test_reordering_and_adding_fields_keeps_ordinals() -> None:
    store: Dict[str, int] = {}
    _emit(_user_api("id", "name"), store)
    text = _text(_emit(_user_api("email", "name", "id"), store))
    assert _ordinals(text, "struct", "User") == {"id": 0, "name": 1, "email": 2}


def test_removed_field_keeps_its_ordinal_and_layout() -> None:
    store: Dict[str, int] = {}
    _emit(_user_api("id", "age", "name"), store)  # id :Int32 @0, age :Int32 @1, name :Text @2
    result = _emit(_user_api("id", "name", "nick"), store)
    text = _text(result)
    assert _block(text, "struct", "User").splitlines() == [
        "  id @0 :Int32;",
        "  obsoleteAge @1 :UInt32;",  # same 32-bit slot, so name and nick keep their offsets
        "  name @2 :Text;",
        "  nick @3 :Text;",
    ]
    retired = [loss for loss in result.losses if loss.subject == "retired-ordinal"]
    assert len(retired) == 1 and retired[0].pointer == "User.age"


def test_removed_enum_value_and_method_keep_their_ordinals() -> None:
    def api(values: List[str], methods: List[str]) -> CanonicalApi:
        status = Type(
            key="Status",
            name="Status",
            kind=TypeKind.ENUM,
            enum_values=[EnumValue(key=f"Status.{v}", name=v) for v in values],
        )
        ops = [Operation(key=m, name=m, kind=OperationKind.REQUEST_RESPONSE) for m in methods]
        return _api([status], [Service(key="Svc", name="Svc", operations=ops)])

    store: Dict[str, int] = {}
    _emit(api(["a", "b", "c"], ["get", "put"]), store)
    text = _text(_emit(api(["a", "c"], ["put"]), store))
    assert _ordinals(text, "enum", "Status") == {"a": 0, "obsoleteB": 1, "c": 2}
    assert _block(text, "interface", "Svc").splitlines() == [
        "  obsoleteGet @0 () -> ();",
        "  put @1 () -> ();",
    ]


def test_synthesized_ordinals_are_reported_as_inferred() -> None:
    result = _emit(_user_api("id"))
    losses = [loss for loss in result.losses if loss.subject == "synthesized-ordinal"]
    assert losses and losses[0].kind is LossKind.INFERRED and losses[0].pointer == "User.id"
    assert any(loss.subject == "synthesized-file-id" for loss in result.losses)


# ===========================================================================
# CapnpEmitter — a .capnp source keeps its own numbers
# ===========================================================================


def test_capnp_source_keeps_its_file_id_ordinals_and_nesting() -> None:
    result = _emit(_capnp_api("01-address-book.capnp"), {})
    text = _text(result)
    assert "@0xbf5147cbbecf40c1;" in text
    assert _ordinals(text, "struct", "Date") == {"year": 0, "month": 1, "day": 2}
    assert "  phones @3 :List(Person.PhoneNumber);" in text
    assert "\n  struct PhoneNumber {\n    number @0 :Text;\n    type @1 :Person.PhoneNumber.Type;" in text
    assert "    enum Type {\n      mobile @0;\n      home @1;\n      work @2;\n    }" in text
    assert "  lookup @0 (id :UInt32) -> (person :Person);" in text
    assert result.field_identity_assignments == {}  # nothing synthesized, nothing to store


def test_capnp_source_imports_use_valid_syntax() -> None:
    text = _text(_emit(_capnp_api("03-invoice-imports.capnp")))
    assert 'using Shared = import "shared.capnp";' in text
    assert "@import" not in text


def test_capnp_source_method_gap_is_filled() -> None:
    """The parser drops one of 04's methods; the gap is filled so the interface still compiles."""
    result = _emit(_capnp_api("04-event-stress.capnp"))
    ordinals = _ordinals(_text(result), "interface", "Collector")
    assert sorted(ordinals.values()) == list(range(len(ordinals)))
    if len(ordinals) > 2:
        assert any(loss.subject == "ordinal-gap" for loss in result.losses)


# ===========================================================================
# Export service and validator wiring
# ===========================================================================


@patch("app.export_service.load_persisted_field_numbers")
@patch("app.export_service.persist_field_number_assignments")
def test_emit_canonical_loads_and_persists_under_the_capnproto_key(
    mock_persist: MagicMock, mock_load: MagicMock
) -> None:
    stored_id = synthesize_file_id("stored")
    mock_load.return_value = {"User.id": 0, FILE_ID_KEY: file_id_to_store(stored_id)}
    result = emit_canonical(
        _user_api("id", "name"),
        "capnproto",
        opts={"include_comments": False},
        persistence=ExportPersistenceContext(tenant_id="tenant-1", artifact_id="project-1"),
    )
    text = _text(result)
    assert text.startswith(f"@{format_file_id(stored_id)};")
    mock_load.assert_called_once_with("tenant-1", "project-1", "capnproto")
    mock_persist.assert_called_once_with(
        "tenant-1",
        "project-1",
        "capnproto",
        {
            "User.name": 1,
            layout_key("User.id"): int(Layout.BITS32),
            layout_key("User.name"): int(Layout.POINTER),
        },
    )


async def test_validator_skips_when_capnp_is_unavailable() -> None:
    api = _user_api("id")
    with patch(
        "app.capnproto_compile.compile_capnp_schema",
        side_effect=CapnpCompileError("missing", unavailable=True),
    ):
        verdict = await validate_emitted_artifact("capnproto", _emit(api), api=api)
    assert verdict.applicable and not verdict.validated and not verdict.failed


async def test_validator_skips_a_schema_with_imports() -> None:
    api = _capnp_api("03-invoice-imports.capnp")
    verdict = await validate_emitted_artifact("capnproto", _emit(api), api=api)
    assert not verdict.validated and not verdict.failed


async def test_validator_rejects_compiler_diagnostics() -> None:
    api = _user_api("id")
    with patch(
        "app.capnproto_compile.compile_capnp_schema",
        side_effect=CapnpCompileError("bad", diagnostics=["Users.capnp:3:1: error: Parse error."]),
    ):
        verdict = await validate_emitted_artifact("capnproto", _emit(api), api=api)
    assert verdict.failed
    assert "Parse error" in json.dumps(verdict.model_dump())


async def test_compile_refuses_unsafe_paths() -> None:
    with pytest.raises(CapnpCompileError):
        await compile_capnp_schema([CapnpFile(path="../evil.txt", content="")])
    with pytest.raises(CapnpCompileError):
        await compile_capnp_schema([])


# ===========================================================================
# Acceptance: the emitted schema compiles under capnp
# ===========================================================================

#: OpenAPI corpus specs covering scalars, nullable fields, unions (oneOf), untyped items, enums
#: and operations.
_OPENAPI_SPECS = [
    "01-numeric-constraints.yaml",
    "07-nullable-types.yaml",
    "11-unevaluated-items.yaml",
    "19-enumeration-sorting.yaml",
    "20-comprehensive-features.yaml",
    "22-advanced-oneof-polymorphism.yaml",
    "30-openapi-3.0-petstore.yaml",
]


@_needs_capnp
@pytest.mark.parametrize("name", _OPENAPI_SPECS)
async def test_openapi_corpus_exports_compile(name: str) -> None:
    result = _emit(_openapi_api(_EXAMPLES / "openapi" / name))
    await compile_capnp_schema([CapnpFile(path=result.files[0].path, content=_text(result))])


@_needs_capnp
@pytest.mark.parametrize(
    "name",
    ["01-address-book.capnp", "02-minimal-ping.capnp", "04-event-stress.capnp", "06-task-queue.capnp"],
)
async def test_capnp_corpus_round_trips_compile(name: str) -> None:
    result = _emit(_capnp_api(name))
    await compile_capnp_schema([CapnpFile(path=result.files[0].path, content=_text(result))])


@_needs_capnp
async def test_re_export_after_removing_a_field_compiles() -> None:
    store: Dict[str, int] = {}
    _emit(_user_api("id", "age", "name"), store)
    result = _emit(_user_api("name", "nick"), store)
    await compile_capnp_schema([CapnpFile(path=result.files[0].path, content=_text(result))])


@_needs_capnp
async def test_compiler_rejects_a_hole() -> None:
    with pytest.raises(CapnpCompileError) as excinfo:
        await compile_capnp_schema(
            [CapnpFile(path="x.capnp", content="@0x8f1d5c3a2b4e6d70;\nstruct A { a @1 :Text; }\n")]
        )
    assert any("ordinal" in line.lower() for line in excinfo.value.diagnostics)


@_needs_capnp
async def test_validator_passes_an_emitted_schema() -> None:
    api = _openapi_api(_EXAMPLES / "openapi" / "30-openapi-3.0-petstore.yaml")
    verdict = await validate_emitted_artifact("capnproto", _emit(api), api=api)
    assert verdict.validated and verdict.valid


# ===========================================================================
# Fidelity: renames are named, never silent
# ===========================================================================


def test_fidelity_report_names_identifier_renames() -> None:
    from app.fidelity_engine import compute_lossiness_for_emitter
    from app.lossiness import LossinessKind, LossinessSeverity

    api = _api([_user(_field("first_name", "string"), _field("age", "integer"))], [_pet_service()])
    report = compute_lossiness_for_emitter(api, CapnpEmitter)
    renames = {
        item.construct_key: item
        for item in report.items
        if item.kind is LossinessKind.APPROX and "style rules" in item.message
    }
    assert "User.first_name" in renames
    assert renames["User.first_name"].severity is LossinessSeverity.INFO
    assert "POST /pets" in renames  # the method is written postPets
    assert "User.age" not in renames and "GET /pets/{petId}" not in renames
