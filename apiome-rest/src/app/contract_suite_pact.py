"""Compile a pact into a deterministic contract suite — PFX-3.1 (#6931).

A pact is a consumer's recording: for each interaction, the request it sent and the response it
accepted, the provider states it assumed, and the matching rules that widen "this value" to "any
value like this one". Provider verification (PFX-3.2) replays those interactions against a running
provider. This module turns a pact into the same **contract-suite manifest** the ECA-1.1 compiler
produces for a published version (:mod:`app.contract_suite`), so the replay runs on the existing
runner and its evidence cites a suite digest like every other verification.

What a pact case is
-------------------
One HTTP interaction becomes one case with ``source: pact_interaction`` and ``synthetic: false``
(the consumer recorded it; nothing is generated):

* ``request`` — the method, path, query and headers, and the body, exactly as recorded. Pact 2's
  query string and Pact 3/4's object of values are read alike; a Pact 4 body object is unwrapped.
* ``expect`` — the recorded status (or, under a Pact 4 ``statusCode`` rule, the status classes it
  allows) and whether the case expects a client error.
* ``pact`` — everything else verification needs: the interaction's index, ``key`` and pointer,
  its ``pending`` flag, its **provider states** with their parameters, the **expected response**
  (status, headers, body, media type) and the **matching rules** and **generators** of both sides,
  each in one shape whichever specification version filed it.

Cases are grouped by operation (``METHOD path``, sorted) and then follow the pact's own order.

Plugin and GraphQL interactions (PFX-3.7)
-----------------------------------------
* A **gRPC call recorded by the protobuf plugin** (Pact 4 ``Synchronous/Messages``,
  ``transport: grpc``) becomes a ``grpc``-protocol case — the XPC-3.2 RPC case model
  (:mod:`app.contract_suite_rpc`), keyed ``package.Service.Method`` — read through the
  descriptors the pact files in its metadata (:mod:`app.pact_plugin_grpc`). Its request and
  expected reply are protobuf-JSON; its expected status is ``ok`` or the recorded
  ``grpc-status``; its response matching rules are renamed to protobuf-JSON field names. It runs
  on a ``grpc`` or ``connect`` verification target. A suite whose every case is gRPC is stamped
  ``protocol: grpc``; otherwise it stays ``http``.
* A **GraphQL-over-HTTP interaction** stays an HTTP case but carries the operation
  (``case.graphql``, the XPC-1.2 model, :mod:`app.pact_graphql`) so the mutating-method gate
  reads its operation type and the runner checks the GraphQL ``errors`` envelope. Mapping its
  selections onto the consumer-contract model awaits XPC-1.6 (#5733) and is reported.
* Any other plugin interaction (CSV, Avro, a protobuf body over HTTP …) is listed unsupported.

Deterministic per pact version
------------------------------
The manifest is built only from what the pact version's content address covers (the interactions,
the messages and the specification version — :func:`app.pact_publication.pact_content_sha`), the
pacticipant pair and the options. A document's ``metadata`` and the consumer version that published
it are never read, so every consumer version sharing a pact version gets a byte-identical suite
with the same ``sha256:`` digest.

Nothing skipped silently
------------------------
What cannot be replayed is listed under ``unsupported`` **and** reported as a finding: a message
interaction (PFX-3.6), a plugin interaction other than a protobuf-plugin gRPC call (PFX-3.7), a
streaming gRPC method, an interaction with no method or path, a request body that cannot be
decoded. What is compiled more weakly than the pact says is a
``degraded`` finding: an embedded Pact 1 matcher, a matching rule the suite cannot name, a request
generator, an unreadable response body or provider state. What a runner must supply — the provider
states — is an ``info`` finding.

Pure: a parsed pact in, a manifest out. Reading the pact and checking the caller's access live in
:mod:`app.pact_suite_routes`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .change_taxonomy_enum import json_pointer_escape
from .contract_protocols import PROTOCOL_GRPC, PROTOCOL_HTTP
from .contract_suite import (
    CASE_SOURCE_PACT_INTERACTION,
    CODE_NO_CASES_COMPILED,
    CODE_OPERATION_LIMIT_REACHED,
    CODE_OPERATION_NOT_SELECTED,
    CODE_PACT_BODY_UNREADABLE,
    CODE_PACT_EMBEDDED_MATCHER,
    CODE_PACT_GRAPHQL_SELECTIONS_NOT_MAPPED,
    CODE_PACT_GRAPHQL_UNREADABLE,
    CODE_PACT_INTERACTION_MALFORMED,
    CODE_PACT_MATCHING_RULE_UNSUPPORTED,
    CODE_PACT_PLUGIN_INTERACTION,
    CODE_PACT_PLUGIN_PARTIAL,
    CODE_PACT_PROVIDER_STATE,
    CODE_PACT_PROVIDER_STATE_UNREADABLE,
    CODE_PACT_REQUEST_GENERATOR,
    CODE_PACT_RESPONSE_GENERATOR,
    CODE_PACT_SPECIFICATION_ASSUMED,
    CODE_STATUS_UNDECLARED,
    CODE_UNSUPPORTED_OPERATION_KIND,
    CODE_UNSUPPORTED_STREAMING,
    FINDING_DEGRADED,
    FINDING_INFO,
    FINDING_UNSUPPORTED,
    OUTCOME_CLIENT_ERROR,
    OUTCOME_SUCCESS,
    ContractCase,
    ContractCaseExpectation,
    ContractCaseRequest,
    ContractGraphqlRequest,
    ContractPactInteraction,
    ContractRequestParameter,
    ContractRpcRequest,
    ContractSuiteManifest,
    PactGeneratorEntry,
    PactMatchingRuleEntry,
    PactProviderState,
    PactResponseExpectation,
    PactSuiteOptions,
    SuiteApiInfo,
    SuiteFinding,
    SuiteOperation,
    SuitePactInfo,
    SuiteSourceInfo,
    SuiteUnsupportedOperation,
    _case_id,
    _sorted_findings,
    _suite_counts,
    manifest_digest,
)
from .pact_contract_import import interaction_is_http, pact_specification_version
from .pact_graphql import read_graphql_request
from .pact_interaction_reader import as_dict, media_type_of, read_body, read_headers, read_query
from .pact_matching_rules import MatchingRule, parse_matching_rules, parse_path
from .pact_plugin_grpc import (
    CODE_GRPC_STREAMING,
    DescriptorCatalog,
    GrpcPluginCall,
    int64_matcher,
    is_grpc_plugin_interaction,
    plugin_names,
    read_grpc_interaction,
    rename_rule_path,
)
from .pact_publication import pact_content_sha

__all__ = [
    "KNOWN_MATCHERS",
    "ORIGIN_PACT",
    "STATUS_CLASSES",
    "compile_pact_suite",
]

#: ``origin`` of a request parameter whose value the consumer recorded in a pact.
ORIGIN_PACT = "pact"

#: Matchers of Pact specifications 2–4, lowercase as :func:`parse_matching_rules` reports them.
#: A rule naming anything else is carried but reported, because no verifier will know it either.
KNOWN_MATCHERS = frozenset(
    {
        "type",
        "mintype",
        "maxtype",
        "minmaxtype",
        "equality",
        "regex",
        "include",
        "integer",
        "number",
        "decimal",
        "boolean",
        "null",
        "notempty",
        "date",
        "time",
        "timestamp",
        "datetime",
        "semver",
        "values",
        "eachkey",
        "eachvalue",
        "arraycontains",
        "contenttype",
        "statuscode",
    }
)

#: Pact 4 ``statusCode`` rule classes, as the status tokens the runner matches
#: (:func:`app.contract_runner.status_code_matches`).
STATUS_CLASSES: Dict[str, Tuple[str, ...]] = {
    "information": ("1XX",),
    "success": ("2XX",),
    "redirect": ("3XX",),
    "clienterror": ("4XX",),
    "servererror": ("5XX",),
    "nonerror": ("1XX", "2XX", "3XX"),
    "error": ("4XX", "5XX"),
}

#: Rule categories a matcher can be filed under.
_RULE_CATEGORIES = frozenset({"body", "header", "query", "path", "status"})

#: Generator categories whose value is the generator itself rather than a map of paths.
_SINGLE_GENERATOR_CATEGORIES = frozenset({"path", "status", "method"})

#: The status Pact mock servers answer when an interaction records none.
_DEFAULT_STATUS = 200


@dataclass
class _PactCompilation:
    """Run state of one pact compilation.

    Attributes:
        consumer: The consumer pacticipant.
        provider: The provider pacticipant.
        v4: Whether the pact declares specification 4.
        cases: Compiled cases, in compilation order.
        findings: Everything reported.
        unsupported: Interactions no case covers.
        dropped: Interactions left out by ``max_interactions``.
        states: Each provider state named, with the pointer of its first use.
        catalog: The protobuf descriptors the pact files (read only for plugin interactions).
        graphql_pointers: Pointers of the interactions compiled as GraphQL operations.
    """

    consumer: str
    provider: str
    v4: bool
    cases: List[ContractCase] = field(default_factory=list)
    findings: List[SuiteFinding] = field(default_factory=list)
    unsupported: List[SuiteUnsupportedOperation] = field(default_factory=list)
    dropped: int = 0
    states: Dict[str, str] = field(default_factory=dict)
    catalog: Optional[DescriptorCatalog] = None
    graphql_pointers: List[str] = field(default_factory=list)

    def report(
        self,
        code: str,
        level: str,
        message: str,
        *,
        operation_key: Optional[str] = None,
        pointer: Optional[str] = None,
    ) -> None:
        """Record a finding.

        Args:
            code: A code from :data:`app.contract_suite.SUITE_FINDING_CODES`.
            level: ``unsupported``, ``degraded`` or ``info``.
            message: What was not compiled, or compiled weakly, and why.
            operation_key: The operation the finding concerns, if any.
            pointer: JSON Pointer into the pact document.
        """
        self.findings.append(
            SuiteFinding(
                code=code, level=level, message=message, operation_key=operation_key, pointer=pointer
            )
        )

    def leave_out(self, key: str, code: str, reason: str, pointer: str) -> None:
        """List an interaction under ``unsupported`` and report it.

        Args:
            key: The interaction's operation key (``GET /x``) or, without one, its pointer.
            code: Why it cannot be compiled.
            reason: One sentence saying so.
            pointer: JSON Pointer of the interaction.
        """
        self.unsupported.append(SuiteUnsupportedOperation(operation_key=key, code=code, reason=reason))
        self.report(code, FINDING_UNSUPPORTED, reason, operation_key=key, pointer=pointer)


# =============================================================================================
# Entry point
# =============================================================================================


def compile_pact_suite(
    document: Mapping[str, Any],
    *,
    consumer: str,
    provider: str,
    options: Optional[PactSuiteOptions] = None,
    source: Optional[SuiteSourceInfo] = None,
) -> ContractSuiteManifest:
    """Compile a parsed pact into a contract-suite manifest.

    Args:
        document: The parsed Pact document (specification 1–4).
        consumer: The consumer pacticipant's name, as the caller resolved it. The document's own
            ``consumer`` block is not read: it is not part of the pact version's content address.
        provider: The provider pacticipant's name, likewise.
        options: Which interactions to compile. ``None`` compiles every one.
        source: Provenance echoed into the manifest (``kind: pact``). It must name only the
            pacticipant pair and the pact version, or the digest would vary between consumer
            versions sharing the content.

    Returns:
        The manifest, its ``digest`` computed over its own canonical bytes. Never raises for a
        pact it cannot fully express: what cannot be compiled becomes a finding.
    """
    resolved = (options or PactSuiteOptions()).normalized()
    specification = pact_specification_version(document)
    compilation = _PactCompilation(
        consumer=consumer,
        provider=provider,
        v4=(specification or "").startswith("4"),
        catalog=DescriptorCatalog(document),
    )
    _report_specification(compilation, specification)

    entries = _entries(document)
    selected = _select(compilation, entries, resolved)
    for index, pointer, kind, interaction in selected:
        if kind == "interactions" and isinstance(interaction, dict) and is_grpc_plugin_interaction(interaction):
            _compile_grpc_interaction(compilation, index, pointer, interaction)
            continue
        if kind == "messages" or (isinstance(interaction, dict) and not interaction_is_http(interaction)):
            _leave_out_message(compilation, pointer, interaction)
            continue
        _compile_interaction(compilation, index, pointer, interaction)

    _report_states(compilation)
    _report_graphql(compilation)
    if not compilation.cases:
        compilation.report(
            CODE_NO_CASES_COMPILED,
            FINDING_DEGRADED,
            "the pact yields no HTTP or gRPC interaction this suite can replay",
        )

    cases = sorted(compilation.cases, key=lambda case: (case.operation_key, _case_index(case)))
    findings = _sorted_findings(compilation.findings)
    operations = _operations(cases)
    # A suite of gRPC calls only is a gRPC suite (it runs on a grpc or connect target); anything
    # with an HTTP case stays http, and the verifier holds back what the target cannot speak.
    protocol = PROTOCOL_GRPC if cases and all(case.protocol == PROTOCOL_GRPC for case in cases) else PROTOCOL_HTTP
    manifest = ContractSuiteManifest(
        options=None,
        protocol=protocol,
        api=SuiteApiInfo(
            name=provider,
            title=f"Pact: {consumer} → {provider}",
            version=None,
            format=f"pact-{specification}" if specification else "pact",
            paradigm="rpc" if protocol == PROTOCOL_GRPC else "rest",
            protocol=protocol,
            servers=[],
        ),
        source=source,
        pact=SuitePactInfo(
            consumer=consumer,
            provider=provider,
            pact_version_sha=pact_content_sha(document),
            specification_version=specification,
            interaction_count=len(entries),
            options=resolved,
        ),
        operations=operations,
        cases=cases,
        schemas={},
        unsupported=sorted(compilation.unsupported, key=lambda item: item.operation_key),
        findings=findings,
        counts=_suite_counts(
            cases,
            operations_compiled=len(operations),
            operations_skipped=compilation.dropped + len(compilation.unsupported),
            findings=len(findings),
        ),
    )
    return manifest.model_copy(update={"digest": manifest_digest(manifest)})


# =============================================================================================
# Selection
# =============================================================================================


def _entries(document: Mapping[str, Any]) -> List[Tuple[int, str, str, Any]]:
    """Every interaction and message of the pact, in document order.

    Args:
        document: The parsed pact.

    Returns:
        ``(index, pointer, array name, entry)`` for each entry of ``interactions`` and then of
        ``messages`` (a Pact 3 message pact).
    """
    found: List[Tuple[int, str, str, Any]] = []
    for kind in ("interactions", "messages"):
        entries = document.get(kind)
        if isinstance(entries, list):
            found.extend((index, f"/{kind}/{index}", kind, entry) for index, entry in enumerate(entries))
    return found


def _names(entry: Any) -> Set[str]:
    """The names an interaction can be selected by: its description and its Pact 4 key."""
    data = as_dict(entry)
    return {
        value.strip()
        for value in (data.get("description"), data.get("key"))
        if isinstance(value, str) and value.strip()
    }


def _select(
    compilation: _PactCompilation,
    entries: Sequence[Tuple[int, str, str, Any]],
    options: PactSuiteOptions,
) -> List[Tuple[int, str, str, Any]]:
    """Apply the ``interactions`` filter and the ``max_interactions`` cap.

    Args:
        compilation: The run state; a name matching nothing and the truncation are reported.
        entries: Every interaction and message.
        options: The normalized options.

    Returns:
        The entries to compile, in document order.
    """
    chosen = list(entries)
    if options.interactions is not None:
        wanted = set(options.interactions)
        chosen = [entry for entry in entries if _names(entry[3]) & wanted]
        matched = set().union(*(_names(entry[3]) for entry in chosen)) if chosen else set()
        for name in sorted(wanted - matched):
            compilation.report(
                CODE_OPERATION_NOT_SELECTED,
                FINDING_INFO,
                f"no interaction of the pact is described or keyed '{name}'",
            )
    if len(chosen) > options.max_interactions:
        compilation.dropped = len(chosen) - options.max_interactions
        compilation.report(
            CODE_OPERATION_LIMIT_REACHED,
            FINDING_DEGRADED,
            f"the pact selects {len(chosen)} interactions; only the first "
            f"{options.max_interactions} were compiled (max_interactions)",
        )
        chosen = chosen[: options.max_interactions]
    return chosen


# =============================================================================================
# One interaction
# =============================================================================================


def _description(interaction: Mapping[str, Any], pointer: str) -> str:
    """The interaction's description, or its pointer when it has none."""
    description = interaction.get("description")
    return description.strip() if isinstance(description, str) and description.strip() else pointer


