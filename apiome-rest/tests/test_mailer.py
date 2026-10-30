"""The SendGrid mailer (#6384).

Pins: no key or no sender means no mailer (and no request); ``EMAIL_FROM`` may carry a display
name; a send posts SendGrid's v3 body with the bearer key; a refusal or a network error returns
``False`` and never raises; nothing logged carries the key.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from app import mailer

_CONFIG = mailer.MailerConfig(api_key="SG.secret", from_email="no-reply@apiome.example", from_name="Apiome")


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    ("key", "sender"),
    [(None, "a@b.example"), ("", "a@b.example"), ("SG.x", None), ("SG.x", "not an address"), ("  ", "  ")],
)
def test_missing_key_or_sender_means_no_mailer(key, sender):
    assert mailer.mailer_config(key, sender) is None


def test_the_sender_may_carry_a_display_name():
    assert mailer.mailer_config(" SG.x ", "Apiome <no-reply@apiome.example>") == mailer.MailerConfig(
        api_key="SG.x", from_email="no-reply@apiome.example", from_name="Apiome"
    )
    assert mailer.mailer_config("SG.x", "ops@apiome.example").from_name is None


def test_the_settings_configure_the_default(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "sendgrid_api_key", None)
    monkeypatch.setattr(settings, "email_from", "a@b.example")
    assert mailer.is_configured() is False
    monkeypatch.setattr(settings, "sendgrid_api_key", "SG.x")
    assert mailer.is_configured() is True


def test_unconfigured_sends_nothing(monkeypatch):
    monkeypatch.setattr(mailer, "mailer_config", lambda *a, **k: None)
    seen = []
    assert mailer.send_email("a@b.example", "s", "t", client=_client(lambda r: seen.append(r))) is False
    assert seen == []


def test_an_empty_recipient_sends_nothing():
    seen = []
    assert mailer.send_email(" ", "s", "t", config=_CONFIG, client=_client(lambda r: seen.append(r))) is False
    assert seen == []


def test_a_send_posts_the_sendgrid_body():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202)

    assert mailer.send_email("dev@team.example", "Subj", "Text", "<p>Html</p>", config=_CONFIG, client=_client(handler))
    [request] = seen
    assert str(request.url) == mailer.SENDGRID_SEND_URL
    assert request.headers["authorization"] == "Bearer SG.secret"
    assert json.loads(request.content) == {
        "personalizations": [{"to": [{"email": "dev@team.example"}]}],
        "from": {"email": "no-reply@apiome.example", "name": "Apiome"},
        "subject": "Subj",
        "content": [{"type": "text/plain", "value": "Text"}, {"type": "text/html", "value": "<p>Html</p>"}],
    }


def test_a_refusal_returns_false_and_logs_no_secret(caplog):
    caplog.set_level(logging.WARNING)
    refusing = _client(lambda r: httpx.Response(401))
    assert mailer.send_email("a@b.example", "s", "t", config=_CONFIG, client=refusing) is False
    assert "HTTP 401" in caplog.text and "SG.secret" not in caplog.text


def test_a_network_error_is_swallowed(caplog):
    def handler(request):
        raise httpx.ConnectError("down")

    assert mailer.send_email("a@b.example", "s", "t", config=_CONFIG, client=_client(handler)) is False
    assert "ConnectError" in caplog.text
