"""Outgoing email for REST notification families — SendGrid (#6384).

The same sender apiome-ui's auth layer uses: ``SENDGRID_API_KEY`` and ``EMAIL_FROM`` (for example
``Apiome <no-reply@apiome.example>``). With either unset the mailer is **a no-op**: nothing is sent
and nothing fails, so a producer can always call :func:`send_email` and let the configuration
decide.

:func:`send_email` never raises and never logs a message body or the API key — a notification
email may carry links into the app, and the producer's own work (a sweep, a digest) must not fail
because mail could not be sent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Optional

import httpx

_logger = logging.getLogger(__name__)

__all__ = ["SENDGRID_SEND_URL", "MailerConfig", "is_configured", "mailer_config", "send_email"]

#: SendGrid's v3 send endpoint.
SENDGRID_SEND_URL = "https://api.sendgrid.com/v3/mail/send"
#: Seconds one send may take before it is given up.
SEND_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class MailerConfig:
    """A usable mailer configuration.

    Attributes:
        api_key: The SendGrid API key.
        from_email: The sender's address.
        from_name: The sender's display name, or ``None``.
    """

    api_key: str
    from_email: str
    from_name: Optional[str] = None


def mailer_config(api_key: Optional[str] = None, email_from: Optional[str] = None) -> Optional[MailerConfig]:
    """The mailer configuration, or ``None`` when email is not configured.

    Args:
        api_key: The SendGrid key; defaults to the ``SENDGRID_API_KEY`` setting.
        email_from: The sender (``Name <address>`` or a bare address); defaults to ``EMAIL_FROM``.

    Returns:
        A :class:`MailerConfig`, or ``None`` when the key or a valid sender address is missing.
    """
    if api_key is None and email_from is None:
        from .config import settings

        api_key, email_from = settings.sendgrid_api_key, settings.email_from
    key = (api_key or "").strip()
    name, address = parseaddr((email_from or "").strip())
    if not key or "@" not in address:
        return None
    return MailerConfig(api_key=key, from_email=address, from_name=name or None)


def is_configured() -> bool:
    """Whether :func:`send_email` would try to send."""
    return mailer_config() is not None


def send_email(
    to: str,
    subject: str,
    text: str,
    html: Optional[str] = None,
    *,
    config: Optional[MailerConfig] = None,
    client: Optional[httpx.Client] = None,
) -> bool:
    """Send one email. Never raises.

    Args:
        to: The recipient's address.
        subject: The subject line.
        text: The plain-text body.
        html: An HTML body, sent beside the text one when given.
        config: The configuration to use; defaults to :func:`mailer_config`.
        client: An HTTP client (tests pass a mock transport); a short-lived one by default.

    Returns:
        ``True`` once SendGrid accepted the message; ``False`` when email is not configured, the
        address is empty, or the send failed.
    """
    config = config or mailer_config()
    recipient = (to or "").strip()
    if config is None or "@" not in recipient:
        return False
    sender = {"email": config.from_email, **({"name": config.from_name} if config.from_name else {})}
    content = [{"type": "text/plain", "value": text}]
    if html:
        content.append({"type": "text/html", "value": html})
    body = {
        "personalizations": [{"to": [{"email": recipient}]}],
        "from": sender,
        "subject": subject,
        "content": content,
    }
    headers = {"Authorization": f"Bearer {config.api_key}"}
    try:
        if client is not None:
            response = client.post(SENDGRID_SEND_URL, json=body, headers=headers)
        else:
            with httpx.Client(timeout=SEND_TIMEOUT_SECONDS) as owned:
                response = owned.post(SENDGRID_SEND_URL, json=body, headers=headers)
    except Exception as error:  # noqa: BLE001 - mail never fails the producer
        _logger.warning("mailer: SendGrid send failed (%s)", type(error).__name__)
        return False
    if response.status_code >= 300:
        _logger.warning("mailer: SendGrid refused the message (HTTP %s)", response.status_code)
        return False
    return True
