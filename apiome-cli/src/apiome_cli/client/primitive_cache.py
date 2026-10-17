"""A short-lived local cache of a tenant's primitives (CLI 6.3, #3225).

``apiome properties create`` suggests primitive names while you type and copies the chosen
primitive's JSON Schema, so it needs the tenant's primitive list (``GET /v1/primitives/{tenant}``,
schemas included). The list is kept for :data:`TTL_SECONDS` in
``$XDG_CACHE_HOME/apiome/primitives-<key>.json`` (``~/.cache`` when unset), one file per server
and tenant. The cache is a convenience: a file that cannot be read or written is ignored and the
list is fetched again.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional

from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.client.list_response import fetch_list
from apiome_cli.config import APP_CONFIG_DIR_NAME

#: How long a cached primitive list is used before it is fetched again (5 minutes).
TTL_SECONDS = 300


def cache_dir() -> Path:
    """``$XDG_CACHE_HOME/apiome`` (``~/.cache/apiome`` when the variable is unset)."""
    cache_home = os.environ.get("XDG_CACHE_HOME")
    base = Path(cache_home) if cache_home else Path.home() / ".cache"
    return base / APP_CONFIG_DIR_NAME


def cache_path(base_url: str, tenant_slug: str) -> Path:
    """The cache file for one server and tenant (a hash, so no URL lands in a file name)."""
    key = hashlib.sha256(f"{base_url}|{tenant_slug}".encode("utf-8")).hexdigest()[:16]
    return cache_dir() / f"primitives-{key}.json"


def _read(path: Path, now: float) -> Optional[list[dict[str, Any]]]:
    """The cached list when the file is fresh and well formed, else ``None``."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict) or not isinstance(document.get("items"), list):
        return None
    fetched_at = document.get("fetched_at")
    if not isinstance(fetched_at, (int, float)) or not 0 <= now - fetched_at < TTL_SECONDS:
        return None
    return [item for item in document["items"] if isinstance(item, dict)]


def _write(path: Path, items: list[dict[str, Any]], now: float) -> None:
    """Store ``items`` (best effort: a read-only home must not fail the command)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"fetched_at": now, "items": items}), encoding="utf-8")
    except OSError:
        pass


def load_primitives(
    client: RestClient,
    tenant_slug: str,
    *,
    clock: Callable[[], float] = time.time,
) -> list[dict[str, Any]]:
    """The tenant's primitives, from the cache when it is under :data:`TTL_SECONDS` old.

    Args:
        client: The REST client (its ``base_url`` keys the cache).
        tenant_slug: The tenant whose primitives are listed.
        clock: Seconds since the epoch; injectable for tests.

    Returns:
        The primitive rows (``id``, ``name``, ``schema``, ``schema_id`` …).
    """
    now = clock()
    path = cache_path(client.base_url, tenant_slug)
    cached = _read(path, now)
    if cached is not None:
        return cached
    items, _total = fetch_list(client, api_paths.primitives(tenant_slug))
    rows = [item for item in items if isinstance(item, dict)]
    _write(path, rows, now)
    return rows
