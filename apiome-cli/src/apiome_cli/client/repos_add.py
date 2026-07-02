"""Helpers for ``apiome repos add``."""

from __future__ import annotations

from typing import Any

import typer

from apiome_cli.exit_codes import EXIT_USAGE

_SOURCE_CONTROL_CATEGORY = "source_control"
_SOURCE_CONTROL_PROVIDERS = frozenset({"github", "gitlab", "bitbucket"})
_USABLE_ACCOUNT_STATUSES = frozenset({"connected", "limited"})


def flatten_source_control_accounts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return Git provider linked-account rows from a dashboard payload."""
    rows: list[dict[str, Any]] = []
    sections = payload.get("sections")
    if not isinstance(sections, list):
        return rows
    for section in sections:
        if not isinstance(section, dict):
            continue
        if section.get("category") != _SOURCE_CONTROL_CATEGORY:
            continue
        items = section.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            provider = item.get("provider")
            if isinstance(provider, str) and provider in _SOURCE_CONTROL_PROVIDERS:
                rows.append(item)
    return rows


def resolve_linked_account(
    payload: dict[str, Any],
    account_name: str,
) -> dict[str, Any]:
    """
    Find a source-control linked account by display name or external ref.

    Matching is case-insensitive on ``display_name`` and ``external_account_ref``.
    """
    needle = account_name.strip().casefold()
    if not needle:
        msg = "--account must not be empty."
        raise typer.BadParameter(msg)

    matches: list[dict[str, Any]] = []
    for row in flatten_source_control_accounts(payload):
        display_name = row.get("display_name")
        external_ref = row.get("external_account_ref")
        candidates = [
            value.strip().casefold()
            for value in (display_name, external_ref)
            if isinstance(value, str) and value.strip()
        ]
        if needle in candidates:
            matches.append(row)

    if not matches:
        typer.echo(
            f"No linked Git account found for {account_name!r}. "
            "Use `apiome integrations list` to see connected accounts.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    if len(matches) > 1:
        labels = sorted(
            {
                str(row.get("display_name") or row.get("external_account_ref") or "unknown")
                for row in matches
            }
        )
        typer.echo(
            f"Multiple linked accounts match {account_name!r}: {', '.join(labels)}. "
            "Use a more specific --account value.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    account = matches[0]
    account_id = account.get("id")
    if not isinstance(account_id, str) or not account_id.strip():
        typer.echo(
            f"Linked account {account_name!r} is not connected. "
            "Reconnect it from Linked accounts before registering a repository.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    status = account.get("status")
    if status not in _USABLE_ACCOUNT_STATUSES:
        typer.echo(
            f"Linked account {account_name!r} is {status!r}. "
            "Reconnect it before registering a repository.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    return account


def resolve_accessible_repository(
    payload: dict[str, Any],
    repo_slug: str,
) -> dict[str, Any]:
    """Find an accessible repository by ``OWNER/NAME`` (``full_name``)."""
    needle = repo_slug.strip().casefold()
    if not needle:
        msg = "--repo must not be empty."
        raise typer.BadParameter(msg)

    items = payload.get("items")
    if not isinstance(items, list):
        items = []

    matches: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        full_name = item.get("full_name")
        name = item.get("name")
        candidates = [
            value.strip().casefold()
            for value in (full_name, name)
            if isinstance(value, str) and value.strip()
        ]
        if needle in candidates:
            matches.append(item)

    if not matches:
        typer.echo(
            f"No accessible repository found for {repo_slug!r} on the linked account.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    if len(matches) > 1:
        labels = sorted(
            {
                str(row.get("full_name") or row.get("name") or "unknown")
                for row in matches
            }
        )
        typer.echo(
            f"Multiple repositories match {repo_slug!r}: {', '.join(labels)}. "
            "Use the full OWNER/NAME slug.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    return matches[0]


def repository_name_from_clone_url(clone_url: str) -> str:
    """Derive a display name from the last path segment of a clone URL."""
    trimmed = clone_url.strip()
    if trimmed.lower().endswith(".git"):
        trimmed = trimmed[:-4]
    segment = [part for part in trimmed.split("/") if part][-1] if trimmed else ""
    if segment.strip():
        return segment.strip()
    return "repository"


def build_public_url_create_body(
    *,
    clone_url: str,
    branch: str | None,
    preflight: dict[str, Any],
) -> dict[str, object]:
    """Build the REST payload for public-URL repository registration."""
    canonical_url = preflight.get("clone_url")
    if not isinstance(canonical_url, str) or not canonical_url.strip():
        canonical_url = clone_url.strip()

    default_branch = branch.strip() if branch and branch.strip() else None
    if default_branch is None:
        prefetched_branch = preflight.get("default_branch")
        if isinstance(prefetched_branch, str) and prefetched_branch.strip():
            default_branch = prefetched_branch.strip()
        else:
            default_branch = "main"

    visibility = preflight.get("visibility")
    body: dict[str, object] = {
        "connection_type": "public_url",
        "clone_url": canonical_url,
        "name": repository_name_from_clone_url(canonical_url),
        "default_branch": default_branch,
    }
    if visibility in ("public", "private"):
        body["visibility"] = visibility
    return body


def build_linked_account_create_body(
    *,
    repository: dict[str, Any],
    linked_account_id: str,
    branch: str | None,
) -> dict[str, object]:
    """Build the REST payload for linked-account repository registration."""
    provider = repository.get("provider")
    clone_url = repository.get("clone_url")
    name = repository.get("name")
    visibility = repository.get("visibility")
    if not isinstance(provider, str) or provider not in _SOURCE_CONTROL_PROVIDERS:
        msg = "Accessible repository is missing a supported provider."
        raise typer.BadParameter(msg)
    if not isinstance(clone_url, str) or not clone_url.strip():
        msg = "Accessible repository is missing a clone URL."
        raise typer.BadParameter(msg)
    if not isinstance(name, str) or not name.strip():
        msg = "Accessible repository is missing a display name."
        raise typer.BadParameter(msg)

    default_branch = branch.strip() if branch and branch.strip() else None
    if default_branch is None:
        repo_branch = repository.get("default_branch")
        if isinstance(repo_branch, str) and repo_branch.strip():
            default_branch = repo_branch.strip()
        else:
            default_branch = "main"

    body: dict[str, object] = {
        "connection_type": "linked_account",
        "provider": provider,
        "linked_account_id": linked_account_id,
        "clone_url": clone_url.strip(),
        "name": name.strip(),
        "default_branch": default_branch,
    }
    if visibility in ("public", "private"):
        body["visibility"] = visibility
    return body


def validate_add_mode(
    *,
    account: str | None,
    repo: str | None,
    url: str | None,
) -> tuple[str | None, str | None, str | None]:
    """
    Validate mutually exclusive add modes.

    Returns normalized ``(account, repo, url)`` when valid.
    """
    account_value = account.strip() if account and account.strip() else None
    repo_value = repo.strip() if repo and repo.strip() else None
    url_value = url.strip() if url and url.strip() else None

    linked_mode = account_value is not None or repo_value is not None
    public_mode = url_value is not None

    if linked_mode and public_mode:
        typer.echo(
            "Use either --url for a public Git URL or --account with --repo "
            "for a linked account repository, not both.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    if not linked_mode and not public_mode:
        typer.echo(
            "Register a repository with --url URL or --account NAME --repo OWNER/NAME.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    if linked_mode and (account_value is None or repo_value is None):
        typer.echo(
            "Linked-account registration requires both --account and --repo.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    return account_value, repo_value, url_value