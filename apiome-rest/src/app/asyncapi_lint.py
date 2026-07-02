"""AsyncAPI lint pack — MFI-8.3 (#3761).

Quality signals for event-driven (AsyncAPI) APIs, layered on the canonical lint engine
(MFI-4.1 :mod:`app.lint_engine`) and the shared scoring/grade/fingerprint formula
(MFI-4.2 :mod:`app.schema_lint`). It has two complementary halves:

* **Native rules** (:class:`AsyncApiRulePack`) — a :class:`~app.lint_engine.RulePack`
  registered under both ``asyncapi-2`` and ``asyncapi-3`` (the format keys the MFI-8.2
  normalizer emits). The rules run purely over the :class:`~app.canonical_model.CanonicalApi`
  — no I/O — and cover the event-API hygiene the roadmap calls out: **message names**
  (present and not auto-generated), **missing payload schema**, and **server protocol /
  security**. Because they are registered, they run automatically via the engine default
  (:func:`app.lint_engine.lint_canonical_model`) for any AsyncAPI artifact, even with no
  external linter present.

* **Spectral findings** (:func:`spectral_findings`) — the authoritative ``spectral:asyncapi``
  ruleset (v2 *and* v3) is already executed by ``@asyncapi/parser`` during MFI-8.1 parse, and
  surfaces as :class:`~app.asyncapi_parser.AsyncApiDiagnostic` items on the parse result. This
  function maps those Spectral diagnostics into :class:`~app.schema_lint.LintFinding`s so they
  merge into the very same weighted score — i.e. we *wrap* ``extends: spectral:asyncapi``
  through the bundled parser rather than shipping a second copy of Spectral.

The two halves come together in :func:`lint_asyncapi_result` (sync, pure — takes a model plus
an already-obtained parse result) and the convenience :func:`lint_asyncapi` (async — parses,
normalizes, then lints). Spectral is **opt-in and degrades gracefully**: when no parse result
(or no diagnostics) is supplied, the native + common packs still produce a deterministic
score, exactly as MFI-4.3 requires of an external-linter adapter.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from .canonical_model import CanonicalApi, Message, Operation, Server, Service
from .lint_engine import (
    LintRule,
    RulePack,
    is_unstable_name,
    lint_canonical_model,
)
from .schema_lint import LintFinding, LintResult, Severity

__all__ = [
    "AsyncApiRulePack",
    "spectral_findings",
    "lint_asyncapi_result",
    "lint_asyncapi",
    "SPECTRAL_RULE_PREFIX",
]


# ===========================================================================
# Native rule checks (pure generators over the canonical model)
# ===========================================================================
#
# Each check yields ``(path, message)`` pairs in sorted-key order so the engine's
# deterministic re-sort never depends on emission order. Paths mirror the common pack's
# coordinates — ``services.{service}.operations.{operation}.messages.{message}`` for
# messages — so a defect carries the same path no matter which pack reports it.


def _services_sorted(api: CanonicalApi) -> List[Service]:
    return sorted(api.services, key=lambda s: s.key)


def _operations_sorted(service: Service) -> List[Operation]:
    return sorted(service.operations, key=lambda o: o.key)


def _messages_sorted(operation: Operation) -> List[Message]:
    return sorted(operation.messages, key=lambda m: m.key)


def _server_label(server: Server) -> str:
    """A stable, human-meaningful coordinate for a server (it has no ``key``).

    Servers are an unkeyed list on the canonical model, so we identify one by its declared
    ``name`` when present (the authored handle) and fall back to its ``url``. Used both to
    sort servers deterministically and to build a finding path.
    """
    return server.name or server.url or ""


def _servers_sorted(api: CanonicalApi) -> List[Server]:
    return sorted(api.servers, key=_server_label)


def _message_path(service: Service, operation: Operation, message: Message) -> str:
    return (
        f"services.{service.key}.operations.{operation.key}.messages.{message.key}"
    )


def _iter_messages(
    api: CanonicalApi,
) -> Iterable[Tuple[Service, Operation, Message]]:
    """Yield every ``(service, operation, message)`` triple in deterministic order."""
    for service in _services_sorted(api):
        for operation in _operations_sorted(service):
            for message in _messages_sorted(operation):
                yield service, operation, message


def _check_message_missing_name(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """An event message should carry an author-given name (its schema identity).

    A nameless message has no stable handle to diff or reference across versions, so it is
    flagged as a documentation/identity gap.
    """
    for service, operation, message in _iter_messages(api):
        if not (isinstance(message.name, str) and message.name.strip()):
            yield (
                _message_path(service, operation, message),
                f"Message '{message.key}' has no name; event messages should be "
                "named so they have a stable identity across versions.",
            )


def _check_message_unstable_name(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Message names should be author-chosen, not generator output.

    Reuses the shared import-stability heuristic (:func:`app.lint_engine.is_unstable_name`),
    so an auto-generated name like ``InlineMessage1`` — which rarely survives a re-import and
    wrecks diff alignment — is flagged the same way unstable type/field names are.
    """
    for service, operation, message in _iter_messages(api):
        if is_unstable_name(message.name):
            yield (
                _message_path(service, operation, message),
                f"Message name '{message.name}' looks auto-generated/positional and is "
                "unstable across re-imports.",
            )


