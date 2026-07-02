"""gRPC live discovery via Server Reflection — MFI-9.3 (#3766).

Many gRPC services ship no ``.proto`` files to their consumers: the schema exists only on the
running server, exposed through the **gRPC Server Reflection** protocol. MFI-9.1 turns ``.proto``
*source* into a ``FileDescriptorSet`` and MFI-9.2 maps that set onto the canonical model; this
module covers the **third** way an author hands us a gRPC API — a **live endpoint** with no
source — by crawling its reflection service and assembling the very same
:class:`~app.proto_descriptor.CompiledDescriptorSet` the file path produces, so the result flows
into the MFI-9.2 normalizer unchanged.

What it does, in one call (:func:`discover_endpoint`):

* **connect** — open a gRPC channel to a tenant-supplied ``host:port`` target. The host is vetted
  by the **SSRF guard** (:func:`app.ssrf_guard.validate_host`) *before* the channel is created,
  so a target can never be pointed at internal/metadata addresses — the same posture the HTTP
  live-discovery paths use (MFI-5.3 makes live discovery the one explicit network opt-out of the
  no-network sandbox default; the SSRF guard is the brace). Auth is attached as call **metadata**
  built from the **credential vault** model (:func:`app.mcp_auth.build_auth_headers`) — the same
  ``none``/``bearer``/``header``/``oauth2`` mapping the MCP discovery and GraphQL introspection
  paths use — so a stored bearer token or custom header authenticates every reflection RPC. The
  payload is supplied **already decrypted** (decryption is the vault's job, MCAT-6.2).
* **crawl** — call ``ListServices`` to enumerate the server's services, then
  ``FileContainingSymbol`` for each (excluding the reflection services themselves). Each response
  carries the file that declares the symbol **plus its transitive dependencies** as serialized
  ``FileDescriptorProto``\\s, so the union over all services is the full type surface.
* **assemble** — dedup the collected ``FileDescriptorProto``\\s by file name, order them
  deterministically, and pack them into a ``google.protobuf.FileDescriptorSet`` whose bytes are
  handed to :func:`app.proto_descriptor.read_file_descriptor_set` — the exact canonical artifact
  MFI-9.1 produces (the thing the MFI-3.1 fingerprint hook hashes). Files that declare a
  discovered service are flagged *targets*; pulled-in dependencies (well-known types, shared
  messages) are flagged *imports*, mirroring a ``.proto`` ``import``.
* **fall back** — the wire protocol is identical for the modern ``grpc.reflection.v1`` service
  and the older ``grpc.reflection.v1alpha`` one; only the service path differs. The crawl tries
  **v1** first and, when the server has not implemented it (``UNIMPLEMENTED``), transparently
  retries the whole crawl against **v1alpha**.

Validity is a **return value**, not an exception: :func:`discover_endpoint` always returns a
:class:`GrpcReflectionResult` describing what happened (which reflection version answered, the
discovered services, the assembled descriptor metadata, or a human ``reason`` when nothing built).
The one thing that *does* raise is a misconfigured request the caller must fix — an unsafe target
(:class:`~app.ssrf_guard.SSRFError`) or a malformed credential
(:class:`~app.mcp_auth.CredentialPayloadError`) — surfaced as :class:`GrpcReflectionError` so a
route can return a 4xx.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

from google.protobuf import descriptor_pb2
from google.protobuf.message import DecodeError
from pydantic import BaseModel, ConfigDict, Field

from .mcp_auth import AUTH_TYPE_NONE, CredentialPayloadError, build_auth_headers
from .proto_descriptor import (
    CompiledDescriptorSet,
    DescriptorSetSummary,
    ProtoDescriptorError,
    read_file_descriptor_set,
)
from .ssrf_guard import SSRFError, validate_host

__all__ = [
    "ReflectionVersion",
    "GrpcReflectionError",
    "GrpcReflectionResult",
    "ReflectionTransport",
    "ReflectionVersionUnsupportedError",
    "ReflectionConnectionError",
    "REFLECTION_SERVICE_NAMES",
    "build_descriptor_set",
    "discover_endpoint",
]


class ReflectionVersion(str, Enum):
    """The Server Reflection service variant a crawl spoke to.

    The two share an identical wire protocol; they differ only in the fully-qualified service
    name (hence the RPC method path). :attr:`V1` is tried first; :attr:`V1ALPHA` is the
    backwards-compatibility fallback for servers that have not adopted the v1 service.
    """

    #: The modern ``grpc.reflection.v1.ServerReflection`` service.
    V1 = "v1"
    #: The legacy ``grpc.reflection.v1alpha.ServerReflection`` service.
    V1ALPHA = "v1alpha"


#: The reflection services themselves, excluded from the discovered surface — they are the
#: transport we crawled *over*, not part of the tenant's API. Both versions are listed so neither
#: leaks into the imported model regardless of which one answered.
REFLECTION_SERVICE_NAMES = frozenset(
    {
        "grpc.reflection.v1.ServerReflection",
        "grpc.reflection.v1alpha.ServerReflection",
    }
)

#: RPC method path for each reflection version's bidi ``ServerReflectionInfo`` stream. The
#: messages are wire-identical, so the production transport reuses the v1alpha message classes
#: for both and only swaps the path — which is how we reach ``grpc.reflection.v1`` even though
#: ``grpcio-reflection`` ships generated stubs for v1alpha only.
_METHOD_PATHS: Dict[ReflectionVersion, str] = {
    ReflectionVersion.V1: "/grpc.reflection.v1.ServerReflection/ServerReflectionInfo",
    ReflectionVersion.V1ALPHA: "/grpc.reflection.v1alpha.ServerReflection/ServerReflectionInfo",
}

#: Hard ceiling on how many ``FileDescriptorProto``\\s a crawl will assemble, so a hostile or
#: runaway server cannot ask us to hold an unbounded descriptor set in memory.
_MAX_DESCRIPTOR_FILES = 4000

#: Hard ceiling on the combined size of the collected ``FileDescriptorProto`` payloads, a second
#: bound (independent of the file count) against a server returning pathologically large protos.
_MAX_DESCRIPTOR_BYTES = 64 * 1024 * 1024

#: Default per-RPC deadline (seconds) for each reflection stream. Generous enough for a large
#: surface yet bounded so a wedged server fails rather than hanging the import.
_DEFAULT_TIMEOUT_SECONDS = 30.0


# ===========================================================================
# Errors
# ===========================================================================


class GrpcReflectionError(Exception):
    """The discovery request was **misconfigured** and must be fixed before retrying.

    Reserved for caller errors a route should surface as a 4xx — an unsafe/blocked target
    (:class:`~app.ssrf_guard.SSRFError`) or a malformed credential
    (:class:`~app.mcp_auth.CredentialPayloadError`). A server that is merely unreachable or does
    not expose reflection is **not** this error: that is an ordinary outcome captured on
    :class:`GrpcReflectionResult`.
    """


class ReflectionVersionUnsupportedError(Exception):
    """Internal: the server has not implemented the reflection version that was tried.

    Raised by a :class:`ReflectionTransport` to signal "try the other version" — the
    orchestrator catches it and falls back from v1 to v1alpha. It is never surfaced to callers.
    """


class ReflectionConnectionError(Exception):
    """Internal: a terminal failure talking to the server (unreachable, deadline, RPC error).

    Carries a **secret-free** human reason. The orchestrator turns it into a not-``ok``
    :class:`GrpcReflectionResult` rather than re-raising — a server being down is an outcome,
    not a misconfiguration. Distinct from :class:`ReflectionVersionUnsupportedError`, which triggers
    a version fallback instead of ending the crawl.
    """


# ===========================================================================
# Result model
# ===========================================================================


class GrpcReflectionResult(BaseModel):
    """The outcome of crawling a live gRPC endpoint's Server Reflection surface.

    A successful run has :attr:`ok` ``True``, the :attr:`reflection_version` that answered, the
    discovered :attr:`services`, and the assembled descriptor metadata (:attr:`descriptor_set_bytes`
    / :attr:`summary` / :attr:`target_files`). The bytes are the canonical artifact — identical in
    shape to what MFI-9.1 compiles from source — so :meth:`compiled` rebuilds the
    :class:`~app.proto_descriptor.CompiledDescriptorSet` the MFI-9.2 normalizer consumes, with the
    target/import distinction preserved. A failed run has :attr:`ok` ``False`` and a human
    :attr:`reason` (reflection disabled, server unreachable, or no services exposed).
    """

    model_config = ConfigDict(frozen=True)

    ok: bool = Field(description="True when a descriptor set was assembled from the live server.")
    reflection_version: Optional[ReflectionVersion] = Field(
        default=None,
        description="Which reflection service answered (``v1`` or the ``v1alpha`` fallback); "
        "``None`` when neither produced a surface.",
    )
    services: List[str] = Field(
        default_factory=list,
        description="Fully-qualified service names discovered via ``ListServices`` (sorted, with "
        "the reflection services themselves excluded).",
    )
    descriptor_set_bytes: Optional[bytes] = Field(
        default=None,
        description="The assembled binary ``google.protobuf.FileDescriptorSet`` (the canonical "
        "artifact); ``None`` when nothing built.",
    )
    summary: Optional[DescriptorSetSummary] = Field(
        default=None,
        description="Serializable roll-up of the assembled descriptor set; ``None`` when nothing built.",
    )
    target_files: List[str] = Field(
        default_factory=list,
        description="Descriptor-set file names that declare a discovered service (the targets); the "
        "rest are pulled-in imports. Passed back into ``read_file_descriptor_set`` by :meth:`compiled`.",
    )
    reason: Optional[str] = Field(
        default=None,
        description="Human explanation when ``ok`` is ``False`` (reflection disabled / unreachable / "
        "no services); ``None`` on a clean crawl.",
    )

    def compiled(self) -> Optional[CompiledDescriptorSet]:
        """Rebuild the :class:`~app.proto_descriptor.CompiledDescriptorSet` for the normalizer.

        Re-reads :attr:`descriptor_set_bytes` (cheap) with :attr:`target_files` so the
        import-vs-target flags are restored, yielding exactly the object MFI-9.2's
        ``ProtoNormalizer`` expects. Returns ``None`` when the crawl produced no descriptor set.

        Raises:
            ProtoDescriptorError: If the stored bytes are not a parseable ``FileDescriptorSet``
                (should not happen for bytes this module assembled).
        """
        if self.descriptor_set_bytes is None:
            return None
        return read_file_descriptor_set(
            self.descriptor_set_bytes, target_files=self.target_files
        )


# ===========================================================================
# Pure assembly seam (no I/O)
# ===========================================================================


def build_descriptor_set(
    file_descriptor_protos: Sequence[bytes],
    *,
    service_symbols: Sequence[str] = (),
) -> Tuple[bytes, List[str]]:
    """Assemble serialized ``FileDescriptorProto``\\s into one ordered ``FileDescriptorSet``.

    The reflection crawl yields the same file repeatedly (every service drags in its transitive
    dependencies); this seam is the pure, network-free half that turns that raw stream into the
    canonical artifact. It parses each serialized ``FileDescriptorProto``, **dedups by file
    name** (keeping the first occurrence — they are identical across responses), **orders the
    files by name** so the resulting bytes are deterministic (a stable MFI-3.1 fingerprint,
    independent of reflection response order), and serializes the packed
    ``google.protobuf.FileDescriptorSet``.

    It also computes which files are the caller's *targets*: a file is a target when it declares
    any of ``service_symbols`` (the fully-qualified names ``ListServices`` returned); every other
    file is a pulled-in import. With no ``service_symbols`` supplied, every file is treated as a
    target.

    Args:
        file_descriptor_protos: Serialized ``google.protobuf.FileDescriptorProto`` blobs, as the
            reflection ``FileDescriptorResponse`` returns them (order/duplicates irrelevant).
        service_symbols: Fully-qualified service names used to flag target files.

    Returns:
        A ``(descriptor_set_bytes, target_file_names)`` tuple: the serialized, deterministically
        ordered ``FileDescriptorSet`` and the sorted list of file names that declare a service.

    Raises:
        GrpcReflectionError: If no usable file descriptors were supplied, the count/size caps are
            exceeded, or a blob is not a parseable ``FileDescriptorProto``.
    """
    if not file_descriptor_protos:
        raise GrpcReflectionError("reflection returned no file descriptors to assemble")
    if len(file_descriptor_protos) > _MAX_DESCRIPTOR_FILES:
        raise GrpcReflectionError(
            f"reflection returned too many file descriptors "
            f"({len(file_descriptor_protos)}); the limit is {_MAX_DESCRIPTOR_FILES}"
        )

    total_bytes = sum(len(blob) for blob in file_descriptor_protos)
    if total_bytes > _MAX_DESCRIPTOR_BYTES:
        raise GrpcReflectionError(
            f"reflection descriptors exceed the {_MAX_DESCRIPTOR_BYTES}-byte assembly limit"
        )

    symbols = set(service_symbols)
    by_name: Dict[str, descriptor_pb2.FileDescriptorProto] = {}
    target_names: set[str] = set()
    for blob in file_descriptor_protos:
        file_proto = descriptor_pb2.FileDescriptorProto()
        try:
            file_proto.ParseFromString(blob)
        except (DecodeError, ValueError) as exc:
            raise GrpcReflectionError(
                f"reflection returned an unparseable FileDescriptorProto: {exc}"
            ) from exc
        name = file_proto.name
        if not name:
            # A nameless descriptor cannot be deduped or referenced as an import; skip it rather
            # than letting it collide every other anonymous file under the empty-string key.
            continue
        if name not in by_name:
            by_name[name] = file_proto
        # Flag the file as a target if it declares any discovered service. A file can be revisited
        # across responses, so compute this on every sighting (the parse is cheap and idempotent).
        if symbols and _declares_target_service(file_proto, symbols):
            target_names.add(name)

    if not by_name:
        raise GrpcReflectionError("reflection returned only nameless file descriptors")

    descriptor_set = descriptor_pb2.FileDescriptorSet()
    for name in sorted(by_name):
        descriptor_set.file.append(by_name[name])

    # No symbols given → caller cannot distinguish targets, so treat every file as a target
    # (matches read_file_descriptor_set's ``target_files=None`` semantics, but made explicit here).
    targets = sorted(target_names) if symbols else sorted(by_name)
    return descriptor_set.SerializeToString(), targets


def _declares_target_service(
    file_proto: descriptor_pb2.FileDescriptorProto, symbols: set
) -> bool:
    """Return ``True`` if ``file_proto`` declares a service whose FQN is in ``symbols``."""
    package = file_proto.package
    for service in file_proto.service:
        fqn = f"{package}.{service.name}" if package else service.name
        if fqn in symbols:
            return True
    return False


# ===========================================================================
# Transport seam — the network boundary (injectable for tests)
# ===========================================================================


class ReflectionTransport(Protocol):
    """The reflection round-trips :func:`discover_endpoint` needs, abstracted for testing.

    A production transport (:func:`_build_grpc_transport`) wraps a real gRPC channel; tests inject
    a fake so the crawl/assembly/fallback logic runs with no live server. Implementations signal
    a version mismatch with :class:`ReflectionVersionUnsupportedError` (→ fall back) and any terminal
    failure with :class:`ReflectionConnectionError` (→ not-``ok`` result).
    """

    def list_services(self) -> List[str]:
        """Return the server's fully-qualified service names (``ListServices``)."""
        ...

    def files_for_symbols(self, symbols: Sequence[str]) -> List[bytes]:
        """Return serialized ``FileDescriptorProto``\\s for ``FileContainingSymbol(symbol)``.

        The union over the requested symbols — including each file's transitive dependencies.
        """
        ...

    def close(self) -> None:
        """Release the underlying channel/connection."""
        ...


