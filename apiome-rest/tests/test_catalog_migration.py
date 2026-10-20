"""Backstage and Compass import — parsing, the scan hook and the routes — CDG-5.5 (#5983).

The staging and decisions against Postgres are in ``test_catalog_migration_db.py``.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.catalog_migration import (
    COMPASS_MAX_BYTES,
    CatalogParseError,
    backstage_owner_ref,
    classify_link,
    compass_source_ref,
    imply_backstage_teams,
    parse_backstage_file,
    parse_compass_export,
    slugify,
)
from app.catalog_migration_models import MigrationError, MigrationRun, MigrationSuggestion
from app.declared_dependencies import reference_slug
from app.main import app
from app.permissions import Resource
from app.repository_file_scan import apply_backstage

_TENANT = "00000000-0000-4000-8000-000000000001"
_USER = "00000000-0000-4000-8000-000000000002"

_COMPONENT = """
apiVersion: backstage.io/v1alpha1
kind: Component
metadata:
  name: payments-svc
  title: Payments service
  description: Takes money
  annotations:
    github.com/project-slug: acme/payments
    pagerduty.com/service-id: P123
  tags: [java]
  links:
    - url: https://slack.example/payments
      title: Slack
    - url: https://wiki.example/payments
      title: Runbook
    - url: ftp://files.example
      title: Files
spec:
  type: service
  lifecycle: production
  owner: payments-team
  system: billing
  providesApis: [payments-api]
  consumesApis: [api:default/customers, customers]
  dependsOn: [resource:default/payments-db, component:ledger]
"""


# ---------------------------------------------------------------------------------------------
# Backstage
# ---------------------------------------------------------------------------------------------


def test_a_component_maps_its_fields_and_lists_every_other_one() -> None:
    parsed = parse_backstage_file("svc/catalog-info.yaml", _COMPONENT)
    [component] = parsed.components
    assert (component.external_ref, component.name, component.slug, component.category) == (
        "component:default/payments-svc",
        "Payments service",
        "payments-svc",
        "component",
    )
    assert component.source_ref == "backstage:svc/catalog-info.yaml"
    assert (component.component_type, component.lifecycle, component.parent_ref) == ("service", "production", "billing")
    assert component.owner_ref == "group:default/payments-team"
    assert component.provides == ("payments-api",)
    assert [(r.edge_kind, r.slug) for r in component.references] == [
        ("consumes", "customers"),
        ("depends_on", "payments-db"),
        ("depends_on", "ledger"),
    ]
    assert [(link.type, link.url) for link in component.links] == [
        ("chat", "https://slack.example/payments"),
        ("document", "https://wiki.example/payments"),
    ]
    fields = {(u.field, u.reason) for u in parsed.unmapped}
    assert fields == {
        ("metadata.annotations.github.com/project-slug", "no Apiome field"),
        ("metadata.annotations.pagerduty.com/service-id", "no Apiome field"),
        ("metadata.tags", "no Apiome field"),
        ("metadata.links[2]", "no http(s) url"),
    }


def test_a_group_becomes_a_team_with_one_link_of_each_kind() -> None:
    parsed = parse_backstage_file(
        "org.yaml",
        """
kind: Group
metadata:
  name: payments-team
  description: Money
  links:
    - {url: "https://pagerduty.example/p", title: On-call}
    - {url: "https://slack.example/a", title: Slack}
    - {url: "https://slack.example/b", title: Slack too}
spec:
  type: team
  profile: {displayName: Payments, email: pay@acme.example, picture: "https://x"}
  children: []
""",
    )
    [team] = parsed.teams
    assert (team.external_ref, team.name, team.slug, team.contact_email) == (
        "group:default/payments-team",
        "Payments",
        "payments-team",
        "pay@acme.example",
    )
    assert (team.chat_url, team.oncall_url, team.docs_url) == (
        "https://slack.example/a",
        "https://pagerduty.example/p",
        None,
    )
    assert {u.field for u in parsed.unmapped} == {"spec.children", "spec.profile.picture", "metadata.links (chat)"}


def test_an_api_definition_is_inline_or_a_path_beside_the_file() -> None:
    parsed = parse_backstage_file(
        "apis/catalog-info.yaml",
        """
