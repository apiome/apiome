"""Shadow-API report helpers for ``apiome connectors shadow-report`` (CDG-1.6).

The report is computed server-side (``GET /v1/tenants/{t}/shadow-report``); this module parses the
``--fail-on`` list, decides which named categories have rows, and lays the report out as table
rows. Kept apart from the command so the rules are testable without a REST mock.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

#: Categories ``--fail-on`` accepts, and the report key each one counts.
CATEGORY_KEYS: dict[str, str] = {
    "shadow": "shadow",
    "possible-matches": "possibleMatches",
    "undeployed": "undeployed",
    "drift": "drift",
}

#: Output formats ``--format`` accepts.
FORMATS = ("table", "json")


def parse_fail_on(value: str | None) -> list[str]:
    """Parse ``--fail-on shadow,drift`` into known category names.

    :param value: The raw option (comma-separated; case and spaces ignored).
    :returns: The categories, in :data:`CATEGORY_KEYS` order, without repeats.
    :raises ValueError: When a name is not a category.
    """
    names = {part.strip().lower() for part in (value or "").split(",") if part.strip()}
    unknown = sorted(names - set(CATEGORY_KEYS))
    if unknown:
        raise ValueError(
            f"unknown categor{'y' if len(unknown) == 1 else 'ies'} {', '.join(unknown)}; "
            f"choose from {', '.join(CATEGORY_KEYS)}"
        )
    return [name for name in CATEGORY_KEYS if name in names]


def failing_categories(report: Mapping[str, Any], fail_on: Sequence[str]) -> list[str]:
    """The ``fail_on`` categories that have at least one row.

    :param report: The report JSON.
    :param fail_on: Categories from :func:`parse_fail_on`.
    :returns: The non-empty named categories, in :data:`CATEGORY_KEYS` order.
    """
    summary = report.get("summary") or {}
    return [
        name for name in fail_on if int(summary.get(CATEGORY_KEYS[name], 0) or 0) > 0
    ]


def _served_at(row: Mapping[str, Any]) -> str:
    hosts = list(row.get("hosts") or [])
    base = row.get("basePath") or ""
    if not hosts:
        return base or "-"
    return ", ".join(
        host if "://" in host or not base else f"{host}{base}" for host in hosts
    )


def table_rows(report: Mapping[str, Any]) -> list[dict[str, str]]:
    """Every row of every section, flattened for one table.

    :param report: The report JSON.
    :returns: ``{category, api, connector, environment, served_at, detail}`` per row; ``detail``
        is the possible match (tier and confidence), the drift revisions, or the ignore reason.
    """
    rows: list[dict[str, str]] = []
    for category, key in (*CATEGORY_KEYS.items(), ("ignored", "ignored")):
        for row in report.get(key) or []:
            if category == "undeployed":
                rows.append(
                    {
                        "category": category,
                        "api": str(row.get("name") or row.get("projectId")),
                        "connector": "-",
                        "environment": "-",
                        "served_at": ", ".join(row.get("servers") or []) or "-",
                        "detail": "Project"
                        if row.get("kind") == "project"
                        else "Catalog item",
                    }
                )
                continue
            detail = ""
            match = row.get("match") or {}
            if match:
                target = match.get("target") or {}
                detail = (
                    f"{target.get('name')} ({match.get('tier')}, "
                    f"{round(float(match.get('confidence') or 0) * 100)}%)"
                )
            elif category == "drift":
                detail = f"deployed {row.get('deployedRevision')} vs catalog {row.get('catalogRevision')}"
            elif row.get("ignored"):
                detail = str((row.get("ignored") or {}).get("reason") or "")
                if (row.get("ignored") or {}).get("reappeared"):
                    detail = f"reappeared (was ignored: {detail})"
            rows.append(
                {
                    "category": category,
                    "api": str(row.get("name") or row.get("remoteId")),
                    "connector": str(row.get("connectorName") or "-"),
                    "environment": str(row.get("environment") or "-"),
                    "served_at": _served_at(row),
                    "detail": detail or "-",
                }
            )
    return rows
