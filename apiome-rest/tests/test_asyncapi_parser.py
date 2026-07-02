"""Tests for the AsyncAPI parse + validate service (MFI-8.1, #3759).

Two layers:

* **Seam tests** (always run, no Node) drive :func:`app.asyncapi_parser.parse_asyncapi` with an
  injected fake runner that replays the bundled wrapper's JSON contract — including authentic
  payload shapes captured from a real ``@asyncapi/parser`` run — so the Python adaptation
  (result mapping, identity capture, diagnostics, error handling) is fully exercised.
* **End-to-end test** (gated, like the POSIX-only sandbox tests) runs the *real* committed Node
  wrapper through the *real* toolchain runner against the on-disk fixtures, but only when the
  ``asyncapi-parser`` tool actually resolves in this environment (a built image, or a dev box
  that points ``APIOME_ASYNCAPI_PARSER_BIN`` at the wrapper).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Sequence

import pytest

from app.asyncapi_parser import (
    ASYNCAPI_PARSER_TOOL_KEY,
    ASYNCAPI_SUPPORTED_VERSIONS,
    AsyncApiDiagnostic,
    AsyncApiParseError,
    AsyncApiParseResult,
    is_supported_asyncapi_version,
    parse_asyncapi,
)
from app.toolchain_packaging import probe_tool
from app.toolchain_runner import (
    ToolExecutionError,
    ToolNotAvailableError,
    ToolOutputError,
    ToolTimeoutError,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "asyncapi"


# ===========================================================================
# A fake runner replaying the wrapper's JSON contract
# ===========================================================================


@dataclass
class _FakeRunResult:
    """Minimal stand-in for ``ToolRunResult`` — the service only reads ``parsed_json``."""

    parsed_json: Any


class _FakeRunner:
    """A toolchain runner double that returns a fixed payload (or raises a fixed error).

    Records the last invocation so a test can assert the service shelled out with the right
    tool key, empty args, and the document on ``stdin``.
    """

    def __init__(self, *, payload: Any = None, error: Optional[Exception] = None) -> None:
        self._payload = payload
        self._error = error
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
        self.calls.append({"key": key, "args": list(args), "stdin": stdin, "timeout": timeout})
        if self._error is not None:
            raise self._error
        return _FakeRunResult(parsed_json=self._payload)


def _ok_payload(
    *,
    version: str,
    title: str,
    api_version: str,
    doc_id: Optional[str],
    document: dict,
    diagnostics: Optional[list] = None,
) -> dict:
    """Build a valid-document wrapper payload mirroring the real wrapper's contract."""
    return {
        "ok": True,
        "asyncapiVersion": version,
        "identity": {"title": title, "version": api_version, "id": doc_id},
        "document": document,
        "diagnostics": diagnostics or [],
    }


# A v3 payload with the message $ref already dereferenced inline (as @asyncapi/parser returns).
_V3_DEREFERENCED_DOC = {
    "asyncapi": "3.0.0",
    "id": "urn:com:example:user-service",
    "info": {"title": "User Service", "version": "1.2.3"},
    "channels": {
        "userSignedUp": {
            "address": "user/signedup",
            "messages": {
                "UserSignedUp": {
                    "name": "UserSignedUp",
                    "payload": {
                        "type": "object",
                        "properties": {"userId": {"type": "string"}},
                    },
                }
            },
        }
    },
}


# ===========================================================================
# Version helpers
# ===========================================================================


@pytest.mark.parametrize("version", ASYNCAPI_SUPPORTED_VERSIONS)
def test_supported_versions_are_supported(version: str) -> None:
    assert is_supported_asyncapi_version(version)


@pytest.mark.parametrize(
    "version, expected",
    [
        ("2.0.0", True),
        ("2.6.0", True),
        ("3.0.0", True),
        ("3.1.0", True),
        ("1.2.0", False),
        ("4.0.0", False),
        ("", False),
        (None, False),
        ("nonsense", False),
    ],
)
def test_is_supported_asyncapi_version(version: Optional[str], expected: bool) -> None:
    assert is_supported_asyncapi_version(version) is expected


# ===========================================================================
# Valid documents (v2.6 / v3.0 / v3.1)
# ===========================================================================


