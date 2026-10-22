"""Zod schema import — FMT-8.2 (#5463).

Four layers, tested at the seams that own them:

* **detection and intake guards** — pure text, no evaluation: what the adapter claims, and which
  inputs are rejected before any user code could run;
* **the JSON Schema translation** — hand-written extractor output, so every constraint and
  declared-limit rule is pinned without a Node subprocess;
* **end to end through the extractor** — real modules, evaluated;
* **the execution boundary** — modules that loop, throw, or try to escape the sandbox to read a
  file, run a process, open a socket or read the environment. FMT-8.2's third acceptance
  criterion lives here.

The extractor-backed tests skip when the extractor is not installed, like the gRPC suite does
without ``buf``. The corpus contracts (golden snapshots, negatives, round-trip matrix) cover the
shipped fixtures.
"""

from __future__ import annotations

import time
from typing import Any, Dict

import pytest

from app import zod_parser as parser_module
from app.canonical_model import CanonicalApi, TypeKind
from app.fileset import IntakeFileset
from app.format_capability_registry import capability_for
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    get_import_source,
    load_builtin_import_sources,
)
from app.toolchain_packaging import probe_tool
from app.toolchain_runner import ToolNotAvailableError, ToolTimeoutError
from app.toolchain_sandbox import NETWORK_STRICT
from app.zod_import_source import ZOD_CAPABILITIES
from app.zod_normalizer import ZOD_EXTRAS_KEY, ZodNormalizer, translate_schema
from app.zod_parser import (
    LIMIT_DETAILS,
    PARTIAL_LIMITS,
    ZOD_SCHEMA_TOOL_KEY,
    ZodDocument,
    imports_other_zod_api,
    imports_zod,
    is_zod_module,
)

load_builtin_import_sources()

_EXTRACTOR_AVAILABLE = probe_tool(ZOD_SCHEMA_TOOL_KEY).available
needs_extractor = pytest.mark.skipif(
    not _EXTRACTOR_AVAILABLE,
    reason="bundled zod-schema-extractor not resolvable in this environment",
)


@pytest.fixture()
def adapter():
    return get_import_source("zod")


def normalize(defs: Dict[str, Any], exports=None) -> CanonicalApi:
    document = ZodDocument(
        root="m.ts",
        files=("m.ts",),
        zod_version="3.25.76",
        exports=tuple(exports if exports is not None else defs),
        schema={"$defs": defs},
    )
    return ZodNormalizer().normalize(document, include_raw=False)


def types_of(api: CanonicalApi):
    return {t.key: t for t in api.types}


def limits_of(api: CanonicalApi) -> Dict[str, list]:
    return {
        limit["construct"]: limit["locations"]
        for limit in api.extras[ZOD_EXTRAS_KEY]["capability_limits"]
    }


def field(type_, name):
    return next(f for f in type_.fields if f.name == name)


# ===========================================================================
# Adapter surface
# ===========================================================================


def test_adapter_is_registered_with_the_required_tool(adapter):
    assert adapter.key == "zod"
    assert adapter.required_tools == (ZOD_SCHEMA_TOOL_KEY,)
    assert ".ts" in adapter.declared_file_extensions()


def test_declared_unsupported_constructs_are_exactly_the_limit_vocabulary():
    assert set(ZOD_CAPABILITIES.unsupported) == set(LIMIT_DETAILS)
    entry = capability_for("zod")
    assert set(entry.canonical_projection.dropped_constructs) == set(LIMIT_DETAILS)
    assert PARTIAL_LIMITS <= set(LIMIT_DETAILS)


# ===========================================================================
# Detection
# ===========================================================================


@pytest.mark.parametrize(
    "text",
    [
        "import { z } from 'zod';\nexport const A = z.object({ id: z.string() });",
        'import { z } from "zod";\nexport const Status = z.enum(["a", "b"]);',
        "import * as z from 'zod';\nexport const A: z.ZodType<string> = z.string();",
        "import { z } from 'zod/v3';\nexport const A = z.string();",
        "import { z } from 'zod/v4';\nexport const A = z.string();",
    ],
)
def test_detects_modules_that_export_zod_schemas(adapter, text):
    assert is_zod_module(text)
    assert adapter.detect(DetectionInput(text=text)).matched


