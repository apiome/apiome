"""
REPO-12.5 (#2954): emit deduplicated in-app notifications when repository auto/manual
import jobs complete in a state that needs attention.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

from ..database import db
from .spec_detail import _count_change_report_categories

_logger = logging.getLogger(__name__)

_DEFAULT_REPOSITORY_NOTIFICATION_PREFS: Dict[str, bool] = {
    "auto_import_failed": True,
    "auto_import_breaking": True,
    "auto_import_warnings": False,
    "mapping_required": True,
}

_ELIGIBLE_SOURCE_KINDS: Set[str] = {"repository_auto_import", "repository_manual_import"}


def _openapi_warnings_count(change_model: Dict[str, Any] | None) -> int:
    if not isinstance(change_model, dict):
        return 0
    w = change_model.get("warnings")
    return len(w) if isinstance(w, list) else 0


def _parse_repository_notification_prefs(settings: Dict[str, Any]) -> Dict[str, bool]:
    out = dict(_DEFAULT_REPOSITORY_NOTIFICATION_PREFS)
    root = settings.get("notifications") if isinstance(settings.get("notifications"), dict) else {}
    repo = root.get("repository") if isinstance(root.get("repository"), dict) else {}
    for k, default in _DEFAULT_REPOSITORY_NOTIFICATION_PREFS.items():
        v = repo.get(k)
        if isinstance(v, bool):
            out[k] = v
    return out


def _collect_signals(
    *,
    state: str,
    change_model: Dict[str, Any] | None,
    conflict_records: List[Dict[str, Any]] | None,
) -> Dict[str, bool]:
    breaking, _a = _count_change_report_categories(change_model)
    openapi_warn = _openapi_warnings_count(change_model)
    conflicts = len(conflict_records or [])
    return {
        "failed": state == "failed",
        "breaking": breaking > 0,
        "warnings": openapi_warn > 0,
        "mapping_required": conflicts > 0,
        "pending_review": state == "pending_review",
    }


def _user_wants_notification(prefs: Dict[str, bool], signals: Dict[str, bool]) -> bool:
    if signals["failed"] and prefs["auto_import_failed"]:
        return True
    if signals["breaking"] and prefs["auto_import_breaking"]:
        return True
    if signals["warnings"] and prefs["auto_import_warnings"]:
        return True
    if signals["mapping_required"] and prefs["mapping_required"]:
        return True
    if signals["pending_review"] and prefs["auto_import_breaking"]:
        return True
    return False


def _reason_labels(signals: Dict[str, bool]) -> List[str]:
    labels: List[str] = []
    if signals["failed"]:
        labels.append("import failed")
    if signals["breaking"]:
        labels.append("breaking changes")
    if signals["warnings"]:
        labels.append("lint warnings")
    if signals["mapping_required"]:
        labels.append("mapping required")
    if signals["pending_review"] and not signals["failed"]:
        labels.append("awaiting review")
    return labels


def _build_links(
    *,
    repository_id: str,
    repository_file_id: str,
    change_report_id: Optional[str],
    failed: bool,
) -> Dict[str, str]:
    base = f"/ade/dashboard/repositories/{repository_id}"
    specs = f"{base}?tab=specs&fileId={repository_file_id}"
    if change_report_id:
        sync = f"{base}?tab=sync&changeReportId={change_report_id}"
    else:
        sync = f"{base}?tab=sync"
    if failed:
        primary = sync
    elif change_report_id:
        primary = sync
    else:
        primary = specs
    return {"primary": primary, "changeReport": sync, "specsRow": specs, "syncConsole": f"{base}?tab=sync"}


def emit_repository_import_notifications(
    *,
    tenant_id: str,
    repository_id: str,
    repository_full_name: str,
    import_selection_actor_id: Optional[str],
    repository_file_id: str,
    import_job_id: str,
    source_kind: str,
    state: str,
    change_model: Optional[Dict[str, Any]],
    conflict_records: Optional[List[Dict[str, Any]]],
    change_report_id: Optional[str],
) -> None:
    if source_kind not in _ELIGIBLE_SOURCE_KINDS:
        return

    signals = _collect_signals(state=state, change_model=change_model, conflict_records=conflict_records)
    if not any(signals.values()):
        return

    recipient_ids: List[str] = []
    if import_selection_actor_id:
        try:
            UUID(str(import_selection_actor_id))
            recipient_ids.append(str(import_selection_actor_id))
        except ValueError:
            pass

    # Tenant subscribers (repository-event channels) — placeholder until subscriber store exists (#2954 scope).
    # for uid in db.list_repository_event_subscriber_user_ids(tenant_id):
    #     ...

    if not recipient_ids:
        return

    links = _build_links(
        repository_id=repository_id,
        repository_file_id=repository_file_id,
        change_report_id=(change_report_id or "").strip() or None,
        failed=signals["failed"],
    )

    reasons = _reason_labels(signals)
    title = f"Repository import needs attention — {repository_full_name}"
    body = "; ".join(reasons) if reasons else "Repository import requires attention"

    for uid in recipient_ids:
        prefs = _parse_repository_notification_prefs(db.get_user_settings(uid, tenant_id))
        if not _user_wants_notification(prefs, signals):
            continue
        inserted = db.insert_repository_import_notification_if_absent(
            tenant_id=tenant_id,
            import_job_id=import_job_id,
            recipient_user_id=uid,
            repository_id=repository_id,
            title=title,
            body=body,
            primary_link=links["primary"],
            payload={
                "repositoryFullName": repository_full_name,
                "signals": signals,
                "links": links,
                "importJobId": import_job_id,
            },
        )
        if not inserted:
            continue
        _maybe_send_repository_notification_email_digest(uid, tenant_id)


def _maybe_send_repository_notification_email_digest(user_id: str, tenant_id: str) -> None:
    """Enterprise email + Slack are stubbed; enforce a 15-minute digest window per recipient."""
    now = datetime.now(timezone.utc)
    if not db.repository_import_notification_email_may_send(user_id, tenant_id, now):
        return
    # No SMTP integration in this codebase — record the window so duplicates are not "sent".
    db.touch_repository_import_notification_email_digest(user_id, tenant_id, now)
