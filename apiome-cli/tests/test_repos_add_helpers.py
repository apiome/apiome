"""Unit tests for repository add helper functions."""

from __future__ import annotations

import pytest
import typer

from apiome_cli.client.repos_add import (
    build_linked_account_create_body,
    build_public_url_create_body,
    flatten_source_control_accounts,
    repository_name_from_clone_url,
    resolve_accessible_repository,
    resolve_linked_account,
    validate_add_mode,
)
from apiome_cli.exit_codes import EXIT_USAGE

_LINKED_ACCOUNTS_PAYLOAD = {
    "generated_on": "2026-06-07T12:00:00Z",
    "active_tenant_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    "sections": [
        {
            "category": "source_control",
            "title": "Source control",
            "description": "Git hosts",
            "connected_count": 1,
            "items": [
                {
                    "id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                    "provider": "github",
                    "display_name": "Acme GitHub",
                    "status": "connected",
                    "summary": None,
                    "external_account_ref": "acme-org",
                    "last_sync_on": None,
                    "expires_on": None,
                    "error_count": 0,
                    "last_error": None,
                    "scope": "tenant",
                    "data": {},
                },
            ],
        },
    ],
}

_ACCESSIBLE_REPOS_PAYLOAD = {
    "generated_on": "2026-06-07T12:00:00Z",
    "linked_account_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    "provider": "github",
    "items": [
        {
            "provider_repository_id": "123",
            "name": "api-specs",
            "full_name": "acme/api-specs",
            "description": None,
            "provider": "github",
            "default_branch": "main",
            "visibility": "private",
            "clone_url": "https://github.com/acme/api-specs.git",
            "html_url": "https://github.com/acme/api-specs",
            "already_registered": False,
        },
    ],
}


def test_repository_name_from_clone_url_strips_git_suffix() -> None:
    assert (
        repository_name_from_clone_url("https://github.com/acme/public-specs.git")
        == "public-specs"
    )


def test_build_public_url_create_body_uses_preflight_metadata() -> None:
    body = build_public_url_create_body(
        clone_url="https://github.com/acme/public-specs.git",
        branch=None,
        preflight={
            "provider": "github",
            "clone_url": "https://github.com/acme/public-specs.git",
            "default_branch": "develop",
            "visibility": "public",
        },
    )
    assert body == {
        "connection_type": "public_url",
        "clone_url": "https://github.com/acme/public-specs.git",
        "name": "public-specs",
        "default_branch": "develop",
        "visibility": "public",
    }


def test_build_public_url_create_body_honors_branch_override() -> None:
    body = build_public_url_create_body(
        clone_url="https://github.com/acme/public-specs.git",
        branch="release",
        preflight={
            "provider": "github",
            "clone_url": "https://github.com/acme/public-specs.git",
            "default_branch": "develop",
            "visibility": "public",
        },
    )
    assert body["default_branch"] == "release"


def test_build_linked_account_create_body() -> None:
    body = build_linked_account_create_body(
        repository=_ACCESSIBLE_REPOS_PAYLOAD["items"][0],
        linked_account_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        branch="feature",
    )
    assert body == {
        "connection_type": "linked_account",
        "provider": "github",
        "linked_account_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        "clone_url": "https://github.com/acme/api-specs.git",
        "name": "api-specs",
        "default_branch": "feature",
        "visibility": "private",
    }


def test_resolve_linked_account_matches_display_name() -> None:
    account = resolve_linked_account(_LINKED_ACCOUNTS_PAYLOAD, "Acme GitHub")
    assert account["id"] == "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


def test_resolve_accessible_repository_matches_full_name() -> None:
    repository = resolve_accessible_repository(_ACCESSIBLE_REPOS_PAYLOAD, "acme/api-specs")
    assert repository["clone_url"] == "https://github.com/acme/api-specs.git"


def test_validate_add_mode_requires_linked_account_pair() -> None:
    with pytest.raises(typer.Exit):
        validate_add_mode(account="Acme GitHub", repo=None, url=None)


def test_validate_add_mode_rejects_mixed_modes() -> None:
    with pytest.raises(typer.Exit):
        validate_add_mode(
            account="Acme GitHub",
            repo="acme/api-specs",
            url="https://github.com/acme/public-specs.git",
        )


def test_flatten_source_control_accounts_ignores_other_categories() -> None:
    rows = flatten_source_control_accounts(_LINKED_ACCOUNTS_PAYLOAD)
    assert len(rows) == 1
    assert rows[0]["display_name"] == "Acme GitHub"


def test_resolve_linked_account_rejects_ambiguous_matches() -> None:
    payload = {
        **_LINKED_ACCOUNTS_PAYLOAD,
        "sections": [
            {
                **_LINKED_ACCOUNTS_PAYLOAD["sections"][0],
                "items": [
                    _LINKED_ACCOUNTS_PAYLOAD["sections"][0]["items"][0],
                    {
                        **_LINKED_ACCOUNTS_PAYLOAD["sections"][0]["items"][0],
                        "id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                        "display_name": "Acme GitHub",
                    },
                ],
            },
        ],
    }
    with pytest.raises(typer.Exit) as exc_info:
        resolve_linked_account(payload, "Acme GitHub")
    assert exc_info.value.exit_code == EXIT_USAGE


def test_resolve_linked_account_rejects_disconnected_status() -> None:
    payload = {
        **_LINKED_ACCOUNTS_PAYLOAD,
        "sections": [
            {
                **_LINKED_ACCOUNTS_PAYLOAD["sections"][0],
                "items": [
                    {
                        **_LINKED_ACCOUNTS_PAYLOAD["sections"][0]["items"][0],
                        "status": "expired",
                    },
                ],
            },
        ],
    }
    with pytest.raises(typer.Exit) as exc_info:
        resolve_linked_account(payload, "Acme GitHub")
    assert exc_info.value.exit_code == EXIT_USAGE


def test_resolve_accessible_repository_rejects_ambiguous_matches() -> None:
    payload = {
        **_ACCESSIBLE_REPOS_PAYLOAD,
        "items": [
            _ACCESSIBLE_REPOS_PAYLOAD["items"][0],
            {
                **_ACCESSIBLE_REPOS_PAYLOAD["items"][0],
                "provider_repository_id": "456",
                "full_name": "acme/api-specs",
            },
        ],
    }
    with pytest.raises(typer.Exit) as exc_info:
        resolve_accessible_repository(payload, "acme/api-specs")
    assert exc_info.value.exit_code == EXIT_USAGE


def test_validate_add_mode_requires_both_account_and_repo() -> None:
    with pytest.raises(typer.Exit):
        validate_add_mode(account="Acme GitHub", repo=None, url=None)
