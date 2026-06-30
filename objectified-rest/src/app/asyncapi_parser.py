"""AsyncAPI parse + validate service — MFI-8.1 (#3759).

The Python ecosystem for AsyncAPI is thin, so the authoritative parser is the JavaScript
``@asyncapi/parser``. This module is the Python seam over it: it shells out to the bundled
``asyncapi-parser`` tool (a small Node wrapper around ``@asyncapi/parser`` — see
``objectified-rest/toolchain/asyncapi-parse.mjs``) through the polyglot toolchain runner
(:mod:`app.toolchain_runner`, MFI-5.1), feeds the raw document over ``stdin``, and adapts the
wrapper's JSON contract into typed results.

What the parser does for us, in one call:

* **validate** — AsyncAPI 2.6 / 3.0 / 3.1 (and the rest of the 2.x/3.x families) are checked
  against the spec; problems come back as :class:`AsyncApiDiagnostic`\\s with a Spectral-style
  ``severity`` (``error`` / ``warning`` / ``info`` / ``hint``).
* **dereference** — in-document ``$ref``\\s are resolved inline, and the parser's internal
  ``x-parser-*`` bookkeeping keys are stripped, so :attr:`AsyncApiParseResult.document` is a
  clean *canonical JSON* ready for the canonical-model mapping in MFI-8.2.
* **identity** — ``info.title`` / ``info.version`` and the document ``id`` are captured into
  :class:`AsyncApiIdentity`.

A document that fails validation is **not** an exception: :func:`parse_asyncapi` still returns
a result with :attr:`AsyncApiParseResult.ok` ``False`` and the error diagnostics attached, so a
caller can surface them. Callers that prefer the raising style use
:meth:`AsyncApiParseResult.raise_if_invalid`. Exceptions (:class:`AsyncApiParseError`) are
reserved for *infrastructure* failures — the tool is not installed, it timed out, or it
returned something the wrapper contract does not describe.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .toolchain_runner import (
    ToolchainError,
    ToolchainRunner,
    ToolNotAvailableError,
    default_runner,
)

__all__ = [
    "ASYNCAPI_PARSER_TOOL_KEY",
    "ASYNCAPI_SUPPORTED_VERSIONS",
    "AsyncApiIdentity",
    "AsyncApiDiagnostic",
    "AsyncApiParseResult",
    "AsyncApiParseError",
    "is_supported_asyncapi_version",
    "parse_asyncapi",
]


#: Registry key of the bundled Node wrapper tool (declared in :mod:`app.toolchain_packaging`).
ASYNCAPI_PARSER_TOOL_KEY = "asyncapi-parser"

#: The AsyncAPI versions MFI-8.1 explicitly targets. The parser accepts the wider 2.x/3.x
#: families too; this tuple is the documented baseline the fixtures cover and what
#: :func:`is_supported_asyncapi_version` treats as first-class.
ASYNCAPI_SUPPORTED_VERSIONS: Tuple[str, ...] = ("2.6.0", "3.0.0", "3.1.0")

#: Diagnostic severities the wrapper emits (Spectral levels), most-to-least severe.
_SEVERITIES: Tuple[str, ...] = ("error", "warning", "info", "hint")


def is_supported_asyncapi_version(version: Optional[str]) -> bool:
    """Return whether ``version`` is in a supported AsyncAPI major family (2.x or 3.x).

    The parser is the authority on exact validity; this is a cheap, dependency-free guard a
    caller (or the CLI/UI source card) can use to reject a clearly out-of-scope document
    (e.g. AsyncAPI 1.x) before paying for a subprocess. ``None``/empty is not supported.
    """
    if not version:
        return False
    major = version.split(".", 1)[0]
    return major in {"2", "3"}


# ===========================================================================
# Result models
# ===========================================================================


class AsyncApiIdentity(BaseModel):
    """The stable identity captured from a parsed AsyncAPI document.

    Mirrors the spec's identity fields: ``info.title`` / ``info.version`` and the optional
    top-level ``id`` (a URN/URI the author may pin). Any field is ``None`` when the document
    omits it.
    """

    model_config = ConfigDict(frozen=True)

    title: Optional[str] = Field(default=None, description="``info.title`` of the document.")
    version: Optional[str] = Field(
        default=None, description="``info.version`` of the document (the API version)."
    )
    id: Optional[str] = Field(
        default=None, description="The document's top-level ``id`` (URN/URI), when present."
    )


class AsyncApiDiagnostic(BaseModel):
    """One validation finding the parser reported against a document.

    Severities follow the parser's Spectral levels: ``error`` (the document is invalid),
    ``warning`` / ``info`` / ``hint`` (advisory hygiene). Only an ``error`` makes
    :attr:`AsyncApiParseResult.ok` ``False``.
    """

    model_config = ConfigDict(frozen=True)

    severity: str = Field(description="error / warning / info / hint.")
    code: str = Field(description="The rule code the parser fired (e.g. ``asyncapi-is-asyncapi``).")
    message: str = Field(description="Human-readable explanation of the finding.")
    path: str = Field(
        default="", description="Slash-joined JSON path to the offending node (empty = root)."
    )

    @property
    def is_error(self) -> bool:
        """Whether this finding is an error (renders the document invalid)."""
        return self.severity == "error"


class AsyncApiParseResult(BaseModel):
    """The outcome of parsing + validating one AsyncAPI document.

    A *valid* document has :attr:`ok` ``True``, a populated :attr:`document` (dereferenced,
    canonical JSON) and :attr:`identity`, and possibly some advisory (non-error) diagnostics.
    An *invalid* document has :attr:`ok` ``False``, ``document``/``identity`` may be ``None``,
    and :attr:`diagnostics` carries at least one ``error``.
    """

    model_config = ConfigDict(frozen=True)

    ok: bool = Field(description="True when the document parsed and validated with no errors.")
    asyncapi_version: Optional[str] = Field(
        default=None, description="The document's ``asyncapi`` version (e.g. ``3.0.0``)."
    )
    identity: Optional[AsyncApiIdentity] = Field(
        default=None, description="Captured identity (title/version/id); ``None`` when unparsable."
    )
    document: Optional[Dict[str, Any]] = Field(
        default=None,
        description="The dereferenced, canonical JSON document (parser internals stripped); "
        "``None`` when the document could not be parsed.",
    )
    diagnostics: List[AsyncApiDiagnostic] = Field(
        default_factory=list, description="All validation findings, in the parser's order."
    )

    @property
    def errors(self) -> List[AsyncApiDiagnostic]:
        """The error-severity diagnostics (empty when the document is valid)."""
        return [d for d in self.diagnostics if d.is_error]

    @property
    def supported_version(self) -> bool:
        """Whether :attr:`asyncapi_version` is in a supported 2.x/3.x family."""
        return is_supported_asyncapi_version(self.asyncapi_version)

    def raise_if_invalid(self) -> "AsyncApiParseResult":
        """Return ``self`` when valid; raise :class:`AsyncApiParseError` when not.

        A convenience for callers (e.g. an import adapter) that want an invalid document to
        propagate as an error rather than be inspected. The raised error carries the error
        diagnostics and the detected version.

        Raises:
            AsyncApiParseError: When :attr:`ok` is ``False``.
        """
        if self.ok:
            return self
        errors = self.errors
        detail = errors[0].message if errors else "AsyncAPI document failed validation"
        raise AsyncApiParseError(
            detail, diagnostics=self.diagnostics, asyncapi_version=self.asyncapi_version
        )


class AsyncApiParseError(Exception):
    """An AsyncAPI document could not be parsed/validated, or the parser tool failed.

    Raised for *infrastructure* failures (the bundled parser tool is unavailable, timed out,
    or returned output the wrapper contract does not describe) and — only via
    :meth:`AsyncApiParseResult.raise_if_invalid` — for an invalid document. Carries a
    human-readable message a route can surface directly, plus any diagnostics the parser did
    return.
    """

    def __init__(
        self,
        message: str,
        *,
        diagnostics: Optional[List[AsyncApiDiagnostic]] = None,
        asyncapi_version: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics: List[AsyncApiDiagnostic] = list(diagnostics or [])
        self.asyncapi_version = asyncapi_version


# ===========================================================================
# Parse entry point
# ===========================================================================


def _coerce_diagnostics(raw: Any) -> List[AsyncApiDiagnostic]:
    """Adapt the wrapper's ``diagnostics`` array into typed, validated diagnostics.

    Tolerant of a missing/odd shape (a non-list, or non-mapping entries are skipped) so a
    quirk in one finding never sinks an otherwise-usable result.
    """
    if not isinstance(raw, list):
        return []
    out: List[AsyncApiDiagnostic] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        severity = str(entry.get("severity", "error"))
        if severity not in _SEVERITIES:
            severity = "error"
        out.append(
            AsyncApiDiagnostic(
                severity=severity,
                code=str(entry.get("code", "")),
                message=str(entry.get("message", "")),
                path=str(entry.get("path", "")),
            )
        )
    return out


def _identity_from(raw: Any) -> Optional[AsyncApiIdentity]:
    """Adapt the wrapper's ``identity`` object into an :class:`AsyncApiIdentity`, or ``None``."""
    if not isinstance(raw, dict):
        return None

    def _str_or_none(value: Any) -> Optional[str]:
        return value if isinstance(value, str) else None

    return AsyncApiIdentity(
        title=_str_or_none(raw.get("title")),
        version=_str_or_none(raw.get("version")),
        id=_str_or_none(raw.get("id")),
    )