def _check_message_missing_payload(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Every event message should describe its payload.

    A message with neither a named ``payload`` reference nor an inline ``payload_schema``
    publishes no contract for its consumers — the central concern of an event API — so this
    is a structural warning.
    """
    for service, operation, message in _iter_messages(api):
        if message.payload is None and not message.payload_schema:
            yield (
                _message_path(service, operation, message),
                f"Message '{message.name or message.key}' has no payload schema; "
                "consumers have no contract to validate against.",
            )


def _server_has_security(server: Server) -> bool:
    """Whether the server declares any security (the normalizer keeps it in ``extras``).

    AsyncAPI security requirements are not a canonical first-class field; the MFI-8.2
    normalizer preserves the source ``security`` verbatim under ``Server.extras``. A present,
    non-empty value (a list of requirements in v2/v3, or a mapping) counts as declared.
    """
    security = server.extras.get("security")
    return bool(security)


def _check_server_missing_protocol(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Every server should declare its transport protocol.

    Without a protocol (kafka/amqp/mqtt/ws/…), a server binding is ambiguous — consumers
    cannot tell how to connect — so a missing protocol is a warning.
    """
    for server in _servers_sorted(api):
        if not (isinstance(server.protocol, str) and server.protocol.strip()):
            yield (
                f"servers.{_server_label(server)}",
                f"Server '{_server_label(server)}' does not declare a transport "
                "protocol (e.g. kafka, amqp, mqtt, ws).",
            )


def _check_server_missing_security(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Servers should usually declare a security scheme.

    Event brokers are rarely meant to be open, so an undeclared security requirement is a
    governance smell — flagged at ``info`` severity (not every server genuinely needs one).
    """
    for server in _servers_sorted(api):
        if not _server_has_security(server):
            yield (
                f"servers.{_server_label(server)}",
                f"Server '{_server_label(server)}' declares no security requirements; "
                "confirm the broker is intentionally unauthenticated.",
            )


# ===========================================================================
# The AsyncAPI native rule pack
# ===========================================================================


class AsyncApiRulePack(RulePack, register=True):
    """Native, deterministic hygiene rules for AsyncAPI (event-driven) artifacts.

    Runs in addition to the always-on :class:`~app.lint_engine.CommonRulePack` whenever the
    canonical model's ``format`` is ``asyncapi-3`` (this class) or ``asyncapi-2`` (the
    :class:`_AsyncApi2RulePack` alias below). Pure over the model — no I/O — so it is safe on
    the always-on lint path even when no external linter is available; the Spectral findings
    that complete the picture are merged in separately by :func:`lint_asyncapi_result`.
    """

    format = "asyncapi-3"
    pack_id = "asyncapi"

    #: Built once at class-definition time (the pack is stateless). Listed in execution order
    #: for readability; the engine re-sorts findings deterministically regardless.
    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="asyncapi.message-missing-name",
            category="documentation",
            severity="info",
            description="Every event message should carry an author-given name.",
            check=_check_message_missing_name,
        ),
        LintRule(
            rule_id="asyncapi.message-unstable-name",
            category="naming",
            severity="warning",
            description="Message names should be author-chosen, not generator output.",
            check=_check_message_unstable_name,
        ),
        LintRule(
            rule_id="asyncapi.message-missing-payload",
            category="structure",
            severity="warning",
            description="Every event message should declare a payload schema.",
            check=_check_message_missing_payload,
        ),
        LintRule(
            rule_id="asyncapi.server-missing-protocol",
            category="structure",
            severity="warning",
            description="Every server should declare its transport protocol.",
            check=_check_server_missing_protocol,
        ),
        LintRule(
            rule_id="asyncapi.server-missing-security",
            category="structure",
            severity="info",
            description="Servers should usually declare a security scheme.",
            check=_check_server_missing_security,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the AsyncAPI native rules in deterministic execution order."""
        return list(self._RULES)


class _AsyncApi2RulePack(AsyncApiRulePack, register=True):
    """Alias registration of :class:`AsyncApiRulePack` under the ``asyncapi-2`` key.

    AsyncAPI 2.x and 3.x normalize into the same canonical shape (the MFI-8.2 normalizer
    dispatches on the document's own version), so the v2 and v3 lint rules are identical;
    this thin subclass only adds the second registry key.
    """

    format = "asyncapi-2"


# ===========================================================================
# Spectral (spectral:asyncapi) diagnostics -> canonical findings
# ===========================================================================

#: Namespace every Spectral-sourced finding's rule id lives under, so they group cleanly
#: against the ``asyncapi.*`` native rules and the ``common.*`` cross-format rules.
SPECTRAL_RULE_PREFIX = "asyncapi.spectral"

# Spectral emits four severities; the canonical scorer recognizes three. ``hint`` (the
# lowest, advisory level) folds into ``info`` so it still contributes — gently — to the score.
_SPECTRAL_SEVERITY: Dict[str, Severity] = {
    "error": "error",
    "warning": "warning",
    "info": "info",
    "hint": "info",
}


def spectral_findings(diagnostics: Iterable["object"]) -> List[LintFinding]:
    """Map ``spectral:asyncapi`` diagnostics into canonical :class:`LintFinding`s.

    The diagnostics are the ``@asyncapi/parser`` output (MFI-8.1) — i.e. the official
    ``spectral:asyncapi`` v2/v3 ruleset run during parse — each carrying a ``severity`` /
    ``code`` / ``message`` / ``path``. Each becomes one finding whose ``rule`` is namespaced
    ``asyncapi.spectral.<code>`` so it merges into the score and groups with the native rules.

    Args:
        diagnostics: An iterable of objects exposing ``severity`` / ``code`` / ``message`` /
            ``path`` string attributes — typically
            :class:`~app.asyncapi_parser.AsyncApiDiagnostic`. Accepted structurally so this
            stays free of a hard import of the parser module.

    Returns:
        One :class:`LintFinding` per diagnostic, deduplicated implicitly by the assembler's
        stable id. The list preserves input order; the engine re-sorts deterministically.
    """
    findings: List[LintFinding] = []
    for diagnostic in diagnostics:
        raw_severity = str(getattr(diagnostic, "severity", "") or "")
        severity = _SPECTRAL_SEVERITY.get(raw_severity.lower(), "info")
        code = str(getattr(diagnostic, "code", "") or "").strip() or "unknown"
        message = str(getattr(diagnostic, "message", "") or "")
        path = str(getattr(diagnostic, "path", "") or "") or "(document)"
        findings.append(
            LintFinding(
                path=path,
                category="spectral",
                rule=f"{SPECTRAL_RULE_PREFIX}.{code}",
                severity=severity,
                message=message,
            )
        )
    return findings


# ===========================================================================
# Merge entry points
# ===========================================================================


def lint_asyncapi_result(
    model: CanonicalApi,
    parse_result: Optional["object"] = None,
) -> LintResult:
    """Lint an AsyncAPI model, merging Spectral findings into the score when available.

    Combines three sources through the shared engine so the score, grade, and
    ``report_fingerprint`` use the exact same formula as every other format:

    * the always-on :class:`~app.lint_engine.CommonRulePack` (cross-format hygiene),
    * the registered :class:`AsyncApiRulePack` (native event-API rules), looked up by the
      model's ``asyncapi-2`` / ``asyncapi-3`` format, and
    * the ``spectral:asyncapi`` diagnostics from ``parse_result`` (MFI-8.1), if supplied.

    Args:
        model: The canonical AsyncAPI artifact (from the MFI-8.2 normalizer). Not mutated.
        parse_result: The MFI-8.1 parse result whose ``diagnostics`` carry the Spectral
            findings. When ``None`` (or it has no diagnostics), Spectral contributes nothing
            and the report degrades gracefully to the native + common packs.

    Returns:
        A deterministic :class:`~app.schema_lint.LintResult`.
    """
    extra = spectral_findings(getattr(parse_result, "diagnostics", []) or [])
    return lint_canonical_model(model, extra_findings=extra)


async def lint_asyncapi(
    raw: str,
    *,
    runner: Optional["object"] = None,
    timeout: Optional[float] = None,
) -> LintResult:
    """Parse, normalize, and lint raw AsyncAPI source end-to-end (v2 and v3).

    A convenience that ties MFI-8.1 (parse + ``spectral:asyncapi``) and MFI-8.2 (normalize)
    to this pack: it parses ``raw`` to obtain the dereferenced document and its Spectral
    diagnostics, normalizes the document into the canonical model, then merges everything via
    :func:`lint_asyncapi_result`. The MFI-8.5 import pipeline, which already holds the parse
    result and the model, calls :func:`lint_asyncapi_result` directly instead.

    Args:
        raw: The raw AsyncAPI source text (JSON or YAML).
        runner: Optional toolchain runner override forwarded to the parser (injectable for
            tests); defaults to the shared runner.
        timeout: Optional per-call parse timeout in seconds.

    Returns:
        A deterministic :class:`~app.schema_lint.LintResult`.

    Raises:
        app.asyncapi_parser.AsyncApiParseError: If the parser tool is unavailable/times out,
            or the document is invalid (no dereferenced document to normalize). A valid but
            imperfect document does not raise — its Spectral findings flow into the score.
    """
    # Imported lazily so importing this pack (e.g. for native-rule registration on the
    # always-on lint path) never pulls in the parser/normalizer machinery.
    from .asyncapi_normalizer import AsyncApiNormalizer
    from .asyncapi_parser import parse_asyncapi

    parse_result = await parse_asyncapi(raw, runner=runner, timeout=timeout)
    parse_result.raise_if_invalid()
    model = AsyncApiNormalizer().normalize(parse_result.document)
    return lint_asyncapi_result(model, parse_result)