@pytest.mark.parametrize(
    "text",
    [
        "export interface A { id: string }",
        "import { z } from 'zod';\nconst Private = z.string();",
        "import { z } from 'zodiac';\nexport const A = z.string();",
        "export const A = 1;",
    ],
)
def test_does_not_claim_modules_without_exported_zod(adapter, text):
    assert not adapter.detect(DetectionInput(text=text)).matched


def test_typescript_types_adapter_leaves_zod_modules_alone():
    text = (
        "import { z } from 'zod';\nexport const A = z.string();\nexport interface B { id: string }"
    )
    assert not get_import_source("typescript-types").detect(DetectionInput(text=text)).matched


def test_zod_import_recognition():
    assert imports_zod("import { z } from 'zod'")
    assert not imports_zod("import { z } from 'zod/v4'")
    assert imports_other_zod_api("import { z } from 'zod/mini'") == "zod/mini"


# ===========================================================================
# Intake guards — nothing is evaluated
# ===========================================================================


@pytest.mark.parametrize(
    "text, code",
    [
        ("  \n", "INPUT_EMPTY"),
        ("i\x00m\x00p\x00", "INPUT_ENCODING_INVALID"),
        ("export interface A { id: string }", "FORMAT_MISMATCH"),
        ("import { z } from 'zod/v4';\nexport const A = z.string();", "FORMAT_VERSION_UNSUPPORTED"),
    ],
)
def test_guards_reject_before_any_code_runs(adapter, monkeypatch, text, code):
    def _never(*args, **kwargs):  # pragma: no cover - reaching it is the failure
        raise AssertionError("the extractor must not run for a guarded input")

    monkeypatch.setattr(parser_module, "run_tool_blocking", _never)
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse(text, source_label="m.ts")
    assert excinfo.value.code == code


def test_oversized_input_is_too_large(adapter, monkeypatch):
    monkeypatch.setattr(parser_module, "MAX_ZOD_BYTES", 16)
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse("import { z } from 'zod';\nexport const A = z.string();", source_label="m.ts")
    assert excinfo.value.code == "INPUT_TOO_LARGE"


def test_extractor_runs_under_the_strict_untrusted_code_policy(adapter, monkeypatch):
    seen = {}

    def _capture(key, **kwargs):
        seen.update(kwargs, key=key)
        raise ToolNotAvailableError(key, "zod-extract")

    monkeypatch.setattr(parser_module, "run_tool_blocking", _capture)
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse("import { z } from 'zod';\nexport const A = z.string();", source_label="m.ts")
    assert excinfo.value.code == "ADAPTER_UNAVAILABLE"
    assert seen["key"] == ZOD_SCHEMA_TOOL_KEY
    assert seen["policy"].no_network is True
    assert seen["policy"].network_enforcement == NETWORK_STRICT
    assert seen["timeout"] > parser_module.EVALUATION_BUDGET_MS / 1000


def test_a_runner_timeout_is_a_time_limit(adapter, monkeypatch):
    def _slow(key, **kwargs):
        raise ToolTimeoutError(key, 30.0)

    monkeypatch.setattr(parser_module, "run_tool_blocking", _slow)
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse("import { z } from 'zod';\nexport const A = z.string();", source_label="m.ts")
    assert excinfo.value.code == "INPUT_TIME_LIMIT"


def test_fileset_without_a_typescript_root_is_rejected(adapter):
    fileset = IntakeFileset.from_members({"notes.md": "# hi", "a.ts": "x"}, root="notes.md")
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse_fileset(fileset)
    assert excinfo.value.code == "INPUT_SEMANTIC_INVALID"


# ===========================================================================
# JSON Schema → canonical
# ===========================================================================


