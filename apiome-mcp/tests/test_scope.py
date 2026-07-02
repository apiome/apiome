"""Tests for MCP API key :class:`apiome_mcp.scope.Scope` (#3001)."""

from __future__ import annotations

import uuid
from typing import Any

from apiome_mcp.scope import Scope, parse_scope_json


def test_allows_public_empty_lists() -> None:
    s = Scope()
    t, p = str(uuid.uuid4()), str(uuid.uuid4())
    assert s.allows(t, p)
    assert s.allows(t, None)


def test_allows_tenant_restriction() -> None:
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    s = Scope(tenants=[a])
    assert s.allows(a, None)
    assert s.allows(a, str(uuid.uuid4()))
    assert not s.allows(b, None)


def test_allows_project_restriction() -> None:
    tid = str(uuid.uuid4())
    p1, p2 = str(uuid.uuid4()), str(uuid.uuid4())
    s = Scope(projects=[p1])
    assert s.allows(tid, p1)
    assert not s.allows(tid, p2)
    assert not s.allows(tid, None)


def test_allows_tenant_and_project() -> None:
    tid_ok, tid_bad = str(uuid.uuid4()), str(uuid.uuid4())
    pid_ok, pid_bad = str(uuid.uuid4()), str(uuid.uuid4())
    s = Scope(tenants=[tid_ok], projects=[pid_ok])
    assert s.allows(tid_ok, pid_ok)
    assert not s.allows(tid_bad, pid_ok)
    assert not s.allows(tid_ok, pid_bad)


def test_scope_tenants_projects_are_tuples() -> None:
    """Fields are stored as tuples even when constructed with lists."""
    s = Scope(tenants=["a", "b"], projects=["p"])
    assert isinstance(s.tenants, tuple)
    assert isinstance(s.projects, tuple)
    assert s.tenants == ("a", "b")
    assert s.projects == ("p",)


def test_parse_scope_json_none_and_empty_dict() -> None:
    assert parse_scope_json(None) == Scope()
    assert parse_scope_json({}) == Scope()


def test_parse_scope_json_round_trip_lists() -> None:
    t, p = str(uuid.uuid4()), str(uuid.uuid4())
    raw = {"tenants": [t], "projects": [p]}
    s = parse_scope_json(raw)
    assert s == Scope(tenants=[t], projects=[p])
    assert s.to_json_dict() == raw


def test_parse_scope_json_ignores_unknown_keys_and_legacy_shape() -> None:
    assert parse_scope_json({"tenant": True}) == Scope()
    assert parse_scope_json({"tenants": ["x"], "extra": 1}) == Scope(tenants=("x",))


def test_parse_scope_json_wrong_field_type_denies_all(caplog: Any) -> None:
    """A non-list ``tenants``/``projects`` value is invalid → deny-all + warning."""
    import logging

    with caplog.at_level(logging.WARNING, logger="apiome_mcp.scope"):
        bad_tenants = parse_scope_json({"tenants": "bad"})
        bad_projects = parse_scope_json({"projects": 42})
    assert bad_tenants.deny_all is True
    assert not bad_tenants.allows(str(uuid.uuid4()), str(uuid.uuid4()))
    assert bad_projects.deny_all is True
    assert len(caplog.records) >= 2


def test_parse_scope_json_filters_non_string_items() -> None:
    """Non-string items inside a valid list are silently filtered out."""
    s = parse_scope_json({"tenants": [1, "keep", None]})
    assert s == Scope(tenants=["keep"])


def test_parse_scope_json_non_dict_denies_all(caplog: Any) -> None:
    """Non-dict (and non-None, non-Scope) raw values → deny-all + warning."""
    import logging

    with caplog.at_level(logging.WARNING, logger="apiome_mcp.scope"):
        s = parse_scope_json([1, 2])
    assert s.deny_all is True
    assert not s.allows(str(uuid.uuid4()), str(uuid.uuid4()))
    assert len(caplog.records) >= 1


def test_parse_scope_json_scope_instance() -> None:
    s = Scope(tenants=["a"])
    assert parse_scope_json(s) is s