def _leave_out_message(compilation: _PactCompilation, pointer: str, interaction: Any) -> None:
    """List a message (or other non-HTTP) interaction under ``unsupported``.

    Args:
        compilation: The run state.
        pointer: JSON Pointer of the entry.
        interaction: The entry.
    """
    data = as_dict(interaction)
    declared = data.get("type")
    kind = declared.strip() if isinstance(declared, str) and declared.strip() else "message"
    compilation.leave_out(
        pointer,
        CODE_UNSUPPORTED_OPERATION_KIND,
        f"'{_description(data, pointer)}' is a {kind} interaction, which carries no HTTP "
        "exchange to replay; message pacts are verified against AsyncAPI (PFX-3.6)",
        pointer,
    )


def _is_plugin(interaction: Mapping[str, Any]) -> bool:
    """Whether a Pact 4 interaction is driven by a plugin (gRPC, protobuf, CSV …).

    Args:
        interaction: The interaction.

    Returns:
        True when it carries plugin configuration or markup, or a transport other than HTTP.
    """
    if interaction.get("pluginConfiguration") or interaction.get("interactionMarkup"):
        return True
    transport = interaction.get("transport")
    return isinstance(transport, str) and transport.strip().lower() not in ("", "http", "https")


def _compile_interaction(
    compilation: _PactCompilation, index: int, pointer: str, raw: Any
) -> None:
    """Compile one HTTP interaction into a case, or report why it cannot be.

    Args:
        compilation: The run state, filled in place.
        index: Position of the interaction in ``interactions``.
        pointer: Its JSON Pointer.
        raw: The interaction.
    """
    if not isinstance(raw, dict):
        compilation.leave_out(
            pointer, CODE_PACT_INTERACTION_MALFORMED, "the interaction is not an object", pointer
        )
        return
    interaction: Mapping[str, Any] = raw
    description = _description(interaction, pointer)
    request = as_dict(interaction.get("request"))
    response = as_dict(interaction.get("response"))
    request_pointer, response_pointer = f"{pointer}/request", f"{pointer}/response"
    method = request.get("method")
    path = request.get("path", "/")
    if not isinstance(method, str) or not method.strip() or not isinstance(path, str) or not path.strip():
        compilation.leave_out(
            pointer,
            CODE_PACT_INTERACTION_MALFORMED,
            f"'{description}' records no request method and path, so there is nothing to send",
            pointer,
        )
        return
    method = method.strip().upper()
    path = path.strip()
    key = f"{method} {path}"
    if _is_plugin(interaction):
        names = ", ".join(plugin_names(interaction)) or "an unnamed plugin"
        compilation.leave_out(
            key,
            CODE_PACT_PLUGIN_INTERACTION,
            f"'{description}' is a plugin interaction ({names}); its exchange is defined by the "
            "plugin, not by the HTTP request it records — only gRPC calls recorded by the "
            "protobuf plugin are replayed",
            pointer,
        )
        return

    body = read_body(request, request_pointer, compilation.v4)
    if body.problem:
        compilation.leave_out(
            key,
            CODE_PACT_BODY_UNREADABLE,
            f"the request body of '{description}' cannot be sent: {body.problem}",
            pointer,
        )
        return
    if body.embedded:
        _report_embedded(compilation, key, body.pointer)

    headers = read_headers(request)
    parameters = _parameters(request, headers)
    request_media = body.media_type or media_type_of(headers.get("content-type", ("", ""))[1])
    graphql = _graphql(
        compilation, key, method, path, body.value if body.present else None, request_media, request, pointer
    )
    if graphql is _LEFT_OUT:
        return
    expected = _response(compilation, key, response, response_pointer)
    request_rules = _rules(compilation, key, request, request_pointer)
    states = _provider_states(compilation, key, interaction, pointer)
    status_codes, status_declared = _status_tokens(compilation, key, expected)
    outcome = (
        OUTCOME_CLIENT_ERROR
        if status_codes and all(code.upper().startswith("4") for code in status_codes)
        else OUTCOME_SUCCESS
    )
    pending = interaction.get("pending") is True
    interaction_key = interaction.get("key") if isinstance(interaction.get("key"), str) else None
    type_name = interaction.get("type")

    pact = ContractPactInteraction(
        index=index,
        key=interaction_key,
        description=description,
        pointer=pointer,
        interaction_type=type_name.strip() if isinstance(type_name, str) and type_name.strip() else "http",
        pending=pending,
        provider_states=states,
        request_matching_rules=request_rules,
        request_generators=_generators(compilation, key, request, request_pointer, side="request"),
        response=expected,
    )
    given = f" given {', '.join(repr(state.name) for state in states)}" if states else ""
    compilation.cases.append(
        ContractCase(
            case_id=_case_id(key, CASE_SOURCE_PACT_INTERACTION, interaction_key or description, pointer, description),
            operation_key=key,
            operation_name=description,
            source=CASE_SOURCE_PACT_INTERACTION,
            source_detail=interaction_key or description,
            source_pointer=pointer,
            title=description,
            description=(
                f"Replay '{description}'{given} as {compilation.consumer} recorded it: "
                f"{key} → {', '.join(status_codes)}."
            ),
            synthetic=False,
            protocol=PROTOCOL_HTTP,
            request=ContractCaseRequest(
                method=method,
                path_template=path,
                path=path,
                parameters=parameters,
                has_body=body.present,
                body=body.value if body.present else None,
                media_type=request_media if body.present else None,
            ),
            graphql=graphql if isinstance(graphql, ContractGraphqlRequest) else None,
            pact=pact,
            expect=ContractCaseExpectation(
                outcome=outcome,
                status_codes=status_codes,
                status_declared=status_declared,
                response_schema_id=None,
                reason=(
                    f"{compilation.consumer} accepts this response; the body, headers and status "
                    "are compared under the pact's matching rules (`pact.response`)."
                ),
            ),
            tags=_tags(pending, "graphql" if isinstance(graphql, ContractGraphqlRequest) else None),
        )
    )


