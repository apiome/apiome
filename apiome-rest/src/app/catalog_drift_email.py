"""Catalog drift email — MFI-31.3a (#6384).

When a tenant turned on **Email me about drift too** (``catalog_drift_settings.email_enabled``) and
the installation has a mailer (:mod:`app.mailer`), drift is emailed beside the webhook:

* **Right away** (:func:`email_event`): one email per announced event to each member of the item's
  confirmed owner team — the people owner routing (:mod:`app.owner_routing`) gives an inbox row,
  minus whoever the refresh acted as.
* **Daily digest** (:func:`email_digest`): one email per recipient per digest, listing the waiting
  drift of the items that recipient's team owns. Nobody is told about another team's items.

An item with no confirmed owner is emailed to nobody (it is in the Unowned findings report). A
member with no address, or a disabled or deleted account, is skipped. Both functions never raise:
email is the last channel of an announcement and must not fail the sweep.

The builders (:func:`event_message`, :func:`digest_message`) are pure, so the wording is
unit-testable without a database or a mailer.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from . import mailer

_logger = logging.getLogger(__name__)

__all__ = [
    "EmailMessage",
    "absolute_link",
    "digest_message",
    "email_digest",
    "email_event",
    "event_message",
    "owner_emails",
]


@dataclass(frozen=True)
class EmailMessage:
    """One email's content.

    Attributes:
        subject: The subject line.
        text: The plain-text body.
        html: The HTML body.
    """

    subject: str
    text: str
    html: str


def absolute_link(link: str, base_url: Optional[str] = None) -> str:
    """An app link (``/ade/…``) on the public apiome-ui address (``APIOME_UI_PUBLIC_URL``).

    Args:
        link: The relative link from a drift payload.
        base_url: The public address; defaults to the ``ui_public_url`` setting.

    Returns:
        The absolute URL.
    """
    if base_url is None:
        from .config import settings

        base_url = settings.ui_public_url
    return f"{str(base_url or '').rstrip('/')}{link}"


# ---------------------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------------------


def _version_line(payload: Mapping[str, Any]) -> str:
    """``1.0.0 → 2026-10-28T12:00Z`` for a drift payload."""
    versions = payload.get("versions") or {}
    before = (versions.get("from") or {}).get("label") or "the previous version"
    after = (versions.get("to") or {}).get("label") or "the new version"
    return f"{before} → {after}"


def _counts_line(counts: Mapping[str, Any]) -> str:
    """``1 breaking, 2 safe`` — the non-zero counts, worst first."""
    parts = [f"{int(counts.get(s) or 0)} {s}" for s in ("breaking", "dangerous", "safe") if counts.get(s)]
    return ", ".join(parts) or "no graded changes"


def event_message(payload: Mapping[str, Any], *, base_url: Optional[str] = None) -> EmailMessage:
    """The email for one ``catalog.drift.detected`` payload.

    Args:
        payload: From :func:`app.catalog_drift.drift_payload`.
        base_url: The public apiome-ui address; defaults to the setting.

    Returns:
        The subject, a text body and an HTML body: the summary, the versions, the counts, the top
        findings and a link to **What changed**.
    """
    name = (payload.get("artifact") or {}).get("name") or "A catalog item"
    severity = str(payload.get("severity") or "")
    link = absolute_link(str(payload.get("link") or ""), base_url)
    findings = list(payload.get("topFindings") or [])
    subject = f"[Apiome] {severity.capitalize()} drift in {name}"

    text_lines = [
        str(payload.get("summary") or ""),
        "",
        f"Versions: {_version_line(payload)}",
        f"Changes: {_counts_line(payload.get('counts') or {})}",
    ]
    if findings:
        text_lines += ["", "Top findings:"]
        text_lines += [_finding_line(f) for f in findings]
    text_lines += ["", f"See what changed: {link}"]

    items = "".join(
        f"<li><strong>{_e(f.get('severity'))}</strong> <code>{_e(f.get('key'))}</code>"
        f"{' — ' + _e(f.get('rationale')) if f.get('rationale') else ''}</li>"
        for f in findings
    )
    body = (
        f"<p>{_e(payload.get('summary'))}</p>"
        f"<p>Versions: {_e(_version_line(payload))}<br>Changes: {_e(_counts_line(payload.get('counts') or {}))}</p>"
        + (f"<p>Top findings:</p><ul>{items}</ul>" if items else "")
        + f'<p><a href="{_e(link)}">See what changed</a></p>'
    )
    return EmailMessage(subject=subject, text="\n".join(text_lines), html=body)


def _finding_line(finding: Mapping[str, Any]) -> str:
    """``- [breaking] Order.total: Removing a field breaks clients`` (no reason → no colon)."""
    line = f"- [{finding.get('severity')}] {finding.get('key')}"
    return f"{line}: {finding['rationale']}" if finding.get("rationale") else line


def digest_message(payloads: Sequence[Mapping[str, Any]], *, base_url: Optional[str] = None) -> EmailMessage:
    """The digest email listing several drift payloads.

    Args:
        payloads: :func:`app.catalog_drift.drift_payload` bodies, oldest first.
        base_url: The public apiome-ui address; defaults to the setting.

    Returns:
        The subject (with the count), and one line per drift with its link.
    """
    count = len(payloads)
    noun = "drift" if count == 1 else "drifts"
    subject = f"[Apiome] Daily drift digest: {count} catalog {noun}"
    text_lines = [f"{count} catalog {noun} since the last digest:", ""]
    rows = []
    for payload in payloads:
        link = absolute_link(str(payload.get("link") or ""), base_url)
        text_lines.append(f"- {payload.get('summary')} ({_version_line(payload)}) {link}")
        rows.append(
            f'<li><a href="{_e(link)}">{_e(payload.get("summary"))}</a> ({_e(_version_line(payload))})</li>'
        )
    body = f"<p>{count} catalog {noun} since the last digest:</p><ul>{''.join(rows)}</ul>"
    return EmailMessage(subject=subject, text="\n".join(text_lines), html=body)


def _e(value: Any) -> str:
    """HTML-escaped text (``None`` → empty)."""
    return html.escape("" if value is None else str(value))


# ---------------------------------------------------------------------------------------
# Recipients
# ---------------------------------------------------------------------------------------


def owner_emails(db: Any, tenant_id: str, item_id: str, *, exclude: Iterable[Optional[str]] = ()) -> List[str]:
    """The addresses of the item's confirmed owner team members (owner routing's recipients).

    Args:
        db: Database handle.
        tenant_id: The item's tenant.
        item_id: The catalog item.
        exclude: User ids not to email (the actor).

    Returns:
        Addresses of enabled, undeleted members, in owner routing's order; empty when the item has
        no confirmed owner.
    """
    from .owner_routing import owner_recipients

    owner = owner_recipients(db, tenant_id, "catalog_item", item_id, exclude=exclude)
    if owner is None or not owner.user_ids:
        return []
    rows = db.execute_query(
        """
        SELECT id::text AS id, email FROM apiome.users
        WHERE id = ANY(%s::uuid[]) AND deleted_at IS NULL AND enabled IS NOT FALSE
          AND email IS NOT NULL AND email <> ''
        """,
        (list(owner.user_ids),),
    )
    by_id = {str(row["id"]): str(row["email"]) for row in rows}
    return [by_id[user_id] for user_id in owner.user_ids if user_id in by_id]


# ---------------------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------------------


def email_event(
    db: Any,
    *,
    tenant_id: str,
    item_id: str,
    payload: Mapping[str, Any],
    actor_id: Optional[str] = None,
    send: Optional[Callable[..., bool]] = None,
) -> int:
    """Email one announced drift to the item's owner team. Never raises.

    The caller has already checked the tenant's opt-in.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        item_id: The catalog item.
        payload: The ``catalog.drift.detected`` payload.
        actor_id: Who the refresh acted as; not emailed.
        send: The sender (tests); defaults to :func:`app.mailer.send_email`.

    Returns:
        How many emails were accepted.
    """
    if send is None:
        if not mailer.is_configured():
            return 0
        send = mailer.send_email
    try:
        message = event_message(payload)
        return sum(
            1
            for address in owner_emails(db, tenant_id, item_id, exclude=[actor_id])
            if send(address, message.subject, message.text, message.html)
        )
    except Exception:  # noqa: BLE001 - email never fails the sweep
        _logger.warning("catalog drift: could not email drift for item %s", item_id, exc_info=True)
        return 0


def email_digest(
    db: Any,
    *,
    tenant_id: str,
    payloads: Sequence[Mapping[str, Any]],
    send: Optional[Callable[..., bool]] = None,
) -> int:
    """Email a tenant's digest: one email per recipient, listing their teams' items. Never raises.

    The caller has already checked the tenant's opt-in.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        payloads: One ``catalog.drift.detected``-shaped payload per waiting event, oldest first.
        send: The sender (tests); defaults to :func:`app.mailer.send_email`.

    Returns:
        How many emails were accepted.
    """
    if send is None:
        if not mailer.is_configured():
            return 0
        send = mailer.send_email
    try:
        by_item: Dict[str, List[str]] = {}
        per_recipient: Dict[str, List[Mapping[str, Any]]] = {}
        for payload in payloads:
            item_id = str((payload.get("artifact") or {}).get("id") or "")
            if item_id not in by_item:
                by_item[item_id] = owner_emails(db, tenant_id, item_id)
            for address in by_item[item_id]:
                per_recipient.setdefault(address, []).append(payload)
        sent = 0
        for address, mine in per_recipient.items():
            message = digest_message(mine)
            if send(address, message.subject, message.text, message.html):
                sent += 1
        return sent
    except Exception:  # noqa: BLE001 - email never fails the digest
        _logger.warning("catalog drift: could not email the digest for tenant %s", tenant_id, exc_info=True)
        return 0