def test_constraints_become_canonical_constraints():
    api = normalize(
        {
            "User": {
                "type": "object",
                "properties": {
                    "handle": {
                        "type": "string",
                        "minLength": 2,
                        "maxLength": 32,
                        "pattern": "^[a-z]+$",
                    },
                    "email": {"type": "string", "format": "email"},
                    "age": {"type": "integer", "minimum": 0, "exclusiveMaximum": 150},
                    "score": {"type": "number", "multipleOf": 0.5},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 5,
                    },
                },
                "required": ["handle", "email", "age", "score", "tags"],
            }
        }
    )
    user = types_of(api)["User"]
    handle = field(user, "handle").constraints
    assert (handle.min_length, handle.max_length, handle.pattern) == (2, 32, "^[a-z]+$")
    assert field(user, "email").constraints.format == "email"
    age = field(user, "age")
    assert age.type.name == "integer"
    assert (age.constraints.minimum, age.constraints.exclusive_maximum) == (0, 150)
    assert field(user, "score").constraints.multiple_of == 0.5
    tags = field(user, "tags")
    assert (tags.constraints.min_items, tags.constraints.max_items) == (1, 5)


def test_optional_nullable_and_default():
    api = normalize(
        {
            "Order": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "note": {"type": "string"},
                    "cancelledAt": {
                        "anyOf": [{"type": "string", "format": "date-time"}, {"type": "null"}]
                    },
                    "status": {"type": "string", "enum": ["new", "paid"], "default": "new"},
                },
                "required": ["id", "cancelledAt"],
            }
        }
    )
    order = types_of(api)["Order"]
    assert field(order, "id").type.nullable is False
    assert field(order, "note").type.nullable is True
    cancelled = field(order, "cancelledAt")
    assert cancelled.type.nullable is True and cancelled.constraints.format == "date-time"
    status = field(order, "status")
    assert status.default == "new" and status.constraints.enum == ["new", "paid"]


def test_enum_export_and_discriminated_union():
    api = normalize(
        {
            "Status": {"type": "string", "enum": ["new", "paid"]},
            "Shape": {
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {"kind": {"const": "circle"}, "r": {"type": "number"}},
                        "required": ["kind", "r"],
                    },
                    {
                        "type": "object",
                        "properties": {"kind": {"const": "square"}, "s": {"type": "number"}},
                        "required": ["kind", "s"],
                    },
                ],
                "x-zod-discriminator": "kind",
            },
        }
    )
    types = types_of(api)
    assert types["Status"].kind is TypeKind.ENUM
    assert types["Shape"].kind is TypeKind.UNION
    assert types["Shape"].union_members == ["Shape_circle", "Shape_square"]


def test_refs_records_maps_and_recursion():
    api = normalize(
        {
            "Node": {
                "type": "object",
                "properties": {
                    "children": {"type": "array", "items": {"$ref": "#/$defs/Node"}},
                    "attrs": {
                        "type": "object",
                        "propertyNames": {"type": "string"},
                        "additionalProperties": {"type": "number"},
                    },
                },
                "required": ["children", "attrs"],
            }
        }
    )
    types = types_of(api)
    node = types["Node"]
    assert field(node, "children").type.item.name == "Node"
    attrs = types[field(node, "attrs").type.name]
    assert attrs.kind is TypeKind.MAP and attrs.value_type.name == "number"


def test_strict_and_passthrough_are_recorded_on_the_record():
    api = normalize(
        {
            "Strict": {
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "required": ["a"],
                "additionalProperties": False,
            },
            "Loose": {
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "required": ["a"],
                "additionalProperties": True,
            },
        }
    )
    types = types_of(api)
    assert types["Strict"].extras["zod_unknown_keys"] == "strict"
    assert types["Loose"].extras["zod_unknown_keys"] == "passthrough"


def test_catchall_is_a_declared_additional_properties_limit():
    api = normalize(
        {
            "Bag": {
                "type": "object",
                "properties": {"known": {"type": "string"}},
                "required": ["known"],
                "additionalProperties": {"type": "string"},
            }
        }
    )
    assert limits_of(api)["zod.additional_properties"] == ["Bag"]


def test_partial_limits_keep_the_shape_and_are_declared():
    api = normalize(
        {
            "Range": {
                "type": "object",
                "properties": {"start": {"type": "number"}, "end": {"type": "number"}},
                "required": ["start", "end"],
                "x-zod-limits": ["zod.refine"],
            },
            "Slug": {"type": "string", "x-zod-limits": ["zod.transform"]},
            "OrderId": {"type": "string", "format": "uuid", "x-zod-limits": ["zod.brand"]},
            "Query": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "x-zod-limits": ["zod.coerce"]}},
            },
        }
    )
    types = types_of(api)
    assert {f.name for f in types["Range"].fields} == {"start", "end"}
    assert types["OrderId"].constraints.format == "uuid"
    limits = limits_of(api)
    assert limits["zod.refine"] == ["Range"]
    assert limits["zod.transform"] == ["Slug"]
    assert limits["zod.brand"] == ["OrderId"]
    assert limits["zod.coerce"] == ["Query.limit"]


