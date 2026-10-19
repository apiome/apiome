"""Ownership vocabulary and suggestion producers — CDG-2.2 (#5961).

Pure functions in :mod:`app.entity_owners`: the kind registry and its permissions, what a document
says about its own owner (``x-apiome-owner``, ``info.contact``), CODEOWNERS parsing and matching,
and the envelope fragment every list read joins.
"""

from __future__ import annotations

import pytest

from app.entity_owners import (
    CODE_INVALID,
    KINDS,
    OwnerValidationError,
    codeowners_for_path,
    kind_spec,
    owner_envelope_join,
    owner_ref_from_value,
    parse_codeowners,
    spec_owner_suggestions,
)
from app.permissions import Resource

# ---------------------------------------------------------------------------------------------
# kinds
# ---------------------------------------------------------------------------------------------


def test_each_kind_is_gated_by_the_permission_that_edits_it() -> None:
    assert {kind: spec.resource for kind, spec in KINDS.items()} == {
        "project": Resource.PROJECTS,
        "catalog_item": Resource.PROJECTS,
        "mcp_endpoint": Resource.PROJECTS,
        "consumer": Resource.CONSUMER_CONTRACTS,
        "connector": Resource.IMPORTS,
        # CDG-5.2: an agent is a consumer; its model is catalogued with it.
        "agent": Resource.CONSUMER_CONTRACTS,
        "model": Resource.CONSUMER_CONTRACTS,
    }


def test_projects_and_catalog_items_are_told_apart_by_publishable() -> None:
    assert "e.publishable" in KINDS["project"].where
    assert "NOT e.publishable" in KINDS["catalog_item"].where


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(OwnerValidationError) as caught:
        kind_spec("widget")
    assert caught.value.code == CODE_INVALID


# ---------------------------------------------------------------------------------------------
# document suggestions
# ---------------------------------------------------------------------------------------------


def test_the_extension_names_the_owner() -> None:
    assert spec_owner_suggestions({"x-apiome-owner": "Payments"}) == [
        {"team": "payments", "sourceRef": "x-apiome-owner: payments"}
    ]


def test_the_extension_may_list_several_teams() -> None:
    found = spec_owner_suggestions({"x-apiome-owner": ["payments", "platform", "payments"]})
    assert [s["team"] for s in found] == ["payments", "platform"]


def test_a_contact_name_shaped_like_a_slug_is_a_suggestion() -> None:
    found = spec_owner_suggestions({"info": {"contact": {"name": "payments"}}})
    assert found == [{"team": "payments", "sourceRef": "info.contact.name: payments"}]


def test_a_prose_contact_name_suggests_nothing() -> None:
    assert spec_owner_suggestions({"info": {"contact": {"name": "Jane Doe"}}}) == []


def test_contact_does_not_repeat_the_extension() -> None:
    found = spec_owner_suggestions(
        {"x-apiome-owner": "payments", "info": {"contact": {"name": "payments"}}}
    )
    assert len(found) == 1 and found[0]["sourceRef"].startswith("x-apiome-owner")


@pytest.mark.parametrize("document", [None, "openapi: 3.0.0", {"x-apiome-owner": 7}, {"info": "x"}])
def test_anything_else_suggests_nothing(document) -> None:
    assert spec_owner_suggestions(document) == []


# ---------------------------------------------------------------------------------------------
# CODEOWNERS
# ---------------------------------------------------------------------------------------------

_CODEOWNERS = """
# Default owners
*                       @acme/platform
/api/payments/          @acme/payments @alice
*.proto                 @acme/rpc        # trailing comment
docs/**/openapi.yaml    @acme/docs
/api/payments/legacy/
[Section header]
"""


def test_parse_skips_comments_blanks_and_section_headers() -> None:
    rules = parse_codeowners(_CODEOWNERS)
    assert rules[0] == ("*", ["@acme/platform"])
    assert rules[2] == ("*.proto", ["@acme/rpc"])
    assert rules[-1] == ("/api/payments/legacy/", [])
    assert len(rules) == 5


@pytest.mark.parametrize(
    "path,owners",
    [
        ("README.md", ["@acme/platform"]),
        ("api/payments/openapi.yaml", ["@acme/payments", "@alice"]),
        ("services/billing/billing.proto", ["@acme/rpc"]),
        ("docs/v1/public/openapi.yaml", ["@acme/docs"]),
        ("docs/openapi.yaml", ["@acme/docs"]),
        # The last matching rule wins, and an ownerless rule removes ownership.
        ("api/payments/legacy/openapi.yaml", []),
        # Anchored directory patterns do not match elsewhere.
        ("other/api/payments/openapi.yaml", ["@acme/platform"]),
    ],
)
def test_the_last_matching_rule_wins(path: str, owners) -> None:
    assert codeowners_for_path(parse_codeowners(_CODEOWNERS), path) == owners


def test_no_rules_means_no_owners() -> None:
    assert codeowners_for_path([], "api/openapi.yaml") == []


# ---------------------------------------------------------------------------------------------
# envelope
# ---------------------------------------------------------------------------------------------


def test_the_envelope_join_prefers_confirmed_and_ignores_deleted_teams() -> None:
    sql = owner_envelope_join(("project", "catalog_item"), "p.id", "p.tenant_id")
    assert "LEFT JOIN LATERAL" in sql and "AS entity_owner" in sql
    assert "eo.entity_kind IN ('project', 'catalog_item')" in sql
    assert "ORDER BY (eo.status = 'confirmed') DESC" in sql
    assert "ot.deleted_at IS NULL" in sql
    assert "LIMIT 1" in sql


def test_the_envelope_join_refuses_an_unknown_kind() -> None:
    with pytest.raises(OwnerValidationError):
        owner_envelope_join(("widget",), "w.id", "w.tenant_id")


def test_owner_ref_from_value() -> None:
    ref = owner_ref_from_value(
        {"team": {"id": "t1", "slug": "payments", "name": "Payments"}, "status": "suggested",
         "source": "gateway_tag"}
    )
    assert ref is not None and ref.team.slug == "payments" and ref.status == "suggested"
    assert owner_ref_from_value(None) is None
    assert owner_ref_from_value({"status": "confirmed"}) is None
