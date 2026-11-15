"""The broker binding connectivity test — XPC-2.1 (#5735).

``POST …/mock/broker-bindings/{id}/test`` answers one question: *can Apiome reach this broker with
this credential?* It does the least that answers it — open one connection to a bootstrap host,
complete the TLS and SASL handshakes, and ask for cluster metadata — and nothing more: no topic is
created, read or written, and the broker addresses the metadata advertises are counted, never
connected to (an advertised address is broker-controlled and could point anywhere).

**Address rule at connect time.** Every bootstrap host is resolved and checked again
(:func:`app.mock_broker_addresses.check_bootstrap`) immediately before connecting, so a DNS
record changed since the binding was stored can't steer the probe inward. A plaintext connection
goes to the exact address that passed the check; a TLS one connects by hostname (certificate
verification needs it), which leaves the resolve-to-connect window that :mod:`app.ssrf_guard`
documents for HTTP fetches.

**Outcomes are categories, never messages.** The result is ``reachable`` or ``unreachable`` with
one of the :data:`REASONS`; the broker's error text, which can quote the username, is never
returned or logged. A wrong password is ``unreachable: auth``.

**Cached for 60 seconds** per binding *state* (id, address, flags, credential version and rotation
time), so repeated clicks don't hammer a cluster, and a rotation or an edit is tested afresh.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Literal, Mapping, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .mock_broker_addresses import BootstrapAddressError, CheckedHost, check_bootstrap
from .mock_broker_bindings import BrokerCredential, open_credential, stored_bootstrap

logger = logging.getLogger(__name__)

__all__ = [
    "CACHE_TTL_SECONDS",
    "REASONS",
    "BrokerProbeResult",
    "ProbeAttempt",
    "clear_probe_cache",
    "probe_binding",
    "security_protocol",
]

#: How long one probe result is reused for the same binding state.
CACHE_TTL_SECONDS = 60.0

#: Most results the in-process cache holds; the oldest is evicted past this.
_CACHE_MAX_ENTRIES = 512

#: Per-host budget for connect + handshakes + metadata.
_HOST_TIMEOUT_SECONDS = 5.0

#: Budget for the whole probe, across every bootstrap host.
_PROBE_TIMEOUT_SECONDS = 15.0

#: Why a broker is unreachable. ``auth``: the broker refused the SASL credential (or its
#: mechanism); ``credential-unavailable``: the stored credential could not be opened on this
#: deployment; ``address-disallowed``: a host now resolves to a non-public address, or no longer
#: resolves; ``tls``: the TLS handshake or certificate check failed; ``timeout``: no answer in
#: time; ``connect``: the connection was refused or dropped; ``protocol``: it answered, but not as
#: a Kafka broker.
REASONS = (
    "auth",
    "credential-unavailable",
    "address-disallowed",
    "tls",
    "timeout",
    "connect",
    "protocol",
)

Reason = Literal[
    "auth", "credential-unavailable", "address-disallowed", "tls", "timeout", "connect", "protocol"
]


class BrokerProbeResult(BaseModel):
    """What one connectivity test found.

    Attributes:
        binding_id: The binding tested.
        status: ``reachable`` or ``unreachable``.
        reason: Why it is unreachable (one of :data:`REASONS`), or ``None`` when reachable.
        summary: ``"reachable"`` or ``"unreachable: <reason>"``, for a status line.
        bootstrap: The entry that answered (reachable) or ``None``.
        brokers: How many brokers the cluster metadata lists (reachable only).
        topics: How many topics the metadata lists (reachable only).
        checked_at: When the probe actually ran (earlier than now when ``cached``).
        cached: Whether this result came from the 60-second cache.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    binding_id: str = Field(serialization_alias="bindingId")
    status: Literal["reachable", "unreachable"]
    reason: Optional[Reason] = None
    summary: str
    bootstrap: Optional[str] = None
    brokers: Optional[int] = None
    topics: Optional[int] = None
    checked_at: datetime = Field(serialization_alias="checkedAt")
    cached: bool = False


@dataclass(frozen=True)
class ProbeAttempt:
    """One connection the probe will make: where, and with what.

    Attributes:
        host: What to connect to: the checked address for plaintext, the hostname for TLS.
        port: The port.
        label: The stored ``host:port`` entry, for the result.
        security_protocol: ``PLAINTEXT``, ``SSL``, ``SASL_PLAINTEXT`` or ``SASL_SSL``.
        ssl_context: The TLS context, or ``None`` without TLS.
        sasl_mechanism: The mechanism, or ``None``.
        credential: The opened credential, or ``None``.
        client_id: The Kafka ``client.id`` to present.
    """

    host: str
    port: int
    label: str
    security_protocol: str
    ssl_context: Optional[ssl.SSLContext]
    sasl_mechanism: Optional[str]
    credential: Optional[BrokerCredential] = field(repr=False, default=None)
    client_id: str = "apiome-mock"


