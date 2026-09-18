"""Tool-schema regression corpus — AGX-1.4 (#4532).

The AGX-1.1 compiler turns a published version into the toolset every tenant's agents
see, so a mapping change that renames a tool or drifts a schema breaks them all at once.
This suite pins the compiler's output for the whole examples corpus:

* **determinism gate** — each ``valid`` corpus entry is recompiled and must reproduce its
  checked-in golden (``tests/golden/toolsets/<corpus path>.json``) byte for byte;
* **MCP validity gate** — every tool in every stored golden must be a valid MCP
  ``tools/list`` entry: the compiler's contract, the MCP SDK's ``Tool`` model and the
  JSON-Schema 2020-12 metaschema;
* **store hygiene** — no golden outlives its corpus entry.

The remaining tests prove the gates bite: a drifted, missing or invalid golden fails with
a message that names the tool and the regenerate command.

Regenerate with ``uv run pytest tests/test_toolset_goldens.py --update-golden`` (from
``apiome-mcp/``), then review and commit the golden diff with the change that caused it.
See ``docs/TOOLSET_GOLDENS.md``.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from apiome_mcp.tool_compiler import MCP_TOOL_MAPPING_VERSION, McpToolset, compile_openapi_toolset
from toolset_corpus import (
    GOLDEN_ROOT,
    REGENERATE_COMMAND,
    UPDATE_OPTION,
    compile_entry,
    corpus_entries,
    corpus_entry_params,
    describe_drift,
    golden_entry_paths,
    golden_mismatch,
    golden_path,
    golden_violations,
    load_golden,
    prune_orphan_goldens,
    updating_goldens,
    write_golden,
)

_DOCS = Path(__file__).resolve().parents[1] / "docs" / "TOOLSET_GOLDENS.md"

#: A small OpenAPI document for the gate tests, so they never depend on a corpus fixture.
_ORDERS_API: dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "Orders", "version": "1"},
    "paths": {
        "/orders": {
            "get": {
                "operationId": "listOrders",
                "summary": "List orders",
                "parameters": [{"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1}}],
                "responses": {
                    "200": {
                        "description": "The orders",
                        "content": {
                            "application/json": {
                                "schema": {"type": "array", "items": {"type": "object", "properties": {"id": {}}}}
                            }
                        },
                    }
                },
            }
        },
        "/orders/{id}": {
            "delete": {
                "operationId": "deleteOrder",
                "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"204": {"description": "Deleted"}},
            }
        },
    },
}


def _orders() -> McpToolset:
    return compile_openapi_toolset(_ORDERS_API)


def _orders_golden() -> dict[str, Any]:
    document = json.loads(_orders().serialize())
    assert isinstance(document, dict)
    return document


def _tool(document: dict[str, Any], name: str) -> dict[str, Any]:
    """The tool called ``name`` in a golden document."""
    tool = next(tool for tool in document["tools"] if tool["name"] == name)
    assert isinstance(tool, dict)
    return tool


#: Where ``listOrders`` sits in the compiled toolset (canonical order puts it second).
_LIST = [tool["name"] for tool in _orders_golden()["tools"]].index("listOrders")


def _render(document: dict[str, Any]) -> str:
    """Serialize a golden document the way :meth:`McpToolset.serialize` does."""
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


# ===========================================================================
# Determinism gate
# ===========================================================================


@pytest.mark.parametrize("entry", corpus_entry_params())
def test_the_compiled_toolset_reproduces_its_golden(entry: Any, request: pytest.FixtureRequest) -> None:
    """Recompiling a corpus entry reproduces its golden byte for byte.

    With ``--update-golden`` the golden is rewritten from the fresh compile instead.
    """
    serialized = compile_entry(entry).serialize()
    if updating_goldens(request.config):
        write_golden(entry.path, serialized)
        return
    mismatch = golden_mismatch(entry.path, serialized)
    if mismatch is not None:
        pytest.fail(mismatch, pytrace=False)


def test_no_golden_outlives_its_corpus_entry(request: pytest.FixtureRequest) -> None:
    """Every golden maps to a corpus entry; ``--update-golden`` deletes the orphans instead.

    A golden whose entry is only skipped here (its bundled tool is missing) is not an
    orphan: it stays for the environments that can compile it.
    """
    known = [entry.path for entry in corpus_entries()]
    if updating_goldens(request.config):
        prune_orphan_goldens(known)
        return
    orphans = sorted(set(golden_entry_paths()) - set(known))
    assert not orphans, (
        f"golden toolsets with no valid corpus entry (delete them, or run `{REGENERATE_COMMAND}`):\n  "
        + "\n  ".join(orphans)
    )


# ===========================================================================
# MCP validity gate
# ===========================================================================


@pytest.mark.parametrize("entry_path", golden_entry_paths())
def test_every_golden_tool_is_mcp_valid(entry_path: str) -> None:
    """Every tool of every stored golden is a valid MCP ``tools/list`` entry.

    Runs after the determinism tests, so under ``--update-golden`` it checks the goldens
    just written; one pruned as an orphan in the same run is skipped.
    """
    path = golden_path(entry_path)
    if not path.is_file():
        pytest.skip("pruned as an orphan by --update-golden in this run")
    document = json.loads(path.read_text(encoding="utf-8"))
    problems = golden_violations(document)
    assert not problems, f"{entry_path}: golden toolset is not MCP-valid:\n  " + "\n  ".join(problems)


def test_the_goldens_carry_the_corpus_toolsets() -> None:
    """The store is the real corpus, not a handful of empty toolsets."""
    tools = 0
    for entry_path in golden_entry_paths():
        document = json.loads(golden_path(entry_path).read_text(encoding="utf-8"))
        tools += len(document["tools"])
    assert tools > 500, "the golden store should cover every tool the examples corpus compiles to"


# ===========================================================================
# The determinism gate bites
# ===========================================================================


def test_a_matching_golden_passes(tmp_path: Path) -> None:
    write_golden("openapi/orders.yaml", _orders().serialize(), root=tmp_path)
    assert golden_mismatch("openapi/orders.yaml", _orders().serialize(), root=tmp_path) is None


def test_a_missing_golden_fails_with_the_regenerate_command(tmp_path: Path) -> None:
    message = golden_mismatch("openapi/orders.yaml", _orders().serialize(), root=tmp_path)
    assert message is not None
    assert "no golden toolset" in message
    assert REGENERATE_COMMAND in message


def test_a_drifted_compile_fails_and_names_the_tool(tmp_path: Path) -> None:
    write_golden("openapi/orders.yaml", _orders().serialize(), root=tmp_path)
    drifted = _orders_golden()
    _tool(drifted, "listOrders")["description"] = "Lists every order."

    message = golden_mismatch("openapi/orders.yaml", _render(drifted), root=tmp_path)

    assert message is not None
    assert "CHANGED 'listOrders' (GET /orders): description" in message
    assert any(line.startswith("+") and "Lists every order." in line for line in message.splitlines())
    assert REGENERATE_COMMAND in message


def test_a_whitespace_only_change_still_fails_the_byte_gate(tmp_path: Path) -> None:
    write_golden("openapi/orders.yaml", _orders().serialize(), root=tmp_path)
    assert golden_mismatch("openapi/orders.yaml", _orders().serialize().rstrip("\n"), root=tmp_path) is not None


def test_a_rename_is_reported_as_a_rename_of_the_operation() -> None:
    golden = _orders_golden()
    compiled = copy.deepcopy(golden)
    _tool(compiled, "listOrders")["name"] = "list_orders"
    report = describe_drift("openapi/orders.yaml", _render(golden), _render(compiled))
    assert "RENAMED 'listOrders' → 'list_orders' (GET /orders)" in report
    assert "REMOVED" not in report and "ADDED" not in report


def test_added_and_removed_tools_are_reported_by_operation() -> None:
    golden = _orders_golden()
    compiled = copy.deepcopy(golden)
    removed = _tool(compiled, "deleteOrder")
    compiled["tools"].remove(removed)
    compiled["tools"].append({**removed, "name": "cancelOrder", "operation": "POST /orders/{id}/cancel"})
    report = describe_drift("openapi/orders.yaml", _render(golden), _render(compiled))
    assert "REMOVED 'deleteOrder' (DELETE /orders/{id})" in report
    assert "ADDED 'cancelOrder' (POST /orders/{id}/cancel)" in report


def test_a_schema_drift_names_the_changed_fields() -> None:
    golden = _orders_golden()
    compiled = copy.deepcopy(golden)
    listing = _tool(compiled, "listOrders")
    listing["inputSchema"]["properties"]["limit"]["maximum"] = 100
    listing["output"]["schema"] = {"type": "object"}
    report = describe_drift("openapi/orders.yaml", _render(golden), _render(compiled))
    assert "CHANGED 'listOrders' (GET /orders): inputSchema, output" in report


def test_a_mapping_version_bump_is_reported() -> None:
    golden = _orders_golden()
    compiled = {**golden, "mappingVersion": MCP_TOOL_MAPPING_VERSION + 1}
    report = describe_drift("openapi/orders.yaml", _render(golden), _render(compiled))
    assert f"mappingVersion: {MCP_TOOL_MAPPING_VERSION} → {MCP_TOOL_MAPPING_VERSION + 1}" in report


def test_a_reorder_is_reported_when_nothing_else_changed() -> None:
    golden = _orders_golden()
    compiled = {**golden, "tools": list(reversed(golden["tools"]))}
    report = describe_drift("openapi/orders.yaml", _render(golden), _render(compiled))
    assert "tool order changed" in report


def test_a_corrupt_golden_is_reported_as_such() -> None:
    report = describe_drift("openapi/orders.yaml", "{not json", _orders().serialize())
    assert "the stored golden is not valid JSON" in report


def test_a_long_diff_is_truncated() -> None:
    golden = _orders_golden()
    compiled = copy.deepcopy(golden)
    _tool(compiled, "listOrders")["inputSchema"]["properties"] = {
        f"arg{index}": {"type": "string"} for index in range(200)
    }
    report = describe_drift("openapi/orders.yaml", _render(golden), _render(compiled))
    assert "more diff lines" in report
    assert len(report.splitlines()) < 100


# ===========================================================================
# The MCP validity gate bites
# ===========================================================================


def test_a_compiled_toolset_is_mcp_valid() -> None:
    assert golden_violations(_orders_golden()) == []


def _mutated(path: list[Any], value: Any) -> dict[str, Any]:
    """The orders golden with the value at ``path`` replaced (a ``None`` value deletes it)."""
    document = _orders_golden()
    node: Any = document
    for key in path[:-1]:
        node = node[key]
    if value is None:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return document


def _listing(*path: Any) -> list[Any]:
    """A :func:`_mutated` path into the ``listOrders`` tool."""
    return ["tools", _LIST, *path]


@pytest.mark.parametrize(
    ("document", "pointer"),
    [
        pytest.param([], "/:", id="not-an-object"),
        pytest.param(_mutated(["mappingVersion"], 0), "/mappingVersion", id="stale-mapping-version"),
        pytest.param(_mutated(["tools"], {}), "/tools", id="tools-not-an-array"),
        pytest.param(_mutated(_listing(), "listOrders"), f"/tools/{_LIST}: must be an object", id="tool-not-an-object"),
        pytest.param(_mutated(_listing("name"), "list orders!"), f"/tools/{_LIST}/name", id="illegal-name"),
        pytest.param(_mutated(_listing("description"), " "), f"/tools/{_LIST}/description", id="blank-description"),
        pytest.param(_mutated(_listing("inputSchema"), None), f"/tools/{_LIST}/inputSchema", id="no-input-schema"),
        pytest.param(
            _mutated(_listing("inputSchema", "type"), "string"),
            f"/tools/{_LIST}/inputSchema/type",
            id="non-object-root",
        ),
        pytest.param(
            _mutated(_listing("inputSchema", "properties", "limit", "$ref"), "#/$defs/Limit"),
            f"/tools/{_LIST}/inputSchema/properties/limit",
            id="ref-keyword",
        ),
        pytest.param(
            _mutated(_listing("inputSchema", "properties", "limit", "pattern"), "("),
            f"/tools/{_LIST}/inputSchema/properties/limit/pattern",
            id="metaschema-invalid-regex",
        ),
        pytest.param(_mutated(_listing("title"), 5), f"/tools/{_LIST}/title: MCP SDK rejects it", id="sdk-rejects"),
        pytest.param(
            _mutated(_listing("output", "schema", "not"), {"type": "null"}),
            f"/tools/{_LIST}/output/schema",
            id="output-schema-outside-subset",
        ),
        pytest.param(
            _mutated(["tools", 1 - _LIST, "name"], "listOrders"),
            "/tools/1/name",  # reported on the second of the two same-named tools
            id="duplicate-name",
        ),
    ],
)
def test_each_contract_breach_is_reported_at_its_pointer(document: Any, pointer: str) -> None:
    problems = golden_violations(document)
    assert any(problem.startswith(pointer) for problem in problems), problems


# ===========================================================================
# Store and update workflow
# ===========================================================================


def test_goldens_mirror_the_corpus_path_and_keep_its_extension(tmp_path: Path) -> None:
    assert golden_path("openapi/x.yaml", root=tmp_path) == tmp_path / "openapi" / "x.yaml.json"
    assert golden_path("asyncapi/06-set/root.yaml").is_relative_to(GOLDEN_ROOT)


def test_writing_a_golden_only_touches_changed_files(tmp_path: Path) -> None:
    serialized = _orders().serialize()
    assert write_golden("openapi/orders.yaml", serialized, root=tmp_path) is True
    assert write_golden("openapi/orders.yaml", serialized, root=tmp_path) is False
    assert load_golden("openapi/orders.yaml", root=tmp_path) == serialized.encode("utf-8")
    assert write_golden("openapi/orders.yaml", serialized.replace("Orders", "Order"), root=tmp_path) is True
    assert golden_entry_paths(root=tmp_path) == ["openapi/orders.yaml"]


def test_pruning_deletes_orphans_and_their_empty_directories(tmp_path: Path) -> None:
    serialized = _orders().serialize()
    for entry_path in ("openapi/kept.yaml", "graphql/gone.graphql", "asyncapi/06-set/root.yaml"):
        write_golden(entry_path, serialized, root=tmp_path)

    removed = prune_orphan_goldens(["openapi/kept.yaml"], root=tmp_path)

    assert removed == ["asyncapi/06-set/root.yaml", "graphql/gone.graphql"]
    assert golden_entry_paths(root=tmp_path) == ["openapi/kept.yaml"]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["openapi"]


def test_an_empty_store_lists_no_goldens(tmp_path: Path) -> None:
    assert golden_entry_paths(root=tmp_path / "missing") == []


def test_the_update_flag_is_registered(request: pytest.FixtureRequest) -> None:
    assert isinstance(request.config.getoption(UPDATE_OPTION), bool)


def test_the_regenerate_command_runs_this_suite_and_is_documented() -> None:
    assert Path(__file__).name in REGENERATE_COMMAND
    assert REGENERATE_COMMAND in _DOCS.read_text(encoding="utf-8")
