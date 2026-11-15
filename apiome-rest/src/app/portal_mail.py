"""The reader sign-in email — PCX-1.1 (#5889).

PCX-1.1 mails a magic link through "the PCX-3.1 email channel". That channel (#5903) is not merged
yet, so this module is the seam the issue asks for: :class:`ReaderMailer` is the adapter interface,
and :class:`SendGridReaderMailer` implements it with today's direct SendGrid sender
(:func:`app.mailer.send_email`). When PCX-3.1 lands it supplies another implementation and
:func:`default_reader_mailer` returns that instead; the store never changes.

The link is never logged: it is a bearer credential until it is exchanged.
"""

from __future__ import annotations

import html
import logging
from typing import Optional, Protocol
from urllib.parse import urlencode

from . import mailer
from .portal_auth import MAGIC_LINK_TTL_MINUTES

_logger = logging.getLogger(__name__)

__all__ = [
    "ReaderMailer",
    "SendGridReaderMailer",
    "default_reader_mailer",
    "magic_link_url",
    "render_magic_link_email",
]

#: The Browse route that exchanges a token for a session (``apiome-browse``
#: ``src/app/portal/auth/exchange/route.ts``).
EXCHANGE_PATH = "/portal/auth/exchange"


class ReaderMailer(Protocol):
    """Sends a reader their sign-in link."""

    def send_magic_link(self, *, to: str, tenant_name: str, link: str) -> bool:
        """Send one sign-in link.

        Args:
            to: The reader's address.
            tenant_name: The portal the link signs into, for the subject and body.
            link: The magic link.

        Returns:
            True once the message was handed to the mail provider.
        """
        ...


def magic_link_url(browse_url: str, tenant_slug: str, token: str) -> str:
    """Build the link a reader clicks.

    Args:
        browse_url: The public Browse root (``APIOME_PUBLIC_BROWSE_URL``), without a trailing slash.
            Empty yields a site-relative link, which only makes sense in tests.
        tenant_slug: The tenant the token belongs to.
        token: The magic-link token.

    Returns:
        ``<browse_url>/portal/auth/exchange?tenant=<slug>&token=<token>``.
    """
    query = urlencode({"tenant": tenant_slug, "token": token})
    return f"{browse_url.rstrip('/')}{EXCHANGE_PATH}?{query}"


def render_magic_link_email(tenant_name: str, link: str) -> tuple[str, str, str]:
    """Render the sign-in email.

    Args:
        tenant_name: The portal's display name.
        link: The magic link.

    Returns:
        ``(subject, text, html)``.
    """
    subject = f"Sign in to {tenant_name} API docs"
    text = (
        f"Use this link to sign in to {tenant_name} in Apiome Browse:\n\n{link}\n\n"
        f"The link works once and expires in {MAGIC_LINK_TTL_MINUTES} minutes. "
        "If you did not ask to sign in, ignore this email."
    )
    safe_name = html.escape(tenant_name)
    safe_link = html.escape(link, quote=True)
    body = (
        f"<p>Use this link to sign in to <strong>{safe_name}</strong> in Apiome Browse:</p>"
        f'<p><a href="{safe_link}">Sign in</a></p>'
        f"<p>The link works once and expires in {MAGIC_LINK_TTL_MINUTES} minutes. "
        "If you did not ask to sign in, ignore this email.</p>"
    )
    return subject, text, body


class SendGridReaderMailer:
    """The interim :class:`ReaderMailer`: a direct SendGrid send through :mod:`app.mailer`."""

    def send_magic_link(self, *, to: str, tenant_name: str, link: str) -> bool:
        """Send one sign-in link. Never raises; a no-op when mail is not configured.

        Args:
            to: The reader's address.
            tenant_name: The portal's display name.
            link: The magic link.

        Returns:
            True once SendGrid accepted the message.
        """
        if not mailer.is_configured():
            _logger.warning("portal mail: email is not configured; no sign-in link was sent")
            return False
        subject, text, body = render_magic_link_email(tenant_name, link)
        return mailer.send_email(to, subject, text, body)


_default: Optional[ReaderMailer] = None


def default_reader_mailer() -> ReaderMailer:
    """The mailer the routes use (swap point for PCX-3.1 and for tests)."""
    global _default
    if _default is None:
        _default = SendGridReaderMailer()
    return _default