def _build_grpc_transport(
    target: str,
    version: ReflectionVersion,
    *,
    metadata: Sequence[Tuple[str, str]],
    timeout: float,
    secure: bool,
    channel_credentials: Optional[object],
) -> ReflectionTransport:
    """Build the production :class:`ReflectionTransport` over a real gRPC channel.

    ``grpcio`` is imported lazily so this module loads in environments without it; a real crawl
    requires it (declared as a dependency). The channel is created here — the SSRF host check has
    already run in :func:`discover_endpoint` before we reach this point.
    """
    try:
        import grpc
    except ImportError as exc:  # pragma: no cover - grpcio is a declared dependency
        raise GrpcReflectionError(
            "grpcio is not available in this runtime; gRPC live discovery is unavailable here"
        ) from exc
    from grpc_reflection.v1alpha import reflection_pb2

    if secure:
        creds = channel_credentials or grpc.ssl_channel_credentials()
        channel = grpc.secure_channel(target, creds)  # type: ignore[arg-type]
    else:
        channel = grpc.insecure_channel(target)

    return _GrpcReflectionTransport(
        channel=channel,
        version=version,
        metadata=list(metadata),
        timeout=timeout,
        grpc_module=grpc,
        reflection_pb2=reflection_pb2,
    )


class _GrpcReflectionTransport:
    """A :class:`ReflectionTransport` backed by a live gRPC channel.

    Drives the bidi ``ServerReflectionInfo`` stream directly via ``channel.stream_stream`` using
    the v1alpha message classes (wire-identical to v1) and the version-specific method path, so it
    can address either reflection service from the single set of generated messages.
    """

    def __init__(
        self,
        *,
        channel,
        version: ReflectionVersion,
        metadata: Sequence[Tuple[str, str]],
        timeout: float,
        grpc_module,
        reflection_pb2,
    ) -> None:
        self._channel = channel
        self._version = version
        self._metadata = list(metadata)
        self._timeout = timeout
        self._grpc = grpc_module
        self._pb2 = reflection_pb2
        self._method = channel.stream_stream(
            _METHOD_PATHS[version],
            request_serializer=reflection_pb2.ServerReflectionRequest.SerializeToString,
            response_deserializer=reflection_pb2.ServerReflectionResponse.FromString,
        )

    def _exchange(self, requests: Sequence[object]) -> List[object]:
        """Send ``requests`` over a fresh ``ServerReflectionInfo`` stream and read every response.

        Maps gRPC failures onto the module's internal taxonomy: ``UNIMPLEMENTED`` (the server
        does not run this reflection version) → :class:`ReflectionVersionUnsupportedError`; anything
        else → :class:`ReflectionConnectionError` with a secret-free reason.
        """
        try:
            responses = self._method(
                iter(requests), metadata=self._metadata or None, timeout=self._timeout
            )
            return list(responses)
        except self._grpc.RpcError as exc:
            code = exc.code() if hasattr(exc, "code") else None
            if code == self._grpc.StatusCode.UNIMPLEMENTED:
                raise ReflectionVersionUnsupportedError(
                    f"server does not implement gRPC reflection {self._version.value}"
                ) from exc
            detail = code.name.lower().replace("_", " ") if code is not None else "rpc error"
            raise ReflectionConnectionError(
                f"gRPC reflection {self._version.value} failed: {detail}"
            ) from exc

    def list_services(self) -> List[str]:
        request = self._pb2.ServerReflectionRequest(list_services="")
        responses = self._exchange([request])
        services: List[str] = []
        for response in responses:
            if response.HasField("error_response"):
                # An error on ListServices means this version is unusable; fall back to the other.
                raise ReflectionVersionUnsupportedError(
                    f"reflection {self._version.value} ListServices returned an error "
                    f"(code {response.error_response.error_code})"
                )
            for service in response.list_services_response.service:
                services.append(service.name)
        return services

    def files_for_symbols(self, symbols: Sequence[str]) -> List[bytes]:
        if not symbols:
            return []
        requests = [
            self._pb2.ServerReflectionRequest(file_containing_symbol=symbol) for symbol in symbols
        ]
        responses = self._exchange(requests)
        blobs: List[bytes] = []
        for response in responses:
            if response.HasField("error_response"):
                # A single symbol may be unresolvable (e.g. a service with no own file); skip it
                # rather than failing the whole crawl — other symbols still yield the surface.
                continue
            blobs.extend(response.file_descriptor_response.file_descriptor_proto)
        return blobs

    def close(self) -> None:
        self._channel.close()


