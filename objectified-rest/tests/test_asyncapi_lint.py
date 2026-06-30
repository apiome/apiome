"""Tests for the AsyncAPI lint pack (MFI-8.3, #3761).

The acceptance criteria are: **lints v2 + v3**, and **findings merge into the score**. These
tests pin three layers:

* the **native rule pack** (:class:`app.asyncapi_lint.AsyncApiRulePack`) — each rule fires on
  a defective canonical model and a clean, fully documented model produces no ``asyncapi.*``
  findings — registered under both ``asyncapi-2`` and ``asyncapi-3``;
* the **Spectral mapping** (:func:`app.asyncapi_lint.spectral_findings`) — ``spectral:asyncapi``
  diagnostics (the ``@asyncapi/parser`` output) become namespaced, severity-folded findings;
* the **merge** — :func:`app.asyncapi_lint.lint_asyncapi_result` rolls Spectral + native +
  common into one deterministic score, and :func:`app.asyncapi_lint.lint_asyncapi` does it
  end-to-end from raw source for both AsyncAPI families (seam-tested with a fake runner that
  replays the parser contract, plus a gated end-to-end suite over the real bundled parser).

Everything here is pure (no DB/network) except the gated real-parser class, mirroring the
module under test.
"""

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Sequence

import pytest

from app.asyncapi_lint import (
    SPECTRAL_RULE_PREFIX,
    AsyncApiRulePack,
    lint_asyncapi,
    lint_asyncapi_result,
    spectral_findings,
)
from app.asyncapi_parser import (
    ASYNCAPI_PARSER_TOOL_KEY,
    AsyncApiDiagnostic,
    AsyncApiParseError,
)
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Server,
    Service,
    TypeRef,
)
from app.lint_engine import available_lint_formats, get_rule_pack, lint_canonical_model
from app.toolchain_packaging import probe_tool

_FIXTURES = Path(__file__).parent / "fixtures" / "asyncapi"


# ===========================================================================
# Canonical-model fixtures (pure)
# ===========================================================================


def _message(
    key: str,
    *,
    name: Optional[str],
    payload: bool,
    description: str = "An event.",
) -> Message:
    """A canonical event message, optionally with a payload and a name."""
    return Message(
        key=key,
        role=MessageRole.EVENT,
        name=name,
        payload=TypeRef(name="UserSignedUp") if payload else None,
        description=description,
    )


def _event_api(
    *,
    message: Message,
    server: Server,
    api_description: str = "A sample event API.",
) -> CanonicalApi:
    """An AsyncAPI canonical artifact with a single channel/operation/message + one server."""
    operation = Operation(
        key="publishSignup",
        name="publishSignup",
        kind=OperationKind.PUBLISH,
        description="Publishes a signup event.",
        channel_ref="user/signedup",
        messages=[message],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.EVENT,
        format="asyncapi-3",
        protocol="kafka",
        identity=ApiIdentity(name="Signups"),
        description=api_description,
        servers=[server],
        services=[
            Service(
                key="signups",
                name="signups",
                description="Signup events.",
                operations=[operation],
            )
        ],
    )


def _clean_event_api() -> CanonicalApi:
    """A fully documented, well-formed AsyncAPI artifact — no ``asyncapi.*`` findings."""
    return _event_api(
        message=_message("publish#event", name="UserSignedUp", payload=True),
        server=Server(
            url="broker.example.com",
            name="production",
            protocol="kafka",
            extras={"security": [{"saslScram": []}]},
        ),
    )


# ===========================================================================
# Native rules — each fires; a clean model is silent
# ===========================================================================


def _asyncapi_rules(api: CanonicalApi) -> set:
    return {
        f.rule for f in lint_canonical_model(api).findings if f.rule.startswith("asyncapi.")
    }


def test_clean_event_api_has_no_native_asyncapi_findings() -> None:
    result = lint_canonical_model(_clean_event_api())
    assert not [f for f in result.findings if f.rule.startswith("asyncapi.")]
    # Fully documented + well-formed ⇒ a perfect score.
    assert result.score == 100
    assert result.grade == "A"