def _tags(pending: bool, kind: Optional[str]) -> List[str]:
    """The tags of a pact case: ``pact``, then its kind (``graphql``, ``grpc``), then ``pending``."""
    return ["pact", *([kind] if kind else []), *(["pending"] if pending else [])]


#: Returned by :func:`_graphql` when the interaction was listed unsupported (a subscription).
_LEFT_OUT = object()


def _graphql(
    compilation: _PactCompilation,
    key: str,
    method: str,
    path: str,
    body: Any,
    media_type: Optional[str],
    request: Mapping[str, Any],
    pointer: str,
) -> Any:
    """Read the GraphQL operation an HTTP interaction carries, if it carries one (PFX-3.7).

    Args:
        compilation: The run state; an unreadable operation is reported, a subscription left out.
        key: The case's operation key.
        method: The upper-cased HTTP method.
        path: The recorded path.
        body: The decoded request body, or ``None``.
        media_type: The body's media type.
        request: The pact ``request`` object.
        pointer: The interaction's JSON Pointer.

    Returns:
        The :class:`ContractGraphqlRequest` to attach; ``None`` for a request that is not GraphQL
        (or is, unreadably — then reported and replayed as plain HTTP); :data:`_LEFT_OUT` when the
        interaction was listed unsupported.
    """
    operation, problem = read_graphql_request(method, path, body, media_type, read_query(request))
    if problem:
        compilation.report(
            CODE_PACT_GRAPHQL_UNREADABLE,
            FINDING_DEGRADED,
            f"the request carries a GraphQL operation that cannot be read: {problem}; it is "
            f"replayed as plain HTTP, and {method} decides whether it is mutating",
            operation_key=key,
            pointer=f"{pointer}/request",
        )
        return None
    if operation is None:
        return None
    if operation.operation_type == "subscription":
        compilation.leave_out(
            key,
            CODE_UNSUPPORTED_STREAMING,
            f"the GraphQL operation '{operation.operation_name or operation.field}' is a subscription; "
            "a request/response replay cannot express a stream",
            pointer,
        )
        return _LEFT_OUT
    compilation.graphql_pointers.append(pointer)
    return ContractGraphqlRequest(
        query=operation.query,
        variables=operation.variables,
        operationName=operation.operation_name,
        operation_type=operation.operation_type,
        field=operation.field,
    )


