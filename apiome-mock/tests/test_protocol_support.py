"""Protocol support report tests (#5755, XPC-5.4).

``mock-action`` branches on this report, so its shape is a contract: every protocol id present,
``served`` always a boolean, and an unserved protocol always carrying a reason.
"""

from __future__ import annotations

from apiome_mock.protocol_support import PROTOCOL_IDS, ProtocolSupport, portable_protocols, protocols_as_dict


def test_every_protocol_is_reported() -> None:
    assert tuple(protocols_as_dict(portable_protocols())) == PROTOCOL_IDS


def test_the_portable_runtime_serves_http_at_the_mount() -> None:
    assert portable_protocols()["http"] == ProtocolSupport(served=True, path="")


def test_every_unserved_protocol_says_why() -> None:
    for protocol, entry in portable_protocols().items():
        if not entry.served:
            assert entry.reason, protocol
            assert "HTTP only" in entry.reason


def test_entries_render_only_the_fields_that_apply() -> None:
    assert ProtocolSupport(served=True, path="/graphql").as_dict() == {"served": True, "path": "/graphql"}
    assert ProtocolSupport(served=True, port=8776).as_dict() == {"served": True, "port": 8776}
    assert ProtocolSupport(served=False, reason="no").as_dict() == {"served": False, "reason": "no"}