kind: API
metadata: {name: inline-api}
spec: {type: openapi, owner: team-a, definition: "openapi: 3.0.0"}
---
kind: API
metadata: {name: file-api}
spec: {type: asyncapi, definition: {$text: ../specs/events.yaml}}
---
kind: API
metadata: {name: remote-api}
spec: {type: openapi, definition: {$text: "https://example.com/openapi.yaml"}}
---
kind: API
metadata: {name: escaping-api}
spec: {type: openapi, definition: {$text: ../../../etc/passwd}}
""",
    )
    assert [(a.slug, a.definition, a.definition_path, a.owner_ref) for a in parsed.apis] == [
        ("inline-api", "openapi: 3.0.0", None, "group:default/team-a"),
        ("file-api", None, "specs/events.yaml", None),
    ]
    reasons = {(u.entity, u.reason) for u in parsed.unmapped}
    assert ("api:default/remote-api", "URL definitions are not fetched") in reasons
    assert ("api:default/escaping-api", "path leaves the repository") in reasons


def test_kinds_without_an_apiome_place_and_user_owners_are_reported() -> None:
    parsed = parse_backstage_file(
        "catalog-info.yaml",
        """
kind: User
metadata: {name: jdoe}
---
kind: System
metadata: {name: billing}
spec: {owner: "user:jdoe", domain: finance}
---
kind: Domain
metadata: {name: finance}
spec: {owner: finance-team}
---
not: an entity
""",
    )
    assert [(c.category, c.parent_ref, c.owner_ref) for c in parsed.components] == [
        ("system", "finance", None),
        ("domain", None, "group:default/finance-team"),
    ]
    reasons = [u.reason for u in parsed.unmapped]
    assert "kind 'User' is not imported" in reasons
    assert "owned by a user, not a group: Apiome owners are teams" in reasons


def test_owners_without_a_group_still_become_team_suggestions() -> None:
    parsed = parse_backstage_file("catalog-info.yaml", _COMPONENT)
    imply_backstage_teams(parsed)
    assert [(t.external_ref, t.slug, t.named) for t in parsed.teams] == [
        ("group:default/payments-team", "payments-team", False),
    ]


def test_malformed_yaml_is_one_report_line() -> None:
    parsed = parse_backstage_file("catalog-info.yaml", "kind: [unclosed")
    assert parsed.entities == 0 and [(u.entity, u.reason) for u in parsed.unmapped] == [
        ("catalog-info.yaml", "not valid YAML"),
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("team-a", "group:default/team-a"),
        ("group:team-a", "group:default/team-a"),
        ("Group:Platform/Team-A", "group:platform/team-a"),
        ("user:jdoe", "user:default/jdoe"),
        ("", None),
        (None, None),
    ],
)
def test_owner_references_are_normalized(value: Any, expected: Any) -> None:
    assert backstage_owner_ref(value) == expected


def test_links_are_classified_by_their_words() -> None:
    assert classify_link(None, "chat", "Team chat") == "chat"
    assert classify_link("pagerduty", None, None) == "on_call"
    assert classify_link(None, "github", "Source") == "repository"
    assert classify_link(None, None, "Grafana") == "dashboard"
    assert classify_link(None, None, "Handbook") == "document"
    assert classify_link(None, None, "Status page") == "other"


def test_slugs_always_have_the_handle_shape() -> None:
    assert slugify("Payments Service!") == "payments-service"
    assert slugify("---", "team") == "team"
    assert len(slugify("x" * 300)) == 128


# ---------------------------------------------------------------------------------------------
# Compass
# ---------------------------------------------------------------------------------------------


def _compass(**extra: Any) -> bytes:
    return json.dumps(
        {
            "components": [
                {
                    "id": "ari:c/1",
                    "name": "Checkout",
                    "typeId": "SERVICE",
                    "ownerId": "ari:team/abc123456789",
                    "links": [
                        {"type": "CHAT_CHANNEL", "url": "https://chat.example/x", "name": "#checkout"},
                        {"type": "ON_CALL", "url": "https://oncall.example/x"},
                        {"type": "DOCUMENT", "url": "https://docs.example/x"},
                        {"type": "REPOSITORY", "url": "https://github.com/acme/checkout"},
                        {"type": "PROJECT", "url": "https://jira.example/x"},
                    ],
                    "relationships": [
                        {"type": "DEPENDS_ON", "endNode": {"id": "ari:c/2"}},
                        {"type": "DEPENDS_ON", "nodeId": "ari:c/9"},
                        {"type": "CHILD_OF", "endNode": {"id": "ari:c/2"}},
                    ],
                    "labels": ["tier-1"],
                    "customFields": [{"name": "cost"}],
                },
                {"id": "ari:c/2", "name": "Ledger"},
                {"name": "no id"},
            ],
            "teams": [{"id": "ari:team/abc123456789", "displayName": "Checkout team"}],
            **extra,
        }
    ).encode()


def test_a_compass_export_maps_links_relationships_and_owners() -> None:
    parsed = parse_compass_export(_compass(exportedAt="2026-10-01"))
    checkout, ledger = parsed.components
    assert (checkout.slug, checkout.component_type, checkout.source_ref) == (
        "checkout",
        "SERVICE",
        compass_source_ref("ari:c/1"),
    )
    assert [link.type for link in checkout.links] == ["chat", "on_call", "document", "repository", "other"]
    assert [(r.reference, r.slug) for r in checkout.references] == [("component:ledger", "ledger")]
    assert ledger.slug == "ledger" and ledger.owner_ref is None
    assert [(t.external_ref, t.name, t.slug, t.named) for t in parsed.teams] == [
        ("ari:team/abc123456789", "Checkout team", "checkout-team", True),
    ]
    reasons = {(u.entity, u.field, u.reason) for u in parsed.unmapped}
    assert ("export", "exportedAt", "not imported") in reasons
    assert ("compass:Checkout", "labels", "no Apiome field") in reasons
    assert ("compass:Checkout", "customFields", "no Apiome field") in reasons
    assert ("compass:Checkout", "relationships[1]", "target component is not in the export") in reasons
    assert ("compass:Checkout", "relationships[2]", "relationship CHILD_OF is not imported") in reasons
    assert ("export", "components", "1 entries without an id were skipped") in reasons


def test_an_owner_missing_from_teams_gets_a_made_up_name() -> None:
    raw = json.dumps([{"id": "ari:c/1", "name": "A", "ownerId": "ari:cloud:identity::team/0f1e2d3c-aaaa"}]).encode()
    [team] = parse_compass_export(raw).teams
    assert (team.name, team.slug, team.named) == ("Compass team 0f1e2d3c", "compass-team-0f1e2d3c", False)


def test_a_graphql_search_response_is_read_too() -> None:
    raw = json.dumps(
        {"data": {"compass": {"searchComponents": {"nodes": [{"component": {"id": "ari:c/1", "name": "A"}}]}}}}
    )
    assert [c.slug for c in parse_compass_export(raw.encode()).components] == ["a"]


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b"not json", "migration-invalid"),
        (b'{"nothing": []}', "migration-invalid"),
        (b"x" * (COMPASS_MAX_BYTES + 1), "migration-too-large"),
    ],
)
def test_an_unreadable_export_is_refused(raw: bytes, code: str) -> None:
    with pytest.raises(CatalogParseError) as refused:
        parse_compass_export(raw)
    assert refused.value.code == code


def test_references_are_read_the_way_their_source_wrote_them() -> None:
    assert reference_slug("backstage:catalog-info.yaml", "component:default/Ledger") == "ledger"
    assert reference_slug("compass:abc", "component:ledger") == "ledger"
    assert reference_slug("manual", "ledger#/components/schemas/Entry") == "ledger"


# ---------------------------------------------------------------------------------------------
# The scan hook
# ---------------------------------------------------------------------------------------------


class _ScanDb:
    def execute_query(self, sql: str, params: Any = None) -> List[Dict[str, Any]]:
        if "tenant_repositories" in sql:
            return [{"created_by": _USER}]
        return [{"path": "catalog-info.yaml"}]


def test_the_scan_stages_the_catalog_before_writing_declarations() -> None:
    calls: List[str] = []
    staged: Dict[str, Any] = {}

    def catalog(tenant, repository, branch, files, *, label, fetch_file, actor_id):
        calls.append("catalog")
        staged.update(files=files, label=label, actor=actor_id, fetched=fetch_file("specs/openapi.yaml"))

    def fetch(owner, repo, path, ref, token, max_bytes):
        return f"text of {path}", False

    apply_backstage(
        _ScanDb(),
        _TENANT,
        "r",
        "main",
        "acme",
        "orders",
        None,
        fetch_text=fetch,
        record=lambda *a: calls.append("declarations"),
        catalog=catalog,
    )
    assert calls == ["catalog", "declarations"]
    assert staged == {
        "files": {"catalog-info.yaml": "text of catalog-info.yaml"},
        "label": "acme/orders · main",
        "actor": _USER,
        "fetched": "text of specs/openapi.yaml",
    }


# ---------------------------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def authed():
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT,
        "user_id": _USER,
        "auth_method": "jwt",
    }
    with patch("app.catalog_migration_routes.enforce_permission", return_value=_USER) as permit:
        yield TestClient(app), permit
    app.dependency_overrides.clear()


def _suggestion(kind: str = "team") -> MigrationSuggestion:
    return MigrationSuggestion(
        id="s1", kind=kind, source="compass", external_ref="ari:x", name="Team", slug="team", status="suggested"
    )


def test_an_upload_needs_imports_create(authed) -> None:
    client, permit = authed
    run = MigrationRun(id="r1", source="compass", label="compass.json")
    with patch("app.catalog_migration_routes.store.import_compass_export", return_value=run) as imported:
        response = client.post(
            "/v1/tenants/acme/catalog-migrations/compass", json={"filename": "compass.json", "content": "{}"}
        )
    assert response.status_code == 201 and response.json()["label"] == "compass.json"
    assert [call.args[2:4] for call in permit.call_args_list] == [(Resource.IMPORTS, "create")]
    assert imported.call_args.args[1:3] == ("compass.json", b"{}")


def test_a_refused_upload_keeps_its_code(authed) -> None:
    client, _ = authed
    with patch(
        "app.catalog_migration_routes.store.import_compass_export",
        side_effect=MigrationError("migration-too-large", "too big"),
    ):
        response = client.post("/v1/tenants/acme/catalog-migrations/compass", json={"content": "{}"})
    assert response.status_code == 413 and response.json()["detail"]["code"] == "migration-too-large"


def test_accepting_a_team_also_needs_teams_create(authed) -> None:
    client, permit = authed
    with (
        patch("app.catalog_migration_routes.store.read_suggestion", return_value=_suggestion("team")),
        patch("app.catalog_migration_routes.store.accept_suggestion", return_value=_suggestion("team")),
    ):
        response = client.post("/v1/tenants/acme/catalog-migration-suggestions/s1/accept", json={})
    assert response.status_code == 200
    assert [call.args[2] for call in permit.call_args_list] == [Resource.IMPORTS, Resource.TEAMS]


def test_accepting_a_component_needs_only_imports_create(authed) -> None:
    client, permit = authed
    with (
        patch("app.catalog_migration_routes.store.read_suggestion", return_value=_suggestion("component")),
        patch("app.catalog_migration_routes.store.accept_suggestion", return_value=_suggestion("component")) as accept,
    ):
        response = client.post(
            "/v1/tenants/acme/catalog-migration-suggestions/s1/accept",
            json={"slug": "checkout-web", "asComponent": True},
        )
    assert response.status_code == 200
    assert [call.args[2] for call in permit.call_args_list] == [Resource.IMPORTS]
    assert accept.call_args.args[2].slug == "checkout-web" and accept.call_args.args[2].as_component is True


@pytest.mark.parametrize(
    ("code", "status"),
    [("migration-suggestion-decided", 409), ("migration-slug-taken", 409), ("migration-suggestion-not-found", 404)],
)
def test_decision_refusals_map_to_statuses(authed, code: str, status: int) -> None:
    client, _ = authed
    with patch("app.catalog_migration_routes.store.dismiss_suggestion", side_effect=MigrationError(code, "no")):
        response = client.post("/v1/tenants/acme/catalog-migration-suggestions/s1/dismiss")
    assert response.status_code == status and response.json()["detail"]["code"] == code


def test_an_unknown_report_or_component_is_a_404(authed) -> None:
    client, _ = authed
    assert client.get("/v1/tenants/acme/catalog-migrations/not-a-uuid").status_code == 404
    with patch(
        "app.catalog_migration_routes.store.read_component", side_effect=MigrationError("component-not-found", "no")
    ):
        assert client.get("/v1/tenants/acme/catalog-components/nope").status_code == 404