def _report_graphql(compilation: _PactCompilation) -> None:
    """Report, once, that GraphQL selections are not mapped onto consumer contracts yet.

    Args:
        compilation: The run state.
    """
    if not compilation.graphql_pointers:
        return
    count = len(compilation.graphql_pointers)
    compilation.report(
        CODE_PACT_GRAPHQL_SELECTIONS_NOT_MAPPED,
        FINDING_INFO,
        f"{count} interaction{'s' if count != 1 else ''} carry a GraphQL operation, verified as "
        "GraphQL-over-HTTP; the fields they select are not mapped onto the consumer-contract "
        "model, which awaits GraphQL consumer contracts (XPC-1.6, #5733)",
        pointer=compilation.graphql_pointers[0],
    )


# =============================================================================================
# A gRPC call recorded by the protobuf plugin (PFX-3.7)
# =============================================================================================


def _compile_grpc_interaction(
    compilation: _PactCompilation, index: int, pointer: str, interaction: Mapping[str, Any]
) -> None:
    """Compile one protobuf-plugin gRPC interaction into a ``grpc`` case, or report why not.

    Args:
        compilation: The run state, filled in place.
        index: Position of the interaction in ``interactions``.
        pointer: Its JSON Pointer.
        interaction: The interaction.
    """
    description = _description(interaction, pointer)
    assert compilation.catalog is not None
    call, problem = read_grpc_interaction(interaction, pointer, compilation.catalog)
    if call is None:
        assert problem is not None
        compilation.leave_out(
            pointer,
            CODE_UNSUPPORTED_STREAMING if problem.code == CODE_GRPC_STREAMING else CODE_PACT_PLUGIN_INTERACTION,
            f"the gRPC interaction '{description}' cannot be replayed ({problem.code}): {problem.reason}",
            pointer,
        )
        return
    key = f"{call.service}.{call.method}"
    for where, note in call.notes:
        compilation.report(CODE_PACT_PLUGIN_PARTIAL, FINDING_DEGRADED, note, operation_key=key, pointer=where)
    if call.expect_message:
        compilation.report(
            CODE_PACT_PLUGIN_PARTIAL,
            FINDING_DEGRADED,
            f"the recorded grpc-message {call.expect_message!r} is not compared; only the status is",
            operation_key=key,
            pointer=f"{call.response_pointer}/metadata",
        )

    request = as_dict(interaction.get("request"))
    responses = interaction.get("response")
    response = as_dict(responses[0]) if isinstance(responses, list) and responses else as_dict(responses)
    request_pointer = f"{pointer}/request"
    states = _provider_states(compilation, key, interaction, pointer)
    pending = interaction.get("pending") is True
    interaction_key = interaction.get("key") if isinstance(interaction.get("key"), str) else None
    expected = PactResponseExpectation(
        status=None,
        headers={},
        has_body=call.has_body,
        body=call.body if call.has_body else None,
        media_type="application/json" if call.has_body else None,
        body_pointer=f"{call.response_pointer}/contents/content" if call.has_body else None,
        matching_rules=_grpc_rules(compilation, key, response, call.response_pointer, call),
        generators=_generators(compilation, key, response, call.response_pointer, side="response"),
    )
    pact = ContractPactInteraction(
        index=index,
        key=interaction_key,
        description=description,
        pointer=pointer,
        interaction_type="Synchronous/Messages",
        pending=pending,
        provider_states=states,
        request_matching_rules=_grpc_rules(compilation, key, request, request_pointer, None),
        request_generators=_generators(compilation, key, request, request_pointer, side="request"),
        response=expected,
    )
    given = f" given {', '.join(repr(state.name) for state in states)}" if states else ""
    success = call.expect_code == "ok"
    compilation.cases.append(
        ContractCase(
            case_id=_case_id(key, CASE_SOURCE_PACT_INTERACTION, interaction_key or description, pointer, description),
            operation_key=key,
            operation_name=call.method,
            source=CASE_SOURCE_PACT_INTERACTION,
            source_detail=interaction_key or description,
            source_pointer=pointer,
            title=description,
            description=(
                f"Replay '{description}'{given} as {compilation.consumer} recorded it: "
                f"{call.procedure} → {call.expect_code}."
            ),
            synthetic=False,
            protocol=PROTOCOL_GRPC,
            request=ContractCaseRequest(
                method="POST",
                path_template=call.procedure,
                path=call.procedure,
                parameters=[],
                has_body=True,
                body=call.message,
                media_type="application/json",
            ),
            rpc=ContractRpcRequest(
                service=call.service,
                method=call.method,
                procedure=call.procedure,
                input_type=call.input_type,
                output_type=call.output_type,
                message=call.message,
                idempotency_level=call.idempotency_level,
                expect_code=call.expect_code,
            ),
            pact=pact,
            expect=ContractCaseExpectation(
                outcome=OUTCOME_SUCCESS if success else OUTCOME_CLIENT_ERROR,
                status_codes=["200"] if success else ["4XX", "5XX"],
                status_declared=False,
                response_schema_id=None,
                reason=(
                    f"{compilation.consumer} expects status `{call.expect_code}`"
                    + (
                        " and a reply matching the recorded message under the pact's matching rules "
                        "(`pact.response`)."
                        if call.has_body
                        else "."
                    )
                ),
            ),
            tags=_tags(pending, "grpc"),
        )
    )