async def test_parse_valid_v3_dereferenced_and_identity() -> None:
    runner = _FakeRunner(
        payload=_ok_payload(
            version="3.0.0",
            title="User Service",
            api_version="1.2.3",
            doc_id="urn:com:example:user-service",
            document=_V3_DEREFERENCED_DOC,
            diagnostics=[
                {
                    "severity": "info",
                    "code": "asyncapi-latest-version",
                    "message": "A newer AsyncAPI version is available.",
                    "path": "asyncapi",
                }
            ],
        )
    )

    result = await parse_asyncapi("asyncapi: 3.0.0\n...", runner=runner)

    assert result.ok is True
    assert result.asyncapi_version == "3.0.0"
    assert result.supported_version is True
    assert result.identity is not None
    assert result.identity.title == "User Service"
    assert result.identity.version == "1.2.3"
    assert result.identity.id == "urn:com:example:user-service"
    # The message $ref is dereferenced inline in the canonical document.
    payload = result.document["channels"]["userSignedUp"]["messages"]["UserSignedUp"]["payload"]
    assert payload == {"type": "object", "properties": {"userId": {"type": "string"}}}
    # An info-level diagnostic does not make the document invalid.
    assert result.errors == []
    assert result.diagnostics[0].severity == "info"


@pytest.mark.parametrize(
    "version, api_version",
    [("2.6.0", "1.0.0"), ("3.0.0", "1.2.3"), ("3.1.0", "2.0.0")],
)
async def test_parse_captures_version_across_families(version: str, api_version: str) -> None:
    runner = _FakeRunner(
        payload=_ok_payload(
            version=version,
            title="T",
            api_version=api_version,
            doc_id=None,
            document={"asyncapi": version, "info": {"title": "T", "version": api_version}},
        )
    )
    result = await parse_asyncapi("doc", runner=runner)
    assert result.ok is True
    assert result.asyncapi_version == version
    assert result.identity.version == api_version


async def test_warnings_do_not_invalidate_a_valid_document() -> None:
    runner = _FakeRunner(
        payload=_ok_payload(
            version="2.6.0",
            title="T",
            api_version="1.0.0",
            doc_id=None,
            document={"asyncapi": "2.6.0", "info": {"title": "T", "version": "1.0.0"}},
            diagnostics=[
                {"severity": "warning", "code": "asyncapi-servers", "message": "no servers", "path": ""},
                {"severity": "hint", "code": "asyncapi-tags", "message": "add tags", "path": ""},
            ],
        )
    )
    result = await parse_asyncapi("doc", runner=runner)
    assert result.ok is True
    assert result.errors == []
    assert {d.severity for d in result.diagnostics} == {"warning", "hint"}


async def test_run_invocation_feeds_document_on_stdin() -> None:
    runner = _FakeRunner(
        payload=_ok_payload(
            version="3.0.0",
            title="T",
            api_version="1",
            doc_id=None,
            document={"asyncapi": "3.0.0", "info": {"title": "T", "version": "1"}},
        )
    )
    await parse_asyncapi("THE-RAW-DOC", runner=runner, timeout=12.0)
    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call["key"] == ASYNCAPI_PARSER_TOOL_KEY
    assert call["args"] == []
    assert call["stdin"] == "THE-RAW-DOC"
    assert call["timeout"] == 12.0


# ===========================================================================
# Invalid documents — reported, not raised
# ===========================================================================


async def test_invalid_document_reports_errors_without_raising() -> None:
    runner = _FakeRunner(
        payload={
            "ok": False,
            "asyncapiVersion": None,
            "identity": None,
            "document": None,
            "diagnostics": [
                {
                    "severity": "error",
                    "code": "asyncapi-document-resolved",
                    "message": '"info" property must have required property "version"',
                    "path": "info",
                }
            ],
        }
    )
    result = await parse_asyncapi("asyncapi: 3.0.0\ninfo:\n  title: X\n", runner=runner)

    assert result.ok is False
    assert result.document is None
    assert result.identity is None
    assert len(result.errors) == 1
    assert result.errors[0].is_error is True
    assert "required property" in result.errors[0].message


async def test_raise_if_invalid_raises_with_diagnostics() -> None:
    runner = _FakeRunner(
        payload={
            "ok": False,
            "asyncapiVersion": None,
            "identity": None,
            "document": None,
            "diagnostics": [
                {
                    "severity": "error",
                    "code": "asyncapi-is-asyncapi",
                    "message": "This is not an AsyncAPI document.",
                    "path": "",
                }
            ],
        }
    )
    result = await parse_asyncapi("{}", runner=runner)
    assert result.ok is False
    with pytest.raises(AsyncApiParseError) as exc:
        result.raise_if_invalid()
    assert "not an AsyncAPI document" in str(exc.value)
    assert exc.value.diagnostics and exc.value.diagnostics[0].code == "asyncapi-is-asyncapi"