def _result_from_payload(payload: Any) -> AsyncApiParseResult:
    """Build an :class:`AsyncApiParseResult` from the wrapper's parsed JSON object.

    Raises:
        AsyncApiParseError: If ``payload`` is not the object shape the wrapper guarantees.
    """
    if not isinstance(payload, dict):
        raise AsyncApiParseError(
            "AsyncAPI parser returned an unexpected (non-object) result; the wrapper contract "
            "was violated"
        )

    diagnostics = _coerce_diagnostics(payload.get("diagnostics"))
    document = payload.get("document")
    if document is not None and not isinstance(document, dict):
        document = None

    version = payload.get("asyncapiVersion")
    asyncapi_version = version if isinstance(version, str) else None

    # Trust the wrapper's ``ok`` when present, but never call a document with error diagnostics
    # valid (defence in depth against a wrapper contract drift).
    has_errors = any(d.is_error for d in diagnostics)
    ok = bool(payload.get("ok")) and document is not None and not has_errors

    return AsyncApiParseResult(
        ok=ok,
        asyncapi_version=asyncapi_version,
        identity=_identity_from(payload.get("identity")),
        document=document,
        diagnostics=diagnostics,
    )


async def parse_asyncapi(
    raw: str,
    *,
    source_label: Optional[str] = None,
    runner: Optional[ToolchainRunner] = None,
    timeout: Optional[float] = None,
) -> AsyncApiParseResult:
    """Parse, validate and dereference an AsyncAPI document via ``@asyncapi/parser``.

    The raw document (JSON or YAML) is fed over ``stdin`` to the bundled ``asyncapi-parser``
    tool, which validates it, resolves in-document ``$ref``\\s, and returns canonical JSON.
    The result describes the outcome either way: a valid document yields ``ok=True`` with a
    dereferenced :attr:`~AsyncApiParseResult.document` and :attr:`~AsyncApiParseResult.identity`;
    an invalid one yields ``ok=False`` with error diagnostics. Validation failure is therefore
    a *return value*, not an exception.

    Args:
        raw: The raw AsyncAPI source text (already fetched by the ingestion layer).
        source_label: Optional label (filename/URL) used only to enrich an infrastructure
            error message.
        runner: The toolchain runner to use; defaults to the shared
            :data:`app.toolchain_runner.default_runner`. Injectable for tests.
        timeout: Optional per-call timeout in seconds; falls back to the tool/service default.

    Returns:
        An :class:`AsyncApiParseResult`.

    Raises:
        AsyncApiParseError: For *infrastructure* failures only — the parser tool is not
            installed in this runtime, it exceeded its timeout, or it produced output the
            wrapper contract does not describe. A merely-invalid document does **not** raise.
    """
    active_runner = runner if runner is not None else default_runner
    where = f" ({source_label})" if source_label else ""

    try:
        run_result = await active_runner.run(
            ASYNCAPI_PARSER_TOOL_KEY, [], stdin=raw, timeout=timeout
        )
    except ToolNotAvailableError as exc:
        raise AsyncApiParseError(
            f"The AsyncAPI parser tool is not available in this runtime{where}; AsyncAPI import "
            "is unavailable here (see the bundled toolchain packaging, MFI-5.2)."
        ) from exc
    except ToolchainError as exc:
        raise AsyncApiParseError(
            f"The AsyncAPI parser tool failed{where}: {exc}"
        ) from exc

    return _result_from_payload(run_result.parsed_json)
