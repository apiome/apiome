"""Execute gRPC-family contract cases over Connect or native gRPC — XPC-3.2 (#5742).

A suite compiled by :mod:`app.contract_suite_rpc` is stamped ``grpc`` and runs on a target whose
``protocol`` is either ``connect`` or ``grpc``. The cases are identical; this module supplies the
two transports and the one judge they share.

Transports
----------
* **Connect** (:class:`ConnectTransport`) — every case is an HTTP ``POST`` of its protobuf-JSON
  message to ``{base_url}/{package.Service}/{Method}`` with ``Content-Type: application/json``
  and ``Connect-Protocol-Version: 1``, sent through the runner's SSRF-guarded httpx client. A
  ``200`` carries the response message; anything else carries a Connect error object
  ``{code, message, details}``, and a body without a ``code`` is mapped from its HTTP status by
  the Connect protocol's own table. No HTTP/2, no grpc-web proxy.
* **gRPC** (:class:`GrpcTransport`) — a ``grpcio`` channel to ``base_url``'s host and port, TLS
  when the scheme is ``https``, the per-call deadline from the target policy's
  ``request_timeout_seconds``, and the target's auth headers as call metadata. The server's own
  descriptors are fetched once per run through **server reflection**
  (:func:`app.grpc_reflection.discover_endpoint`) so each JSON message can be encoded into the
  binary protobuf the server reads, and each binary reply decoded back to protobuf-JSON. A case
  the JSON encoding alone can express (``json_only``: a wrong-typed or an unknown field) is
  recorded as skipped with ``rpc-negative-json-only`` — binary protobuf cannot carry it.

The judge
---------
Both transports reduce a reply to a status code and a decoded message
(:class:`RpcReply`). The first assertion compares the status with the case's
``rpc.expect_code`` (``ok``, or ``invalid_argument`` for a negative). A success case then has
its message validated with :mod:`app.schema_instance_validation` against the manifest's
``rpc:<operation key>`` schema — the protobuf-JSON view of the *published* output type — so a
response missing a required field fails with a JSON Pointer into the message, exactly as an HTTP
response-schema failure does.

Transport failures (connect errors, timeouts, ``UNAVAILABLE``, ``DEADLINE_EXCEEDED``) are retried
under the policy's ``retry_attempts``; a status or schema mismatch never is.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Protocol, Tuple
from urllib.parse import urlsplit

import httpx

from .contract_protocols import PROTOCOL_GRPC
from .contract_runner import (
    _FIELD_LIMIT,
    _MESSAGE_LIMIT,
    FAILURE_TIMEOUT,
    FAILURE_TRANSPORT_ERROR,
    _bounded,
    _is_transport_failure,
    _join_url,
    _parse_json_body,
    _response_schema_assertions,
    skipped_operation,
)
from .contract_suite import ContractCase
from .contract_suite_rpc import RPC_CODE_OK
from .grpc_reflection import GrpcReflectionError, discover_endpoint
from .ssrf_guard import SSRFError, validate_host
from .verification_evidence import (
    ASSERTION_KIND_CUSTOM,
    ASSERTION_KIND_STATUS_CODE,
    ASSERTION_OUTCOME_FAILED,
    ASSERTION_OUTCOME_PASSED,
    OPERATION_OUTCOME_ERRORED,
    OPERATION_OUTCOME_FAILED,
    OPERATION_OUTCOME_PASSED,
    AssertionInput,
    OperationResultInput,
)
from .verification_target import NETWORK_CLASS_PRIVATE, ResolvedTarget

__all__ = [
    "CONNECT_PROTOCOL_VERSION",
    "FAILURE_RPC_DESCRIPTOR_MISMATCH",
    "FAILURE_RPC_JSON_ONLY",
    "FAILURE_RPC_REFLECTION_UNAVAILABLE",
    "FAILURE_RPC_RESPONSE_UNDECODABLE",
    "FAILURE_RPC_STATUS_MISMATCH",
    "ConnectTransport",
    "GrpcTransport",
    "RpcReply",
    "RpcTransport",
    "RpcTransportError",
    "build_rpc_transport",
    "connect_code_for_http_status",
    "execute_rpc_case",
]

#: A reply's status code was not the one the case expects.
FAILURE_RPC_STATUS_MISMATCH = "rpc-status-mismatch"
#: A success reply's body is not a protobuf-JSON message (not a JSON object, or not decodable).
FAILURE_RPC_RESPONSE_UNDECODABLE = "rpc-response-undecodable"
#: A native gRPC run met a case only the JSON encoding can express.
FAILURE_RPC_JSON_ONLY = "rpc-negative-json-only"
#: The server's reflection could not be read, so no message could be encoded for it.
FAILURE_RPC_REFLECTION_UNAVAILABLE = "rpc-reflection-unavailable"
#: The server's reflected descriptors do not declare the case's types, or reject its message.
FAILURE_RPC_DESCRIPTOR_MISMATCH = "rpc-descriptor-mismatch"

#: The ``Connect-Protocol-Version`` header every Connect request carries.
CONNECT_PROTOCOL_VERSION = "1"

#: The Connect protocol's HTTP-status → code table, for an error response without a ``code``.
_CONNECT_CODE_BY_HTTP_STATUS: Dict[int, str] = {
    400: "internal",
    401: "unauthenticated",
    403: "permission_denied",
    404: "unimplemented",
    429: "unavailable",
    502: "unavailable",
    503: "unavailable",
    504: "unavailable",
}

#: gRPC statuses that say the call never reached a handler — retried like a connect error.
_RETRYABLE_GRPC_CODES = frozenset({"unavailable"})


def connect_code_for_http_status(status: int) -> str:
    """Map an HTTP status to a Connect code, for an error body that does not carry one.

    Args:
        status: The HTTP status of a non-``200`` Connect response.

    Returns:
        The Connect code the protocol assigns that status (``unknown`` for anything unlisted).
    """
    return _CONNECT_CODE_BY_HTTP_STATUS.get(status, "unknown")


@dataclass(frozen=True)
class RpcReply:
    """One call's outcome, whichever transport carried it.

    Attributes:
        code: The status code in Connect's lower-snake spelling — ``ok`` on success.
        message: The error message, when the server sent one.
        body: The decoded response message (protobuf-JSON) on success; ``None`` otherwise.
        http_status: The HTTP status over Connect; ``None`` over native gRPC.
    """

    code: str
    message: Optional[str] = None
    body: Any = None
    http_status: Optional[int] = None


class RpcTransportError(Exception):
    """The call never produced a reply: a connect error, a timeout, or ``UNAVAILABLE``.

    Attributes:
        code: ``timeout`` or ``transport-error`` (:mod:`app.contract_runner`'s codes), or an RPC
            setup code such as :data:`FAILURE_RPC_REFLECTION_UNAVAILABLE`.
        retryable: Whether the policy's ``retry_attempts`` applies.
    """

    def __init__(self, code: str, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class RpcContractError(Exception):
    """The call could not be made because the server's descriptors disagree with the case.

    Attributes:
        code: Stable failure code, :data:`FAILURE_RPC_DESCRIPTOR_MISMATCH`.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RpcTransport(Protocol):
    """What :func:`execute_rpc_case` needs from a transport."""

    protocol: str

    def call(self, case: ContractCase) -> RpcReply:
        """Make one unary call and return its reply.

        Raises:
            RpcTransportError: When no reply was produced.
            RpcContractError: When the case cannot be encoded for the server.
        """
        ...

    def close(self) -> None:
        """Release whatever the transport holds open."""
        ...


# ===========================================================================
# Connect
# ===========================================================================


class ConnectTransport:
    """Connect-protocol unary calls over the run's httpx client.

    Args:
        client: The runner's (SSRF-guarded) httpx client.
        base_url: The target URL procedures are joined onto.
        auth_headers: Headers attached to every call.
        timeout_seconds: The policy's per-call timeout, sent as ``Connect-Timeout-Ms``.
    """

    protocol = "connect"

    def __init__(
        self,
        client: httpx.Client,
        *,
        base_url: str,
        auth_headers: Mapping[str, str],
        timeout_seconds: int,
    ) -> None:
        self._client = client
        self._base_url = base_url
        self._auth_headers = dict(auth_headers)
        self._timeout_ms = str(max(1, int(timeout_seconds)) * 1000)

    def request(self, case: ContractCase) -> httpx.Request:
        """Build the Connect request for one case.

        Args:
            case: A ``grpc``-protocol case.

        Returns:
            The ``POST`` of the case's protobuf-JSON message to its procedure.
        """
        assert case.rpc is not None
        headers = {
            **self._auth_headers,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Connect-Protocol-Version": CONNECT_PROTOCOL_VERSION,
            "Connect-Timeout-Ms": self._timeout_ms,
        }
        return self._client.build_request(
            "POST",
            _join_url(self._base_url, case.rpc.procedure),
            headers=headers,
            json=case.rpc.message,
        )

    def call(self, case: ContractCase) -> RpcReply:
        """Send one case and read the reply (see :class:`RpcTransport`)."""
        try:
            response = self._client.send(self.request(case))
        except Exception as exc:  # noqa: BLE001 - classified like the HTTP runner does
            is_transport, code, message = _is_transport_failure(exc)
            raise RpcTransportError(code, message, retryable=is_transport) from exc
        body = _parse_json_body(response)
        if response.status_code == 200:
            return RpcReply(code=RPC_CODE_OK, body=body, http_status=200)
        code = body.get("code") if isinstance(body, dict) else None
        message = body.get("message") if isinstance(body, dict) else None
        if not isinstance(code, str) or not code:
            code = connect_code_for_http_status(response.status_code)
        return RpcReply(
            code=code,
            message=str(message) if message is not None else None,
            http_status=response.status_code,
        )

    def close(self) -> None:
        """Nothing to release: the httpx client belongs to the runner."""


# ===========================================================================
# Native gRPC
# ===========================================================================


def _grpc_address(base_url: str) -> Tuple[str, int, bool]:
    """Split a target URL into the ``host``, ``port`` and TLS flag a gRPC channel needs.

    ``https://api.example.com`` → ``("api.example.com", 443, True)``;
    ``http://127.0.0.1:8776`` → ``("127.0.0.1", 8776, False)``. A path is ignored: gRPC has no
    path prefix, the procedure *is* the path.

    Raises:
        RpcTransportError: When the URL has no host.
    """
    parts = urlsplit(base_url)
    host = parts.hostname or ""
    if not host:
        raise RpcTransportError(
            FAILURE_TRANSPORT_ERROR, "target base_url has no host to open a gRPC channel to",
            retryable=False,
        )
    secure = parts.scheme == "https"
    port = parts.port or (443 if secure else 80)
    return host, port, secure


class GrpcTransport:
    """Native gRPC unary calls with descriptors from server reflection.

    The channel and the reflected descriptor pool are created on the first call and shared by
    every case of the run (cases may run concurrently, so both are guarded by a lock).

    Args:
        target: The resolved target: address, network class and policy.
        auth_headers: Headers sent as call metadata (keys lower-cased, as gRPC requires).
        channel_factory: Builds the channel from ``(address, secure)`` — a test seam; production
            builds an insecure or a TLS ``grpcio`` channel.
    """

    protocol = PROTOCOL_GRPC

    def __init__(
        self,
        target: ResolvedTarget,
        *,
        auth_headers: Mapping[str, str],
        channel_factory: Optional[Any] = None,
    ) -> None:
        self._target = target
        self._metadata = [(name.lower(), value) for name, value in auth_headers.items()]
        self._timeout = float(max(1, int(target.policy.request_timeout_seconds)))
        self._channel_factory = channel_factory
        self._lock = threading.Lock()
        self._channel: Any = None
        self._pool: Any = None
        self._setup_error: Optional[RpcTransportError] = None

    def _open(self) -> None:
        """Open the channel and read the server's descriptors, once, or remember why not."""
        with self._lock:
            if self._channel is not None or self._setup_error is not None:
                return
            try:
                host, port, secure = _grpc_address(self._target.base_url)
                allow_private = self._target.network_class == NETWORK_CLASS_PRIVATE
                if not allow_private:
                    validate_host(host)
                address = f"{host}:{port}"
                self._pool = _reflect_pool(
                    address,
                    secure=secure,
                    metadata=self._metadata,
                    timeout=self._timeout,
                    allow_private=allow_private,
                )
                self._channel = self._build_channel(address, secure)
            except SSRFError as exc:
                self._setup_error = RpcTransportError(
                    FAILURE_TRANSPORT_ERROR,
                    f"the target host is refused by the SSRF policy: {exc}",
                    retryable=False,
                )
            except RpcTransportError as exc:
                self._setup_error = exc

    def _build_channel(self, address: str, secure: bool) -> Any:
        """Build the channel calls are made on."""
        if self._channel_factory is not None:
            return self._channel_factory(address, secure)
        import grpc

        if secure:
            return grpc.secure_channel(address, grpc.ssl_channel_credentials())
        return grpc.insecure_channel(address)

    def call(self, case: ContractCase) -> RpcReply:
        """Encode, call and decode one case (see :class:`RpcTransport`)."""
        import grpc
        from google.protobuf import json_format, message_factory

        assert case.rpc is not None
        self._open()
        if self._setup_error is not None:
            raise self._setup_error
        rpc = case.rpc
        try:
            input_class = message_factory.GetMessageClass(
                self._pool.FindMessageTypeByName(rpc.input_type)
            )
            output_class = message_factory.GetMessageClass(
                self._pool.FindMessageTypeByName(rpc.output_type)
            )
        except KeyError as exc:
            raise RpcContractError(
                FAILURE_RPC_DESCRIPTOR_MISMATCH,
                f"the server's reflection does not declare {rpc.input_type!r} and "
                f"{rpc.output_type!r}, the types the contract names for {rpc.procedure}",
            ) from exc

        request = input_class()
        try:
            json_format.ParseDict(rpc.message, request)
        except json_format.ParseError as exc:
            raise RpcContractError(
                FAILURE_RPC_DESCRIPTOR_MISMATCH,
                f"the server's {rpc.input_type!r} does not accept the contract's message: {exc}",
            ) from exc

        stub = self._channel.unary_unary(
            rpc.procedure,
            request_serializer=_identity,
            response_deserializer=_identity,
        )
        try:
            # A negative case may omit a required field on purpose: serialize it partially.
            payload = stub(
                request.SerializePartialToString(),
                metadata=self._metadata or None,
                timeout=self._timeout,
            )
        except grpc.RpcError as exc:
            status = exc.code() if hasattr(exc, "code") else None
            code = status.name.lower() if status is not None else "unknown"
            details = exc.details() if hasattr(exc, "details") else None
            if status == grpc.StatusCode.DEADLINE_EXCEEDED:
                raise RpcTransportError(FAILURE_TIMEOUT, "the call exceeded its deadline") from exc
            if code in _RETRYABLE_GRPC_CODES:
                raise RpcTransportError(
                    FAILURE_TRANSPORT_ERROR, f"transport error: {code}"
                ) from exc
            return RpcReply(code=code, message=details)

        response = output_class()
        try:
            response.ParseFromString(payload)
        except Exception as exc:  # noqa: BLE001 - an undecodable reply is an observation
            return RpcReply(code=RPC_CODE_OK, message=f"undecodable response: {exc}", body=None)
        return RpcReply(code=RPC_CODE_OK, body=json_format.MessageToDict(response))

    def close(self) -> None:
        """Close the channel, if one was opened."""
        if self._channel is not None:
            try:
                self._channel.close()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass


def _identity(value: bytes) -> bytes:
    """Pass already-serialized protobuf bytes through ``grpcio`` untouched."""
    return value


def _reflect_pool(
    address: str,
    *,
    secure: bool,
    metadata: List[Tuple[str, str]],
    timeout: float,
    allow_private: bool,
) -> Any:
    """Read a server's descriptors through reflection into a fresh descriptor pool.

    Raises:
        RpcTransportError: ``rpc-reflection-unavailable`` when reflection is off, unreachable,
            or returns descriptors that do not load.
    """
    from google.protobuf import descriptor_pb2, descriptor_pool

    try:
        result = discover_endpoint(
            address,
            metadata=metadata,
            secure=secure,
            timeout=timeout,
            allow_private=allow_private,
        )
    except GrpcReflectionError as exc:
        raise RpcTransportError(
            FAILURE_RPC_REFLECTION_UNAVAILABLE, str(exc), retryable=False
        ) from exc
    if not result.ok or not result.descriptor_set_bytes:
        raise RpcTransportError(
            FAILURE_RPC_REFLECTION_UNAVAILABLE,
            "the server's descriptors could not be read through reflection: "
            f"{result.reason or 'no descriptors returned'}; native gRPC verification needs "
            "server reflection (use a `connect` target otherwise)",
            retryable=False,
        )

    descriptor_set = descriptor_pb2.FileDescriptorSet()
    descriptor_set.ParseFromString(result.descriptor_set_bytes)
    files = {item.name: item for item in descriptor_set.file}
    pool = descriptor_pool.DescriptorPool()
    added: set = set()

    def _add(name: str) -> None:
        # Dependencies first: a pool refuses a file whose imports it has not seen.
        if name in added or name not in files:
            return
        added.add(name)
        for dependency in files[name].dependency:
            _add(dependency)
        pool.Add(files[name])

    try:
        for name in sorted(files):
            _add(name)
    except Exception as exc:  # noqa: BLE001 - a descriptor that does not load is a setup fault
        raise RpcTransportError(
            FAILURE_RPC_REFLECTION_UNAVAILABLE,
            f"the server's reflected descriptors do not load: {exc}",
            retryable=False,
        ) from exc
    return pool


def build_rpc_transport(
    target: ResolvedTarget,
    *,
    client: httpx.Client,
    auth_headers: Mapping[str, str],
) -> RpcTransport:
    """Pick the transport a target's protocol names.

    Args:
        target: The resolved target; ``protocol`` ``grpc`` opens a native channel, anything else
            (``connect``) uses the HTTP client.
        client: The runner's httpx client.
        auth_headers: Headers for every call.

    Returns:
        The transport. The caller closes it when the run ends.
    """
    if target.protocol == PROTOCOL_GRPC:
        return GrpcTransport(target, auth_headers=auth_headers)
    return ConnectTransport(
        client,
        base_url=target.base_url,
        auth_headers=auth_headers,
        timeout_seconds=target.policy.request_timeout_seconds,
    )


# ===========================================================================
# Execution and judgment
# ===========================================================================


def _rpc_assertions(
    case: ContractCase, reply: RpcReply, *, schemas: Mapping[str, Dict[str, Any]]
) -> List[AssertionInput]:
    """Judge one reply: the status code first, then (for a success case) the message.

    Args:
        case: The ``grpc``-protocol case.
        reply: What came back.
        schemas: The manifest's schema map.

    Returns:
        The assertions to record, in order — the first failed one decides the case.
    """
    assert case.rpc is not None
    expected = case.rpc.expect_code
    matched = reply.code == expected
    detail = f": {reply.message}" if reply.message else ""
    status = AssertionInput(
        kind=ASSERTION_KIND_STATUS_CODE,
        outcome=ASSERTION_OUTCOME_PASSED if matched else ASSERTION_OUTCOME_FAILED,
        subject="rpc-status",
        expected=expected,
        actual=_bounded(reply.code, _FIELD_LIMIT),
        code=None if matched else FAILURE_RPC_STATUS_MISMATCH,
        message=(
            None
            if matched
            else _bounded(f"expected status `{expected}`, got `{reply.code}`{detail}", _MESSAGE_LIMIT)
        ),
    )
    if not matched or expected != RPC_CODE_OK:
        return [status]
    if not isinstance(reply.body, dict):
        return [
            status,
            AssertionInput(
                kind=ASSERTION_KIND_CUSTOM,
                outcome=ASSERTION_OUTCOME_FAILED,
                subject="message",
                expected=case.rpc.output_type,
                actual=_bounded(reply.message or type(reply.body).__name__, _FIELD_LIMIT),
                code=FAILURE_RPC_RESPONSE_UNDECODABLE,
                message=_bounded(
                    f"the reply does not decode as {case.rpc.output_type!r}"
                    f"{': ' + reply.message if reply.message else ''}",
                    _MESSAGE_LIMIT,
                ),
            ),
        ]
    return [status, *_response_schema_assertions(case, schemas=schemas, body=reply.body)]


def execute_rpc_case(
    case: ContractCase,
    *,
    target: ResolvedTarget,
    transport: RpcTransport,
    schemas: Mapping[str, Dict[str, Any]],
) -> OperationResultInput:
    """Execute one ``grpc``-protocol case and return its evidence record.

    The caller has already applied the mutating-method gate.

    Args:
        case: The case.
        target: The resolved target, for its retry policy.
        transport: The run's transport.
        schemas: The manifest's schema map.

    Returns:
        The case's :class:`OperationResultInput`.
    """
    assert case.rpc is not None
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    if case.rpc.json_only and transport.protocol == PROTOCOL_GRPC:
        return skipped_operation(
            case,
            code=FAILURE_RPC_JSON_ONLY,
            message=(
                "this negative case sets a wrong-typed or unknown JSON field, which binary "
                "protobuf cannot carry; run it against a `connect` target"
            ),
            started_at=started,
        )

    def _record(
        outcome: str,
        *,
        attempts: int,
        code: Optional[str] = None,
        message: Optional[str] = None,
        http_status: Optional[int] = None,
        assertions: Optional[List[AssertionInput]] = None,
    ) -> OperationResultInput:
        return OperationResultInput(
            case_id=case.case_id,
            operation_key=case.operation_key,
            operation_name=case.operation_name,
            case_source=case.source,
            http_method="POST",
            http_path=case.rpc.procedure,
            outcome=outcome,
            failure_code=code,
            failure_message=message,
            expected_status=case.rpc.expect_code,
            actual_status=http_status,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
            duration_ms=int((time.perf_counter() - t0) * 1000),
            attempts=attempts,
            assertions=assertions or [],
        )

    policy = target.policy
    max_attempts = 1 + max(0, int(policy.retry_attempts))
    backoff_s = max(0, int(policy.retry_backoff_ms)) / 1000.0
    attempts = 0
    reply: Optional[RpcReply] = None
    while reply is None:
        attempts += 1
        try:
            reply = transport.call(case)
        except RpcContractError as exc:
            return _record(
                OPERATION_OUTCOME_FAILED,
                attempts=attempts,
                code=exc.code,
                message=_bounded(str(exc), _MESSAGE_LIMIT),
            )
        except RpcTransportError as exc:
            if not exc.retryable or attempts >= max_attempts:
                return _record(
                    OPERATION_OUTCOME_ERRORED,
                    attempts=attempts,
                    code=exc.code,
                    message=_bounded(str(exc), _MESSAGE_LIMIT),
                )
            if backoff_s:
                time.sleep(backoff_s)

    assertions = _rpc_assertions(case, reply, schemas=schemas)
    headline = next(
        (item for item in assertions if item.outcome == ASSERTION_OUTCOME_FAILED), None
    )
    if headline is not None:
        return _record(
            OPERATION_OUTCOME_FAILED,
            attempts=attempts,
            code=headline.code,
            message=headline.message,
            http_status=reply.http_status,
            assertions=assertions,
        )
    return _record(
        OPERATION_OUTCOME_PASSED,
        attempts=attempts,
        http_status=reply.http_status,
        assertions=assertions,
    )
