"""
Change-report audit trail — the verbs and the write helper (#2705, CR-V2-01).

Every change to a publication change report or to its templates appends one row to
``apiome.change_report_audit`` with the acting user and a timestamp: report edits and
regenerations, the three approval transitions, PDF exports, and template creation and default
changes. This module centralises the vocabulary and the single best-effort write helper, in
the shape of ``registry_audit.py``; the read side is in ``change_report_enterprise_routes.py``.

Audit rows are written whether or not the tenant holds the ``change-report-enterprise``
entitlement — the trail should not have a hole for the time before a tenant upgraded — and
only *reading* it is gated.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .auth import get_authenticated_user_id

_logger = logging.getLogger(__name__)

ACTION_REPORT_EDIT = "report.edit"
ACTION_REPORT_REGENERATE = "report.regenerate"
ACTION_REPORT_SUBMIT = "report.submit"
ACTION_REPORT_APPROVE = "report.approve"
ACTION_REPORT_REJECT = "report.reject"
ACTION_REPORT_EXPORT_PDF = "report.export_pdf"
ACTION_TEMPLATE_CREATE = "template.create"
ACTION_TEMPLATE_DEFAULT_TENANT = "template.default_tenant"
ACTION_TEMPLATE_DEFAULT_PROJECT = "template.default_project"

#: Every verb this service writes — the values the audit list's ``action`` filter accepts.
CHANGE_REPORT_AUDIT_ACTIONS = (
    ACTION_REPORT_EDIT,
    ACTION_REPORT_REGENERATE,
    ACTION_REPORT_SUBMIT,
    ACTION_REPORT_APPROVE,
    ACTION_REPORT_REJECT,
    ACTION_REPORT_EXPORT_PDF,
    ACTION_TEMPLATE_CREATE,
    ACTION_TEMPLATE_DEFAULT_TENANT,
    ACTION_TEMPLATE_DEFAULT_PROJECT,
)


def record_change_report_audit(
    db: Any,
    auth_data: Dict[str, Any],
    action: str,
    *,
    project_id: Optional[str] = None,
    change_report_id: Optional[str] = None,
    published_revision_id: Optional[str] = None,
    template_version_id: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    """Write one change-report audit row for an action that has just succeeded.

    Best-effort: any error (including resolving the actor) is logged and swallowed, so an audit
    write can never fail the action it records.

    Args:
        db: The database accessor (passed in so the caller's patched/test db is used).
        auth_data: The request's resolved auth context (carries ``tenant_id`` and the actor).
        action: One of the ``ACTION_*`` verbs.
        project_id: Project the event belongs to, when it has one.
        change_report_id: Affected report id; None for template events.
        published_revision_id: Published version of the affected report, when one.
        template_version_id: Template version involved, when one.
        detail: Structured JSON context (changed fields, states, note, PDF hash).
    """
    try:
        db.insert_change_report_audit(
            auth_data.get("tenant_id"),
            action,
            project_id=project_id,
            change_report_id=change_report_id,
            published_revision_id=published_revision_id,
            template_version_id=template_version_id,
            actor_id=get_authenticated_user_id(auth_data),
            detail=detail,
        )
    except Exception as e:
        _logger.warning("record_change_report_audit(%s) failed: %s", action, e)