def test_message_missing_name_fires() -> None:
    api = _event_api(
        message=_message("publish#event", name=None, payload=True),
        server=_clean_event_api().servers[0],
    )
    assert "asyncapi.message-missing-name" in _asyncapi_rules(api)


def test_message_unstable_name_fires() -> None:
    api = _event_api(
        message=_message("publish#event", name="InlinePayload2", payload=True),
        server=_clean_event_api().servers[0],
    )
    assert "asyncapi.message-unstable-name" in _asyncapi_rules(api)


def test_message_missing_payload_fires() -> None:
    api = _event_api(
        message=_message("publish#event", name="UserSignedUp", payload=False),
        server=_clean_event_api().servers[0],
    )
    assert "asyncapi.message-missing-payload" in _asyncapi_rules(api)


def test_message_with_inline_payload_schema_is_clean() -> None:
    """A message with no named payload but an inline ``payload_schema`` is not flagged."""
    message = Message(
        key="publish#event",
        role=MessageRole.EVENT,
        name="UserSignedUp",
        payload_schema={"type": "object", "properties": {"userId": {"type": "string"}}},
        description="An event.",
    )
    api = _event_api(message=message, server=_clean_event_api().servers[0])
    assert "asyncapi.message-missing-payload" not in _asyncapi_rules(api)


def test_server_missing_protocol_fires() -> None:
    api = _event_api(
        message=_message("publish#event", name="UserSignedUp", payload=True),
        server=Server(url="broker.example.com", name="prod", extras={"security": [{}]}),
    )
    assert "asyncapi.server-missing-protocol" in _asyncapi_rules(api)


def test_server_missing_security_fires() -> None:
    api = _event_api(
        message=_message("publish#event", name="UserSignedUp", payload=True),
        server=Server(url="broker.example.com", name="prod", protocol="kafka"),
    )
    assert "asyncapi.server-missing-security" in _asyncapi_rules(api)


def test_dirty_event_api_surfaces_every_native_rule() -> None:
    api = _event_api(
        message=_message("publish#event", name="InlinePayload2", payload=False),
        server=Server(url="broker.example.com", name="prod"),
    )
    fired = _asyncapi_rules(api)
    assert {
        "asyncapi.message-unstable-name",
        "asyncapi.message-missing-payload",
        "asyncapi.server-missing-protocol",
        "asyncapi.server-missing-security",
    } <= fired
    # Findings drag the score below a clean 100 — they merge into the score.
    assert lint_canonical_model(api).score < 100


# ===========================================================================
# Registry: the pack is registered under both AsyncAPI families
# ===========================================================================


@pytest.mark.parametrize("format_key", ["asyncapi-2", "asyncapi-3"])
def test_pack_registered_for_both_families(format_key: str) -> None:
    pack_cls = get_rule_pack(format_key)
    assert pack_cls is not None
    assert issubclass(pack_cls, AsyncApiRulePack)
    assert format_key in available_lint_formats()


def test_v2_and_v3_run_the_same_native_rules() -> None:
    """The same defective model lints identically whether tagged v2 or v3."""
    base = _event_api(
        message=_message("publish#event", name=None, payload=False),
        server=Server(url="broker.example.com", name="prod"),
    )
    v3 = base.model_copy(update={"format": "asyncapi-3"})
    v2 = base.model_copy(update={"format": "asyncapi-2"})
    assert _asyncapi_rules(v3) == _asyncapi_rules(v2)
    assert _asyncapi_rules(v3)  # non-empty: the rules actually ran


# ===========================================================================
# Spectral diagnostics -> canonical findings
# ===========================================================================


def test_spectral_findings_namespace_and_severity_fold() -> None:
    diagnostics = [
        AsyncApiDiagnostic(
            severity="warning",
            code="asyncapi-payload-default",
            message="Payload should declare a default.",
            path="channels/userSignedUp",
        ),
        AsyncApiDiagnostic(severity="hint", code="asyncapi-tags", message="Add tags.", path=""),
    ]
    findings = spectral_findings(diagnostics)
    assert [f.rule for f in findings] == [
        f"{SPECTRAL_RULE_PREFIX}.asyncapi-payload-default",
        f"{SPECTRAL_RULE_PREFIX}.asyncapi-tags",
    ]
    assert [f.severity for f in findings] == ["warning", "info"]  # hint folds to info
    assert [f.category for f in findings] == ["spectral", "spectral"]
    # An empty diagnostic path is anchored to a readable placeholder.
    assert findings[1].path == "(document)"