async def test_raise_if_invalid_returns_self_when_valid() -> None:
    runner = _FakeRunner(
        payload=_ok_payload(
            version="3.0.0",
            title="T",
            api_version="1",
            doc_id=None,
            document={"asyncapi": "3.0.0", "info": {"title": "T", "version": "1"}},
        )
    )
    result = await parse_asyncapi("doc", runner=runner)
    assert result.raise_if_invalid() is result


async def test_error_diagnostic_overrides_a_truthy_ok_flag() -> None:
    # Defence in depth: even if the wrapper said ok=true, an error diagnostic forces ok=false.
    runner = _FakeRunner(
        payload={
            "ok": True,
            "asyncapiVersion": "3.0.0",
            "identity": {"title": "T", "version": "1", "id": None},
            "document": {"asyncapi": "3.0.0"},
            "diagnostics": [
                {"severity": "error", "code": "boom", "message": "bad", "path": ""}
            ],
        }
    )
    result = await parse_asyncapi("doc", runner=runner)
    assert result.ok is False


async def test_missing_document_forces_ok_false_even_if_flag_true() -> None:
    runner = _FakeRunner(
        payload={
            "ok": True,
            "asyncapiVersion": "3.0.0",
            "identity": None,
            "document": None,
            "diagnostics": [],
        }
    )
    result = await parse_asyncapi("doc", runner=runner)
    assert result.ok is False


# ===========================================================================
# Payload coercion robustness
# ===========================================================================


async def test_diagnostics_coercion_is_tolerant() -> None:
    runner = _FakeRunner(
        payload={
            "ok": True,
            "asyncapiVersion": "3.0.0",
            "identity": {"title": "T", "version": "1", "id": None},
            "document": {"asyncapi": "3.0.0", "info": {"title": "T", "version": "1"}},
            "diagnostics": [
                "not-a-mapping",
                {"severity": "weird", "code": 123, "message": None},  # unknown sev -> error; coerced
                {"code": "no-severity", "message": "x"},  # missing severity -> defaults to error
            ],
        }
    )
    result = await parse_asyncapi("doc", runner=runner)
    # The string entry is dropped; the two mappings survive, both as errors.
    assert len(result.diagnostics) == 2
    assert all(isinstance(d, AsyncApiDiagnostic) for d in result.diagnostics)
    assert all(d.severity == "error" for d in result.diagnostics)
    # An error diagnostic means the document is not ok despite the flag.
    assert result.ok is False


async def test_non_dict_document_is_normalised_to_none() -> None:
    runner = _FakeRunner(
        payload={
            "ok": True,
            "asyncapiVersion": "3.0.0",
            "identity": None,
            "document": ["not", "an", "object"],
            "diagnostics": [],
        }
    )
    result = await parse_asyncapi("doc", runner=runner)
    assert result.document is None
    assert result.ok is False


async def test_identity_with_non_string_fields_becomes_none_fields() -> None:
    runner = _FakeRunner(
        payload={
            "ok": True,
            "asyncapiVersion": "3.0.0",
            "identity": {"title": 5, "version": None, "id": 7},
            "document": {"asyncapi": "3.0.0", "info": {"title": "T", "version": "1"}},
            "diagnostics": [],
        }
    )
    result = await parse_asyncapi("doc", runner=runner)
    assert result.identity is not None
    assert result.identity.title is None
    assert result.identity.version is None
    assert result.identity.id is None


# ===========================================================================
# Infrastructure failures — raised as AsyncApiParseError
# ===========================================================================


async def test_tool_not_available_raises_parse_error() -> None:
    runner = _FakeRunner(
        error=ToolNotAvailableError(ASYNCAPI_PARSER_TOOL_KEY, "asyncapi-parser")
    )
    with pytest.raises(AsyncApiParseError) as exc:
        await parse_asyncapi("doc", runner=runner, source_label="events.yaml")
    assert "not available" in str(exc.value)
    assert "events.yaml" in str(exc.value)


async def test_tool_timeout_raises_parse_error() -> None:
    runner = _FakeRunner(error=ToolTimeoutError(ASYNCAPI_PARSER_TOOL_KEY, 30.0))
    with pytest.raises(AsyncApiParseError) as exc:
        await parse_asyncapi("doc", runner=runner)
    assert "failed" in str(exc.value)


