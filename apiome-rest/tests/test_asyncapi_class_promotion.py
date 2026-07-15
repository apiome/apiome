"""Tests for AsyncAPI message → designer Class promotion (#2772)."""

from __future__ import annotations

from typing import Any, Dict, List

from app.asyncapi_class_promotion import promote_asyncapi_message_classes
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Service,
    TypeRef,
)


class _FakeDb:
    def __init__(self) -> None:
        self.classes: List[Dict[str, Any]] = []

    def create_class(
        self, version_id, name, schema, description=None, enabled=True
    ):
        row = {
            "id": f"class-{len(self.classes) + 1}",
            "version_id": version_id,
            "name": name,
            "schema": schema,
            "description": description,
        }
        self.classes.append(row)
        return row


def _model() -> CanonicalApi:
    return CanonicalApi(
        paradigm=ApiParadigm.EVENT,
        format="asyncapi-3",
        identity=ApiIdentity(name="Events"),
        services=[
            Service(
                key="default",
                name="default",
                operations=[
                    Operation(
                        key="onSignup",
                        name="onSignup",
                        kind=OperationKind.SUBSCRIBE,
                        extras={"action": "receive"},
                        messages=[
                            Message(
                                key="onSignup#event",
                                role=MessageRole.EVENT,
                                name="UserSignedUp",
                                payload_schema={
                                    "type": "object",
                                    "properties": {"id": {"type": "string"}},
                                },
                                headers=[
                                    CanonicalField(
                                        key="onSignup#event.corr",
                                        name="correlationId",
                                        type=TypeRef(name="string", nullable=False),
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
    )


def test_promotes_payload_and_headers_into_classes() -> None:
    fake = _FakeDb()
    model = promote_asyncapi_message_classes(fake, "ver-1", _model())
    msg = model.operations()[0].messages[0]

    assert msg.extras["payload_class_id"] == "class-1"
    assert msg.extras["headers_class_id"] == "class-2"
    assert fake.classes[0]["name"] == "UserSignedUp"
    assert fake.classes[0]["schema"]["properties"]["id"]["type"] == "string"
    assert fake.classes[1]["name"] == "UserSignedUpHeaders"
    assert "correlationId" in fake.classes[1]["schema"]["properties"]


def test_class_name_collision_gets_suffix() -> None:
    fake = _FakeDb()
    model = CanonicalApi(
        paradigm=ApiParadigm.EVENT,
        format="asyncapi-2",
        identity=ApiIdentity(name="E"),
        services=[
            Service(
                key="default",
                name="default",
                operations=[
                    Operation(
                        key="a",
                        name="a",
                        kind=OperationKind.PUBLISH,
                        messages=[
                            Message(
                                key="a#1",
                                role=MessageRole.EVENT,
                                name="Dup",
                                payload_schema={"type": "object"},
                            ),
                            Message(
                                key="a#2",
                                role=MessageRole.EVENT,
                                name="Dup",
                                payload_schema={"type": "object"},
                            ),
                        ],
                    )
                ],
            )
        ],
    )
    promote_asyncapi_message_classes(fake, "ver-1", model)
    assert [c["name"] for c in fake.classes] == ["Dup", "Dup_2"]
