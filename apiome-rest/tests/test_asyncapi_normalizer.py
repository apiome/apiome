"""End-to-end tests for the AsyncAPI normalizer (MFI-8.2, #3760).

Exercises the acceptance criterion — *a multi-channel doc normalizes; round-trips;
fingerprint stable* — for both AsyncAPI families: a representative dereferenced v3
document (multiple channels, send + receive operations, payload/header/correlationId
messages, host+pathname servers, address parameters) and a v2 document (publish/
subscribe channel operations, ``oneOf`` messages, schema-typed parameters) map
cleanly into the canonical EVENT model, the output is deterministically ordered and
idempotent, its fingerprint is invariant to source declaration order yet flips on a
structural change, the model survives the JSONB round-trip, and error paths behave.

A final gated suite feeds the *real* dereferenced output of the MFI-8.1 parser
(``parse_asyncapi``) into the normalizer when the bundled Node tool is present, so
the contract between the two stages is verified against authentic payloads.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict

import pytest

from app.asyncapi_normalizer import AsyncApiNormalizer
from app.asyncapi_parser import ASYNCAPI_PARSER_TOOL_KEY, parse_asyncapi
from app.canonical_model import (
    ApiParadigm,
    CanonicalApi,
    MessageRole,
    OperationKind,
)
from app.fingerprint import canonical_fingerprint
from app.normalizer import get_normalizer
from app.toolchain_packaging import probe_tool

_FIXTURES = Path(__file__).parent / "fixtures" / "asyncapi"


# ===========================================================================
# Representative dereferenced documents (what the MFI-8.1 parser hands us)
# ===========================================================================


def _v3_doc() -> Dict[str, Any]:
    """A multi-channel, dereferenced AsyncAPI 3.0 document.

    Mirrors what ``parse_asyncapi`` produces: ``$ref``s inlined, so each operation's
    ``channel`` is the channel object itself and channel messages are inline.
    """
    signedup_channel = {
        "address": "user/{userId}/signedup",
        "parameters": {
            "userId": {"description": "the user", "location": "$message.header#/userId"}
        },
        "messages": {
            "UserSignedUp": {
                "name": "UserSignedUp",
                "contentType": "application/json",
                "headers": {
                    "type": "object",
                    "properties": {"x-trace": {"type": "string"}},
                    "required": ["x-trace"],
                },
                "correlationId": {"location": "$message.header#/x-trace"},
                "payload": {
                    "type": "object",
                    "properties": {
                        "userId": {"type": "string"},
                        "email": {"type": "string", "format": "email"},
                    },
                },
            }
        },
        "bindings": {"kafka": {"partitions": 3}},
    }
    deleted_channel = {
        "address": "user/{userId}/deleted",
        "parameters": {"userId": {}},
        "messages": {
            "UserDeleted": {
                "name": "UserDeleted",
                "payload": {
                    "type": "object",
                    "properties": {"userId": {"type": "string"}},
                },
            }
        },
    }
    return {
        "asyncapi": "3.0.0",
        "id": "urn:com:example:user-service",
        "info": {
            "title": "User Service",
            "version": "1.2.3",
            "description": "A sample event API.",
        },
        "defaultContentType": "application/json",
        "servers": {
            "production": {
                "host": "broker.example.com",
                "pathname": "/events",
                "protocol": "kafka",
                "protocolVersion": "3.5",
                "description": "prod",
                "variables": {
                    "env": {"default": "prod", "enum": ["prod", "staging"]}
                },
            }
        },
        "channels": {
            "userSignedUp": signedup_channel,
            "userDeleted": deleted_channel,
        },
        "operations": {
            "onUserSignedUp": {
                "action": "receive",
                "channel": copy.deepcopy(signedup_channel),
                "reply": {"address": "user/ack"},
                "tags": [{"name": "users"}],
            },
            "sendUserDeleted": {
                "action": "send",
                "channel": copy.deepcopy(deleted_channel),
            },
        },
    }


def _v2_doc() -> Dict[str, Any]:
    """A dereferenced AsyncAPI 2.6 document with publish/subscribe + a ``oneOf`` message."""
    return {
        "asyncapi": "2.6.0",
        "id": "urn:com:example:streetlights",
        "info": {"title": "Streetlights API", "version": "1.0.0"},
        "defaultContentType": "application/json",
        "servers": {
            "production": {"url": "mqtt://broker.example.com", "protocol": "mqtt"}
        },
        "channels": {
            "light/{lampId}/measured": {
                "description": "Telemetry for a single lamp.",
                "parameters": {
                    "lampId": {
                        "description": "lamp id",
                        "schema": {"type": "string"},
                    }
                },
                "publish": {
                    "operationId": "onLightMeasured",
                    "message": {
                        "name": "LightMeasured",
                        "payload": {
                            "type": "object",
                            "properties": {"lumens": {"type": "integer", "minimum": 0}},
                        },
                    },
                },
                "subscribe": {
                    "message": {
                        "oneOf": [
                            {"name": "DimLight", "payload": {"type": "object"}},
                            {"name": "TurnOff", "payload": {"type": "object"}},
                        ]
                    },
                },
                "bindings": {"mqtt": {"qos": 1}},
            }
        },
    }


# ===========================================================================
# AsyncAPI 3 — multi-channel mapping
# ===========================================================================


def test_v3_multichannel_normalizes() -> None:
    api = AsyncApiNormalizer().normalize(_v3_doc())

    assert api.paradigm is ApiParadigm.EVENT
    assert api.format == "asyncapi-3"
    assert api.protocol == "kafka"
    assert api.title == "User Service"
    assert api.version == "1.2.3"
    assert api.identity.id == "urn:com:example:user-service"

    # Server: v3 host + pathname recombine into the URL; the split is kept for fidelity.
    server = api.servers[0]
    assert server.url == "broker.example.com/events"
    assert server.protocol == "kafka"
    assert server.extras["pathname"] == "/events"
    assert server.extras["protocolVersion"] == "3.5"
    assert server.variables[0].name == "env"
    assert server.variables[0].enum == ["prod", "staging"]

    # Two channels keyed by their addresses, each with its address parameter.
    assert {c.key for c in api.channels} == {
        "user/{userId}/signedup",
        "user/{userId}/deleted",
    }
    signed = next(c for c in api.channels if c.key == "user/{userId}/signedup")
    assert signed.bindings["kafka"] == {"partitions": 3}
    assert signed.parameters[0].key == "user/{userId}/signedup#param.userId"
    assert signed.parameters[0].name == "userId"

    ops = {op.key: op for op in api.operations()}
    assert set(ops) == {"onUserSignedUp", "sendUserDeleted"}

    receive = ops["onUserSignedUp"]
    assert receive.kind is OperationKind.SUBSCRIBE
    assert receive.channel_ref == "user/{userId}/signedup"
    assert receive.extras["action"] == "receive"
    assert receive.extras["reply"] == {"address": "user/ack"}
    assert receive.tags == ["users"]

    send = ops["sendUserDeleted"]
    assert send.kind is OperationKind.PUBLISH
    assert send.channel_ref == "user/{userId}/deleted"

    # Message: EVENT role, inline payload schema, headers as fields, correlationId in extras.
    msg = receive.messages[0]
    assert msg.role is MessageRole.EVENT
    assert msg.key == "onUserSignedUp#event.UserSignedUp"
    assert msg.payload_schema["properties"]["email"] == {
        "type": "string",
        "format": "email",
    }
    assert msg.content_types == ["application/json"]
    assert msg.extras["correlationId"] == {"location": "$message.header#/x-trace"}
    assert [h.name for h in msg.headers] == ["x-trace"]
    assert msg.headers[0].type.nullable is False  # required header


def test_v3_operation_messages_subset_resolved() -> None:
    """An operation that lists a subset of channel messages uses just those."""
    doc = _v3_doc()
    # The send op explicitly lists the channel's single message by ref.
    doc["operations"]["sendUserDeleted"]["messages"] = [
        {"$ref": "#/channels/userDeleted/messages/UserDeleted"}
    ]
    api = AsyncApiNormalizer().normalize(doc)
    send = next(op for op in api.operations() if op.key == "sendUserDeleted")
    assert [m.name for m in send.messages] == ["UserDeleted"]
    assert send.messages[0].key == "sendUserDeleted#event.UserDeleted"


def test_v3_channel_ref_resolves_when_ref_not_inlined() -> None:
    """A still-present ``channel`` ``$ref`` (un-dereferenced) still resolves."""
    doc = _v3_doc()
    doc["operations"]["onUserSignedUp"]["channel"] = {"$ref": "#/channels/userSignedUp"}
    api = AsyncApiNormalizer().normalize(doc)
    receive = next(op for op in api.operations() if op.key == "onUserSignedUp")
    assert receive.channel_ref == "user/{userId}/signedup"


# ===========================================================================
# AsyncAPI 2 — publish/subscribe mapping
# ===========================================================================


def test_v2_normalizes() -> None:
    api = AsyncApiNormalizer().normalize(_v2_doc())

    assert api.paradigm is ApiParadigm.EVENT
    assert api.format == "asyncapi-2"
    assert api.protocol == "mqtt"
    assert api.servers[0].url == "mqtt://broker.example.com"

    channel = api.channels[0]
    assert channel.key == "light/{lampId}/measured"
    assert channel.address == "light/{lampId}/measured"
    assert channel.bindings["mqtt"] == {"qos": 1}
    # v2 parameters carry a schema → typed canonical field.
    assert channel.parameters[0].name == "lampId"
    assert channel.parameters[0].type.name == "string"

    ops = {op.key: op for op in api.operations()}
    # publish keeps its operationId as key; subscribe (no id) falls back to action+address.
    assert "onLightMeasured" in ops
    assert "subscribe light/{lampId}/measured" in ops

    publish = ops["onLightMeasured"]
    assert publish.kind is OperationKind.PUBLISH
    assert publish.channel_ref == "light/{lampId}/measured"
    assert publish.extras["action"] == "publish"
    assert publish.messages[0].name == "LightMeasured"
    assert publish.messages[0].payload_schema["properties"]["lumens"]["minimum"] == 0

    # subscribe used a oneOf — both variants become messages.
    subscribe = ops["subscribe light/{lampId}/measured"]
    assert subscribe.kind is OperationKind.SUBSCRIBE
    assert {m.name for m in subscribe.messages} == {"DimLight", "TurnOff"}


# ===========================================================================
# Determinism, ordering, and fingerprint stability (round-trips)
# ===========================================================================


def test_normalization_is_idempotent() -> None:
    normalizer = AsyncApiNormalizer()
    first = normalizer.normalize(_v3_doc())
    second = normalizer.normalize(_v3_doc())
    assert first.model_dump() == second.model_dump()


def test_fingerprint_invariant_to_source_order() -> None:
    """Reordering servers/channels/operations does not change the fingerprint."""
    base = _v3_doc()
    reordered = _v3_doc()
    # Reverse the insertion order of the identity-keyed maps.
    reordered["channels"] = dict(reversed(list(reordered["channels"].items())))
    reordered["operations"] = dict(reversed(list(reordered["operations"].items())))

    fp_base = canonical_fingerprint(AsyncApiNormalizer().normalize(base))
    fp_reordered = canonical_fingerprint(AsyncApiNormalizer().normalize(reordered))
    assert fp_base == fp_reordered


def test_fingerprint_flips_on_structural_change() -> None:
    """A payload change (here, a new field) flips the fingerprint."""
    base = _v3_doc()
    changed = _v3_doc()
    changed["channels"]["userSignedUp"]["messages"]["UserSignedUp"]["payload"][
        "properties"
    ]["nickname"] = {"type": "string"}

    fp_base = canonical_fingerprint(AsyncApiNormalizer().normalize(base))
    fp_changed = canonical_fingerprint(AsyncApiNormalizer().normalize(changed))
    assert fp_base != fp_changed


def test_fingerprint_ignores_description_only_edit() -> None:
    """A description-only edit does not flip the fingerprint."""
    base = _v3_doc()
    documented = _v3_doc()
    documented["operations"]["onUserSignedUp"]["description"] = "now documented"

    fp_base = canonical_fingerprint(AsyncApiNormalizer().normalize(base))
    fp_documented = canonical_fingerprint(AsyncApiNormalizer().normalize(documented))
    assert fp_base == fp_documented


def test_jsonb_round_trip_is_lossless() -> None:
    api = AsyncApiNormalizer().normalize(_v3_doc())
    reloaded = CanonicalApi.model_validate(json.loads(json.dumps(api.model_dump())))
    assert reloaded == api


# ===========================================================================
# Registry + error paths
# ===========================================================================


@pytest.mark.parametrize("format_key", ["asyncapi-2", "asyncapi-3"])
def test_registered_under_both_format_keys(format_key: str) -> None:
    # Importing the module (done at the top) self-registers both keys.
    cls = get_normalizer(format_key)
    assert cls is not None
    assert issubclass(cls, AsyncApiNormalizer)


def test_rejects_non_mapping() -> None:
    with pytest.raises(ValueError):
        AsyncApiNormalizer().normalize("not-a-dict")


def test_rejects_non_asyncapi_document() -> None:
    with pytest.raises(ValueError):
        AsyncApiNormalizer().normalize({"openapi": "3.1.0", "info": {}})


def test_include_raw_toggles_native_ast() -> None:
    doc = _v3_doc()
    assert AsyncApiNormalizer().normalize(doc, include_raw=True).raw == doc
    assert AsyncApiNormalizer().normalize(doc, include_raw=False).raw is None


def test_empty_document_normalizes_to_empty_model() -> None:
    """A minimal valid-shaped doc with no channels/operations still normalizes."""
    api = AsyncApiNormalizer().normalize(
        {"asyncapi": "3.0.0", "info": {"title": "Empty", "version": "0.0.1"}}
    )
    assert api.channels == []
    assert api.services == []
    assert api.servers == []


# ===========================================================================
# End-to-end: the real MFI-8.1 parser feeding the normalizer (gated)
# ===========================================================================

_PARSER_AVAILABLE = bool(getattr(probe_tool(ASYNCAPI_PARSER_TOOL_KEY), "available", False))


@pytest.mark.skipif(
    not _PARSER_AVAILABLE,
    reason="asyncapi-parser tool is not resolvable in this environment "
    "(bundled only in the image / via APIOME_ASYNCAPI_PARSER_BIN)",
)
class TestRealParserToNormalizer:
    """Normalize the authentic dereferenced output of the real parser."""

    @pytest.mark.parametrize(
        "fixture, format_key, title",
        [
            ("streetlights_2.6.yaml", "asyncapi-2", "Streetlights API"),
            ("user_events_3.0.yaml", "asyncapi-3", "User Service"),
            ("account_3.1.yaml", "asyncapi-3", "Account Service"),
        ],
    )
    async def test_fixture_parses_and_normalizes(
        self, fixture: str, format_key: str, title: str
    ) -> None:
        raw = (_FIXTURES / fixture).read_text()
        parsed = await parse_asyncapi(raw, source_label=fixture)
        assert parsed.ok is True

        api = AsyncApiNormalizer().normalize(parsed.document)
        assert api.paradigm is ApiParadigm.EVENT
        assert api.format == format_key
        assert api.title == title
        # At least one channel and one operation, each operation bound to a channel.
        assert api.channels
        operations = api.operations()
        assert operations
        channel_keys = {c.key for c in api.channels}
        for op in operations:
            assert op.channel_ref in channel_keys
            assert op.messages and op.messages[0].role is MessageRole.EVENT

        # Fingerprint is stable across a re-normalize of the same parsed document.
        assert canonical_fingerprint(api) == canonical_fingerprint(
            AsyncApiNormalizer().normalize(parsed.document)
        )
