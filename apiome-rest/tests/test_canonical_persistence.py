"""Lossless dump/load for the MFI-2.2 canonical persistence codec (#2772).

SQL against a live Postgres is exercised indirectly through the import pipeline;
these unit tests lock the pure tree codec — dump → load must equal the original
model for the event (AsyncAPI) sample that REPO-3.3 cares about, plus a message
that uses ``required`` / ``payload_schema`` (columns that need extras mapping).
"""

from __future__ import annotations

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Server,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.canonical_persistence import dump_canonical_tree, load_canonical_tree


def _event_sample() -> CanonicalApi:
    """AsyncAPI-shaped model with bindings, channel params, and an event message."""
    signup = Type(
        key="UserSignedUp",
        name="UserSignedUp",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(
                key="UserSignedUp.userId",
                name="userId",
                type=TypeRef(name="string", nullable=False),
            )
        ],
    )
    channel = Channel(
        key="user/{userId}/signedup",
        address="user/{userId}/signedup",
        protocol="kafka",
        parameters=[
            CanonicalField(
                key="user/{userId}/signedup#param.userId",
                name="userId",
                type=TypeRef(name="string", nullable=False),
            )
        ],
        bindings={"kafka": {"partitions": 3, "bindingVersion": "0.4.0"}},
        extras={"status": "ok"},
    )
    publish = Operation(
        key="onUserSignedUp",
        name="onUserSignedUp",
        kind=OperationKind.PUBLISH,
        channel_ref="user/{userId}/signedup",
        extras={"action": "send"},
        messages=[
            Message(
                key="onUserSignedUp#event",
                role=MessageRole.EVENT,
                name="UserSignedUp",
                content_types=["application/json"],
                payload=TypeRef(name="UserSignedUp", nullable=False),
                payload_schema={
                    "type": "object",
                    "properties": {"userId": {"type": "string"}},
                },
                required=True,
                extras={"correlationId": "userId"},
            )
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.EVENT,
        format="asyncapi-3",
        protocol="kafka",
        identity=ApiIdentity(name="Accounts Service", id="urn:example:accounts"),
        version="1.2.3",
        title="Accounts Service",
        servers=[Server(url="kafka://broker.example.com", protocol="kafka")],
        services=[Service(key="accounts", name="accounts", operations=[publish])],
        channels=[channel],
        types=[signup],
        raw={"asyncapi": "3.0.0"},
    )


def test_event_tree_round_trips_losslessly() -> None:
    original = _event_sample()
    reloaded = load_canonical_tree(dump_canonical_tree(original))
    assert reloaded == original


def test_bindings_and_action_survive_codec() -> None:
    tree = dump_canonical_tree(_event_sample())
    assert tree["channels"][0]["bindings"]["kafka"]["partitions"] == 3
    assert tree["services"][0]["operations"][0]["extras"]["action"] == "send"
    msg = tree["services"][0]["operations"][0]["messages"][0]
    assert msg["extras"]["_canonical_required"] is True
    assert msg["payload_schema"]["type"] == "object"

    reloaded = load_canonical_tree(tree)
    assert reloaded.channels[0].bindings == {
        "kafka": {"partitions": 3, "bindingVersion": "0.4.0"}
    }
    assert reloaded.operations()[0].extras["action"] == "send"
    assert reloaded.operations()[0].messages[0].required is True


def test_parse_error_channel_extras_round_trip() -> None:
    api = CanonicalApi(
        paradigm=ApiParadigm.EVENT,
        format="asyncapi-2",
        identity=ApiIdentity(name="Partial"),
        channels=[
            Channel(
                key="bad/channel",
                address="bad/channel",
                extras={"status": "parse_error", "parse_error": "missing message"},
            ),
            Channel(
                key="good/channel",
                address="good/channel",
                bindings={"mqtt": {"qos": 1}},
            ),
        ],
    )
    reloaded = load_canonical_tree(dump_canonical_tree(api))
    assert reloaded.channels[0].extras["status"] == "parse_error"
    assert reloaded.channels[1].bindings["mqtt"]["qos"] == 1
