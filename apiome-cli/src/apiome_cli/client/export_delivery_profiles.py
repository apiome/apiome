"""REST helpers for export delivery profiles and deliveries (MFX-38.4).

A delivery profile is a workspace's saved destination for a finished export — a git repository, a
webhook or an S3-compatible bucket — with a reference to the credential it delivers with. These
helpers wrap ``/v1/export/{tenant}/delivery-profiles`` and ``/v1/export/{tenant}/jobs/{job_id}/deliveries``:

* :func:`resolve_profile_id` turns a profile **name or id** into its id;
* :func:`build_destination` turns command-line flags into the channel block the API takes;
* :func:`wait_for_job_deliveries` waits for the deliveries an export job was submitted with
  (``delivery_profiles``) — they run once the job completes and land on it as
  ``EXPORT_DELIVERED`` / ``EXPORT_DELIVERY_FAILED`` events.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from uuid import UUID

import typer

from apiome_cli.client import api_paths
from apiome_cli.client.errors import exit_on_api_error
from apiome_cli.client.http import RestClient
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_USAGE

#: The delivery channels, as the API names them.
CHANNELS = ("git", "webhook", "object_storage")
#: The API's block name for each channel.
CHANNEL_BLOCKS = {"git": "git", "webhook": "webhook", "object_storage": "objectStorage"}
#: The job events a delivery on completion adds.
DELIVERY_EVENT_CODES = frozenset({"EXPORT_DELIVERED", "EXPORT_DELIVERY_FAILED"})


def _json_object(response: Any, what: str) -> dict[str, Any]:
    """The response body as a JSON object, or exit naming what was expected."""
    payload = response.json()
    if not isinstance(payload, dict):
        typer.echo(f"{what} response was not a JSON object.", err=True)
        raise typer.Exit(EXIT_ERROR)
    return payload


def list_profiles(client: RestClient, tenant_slug: str, *, channel: str | None = None) -> list[dict[str, Any]]:
    """``GET …/delivery-profiles`` — the workspace's profiles, by name.

    Args:
        client: The authenticated client.
        tenant_slug: The tenant.
        channel: Only profiles of this channel.

    Returns:
        The profiles.
    """
    path = api_paths.export_delivery_profiles(tenant_slug)
    if channel:
        path = f"{path}?channel={channel}"
    profiles = _json_object(client.get(path), "Delivery profile list").get("profiles")
    return [p for p in profiles if isinstance(p, dict)] if isinstance(profiles, list) else []


def resolve_profile_id(client: RestClient, tenant_slug: str, ref: str) -> str:
    """A profile's id from its id or its name.

    Args:
        client: The authenticated client.
        tenant_slug: The tenant.
        ref: A profile id (UUID) or a profile name.

    Returns:
        The profile id.

    Raises:
        typer.Exit: :data:`EXIT_USAGE` when no profile has that name.
    """
    ref = ref.strip()
    try:
        return str(UUID(ref))
    except ValueError:
        pass
    for profile in list_profiles(client, tenant_slug):
        if profile.get("name") == ref and isinstance(profile.get("id"), str):
            return str(profile["id"])
    typer.echo(f"No delivery profile named {ref!r} exists in this workspace "
               "(apiome export profiles list).", err=True)
    raise typer.Exit(EXIT_USAGE)


def get_profile(client: RestClient, tenant_slug: str, profile_id: str) -> dict[str, Any]:
    """``GET …/delivery-profiles/{id}``."""
    return _json_object(client.get(api_paths.export_delivery_profile(tenant_slug, profile_id)), "Delivery profile")


def create_profile(client: RestClient, tenant_slug: str, body: Mapping[str, Any]) -> dict[str, Any]:
    """``POST …/delivery-profiles`` with ``{name, description?, channel, <block>}``."""
    response = client.post(api_paths.export_delivery_profiles(tenant_slug), json=dict(body))
    return _json_object(response, "Delivery profile")


def update_profile(client: RestClient, tenant_slug: str, profile_id: str,
                   body: Mapping[str, Any]) -> dict[str, Any]:
    """``PATCH …/delivery-profiles/{id}`` (exits on an HTTP error)."""
    response = client.patch_raw(api_paths.export_delivery_profile(tenant_slug, profile_id), json=dict(body))
    exit_on_api_error(response)
    return _json_object(response, "Delivery profile")


def delete_profile(client: RestClient, tenant_slug: str, profile_id: str) -> None:
    """``DELETE …/delivery-profiles/{id}``."""
    client.delete(api_paths.export_delivery_profile(tenant_slug, profile_id))


def profile_deliveries(client: RestClient, tenant_slug: str, profile_id: str) -> list[dict[str, Any]]:
    """``GET …/delivery-profiles/{id}/deliveries`` — every delivery made with the profile."""
    path = api_paths.export_delivery_profile_deliveries(tenant_slug, profile_id)
    rows = _json_object(client.get(path), "Delivery list").get("deliveries")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def job_deliveries(client: RestClient, tenant_slug: str, job_id: str) -> list[dict[str, Any]]:
    """``GET …/jobs/{job_id}/deliveries`` — every delivery of one export job."""
    rows = _json_object(client.get(api_paths.export_job_deliveries(tenant_slug, job_id)), "Delivery list")
    deliveries = rows.get("deliveries")
    return [r for r in deliveries if isinstance(r, dict)] if isinstance(deliveries, list) else []


def deliver_job(client: RestClient, tenant_slug: str, job_id: str, profile_id: str) -> dict[str, Any]:
    """``POST …/jobs/{job_id}/deliveries`` with ``{profileId}`` — deliver a completed job now."""
    response = client.post(api_paths.export_job_deliveries(tenant_slug, job_id), json={"profileId": profile_id})
    return _json_object(response, "Delivery")


def build_destination(
    channel: str,
    *,
    repository: str | None = None,
    path: str | None = None,
    base_branch: str | None = None,
    mode: str | None = None,
    url: str | None = None,
    secret: str | None = None,
    artifact: str | None = None,
    credential: str | None = None,
    bucket: str | None = None,
    prefix: str | None = None,
    partitioning: str | None = None,
    require: bool = True,
) -> dict[str, Any] | None:
    """The channel block for a profile from command-line flags.

    Args:
        channel: ``git``, ``webhook`` or ``object_storage``.
        repository, path, base_branch, mode: The git destination.
        url, secret, artifact: The webhook destination (``secret`` already read from its source).
        credential, bucket, prefix, partitioning: The object-storage destination (``partitioning``
            comma-separated; ``""`` for none).
        require: Whether the channel's required flags must be present (on create). On an update,
            ``None`` is returned when no destination flag was given.

    Returns:
        ``{<block name>: {...}}``, or ``None`` (update without destination flags).

    Raises:
        typer.Exit: :data:`EXIT_USAGE` for a missing required flag or a flag of another channel.
    """
    flags: dict[str, dict[str, Any]] = {
        "git": {"--repository": repository, "--path": path, "--base-branch": base_branch, "--mode": mode},
        "webhook": {"--url": url, "--secret-env": secret, "--artifact": artifact},
        "object_storage": {"--credential": credential, "--bucket": bucket, "--prefix": prefix,
                           "--partitioning": partitioning},
    }
    if channel not in flags:
        typer.echo(f"--channel must be one of {', '.join(CHANNELS)}.", err=True)
        raise typer.Exit(EXIT_USAGE)
    stray = sorted(name for other, named in flags.items() if other != channel
                   for name, value in named.items() if value is not None)
    if stray:
        typer.echo(f"{', '.join(stray)} do not apply to a {channel} profile.", err=True)
        raise typer.Exit(EXIT_USAGE)
    given = {name: value for name, value in flags[channel].items() if value is not None}
    if not given and not require:
        return None
    required = {"git": ["--repository"], "webhook": ["--url"] + (["--secret-env"] if require else []),
                "object_storage": ["--credential", "--bucket"]}[channel]
    missing = [name for name in required if name not in given]
    if missing:
        typer.echo(f"A {channel} profile needs {', '.join(missing)}.", err=True)
        raise typer.Exit(EXIT_USAGE)
    block: dict[str, Any]
    if channel == "git":
        block = {"repositoryId": repository, "targetPath": path or "", "mode": mode or "pr"}
        if base_branch:
            block["baseBranch"] = base_branch
    elif channel == "webhook":
        block = {"url": url, "artifact": artifact or "auto"}
        if secret is not None:
            block["secret"] = secret
    else:
        block = {"credentialId": credential, "bucket": bucket, "prefix": prefix or ""}
        if partitioning is not None:
            block["partitioning"] = [part.strip() for part in partitioning.split(",") if part.strip()]
    return {CHANNEL_BLOCKS[channel]: block}


def delivery_events(status: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The ``EXPORT_DELIVERED`` / ``EXPORT_DELIVERY_FAILED`` events of a job status, in order."""
    events = status.get("events")
    if not isinstance(events, list):
        return []
    return [e for e in events if isinstance(e, dict) and e.get("code") in DELIVERY_EVENT_CODES]


