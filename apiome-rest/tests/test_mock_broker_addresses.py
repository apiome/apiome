"""Broker bootstrap normalization and the SSRF address rule — XPC-2.1 (#5735).

DNS is faked (``socket.getaddrinfo`` is patched), so these run offline and deterministically.
"""

from __future__ import annotations

import socket
from typing import Dict, List

import pytest

from app import mock_broker_addresses as addresses
from app.config import settings
from app.mock_broker_addresses import (
    BootstrapAddressError,
    BootstrapEntry,
    check_bootstrap,
    dev_broker_bootstrap,
    normalize_bootstrap,
    parse_entry,
)


@pytest.fixture
def dns(monkeypatch) -> Dict[str, List[str]]:
    """A fake resolver: map a hostname to the addresses it returns (absent ⇒ NXDOMAIN)."""
    table: Dict[str, List[str]] = {}

    def fake_getaddrinfo(host, port, *args, **kwargs):
        try:
            import ipaddress

            ipaddress.ip_address(host)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, port))]
        except ValueError:
            pass
        if host not in table:
            raise socket.gaierror("Name or service not known")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in table[host]]

    monkeypatch.setattr(addresses.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(settings, "mock_broker_allow_private", False)
    monkeypatch.setattr(settings, "mock_dev_broker_bootstrap", None)
    return table


# ============================================================================
# Normalization
# ============================================================================
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("broker.example.com", "broker.example.com:9092"),
        ("Broker.Example.COM:9093", "broker.example.com:9093"),
        ("broker.example.com.:9094", "broker.example.com:9094"),
        ("  8.8.8.8:19092 ", "8.8.8.8:19092"),
        ("[2001:4860:4860:0:0:0:0:8888]:9092", "[2001:4860:4860::8888]:9092"),
        ("[2001:4860:4860::8888]", "[2001:4860:4860::8888]:9092"),
        ("redpanda_dev:9092", "redpanda_dev:9092"),
    ],
)
def test_entries_are_normalized(raw, expected):
    assert parse_entry(raw).render() == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "kafka://broker.example.com:9092",
        "user:pass@broker.example.com:9092",
        "broker.example.com:9092/path",
        "broker.example.com:9092?x=1",
        "broker.example.com:0",
        "broker.example.com:65536",
        "broker.example.com:port",
        "broker.example.com:",
        "broker example.com",
        "2001:db8::1",
        "[2001:db8::1",
        "[not-ipv6]:9092",
        ":9092",
        "bröker.example.com",
    ],
)
def test_malformed_entries_are_refused(raw):
    with pytest.raises(BootstrapAddressError) as caught:
        parse_entry(raw)
    assert caught.value.disallowed is False


def test_a_list_is_split_on_commas_and_deduplicated():
    entries = normalize_bootstrap(["a.example.com:9092,b.example.com", "A.example.com:9092"])
    assert [entry.render() for entry in entries] == ["a.example.com:9092", "b.example.com:9092"]


def test_every_bad_entry_is_reported_at_once():
    with pytest.raises(BootstrapAddressError) as caught:
        normalize_bootstrap(["kafka://a:1", "b:0", "c.example.com:9092"])
    assert len(caught.value.errors) == 2


def test_an_empty_or_oversized_list_is_refused():
    with pytest.raises(BootstrapAddressError):
        normalize_bootstrap([])
    with pytest.raises(BootstrapAddressError):
        normalize_bootstrap([" , "])
    with pytest.raises(BootstrapAddressError) as caught:
        normalize_bootstrap([f"b{i}.example.com" for i in range(17)])
    assert "at most 16" in str(caught.value)


# ============================================================================
# The address rule
# ============================================================================
def test_a_public_host_passes_and_reports_its_addresses(dns):
    dns["broker.example.com"] = ["8.8.4.4", "8.8.8.8"]
    (checked,) = check_bootstrap(normalize_bootstrap(["broker.example.com"]))
    assert checked.addresses == ("8.8.4.4", "8.8.8.8")
    assert checked.exempt is False


@pytest.mark.parametrize(
    "address",
    ["10.0.0.5", "127.0.0.1", "169.254.169.254", "192.168.1.1", "172.16.0.1", "100.64.0.1", "0.0.0.0"],
)
def test_a_private_address_is_disallowed(dns, address):
    dns["internal.example.com"] = [address]
    with pytest.raises(BootstrapAddressError) as caught:
        check_bootstrap(normalize_bootstrap(["internal.example.com:9092"]))
    assert caught.value.disallowed is True
    # The refusal names the host, never the internal address it resolved to.
    assert "internal.example.com" in str(caught.value)
    assert address not in str(caught.value)


def test_one_private_address_among_public_ones_is_enough_to_refuse(dns):
    dns["mixed.example.com"] = ["8.8.8.8", "10.1.2.3"]
    with pytest.raises(BootstrapAddressError) as caught:
        check_bootstrap(normalize_bootstrap(["mixed.example.com"]))
    assert caught.value.disallowed


def test_private_ip_literals_and_mapped_ipv6_are_refused(dns):
    for raw in ("10.0.0.1:9092", "[::1]:9092", "[::ffff:10.0.0.1]:9092", "[fd00::1]:9092"):
        with pytest.raises(BootstrapAddressError):
            check_bootstrap(normalize_bootstrap([raw]))


def test_an_unresolvable_host_is_refused_not_allowed(dns):
    with pytest.raises(BootstrapAddressError) as caught:
        check_bootstrap(normalize_bootstrap(["nowhere.example.com"]))
    assert caught.value.disallowed is True
    assert "could not resolve" in str(caught.value)


def test_the_dev_broker_is_exempt_only_for_its_exact_host_and_port(dns, monkeypatch):
    monkeypatch.setattr(settings, "mock_dev_broker_bootstrap", "redpanda:9092")
    dns["redpanda"] = ["172.18.0.4"]
    (checked,) = check_bootstrap(normalize_bootstrap(["redpanda:9092"]))
    assert checked.exempt is True
    # Same host, another port: not the dev broker.
    with pytest.raises(BootstrapAddressError):
        check_bootstrap(normalize_bootstrap(["redpanda:9644"]))
    # Another private host: still refused.
    dns["postgres"] = ["172.18.0.2"]
    with pytest.raises(BootstrapAddressError):
        check_bootstrap(normalize_bootstrap(["postgres:5432"]))


def test_without_the_profile_variable_the_dev_host_is_not_exempt(dns):
    dns["redpanda"] = ["172.18.0.4"]
    with pytest.raises(BootstrapAddressError):
        check_bootstrap(normalize_bootstrap(["redpanda:9092"]))


def test_allow_private_lifts_the_address_check_but_not_the_shape_rules(dns, monkeypatch):
    monkeypatch.setattr(settings, "mock_broker_allow_private", True)
    (checked,) = check_bootstrap(normalize_bootstrap(["10.0.0.5:9092"]))
    assert checked.addresses == ()
    with pytest.raises(BootstrapAddressError):
        normalize_bootstrap(["kafka://10.0.0.5:9092"])


def test_dev_broker_bootstrap_reads_and_normalizes_the_variable(monkeypatch):
    monkeypatch.setattr(settings, "mock_dev_broker_bootstrap", " Redpanda:9092 ")
    assert dev_broker_bootstrap() == [BootstrapEntry(host="redpanda", port=9092)]
    monkeypatch.setattr(settings, "mock_dev_broker_bootstrap", "kafka://bad")
    assert dev_broker_bootstrap() == []
    monkeypatch.setattr(settings, "mock_dev_broker_bootstrap", "")
    assert dev_broker_bootstrap() == []