def _grpc_rules(
    compilation: _PactCompilation,
    key: str,
    section: Mapping[str, Any],
    pointer: str,
    call: Optional[GrpcPluginCall],
) -> List[PactMatchingRuleEntry]:
    """Read a plugin request's or response's matching rules.

    Body rules are filed under ``body`` or (Pact 4 messages) ``content``. On the response they are
    renamed from ``.proto`` field names to protobuf-JSON names, so they select fields of the reply
    the runner decodes; metadata rules are carried but reported, since metadata is not compared.

    Args:
        compilation: The run state.
        key: The case's operation key.
        section: The plugin ``request`` or ``response`` object.
        pointer: Its JSON Pointer.
        call: The read call, for the response side (its output descriptor); ``None`` for the
            request side, whose rules only describe what the consumer may vary.

    Returns:
        Every rule, the unsupported ones included.
    """
    entries: List[PactMatchingRuleEntry] = []
    for rule in parse_matching_rules(section.get("matchingRules"), f"{pointer}/matchingRules", message=True):
        path, match, matcher = rule.path, rule.kind, dict(rule.matcher)
        if rule.category == "metadata":
            if call is not None:
                compilation.report(
                    CODE_PACT_PLUGIN_PARTIAL,
                    FINDING_DEGRADED,
                    f"the metadata matching rule on '{rule.path}' is carried but not applied: gRPC "
                    "response metadata is not compared",
                    operation_key=key,
                    pointer=rule.pointer,
                )
        elif call is not None and rule.category == "body":
            steps = parse_path(rule.path)
            renamed, int64 = rename_rule_path(steps, call.output_descriptor) if steps is not None else (None, False)
            replacement = int64_matcher(rule.kind, rule.matcher) if int64 else None
            if replacement is not None:
                compilation.report(
                    CODE_PACT_PLUGIN_PARTIAL,
                    FINDING_INFO,
                    f"the {rule.kind} rule at '{rule.path}' names a 64-bit integer field, which "
                    "protobuf-JSON prints as a decimal string; it is applied as a digits-only regex",
                    operation_key=key,
                    pointer=rule.pointer,
                )
                match, matcher = "regex", replacement
            if renamed is None:
                compilation.report(
                    CODE_PACT_MATCHING_RULE_UNSUPPORTED,
                    FINDING_DEGRADED,
                    f"the body matching rule at '{rule.path}' names no field of "
                    f"'{call.output_type}'; it is carried but selects nothing",
                    operation_key=key,
                    pointer=rule.pointer,
                )
            else:
                path = renamed
        if call is not None and rule.category != "metadata":
            problem = _rule_problem(MatchingRule(rule.category, path, match, matcher, rule.pointer))
            if problem:
                compilation.report(
                    CODE_PACT_MATCHING_RULE_UNSUPPORTED,
                    FINDING_DEGRADED,
                    f"the {rule.category} matching rule at '{rule.path or rule.category}' {problem}; "
                    "it is carried but cannot be applied",
                    operation_key=key,
                    pointer=rule.pointer,
                )
        entries.append(
            PactMatchingRuleEntry(
                category=rule.category,
                path=path,
                match=match,
                matcher=matcher,
                combine=rule.combine,
                pointer=rule.pointer,
            )
        )
    return entries