#: The connector: given an attempt, return ``(brokers, topics)`` or raise. Injectable for tests.
Connector = Callable[[ProbeAttempt], Awaitable[Tuple[int, int]]]

_cache: Dict[Tuple[Any, ...], Tuple[float, BrokerProbeResult]] = {}


def clear_probe_cache() -> None:
    """Forget every cached result (tests, and after a binding is deleted)."""
    _cache.clear()


def security_protocol(tls_enabled: bool, sasl_mechanism: Optional[str]) -> str:
    """Return the Kafka ``security.protocol`` for a binding's flags.

    Args:
        tls_enabled: Whether TLS is on.
        sasl_mechanism: The SASL mechanism, or ``None``.

    Returns:
        ``PLAINTEXT``, ``SSL``, ``SASL_PLAINTEXT`` or ``SASL_SSL``.
    """
    if sasl_mechanism:
        return "SASL_SSL" if tls_enabled else "SASL_PLAINTEXT"
    return "SSL" if tls_enabled else "PLAINTEXT"


def _ssl_context(verify: bool) -> ssl.SSLContext:
    """Build the TLS context: system trust store and hostname check, unless ``verify`` is off."""
    context = ssl.create_default_context()
    if not verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def _cache_key(row: Mapping[str, Any]) -> Tuple[Any, ...]:
    """Key a result by everything that could change it."""
    return (
        str(row.get("id")),
        tuple(row.get("bootstrap") or ()),
        bool(row.get("tls_enabled")),
        bool(row.get("tls_verify", True)),
        row.get("sasl_mechanism"),
        row.get("key_version"),
        str(row.get("rotated_at") or ""),
        str(row.get("client_id_prefix") or ""),
    )


def _result(
    binding_id: str,
    *,
    reason: Optional[str] = None,
    bootstrap: Optional[str] = None,
    brokers: Optional[int] = None,
    topics: Optional[int] = None,
) -> BrokerProbeResult:
    """Build a fresh result."""
    return BrokerProbeResult(
        binding_id=binding_id,
        status="unreachable" if reason else "reachable",
        reason=reason,
        summary=f"unreachable: {reason}" if reason else "reachable",
        bootstrap=bootstrap,
        brokers=brokers,
        topics=topics,
        checked_at=datetime.now(timezone.utc),
    )


def classify_error(error: BaseException) -> str:
    """Map a connection failure onto one of :data:`REASONS`, without reading its message.

    Args:
        error: What the connector raised.

    Returns:
        The reason category.
    """
    from aiokafka import errors as kafka_errors

    auth_errors = (
        kafka_errors.SaslAuthenticationFailed,
        kafka_errors.AuthenticationFailedError,
        kafka_errors.AuthenticationMethodNotSupported,
        kafka_errors.UnsupportedSaslMechanismError,
        kafka_errors.IllegalSaslStateError,
        kafka_errors.ClusterAuthorizationFailedError,
        kafka_errors.TopicAuthorizationFailedError,
    )
    if isinstance(error, auth_errors):
        return "auth"
    if isinstance(error, ssl.SSLError):
        return "tls"
    if isinstance(error, (asyncio.TimeoutError, TimeoutError, kafka_errors.KafkaTimeoutError)):
        return "timeout"
    if isinstance(error, (OSError, kafka_errors.KafkaConnectionError)):
        # aiokafka wraps a TLS failure in a connection error; look one level down.
        cause = error.__cause__ or error.__context__
        if isinstance(cause, ssl.SSLError):
            return "tls"
        return "connect"
    if isinstance(error, ValueError):
        # aiokafka's SCRAM client raises ValueError when the server's proof does not match.
        return "auth"
    return "protocol"