# ===========================================================================
# Orchestration
# ===========================================================================


def _auth_metadata(
    auth_type: Optional[str], auth_payload: Optional[Mapping[str, object]]
) -> List[Tuple[str, str]]:
    """Map a credential-vault entry onto gRPC call metadata, or ``[]`` for no/anonymous auth.

    Reuses the shared credential-vault auth model (:func:`app.mcp_auth.build_auth_headers`): the
    ``payload`` is supplied **decrypted** and only ever yields headers, which become gRPC metadata
    pairs with lower-cased keys (gRPC requires lower-case metadata names; ``Authorization`` →
    ``authorization``).

    Raises:
        GrpcReflectionError: If the credential is missing or malformed for its ``auth_type``.
    """
    if not auth_type or auth_type == AUTH_TYPE_NONE:
        return []
    if auth_payload is None:
        raise GrpcReflectionError(
            f"auth_type={auth_type!r} requires a credential payload (auth_payload)"
        )
    try:
        headers = build_auth_headers(auth_type, dict(auth_payload))
    except CredentialPayloadError as exc:
        raise GrpcReflectionError(str(exc)) from exc
    return [(name.lower(), value) for name, value in headers.items()]


def _host_of(target: str) -> str:
    """Extract the bare host from a ``host``/``host:port``/``[ipv6]:port`` reflection target.

    Strips any ``scheme://`` prefix and any ``user:pass@`` authority a caller might include, then
    drops the port. Used to feed :func:`app.ssrf_guard.validate_host` — the SSRF policy vets the
    host, not the port.

    Raises:
        GrpcReflectionError: If no host can be extracted from ``target``.
    """
    raw = (target or "").strip()
    if not raw:
        raise GrpcReflectionError("gRPC target is empty")
    # Drop a scheme (grpc://, dns:///host:port, etc.) if present, keeping the authority.
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    # Drop any "user:pass@" authority *first* — error messages below must never echo it, so a
    # credential a caller mistakenly embedded in the target can't leak into logs.
    raw = raw.rsplit("@", 1)[-1].strip("/")
    if not raw:
        raise GrpcReflectionError("could not parse a host from the gRPC target")

    if raw.startswith("["):
        # Bracketed IPv6 literal: [::1]:50051 → host is the part inside the brackets.
        end = raw.find("]")
        if end == -1:
            raise GrpcReflectionError("malformed IPv6 gRPC target (missing closing ']')")
        host = raw[1:end]
    elif raw.count(":") > 1:
        # A bare (unbracketed) IPv6 literal with no port — take it whole.
        host = raw
    else:
        # host or host:port.
        host = raw.split(":", 1)[0]

    host = host.strip()
    if not host:
        raise GrpcReflectionError("could not parse a host from the gRPC target")
    return host