def test_shapeless_constructs_are_left_out_never_any():
    api = normalize(
        {
            "Handler": {"x-zod-unsupported": "zod.function", "description": "function schema"},
            "Holder": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "check": {"x-zod-unsupported": "zod.custom"},
                    "later": {"x-zod-unsupported": "zod.promise"},
                },
                "required": ["id", "check", "later"],
            },
        }
    )
    types = types_of(api)
    assert "Handler" not in types
    assert [f.name for f in types["Holder"].fields] == ["id"]
    limits = limits_of(api)
    assert limits["zod.function"] == ["Handler"]
    assert limits["zod.custom"] == ["Holder.check"]
    assert limits["zod.promise"] == ["Holder.later"]
    assert all(f.type.name != "any" for t in api.types for f in t.fields)


def test_identity_prefers_the_first_object_schema():
    api = normalize(
        {
            "Status": {"type": "string", "enum": ["a"]},
            "Order": {"type": "object", "properties": {}},
        },
        exports=["Status", "Order"],
    )
    assert api.identity.name == "Order"


def test_a_sibling_schema_appears_only_because_it_is_referenced():
    api = normalize(
        {
            "Shipment": {
                "type": "object",
                "properties": {"to": {"$ref": "#/$defs/Address"}},
                "required": ["to"],
            },
            "Address": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
        exports=["Shipment"],
    )
    assert set(types_of(api)) == {"Shipment", "Address"}
    assert api.extras[ZOD_EXTRAS_KEY]["exports"] == ["Shipment"]


def test_translate_handles_tuples_and_any():
    node = translate_schema(
        {"type": "array", "prefixItems": [{"type": "string"}], "items": {"type": "number"}}
    )
    assert node["kind"] == "tuple" and node["elements"][-1]["rest"] is True
    assert translate_schema({})["name"] == "any"
    assert translate_schema({"x-zod-type": "unknown"})["name"] == "unknown"


# ===========================================================================
# End to end through the extractor
# ===========================================================================


def _import(adapter, text: str) -> CanonicalApi:
    return adapter.normalize(adapter.parse(text, source_label="schemas.ts"))


@needs_extractor
def test_a_module_imports_with_its_constraints(adapter):
    api = _import(
        adapter,
        """
        import { z } from 'zod';
        export const Order = z.object({
          id: z.string().uuid(),
          sku: z.string().regex(/^[A-Z]{3}-\\d{4}$/),
          quantity: z.number().int().positive().max(99),
          note: z.string().max(200).optional(),
          placedAt: z.string().datetime(),
        }).describe('An order.');
        """,
    )
    order = types_of(api)["Order"]
    assert order.description == "An order."
    assert field(order, "id").constraints.format == "uuid"
    assert field(order, "sku").constraints.pattern == "^[A-Z]{3}-\\d{4}$"
    quantity = field(order, "quantity")
    assert quantity.type.name == "integer"
    assert (quantity.constraints.exclusive_minimum, quantity.constraints.maximum) == (0, 99)
    assert field(order, "note").type.nullable is True
    assert field(order, "placedAt").constraints.format == "date-time"


@needs_extractor
def test_refinements_and_transforms_are_declared(adapter):
    api = _import(
        adapter,
        """
        import { z } from 'zod';
        export const Range = z.object({ a: z.number(), b: z.number() }).refine((v) => v.b > v.a);
        export const Slug = z.string().trim().toLowerCase();
        export const Fn = z.function();
        """,
    )
    limits = limits_of(api)
    assert limits["zod.refine"] == ["Range"]
    assert limits["zod.transform"] == ["Slug"]
    assert limits["zod.function"] == ["Fn"]
    assert "Fn" not in types_of(api)


@needs_extractor
def test_a_fileset_resolves_schemas_across_modules(adapter):
    fileset = IntakeFileset.from_members(
        {
            "index.ts": (
                "import { z } from 'zod';\nimport { Money } from './money';\n"
                "export const Order = z.object({ total: Money });\n"
            ),
            "money.ts": (
                "import { z } from 'zod';\n"
                "export const Money = z.object({ value: z.number().int(), currency: z.string().length(3) });\n"
            ),
        },
        root="index.ts",
    )
    api = adapter.normalize(adapter.parse_fileset(fileset))
    types = types_of(api)
    assert field(types["Order"], "total").type.name == "Money"
    assert field(types["Money"], "currency").constraints.max_length == 3


@needs_extractor
def test_an_import_outside_the_upload_is_unresolved(adapter):
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse(
            "import { z } from 'zod';\nimport { X } from './elsewhere';\nexport const A = z.object({ x: X });\n",
            source_label="a.ts",
        )
    assert excinfo.value.code == "INPUT_REFERENCE_UNRESOLVED"


@needs_extractor
def test_a_package_other_than_zod_is_unresolved(adapter):
    with pytest.raises(ImportSourceError) as excinfo:
        # The import is used: TypeScript drops an unused one before anything is evaluated.
        adapter.parse(
            "import { z } from 'zod';\nimport fs from 'fs';\nexport const A = z.string().describe(String(fs));\n",
            source_label="a.ts",
        )
    assert excinfo.value.code == "INPUT_REFERENCE_UNRESOLVED"


@needs_extractor
def test_syntax_errors_are_malformed_or_truncated(adapter):
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse(
            "import { z } from 'zod';\nexport const A = z.object({ a: z.string( });\nexport const B = 1;\n",
            source_label="a.ts",
        )
    assert excinfo.value.code == "INPUT_MALFORMED"
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse(
            "import { z } from 'zod';\nexport const A = z.object({\n  a: z.str", source_label="a.ts"
        )
    assert excinfo.value.code == "INPUT_TRUNCATED"


# ===========================================================================
# The execution boundary
# ===========================================================================

_ESCAPE = "const host = (z as any).constructor.constructor('return process')();\n"


@needs_extractor
def test_a_module_that_throws_fails_cleanly(adapter):
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse(
            "import { z } from 'zod';\nthrow new Error('boom');\nexport const A = z.string();\n",
            source_label="a.ts",
        )
    assert excinfo.value.code == "INPUT_SEMANTIC_INVALID"
    assert "boom" in str(excinfo.value)


@needs_extractor
@pytest.mark.parametrize(
    "body",
    [
        "while (true) {}\nexport const A = z.string();",
        "export const A = z.lazy(() => { while (true) {} });",
        "export const A = z.object({ x: z.string().default(() => { while (true) {} return ''; }) });",
    ],
    ids=["loop-at-import", "loop-in-lazy-getter", "loop-in-default"],
)
def test_an_endless_loop_fails_within_budget(adapter, body):
    started = time.monotonic()
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse(f"import {{ z }} from 'zod';\n{body}\n", source_label="a.ts")
    elapsed = time.monotonic() - started
    assert excinfo.value.code == "INPUT_TIME_LIMIT"
    assert elapsed < parser_module.EVALUATION_BUDGET_MS / 1000 + 10


@needs_extractor
@pytest.mark.parametrize(
    "attack, message",
    [
        ("host.getBuiltinModule('fs').readFileSync('/etc/hostname', 'utf8');", "allow-fs-read"),
        ("host.getBuiltinModule('child_process').execSync('id');", "allow-child-process"),
        ("host.getBuiltinModule('net').connect(80, '1.1.1.1');", "network access is disabled"),
    ],
    ids=["read-a-file", "run-a-process", "open-a-socket"],
)
def test_escaping_the_vm_still_meets_the_walls(adapter, attack, message):
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse(
            f"import {{ z }} from 'zod';\n{_ESCAPE}{attack}\nexport const A = z.string();\n",
            source_label="a.ts",
        )
    assert excinfo.value.code == "INPUT_SEMANTIC_INVALID"
    assert message in str(excinfo.value)


@needs_extractor
def test_escaped_code_finds_an_empty_environment(adapter):
    api = _import(
        adapter,
        f"import {{ z }} from 'zod';\n{_ESCAPE}export const Keys = z.literal(JSON.stringify(Object.keys(host.env)));\n",
    )
    assert types_of(api)["Keys"].constraints.enum == ["[]"]