def _case_index(case: ContractCase) -> int:
    """The pact position of a case, for ordering cases within an operation."""
    return case.pact.index if case.pact is not None else 0


def _parameters(
    request: Mapping[str, Any], headers: Mapping[str, Tuple[str, str]]
) -> List[ContractRequestParameter]:
    """The query and header values of a recorded request.

    Args:
        request: The pact ``request`` object.
        headers: Its headers, as :func:`read_headers` returns them.

    Returns:
        One parameter per query value (a repeated name yields one per value, in recorded order)
        and per header, query first, each sorted by name.
    """
    found: List[ContractRequestParameter] = []
    query = read_query(request)
    for name in sorted(query):
        found.extend(
            ContractRequestParameter(name=name, location="query", value=value, origin=ORIGIN_PACT, required=True)
            for value in query[name]
        )
    for lower in sorted(headers):
        name, value = headers[lower]
        found.append(
            ContractRequestParameter(name=name, location="header", value=value, origin=ORIGIN_PACT, required=True)
        )
    return found


def _response(
    compilation: _PactCompilation, key: str, response: Mapping[str, Any], pointer: str
) -> PactResponseExpectation:
    """Read the response the consumer expects.

    Args:
        compilation: The run state; an unreadable body or embedded matcher is reported.
        key: The case's operation key.
        response: The pact ``response`` object.
        pointer: Its JSON Pointer.

    Returns:
        The expectation, rules and generators included.
    """
    body = read_body(response, pointer, compilation.v4)
    rules = _rules(compilation, key, response, pointer)
    if body.problem and _has_root_content_type_rule(rules):
        compilation.report(
            CODE_PACT_BODY_UNREADABLE,
            FINDING_INFO,
            f"the expected response body cannot be decoded ({body.problem}); it is judged by its "
            "contentType rule, which inspects the bytes the provider returns",
            operation_key=key,
            pointer=body.pointer,
        )
    elif body.problem:
        compilation.report(
            CODE_PACT_BODY_UNREADABLE,
            FINDING_DEGRADED,
            f"the expected response body cannot be decoded ({body.problem}); only the status and "
            "headers can be compared",
            operation_key=key,
            pointer=body.pointer,
        )
    elif body.embedded:
        _report_embedded(compilation, key, body.pointer)
    headers = read_headers(response)
    status = response.get("status")
    return PactResponseExpectation(
        status=status if isinstance(status, int) and not isinstance(status, bool) else None,
        headers={name: value for name, value in sorted(headers.values())},
        # An explicitly empty body ("body": null, or a Pact 4 empty content) is recorded as "" so a
        # verifier requires an empty response body instead of accepting any (PFX-3.4).
        has_body=body.present or body.empty,
        body="" if body.empty else body.value if body.present and not body.problem else None,
        media_type=body.media_type or media_type_of(headers.get("content-type", ("", ""))[1]),
        body_pointer=body.pointer or None,
        matching_rules=rules,
        generators=_generators(compilation, key, response, pointer, side="response"),
    )


