"""Unit tests for the deterministic MCP lint rule engine (V2-MCP-21.1, #3682).

These exercise :mod:`app.mcp_lint`: the pure, no-I/O engine that walks a normalized
:class:`~app.mcp_client.normalize.DiscoverySurface` and emits ordered
:class:`~app.mcp_lint.LintFinding` objects with stable ids. Concrete MCP hygiene rules
(V2-MCP-21.2) and annotation/security rules (V2-MCP-21.3) plug into the same registry;
here we cover the engine contract and its foundational rules on hand-built fixtures.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.mcp_client.handshake import ServerInfo
from app.mcp_client.normalize import (
    ITEM_TYPE_PROMPT,
    ITEM_TYPE_RESOURCE,
    ITEM_TYPE_RESOURCE_TEMPLATE,
    ITEM_TYPE_TOOL,
    CapabilityItem,
    DiscoverySurface,
)
from app.mcp_lint import (
    RULE_CATALOGUE,
    SEVERITY_PENALTY,
    finding_dicts,
    item_path,
    lint_mcp_surface,
    make_finding,
    register_rule_metadata,
)

# --- Fixture builders -----------------------------------------------------------------------


def _tool(name: str, ordinal: int = 0, **extra: Any) -> CapabilityItem:
    return CapabilityItem(item_type=ITEM_TYPE_TOOL, name=name, ordinal=ordinal, **extra)


def _resource(name: str, ordinal: int = 0, **extra: Any) -> CapabilityItem:
    return CapabilityItem(item_type=ITEM_TYPE_RESOURCE, name=name, ordinal=ordinal, **extra)


def _prompt(name: str, ordinal: int = 0, **extra: Any) -> CapabilityItem:
    return CapabilityItem(item_type=ITEM_TYPE_PROMPT, name=name, ordinal=ordinal, **extra)


def _surface(
    tools: Optional[List[CapabilityItem]] = None,
    resources: Optional[List[CapabilityItem]] = None,
    resource_templates: Optional[List[CapabilityItem]] = None,
    prompts: Optional[List[CapabilityItem]] = None,
) -> DiscoverySurface:
    return DiscoverySurface(
        protocol_version="2025-06-18",
        server_info=ServerInfo(name="srv", title="Server", version="1.0.0"),
        capabilities={},
        instructions=None,
        tools=tuple(tools or ()),
        resources=tuple(resources or ()),
        resource_templates=tuple(resource_templates or ()),
        prompts=tuple(prompts or ()),
    )


# A surface with one of every foundational defect: a missing name, a duplicate name.
DIRTY_SURFACE = _surface(
    tools=[
        _tool("search", ordinal=0),
        _tool("search", ordinal=1),  # duplicate name
        _tool("", ordinal=2),  # missing name
    ],
)

# A surface that is well-formed for the foundational rules (no missing/duplicate names,
# and it is non-empty).
CLEAN_SURFACE = _surface(
    tools=[_tool("search", ordinal=0), _tool("fetch", ordinal=1)],
    resources=[_resource("doc", ordinal=0)],
)


# --- Engine contract ------------------------------------------------------------------------


def test_clean_surface_has_no_foundational_findings() -> None:
    findings = lint_mcp_surface(CLEAN_SURFACE)
    rules = {f.rule for f in findings}
    assert "naming.item-name-missing" not in rules
    assert "structure.duplicate-item-name" not in rules
    assert "structure.empty-surface" not in rules


def test_dirty_surface_surfaces_foundational_rules() -> None:
    findings = lint_mcp_surface(DIRTY_SURFACE)
    rules = {f.rule for f in findings}
    assert "naming.item-name-missing" in rules
    assert "structure.duplicate-item-name" in rules


def test_empty_surface_flagged() -> None:
    findings = lint_mcp_surface(_surface())
    rules = {f.rule for f in findings}
    assert "structure.empty-surface" in rules
    # The empty-surface finding is anchored at the surface root.
    empty = next(f for f in findings if f.rule == "structure.empty-surface")
    assert empty.path == "surface"
    assert empty.severity == "info"


def test_findings_sorted_by_path_rule_id() -> None:
    findings = lint_mcp_surface(DIRTY_SURFACE)
    keys = [(f.path, f.rule, f.id) for f in findings]
    assert keys == sorted(keys)


def test_determinism_same_input_same_output() -> None:
    a = lint_mcp_surface(DIRTY_SURFACE)
    b = lint_mcp_surface(DIRTY_SURFACE)
    assert [f.id for f in a] == [f.id for f in b]
    assert finding_dicts(a) == finding_dicts(b)


def test_finding_ids_are_stable_hashes() -> None:
    for finding in lint_mcp_surface(DIRTY_SURFACE):
        assert finding.id.startswith("mcp-lint-")
        assert len(finding.id) == len("mcp-lint-") + 16


def test_same_path_rule_message_yields_same_id() -> None:
    a = make_finding("tools.x", "naming.item-name-missing", "tool at ordinal 0 has no name.")
    b = make_finding("tools.x", "naming.item-name-missing", "tool at ordinal 0 has no name.")
    assert a.id == b.id


def test_engine_is_pure_does_not_mutate_surface() -> None:
    before = DIRTY_SURFACE.all_items()
    lint_mcp_surface(DIRTY_SURFACE)
    assert DIRTY_SURFACE.all_items() == before


def test_extra_findings_are_merged_and_ordered() -> None:
    extra = [make_finding("zzz.last", "structure.empty-surface", "injected.")]
    findings = lint_mcp_surface(CLEAN_SURFACE, extra_findings=extra)
    assert any(f.path == "zzz.last" for f in findings)
    keys = [(f.path, f.rule, f.id) for f in findings]
    assert keys == sorted(keys)  # injected finding participates in the global ordering


# --- Foundational rule specifics ------------------------------------------------------------


def test_duplicate_name_reports_only_second_occurrence() -> None:
    surface = _surface(
        tools=[_tool("a", 0), _tool("a", 1), _tool("a", 2)],
    )
    dups = [
        f for f in lint_mcp_surface(surface) if f.rule == "structure.duplicate-item-name"
    ]
    # First definition is canonical; only ordinals 1 and 2 are flagged.
    assert len(dups) == 2


def test_duplicate_names_across_kinds_do_not_collide() -> None:
    # The same name in two different kinds is legal; only intra-kind duplicates are flagged.
    surface = _surface(
        tools=[_tool("thing", 0)],
        resources=[_resource("thing", 0)],
    )
    dups = [
        f for f in lint_mcp_surface(surface) if f.rule == "structure.duplicate-item-name"
    ]
    assert dups == []


def test_blank_name_not_double_counted_as_duplicate() -> None:
    # Two blank-named tools each trip name-missing, not duplicate-name (blank is not a name).
    surface = _surface(tools=[_tool("", 0), _tool("", 1)])
    findings = lint_mcp_surface(surface)
    assert sum(1 for f in findings if f.rule == "naming.item-name-missing") == 2
    assert [f for f in findings if f.rule == "structure.duplicate-item-name"] == []


def test_item_path_uses_name_then_ordinal_fallback() -> None:
    assert item_path(_tool("search", ordinal=3)) == "tools.search"
    assert item_path(_tool("", ordinal=3)) == "tools.#3"
    assert item_path(_resource("doc", ordinal=0)) == "resources.doc"
    assert item_path(_prompt("greet", ordinal=0)) == "prompts.greet"
    assert (
        item_path(
            CapabilityItem(item_type=ITEM_TYPE_RESOURCE_TEMPLATE, name="tpl", ordinal=0)
        )
        == "resourceTemplates.tpl"
    )


# --- Catalogue / registry contract ----------------------------------------------------------


def test_every_catalogued_rule_has_valid_severity() -> None:
    for rule, (category, severity) in RULE_CATALOGUE.items():
        assert severity in SEVERITY_PENALTY, rule
        assert rule.split(".")[0] == category, rule


def test_make_finding_rejects_unregistered_rule() -> None:
    try:
        make_finding("path", "does.not-exist", "msg")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError for an unregistered rule")


def test_register_rule_metadata_is_idempotent_but_guards_divergence() -> None:
    register_rule_metadata("naming.item-name-missing", "naming", "error")  # identical: no-op
    try:
        register_rule_metadata("naming.item-name-missing", "naming", "warning")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError on divergent re-registration")


def test_finding_as_dict_has_stable_keys() -> None:
    finding = make_finding("surface", "structure.empty-surface", "msg")
    payload: Dict[str, str] = finding.as_dict()
    assert set(payload.keys()) == {"id", "path", "category", "rule", "severity", "message"}