def test_spectral_findings_handle_empty_and_blank_code() -> None:
    findings = spectral_findings(
        [AsyncApiDiagnostic(severity="error", code="", message="boom", path="x")]
    )
    assert findings[0].rule == f"{SPECTRAL_RULE_PREFIX}.unknown"
    assert findings[0].severity == "error"


def test_spectral_findings_empty_iterable() -> None:
    assert spectral_findings([]) == []


# ===========================================================================
# Merge: Spectral + native + common roll into one score
# ===========================================================================


def test_lint_asyncapi_result_merges_spectral_into_score() -> None:
    api = _clean_event_api()  # no native or common findings on its own
    clean = lint_asyncapi_result(api, parse_result=None)
    assert clean.score == 100
    assert not clean.findings

    @dataclass
    class _ParseResult:
        diagnostics: List[AsyncApiDiagnostic]

    parse_result = _ParseResult(
        diagnostics=[
            AsyncApiDiagnostic(
                severity="warning",
                code="asyncapi-operation-description",
                message="Operation needs a description.",
                path="operations/onUserSignedUp",
            )
        ]
    )
    merged = lint_asyncapi_result(api, parse_result)
    rules = {f.rule for f in merged.findings}
    assert f"{SPECTRAL_RULE_PREFIX}.asyncapi-operation-description" in rules
    # The Spectral warning pulled the score down — i.e. it merged into the score.
    assert merged.score < clean.score


def test_lint_asyncapi_result_degrades_gracefully_without_parse_result() -> None:
    """No parse result ⇒ native + common still produce a deterministic score."""
    api = _event_api(
        message=_message("publish#event", name=None, payload=False),
        server=Server(url="broker.example.com", name="prod"),
    )
    result = lint_asyncapi_result(api, parse_result=None)
    assert result.findings
    assert all(not f.rule.startswith(SPECTRAL_RULE_PREFIX) for f in result.findings)
    assert result.score < 100


def test_merge_is_deterministic() -> None:
    api = _clean_event_api()

    @dataclass
    class _ParseResult:
        diagnostics: List[AsyncApiDiagnostic]

    diags = [
        AsyncApiDiagnostic(severity="info", code="a", message="m", path="p"),
        AsyncApiDiagnostic(severity="warning", code="b", message="n", path="q"),
    ]
    a = lint_asyncapi_result(api, _ParseResult(diagnostics=copy.deepcopy(diags)))
    b = lint_asyncapi_result(api, _ParseResult(diagnostics=copy.deepcopy(diags)))
    assert a.report_fingerprint == b.report_fingerprint
    assert a.score == b.score
    assert [f.id for f in a.findings] == [f.id for f in b.findings]


# ===========================================================================
# End-to-end (seam): real parser service via a fake runner, v2 + v3
# ===========================================================================


@dataclass
class _FakeRunResult:
    parsed_json: Any


class _FakeRunner:
    """A toolchain runner double returning a fixed parser-wrapper payload."""

    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.calls: List[dict] = []

    async def run(
        self,
        key: str,
        args: Sequence[str] = (),
        *,
        stdin: Optional[str] = None,
        timeout: Optional[float] = None,
        **_: Any,
    ) -> _FakeRunResult:
        self.calls.append({"key": key, "stdin": stdin})
        return _FakeRunResult(parsed_json=self._payload)


def _wrapper_payload(*, version: str, document: dict, diagnostics: list) -> dict:
    """Mirror the ``asyncapi-parse.mjs`` contract for a valid document."""
    info = document.get("info", {})
    return {
        "ok": True,
        "asyncapiVersion": version,
        "identity": {
            "title": info.get("title"),
            "version": info.get("version"),
            "id": document.get("id"),
        },
        "document": document,
        "diagnostics": diagnostics,
    }


