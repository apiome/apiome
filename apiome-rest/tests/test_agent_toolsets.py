"""Agent toolset curation rules — AGX-1.2 (#4530).

The safe-by-default policy, tested without HTTP: how an operation is classified as a read or a
write op, how a new toolset is seeded from a version's canonical model (reads on, writes and
deprecated operations off, names exactly as the AGX-1.1 compiler gives them), and the service
functions' refusals over the in-memory :class:`~agent_toolset_fakes.FakeToolsetStore`.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest
from agent_toolset_fakes import FakeToolsetStore

import app.agent_toolsets as toolsets
from app.agent_toolsets import (
    CODE_TOOL_NOT_FOUND,
    CODE_TOOLSET_EXISTS,
    CODE_TOOLSET_INVALID,
    CODE_TOOLSET_NOT_FOUND,
    CODE_TOOLSET_SOURCE_UNAVAILABLE,
    CODE_VERSION_NOT_FOUND,
    CODE_VERSION_UNPUBLISHED,
    CODE_WRITE_OP_UNCONFIRMED,
    AgentToolsetCreate,
    AgentToolsetError,
    AgentToolsetUpdate,
    AgentToolUpdate,
    audit_tool_detail,
    create_agent_toolset,
    delete_agent_toolset,
    get_agent_toolset,
    is_write_operation,
    seed_tools,
    update_agent_toolset,
    update_agent_toolset_tool,
)
from app.canonical_model import Operation, OperationKind
from app.database import db
from app.export_source import ExportSourceError
from app.mcp_tool_mapping import compile_mcp_tools
from app.openapi_normalizer import OpenApiNormalizer

_TENANT = "11111111-1111-4111-8111-111111111111"
_OTHER_TENANT = "99999999-9999-4999-8999-999999999999"
_ACTOR = "33333333-3333-4333-8333-333333333333"
_MISSING = "77777777-7777-4777-8777-777777777777"


def _ok(description: str = "ok") -> Dict[str, Any]:
    return {"200": {"description": description}}


#: Every verb, plus a deprecated read, so the seed rules are all exercised by one document.
PETSTORE: Dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Pets", "version": "1.0.0"},
    "paths": {
        "/pets": {
            "get": {"operationId": "listPets", "responses": _ok()},
            "head": {"operationId": "headPets", "responses": _ok()},
            "post": {"operationId": "createPet", "responses": _ok()},
        },
        "/pets/{id}": {
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "get": {"operationId": "getPet", "responses": _ok()},
            "put": {"operationId": "replacePet", "responses": _ok()},
            "patch": {"operationId": "updatePet", "responses": _ok()},
            "delete": {"operationId": "deletePet", "responses": _ok()},
        },
        "/legacy": {
            "get": {"operationId": "legacyList", "deprecated": True, "responses": _ok()},
        },
    },
}


def _api():
    return OpenApiNormalizer().normalize(PETSTORE)


@pytest.fixture
def store(monkeypatch) -> FakeToolsetStore:
    """The toolset accessors, in memory, with the version loader pointed at :data:`PETSTORE`."""
    monkeypatch.setattr(toolsets, "_load_version_api", lambda *_args: _api())
    return FakeToolsetStore().install(monkeypatch, db)


def _create(store: FakeToolsetStore, **overrides: Any):
    version_id = store.seed_version(_TENANT)
    body = AgentToolsetCreate(versionId=version_id, **overrides)
    return create_agent_toolset(_TENANT, body, actor_id=_ACTOR)


def _by_operation(toolset) -> Dict[str, Any]:
    return {tool.operation: tool for tool in toolset.tools}


# ============================================================================
# Classification
# ============================================================================
@pytest.mark.parametrize(
    ("method", "write"),
    [
        ("GET", False),
        ("HEAD", False),
        ("get", False),
        (" head ", False),
        ("POST", True),
        ("PUT", True),
        ("PATCH", True),
        ("DELETE", True),
        ("OPTIONS", True),
        ("TRACE", True),
    ],
)
def test_http_operations_are_reads_only_for_get_and_head(method: str, write: bool) -> None:
    operation = Operation(
        key=f"{method.strip().upper()} /x",
        name="x",
        kind=OperationKind.REQUEST_RESPONSE,
        http_method=method,
        http_path="/x",
    )
    assert is_write_operation(operation) is write


@pytest.mark.parametrize(
    ("kind", "write"),
    [
        (OperationKind.QUERY, False),
        (OperationKind.MUTATION, True),
        (OperationKind.REQUEST_RESPONSE, True),  # an RPC method cannot be shown to be a read
        (OperationKind.ONE_WAY, True),
    ],
)
def test_operations_without_a_verb_are_writes_unless_they_are_queries(kind, write) -> None:
    operation = Operation(key="Svc.op", name="op", kind=kind)
    assert is_write_operation(operation) is write


# ============================================================================
# Seeding
# ============================================================================
def test_seeding_enables_reads_and_leaves_writes_and_deprecated_reads_off() -> None:
    seeds = {seed.operation_key: seed for seed in seed_tools(_api())}
    assert set(seeds) == {
        "GET /pets",
        "HEAD /pets",
        "POST /pets",
        "GET /pets/{id}",
        "PUT /pets/{id}",
        "PATCH /pets/{id}",
        "DELETE /pets/{id}",
        "GET /legacy",
    }
    enabled = {key for key, seed in seeds.items() if seed.enabled}
    assert enabled == {"GET /pets", "HEAD /pets", "GET /pets/{id}"}
    writes = {key for key, seed in seeds.items() if seed.write_op}
    assert writes == {"POST /pets", "PUT /pets/{id}", "PATCH /pets/{id}", "DELETE /pets/{id}"}
    assert seeds["GET /legacy"].write_op is False and seeds["GET /legacy"].enabled is False


def test_seeded_names_are_the_compilers_names() -> None:
    """Tool names come from compile_mcp_tools, so curation never re-derives or renames them."""
    compiled = {tool.operation: tool.name for tool in compile_mcp_tools(_api(), exposed=None).tools}
    seeds = {seed.operation_key: seed.tool_name for seed in seed_tools(_api())}
    for operation, name in compiled.items():
        assert seeds[operation] == name


def test_seeding_is_deterministic() -> None:
    assert seed_tools(_api()) == seed_tools(_api())


def test_a_model_without_callable_operations_seeds_nothing() -> None:
    schema_only = {"openapi": "3.0.3", "info": {"title": "S", "version": "1"}, "paths": {}}
    assert seed_tools(OpenApiNormalizer().normalize(schema_only)) == []


# ============================================================================
# Create
# ============================================================================
def test_a_new_toolset_exposes_only_read_operations(store) -> None:
    """Acceptance: a newly created toolset exposes only read operations by default."""
    created = _create(store)
    assert created.enabled is True and created.target == "prod"
    assert created.tool_count == 8
    assert created.enabled_write_op_count == 0
    exposed = [tool for tool in created.tools if tool.enabled]
    assert exposed and all(not tool.write_op for tool in exposed)
    assert created.enabled_tool_count == len(exposed) == 3
    assert all(tool.write_confirmed_at is None for tool in created.tools)


def test_create_honours_target_and_enabled(store) -> None:
    created = _create(store, target="mock", enabled=False)
    assert (created.target, created.enabled) == ("mock", False)


def test_create_refuses_an_unknown_or_foreign_version(store) -> None:
    foreign = store.seed_version(_OTHER_TENANT)
    for version_id in (_MISSING, foreign):
        with pytest.raises(AgentToolsetError) as caught:
            create_agent_toolset(_TENANT, AgentToolsetCreate(versionId=version_id))
        assert caught.value.code == CODE_VERSION_NOT_FOUND
    assert store.toolsets == {}


@pytest.mark.parametrize("state", [{"published": False}, {"deleted": True}])
def test_create_refuses_an_unpublished_or_deleted_version(store, state) -> None:
    version_id = store.seed_version(_TENANT, **state)
    with pytest.raises(AgentToolsetError) as caught:
        create_agent_toolset(_TENANT, AgentToolsetCreate(versionId=version_id))
    assert caught.value.code == CODE_VERSION_UNPUBLISHED
    assert store.toolsets == {}


def test_create_refuses_a_version_whose_source_cannot_be_read(store, monkeypatch) -> None:
    def _unreadable(*_args: Any):
        raise ExportSourceError("no captured source", status_code=422)

    monkeypatch.setattr(toolsets, "_load_version_api", _unreadable)
    with pytest.raises(AgentToolsetError) as caught:
        _create(store)
    assert caught.value.code == CODE_TOOLSET_SOURCE_UNAVAILABLE
    assert "no captured source" in str(caught.value)
    assert store.toolsets == {}


def test_a_version_has_one_toolset(store) -> None:
    created = _create(store)
    with pytest.raises(AgentToolsetError) as caught:
        create_agent_toolset(_TENANT, AgentToolsetCreate(versionId=created.version_id))
    assert caught.value.code == CODE_TOOLSET_EXISTS
    assert len(store.toolsets) == 1


# ============================================================================
# Tool updates — the write-op confirmation
# ============================================================================
def test_enabling_a_delete_without_confirmation_is_refused(store) -> None:
    """Acceptance: enabling a DELETE needs the explicit write-op confirmation flag."""
    created = _create(store)
    delete = _by_operation(created)["DELETE /pets/{id}"]
    with pytest.raises(AgentToolsetError) as caught:
        update_agent_toolset_tool(
            _TENANT, created.id, delete.id, AgentToolUpdate(enabled=True), actor_id=_ACTOR
        )
    assert caught.value.code == CODE_WRITE_OP_UNCONFIRMED
    assert "DELETE /pets/{id}" in str(caught.value)
    assert store.tools[delete.id]["enabled"] is False
    assert "set_agent_toolset_tool_enabled" not in store.calls


def test_enabling_a_delete_with_confirmation_stamps_who_and_when(store) -> None:
    created = _create(store)
    delete = _by_operation(created)["DELETE /pets/{id}"]
    before, after = update_agent_toolset_tool(
        _TENANT,
        created.id,
        delete.id,
        AgentToolUpdate(enabled=True, confirmWriteOp=True),
        actor_id=_ACTOR,
    )
    assert (before.enabled, after.enabled) == (False, True)
    assert after.write_confirmed_by == _ACTOR and after.write_confirmed_at is not None
    assert get_agent_toolset(_TENANT, created.id).enabled_write_op_count == 1


def test_disabling_a_write_op_clears_its_confirmation(store) -> None:
    created = _create(store)
    delete = _by_operation(created)["DELETE /pets/{id}"]
    confirm = AgentToolUpdate(enabled=True, confirmWriteOp=True)
    update_agent_toolset_tool(_TENANT, created.id, delete.id, confirm, actor_id=_ACTOR)
    _, after = update_agent_toolset_tool(
        _TENANT, created.id, delete.id, AgentToolUpdate(enabled=False), actor_id=_ACTOR
    )
    assert after.enabled is False and after.write_confirmed_at is None
    with pytest.raises(AgentToolsetError):  # a fresh confirmation is needed again
        update_agent_toolset_tool(_TENANT, created.id, delete.id, AgentToolUpdate(enabled=True))


def test_reads_toggle_without_confirmation(store) -> None:
    created = _create(store)
    read = _by_operation(created)["GET /pets"]
    _, off = update_agent_toolset_tool(_TENANT, created.id, read.id, AgentToolUpdate(enabled=False))
    _, on = update_agent_toolset_tool(_TENANT, created.id, read.id, AgentToolUpdate(enabled=True))
    assert (off.enabled, on.enabled) == (False, True)
    assert on.write_confirmed_at is None  # a read never carries a confirmation


def test_confirmation_on_a_read_is_harmless(store) -> None:
    created = _create(store)
    legacy = _by_operation(created)["GET /legacy"]
    _, on = update_agent_toolset_tool(
        _TENANT, created.id, legacy.id, AgentToolUpdate(enabled=True, confirmWriteOp=True)
    )
    assert on.enabled is True and on.write_confirmed_at is None


def test_a_tool_of_another_toolset_or_tenant_is_not_found(store) -> None:
    first = _create(store)
    second = _create(store)
    tool = first.tools[0]
    for toolset_id, tenant in ((second.id, _TENANT), (first.id, _OTHER_TENANT)):
        with pytest.raises(AgentToolsetError) as caught:
            update_agent_toolset_tool(tenant, toolset_id, tool.id, AgentToolUpdate(enabled=False))
        assert caught.value.code == CODE_TOOL_NOT_FOUND


def test_audit_detail_names_the_operation_and_the_change(store) -> None:
    created = _create(store)
    delete = _by_operation(created)["DELETE /pets/{id}"]
    before, after = update_agent_toolset_tool(
        _TENANT, created.id, delete.id, AgentToolUpdate(enabled=True, confirmWriteOp=True)
    )
    detail = audit_tool_detail(before, after)
    assert detail["operation"] == "DELETE /pets/{id}"
    assert detail["toolName"] == delete.tool_name
    assert detail["writeOp"] is True
    assert (detail["enabledBefore"], detail["enabledAfter"]) == (False, True)
    assert detail["writeConfirmedAt"] == after.write_confirmed_at.isoformat()


# ============================================================================
# Toolset updates / delete
# ============================================================================
def test_update_changes_settings_and_reports_before_and_after(store) -> None:
    created = _create(store)
    before, after = update_agent_toolset(
        _TENANT, created.id, AgentToolsetUpdate(enabled=False, target="mock"), actor_id=_ACTOR
    )
    assert (before.enabled, before.target) == (True, "prod")
    assert (after.enabled, after.target) == (False, "mock")
    assert after.updated_by == _ACTOR


def test_an_empty_update_is_refused(store) -> None:
    created = _create(store)
    with pytest.raises(AgentToolsetError) as caught:
        update_agent_toolset(_TENANT, created.id, AgentToolsetUpdate())
    assert caught.value.code == CODE_TOOLSET_INVALID


def test_update_and_delete_of_a_foreign_toolset_are_not_found(store) -> None:
    created = _create(store)
    with pytest.raises(AgentToolsetError) as caught:
        update_agent_toolset(_OTHER_TENANT, created.id, AgentToolsetUpdate(enabled=False))
    assert caught.value.code == CODE_TOOLSET_NOT_FOUND
    with pytest.raises(AgentToolsetError) as caught:
        delete_agent_toolset(_OTHER_TENANT, created.id)
    assert caught.value.code == CODE_TOOLSET_NOT_FOUND
    assert created.id in store.toolsets


def test_delete_removes_the_toolset_and_its_tools(store) -> None:
    created = _create(store)
    removed = delete_agent_toolset(_TENANT, created.id)
    assert removed.id == created.id
    assert store.toolsets == {} and store.tools == {}
    with pytest.raises(AgentToolsetError):
        get_agent_toolset(_TENANT, created.id)