def discover_endpoint(
    target: str,
    *,
    auth_type: Optional[str] = None,
    auth_payload: Optional[Mapping[str, object]] = None,
    metadata: Optional[Sequence[Tuple[str, str]]] = None,
    secure: bool = False,
    channel_credentials: Optional[object] = None,
    timeout: Optional[float] = None,
    transport_factory: Optional[Callable[[ReflectionVersion], ReflectionTransport]] = None,
) -> GrpcReflectionResult:
    """Crawl a live gRPC server's Server Reflection surface into a canonical descriptor set.

    Connects to ``target`` (SSRF-guarded, optionally authenticated from the credential vault),
    enumerates its services via ``ListServices``, pulls each service's file (plus transitive
    dependencies) via ``FileContainingSymbol``, and assembles the union into a
    ``google.protobuf.FileDescriptorSet`` whose bytes match the MFI-9.1 file path exactly — so the
    result flows into the MFI-9.2 normalizer (via :meth:`GrpcReflectionResult.compiled`) unchanged.
    The crawl tries the modern ``grpc.reflection.v1`` service first and falls back to
    ``grpc.reflection.v1alpha`` when v1 is not implemented.

    Validity is a *return value*: a server that is unreachable or has reflection disabled yields a
    not-``ok`` :class:`GrpcReflectionResult` with a human ``reason`` rather than raising. The
    function raises only for a request the caller must fix (an unsafe target or a malformed
    credential).

    Args:
        target: The gRPC endpoint as ``host:port`` (a ``scheme://`` prefix and ``user:pass@``
            authority are tolerated and stripped; the host is SSRF-validated).
        auth_type: Credential-vault auth type (``none``/``bearer``/``header``/``oauth2``); ``None``
            or ``"none"`` crawls unauthenticated.
        auth_payload: The **decrypted** credential payload for ``auth_type`` (e.g.
            ``{"token": "…"}`` for ``bearer``). Ignored for ``none``.
        metadata: Extra gRPC metadata pairs merged in **after** the auth metadata (so a caller can
            add a routing header without overriding the credential). Keys are lower-cased.
        secure: When ``True`` open a TLS channel (default-trust unless ``channel_credentials`` is
            supplied); when ``False`` (default) an insecure channel.
        channel_credentials: Optional ``grpc.ChannelCredentials`` for the TLS channel (e.g. a
            pinned CA); ignored when ``secure`` is ``False``.
        timeout: Per-RPC deadline in seconds; defaults to 30s.
        transport_factory: A factory ``(version) -> ReflectionTransport`` used instead of building
            a real gRPC channel — a dependency-injection seam for tests. Production callers omit it.

    Returns:
        A :class:`GrpcReflectionResult`.

    Raises:
        GrpcReflectionError: If ``target`` is rejected by the SSRF policy or the credential is
            malformed for its ``auth_type``.
    """
    # 1) Vet the target host up front — an SSRF rejection is a config/security problem, never a
    #    "the server is just down" outcome.
    host = _host_of(target)
    try:
        validate_host(host)
    except SSRFError as exc:
        raise GrpcReflectionError(str(exc)) from exc

    # 2) Resolve auth → call metadata (raises on a malformed credential), then merge extras.
    call_metadata = _auth_metadata(auth_type, auth_payload)
    call_metadata.extend((name.lower(), value) for name, value in (metadata or []))

    effective_timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT_SECONDS

    def _default_factory(version: ReflectionVersion) -> ReflectionTransport:
        return _build_grpc_transport(
            target,
            version,
            metadata=call_metadata,
            timeout=effective_timeout,
            secure=secure,
            channel_credentials=channel_credentials,
        )

    factory = transport_factory or _default_factory

    # 3) Crawl v1, falling back to v1alpha on UNIMPLEMENTED. The last terminal/empty reason is kept
    #    so a failed run explains itself.
    last_reason: Optional[str] = None
    for version in (ReflectionVersion.V1, ReflectionVersion.V1ALPHA):
        outcome = _crawl_version(version, factory)
        if outcome.ok and outcome.result is not None:
            return outcome.result
        last_reason = outcome.reason
        if not outcome.retry_other_version:
            # A terminal failure (unreachable / no services); trying the other version won't help.
            break

    return GrpcReflectionResult(
        ok=False,
        reason=last_reason or "gRPC reflection produced no surface",
    )