async def kafka_connect(attempt: ProbeAttempt) -> Tuple[int, int]:
    """Open one Kafka connection, handshake, fetch metadata, and close it.

    Args:
        attempt: Where and how to connect.

    Returns:
        ``(brokers, topics)`` from the cluster metadata.

    Raises:
        Exception: Whatever the connection raised; :func:`classify_error` sorts it.
    """
    from aiokafka.conn import create_conn
    from aiokafka.protocol.metadata import MetadataRequest

    credential = attempt.credential
    conn = await create_conn(
        attempt.host,
        attempt.port,
        client_id=attempt.client_id,
        request_timeout_ms=int(_HOST_TIMEOUT_SECONDS * 1000),
        ssl_context=attempt.ssl_context,
        security_protocol=attempt.security_protocol,
        sasl_mechanism=attempt.sasl_mechanism,
        sasl_plain_username=credential.username if credential else None,
        sasl_plain_password=credential.password if credential else None,
    )
    try:
        # ``None`` lists every topic (counting is all we do); topic auto-creation is off, so the
        # probe can never create a topic as a side effect.
        metadata = await conn.send(MetadataRequest(None, allow_auto_topic_creation=False))
    finally:
        conn.close()
    return len(getattr(metadata, "brokers", []) or []), len(getattr(metadata, "topics", []) or [])


def _attempts(
    row: Mapping[str, Any], checked: List[CheckedHost], credential: Optional[BrokerCredential]
) -> List[ProbeAttempt]:
    """Expand checked hosts into connection attempts, pinning plaintext ones to their address."""
    tls_enabled = bool(row.get("tls_enabled"))
    context = _ssl_context(bool(row.get("tls_verify", True))) if tls_enabled else None
    protocol = security_protocol(tls_enabled, row.get("sasl_mechanism"))
    client_id = f"{row.get('client_id_prefix') or 'apiome-mock'}-probe"
    attempts: List[ProbeAttempt] = []
    for host in checked:
        # TLS needs the hostname for SNI and verification; plaintext goes to the checked address.
        targets = [host.entry.host] if tls_enabled or not host.addresses else list(host.addresses)
        for target in targets:
            attempts.append(
                ProbeAttempt(
                    host=target,
                    port=host.entry.port,
                    label=host.entry.render(),
                    security_protocol=protocol,
                    ssl_context=context,
                    sasl_mechanism=row.get("sasl_mechanism"),
                    credential=credential,
                    client_id=client_id,
                )
            )
    return attempts


async def _run(row: Mapping[str, Any], connector: Connector) -> BrokerProbeResult:
    """Probe a binding once, uncached."""
    binding_id = str(row.get("id"))
    credential: Optional[BrokerCredential] = None
    if row.get("sasl_mechanism"):
        credential = open_credential(row)
        if credential is None:
            return _result(binding_id, reason="credential-unavailable")

    try:
        checked = await asyncio.to_thread(check_bootstrap, stored_bootstrap(row))
    except BootstrapAddressError:
        return _result(binding_id, reason="address-disallowed")

    # The most specific failure wins: an auth refusal from one host says more than a timeout from
    # another, so keep trying hosts and report the most telling reason if none answers.
    priority = {reason: index for index, reason in enumerate(REASONS)}
    worst: Optional[str] = None
    for attempt in _attempts(row, checked, credential):
        try:
            brokers, topics = await asyncio.wait_for(connector(attempt), _HOST_TIMEOUT_SECONDS)
        except Exception as exc:  # noqa: BLE001 - every failure is categorised, none propagates
            reason = classify_error(exc)
            # The type only: a broker's message can quote the username.
            logger.info(
                "Broker probe %s via %s: %s (%s)", binding_id, attempt.label, reason, type(exc).__name__
            )
            if worst is None or priority[reason] < priority[worst]:
                worst = reason
            if reason == "auth":
                # The credential is wrong for the cluster; other hosts will say the same.
                break
            continue
        return _result(binding_id, bootstrap=attempt.label, brokers=brokers, topics=topics)
    return _result(binding_id, reason=worst or "connect")


async def probe_binding(
    row: Mapping[str, Any], *, connector: Optional[Connector] = None, now: Optional[float] = None
) -> BrokerProbeResult:
    """Test a binding, reusing a result less than 60 seconds old for the same binding state.

    Args:
        row: The stored binding, *with* its ciphertext (``mock_broker_bindings.get_binding``).
        connector: How to connect; :func:`kafka_connect` by default.
        now: The monotonic clock reading (tests).

    Returns:
        The result; ``cached`` is ``True`` when it came from the cache.
    """
    clock = time.monotonic() if now is None else now
    key = _cache_key(row)
    hit = _cache.get(key)
    if hit is not None and clock - hit[0] < CACHE_TTL_SECONDS:
        return hit[1].model_copy(update={"cached": True})

    try:
        result = await asyncio.wait_for(_run(row, connector or kafka_connect), _PROBE_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        result = _result(str(row.get("id")), reason="timeout")

    if len(_cache) >= _CACHE_MAX_ENTRIES:
        _cache.pop(min(_cache, key=lambda k: _cache[k][0]))
    _cache[key] = (clock, result)
    return result
