"""Export delivery profiles: the rules — MFX-38.4 (#4331).

Git (MFX-38.1), webhook (MFX-38.2) and object-storage (MFX-38.3) delivery each take their destination
in the request. A **delivery profile** is that destination stored once, by name, for the workspace:
a channel, the channel's non-secret request fields, and a reference to the credential it delivers
with. A person, a pipeline or a scheduled export (MFX-39.4) then delivers a job by naming the profile.
This module is the pure half — no database, no network:

* **The request** (:class:`DeliveryProfileCreate`, :class:`DeliveryProfileUpdate`,
  :func:`normalize_create`, :func:`normalize_update`) — a name, a description and exactly one channel
  block, validated by the channel's own rules (:func:`app.export_git_delivery.normalize_request`, …),
  so a profile can never hold a destination its channel would refuse.
* **The stored destination** — the channel's request fields in camelCase, exactly as its delivery
  endpoint takes them, so :func:`channel_request` rebuilds that endpoint's body from it.
* **The credential reference** (:func:`credential_ref`) — the git repository (its linked account is
  the credential), the storage credential in the vault, or the webhook signing secret, which has
  nowhere else to live and is sealed on the profile. A secret is never returned.
* **The outcome** (:func:`delivery_outcome`) — every channel's statuses folded into ``in_progress``,
  ``delivered`` or ``failed``, so one list can show every attempt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Mapping, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .export_git_delivery import ExportGitDeliveryRequestError, GitDeliveryRequest
from .export_git_delivery import normalize_request as normalize_git_request
from .export_object_storage_delivery import ExportObjectStorageRequestError, ObjectStorageDeliveryRequest
from .export_object_storage_delivery import normalize_request as normalize_object_storage_request
from .export_webhook_delivery import (
    SECRET_MAX_CHARS,
    SECRET_MIN_CHARS,
    URL_MAX_CHARS,
    WebhookDeliveryRequest,
    display_url,
)
from .ssrf_guard import SSRFError, validate_url_policy

__all__ = [
    "CHANNELS",
    "DESCRIPTION_MAX_CHARS",
    "NAME_MAX_CHARS",
    "DeliveryProfileCreate",
    "DeliveryProfileRequestError",
    "DeliveryProfileUpdate",
    "NormalizedProfile",
    "WebhookProfileDestination",
    "channel_request",
    "credential_ref",
    "delivery_outcome",
    "normalize_create",
    "normalize_update",
    "public_destination",
]

#: The delivery channels a profile can name.
CHANNELS = ("git", "webhook", "object_storage")
NAME_MAX_CHARS = 120
DESCRIPTION_MAX_CHARS = 1000

#: The request field that carries each channel's block.
_BLOCK_FIELDS = {"git": "git", "webhook": "webhook", "object_storage": "objectStorage"}

#: Each channel's run statuses that mean "the destination has it".
_DELIVERED_STATUSES = {
    "git": frozenset({"opened", "updated", "unchanged", "up_to_date", "committed"}),
    "webhook": frozenset({"delivered"}),
    "object_storage": frozenset({"delivered"}),
}

ChannelRequest = Union[GitDeliveryRequest, WebhookDeliveryRequest, ObjectStorageDeliveryRequest]


class DeliveryProfileRequestError(ValueError):
    """A profile request that cannot be accepted.

    Attributes:
        errors: One message per problem, so a form can mark every bad field at once.
    """

    def __init__(self, *errors: str) -> None:
        self.errors: List[str] = [str(error) for error in errors if error]
        super().__init__("; ".join(self.errors) or "invalid export delivery profile")


class WebhookProfileDestination(BaseModel):
    """A webhook profile's destination: the webhook delivery body, the secret kept sealed."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    url: str = Field(description="The receiver: a public `https` (or `http`) URL. Shown without its query "
                     "string, which often carries a token.")
    secret: Optional[SecretStr] = Field(
        default=None,
        description=f"The shared signing secret ({SECRET_MIN_CHARS}–{SECRET_MAX_CHARS} characters). Required "
        "when the profile is created; on an update, leave it out to keep the stored one. Sealed on arrival "
        "and never returned.",
    )
    artifact: Literal["auto", "fetch"] = Field(
        default="auto",
        description="How the bundle travels: `auto` (inline when small enough) or `fetch` (always a signed link).",
    )