class _CrawlVersionResult:
    """Internal: the classified result of :func:`_crawl_version` (success or a typed failure).

    ``result`` holds a successful :class:`GrpcReflectionResult`; otherwise ``reason`` explains the
    failure and ``retry_other_version`` says whether falling back to the other reflection version
    is worth attempting.
    """

    __slots__ = ("ok", "result", "reason", "retry_other_version")

    def __init__(
        self,
        *,
        result: Optional[GrpcReflectionResult] = None,
        reason: Optional[str] = None,
        retry_other_version: bool = False,
    ) -> None:
        self.ok = result is not None and result.ok
        self.result = result
        self.reason = reason
        self.retry_other_version = retry_other_version


def _crawl_version(
    version: ReflectionVersion,
    factory: Callable[[ReflectionVersion], ReflectionTransport],
) -> _CrawlVersionResult:
    """Run a full crawl against one reflection ``version`` and classify the outcome."""
    try:
        transport = factory(version)
    except ReflectionVersionUnsupportedError as exc:
        return _CrawlVersionResult(reason=str(exc), retry_other_version=True)
    except ReflectionConnectionError as exc:
        return _CrawlVersionResult(reason=str(exc), retry_other_version=False)

    try:
        try:
            service_names = transport.list_services()
        except ReflectionVersionUnsupportedError as exc:
            return _CrawlVersionResult(reason=str(exc), retry_other_version=True)
        except ReflectionConnectionError as exc:
            return _CrawlVersionResult(reason=str(exc), retry_other_version=False)

        services = sorted(
            {name for name in service_names if name and name not in REFLECTION_SERVICE_NAMES}
        )
        if not services:
            return _CrawlVersionResult(
                reason="server exposes no services via reflection (only the reflection service "
                "itself was advertised)",
                retry_other_version=False,
            )

        try:
            blobs = transport.files_for_symbols(services)
        except ReflectionVersionUnsupportedError as exc:
            return _CrawlVersionResult(reason=str(exc), retry_other_version=True)
        except ReflectionConnectionError as exc:
            return _CrawlVersionResult(reason=str(exc), retry_other_version=False)

        if not blobs:
            return _CrawlVersionResult(
                reason="reflection advertised services but returned no file descriptors for them",
                retry_other_version=False,
            )

        try:
            descriptor_bytes, target_files = build_descriptor_set(
                blobs, service_symbols=services
            )
            compiled = read_file_descriptor_set(descriptor_bytes, target_files=target_files)
        except (GrpcReflectionError, ProtoDescriptorError) as exc:
            return _CrawlVersionResult(reason=str(exc), retry_other_version=False)

        result = GrpcReflectionResult(
            ok=True,
            reflection_version=version,
            services=services,
            descriptor_set_bytes=descriptor_bytes,
            summary=compiled.summary,
            target_files=list(target_files),
            reason=None,
        )
        return _CrawlVersionResult(result=result)
    finally:
        try:
            transport.close()
        except Exception:  # pragma: no cover - best-effort channel cleanup
            pass