def wait_for_job_deliveries(
    client: RestClient,
    tenant_slug: str,
    job_id: str,
    *,
    expected: int,
    poll_interval: float,
    timeout: float,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> list[dict[str, Any]]:
    """Wait until a completed job carries one delivery event per profile it was submitted with.

    Args:
        client: The authenticated client.
        tenant_slug: The tenant.
        job_id: The completed job.
        expected: How many profiles it was submitted with.
        poll_interval: Seconds between polls.
        timeout: Seconds to wait in all.
        sleep, monotonic: Clock seams for tests.

    Returns:
        The delivery events seen — fewer than ``expected`` when the wait timed out.
    """
    deadline = monotonic() + timeout
    path = api_paths.export_job(tenant_slug, job_id)
    events: list[dict[str, Any]] = []
    while True:
        events = delivery_events(_json_object(client.get(path), "Export status"))
        remaining = deadline - monotonic()
        if len(events) >= expected or remaining <= 0:
            return events
        sleep(min(poll_interval, remaining))


def format_delivery_events(events: Sequence[Mapping[str, Any]], expected: int, job_id: str) -> list[str]:
    """Human lines for a job's delivery events (stderr), noting deliveries still running."""
    lines = [("Delivered: " if e.get("code") == "EXPORT_DELIVERED" else "Delivery failed: ") + str(e.get("message"))
             for e in events]
    if len(events) < expected:
        lines.append(f"{expected - len(events)} deliver{'y is' if expected - len(events) == 1 else 'ies are'} "
                     f"still running; see apiome export deliveries {job_id}.")
    return lines


def report_job_deliveries(
    client: RestClient,
    tenant_slug: str,
    job_id: str,
    *,
    expected: int,
    poll_interval: float,
    timeout: float,
) -> None:
    """Wait for a completed job's on-completion deliveries, print them (stderr), exit 1 if one failed.

    Args:
        client: The authenticated client.
        tenant_slug: The tenant.
        job_id: The completed job.
        expected: How many profiles it was submitted with (``0`` does nothing).
        poll_interval: Seconds between polls.
        timeout: Seconds to wait in all.

    Raises:
        typer.Exit: :data:`EXIT_ERROR` when a delivery failed.
    """
    if expected <= 0:
        return
    events = wait_for_job_deliveries(client, tenant_slug, job_id, expected=expected,
                                     poll_interval=poll_interval, timeout=timeout)
    for line in format_delivery_events(events, expected, job_id):
        typer.echo(line, err=True)
    if any(event.get("code") == "EXPORT_DELIVERY_FAILED" for event in events):
        raise typer.Exit(EXIT_ERROR)


def resolve_profile_ids(client: RestClient, tenant_slug: str, refs: Sequence[str]) -> list[str]:
    """Profile ids for ``--deliver`` values (names or ids), in order, without repeats."""
    ids: list[str] = []
    for ref in refs:
        profile_id = resolve_profile_id(client, tenant_slug, ref)
        if profile_id not in ids:
            ids.append(profile_id)
    return ids