def _has_root_content_type_rule(rules: Sequence[PactMatchingRuleEntry]) -> bool:
    """Whether a response's rules judge its whole body by content type (``contentType`` on ``$``).

    Args:
        rules: The response's matching rules.

    Returns:
        ``True`` when a body rule on ``$`` is a ``contentType`` matcher.
    """
    return any(rule.category == "body" and rule.path.strip() == "$" and rule.match == "contenttype" for rule in rules)


def _status_tokens(
    compilation: _PactCompilation, key: str, expected: PactResponseExpectation
) -> Tuple[List[str], bool]:
    """The status tokens a case expects.

    A Pact 4 ``statusCode`` rule widens the recorded status to a class (``success`` → ``2XX``)
    or a list of codes; otherwise the recorded status is exact. A response with no status is
    read as 200, as Pact mock servers answer, and reported.

    Args:
        compilation: The run state.
        key: The case's operation key.
        expected: The expected response.

    Returns:
        ``(tokens, declared)`` — ``declared`` is false only when the pact records no status.
    """
    for rule in expected.matching_rules:
        if rule.category != "status" or rule.match != "statuscode":
            continue
        tokens = _status_rule_tokens(rule.matcher.get("status"))
        if tokens:
            return tokens, True
        compilation.report(
            CODE_PACT_MATCHING_RULE_UNSUPPORTED,
            FINDING_DEGRADED,
            f"the statusCode rule's status {rule.matcher.get('status')!r} names no status class or "
            "code; the recorded status is expected exactly",
            operation_key=key,
            pointer=rule.pointer,
        )
    if expected.status is None:
        compilation.report(
            CODE_STATUS_UNDECLARED,
            FINDING_DEGRADED,
            f"the pact records no response status; {_DEFAULT_STATUS} is expected, as a Pact mock "
            "server answers",
            operation_key=key,
        )
        return [str(_DEFAULT_STATUS)], False
    return [str(expected.status)], True


def _status_rule_tokens(status: Any) -> List[str]:
    """Translate a ``statusCode`` rule's ``status`` into status tokens.

    Args:
        status: A class name (``success``, ``clientError`` …) or a list of codes.

    Returns:
        The tokens, sorted and distinct, or an empty list for a value that names nothing.
    """
    if isinstance(status, str):
        return list(STATUS_CLASSES.get(status.strip().lower(), ()))
    if isinstance(status, list) and status:
        codes = {str(code) for code in status if isinstance(code, int) and not isinstance(code, bool)}
        if len(codes) == len(status):
            return sorted(codes)
    return []


# =============================================================================================
# Rules, generators, states
# =============================================================================================


def _rules(
    compilation: _PactCompilation, key: str, section: Mapping[str, Any], pointer: str
) -> List[PactMatchingRuleEntry]:
    """Read a request's or response's matching rules, reporting the ones no verifier can apply.

    Args:
        compilation: The run state.
        key: The case's operation key.
        section: The pact ``request`` or ``response``.
        pointer: Its JSON Pointer.

    Returns:
        Every rule, in a stable order — the unsupported ones included, so nothing is lost.
    """
    entries: List[PactMatchingRuleEntry] = []
    for rule in parse_matching_rules(section.get("matchingRules"), f"{pointer}/matchingRules"):
        problem = _rule_problem(rule)
        if problem:
            compilation.report(
                CODE_PACT_MATCHING_RULE_UNSUPPORTED,
                FINDING_DEGRADED,
                f"the {rule.category} matching rule at '{rule.path or rule.category}' {problem}; it "
                "is carried but cannot be applied",
                operation_key=key,
                pointer=rule.pointer,
            )
        entries.append(
            PactMatchingRuleEntry(
                category=rule.category,
                path=rule.path,
                match=rule.kind,
                matcher=dict(rule.matcher),
                combine=rule.combine,
                pointer=rule.pointer,
            )
        )
    return entries


def _rule_problem(rule: MatchingRule) -> Optional[str]:
    """Why a matching rule cannot be applied, or ``None`` when it can.

    Args:
        rule: The rule.

    Returns:
        A clause naming the problem: an unknown location, an unknown matcher, or a body path
        that is not a JSONPath a verifier reads.
    """
    if rule.category not in _RULE_CATEGORIES:
        return "is filed under a part of the message Pact does not define"
    if rule.kind not in KNOWN_MATCHERS:
        return f"uses the matcher '{rule.kind}', which no Pact specification defines"
    if rule.category == "body" and parse_path(rule.path) is None:
        return "has a path that is not a JSONPath"
    return None


def _generators(
    compilation: _PactCompilation,
    key: str,
    section: Mapping[str, Any],
    pointer: str,
    *,
    side: str,
) -> List[PactGeneratorEntry]:
    """Read a request's or response's generators, and report each one.

    Args:
        compilation: The run state.
        key: The case's operation key.
        section: The pact ``request`` or ``response``.
        pointer: Its JSON Pointer.
        side: ``request`` or ``response``.

    Returns:
        Every generator, sorted by category and path.
    """
    generators = section.get("generators")
    if not isinstance(generators, dict):
        return []
    entries: List[PactGeneratorEntry] = []
    for category in sorted(str(name) for name in generators):
        value = generators[category]
        where = f"{pointer}/generators/{json_pointer_escape(category)}"
        if category in _SINGLE_GENERATOR_CATEGORIES or not isinstance(value, dict) or "type" in value:
            located: List[Tuple[str, str, Any]] = [("", where, value)]
        else:
            located = [
                (str(path), f"{where}/{json_pointer_escape(str(path))}", value[path])
                for path in sorted(value, key=str)
            ]
        for path, entry_pointer, generator in located:
            data = as_dict(generator)
            kind = data.get("type") if isinstance(data.get("type"), str) else None
            entries.append(
                PactGeneratorEntry(category=category, path=path, type=kind, generator=dict(data), pointer=entry_pointer)
            )
            _report_generator(compilation, key, side, category, kind, entry_pointer)
    return entries


