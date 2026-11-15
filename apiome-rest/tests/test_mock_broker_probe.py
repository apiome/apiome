"""The broker binding connectivity probe — XPC-2.1 (#5735).

The Kafka connection is an injected connector, and DNS is faked, so these run offline: they pin
how failures are categorised (a wrong password is ``auth``), where the probe connects (the checked
address for plaintext, the hostname for TLS), that the address rule runs again at test time, and
the 60-second cache.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import socket
import ssl
from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest
from aiokafka import errors as kafka_errors

from app import mock_broker_addresses as addresses
from app import mock_broker_bindings
from app.config import settings
from app.mock_broker_probe import (
    CACHE_TTL_SECONDS,
    ProbeAttempt,
    classify_error,
    clear_probe_cache,
    probe_binding,
    security_protocol,
)

_DNS: Dict[str, List[str]] = {"broker.example.com": ["8.8.8.8", "8.8.4.4"], "b2.example.com": ["1.1.1.1"]}
_PASSWORD = "PROBE-secret-pw-77"


@pytest.fixture(autouse=True)
def _environment(monkeypatch):
    """Fake DNS, one master key, and an empty cache."""

    def fake_getaddrinfo(host, port, *args, **kwargs):
        import ipaddress

        try:
            ipaddress.ip_address(host)
            ips = [host]
        except ValueError:
            if host not in _DNS:
                raise socket.gaierror("nx")
            ips = _DNS[host]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]

    monkeypatch.setattr(addresses.socket, "getaddrinfo", fake_getaddrinfo)
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "broker_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "broker_credential_active_key_version", None)
    monkeypatch.setattr(settings, "mock_broker_allow_private", False)
    monkeypatch.setattr(settings, "mock_dev_broker_bootstrap", None)
    clear_probe_cache()
    yield
    clear_probe_cache()


def _row(**overrides: Any) -> Dict[str, Any]:
    """A stored binding row with a sealed SCRAM credential."""
    blob, version = mock_broker_bindings._CIPHER.seal({"username": "svc", "password": _PASSWORD})
    row: Dict[str, Any] = {
        "id": "99999999-9999-4999-8999-999999999999",
        "version_id": "55555555-5555-4555-8555-555555555555",
        "protocol": "kafka",
        "bootstrap": ["broker.example.com:9092"],
        "tls_enabled": False,
        "tls_verify": True,
        "sasl_mechanism": "SCRAM-SHA-256",
        "credential_ciphertext": blob,
        "key_version": version,
        "client_id_prefix": "acme",
        "rotated_at": None,
    }
    row.update(overrides)
    return row


class Recorder:
    """A connector that records attempts and answers from a script."""

    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.attempts: List[ProbeAttempt] = []

    async def __call__(self, attempt: ProbeAttempt):
        self.attempts.append(attempt)
        outcome = self.outcomes.pop(0) if self.outcomes else (1, 0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _probe(row: Dict[str, Any], connector: Recorder, now: float = 1000.0):
    return asyncio.run(probe_binding(row, connector=connector, now=now))


# ============================================================================
# Pure helpers
# ============================================================================
@pytest.mark.parametrize(
    ("tls", "sasl", "expected"),
    [
        (False, None, "PLAINTEXT"),
        (True, None, "SSL"),
        (False, "PLAIN", "SASL_PLAINTEXT"),
        (True, "SCRAM-SHA-512", "SASL_SSL"),
    ],
)
def test_security_protocol(tls, sasl, expected):
    assert security_protocol(tls, sasl) == expected


def _wrapped_tls_error() -> Exception:
    try:
        try:
            raise ssl.SSLCertVerificationError("bad cert")
        except ssl.SSLError as inner:
            raise kafka_errors.KafkaConnectionError("connect failed") from inner
    except kafka_errors.KafkaConnectionError as outer:
        return outer


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (kafka_errors.SaslAuthenticationFailed("bad password for svc"), "auth"),
        (kafka_errors.UnsupportedSaslMechanismError("nope"), "auth"),
        (kafka_errors.IllegalSaslStateError("state"), "auth"),
        (ValueError("Server sent wrong signature!"), "auth"),
        (ssl.SSLError("handshake"), "tls"),
        (asyncio.TimeoutError(), "timeout"),
        (kafka_errors.KafkaTimeoutError(), "timeout"),
        (ConnectionRefusedError(), "connect"),
        (kafka_errors.KafkaConnectionError("broken"), "connect"),
        (kafka_errors.UnrecognizedBrokerVersion(), "protocol"),
    ],
)
def test_errors_are_categorised_by_type(error, reason):
    assert classify_error(error) == reason


def test_a_tls_failure_wrapped_in_a_connection_error_is_tls():
    assert classify_error(_wrapped_tls_error()) == "tls"


# ============================================================================
# The probe
# ============================================================================
def test_a_reachable_broker_reports_its_metadata_counts():
    connector = Recorder((3, 12))
    result = _probe(_row(), connector)
    assert (result.status, result.reason, result.summary) == ("reachable", None, "reachable")
    assert (result.brokers, result.topics, result.bootstrap) == (3, 12, "broker.example.com:9092")
    assert result.cached is False


def test_plaintext_connects_to_the_checked_address_with_the_opened_credential():
    connector = Recorder()
    _probe(_row(), connector)
    (attempt,) = connector.attempts
    assert attempt.host == "8.8.8.8"  # pinned to what passed the address rule
    assert attempt.port == 9092
    assert attempt.security_protocol == "SASL_PLAINTEXT"
    assert attempt.sasl_mechanism == "SCRAM-SHA-256"
    assert attempt.credential.password == _PASSWORD
    assert attempt.client_id == "acme-probe"
    assert _PASSWORD not in repr(attempt)


def test_tls_connects_by_hostname_with_a_verifying_context():
    connector = Recorder()
    _probe(_row(tls_enabled=True), connector)
    (attempt,) = connector.attempts
    assert attempt.host == "broker.example.com"
    assert attempt.security_protocol == "SASL_SSL"
    assert attempt.ssl_context.check_hostname is True
    assert attempt.ssl_context.verify_mode == ssl.CERT_REQUIRED


def test_tls_verify_off_disables_certificate_checks():
    connector = Recorder()
    _probe(_row(tls_enabled=True, tls_verify=False), connector)
    context = connector.attempts[0].ssl_context
    assert context.check_hostname is False and context.verify_mode == ssl.CERT_NONE


def test_a_wrong_password_is_unreachable_auth_and_stops_trying_hosts():
    connector = Recorder(kafka_errors.SaslAuthenticationFailed(f"bad creds {_PASSWORD}"))
    result = _probe(_row(bootstrap=["broker.example.com:9092", "b2.example.com:9092"]), connector)
    assert result.summary == "unreachable: auth"
    assert len(connector.attempts) == 1
    assert _PASSWORD not in result.model_dump_json()


def test_the_next_address_is_tried_when_one_fails():
    connector = Recorder(ConnectionRefusedError(), (1, 2))
    result = _probe(_row(), connector)
    assert result.status == "reachable"
    assert [attempt.host for attempt in connector.attempts] == ["8.8.8.8", "8.8.4.4"]


def test_the_most_telling_failure_wins_when_every_host_fails():
    connector = Recorder(asyncio.TimeoutError(), ConnectionRefusedError(), ssl.SSLError("x"))
    result = _probe(_row(bootstrap=["broker.example.com:9092", "b2.example.com:9092"]), connector)
    assert result.reason == "tls"


def test_an_unopenable_credential_fails_closed_without_connecting(monkeypatch):
    row = _row()
    other = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "broker_credential_encryption_keys", json.dumps({"1": other}))
    connector = Recorder()
    assert _probe(row, connector).summary == "unreachable: credential-unavailable"
    assert connector.attempts == []


def test_the_address_rule_runs_again_at_test_time(monkeypatch):
    # Stored while public; the record now points inward.
    monkeypatch.setitem(_DNS, "broker.example.com", ["10.0.0.9"])
    connector = Recorder()
    assert _probe(_row(), connector).summary == "unreachable: address-disallowed"
    assert connector.attempts == []


def test_a_binding_without_sasl_connects_plaintext_without_a_credential():
    connector = Recorder()
    _probe(_row(sasl_mechanism=None, credential_ciphertext=None, key_version=None), connector)
    (attempt,) = connector.attempts
    assert attempt.security_protocol == "PLAINTEXT" and attempt.credential is None


def test_a_slow_broker_times_out(monkeypatch):
    monkeypatch.setattr("app.mock_broker_probe._HOST_TIMEOUT_SECONDS", 0.01)

    async def hang(attempt):
        await asyncio.sleep(1)

    result = asyncio.run(probe_binding(_row(bootstrap=["8.8.8.8:9092"]), connector=hang, now=1.0))
    assert result.summary == "unreachable: timeout"


# ============================================================================
# The cache
# ============================================================================
def test_a_result_is_reused_for_sixty_seconds():
    connector = Recorder((1, 1))
    row = _row()
    first = _probe(row, connector, now=1000.0)
    again = _probe(row, connector, now=1000.0 + CACHE_TTL_SECONDS - 1)
    assert again.cached is True and again.checked_at == first.checked_at
    assert len(connector.attempts) == 1
    later = _probe(row, connector, now=1000.0 + CACHE_TTL_SECONDS + 1)
    assert later.cached is False
    assert len(connector.attempts) == 2


def test_a_rotation_is_tested_afresh():
    connector = Recorder(kafka_errors.SaslAuthenticationFailed("x"), (1, 1))
    row = _row()
    assert _probe(row, connector).summary == "unreachable: auth"
    rotated = {**row, "rotated_at": datetime.now(timezone.utc)}
    assert _probe(rotated, connector).summary == "reachable"
