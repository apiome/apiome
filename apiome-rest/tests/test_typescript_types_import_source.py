"""TypeScript type-declaration import — FMT-8.1 (#5462).

Three layers, tested at the seams that own them:

* **detection and intake guards** — pure text, no compiler: what the adapter claims, and which
  inputs are rejected with which taxonomy code before the extractor ever runs;
* **the normalizer** — driven with hand-built extractor ASTs, so every modelling rule (generic
  instantiation, ``extends`` flattening, unions, intersections, tuples, maps, the declared
  limits) is pinned without a Node subprocess;
* **end to end through the compiler** — real TypeScript through the bundled extractor. These
  skip when the extractor is not installed, exactly like the gRPC suite does without ``buf``.

The corpus contracts (golden snapshots, negatives, round-trip matrix) cover the shipped
fixtures; this file covers the rules those fixtures do not happen to exercise.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from app import typescript_types_parser as parser_module
from app.canonical_model import CanonicalApi, Type, TypeKind
from app.fileset import IntakeFileset
from app.format_capability_registry import capability_for
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    get_import_source,
    load_builtin_import_sources,
)
from app.toolchain_packaging import probe_tool
from app.toolchain_runner import ToolNotAvailableError, ToolRunResult
from app.typescript_types_import_source import TYPESCRIPT_TYPES_CAPABILITIES
from app.typescript_types_normalizer import TYPESCRIPT_EXTRAS_KEY, TypeScriptTypesNormalizer
from app.typescript_types_parser import (
    LIMIT_DETAILS,
    TYPESCRIPT_SUFFIXES,
    TYPESCRIPT_TYPES_TOOL_KEY,
    LimitRecorder,
    TsDocument,
    imported_schema_library,
    is_typescript_types,
)

load_builtin_import_sources()

_EXTRACTOR_AVAILABLE = probe_tool(TYPESCRIPT_TYPES_TOOL_KEY).available
needs_extractor = pytest.mark.skipif(
    not _EXTRACTOR_AVAILABLE,
    reason="bundled typescript-types-extractor not resolvable in this environment",
)


@pytest.fixture()
def adapter():
    return get_import_source("typescript-types")


# ===========================================================================
# AST builders — the extractor's neutral JSON, written by hand
# ===========================================================================


def prim(name: str) -> Dict[str, Any]:
    return {"kind": "primitive", "name": name}


def lit(value: Any) -> Dict[str, Any]:
    return {"kind": "literal", "value": value}


def ref(name: str, *args: Any, module: str = "m.ts") -> Dict[str, Any]:
    return {"kind": "ref", "target": f"{module}#{name}", "name": name, "typeArguments": list(args)}


def tparam(name: str) -> Dict[str, Any]:
    return {"kind": "typeParameter", "name": name}


def arr(element: Any) -> Dict[str, Any]:
    return {"kind": "array", "element": element, "readonly": False}


def union(*members: Any) -> Dict[str, Any]:
    return {"kind": "union", "members": list(members)}


def prop(
    name: str,
    type_: Any,
    *,
    optional: bool = False,
    readonly: bool = False,
    doc: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "name": name,
        "optional": optional,
        "readonly": readonly,
        "type": type_,
        "doc": doc,
        "deprecated": False,
        "line": 1,
    }


def obj(
    *props: Any, index: Optional[List[Any]] = None, unsupported: Optional[List[Any]] = None
) -> Dict[str, Any]:
    return {
        "kind": "object",
        "properties": list(props),
        "indexSignatures": index or [],
        "unsupported": unsupported or [],
    }


def unsupported(construct: str, text: str = "…") -> Dict[str, Any]:
    return {"kind": "unsupported", "construct": construct, "text": text}


def interface(
    name: str,
    *props: Any,
    params=(),
    extends=(),
    index=None,
    exported=True,
    merged=1,
    unsupported_members=None,
) -> Dict[str, Any]:
    return {
        "id": f"m.ts#{name}",
        "name": name,
        "module": "m.ts",
        "line": 1,
        "exported": exported,
        "doc": None,
        "deprecated": False,
        "typeParameters": [{"name": p, "default": None} for p in params],
        "mergedDeclarations": merged,
        "kind": "interface",
        "extends": list(extends),
        "properties": list(props),
        "indexSignatures": index or [],
        "unsupported": unsupported_members or [],
    }


def alias(name: str, type_: Any, *, params=(), exported=True) -> Dict[str, Any]:
    return {
        "id": f"m.ts#{name}",
        "name": name,
        "module": "m.ts",
        "line": 1,
        "exported": exported,
        "doc": None,
        "deprecated": False,
        "typeParameters": [{"name": p, "default": None} for p in params],
        "mergedDeclarations": 1,
        "kind": "alias",
        "type": type_,
    }


def enum(name: str, members: List[Any], *, const: bool = False) -> Dict[str, Any]:
    return {
        "id": f"m.ts#{name}",
        "name": name,
        "module": "m.ts",
        "line": 1,
        "exported": True,
        "doc": None,
        "deprecated": False,
        "typeParameters": [],
        "mergedDeclarations": 1,
        "kind": "enum",
        "const": const,
        "members": [{"name": n, "value": v, "doc": None, "deprecated": False} for n, v in members],
    }


def normalize(*declarations: Dict[str, Any]) -> CanonicalApi:
    document = TsDocument(
        root="m.ts", files=("m.ts",), typescript_version="6.0.3", declarations=tuple(declarations)
    )
    return TypeScriptTypesNormalizer().normalize(document, include_raw=False)


def types_of(api: CanonicalApi) -> Dict[str, Type]:
    return {t.key: t for t in api.types}


def limits_of(api: CanonicalApi) -> Dict[str, List[str]]:
    return {
        limit["construct"]: limit["locations"]
        for limit in api.extras[TYPESCRIPT_EXTRAS_KEY]["capability_limits"]
    }


def field(type_: Type, name: str):
    return next(f for f in type_.fields if f.name == name)


# ===========================================================================
# Adapter surface
# ===========================================================================


def test_adapter_is_registered_with_the_required_tool(adapter):
    assert adapter.key == "typescript-types"
    assert adapter.required_tools == (TYPESCRIPT_TYPES_TOOL_KEY,)
    assert ".d.ts" in adapter.declared_file_extensions()
    assert ".ts" in adapter.declared_file_extensions()


def test_declared_unsupported_constructs_are_exactly_the_limit_vocabulary():
    """The adapter, the limit table and the registry seed name the same constructs."""
    assert set(TYPESCRIPT_TYPES_CAPABILITIES.unsupported) == set(LIMIT_DETAILS)
    entry = capability_for("typescript-types")
    assert set(entry.canonical_projection.dropped_constructs) == set(LIMIT_DETAILS)


def test_limit_recorder_rejects_an_undeclared_construct():
    with pytest.raises(KeyError):
        LimitRecorder().record("typescript.not_a_limit")


# ===========================================================================
# Detection
# ===========================================================================


@pytest.mark.parametrize(
    "text",
    [
        "export interface A { id: string }",
        "export type Status = 'on' | 'off';",
        "export type Page<T> = { items: T[] };",
        "export enum Role { Admin = 'admin' }",
        "export const enum Flag { On = 1 }",
        "export declare interface D { x: number }",
        "export * from './order';",
        "export type { Order } from './order';",
    ],
)
def test_detects_exported_type_declarations(adapter, text):
    assert is_typescript_types(text)
    assert adapter.detect(DetectionInput(text=text)).matched


def test_a_typescript_filename_raises_confidence(adapter):
    text = "export interface A { id: string }"
    pasted = adapter.detect(DetectionInput(text=text)).confidence
    uploaded = adapter.detect(DetectionInput(text=text, filename="types.d.ts")).confidence
    assert uploaded > pasted >= 0.8


@pytest.mark.parametrize(
    "text",
    [
        "export function pageSize(n: number): number { return n; }",
        "const LIMIT = 25;",
        "interface Internal { id: string }",
        '{"openapi": "3.1.0"}',
        "import { z } from 'zod';\nexport const Order = z.object({});\nexport type Order = z.infer<typeof Order>;",
    ],
)
def test_does_not_claim_non_type_modules(adapter, text):
    assert not adapter.detect(DetectionInput(text=text)).matched


@pytest.mark.parametrize(
    "specifier, library",
    [("zod", "zod"), ("zod/v4", "zod"), ("@sinclair/typebox", "@sinclair/typebox"), ("yup", "yup")],
)
def test_schema_library_imports_are_recognized(specifier, library):
    assert imported_schema_library(f"import {{ x }} from '{specifier}';") == library


def test_a_lookalike_package_is_not_a_schema_library():
    assert imported_schema_library("import { x } from 'zodiac';") is None


# ===========================================================================
# Intake guards (before the compiler runs)
# ===========================================================================


@pytest.mark.parametrize(
    "text, code",
    [
        ("   \n", "INPUT_EMPTY"),
        ("e\x00x\x00p\x00", "INPUT_ENCODING_INVALID"),
        ("﻿export interface A { id: string }", "INPUT_ENCODING_INVALID"),
        ("export interface A { id: � }", "INPUT_ENCODING_INVALID"),
        ("import { z } from 'zod';\nexport const A = z.string();", "FORMAT_MISMATCH"),
    ],
)
def test_guards_classify_before_the_extractor_runs(adapter, monkeypatch, text, code):
    def _never(*args, **kwargs):  # pragma: no cover - reaching it is the failure
        raise AssertionError("the extractor must not run for a guarded input")

    monkeypatch.setattr(parser_module, "run_tool_blocking", _never)
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse(text, source_label="types.ts")
    assert excinfo.value.code == code


def test_oversized_input_is_too_large(adapter, monkeypatch):
    monkeypatch.setattr(parser_module, "MAX_TYPESCRIPT_BYTES", 32)
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse("export interface A { id: string; name: string }", source_label="a.ts")
    assert excinfo.value.code == "INPUT_TOO_LARGE"


def test_missing_extractor_is_adapter_unavailable(adapter, monkeypatch):
    def _missing(*args, **kwargs):
        raise ToolNotAvailableError(TYPESCRIPT_TYPES_TOOL_KEY, "typescript-types-extract")

    monkeypatch.setattr(parser_module, "run_tool_blocking", _missing)
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse("export interface A { id: string }", source_label="a.ts")
    assert excinfo.value.code == "ADAPTER_UNAVAILABLE"


def test_a_broken_extractor_contract_is_an_internal_fault(adapter, monkeypatch):
    def _garbage(*args, **kwargs):
        return ToolRunResult(
            key=TYPESCRIPT_TYPES_TOOL_KEY,
            argv=["x"],
            exit_code=0,
            stdout="[]",
            stderr="",
            parsed_json=["not", "an", "object"],
            duration_ms=1,
        )

    monkeypatch.setattr(parser_module, "run_tool_blocking", _garbage)
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse("export interface A { id: string }", source_label="a.ts")
    assert excinfo.value.code == "INTERNAL_ADAPTER_FAULT"


def test_fileset_without_a_typescript_root_is_rejected(adapter):
    fileset = IntakeFileset.from_members(
        {"README.md": "# hi", "a.ts": "export interface A {}"}, root="README.md"
    )
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse_fileset(fileset)
    assert excinfo.value.code == "INPUT_SEMANTIC_INVALID"


def test_normalize_rejects_a_foreign_ast(adapter):
    with pytest.raises(ImportSourceError):
        adapter.normalize({"not": "a document"})


# ===========================================================================
# Normalizer — modelling rules
# ===========================================================================


def test_interface_becomes_a_record_with_optional_and_readonly_kept():
    api = normalize(
        interface(
            "User",
            prop("id", prim("string"), readonly=True),
            prop("nick", prim("string"), optional=True, doc="Shown in the UI."),
            prop("bio", union(prim("string"), prim("null"))),
        )
    )
    user = types_of(api)["User"]
    assert user.kind is TypeKind.RECORD
    assert field(user, "id").type.nullable is False
    assert field(user, "id").extras["typescript_readonly"] is True
    assert field(user, "nick").type.nullable is True
    assert field(user, "nick").extras["typescript_optional"] is True
    assert field(user, "nick").description == "Shown in the UI."
    assert field(user, "bio").type.nullable is True
    assert field(user, "bio").type.name == "string"
    assert api.identity.name == "User"


def test_literal_union_alias_is_an_enum_and_inline_literals_are_constraints():
    api = normalize(
        alias("Status", union(lit("new"), lit("paid"))),
        interface("Order", prop("mode", union(lit("AUTO"), lit("MANUAL")), optional=True)),
    )
    status = types_of(api)["Status"]
    assert status.kind is TypeKind.ENUM
    assert [v.value for v in status.enum_values] == ["new", "paid"]
    mode = field(types_of(api)["Order"], "mode")
    assert mode.type.name == "string" and mode.constraints.enum == ["AUTO", "MANUAL"]


def test_enum_declaration_keeps_constant_values():
    api = normalize(enum("Level", [("Low", 0), ("High", 10)], const=True))
    level = types_of(api)["Level"]
    assert level.kind is TypeKind.ENUM
    assert [(v.name, v.value) for v in level.enum_values] == [("Low", 0), ("High", 10)]
    assert level.extras["typescript_kind"] == "const_enum"


def test_union_of_inline_objects_names_variants_by_discriminant():
    api = normalize(
        alias(
            "Shape",
            union(
                obj(prop("kind", lit("circle")), prop("r", prim("number"))),
                obj(prop("kind", lit("square")), prop("side", prim("number"))),
            ),
        )
    )
    shape = types_of(api)["Shape"]
    assert shape.kind is TypeKind.UNION
    assert shape.union_members == ["Shape_circle", "Shape_square"]
    assert {"Shape_circle", "Shape_square"} <= set(types_of(api))


def test_union_of_named_types_references_them():
    api = normalize(
        interface("A", prop("a", prim("string"))),
        interface("B", prop("b", prim("string"))),
        alias("AorB", union(ref("A"), ref("B"))),
    )
    assert types_of(api)["AorB"].union_members == ["A", "B"]


def test_extends_is_flattened_with_the_child_overriding():
    api = normalize(
        interface(
            "Base", prop("id", prim("string")), prop("updatedAt", prim("string"), optional=True)
        ),
        interface("Child", prop("updatedAt", prim("string")), extends=[ref("Base")]),
    )
    child = types_of(api)["Child"]
    assert {f.name for f in child.fields} == {"id", "updatedAt"}
    assert field(child, "updatedAt").type.nullable is False
    assert child.extras["typescript_extends"] == ["Base"]


def test_intersection_of_objects_is_one_merged_record():
    api = normalize(
        interface("Stamp", prop("at", prim("string"))),
        alias(
            "Audited",
            {"kind": "intersection", "members": [ref("Stamp"), obj(prop("by", prim("string")))]},
        ),
    )
    audited = types_of(api)["Audited"]
    assert audited.kind is TypeKind.RECORD
    assert {f.name for f in audited.fields} == {"at", "by"}


def test_intersection_with_a_primitive_is_a_declared_limit_not_a_guess():
    api = normalize(
        interface(
            "Branded",
            prop(
                "id",
                {
                    "kind": "intersection",
                    "members": [prim("string"), obj(prop("__brand", lit("Id")))],
                },
            ),
        )
    )
    id_field = field(types_of(api)["Branded"], "id")
    assert id_field.type.name == "string"
    assert "typescript.intersection" in limits_of(api)


def test_generic_alias_instantiation_is_built_under_the_alias_name():
    api = normalize(
        interface(
            "Page", prop("items", arr(tparam("T"))), prop("total", prim("number")), params=["T"]
        ),
        interface("Order", prop("id", prim("string"))),
        alias("OrderPage", ref("Page", ref("Order"))),
    )
    types = types_of(api)
    assert "Page" not in types
    page = types["OrderPage"]
    assert page.kind is TypeKind.RECORD
    assert field(page, "items").type.item.name == "Order"
    assert page.extras["typescript_instantiates"] == "Page"
    assert "typescript.unresolved_generic" not in limits_of(api)


def test_inline_generic_instantiations_get_one_type_per_argument_list():
    api = normalize(
        interface("Page", prop("items", arr(tparam("T"))), params=["T"]),
        interface("A", prop("a", prim("string"))),
        interface("B", prop("b", prim("string"))),
        interface(
            "Holder",
            prop("as", ref("Page", ref("A"))),
            prop("bs", ref("Page", ref("B"))),
            prop("as2", ref("Page", ref("A"))),
        ),
    )
    holder = types_of(api)["Holder"]
    assert field(holder, "as").type.name == "Page_A"
    assert field(holder, "bs").type.name == "Page_B"
    assert field(holder, "as2").type.name == "Page_A"


def test_an_uninstantiated_generic_is_declared_and_never_modelled():
    api = normalize(interface("Envelope", prop("payload", tparam("T")), params=["T"]))
    assert api.types == []
    assert limits_of(api)["typescript.unresolved_generic"] == ["Envelope"]


def test_a_generic_alias_with_an_unsupported_body_declares_the_body_construct():
    api = normalize(alias("Unwrap", unsupported("conditional_type"), params=["T"]))
    limits = limits_of(api)
    assert limits["typescript.conditional_type"] == ["Unwrap"]
    assert "typescript.unresolved_generic" not in limits


def test_unsupported_members_are_left_out_never_any():
    api = normalize(
        interface(
            "Widget",
            prop("id", prim("string")),
            prop("onClick", unsupported("function_type")),
            prop("label", unsupported("template_literal_type")),
            unsupported_members=[
                {"name": "[brand]", "construct": "symbol_key", "text": "[brand]: true"}
            ],
        )
    )
    widget = types_of(api)["Widget"]
    assert [f.name for f in widget.fields] == ["id"]
    limits = limits_of(api)
    assert limits["typescript.function_type"] == ["Widget.onClick"]
    assert limits["typescript.template_literal_type"] == ["Widget.label"]
    assert limits["typescript.symbol_key"] == ["Widget.[brand]"]
    assert all(f.type.name != "any" for t in api.types for f in t.fields)


def test_merged_interface_and_its_references_are_declared():
    api = normalize(
        interface("Merged", prop("first", prim("string")), merged=2),
        interface("User", prop("id", prim("string")), prop("meta", ref("Merged"))),
    )
    types = types_of(api)
    assert "Merged" not in types
    assert [f.name for f in types["User"].fields] == ["id"]
    limits = limits_of(api)
    assert limits["typescript.declaration_merging"] == ["Merged"]
    assert limits["typescript.unmodelled_reference"] == ["User.meta"]


def test_an_unsupported_top_level_alias_is_not_an_unmodelled_reference():
    api = normalize(alias("Handler", unsupported("function_type")))
    limits = limits_of(api)
    assert limits == {"typescript.function_type": ["Handler"]}


def test_index_signature_only_object_is_a_map():
    api = normalize(
        interface(
            "Scores",
            index=[
                {
                    "keyName": "k",
                    "keyType": prim("string"),
                    "valueType": prim("number"),
                    "readonly": False,
                }
            ],
        )
    )
    scores = types_of(api)["Scores"]
    assert scores.kind is TypeKind.MAP
    assert scores.key_type.name == "string" and scores.value_type.name == "number"


def test_index_signature_beside_properties_is_recorded_and_declared():
    api = normalize(
        interface(
            "Bag",
            prop("known", prim("string")),
            index=[
                {
                    "keyName": "k",
                    "keyType": prim("string"),
                    "valueType": prim("number"),
                    "readonly": False,
                }
            ],
        )
    )
    bag = types_of(api)["Bag"]
    assert bag.kind is TypeKind.RECORD
    assert bag.extras["typescript_index"][0]["value_type"]["name"] == "number"
    assert limits_of(api)["typescript.index_signature"] == ["Bag"]


@pytest.mark.parametrize("lib", ["Record", "Map", "ReadonlyMap"])
def test_record_and_map_become_map_types(lib):
    api = normalize(
        alias(
            "Lookup",
            {"kind": "lib", "name": lib, "typeArguments": [prim("string"), prim("number")]},
        )
    )
    lookup = types_of(api)["Lookup"]
    assert lookup.kind is TypeKind.MAP
    assert lookup.value_type.name == "number"


def test_set_is_a_list_of_unique_items():
    api = normalize(
        interface(
            "Tags", prop("tags", {"kind": "lib", "name": "Set", "typeArguments": [prim("string")]})
        )
    )
    tags = field(types_of(api)["Tags"], "tags")
    assert tags.type.item.name == "string"
    assert tags.constraints.unique_items is True


def test_tuple_is_a_bounded_list_with_positions_recorded():
    tuple_node = {
        "kind": "tuple",
        "elements": [
            {"name": "id", "type": prim("string"), "optional": False, "rest": False},
            {"name": "count", "type": prim("number"), "optional": False, "rest": False},
            {"name": "active", "type": prim("boolean"), "optional": True, "rest": False},
        ],
    }
    api = normalize(alias("Row", tuple_node))
    row = types_of(api)["Row"]
    assert row.kind is TypeKind.ALIAS
    assert row.constraints.min_items == 2 and row.constraints.max_items == 3
    assert [e["name"] for e in row.extras["typescript_tuple"]] == ["id", "count", "active"]
    assert types_of(api)[row.aliased.item.name].union_members == ["string", "number", "boolean"]
    assert limits_of(api)["typescript.tuple_positions"] == ["Row"]


def test_variadic_tuple_has_no_upper_bound():
    tuple_node = {
        "kind": "tuple",
        "elements": [
            {"name": None, "type": prim("string"), "optional": False, "rest": False},
            {"name": None, "type": arr(prim("number")), "optional": False, "rest": True},
        ],
    }
    row = types_of(normalize(alias("Args", tuple_node)))["Args"]
    assert row.constraints.min_items == 1 and row.constraints.max_items is None


def test_date_is_a_formatted_string():
    api = normalize(interface("Event", prop("at", prim("date"))))
    at = field(types_of(api)["Event"], "at")
    assert at.type.name == "string" and at.constraints.format == "date-time"


def test_evaluated_utility_types_model_as_their_shape():
    picked = {
        "kind": "evaluated",
        "via": "utility:Pick",
        "text": "Pick<User, 'id'>",
        "type": obj(prop("id", prim("string"))),
    }
    api = normalize(alias("UserRef", picked))
    user_ref = types_of(api)["UserRef"]
    assert user_ref.kind is TypeKind.RECORD
    assert [f.name for f in user_ref.fields] == ["id"]
    assert user_ref.extras["typescript_evaluated"]["via"] == "utility:Pick"


def test_self_referencing_interface_terminates():
    api = normalize(interface("Node", prop("children", arr(ref("Node")))))
    node = types_of(api)["Node"]
    assert field(node, "children").type.item.name == "Node"


def test_non_exported_helpers_appear_only_when_referenced():
    api = normalize(
        interface("Used", prop("x", prim("string")), exported=False),
        interface("Unused", prop("y", prim("string")), exported=False),
        interface("Root", prop("used", ref("Used"))),
    )
    assert set(types_of(api)) == {"Root", "Used"}
    assert api.extras[TYPESCRIPT_EXTRAS_KEY]["exports"] == ["Root"]


def test_identity_prefers_the_first_exported_interface():
    api = normalize(
        alias("Status", union(lit("a"), lit("b"))), interface("Order", prop("id", prim("string")))
    )
    assert api.identity.name == "Order"
    assert api.extras[TYPESCRIPT_EXTRAS_KEY]["root_type"] == "Order"


# ===========================================================================
# End to end through the TypeScript compiler
# ===========================================================================


def _import(adapter, text: str, name: str = "types.ts") -> CanonicalApi:
    return adapter.normalize(adapter.parse(text, source_label=name))


@needs_extractor
def test_compiler_reads_a_module_end_to_end(adapter):
    api = _import(
        adapter,
        """
        /** A customer. */
        export interface Customer {
          id: string;
          /** @deprecated use tags */
          segment?: string;
          tags: readonly string[];
          createdAt: Date;
        }
        export enum Tier { Free, Pro = 5, Team }
        """,
    )
    types = types_of(api)
    customer = types["Customer"]
    assert customer.description == "A customer."
    assert field(customer, "segment").deprecated is True
    assert field(customer, "tags").type.item.name == "string"
    assert field(customer, "createdAt").constraints.format == "date-time"
    assert [(v.name, v.value) for v in types["Tier"].enum_values] == [
        ("Free", 0),
        ("Pro", 5),
        ("Team", 6),
    ]


@needs_extractor
def test_compiler_evaluates_utilities_and_queries(adapter):
    api = _import(
        adapter,
        """
        export interface User { id: string; name: string; email?: string }
        export type UserPatch = Partial<Pick<User, 'name' | 'email'>>;
        export type UserKey = keyof User;
        export type NameType = User['name'];
        """,
    )
    types = types_of(api)
    patch = types["UserPatch"]
    assert {f.name for f in patch.fields} == {"name", "email"}
    assert all(f.type.nullable for f in patch.fields)
    # The checker orders an evaluated union by its own type ids, not by declaration order.
    assert {v.value for v in types["UserKey"].enum_values} == {"id", "name", "email"}
    assert types["NameType"].aliased.name == "string"


@needs_extractor
def test_compiler_syntax_error_is_malformed(adapter):
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse("export interface A {\n  id string;\n}\n", source_label="a.ts")
    assert excinfo.value.code == "INPUT_MALFORMED"


@needs_extractor
def test_compiler_text_cut_short_is_truncated(adapter):
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse("export interface A {\n  id: string;\n  name: Str", source_label="a.ts")
    assert excinfo.value.code == "INPUT_TRUNCATED"


@needs_extractor
def test_compiler_no_exported_types_is_semantic(adapter):
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse("interface Hidden { id: string }\nexport const x = 1;\n", source_label="a.ts")
    assert excinfo.value.code == "INPUT_SEMANTIC_INVALID"


@needs_extractor
def test_compiler_unresolved_reference_is_rejected_not_any(adapter):
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse(
            "import type { Money } from './money';\nexport interface Order { total: Money }\n",
            source_label="order.ts",
        )
    assert excinfo.value.code == "INPUT_REFERENCE_UNRESOLVED"
    assert "Money" in str(excinfo.value) and "./money" in str(excinfo.value)


@needs_extractor
def test_an_unused_unresolved_import_costs_nothing(adapter):
    api = _import(
        adapter,
        "import type { Unused } from './elsewhere';\nexport interface Order { id: string }\n",
    )
    assert [t.key for t in api.types] == ["Order"]


@needs_extractor
def test_compiler_resolves_a_fileset_across_sub_folders(adapter):
    fileset = IntakeFileset.from_members(
        {
            "index.ts": "export * from './models/order';\nexport type { Money } from './shared/money';\n",
            "models/order.ts": (
                "import type { Money } from '../shared/money';\n"
                "export interface Order { total: Money }\n"
            ),
            "shared/money.ts": "export interface Money { value: number; currency: string }\n",
        },
        root="index.ts",
    )
    api = adapter.normalize(adapter.parse_fileset(fileset))
    types = types_of(api)
    assert field(types["Order"], "total").type.name == "Money"
    assert set(api.extras[TYPESCRIPT_EXTRAS_KEY]["exports"]) == {"Order", "Money"}


@needs_extractor
def test_a_declaration_file_with_declare_reads_like_a_module(adapter):
    api = _import(
        adapter, "export declare interface Point { x: number; y: number }\n", name="point.d.ts"
    )
    assert {f.name for f in types_of(api)["Point"].fields} == {"x", "y"}


@needs_extractor
def test_every_limit_construct_reaches_the_ledger_and_nothing_is_any(adapter):
    api = _import(
        adapter,
        """
        export type Unwrap<T> = T extends Promise<infer U> ? U : T;
        export type Optionalise<T> = { [K in keyof T]?: T[K] };
        export type Topic = `orders.${string}`;
        export type Callback = (value: string) => void;
        export interface Envelope<T> { payload: T }
        export interface Pending { result: Promise<string>; id: string }
        """,
    )
    limits = limits_of(api)
    for construct in (
        "typescript.conditional_type",
        "typescript.mapped_type",
        "typescript.template_literal_type",
        "typescript.function_type",
        "typescript.unresolved_generic",
        "typescript.lib_type",
    ):
        assert construct in limits, construct
    assert [f.name for f in types_of(api)["Pending"].fields] == ["id"]
    assert all(f.type.name not in {"any", "unknown"} for t in api.types for f in t.fields)


def test_typescript_suffixes_cover_declaration_files():
    assert ".d.ts" in TYPESCRIPT_SUFFIXES and ".d.mts" in TYPESCRIPT_SUFFIXES


@needs_extractor
def test_compiler_reads_nothing_outside_the_upload(adapter):
    """A reference or import that points at the host filesystem resolves to nothing."""
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse(
            '/// <reference path="/etc/hostname" />\n'
            '/// <reference types="node" />\n'
            'import type { Secret } from "/etc/hostname";\n'
            "export interface Leak { value: Secret }\n",
            source_label="leak.ts",
        )
    assert excinfo.value.code == "INPUT_REFERENCE_UNRESOLVED"