async def test_tool_execution_error_raises_parse_error() -> None:
    runner = _FakeRunner(
        error=ToolExecutionError(ASYNCAPI_PARSER_TOOL_KEY, 1, "", "wrapper blew up")
    )
    with pytest.raises(AsyncApiParseError) as exc:
        await parse_asyncapi("doc", runner=runner)
    assert "wrapper blew up" in str(exc.value)


async def test_tool_output_error_raises_parse_error() -> None:
    runner = _FakeRunner(
        error=ToolOutputError(ASYNCAPI_PARSER_TOOL_KEY, "not json", "Expecting value")
    )
    with pytest.raises(AsyncApiParseError):
        await parse_asyncapi("doc", runner=runner)


@pytest.mark.parametrize("payload", [None, [], "a string", 42])
async def test_non_object_payload_raises_contract_error(payload: Any) -> None:
    runner = _FakeRunner(payload=payload)
    with pytest.raises(AsyncApiParseError) as exc:
        await parse_asyncapi("doc", runner=runner)
    assert "contract" in str(exc.value)


async def test_default_runner_used_when_none(monkeypatch) -> None:
    captured = _FakeRunner(
        payload=_ok_payload(
            version="3.0.0",
            title="T",
            api_version="1",
            doc_id=None,
            document={"asyncapi": "3.0.0", "info": {"title": "T", "version": "1"}},
        )
    )
    monkeypatch.setattr("app.asyncapi_parser.default_runner", captured)
    result = await parse_asyncapi("doc")  # no runner kwarg
    assert result.ok is True
    assert captured.calls and captured.calls[0]["key"] == ASYNCAPI_PARSER_TOOL_KEY


# ===========================================================================
# Result model surface
# ===========================================================================


def test_result_errors_property_filters_severity() -> None:
    result = AsyncApiParseResult(
        ok=False,
        asyncapi_version="3.0.0",
        diagnostics=[
            AsyncApiDiagnostic(severity="warning", code="w", message="w"),
            AsyncApiDiagnostic(severity="error", code="e", message="e"),
        ],
    )
    assert [d.code for d in result.errors] == ["e"]
    assert result.supported_version is True


# ===========================================================================
# End-to-end: the real Node wrapper through the real runner (gated)
# ===========================================================================

_PARSER_AVAILABLE = bool(getattr(probe_tool(ASYNCAPI_PARSER_TOOL_KEY), "available", False))


@pytest.mark.skipif(
    not _PARSER_AVAILABLE,
    reason="asyncapi-parser tool is not resolvable in this environment "
    "(bundled only in the image / via APIOME_ASYNCAPI_PARSER_BIN)",
)
class TestRealParser:
    """Exercises the committed wrapper end-to-end when the tool is actually present."""

    @pytest.mark.parametrize(
        "fixture, version, title, api_version",
        [
            ("streetlights_2.6.yaml", "2.6.0", "Streetlights API", "1.0.0"),
            ("user_events_3.0.yaml", "3.0.0", "User Service", "1.2.3"),
            ("account_3.1.yaml", "3.1.0", "Account Service", "2.0.0"),
        ],
    )
    async def test_valid_fixtures_parse_and_dereference(
        self, fixture: str, version: str, title: str, api_version: str
    ) -> None:
        raw = (_FIXTURES / fixture).read_text()
        result = await parse_asyncapi(raw, source_label=fixture)
        assert result.ok is True
        assert result.asyncapi_version == version
        assert result.identity.title == title
        assert result.identity.version == api_version
        # A $ref to a component schema is resolved inline (dereferenced) — no "$ref" remains.
        assert "$ref" not in str(result.document.get("channels"))
        assert "x-parser-" not in str(result.document)

    async def test_invalid_fixture_reports_errors(self) -> None:
        raw = (_FIXTURES / "invalid_missing_version_3.0.yaml").read_text()
        result = await parse_asyncapi(raw)
        assert result.ok is False
        assert result.errors
        with pytest.raises(AsyncApiParseError):
            result.raise_if_invalid()

    async def test_non_asyncapi_document_reports_errors(self) -> None:
        raw = (_FIXTURES / "not_asyncapi.json").read_text()
        result = await parse_asyncapi(raw)
        assert result.ok is False
        assert any(d.code == "asyncapi-is-asyncapi" for d in result.errors)
