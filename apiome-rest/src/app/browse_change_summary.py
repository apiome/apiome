"""
Human-readable change blurbs for public browse version listings (#3246).

Uses publication ``change_model_json`` when present; otherwise falls back to
``change_log`` / ``description``.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set


def _parse_change_model(raw: Any) -> Optional[Dict[str, Any]]:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _one_line(text: str, max_len: int = 96) -> str:
    line = text.strip().splitlines()[0].strip()
    if len(line) <= max_len:
        return line
    return line[: max_len - 1].rstrip() + "…"


def _structured_summary(model: Dict[str, Any], baseline_version_slug: Optional[str]) -> Optional[str]:
    schemas = model.get("schemas") if isinstance(model.get("schemas"), dict) else {}
    added_n = len(schemas.get("added") or []) if isinstance(schemas.get("added"), list) else 0
    removed_n = len(schemas.get("removed") or []) if isinstance(schemas.get("removed"), list) else 0
    modified_n = len(schemas.get("modified") or []) if isinstance(schemas.get("modified"), list) else 0

    docs = model.get("documentation") if isinstance(model.get("documentation"), list) else []
    path_keys: Set[str] = set()
    for row in docs:
        if not isinstance(row, dict):
            continue
        if row.get("scope") != "operation":
            continue
        ck = row.get("changeKind")
        if ck not in ("added", "removed", "modified"):
            continue
        p = row.get("path")
        if isinstance(p, str) and p:
            path_keys.add(p)

    parts: List[str] = []
    if path_keys:
        parts.append(f"{len(path_keys)} paths changed")
    class_moves = modified_n + added_n + removed_n
    if class_moves:
        parts.append(f"~{class_moves} classes")

    if not parts:
        return None

    suffix = f" vs v{baseline_version_slug}" if baseline_version_slug else ""
    return ", ".join(parts) + suffix


def browse_version_changes_summary(
    *,
    change_model_json: Any,
    change_log: Optional[str],
    description: Optional[str],
    baseline_version_slug: Optional[str],
) -> Optional[str]:
    """
    Single-line summary for CLI / API ``changes_summary`` field.

    Prefers structured diff stats when ``change_model_json`` yields a non-empty summary;
    otherwise ``change_log``, then truncated ``description``.
    """
    model = _parse_change_model(change_model_json)
    if model:
        structured = _structured_summary(model, baseline_version_slug)
        if structured:
            return structured

    if change_log and str(change_log).strip():
        return _one_line(str(change_log))

    if description and str(description).strip():
        return _one_line(str(description))

    return None