class DeliveryProfileCreate(BaseModel):
    """A new delivery profile: ``POST /v1/export/{tenant}/delivery-profiles``."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str = Field(description=f"A name unique in the workspace (`orders-to-data-lake`), up to "
                      f"{NAME_MAX_CHARS} characters.")
    description: Optional[str] = Field(default=None, description="What the profile is for.")
    channel: Literal["git", "webhook", "object_storage"] = Field(description="The delivery channel.")
    git: Optional[GitDeliveryRequest] = Field(
        default=None, description="For `channel: git` — the git delivery body.")
    webhook: Optional[WebhookProfileDestination] = Field(
        default=None, description="For `channel: webhook` — the webhook delivery body.")
    object_storage: Optional[ObjectStorageDeliveryRequest] = Field(
        default=None, alias="objectStorage", description="For `channel: object_storage` — the object-storage "
        "delivery body.")


class DeliveryProfileUpdate(BaseModel):
    """A change to a profile: ``PATCH /v1/export/{tenant}/delivery-profiles/{id}``. The channel is fixed."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: Optional[str] = Field(default=None, description="A new name.")
    description: Optional[str] = Field(default=None, description="A new description; `\"\"` clears it.")
    git: Optional[GitDeliveryRequest] = Field(default=None, description="A new git destination (replaces it).")
    webhook: Optional[WebhookProfileDestination] = Field(
        default=None, description="A new webhook destination (replaces it; leave `secret` out to keep it).")
    object_storage: Optional[ObjectStorageDeliveryRequest] = Field(
        default=None, alias="objectStorage", description="A new object-storage destination (replaces it).")


@dataclass(frozen=True)
class NormalizedProfile:
    """A validated profile.

    Attributes:
        name: The trimmed name.
        description: The trimmed description, or ``None``.
        channel: ``git``, ``webhook`` or ``object_storage``.
        destination: The channel's non-secret request fields (camelCase), or ``None`` when an update
            leaves the destination as it is.
        secret: A webhook signing secret to seal, or ``None`` to keep the stored one (or for another channel).
    """

    name: str
    description: Optional[str]
    channel: str
    destination: Optional[Dict[str, Any]]
    secret: Optional[str]


def _name_problems(name: str) -> List[str]:
    """Why a (trimmed) name cannot be used, if it cannot."""
    if not name:
        return ["name is required"]
    if len(name) > NAME_MAX_CHARS:
        return [f"name is longer than {NAME_MAX_CHARS} characters"]
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        return ["name cannot contain a control character"]
    return []


def _description(value: Optional[str], problems: List[str]) -> Optional[str]:
    """A trimmed description (``None`` when blank), noting one that is too long."""
    text = (value or "").strip()
    if len(text) > DESCRIPTION_MAX_CHARS:
        problems.append(f"description is longer than {DESCRIPTION_MAX_CHARS} characters")
    return text or None


def _webhook_destination(block: WebhookProfileDestination, *, require_secret: bool,
                         problems: List[str]) -> tuple[Dict[str, Any], Optional[str]]:
    """Validate a webhook block as the webhook channel would; return its destination and secret."""
    url = (block.url or "").strip()
    if not url:
        problems.append("webhook.url is required")
    elif len(url) > URL_MAX_CHARS:
        problems.append(f"webhook.url is longer than {URL_MAX_CHARS} characters")
    else:
        try:
            validate_url_policy(url)
        except SSRFError as exc:
            problems.append(f"webhook.url: {exc}")
    secret = block.secret.get_secret_value() if block.secret is not None else None
    if secret is None:
        if require_secret:
            problems.append("webhook.secret is required")
    elif not SECRET_MIN_CHARS <= len(secret) <= SECRET_MAX_CHARS:
        problems.append(f"webhook.secret must be {SECRET_MIN_CHARS}–{SECRET_MAX_CHARS} characters")
    return {"url": url, "artifact": block.artifact}, secret


def _destination(channel: str, block: Any, *, require_secret: bool,
                 problems: List[str]) -> tuple[Dict[str, Any], Optional[str]]:
    """Validate one channel block with that channel's own rules.

    Args:
        channel: The profile's channel.
        block: The request's block for it.
        require_secret: Whether a webhook block must carry its secret (on create).
        problems: Collects every problem found, prefixed by the block's field name.

    Returns:
        ``(destination, secret)`` — the stored camelCase fields and a webhook secret (else ``None``).
    """
    prefix = _BLOCK_FIELDS[channel] + "."
    if channel == "webhook":
        return _webhook_destination(block, require_secret=require_secret, problems=problems)
    try:
        if channel == "git":
            git = normalize_git_request(block)
            return {"repositoryId": git.repository_id, "targetPath": git.target_path,
                    "baseBranch": git.base_branch, "mode": git.mode}, None
        storage = normalize_object_storage_request(block)
        return {"credentialId": storage.credential_id, "bucket": storage.bucket, "prefix": storage.prefix,
                "partitioning": list(storage.partitioning)}, None
    except (ExportGitDeliveryRequestError, ExportObjectStorageRequestError) as exc:
        problems.extend(prefix + error for error in exc.errors)
        return {}, None


def _blocks(request: Union[DeliveryProfileCreate, DeliveryProfileUpdate]) -> Dict[str, Any]:
    """The channel blocks a request carries, by channel."""
    found = {"git": request.git, "webhook": request.webhook, "object_storage": request.object_storage}
    return {channel: block for channel, block in found.items() if block is not None}