def _report_generator(
    compilation: _PactCompilation,
    key: str,
    side: str,
    category: str,
    kind: Optional[str],
    pointer: str,
) -> None:
    """Report one generator: a request one weakens the replay, a response one is ignored.

    Args:
        compilation: The run state.
        key: The case's operation key.
        side: ``request`` or ``response``.
        category: Where the generator applies.
        kind: Its type.
        pointer: Its JSON Pointer.
    """
    name = kind or "unnamed"
    if side == "response":
        compilation.report(
            CODE_PACT_RESPONSE_GENERATOR,
            FINDING_INFO,
            f"the response {category} generator '{name}' is ignored on verification; the "
            "matching rules decide what the provider may return",
            operation_key=key,
            pointer=pointer,
        )
        return
    detail = (
        "its value comes from the provider state's setup (PFX-3.3)"
        if name == "ProviderState"
        else "a verifier would substitute a generated value"
    )
    compilation.report(
        CODE_PACT_REQUEST_GENERATOR,
        FINDING_DEGRADED,
        f"the request {category} generator '{name}' is not applied: the suite sends the recorded "
        f"example, and {detail}",
        operation_key=key,
        pointer=pointer,
    )


def _provider_states(
    compilation: _PactCompilation, key: str, interaction: Mapping[str, Any], pointer: str
) -> List[PactProviderState]:
    """Read an interaction's provider states in any specification version.

    Pact 1 writes ``provider_state`` or ``providerState`` (one name), Pact 3 and 4 write
    ``providerStates`` (a list of ``{name, params}``).

    Args:
        compilation: The run state; every state name is remembered, an unreadable one reported.
        key: The case's operation key.
        interaction: The interaction.
        pointer: Its JSON Pointer.

    Returns:
        The states, in recorded order.
    """
    states: List[PactProviderState] = []
    listed = interaction.get("providerStates")
    if isinstance(listed, list):
        for position, entry in enumerate(listed):
            where = f"{pointer}/providerStates/{position}"
            data = as_dict(entry)
            name = data.get("name")
            if not isinstance(name, str) or not name.strip():
                compilation.report(
                    CODE_PACT_PROVIDER_STATE_UNREADABLE,
                    FINDING_DEGRADED,
                    "a provider state has no name; the interaction is replayed without it",
                    operation_key=key,
                    pointer=where,
                )
                continue
            params = data.get("params")
            states.append(PactProviderState(name=name.strip(), params=params if isinstance(params, dict) else {}))
            compilation.states.setdefault(name.strip(), where)
        return states
    for spelling in ("providerState", "provider_state"):
        name = interaction.get(spelling)
        if isinstance(name, str) and name.strip():
            compilation.states.setdefault(name.strip(), f"{pointer}/{spelling}")
            return [PactProviderState(name=name.strip())]
    return states


def _report_states(compilation: _PactCompilation) -> None:
    """Report each provider state once: the runner must set it up before its interactions.

    Args:
        compilation: The run state.
    """
    for name in sorted(compilation.states):
        compilation.report(
            CODE_PACT_PROVIDER_STATE,
            FINDING_INFO,
            f"the provider must be put in the state '{name}' before the interactions that name it "
            "are replayed; the suite carries the state, not its setup",
            pointer=compilation.states[name],
        )


def _report_embedded(compilation: _PactCompilation, key: str, pointer: str) -> None:
    """Report a body whose Pact 1 embedded matchers were removed.

    Args:
        compilation: The run state.
        key: The case's operation key.
        pointer: JSON Pointer of the body.
    """
    compilation.report(
        CODE_PACT_EMBEDDED_MATCHER,
        FINDING_DEGRADED,
        "the body embeds Pact 1 matchers (`json_class` / `pact:matcher:type`); the example values "
        "are kept but the embedded rules are not carried",
        operation_key=key,
        pointer=pointer,
    )


def _report_specification(compilation: _PactCompilation, specification: Optional[str]) -> None:
    """Report a missing or unknown specification version.

    Args:
        compilation: The run state.
        specification: The version the pact declares, if any.
    """
    if specification is None:
        compilation.report(
            CODE_PACT_SPECIFICATION_ASSUMED,
            FINDING_INFO,
            "the pact declares no specification version; it is read in the Pact 1–3 shapes",
        )
        return
    major = specification.split(".", 1)[0]
    if major not in ("1", "2", "3", "4"):
        compilation.report(
            CODE_PACT_SPECIFICATION_ASSUMED,
            FINDING_DEGRADED,
            f"the pact declares specification {specification}, which this compiler does not know; "
            "it is read in the Pact 1–3 shapes",
        )


# =============================================================================================
# Assembly
# =============================================================================================


def _operations(cases: Sequence[ContractCase]) -> List[SuiteOperation]:
    """One operation summary per distinct ``METHOD path`` (or gRPC ``package.Service.Method``), sorted.

    Args:
        cases: The compiled cases, sorted by operation key.

    Returns:
        The summaries.
    """
    grouped: Dict[str, List[ContractCase]] = {}
    for case in cases:
        grouped.setdefault(case.operation_key, []).append(case)
    summaries: List[SuiteOperation] = []
    for key in sorted(grouped):
        first = grouped[key][0]
        media = sorted({case.request.media_type for case in grouped[key] if case.request.media_type})
        summaries.append(
            SuiteOperation(
                key=key,
                name=key,
                service_key=first.rpc.service if first.rpc is not None else None,
                http_method=first.request.method,
                http_path=first.request.path_template,
                deprecated=False,
                tags=["pact", "grpc"] if first.rpc is not None else ["pact"],
                case_count=len(grouped[key]),
                request_media_type=media[0] if media else None,
            )
        )
    return summaries
