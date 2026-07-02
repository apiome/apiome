"""Normalize list responses from ``apiome-rest`` (array or paginated envelope)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from apiome_cli.client.http import RestClient


def fetch_list(
    client: RestClient,
    path: str,
    *,
    params: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """GET ``path`` and return ``(items, total)`` for array or ``{items,total}`` bodies."""
    if params:
        encoded = urlencode(params)
        path = f"{path}?{encoded}" if "?" not in path else f"{path}&{encoded}"
    payload = client.get(path).json()
    if isinstance(payload, list):
        rows = [row for row in payload if isinstance(row, dict)]
        return rows, len(rows)
    if isinstance(payload, dict):
        items_raw = payload.get("items")
        if isinstance(items_raw, list):
            rows = [row for row in items_raw if isinstance(row, dict)]
            total = int(payload.get("total", len(rows)))
            return rows, total
        jobs = payload.get("jobs")
        if isinstance(jobs, list):
            rows = [row for row in jobs if isinstance(row, dict)]
            return rows, len(rows)
        repositories = payload.get("repositories")
        if isinstance(repositories, list):
            rows = [row for row in repositories if isinstance(row, dict)]
            return rows, len(rows)
    return [], 0


def paginate_offset_list(
    client: RestClient,
    path: str,
    *,
    limit: int,
    fetch_all: bool = False,
    params: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Page through offset/limit list endpoints such as ``GET /v1/tenants/me``."""
    base_params: list[tuple[str, str]] = list(params or [])
    items: list[dict[str, Any]] = []
    offset = 0
    total = 0
    while True:
        page_params = [*base_params, ("offset", str(offset)), ("limit", str(limit))]
        page_items, total = fetch_list(client, path, params=page_params)
        items.extend(page_items)
        if not fetch_all or not page_items or offset + limit >= total:
            break
        offset += limit
    return items, total