def normalize_create(request: DeliveryProfileCreate) -> NormalizedProfile:
    """Validate a new profile.

    Args:
        request: The request body.

    Returns:
        The :class:`NormalizedProfile`, with a destination (and, for a webhook, the secret).

    Raises:
        DeliveryProfileRequestError: For a bad name or description, a missing block for the channel, a
            block for another channel, or a destination the channel would refuse.
    """
    problems: List[str] = []
    name = (request.name or "").strip()
    problems.extend(_name_problems(name))
    description = _description(request.description, problems)
    blocks = _blocks(request)
    channel = request.channel
    others = sorted(_BLOCK_FIELDS[other] for other in blocks if other != channel)
    if others:
        problems.append(f"a {channel} profile cannot carry {', '.join(others)}")
    destination: Dict[str, Any] = {}
    secret: Optional[str] = None
    if channel not in blocks:
        problems.append(f"{_BLOCK_FIELDS[channel]} is required for a {channel} profile")
    else:
        destination, secret = _destination(channel, blocks[channel], require_secret=True, problems=problems)
    if problems:
        raise DeliveryProfileRequestError(*problems)
    return NormalizedProfile(name=name, description=description, channel=channel, destination=destination,
                             secret=secret)


def normalize_update(request: DeliveryProfileUpdate, existing: Mapping[str, Any]) -> NormalizedProfile:
    """Validate a change to a stored profile, filling what it leaves out from the profile.

    Args:
        request: The request body.
        existing: The stored profile row (``name``, ``description``, ``channel``, ``destination``).

    Returns:
        The :class:`NormalizedProfile` to store; ``destination`` is ``None`` when it is unchanged and
        ``secret`` is ``None`` when the stored one is kept.

    Raises:
        DeliveryProfileRequestError: For a bad name or description, a block for another channel, or a
            destination the channel would refuse.
    """
    problems: List[str] = []
    channel = str(existing.get("channel") or "")
    name = (request.name if request.name is not None else str(existing.get("name") or "")).strip()
    problems.extend(_name_problems(name))
    description = (_description(request.description, problems) if request.description is not None
                   else existing.get("description"))
    blocks = _blocks(request)
    others = sorted(_BLOCK_FIELDS[other] for other in blocks if other != channel)
    if others:
        problems.append(f"a {channel} profile cannot carry {', '.join(others)}; its channel cannot change")
    destination: Optional[Dict[str, Any]] = None
    secret: Optional[str] = None
    if channel in blocks:
        destination, secret = _destination(channel, blocks[channel], require_secret=False, problems=problems)
    if problems:
        raise DeliveryProfileRequestError(*problems)
    return NormalizedProfile(name=name, description=description, channel=channel, destination=destination,
                             secret=secret)


def channel_request(channel: str, destination: Mapping[str, Any], secret: Optional[str] = None) -> ChannelRequest:
    """Rebuild the channel's delivery body from a stored destination.

    Args:
        channel: The profile's channel.
        destination: Its stored destination.
        secret: The unsealed webhook secret (webhook channel only).

    Returns:
        The :class:`GitDeliveryRequest`, :class:`WebhookDeliveryRequest` or
        :class:`ObjectStorageDeliveryRequest` the channel's delivery takes.

    Raises:
        ValueError: For an unknown channel, or a webhook profile without a secret.
    """
    fields = dict(destination or {})
    if channel == "git":
        return GitDeliveryRequest.model_validate(fields)
    if channel == "object_storage":
        return ObjectStorageDeliveryRequest.model_validate(fields)
    if channel == "webhook":
        if not secret:
            raise ValueError("a webhook profile needs its signing secret to deliver")
        return WebhookDeliveryRequest.model_validate({**fields, "secret": secret})
    raise ValueError(f"unknown export delivery channel {channel!r}")


def credential_ref(channel: str, destination: Mapping[str, Any]) -> Dict[str, Optional[str]]:
    """What the profile delivers with, by reference — never a secret.

    Returns:
        ``{"kind": "repository", "id": …}`` (the repository's linked account), ``{"kind":
        "storage_credential", "id": …}`` or ``{"kind": "webhook_secret", "id": None}`` (sealed on the profile).
    """
    if channel == "git":
        return {"kind": "repository", "id": destination.get("repositoryId")}
    if channel == "object_storage":
        return {"kind": "storage_credential", "id": destination.get("credentialId")}
    return {"kind": "webhook_secret", "id": None}


def public_destination(channel: str, destination: Mapping[str, Any]) -> Dict[str, Any]:
    """The destination as a response shows it: a webhook URL without its query string."""
    shown = dict(destination or {})
    if channel == "webhook" and shown.get("url"):
        shown["url"] = display_url(str(shown["url"]))
    return shown


def delivery_outcome(channel: str, status: Optional[str]) -> str:
    """Fold a channel's run status into ``in_progress``, ``delivered`` or ``failed``."""
    if status == "failed":
        return "failed"
    if status in _DELIVERED_STATUSES.get(channel, frozenset()):
        return "delivered"
    return "in_progress"
