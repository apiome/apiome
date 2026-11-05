"""What a delivery produced, per channel — MFX-46.3 (#4381).

The Review step's **Deliver** section shows, for each delivery of an export, the artifact it left behind
where it went: the **pull request** a git delivery opened (or the commit it made), the **receipt** a
webhook receiver answered with, the **objects** an object-storage delivery wrote. Each delivery attempt
of ``GET …/jobs/{job}/deliveries`` (MFX-38.4) carries it as ``result`` (:class:`ExportDeliveryResult`),
built here from the channel's run row by :func:`delivery_result`.

Nothing secret is ever part of a result: a webhook's signature and payload stay in the run, a URL loses
its user-info and query (where a token would ride), and storage credentials are never read.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import quote, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["MAX_RESULT_OBJECTS", "ExportDeliveryResult", "delivery_result", "public_url"]

#: The most object URLs a result lists (``object_count`` still counts every one).
MAX_RESULT_OBJECTS = 20


class ExportDeliveryResult(BaseModel):
    """The artifact one delivery left at its destination (the fields of its own channel only)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # git
    mode: Optional[str] = Field(default=None, description="git: `pr` or `commit`.")
    pull_request_url: Optional[str] = Field(
        default=None, serialization_alias="pullRequestUrl", description="git: the pull request opened or updated."
    )
    pull_request_number: Optional[int] = Field(default=None, serialization_alias="pullRequestNumber")
    branch: Optional[str] = Field(default=None, description="git: the branch the files were written on.")
    commit_sha: Optional[str] = Field(default=None, serialization_alias="commitSha", description="git: the commit.")
    # webhook
    http_status: Optional[int] = Field(
        default=None, serialization_alias="httpStatus", description="webhook: the receiver's last HTTP status."
    )
    payload_sha256: Optional[str] = Field(
        default=None, serialization_alias="payloadSha256", description="webhook: the digest of the body sent."
    )
    # object storage
    object_urls: List[str] = Field(
        default_factory=list,
        serialization_alias="objectUrls",
        description=f"object storage: the objects written (at most {MAX_RESULT_OBJECTS}).",
    )
    object_count: Optional[int] = Field(
        default=None, serialization_alias="objectCount", description="object storage: how many objects were written."
    )
    manifest_url: Optional[str] = Field(
        default=None, serialization_alias="manifestUrl", description="object storage: the delivery manifest."
    )


def public_url(url: Optional[str]) -> Optional[str]:
    """``url`` without its user-info, query or fragment (where credentials or tokens would ride).

    Args:
        url: A stored URL, or ``None``.

    Returns:
        The URL safe to show, or ``None``.
    """
    if not url:
        return None
    parts = urlsplit(str(url))
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", "")) or None


def _object_url(endpoint_url: Optional[str], bucket: str, key: str) -> str:
    """Where one object lives: ``{endpoint}/{bucket}/{key}`` (path style), or ``s3://{bucket}/{key}``."""
    path = quote(key, safe="/")
    base = public_url(endpoint_url)
    if base:
        return f"{base.rstrip('/')}/{quote(bucket, safe='')}/{path}"
    return f"s3://{bucket}/{path}"


def delivery_result(channel: str, row: Mapping[str, Any]) -> Optional[ExportDeliveryResult]:
    """The artifact a delivery left, from its channel's run row (pure).

    Args:
        channel: ``git``, ``webhook`` or ``object_storage``.
        row: The run's columns (``result_*`` from ``list_export_delivery_attempts``).

    Returns:
        The result, or ``None`` when the delivery has produced nothing to show yet.
    """
    if channel == "git":
        result = ExportDeliveryResult(
            mode=row.get("result_mode"),
            pull_request_url=public_url(row.get("result_pull_request_url")),
            pull_request_number=row.get("result_pull_request_number"),
            branch=row.get("result_branch"),
            commit_sha=row.get("result_commit_sha"),
        )
    elif channel == "webhook":
        result = ExportDeliveryResult(
            http_status=row.get("result_http_status"),
            payload_sha256=row.get("result_payload_sha256"),
        )
    elif channel == "object_storage":
        bucket = str(row.get("result_bucket") or "")
        objects = [o for o in row.get("result_objects") or [] if isinstance(o, Mapping) and o.get("key")]
        manifest_key = row.get("result_manifest_key")
        endpoint = row.get("result_endpoint_url")
        result = ExportDeliveryResult(
            object_urls=[_object_url(endpoint, bucket, str(o["key"])) for o in objects[:MAX_RESULT_OBJECTS]],
            object_count=len(objects) if objects else None,
            manifest_url=_object_url(endpoint, bucket, str(manifest_key)) if manifest_key and bucket else None,
        )
    else:
        return None
    meaningful: Dict[str, Any] = result.model_dump(exclude_defaults=True)
    return result if meaningful else None
