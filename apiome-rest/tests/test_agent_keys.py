"""Agent keys — AGX-3.1 (#4537): the contract in :mod:`app.agent_keys`.

The store is the in-memory :class:`~agent_key_fakes.FakeAgentKeyStore`. These tests pin what the
routes rely on: allowlists are validated and normalized, the secret is minted in the ``ak_``
format, hashed with bcrypt and never echoed back by any read, the status of a key follows the
MCP middleware's refusal order, and the lifecycle (create / allowlist edit / revoke) refuses
what it should.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
import pytest
from agent_key_fakes import FakeAgentKeyStore

from app.agent_keys import (
    AGENT_KEY_KIND,
    AGENT_KEY_SCHEMA_VERSION,
    AGENT_KEY_SCOPE,
    AGENT_KEY_SECRET_PREFIX,
    CODE_AGENT_KEY_EXISTS,
    CODE_AGENT_KEY_INVALID,
    CODE_AGENT_KEY_NOT_FOUND,
    CODE_AGENT_KEY_REVOKED,
    TOOL_ALLOWLIST_MAX_ENTRIES,
    AgentKeyAllowlistUpdate,
    AgentKeyCreate,
    AgentKeyError,
    create_agent_key,
    get_agent_key,
    key_status,
    list_agent_keys,
    mint_agent_key_secret,
    normalize_tool_allowlist,
    revoke_agent_key,
    update_agent_key_allowlist,
)
from app.auth import API_KEY_SCOPE_AGENT_INVOKE
from app.database import db
from app.tool_projection import TOOL_NAME_PATTERN

_TENANT = "11111111-1111-4111-8111-111111111111"
_OTHER_TENANT = "99999999-9999-4999-8999-999999999999"
_TOOLSET = "22222222-2222-4222-8222-222222222222"
_ACTOR = "33333333-3333-4333-8333-333333333333"
_MISSING = "77777777-7777-4777-8777-777777777777"


@pytest.fixture
def store(monkeypatch) -> FakeAgentKeyStore:
    """The agent-key accessors, in memory."""
    return FakeAgentKeyStore().install(monkeypatch, db)


def _body(**overrides) -> AgentKeyCreate:
    """A valid create request."""
    data = {
        "name": "claude-desktop",
        "toolsetId": _TOOLSET,
        "toolAllowlist": ["listPets", "getPetById"],
    }
    data.update(overrides)
    return AgentKeyCreate.model_validate(data)


# ============================================================================
# Constants
# ============================================================================
def test_constants_match_the_v269_contract():
    assert AGENT_KEY_KIND == "agent"
    assert AGENT_KEY_SCOPE == API_KEY_SCOPE_AGENT_INVOKE == "agent:invoke"
    assert AGENT_KEY_SECRET_PREFIX == "ak_"
    assert TOOL_ALLOWLIST_MAX_ENTRIES == 1024
    assert AGENT_KEY_SCHEMA_VERSION == "agx.agent-key.v1"
    # The allowlist grammar is the AGX-1.1 compiler's, which V269's CHECK copies.
    assert TOOL_NAME_PATTERN.pattern == r"^[A-Za-z0-9_-]{1,64}$"


# ============================================================================
# normalize_tool_allowlist
# ============================================================================
def test_allowlist_is_deduplicated_and_sorted():
    assert normalize_tool_allowlist(["b", "a", "b", "C_1", "x-y"]) == ["C_1", "a", "b", "x-y"]


def test_an_empty_allowlist_is_allowed_and_permits_nothing():
    assert normalize_tool_allowlist([]) == []


@pytest.mark.parametrize(
    "entry",
    ["", "a b", "tool.name", "*", "a" * 65, "é", "tool\n", 1, None, ["x"], {"a": 1}],
)
def test_allowlist_refuses_anything_but_a_tool_name(entry):
    with pytest.raises(AgentKeyError) as exc:
        normalize_tool_allowlist(["ok", entry])
    assert exc.value.code == CODE_AGENT_KEY_INVALID
    assert exc.value.errors[0].startswith("toolAllowlist[1]:")


def test_allowlist_reports_every_bad_entry_at_once():
    with pytest.raises(AgentKeyError) as exc:
        normalize_tool_allowlist(["a b", "fine", "*"])
    assert [e.split(":")[0] for e in exc.value.errors] == ["toolAllowlist[0]", "toolAllowlist[2]"]


def test_allowlist_has_no_wildcard():
    with pytest.raises(AgentKeyError):
        normalize_tool_allowlist(["*"])


def test_allowlist_is_capped():
    assert len(normalize_tool_allowlist([f"t{i}" for i in range(1024)])) == 1024
    with pytest.raises(AgentKeyError) as exc:
        normalize_tool_allowlist([f"t{i}" for i in range(1025)])
    assert "at most 1024" in exc.value.errors[-1]


def test_a_64_character_name_is_the_longest_accepted():
    assert normalize_tool_allowlist(["a" * 64]) == ["a" * 64]


# ============================================================================
# mint_agent_key_secret
# ============================================================================
def test_minted_secret_has_the_agent_format_and_prefix():
    secret, prefix, key_hash = mint_agent_key_secret()
    assert secret.startswith("ak_")
    assert len(secret) == 3 + 64
    int(secret[3:], 16)  # hex
    assert prefix == secret[:12] + "..."


def test_minted_secret_verifies_against_its_bcrypt_hash_only():
    secret, _, key_hash = mint_agent_key_secret()
    assert secret not in key_hash
    assert bcrypt.checkpw(secret.encode(), key_hash.encode())
    assert not bcrypt.checkpw((secret + "x").encode(), key_hash.encode())


def test_minted_secrets_are_distinct():
    assert len({mint_agent_key_secret()[0] for _ in range(5)}) == 5


# ============================================================================
# key_status
# ============================================================================
_NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"enabled": True}, "active"),
        ({"enabled": True, "expires_at": _NOW + timedelta(seconds=1)}, "active"),
        ({"enabled": True, "expires_at": _NOW}, "expired"),
        ({"enabled": True, "expires_at": _NOW - timedelta(days=1)}, "expired"),
        ({"enabled": False}, "disabled"),
        ({"enabled": False, "expires_at": _NOW - timedelta(days=1)}, "disabled"),
        ({"enabled": False, "revoked_at": _NOW}, "revoked"),
        ({"enabled": True, "revoked_at": _NOW, "expires_at": _NOW}, "revoked"),
    ],
)
def test_status_follows_revoked_disabled_expired_precedence(row, expected):
    assert key_status(row, now=_NOW) == expected


def test_status_reads_a_naive_expiry_as_utc():
    naive = (_NOW - timedelta(minutes=1)).replace(tzinfo=None)
    assert key_status({"enabled": True, "expires_at": naive}, now=_NOW) == "expired"


# ============================================================================
# create_agent_key
# ============================================================================
def test_create_stores_an_agent_key_and_returns_the_secret_once(store):
    created = create_agent_key(_TENANT, _body(description="  CI agent  "), actor_id=_ACTOR)
    assert created.secret.startswith("ak_")
    assert created.kind == "agent"
    assert created.status == "active"
    assert created.toolset_id == _TOOLSET
    assert created.tool_allowlist == ["getPetById", "listPets"]
    assert created.key_prefix == created.secret[:12] + "..."
    assert created.description == "CI agent"
    assert created.created_by == _ACTOR

    row = store.rows[created.id]
    assert row["kind"] == "agent" and row["scopes"] == ["agent:invoke"]
    assert bcrypt.checkpw(created.secret.encode(), row["key_hash"].encode())
    assert created.secret not in str(store.rows)  # only the hash is stored

    # No read ever carries the secret again.
    again = get_agent_key(_TENANT, created.id)
    assert "secret" not in again.model_dump()
    assert created.secret not in again.model_dump_json()
    assert all(created.secret not in k.model_dump_json() for k in list_agent_keys(_TENANT))


def test_create_serializes_camel_case(store):
    created = create_agent_key(_TENANT, _body())
    payload = created.model_dump(by_alias=True)
    for field in ("schemaVersion", "keyPrefix", "toolsetId", "toolAllowlist", "createdAt"):
        assert field in payload


def test_create_refuses_every_problem_at_once(store):
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    with pytest.raises(AgentKeyError) as exc:
        create_agent_key(_TENANT, _body(name="   ", toolAllowlist=["a b"], expiresAt=past))
    assert exc.value.code == CODE_AGENT_KEY_INVALID
    fields = [error.split(":")[0] for error in exc.value.errors]
    assert fields == ["name", "toolAllowlist[0]", "expiresAt"]
    assert store.rows == {}


def test_create_accepts_a_future_expiry_and_reads_naive_as_utc(store):
    future = (datetime.now(timezone.utc) + timedelta(days=30)).replace(tzinfo=None)
    created = create_agent_key(_TENANT, _body(expiresAt=future))
    assert created.expires_at == future.replace(tzinfo=timezone.utc)


def test_create_refuses_an_expiry_of_now(store):
    with pytest.raises(AgentKeyError):
        create_agent_key(_TENANT, _body(expiresAt=_NOW), now=_NOW)


def test_create_refuses_a_taken_name_across_kinds(store):
    store.seed_workspace_key(_TENANT, "shared-name")
    with pytest.raises(AgentKeyError) as exc:
        create_agent_key(_TENANT, _body(name="shared-name"))
    assert exc.value.code == CODE_AGENT_KEY_EXISTS
    # Another tenant may use the name.
    assert create_agent_key(_OTHER_TENANT, _body(name="shared-name")).name == "shared-name"


def test_create_body_rejects_unknown_fields_and_bad_toolset():
    with pytest.raises(ValueError):
        AgentKeyCreate.model_validate({**_body().model_dump(by_alias=True), "scopes": ["*"]})
    with pytest.raises(ValueError):
        _body(toolsetId="not-a-uuid")
    assert isinstance(_body().toolset_id, UUID)


# ============================================================================
# list / get
# ============================================================================
def test_list_is_tenant_scoped_filterable_and_hides_workspace_keys(store):
    store.seed_workspace_key(_TENANT, "workspace")
    first = create_agent_key(_TENANT, _body(name="one"))
    create_agent_key(_TENANT, _body(name="two", toolsetId=_MISSING))
    create_agent_key(_OTHER_TENANT, _body(name="theirs"))

    names = {key.name for key in list_agent_keys(_TENANT)}
    assert names == {"one", "two"}
    assert [k.name for k in list_agent_keys(_TENANT, toolset_id=_TOOLSET)] == ["one"]

    revoke_agent_key(_TENANT, first.id)
    assert {k.name for k in list_agent_keys(_TENANT)} == {"two"}
    assert {k.name for k in list_agent_keys(_TENANT, include_revoked=True)} == {"one", "two"}


def test_get_is_tenant_scoped(store):
    created = create_agent_key(_TENANT, _body())
    assert get_agent_key(_TENANT, created.id).id == created.id
    with pytest.raises(AgentKeyError) as exc:
        get_agent_key(_OTHER_TENANT, created.id)
    assert exc.value.code == CODE_AGENT_KEY_NOT_FOUND


def test_get_never_describes_a_workspace_key(store):
    key_id = store.seed_workspace_key(_TENANT, "workspace")
    with pytest.raises(AgentKeyError):
        get_agent_key(_TENANT, key_id)


# ============================================================================
# update_agent_key_allowlist
# ============================================================================
def test_allowlist_update_replaces_the_list_and_returns_the_previous_one(store):
    created = create_agent_key(_TENANT, _body())
    before, updated = update_agent_key_allowlist(
        _TENANT, created.id, AgentKeyAllowlistUpdate(toolAllowlist=["deletePet", "listPets"])
    )
    assert before == ["getPetById", "listPets"]
    assert updated.tool_allowlist == ["deletePet", "listPets"]
    assert store.rows[created.id]["tool_allowlist"] == ["deletePet", "listPets"]


def test_allowlist_update_refuses_bad_names_before_touching_the_store(store):
    created = create_agent_key(_TENANT, _body())
    store.calls.clear()
    with pytest.raises(AgentKeyError) as exc:
        update_agent_key_allowlist(
            _TENANT, created.id, AgentKeyAllowlistUpdate(toolAllowlist=["no spaces"])
        )
    assert exc.value.code == CODE_AGENT_KEY_INVALID
    assert store.calls == []


def test_allowlist_update_of_an_unknown_key_is_not_found(store):
    with pytest.raises(AgentKeyError) as exc:
        update_agent_key_allowlist(_TENANT, _MISSING, AgentKeyAllowlistUpdate(toolAllowlist=[]))
    assert exc.value.code == CODE_AGENT_KEY_NOT_FOUND


def test_allowlist_of_a_revoked_key_is_frozen(store):
    created = create_agent_key(_TENANT, _body())
    revoke_agent_key(_TENANT, created.id)
    with pytest.raises(AgentKeyError) as exc:
        update_agent_key_allowlist(
            _TENANT, created.id, AgentKeyAllowlistUpdate(toolAllowlist=["x"])
        )
    assert exc.value.code == CODE_AGENT_KEY_REVOKED
    assert store.rows[created.id]["tool_allowlist"] == ["getPetById", "listPets"]


def test_allowlist_update_racing_a_revoke_is_refused(store, monkeypatch):
    created = create_agent_key(_TENANT, _body())
    monkeypatch.setattr(db, "update_agent_key_allowlist", lambda *args, **kwargs: None)
    with pytest.raises(AgentKeyError) as exc:
        update_agent_key_allowlist(
            _TENANT, created.id, AgentKeyAllowlistUpdate(toolAllowlist=["x"])
        )
    assert exc.value.code == CODE_AGENT_KEY_REVOKED


# ============================================================================
# revoke_agent_key
# ============================================================================
def test_revoke_is_idempotent_and_reports_the_first_call(store):
    created = create_agent_key(_TENANT, _body())
    key, now = revoke_agent_key(_TENANT, created.id)
    assert now is True
    assert key.status == "revoked" and key.enabled is False and key.revoked_at is not None
    first_revoked_at = key.revoked_at

    again, now_again = revoke_agent_key(_TENANT, created.id)
    assert now_again is False
    assert again.revoked_at == first_revoked_at


def test_revoke_of_an_unknown_or_foreign_key_is_not_found(store):
    created = create_agent_key(_OTHER_TENANT, _body())
    for key_id in (_MISSING, created.id):
        with pytest.raises(AgentKeyError) as exc:
            revoke_agent_key(_TENANT, key_id)
        assert exc.value.code == CODE_AGENT_KEY_NOT_FOUND
    assert store.rows[created.id]["revoked_at"] is None
