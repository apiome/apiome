"""Tests for the ONC RPC / XDR definition: declarations, the migrate note, lint and breaking
changes — MFI-21.6 (#3996)."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import pytest

from app.breaking_change import Severity, available_breaking_change_formats, classify_models
from app.format_lint_capabilities import MODE_NATIVE, capability_for_format
from app.lint_engine import get_rule_pack, lint_canonical_model
from app.oncrpc_breaking import OncRpcBreakingChangeClassifier
from app.oncrpc_import_source import OncRpcImportSource
from app.oncrpc_lint import PROTO3_FOR_XDR, OncRpcRulePack, type_shape
from app.oncrpc_normalizer import OncRpcNormalizer
from app.oncrpc_parser import parse_oncrpc

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "onc-rpc"
_VALID = [
    "01-key-value-store.x",
    "02-file-stat.x",
    "03-inventory-composition.x",
    "04-job-queue-stress.x",
    "05-portmapper-style.x",
    "06-metrics-collector.x",
]

_PROGRAM = """
enum colour { RED = 0, GREEN = 1 };
typedef string name_t<64>;
struct item { name_t name; opaque payload<1024>; int tags[4]; colour tint; };
union lookup switch (int status) {
case 0:
    item found;
default:
    void;
};
program ITEM_PROG {
    version ITEM_VERS {
        void ITEM_NULL(void) = 0;
        lookup ITEM_GET(name_t) = 1;
        int ITEM_PUT(item) = 2;
    } = 1;
} = 0x20000010;
"""


def _fixture(name: str) -> str:
    return (_EXAMPLES / name).read_text(encoding="utf-8")


def _api(text: str):
    adapter = OncRpcImportSource()
    return adapter.normalize(adapter.parse(text, source_label="prog.x"), include_raw=False)


def _findings(text: str) -> List[Tuple[str, str, str]]:
    result = lint_canonical_model(_api(text))
    return sorted((f.rule, f.severity, f.path) for f in result.findings if f.rule.startswith("oncrpc."))


def _grades(base: str, target: str) -> Dict[Tuple[str, str], Tuple[Severity, str]]:
    """``(kind, key)`` → ``(severity, rule_id)`` for the diff of two programs."""
    result = classify_models(_api(base), _api(target))
    assert result.classifier == "oncrpc-procedure"
    return {(c.kind.value, c.key): (c.severity, c.rule_id) for c in result.classifications}


# --- declarations the parser keeps (RFC 4506 §6.3) ----------------------------------------


def test_the_parser_keeps_every_declaration_shape():
    doc = parse_oncrpc(
        "typedef string name_t<>;\ntypedef int ids<8>;\n"
        "struct s { string a<>; opaque b<16>; int c[4]; name_t d; unsigned int e; int *g; name_t names<10>; };\n"
        "program P { version V { void NULLPROC(void) = 0; } = 1; } = 0x20000001;"
    )
    assert [(t.name, t.type_expr) for t in doc.typedefs] == [("name_t", "string<>"), ("ids", "int<8>")]
    assert [(f.name, f.type_expr) for f in doc.structs[0].fields] == [
        ("a", "string<>"),
        ("b", "opaque<16>"),
        ("c", "int[4]"),
        ("d", "name_t"),
        ("e", "unsigned int"),
        ("g", "int*"),
        ("names", "name_t<10>"),
    ]


def test_type_shape_decodes_each_suffix():
    assert type_shape("opaque<1024>") == {
        "base": "opaque",
        "pointer": False,
        "variable": True,
        "bound": 1024,
        "fixed": None,
    }
    assert type_shape("string<>")["bound"] is None and type_shape("string<>")["variable"] is True
    assert type_shape("int[4]")["fixed"] == 4
    assert type_shape("node*")["pointer"] is True
    assert type_shape("unsigned hyper")["base"] == "unsigned hyper"


def test_the_normalizer_maps_arrays_bounds_and_pointers():
    api = OncRpcNormalizer().normalize(
        parse_oncrpc(
            "typedef string name_t<>;\ntypedef string key_t<64>;\n"
            "struct s { name_t names<10>; key_t keys[3]; key_t k; int *g; opaque raw<>; };\n"
            "program P { version V { void NULLPROC(void) = 0; } = 1; } = 0x20000001;"
        ),
        include_raw=False,
    )
    fields = {f.name: f for f in api.types[0].fields}
    assert fields["names"].type.item is not None and fields["names"].type.item.name == "string"
    assert fields["names"].constraints is not None and fields["names"].constraints.max_items == 10
    assert (
        fields["keys"].type.item is not None
        and fields["keys"].constraints.min_items == fields["keys"].constraints.max_items == 3
    )
    assert fields["k"].type.name == "string" and fields["k"].constraints.max_length == 64
    assert fields["g"].type.name == "i32" and fields["g"].type.nullable is True
    assert fields["raw"].type.name == "bytes" and fields["raw"].constraints is None


def test_the_normalizer_records_numbers_on_the_service_and_operations():
    api = _api(_fixture("04-job-queue-stress.x"))
    service = api.services[0]
    assert service.extras["oncrpc_program_number"] == 0x20000004
    assert service.extras["oncrpc_versions"] == {"JOB_VERS_1": 1, "JOB_VERS_2": 2}
    cancel = next(o for o in service.operations if o.name == "JOB_CANCEL")
    assert cancel.extras["oncrpc_procedure_number"] == 3
    assert cancel.extras["oncrpc_version_number"] == 2 and cancel.extras["oncrpc_version_name"] == "JOB_VERS_2"
    assert cancel.extras["oncrpc_arg_type"] == "job_id" and cancel.extras["oncrpc_return_type"] == "void"


# --- the migrate-to-gRPC note -------------------------------------------------------------


def test_the_migration_note_rewrites_the_program_as_proto3():
    note = _api(_PROGRAM).extras["oncrpc_migration"]
    assert note["target"] == "protobuf"
    by_name = {t["name"]: t for t in note["types"]}
    assert by_name["colour"]["proto3"] == "enum colour"
    assert by_name["item"]["proto3"] == "message item { string name, bytes payload, repeated int32 tags, colour tint }"
    assert by_name["lookup"]["proto3"].startswith("message lookup { oneof status")
    assert "inlined" in by_name["name_t"]["proto3"]
    procedures = {p["name"]: p for p in note["procedures"]}
    assert procedures["ITEM_GET"]["proto3"] == "rpc ITEM_GET (string) returns (lookup);"
    assert procedures["ITEM_GET"]["number"] == 1 and procedures["ITEM_GET"]["version"] == "ITEM_VERS"
    assert procedures["ITEM_NULL"]["proto3"] == "rpc ITEM_NULL (google.protobuf.Empty) returns (google.protobuf.Empty);"
    assert any("numbers have no proto3 counterpart" in c for c in note["caveats"])
    assert PROTO3_FOR_XDR["unsigned hyper"] == "uint64"


# --- lint ---------------------------------------------------------------------------------


def test_the_lint_pack_is_registered():
    assert get_rule_pack("oncrpc") is not None
    assert capability_for_format("oncrpc").mode == MODE_NATIVE
    ids = [rule.rule_id for rule in OncRpcRulePack().rules()]
    assert len(ids) == len(set(ids)) and all(i.startswith("oncrpc.") for i in ids)


@pytest.mark.parametrize("name", [n for n in _VALID if n != "05-portmapper-style.x"])
def test_every_site_defined_example_only_lacks_the_null_procedure(name: str):
    findings = _findings(_fixture(name))
    assert findings and all(f[0] == "oncrpc.null-procedure-declared" and f[1] == "info" for f in findings)


def test_the_portmapper_example_is_noted_as_an_assigned_number():
    assert _findings(_fixture("05-portmapper-style.x")) == [
        ("oncrpc.program-number-assigned", "info", "programs.PMAP_PROG"),
    ]


def test_a_complete_program_is_clean():
    assert _findings(_PROGRAM) == []


def test_program_number_rules():
    reserved = _PROGRAM.replace("= 0x20000010;", "= 0x60000001;")
    assert ("oncrpc.program-number-reserved", "warning", "programs.ITEM_PROG") in _findings(reserved)
    assigned = _PROGRAM.replace("= 0x20000010;", "= 100005;")
    assert ("oncrpc.program-number-assigned", "info", "programs.ITEM_PROG") in _findings(assigned)


def test_duplicate_numbers_and_names_are_errors():
    doubled = _PROGRAM.replace("int ITEM_PUT(item) = 2;", "int ITEM_PUT(item) = 1;")
    assert (
        "oncrpc.procedure-numbers-unique",
        "error",
        "programs.ITEM_PROG.versions.ITEM_VERS.procedures.1",
    ) in _findings(doubled)
    renamed = _PROGRAM.replace("int ITEM_PUT(item) = 2;", "int ITEM_GET(item) = 2;")
    assert (
        "oncrpc.procedure-names-unique",
        "error",
        "programs.ITEM_PROG.versions.ITEM_VERS.procedures.ITEM_GET",
    ) in _findings(renamed)
    two_versions = _PROGRAM.replace(
        "    } = 1;\n} = 0x20000010;",
        "    } = 1;\n    version ITEM_VERS_B { void ITEM_NULL_B(void) = 0; } = 1;\n} = 0x20000010;",
    )
    assert ("oncrpc.version-numbers-unique", "error", "programs.ITEM_PROG.versions.1") in _findings(two_versions)
    enum_dup = _PROGRAM.replace("GREEN = 1", "GREEN = 0")
    assert ("oncrpc.enum-values-unique", "error", "types.colour") in _findings(enum_dup)


def test_null_procedure_rules():
    without = _PROGRAM.replace("        void ITEM_NULL(void) = 0;\n", "")
    assert (
        "oncrpc.null-procedure-declared",
        "info",
        "programs.ITEM_PROG.versions.ITEM_VERS.procedures.0",
    ) in _findings(without)
    typed = _PROGRAM.replace("void ITEM_NULL(void) = 0;", "int ITEM_NULL(name_t) = 0;")
    assert ("oncrpc.null-procedure-void", "warning", "programs.ITEM_PROG.versions.ITEM_VERS.procedures.0") in _findings(
        typed
    )


def test_declaration_rules():
    unbounded = _PROGRAM.replace("opaque payload<1024>;", "opaque payload<>;")
    assert ("oncrpc.variable-length-bounded", "info", "types.item.payload") in _findings(unbounded)
    unknown = _PROGRAM.replace("colour tint;", "shade tint;")
    assert ("oncrpc.type-resolves", "error", "types.item.tint") in _findings(unknown)
    no_default = _PROGRAM.replace("default:\n    void;\n", "")
    assert ("oncrpc.union-has-default", "info", "types.lookup") in _findings(no_default)


# --- breaking changes ---------------------------------------------------------------------


def test_the_classifier_is_registered_for_oncrpc():
    assert "oncrpc" in available_breaking_change_formats()
    assert OncRpcBreakingChangeClassifier.classifier_id == "oncrpc-procedure"


def test_the_key_value_store_fixture_is_graded_by_number_and_bound():
    base = _fixture("01-key-value-store.x")
    target = (
        base.replace("kv_status  KV_PUT(kv_put_args) = 2;", "kv_status  KV_PUT(kv_put_args) = 4;")
        .replace("} = 0x20000001;", "} = 0x20000002;")
        .replace("opaque value<1024>;\n};\n\nunion", "opaque value<2048>;\n};\n\nunion")
    )
    grades = _grades(base, target)
    assert grades[("modified", "KV_PROG.KV_PROG")] == (Severity.BREAKING, "oncrpc.program-renumbered")
    assert grades[("modified", "KV_PROG.KV_PROG.KV_PUT")] == (Severity.BREAKING, "oncrpc.procedure-renumbered")
    assert grades[("modified", "KV_PROG.kv_entry.value")] == (Severity.DANGEROUS, "oncrpc.bound-widened")


def test_procedure_and_version_grades():
    removed = _PROGRAM.replace("        int ITEM_PUT(item) = 2;\n", "")
    assert _grades(_PROGRAM, removed)[("removed", "ITEM_PROG.ITEM_PROG.ITEM_PUT")] == (
        Severity.BREAKING,
        "oncrpc.procedure-removed",
    )
    assert _grades(removed, _PROGRAM)[("added", "ITEM_PROG.ITEM_PROG.ITEM_PUT")] == (
        Severity.SAFE,
        "oncrpc.procedure-added",
    )
    retyped = _PROGRAM.replace("int ITEM_PUT(item) = 2;", "lookup ITEM_PUT(item) = 2;")
    assert _grades(_PROGRAM, retyped)[("modified", "ITEM_PROG.ITEM_PROG.ITEM_PUT")] == (
        Severity.BREAKING,
        "oncrpc.procedure-signature-changed",
    )
    renumbered_version = _PROGRAM.replace("    } = 1;\n} = 0x20000010;", "    } = 2;\n} = 0x20000010;")
    grades = _grades(_PROGRAM, renumbered_version)
    assert grades[("modified", "ITEM_PROG.ITEM_PROG")] == (Severity.BREAKING, "oncrpc.version-renumbered")
    assert grades[("modified", "ITEM_PROG.ITEM_PROG.ITEM_GET")] == (Severity.BREAKING, "oncrpc.version-renumbered")
    added_version = _PROGRAM.replace(
        "    } = 1;\n} = 0x20000010;",
        "    } = 1;\n    version ITEM_VERS_2 { void ITEM_NULL2(void) = 0; } = 2;\n} = 0x20000010;",
    )
    assert _grades(_PROGRAM, added_version)[("modified", "ITEM_PROG.ITEM_PROG")] == (
        Severity.SAFE,
        "oncrpc.version-added",
    )
    assert _grades(added_version, _PROGRAM)[("modified", "ITEM_PROG.ITEM_PROG")] == (
        Severity.BREAKING,
        "oncrpc.version-removed",
    )


def test_field_grades():
    added = _PROGRAM.replace("colour tint; };", "colour tint; int weight; };")
    assert _grades(_PROGRAM, added)[("added", "ITEM_PROG.item.weight")] == (Severity.BREAKING, "oncrpc.field-added")
    assert _grades(added, _PROGRAM)[("removed", "ITEM_PROG.item.weight")] == (Severity.BREAKING, "oncrpc.field-removed")
    reordered = _PROGRAM.replace("name_t name; opaque payload<1024>;", "opaque payload<1024>; name_t name;")
    grades = _grades(_PROGRAM, reordered)
    assert grades[("modified", "ITEM_PROG.item.name")] == (Severity.BREAKING, "oncrpc.field-reordered")
    narrowed = _PROGRAM.replace("opaque payload<1024>;", "opaque payload<512>;")
    assert _grades(_PROGRAM, narrowed)[("modified", "ITEM_PROG.item.payload")] == (
        Severity.BREAKING,
        "oncrpc.bound-narrowed",
    )
    unbounded = _PROGRAM.replace("opaque payload<1024>;", "opaque payload<>;")
    assert _grades(_PROGRAM, unbounded)[("modified", "ITEM_PROG.item.payload")] == (
        Severity.DANGEROUS,
        "oncrpc.bound-widened",
    )
    retyped = _PROGRAM.replace("int tags[4];", "hyper tags[4];")
    assert _grades(_PROGRAM, retyped)[("modified", "ITEM_PROG.item.tags")] == (
        Severity.BREAKING,
        "oncrpc.field-type-changed",
    )


def test_union_and_enum_grades():
    arm_added = _PROGRAM.replace("default:\n    void;", "case 1:\n    name_t missing;\ndefault:\n    void;")
    assert _grades(_PROGRAM, arm_added)[("modified", "ITEM_PROG.lookup")] == (
        Severity.DANGEROUS,
        "oncrpc.union-arm-added",
    )
    assert _grades(arm_added, _PROGRAM)[("modified", "ITEM_PROG.lookup")] == (
        Severity.BREAKING,
        "oncrpc.union-arm-removed",
    )
    discriminant = _PROGRAM.replace("switch (int status)", "switch (colour status)")
    assert _grades(_PROGRAM, discriminant)[("modified", "ITEM_PROG.lookup")] == (
        Severity.BREAKING,
        "oncrpc.union-discriminant-changed",
    )
    value_added = _PROGRAM.replace("GREEN = 1 };", "GREEN = 1, BLUE = 2 };")
    assert _grades(_PROGRAM, value_added)[("modified", "ITEM_PROG.colour")] == (
        Severity.SAFE,
        "oncrpc.enum-value-added",
    )
    assert _grades(value_added, _PROGRAM)[("modified", "ITEM_PROG.colour")] == (
        Severity.BREAKING,
        "oncrpc.enum-value-removed",
    )
    renumbered = _PROGRAM.replace("GREEN = 1 };", "GREEN = 2 };")
    assert _grades(_PROGRAM, renumbered)[("modified", "ITEM_PROG.colour")] == (
        Severity.BREAKING,
        "oncrpc.enum-value-renumbered",
    )


def test_what_the_rules_do_not_cover_falls_back_to_the_baseline():
    added_type = _PROGRAM.replace("program ITEM_PROG", "struct extra { int x; };\nprogram ITEM_PROG")
    assert _grades(_PROGRAM, added_type)[("added", "ITEM_PROG.extra")] == (Severity.SAFE, "added-entity")
