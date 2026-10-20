"""PR-back rules — REPO-5.8 (#2793).

The pure half of PR-back: settings validation, the allow/deny list, which source file owns each
path and schema, the file text, the commit message and the pull request description. Also pins
the V302 migration's shape.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from app.pr_back import (
    BRANCH_PREFIX,
    DEFAULT_COMMIT_MESSAGE_TEMPLATE,
    MAX_REVIEWERS,
    PR_BODY_MAX_CHARS,
    FileChangeReport,
    PrBackSettings,
    PrBackSettingsError,
    commit_message_context,
    foreign_schema_refs,
    normalize_settings,
    owner_of,
    parse_spec_text,
    pr_back_branch_name,
    project_allowed,
    pull_request_body,
    pull_request_title,
    render_commit_message,
    serialize_spec,
    slice_spec_for_source,
    spec_format_for_path,
    split_reviewers,
)

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "apiome-db"
    / "scripts"
    / "V302__repository_pr_back_settings_repo_5_8.sql"
)

PROJECT = "5c1e0a10-2c4d-4e5f-8a9b-0c1d2e3f0002"
OTHER = "5c1e0a10-2c4d-4e5f-8a9b-0c1d2e3f0003"

SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Shop", "version": "1.0.0"},
    "paths": {
        "/users": {"get": {"responses": {"200": {"$ref": "#/components/responses/Ok"}}}},
        "/invoices": {
            "get": {
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Invoice"}}
                        }
                    }
                }
            }
        },
        "/notes": {"get": {}},
    },
    "components": {
        "schemas": {
            "User": {"type": "object"},
            "Invoice": {"type": "object", "properties": {"owner": {"$ref": "#/components/schemas/User"}}},
            "Note": {"type": "object"},
        },
        "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
    },
}


def _settings(**overrides) -> dict:
    values = {
        "project_policy": "allow",
        "project_ids": [],
        "target_branch": None,
        "commit_message_template": None,
        "reviewers": [],
    }
    values.update(overrides)
    return values


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_normalize_settings_defaults_and_dedupes():
    settings = normalize_settings(
        **_settings(
            project_ids=[PROJECT.upper(), PROJECT, " ", OTHER],
            target_branch="  ",
            commit_message_template="",
            reviewers=["@octocat", "Octocat", "acme/api-reviewers", ""],
        )
    )
    assert settings == PrBackSettings(
        project_policy="allow",
        project_ids=(PROJECT, OTHER),
        target_branch=None,
        commit_message_template=None,
        reviewers=("octocat", "acme/api-reviewers"),
    )


@pytest.mark.parametrize(
    "overrides, code",
    [
        ({"project_policy": "maybe"}, "pr-back-policy-invalid"),
        ({"target_branch": "feature..x"}, "pr-back-branch-invalid"),
        ({"target_branch": "has space"}, "pr-back-branch-invalid"),
        ({"commit_message_template": "x" * 2001}, "pr-back-template-too-long"),
        ({"commit_message_template": "{{#project}}unclosed"}, "pr-back-template-invalid"),
        ({"commit_message_template": "{{missing}}"}, "pr-back-template-invalid"),
        ({"reviewers": ["not a login"]}, "pr-back-reviewer-invalid"),
        ({"reviewers": ["-leading"]}, "pr-back-reviewer-invalid"),
        ({"reviewers": [f"user{i}" for i in range(MAX_REVIEWERS + 1)]}, "pr-back-reviewers-too-many"),
        ({"project_ids": [f"p{i}" for i in range(501)]}, "pr-back-projects-too-many"),
    ],
)
def test_normalize_settings_refuses_with_a_code(overrides, code):
    with pytest.raises(PrBackSettingsError) as caught:
        normalize_settings(**_settings(**overrides))
    assert caught.value.code == code
    assert caught.value.message


def test_settings_from_row_and_none():
    assert PrBackSettings.from_row(None) is None
    row = {
        "project_policy": "deny",
        "project_ids": [PROJECT],
        "target_branch": "develop",
        "commit_message_template": "Sync {{project}}",
        "reviewers": ["octocat"],
    }
    expected = PrBackSettings("deny", (PROJECT,), "develop", "Sync {{project}}", ("octocat",))
    assert PrBackSettings.from_row(row) == expected


def test_project_allowed_is_opt_in_and_follows_the_policy():
    assert project_allowed(None, PROJECT) is False
    assert project_allowed(PrBackSettings(), PROJECT) is False  # allow with an empty list
    allow = PrBackSettings(project_policy="allow", project_ids=(PROJECT,))
    assert project_allowed(allow, PROJECT.upper()) is True
    assert project_allowed(allow, OTHER) is False
    deny = PrBackSettings(project_policy="deny", project_ids=(PROJECT,))
    assert project_allowed(deny, PROJECT) is False
    assert project_allowed(deny, OTHER) is True
    assert project_allowed(PrBackSettings(project_policy="deny"), OTHER) is True


def test_split_reviewers_separates_teams():
    assert split_reviewers(["octocat", "acme/api-reviewers", "hubot"]) == (["octocat", "hubot"], ["api-reviewers"])


# ---------------------------------------------------------------------------
# Branch and commit message
# ---------------------------------------------------------------------------


def test_branch_name_is_per_project_and_base():
    assert pr_back_branch_name("shop", "main") == f"{BRANCH_PREFIX}shop-main"
    assert pr_back_branch_name("Shop API", "release/2.x") == f"{BRANCH_PREFIX}shop-api-release-2.x"
    assert pr_back_branch_name(None, "") == f"{BRANCH_PREFIX}project-base"


def test_commit_message_renders_template_or_default():
    context = commit_message_context("Shop", "1.4.0", "acme/shop", "main", 2)
    assert render_commit_message(None, context) == "Sync Shop 1.4.0 from Apiome"
    assert DEFAULT_COMMIT_MESSAGE_TEMPLATE in "Sync {{project}} {{version}} from Apiome"
    assert (
        render_commit_message("chore(api): {{project}}@{{version}} → {{branch}} ({{fileCount}} files)", context)
        == "chore(api): Shop@1.4.0 → main (2 files)"
    )
    assert render_commit_message("{{missing}}", context) == "Sync Shop 1.4.0 from Apiome"


def test_commit_message_does_not_html_escape_project_names():
    context = commit_message_context("R&D <API>", "1.0", "o/r", "main", 1)
    assert render_commit_message(None, context) == "Sync R&D <API> 1.0 from Apiome"
    assert render_commit_message("{{{project}}} / {{ project }}", context) == "R&D <API> / R&D <API>"


# ---------------------------------------------------------------------------
# Ownership and slicing
# ---------------------------------------------------------------------------


def test_owner_of_prefers_live_source_then_primary():
    entities = {("path", "/users"): "s-users", ("path", "/gone"): "s-removed", ("class", "Note"): None}
    live = {"s-users", "s-billing"}
    assert owner_of("path", "/users", entities, live, "s-billing") == "s-users"
    assert owner_of("path", "/gone", entities, live, "s-billing") == "s-billing"
    assert owner_of("class", "Note", entities, live, "s-billing") == "s-billing"
    assert owner_of("path", "/edited-in-apiome", entities, live, "s-billing") == "s-billing"


def test_slice_keeps_owned_paths_and_schemas_and_everything_else():
    owners = {
        ("path", "/users"): "users",
        ("class", "User"): "users",
        ("path", "/invoices"): "billing",
        ("class", "Invoice"): "billing",
    }

    def owner(kind, key):
        return owner_of(kind, key, owners, {"users", "billing"}, "users")

    users = slice_spec_for_source(SPEC, source_id="users", owner=owner)
    billing = slice_spec_for_source(SPEC, source_id="billing", owner=owner)
    assert sorted(users["paths"]) == ["/notes", "/users"]  # /notes is unattributed → primary
    assert sorted(users["components"]["schemas"]) == ["Note", "User"]
    assert list(billing["paths"]) == ["/invoices"]
    assert list(billing["components"]["schemas"]) == ["Invoice"]
    for part in (users, billing):
        assert part["info"] == SPEC["info"]
        assert part["components"]["securitySchemes"] == SPEC["components"]["securitySchemes"]
    assert foreign_schema_refs(billing) == ["User"]
    assert foreign_schema_refs(users) == []
    assert len(SPEC["paths"]) == 3  # not mutated


def test_slice_single_source_gets_everything():
    def owner(kind, key):
        return owner_of(kind, key, {}, set(), None)

    assert slice_spec_for_source(SPEC, source_id=None, owner=owner) == SPEC


def test_slice_tolerates_a_spec_without_paths_or_components():
    assert slice_spec_for_source({"openapi": "3.1.0"}, source_id="a", owner=lambda k, n: "a") == {"openapi": "3.1.0"}


# ---------------------------------------------------------------------------
# File text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path, fmt",
    [
        ("openapi.yaml", "yaml"),
        ("api/Spec.YML", "yaml"),
        ("specs/users.json", "json"),
        ("schema.graphql", None),
        ("service.proto", None),
        ("yaml", None),
    ],
)
def test_spec_format_for_path(path, fmt):
    assert spec_format_for_path(path) == fmt


def test_serialize_and_parse_round_trip_in_both_formats():
    for fmt in ("json", "yaml"):
        text = serialize_spec(SPEC, fmt)
        assert text.endswith("\n")
        assert parse_spec_text(text, fmt) == SPEC
    yaml_text = serialize_spec(SPEC, "yaml")
    assert yaml_text.splitlines()[0] == "openapi: 3.1.0"  # renderer order kept, not sorted
    assert json.loads(serialize_spec({"b": 1, "a": "é"}, "json")) == {"b": 1, "a": "é"}
    assert "é" in serialize_spec({"a": "é"}, "yaml")
    assert yaml.safe_load(serialize_spec({"a": "x" * 2000}, "yaml")) == {"a": "x" * 2000}


def test_parse_spec_text_returns_none_for_absent_or_bad_text():
    assert parse_spec_text(None, "json") is None
    assert parse_spec_text("{not json", "json") is None
    assert parse_spec_text("- a list", "yaml") is None
    assert parse_spec_text("key: [unclosed", "yaml") is None


# ---------------------------------------------------------------------------
# Pull request words
# ---------------------------------------------------------------------------


def test_title_names_project_and_version():
    assert pull_request_title("Shop", "1.4.0") == "Apiome: sync Shop 1.4.0"


def _report(**fields) -> FileChangeReport:
    values = {"path": "openapi.yaml", "status": "modified", "header": "# Changes", "body": "- Added `/users`"}
    values.update(fields)
    return FileChangeReport(**values)


def test_body_carries_each_change_report_and_the_branch_warning():
    body = pull_request_body(
        project_name="Shop",
        version_label="1.4.0",
        repository_full_name="acme/shop",
        base_branch="main",
        branch_name="apiome/pr-back-shop-main",
        files=[
            _report(foreign_refs=["User"], notes=["The file on the base branch is Swagger 2.0."]),
            _report(path="billing.json", status="unchanged", header="", body=""),
        ],
        skipped=["`schema.graphql` is not a JSON or YAML file."],
        apiome_version="1.261.0",
    )
    assert body.startswith("## Shop 1.4.0 — rendered from Apiome")
    assert "wrote 1 of 2 source file(s) back to `acme/shop`" in body
    assert "### `openapi.yaml` — modified" in body
    assert "# Changes" in body and "- Added `/users`" in body
    assert "### `billing.json` — unchanged" in body
    assert "left as references: `User`" in body
    assert "> The file on the base branch is Swagger 2.0." in body
    assert "### Not rendered back" in body and "schema.graphql" in body
    assert "(1.261.0)" in body and "`apiome/pr-back-shop-main` belongs to Apiome" in body


def test_body_is_truncated_under_github_limit():
    body = pull_request_body(
        project_name="Shop",
        version_label="1",
        repository_full_name="acme/shop",
        base_branch="main",
        branch_name="b",
        files=[_report(body="x" * (PR_BODY_MAX_CHARS + 10))],
        skipped=[],
        apiome_version=None,
    )
    assert len(body) <= PR_BODY_MAX_CHARS
    assert body.rstrip().endswith("_The change report was truncated to fit GitHub's limit._")


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def test_v302_migration_shape():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "set search_path to apiome, public" in sql
    assert "create table if not exists apiome.repository_pr_back_settings" in sql
    assert "repository_id uuid primary key references apiome.tenant_repositories(id) on delete cascade" in sql
    assert "check (project_policy in ('allow', 'deny'))" in sql
    assert "cardinality(project_ids) <= 500" in sql
    assert f"cardinality(reviewers) <= {MAX_REVIEWERS}" in sql
    assert "create index if not exists idx_repository_pr_back_settings_tenant" in sql
    assert "rollback" in sql
    assert "token" not in sql.replace("--", "")  # no credential is stored
