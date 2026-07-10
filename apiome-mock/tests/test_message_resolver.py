"""Tests for canonical message resolver (SIM-4.4)."""

from __future__ import annotations

from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi, Message, MessageRole

from apiome_mock.message_resolver import encode_message_text, resolve_message_body


def test_resolve_inline_event_payload() -> None:
    api = CanonicalApi(
        paradigm=ApiParadigm.EVENT,
        format="asyncapi-3",
        identity=ApiIdentity(name="events"),
        services=[],
        channels=[],
        types=[],
    )
    message = Message(
        key="onUserSignedUp#event.UserSignedUp",
        role=MessageRole.EVENT,
        payload_schema={
            "type": "object",
            "required": ["userId"],
            "properties": {"userId": {"type": "string"}},
        },
        content_types=["application/json"],
    )
    resolved = resolve_message_body(api, message, seed=7)
    assert resolved.validation_error is None
    assert isinstance(resolved.body, dict)
    assert "userId" in resolved.body
    text = encode_message_text(resolved)
    assert text.startswith("{")
