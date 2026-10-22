"""tRPC router import — FMT-8.3 (#5464).

Three layers:

* **detection and intake guards** — pure text: what the adapter claims (and what it leaves to the
  Zod and TypeScript-types adapters), and the inputs rejected before evaluation;
* **the normalizer** — hand-built router descriptions, so operation kinds, the service hierarchy,
  payload naming, chained inputs and the declared limits are pinned without a subprocess;
* **end to end through the extractor** — real routers, evaluated in the FMT-8.2 sandbox.

The extractor-backed tests skip when the extractor is not installed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from app import zod_parser
from app.canonical_model import CanonicalApi, MessageRole, OperationKind, StreamingMode, TypeKind
from app.fileset import IntakeFileset
from app.format_capability_registry import capability_for
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    get_import_source,
    load_builtin_import_sources,
)
from app.toolchain_packaging import probe_tool
from app.trpc_import_source import TRPC_CAPABILITIES
from app.trpc_normalizer import TRPC_EXTRAS_KEY, TrpcNormalizer
from app.trpc_parser import LIMIT_DETAILS, PARTIAL_LIMITS, TrpcDocument, is_trpc_module
from app.zod_parser import ZOD_SCHEMA_TOOL_KEY

load_builtin_import_sources()

needs_extractor = pytest.mark.skipif(
    not probe_tool(ZOD_SCHEMA_TOOL_KEY).available,
    reason="bundled zod-schema-extractor not resolvable in this environment",
)

_ROUTER = (
    "import { initTRPC } from '@trpc/server';\nimport { z } from 'zod';\n"
    "const t = initTRPC.create();\n"
)


@pytest.fixture()
def adapter():
    return get_import_source("trpc")


def procedure(
    path: str,
    type_: str = "query",
    inputs: Optional[List[Any]] = None,
    output: Any = None,
    meta: Any = None,
) -> Dict[str, Any]:
    return {"path": path, "type": type_, "inputs": inputs or [], "output": output, "meta": meta}


def normalize(
    procedures: List[Dict[str, Any]],
    defs: Optional[Dict[str, Any]] = None,
    *,
    name="appRouter",
    lazy=(),
) -> CanonicalApi:
    document = TrpcDocument(
        root="router.ts",
        files=("router.ts",),
        zod_version="3.25.76",
        routers=({"name": name, "procedures": procedures, "lazy": list(lazy)},),
        schema={"$defs": defs or {}},
    )
    return TrpcNormalizer().normalize(document, include_raw=False)


def operations(api: CanonicalApi):
    return {op.key: op for service in api.services for op in service.operations}


def limits_of(api: CanonicalApi):
    return {
        limit["construct"]: limit["locations"] for limit in api.extras[TRPC_EXTRAS_KEY]["capability_limits"]
    }


OBJ = {
    "type": "object",
    "properties": {"id": {"type": "string", "minLength": 1}},
    "required": ["id"],
}


# ===========================================================================
# Adapter surface and detection
# ===========================================================================


def test_adapter_is_registered(adapter):
    assert adapter.key == "trpc"
    assert adapter.paradigm.value == "rpc"
    assert adapter.required_tools == (ZOD_SCHEMA_TOOL_KEY,)


def test_declared_constructs_match_the_registry():
    assert set(TRPC_CAPABILITIES.unsupported) == set(LIMIT_DETAILS)
    assert set(capability_for("trpc").canonical_projection.dropped_constructs) == set(LIMIT_DETAILS)
    assert PARTIAL_LIMITS <= set(LIMIT_DETAILS)


def test_detects_a_router_module(adapter):
    text = _ROUTER + "export const appRouter = t.router({});\n"
    assert is_trpc_module(text)
    assert adapter.detect(DetectionInput(text=text)).matched


def test_a_router_module_is_left_alone_by_zod_and_typescript_types():
    text = _ROUTER + "export const Input = z.object({});\nexport const appRouter = t.router({});\n"
    assert not get_import_source("zod").detect(DetectionInput(text=text)).matched
    assert not get_import_source("typescript-types").detect(DetectionInput(text=text)).matched


@pytest.mark.parametrize(
    "text",
    ["import { z } from 'zod';\nexport const A = z.string();", "export interface A { id: string }"],
)
def test_does_not_claim_non_router_modules(adapter, text):
    assert not adapter.detect(DetectionInput(text=text)).matched


def test_a_module_without_trpc_is_a_format_mismatch(adapter, monkeypatch):
    def _never(*args, **kwargs):  # pragma: no cover - reaching it is the failure
        raise AssertionError("must not evaluate")

    monkeypatch.setattr(zod_parser, "run_tool_blocking", _never)
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse(
            "import { z } from 'zod';\nexport const A = z.string();\n", source_label="a.ts"
        )
    assert excinfo.value.code == "FORMAT_MISMATCH"


def test_the_extractor_is_asked_for_routers(adapter, monkeypatch):
    seen = {}

    def _capture(key, **kwargs):
        seen.update(kwargs)
        raise zod_parser.ToolNotAvailableError(key, "zod-extract")

    monkeypatch.setattr(zod_parser, "run_tool_blocking", _capture)
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse(_ROUTER + "export const r = t.router({});\n", source_label="a.ts")
    assert excinfo.value.code == "ADAPTER_UNAVAILABLE"
    assert '"routers": true' in seen["stdin"]
    assert seen["policy"].network_enforcement == "strict"


# ===========================================================================
# Normalizer
# ===========================================================================


def test_procedure_kinds_become_operation_kinds():
    api = normalize(
        [
            procedure("get", "query", [OBJ]),
            procedure("set", "mutation", [OBJ]),
            procedure("watch", "subscription", [OBJ], output=OBJ),
        ]
    )
    ops = operations(api)
    assert ops["appRouter.get"].kind is OperationKind.QUERY
    assert ops["appRouter.set"].kind is OperationKind.MUTATION
    watch = ops["appRouter.watch"]
    assert watch.kind is OperationKind.SUBSCRIPTION
    assert watch.streaming is StreamingMode.SERVER
    assert [m.role for m in watch.messages] == [MessageRole.REQUEST, MessageRole.EVENT]
    assert api.paradigm.value == "rpc" and api.protocol == "trpc"


def test_nested_routers_are_a_service_hierarchy():
    api = normalize([procedure("admin.users.list", "query", [OBJ]), procedure("version")])
    services = {s.key: s for s in api.services}
    assert set(services) == {"appRouter", "appRouter.admin", "appRouter.admin.users"}
    assert services["appRouter.admin.users"].extras["trpc_parent"] == "appRouter.admin"
    assert services["appRouter.admin"].extras["trpc_parent"] == "appRouter"
    assert "trpc_parent" not in services["appRouter"].extras
    assert [o.key for o in services["appRouter.admin.users"].operations] == [
        "appRouter.admin.users.list"
    ]
    assert operations(api)["appRouter.admin.users.list"].extras["trpc_path"] == "admin.users.list"


def test_inline_payloads_are_named_after_the_procedure_with_constraints():
    api = normalize([procedure("invoice.list", "query", [OBJ], output=OBJ)])
    types = {t.key: t for t in api.types}
    request = operations(api)["appRouter.invoice.list"].messages[0]
    assert request.payload.name == "InvoiceListInput" and request.required is True
    field = types["InvoiceListInput"].fields[0]
    assert field.constraints.min_length == 1
    assert "InvoiceListOutput" in types


def test_a_named_schema_payload_references_its_type():
    api = normalize([procedure("byId", "query", [{"$ref": "#/$defs/Order"}])], defs={"Order": OBJ})
    assert operations(api)["appRouter.byId"].messages[0].payload.name == "Order"
    assert {t.key for t in api.types} == {"Order"}


def test_chained_inputs_merge_into_one_record():
    second = {"type": "object", "properties": {"b": {"type": "number"}}, "required": ["b"]}
    api = normalize([procedure("chained", "query", [OBJ, second])])
    merged = {t.key: t for t in api.types}["ChainedInput"]
    assert merged.kind is TypeKind.RECORD
    assert {f.name for f in merged.fields} == {"id", "b"}


def test_a_non_schema_validator_keeps_the_operation_without_a_payload():
    api = normalize(
        [
            procedure("handWritten", "query", [{"x-trpc-unsupported": "trpc.non_schema_input"}]),
            procedure("ok", "query", [OBJ]),
        ]
    )
    hand = operations(api)["appRouter.handWritten"]
    assert hand.messages == []
    assert limits_of(api)["trpc.non_schema_input"] == ["appRouter.handWritten"]


def test_meta_and_zod_limits_on_payloads():
    refined = dict(OBJ, **{"x-zod-limits": ["zod.refine"]})
    api = normalize([procedure("write", "mutation", [refined], meta={"scope": "w"})])
    assert operations(api)["appRouter.write"].extras["trpc_meta"] == {"scope": "w"}
    assert limits_of(api)["zod.refine"] == ["WriteInput"]


def test_lazy_routers_are_declared():
    api = normalize([procedure("ping", "query", [OBJ])], lazy=["billing"])
    assert limits_of(api)["trpc.lazy_router"] == ["appRouter.billing"]


def test_several_routers_qualify_type_names():
    document = TrpcDocument(
        root="r.ts",
        files=("r.ts",),
        zod_version="3.25.76",
        routers=(
            {"name": "a", "procedures": [procedure("ping", "query", [OBJ])], "lazy": []},
            {"name": "b", "procedures": [procedure("ping", "query", [OBJ])], "lazy": []},
        ),
        schema={"$defs": {}},
    )
    api = TrpcNormalizer().normalize(document, include_raw=False)
    assert {t.key for t in api.types} == {"APingInput", "BPingInput"}


# ===========================================================================
# End to end through the extractor
# ===========================================================================


@needs_extractor
def test_a_router_imports_end_to_end(adapter):
    api = adapter.normalize(
        adapter.parse(
            _ROUTER
            + """
            export const Order = z.object({ id: z.string().uuid() });
            export const appRouter = t.router({
              order: t.router({
                byId: t.procedure
                  .input(z.object({ id: z.string().uuid() }))
                  .output(Order)
                  .query(() => null as any),
                cancel: t.procedure
                  .input(z.object({ id: z.string(), reason: z.string().max(200) }))
                  .mutation(() => null),
              }),
              health: t.procedure.query(() => 'ok'),
            });
            """,
            source_label="router.ts",
        )
    )
    ops = operations(api)
    assert ops["appRouter.order.byId"].kind is OperationKind.QUERY
    assert ops["appRouter.order.cancel"].kind is OperationKind.MUTATION
    assert ops["appRouter.order.byId"].messages[1].payload.name == "Order"
    cancel = {t.key: t for t in api.types}["OrderCancelInput"]
    assert {f.name: f.constraints.max_length if f.constraints else None for f in cancel.fields}[
        "reason"
    ] == 200
    assert ops["appRouter.health"].messages == []


@needs_extractor
def test_a_router_set_resolves_across_modules(adapter):
    fileset = IntakeFileset.from_members(
        {
            "root.ts": _ROUTER
            + "import { orderRouter } from './orders';\nexport const appRouter = t.router({ order: orderRouter });\n",
            "orders.ts": _ROUTER
            + "import { Money } from './schemas';\n"
            + "export const orderRouter = t.router({\n"
            + "  total: t.procedure.output(Money).query(() => null as any),\n"
            + "});\n",
            "schemas.ts": "import { z } from 'zod';\nexport const Money = z.object({ value: z.number().int() });\n",
        },
        root="root.ts",
    )
    api = adapter.normalize(adapter.parse_fileset(fileset))
    assert operations(api)["appRouter.order.total"].messages[0].payload.name == "Money"


@needs_extractor
def test_routers_that_offer_nothing_to_import_are_rejected(adapter):
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse(_ROUTER + "export const r = t.router({});\n", source_label="a.ts")
    assert excinfo.value.code == "INPUT_SEMANTIC_INVALID"
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse(
            _ROUTER
            + "export const r = t.router({ a: t.procedure.input((v: unknown) => v).query(() => 1) });\n",
            source_label="a.ts",
        )
    assert excinfo.value.code == "INPUT_SEMANTIC_INVALID"
    assert "hand-written" in str(excinfo.value)


@needs_extractor
def test_resolvers_and_middleware_never_run(adapter):
    api = adapter.normalize(
        adapter.parse(
            _ROUTER
            + """
            const authed = t.middleware(() => { throw new Error('middleware ran'); });
            export const r = t.router({
              a: t.procedure
                .use(authed)
                .input(z.object({ x: z.string() }))
                .query(() => { throw new Error('resolver ran'); }),
            });
            """,
            source_label="a.ts",
        )
    )
    assert operations(api)["r.a"].messages[0].payload.name == "AInput"


@needs_extractor
def test_an_endless_router_module_fails_within_budget(adapter):
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse(
            _ROUTER + "while (true) {}\nexport const r = t.router({});\n", source_label="a.ts"
        )
    assert excinfo.value.code == "INPUT_TIME_LIMIT"