def _v3_document() -> dict:
    channel = {
        "address": "user/signedup",
        "messages": {
            "UserSignedUp": {
                "name": "UserSignedUp",
                "payload": {"type": "object", "properties": {"userId": {"type": "string"}}},
            }
        },
    }
    return {
        "asyncapi": "3.0.0",
        "id": "urn:com:example:user-service",
        "info": {"title": "User Service", "version": "1.2.3", "description": "Events."},
        "servers": {
            "production": {"host": "broker.example.com", "protocol": "kafka"}
        },
        "channels": {"userSignedUp": channel},
        "operations": {
            "onUserSignedUp": {
                "action": "receive",
                "channel": copy.deepcopy(channel),
            }
        },
    }


def _v2_document() -> dict:
    return {
        "asyncapi": "2.6.0",
        "id": "urn:com:example:streetlights",
        "info": {"title": "Streetlights API", "version": "1.0.0"},
        "servers": {"production": {"url": "mqtt://broker.example.com", "protocol": "mqtt"}},
        "channels": {
            "light/measured": {
                "description": "Telemetry.",
                "publish": {
                    "message": {
                        "name": "LightMeasured",
                        "payload": {"type": "object", "properties": {"lumens": {"type": "integer"}}},
                    }
                },
            }
        },
    }


@pytest.mark.parametrize(
    "version, document",
    [("3.0.0", _v3_document()), ("2.6.0", _v2_document())],
)
async def test_lint_asyncapi_end_to_end_v2_and_v3(version: str, document: dict) -> None:
    """``lint_asyncapi`` parses, normalizes, and merges Spectral findings for both families."""
    diagnostics = [
        {
            "severity": "warning",
            "code": "asyncapi-info-contact",
            "message": "Info object should contain a contact.",
            "path": "info",
        }
    ]
    runner = _FakeRunner(
        _wrapper_payload(version=version, document=document, diagnostics=diagnostics)
    )
    result = await lint_asyncapi("<raw source>", runner=runner)

    # The parser was shelled out to with the source on stdin.
    assert runner.calls and runner.calls[0]["key"] == ASYNCAPI_PARSER_TOOL_KEY
    assert runner.calls[0]["stdin"] == "<raw source>"

    rules = {f.rule for f in result.findings}
    # The Spectral diagnostic merged in...
    assert f"{SPECTRAL_RULE_PREFIX}.asyncapi-info-contact" in rules
    # ...and merged into the score.
    assert result.score < 100
    assert result.grade in {"A", "B", "C", "D", "F"}


async def test_lint_asyncapi_raises_on_invalid_document() -> None:
    """An invalid document (no dereferenced document) surfaces as a parse error, not a crash."""
    payload = {
        "ok": False,
        "asyncapiVersion": None,
        "identity": None,
        "document": None,
        "diagnostics": [
            {"severity": "error", "code": "asyncapi-is-asyncapi", "message": "bad", "path": ""}
        ],
    }
    runner = _FakeRunner(payload)
    with pytest.raises(AsyncApiParseError):
        await lint_asyncapi("<raw>", runner=runner)


# ===========================================================================
# End-to-end (gated): the real bundled parser over the committed fixtures
# ===========================================================================

_PARSER_AVAILABLE = bool(getattr(probe_tool(ASYNCAPI_PARSER_TOOL_KEY), "available", False))


@pytest.mark.skipif(
    not _PARSER_AVAILABLE,
    reason="asyncapi-parser tool is not resolvable in this environment "
    "(bundled only in the image / via OBJECTIFIED_ASYNCAPI_PARSER_BIN)",
)
class TestRealParserLint:
    """Lints the real 2.6 / 3.0 / 3.1 fixtures end-to-end when the parser is present."""

    @pytest.mark.parametrize(
        "fixture",
        ["streetlights_2.6.yaml", "user_events_3.0.yaml", "account_3.1.yaml"],
    )
    async def test_fixtures_lint_with_merged_score(self, fixture: str) -> None:
        raw = (_FIXTURES / fixture).read_text()
        result = await lint_asyncapi(raw)
        assert 0 <= result.score <= 100
        assert result.grade in {"A", "B", "C", "D", "F"}
        # Deterministic: the same source yields the same fingerprint.
        again = await lint_asyncapi(raw)
        assert result.report_fingerprint == again.report_fingerprint
