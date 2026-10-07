"""AGX-2.1 served toolset (#4533): the agent is served what apiome-rest's ``/compiled`` view shows.

* the tools are ``compile_mcp_tools`` over the enabled operations, with accepted descriptions in;
* the compile runs once per manifest change (cache by fingerprint), so a target flip or a new
  capture window reuses it and an enabled tool or accepted description recompiles;
* a missing / disabled / unpublished toolset is ``None``; an unreadable source raises.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from app.agent_tool_enrichment import apply_description_overrides
from app.catalog_conversion import build_conversion_source
from app.mcp_tool_mapping import compile_mcp_tools

from agent_runtime_fakes import (
    ALL_OPERATIONS,
    ALL_TOOLS,
    TENANT_ID,
    TOOLSET_ID,
    WRITE_OPERATIONS,
    AgentDb,
    manifest_row,
    source_item,
)
from apiome_mcp.agent_toolset_source import (
    ServedToolsetCache,
    ToolsetSourceUnavailableError,
    compile_served_toolset,
    load_served_toolset,
    load_toolset_manifest,
)


def _load(db: AgentDb, cache: ServedToolsetCache) -> Any:
    pool = db.pool()
    served = asyncio.run(load_served_toolset(pool, cache, TENANT_ID, TOOLSET_ID))  # type: ignore[arg-type]
    return served, pool


def _source_reads(pool: Any) -> int:
    return sum(1 for sql, _ in pool.statements if "source_tool_versions" in sql)


def test_the_manifest_carries_target_slugs_exposure_and_capture() -> None:
    db = AgentDb(manifest=manifest_row(body_capture_rate=0.5))
    manifest = asyncio.run(load_toolset_manifest(db.pool(), TENANT_ID, TOOLSET_ID))  # type: ignore[arg-type]
    assert manifest is not None
    assert (manifest.target, manifest.tenant_slug, manifest.project_slug, manifest.version_label) == (
        "mock",
        "acme",
        "petstore",
        "1.0.0",
    )
    assert manifest.exposed == ALL_OPERATIONS
    assert manifest.body_capture.rate == 0.5


def test_the_manifest_carries_the_write_op_flags() -> None:
    db = AgentDb()
    manifest = asyncio.run(load_toolset_manifest(db.pool(), TENANT_ID, TOOLSET_ID))  # type: ignore[arg-type]
    assert manifest is not None
    assert manifest.write_ops == frozenset(WRITE_OPERATIONS)


def test_the_write_op_flags_do_not_change_the_compile_key() -> None:
    db = AgentDb(manifest=manifest_row(write_ops=[]))
    bare = asyncio.run(load_toolset_manifest(db.pool(), TENANT_ID, TOOLSET_ID))  # type: ignore[arg-type]
    flagged = asyncio.run(load_toolset_manifest(AgentDb().pool(), TENANT_ID, TOOLSET_ID))  # type: ignore[arg-type]
    assert bare is not None and flagged is not None
    assert bare.write_ops == frozenset() and bare.fingerprint() == flagged.fingerprint()


def test_the_manifest_sql_reads_only_enabled_write_ops() -> None:
    from apiome_mcp.agent_toolset_source import _MANIFEST

    assert "tt.enabled AND tt.write_op" in _MANIFEST and "AS write_ops" in _MANIFEST


@pytest.mark.parametrize("manifest", [None, manifest_row(available=False)])
def test_an_unavailable_toolset_is_none(manifest: Any) -> None:
    served, _ = _load(AgentDb(manifest=manifest), ServedToolsetCache())
    assert served is None


def test_the_served_tools_match_the_rest_compiled_view() -> None:
    served, _ = _load(AgentDb(), ServedToolsetCache())
    assert set(served.tools) == ALL_TOOLS
    api = build_conversion_source(source_item()).api
    expected = compile_mcp_tools(api, exposed=ALL_OPERATIONS).mcp_tools()
    assert [tool.definition.to_mcp() for tool in served.tools.values()] == expected


def test_only_enabled_operations_are_served() -> None:
    served, _ = _load(AgentDb(manifest=manifest_row(exposed=["GET /pets"])), ServedToolsetCache())
    assert set(served.tools) == {"listPets"}


def test_accepted_descriptions_are_served_and_others_are_not() -> None:
    accepted = [
        {"target_key": "GET /pets", "operation_key": "GET /pets", "accepted_description": "Every pet in the store."},
        {"target_key": "POST /pets", "operation_key": "POST /pets", "accepted_description": "Not exposed."},
    ]
    served, _ = _load(AgentDb(manifest=manifest_row(exposed=["GET /pets"], accepted=accepted)), ServedToolsetCache())
    api = build_conversion_source(source_item()).api
    patched = apply_description_overrides(api, {"GET /pets": "Every pet in the store."})
    assert served.tools["listPets"].definition == compile_mcp_tools(patched, exposed=["GET /pets"]).tools[0]
    assert "Every pet in the store." in (served.tools["listPets"].definition.description or "")


def test_the_compile_is_cached_until_the_tools_change() -> None:
    cache = ServedToolsetCache()
    db = AgentDb()
    _, first = _load(db, cache)
    db.manifest = manifest_row(target="prod", body_capture_rate=0.1)
    served, second = _load(db, cache)
    assert (_source_reads(first), _source_reads(second)) == (1, 0)
    assert served.manifest.target == "prod"

    db.manifest = manifest_row(exposed=["GET /pets"])
    served, third = _load(db, cache)
    assert _source_reads(third) == 1
    assert set(served.tools) == {"listPets"}


def test_the_cache_is_bounded() -> None:
    cache = ServedToolsetCache(max_entries=1)
    db = AgentDb()
    _load(db, cache)
    db.manifest = manifest_row(toolset_id="99999999-9999-4999-8999-999999999999")
    _load(db, cache)
    db.manifest = manifest_row()
    _, pool = _load(db, cache)
    assert _source_reads(pool) == 1


def test_a_missing_source_raises() -> None:
    with pytest.raises(ToolsetSourceUnavailableError):
        _load(AgentDb(source=None), ServedToolsetCache())


def test_a_source_that_lost_an_enabled_operation_raises() -> None:
    db = AgentDb(manifest=manifest_row(exposed=["GET /gone"]))
    with pytest.raises(ToolsetSourceUnavailableError):
        _load(db, ServedToolsetCache())


def test_an_unparseable_source_raises() -> None:
    item = source_item()
    item["format_metadata"] = {"sourceContent": "{not json"}
    with pytest.raises(ToolsetSourceUnavailableError):
        compile_served_toolset(
            asyncio.run(load_toolset_manifest(AgentDb().pool(), TENANT_ID, TOOLSET_ID)),  # type: ignore[arg-type]
            item,
        )
