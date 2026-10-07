"""Unit tests for the SSRF guard (#3612).

The guard vets user-supplied URLs before the import-from-URL and public
repository-registration paths fetch them. DNS resolution is the only external
dependency, so it is mocked to return controlled addresses; every other check
runs in-process.
"""

from unittest.mock import patch

import httpx
import pytest

from app import ssrf_guard
from app.ssrf_guard import SSRFError, build_guarded_client, validate_url


def _resolve_to(*ips):
    """Patch host resolution so ``validate_url`` sees ``ips`` for any host."""
    return patch.object(ssrf_guard, "_resolve_host_ips", lambda host: list(ips))


# ===========================================================================
# Scheme / credential / shape checks (always enforced)
# ===========================================================================


@pytest.mark.parametrize("url", ["ftp://example.com/x", "file:///etc/passwd", "gopher://h/1"])
def test_validate_url_rejects_non_http_schemes(url):
    with pytest.raises(SSRFError, match="scheme"):
        validate_url(url)


def test_validate_url_rejects_credentials_in_url():
    with _resolve_to("93.184.216.34"):
        with pytest.raises(SSRFError, match="credentials"):
            validate_url("https://user:pass@example.com/spec.json")


def test_validate_url_rejects_missing_host():
    with pytest.raises(SSRFError):
        validate_url("http:///nohost")


# ===========================================================================
# IP filtering — internal targets are blocked, public ones allowed
# ===========================================================================


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",        # loopback
        "10.0.0.5",         # RFC1918
        "172.16.4.4",       # RFC1918
        "192.168.1.10",     # RFC1918
        "169.254.169.254",  # link-local / cloud metadata
        "0.0.0.0",          # unspecified
        "100.64.1.1",       # CGNAT / shared
        "::1",              # IPv6 loopback
        "fd00::1",          # IPv6 unique-local
        "::ffff:10.0.0.1",  # IPv4-mapped private
        "64:ff9b::a9fe:a9fe",  # NAT64 of 169.254.169.254 (AGX-2.3 / SIM-3.2 parity)
        "64:ff9b::a00:1",   # NAT64 of 10.0.0.1
        "2002:a00:1::",     # 6to4
    ],
)
def test_validate_url_blocks_internal_addresses(ip):
    with _resolve_to(ip):
        with pytest.raises(SSRFError, match="non-public"):
            validate_url("https://attacker.example/spec.json")


def test_validate_url_allows_a_nat64_public_address():
    with _resolve_to("64:ff9b::808:808"):  # NAT64 of 8.8.8.8
        validate_url("https://example.com/openapi.json")  # no raise


@pytest.mark.parametrize(
    ("address", "blocked"),
    [
        ("169.254.169.254", True),
        ("100.100.100.200", True),  # Alibaba metadata (CGNAT range)
        ("fd00:ec2::254", True),    # AWS IPv6 metadata (unique-local)
        ("fe80::1%eth0", True),     # zone index ignored
        ("64:ff9b::7f00:1", True),  # NAT64 of loopback
        ("not-an-ip", True),        # unparseable fails closed
        ("", True),
        ("93.184.216.34", False),
        ("2606:4700::1111", False),
    ],
)
def test_is_disallowed_address(address, blocked):
    assert ssrf_guard.is_disallowed_address(address) is blocked


def test_validate_url_allows_public_address():
    with _resolve_to("93.184.216.34"):
        validate_url("https://example.com/openapi.json")  # no raise


def test_validate_url_blocks_when_any_resolved_ip_is_internal():
    # DNS that returns one public and one internal address must be rejected
    # (defends against round-robin / rebinding that mixes records).
    with _resolve_to("93.184.216.34", "127.0.0.1"):
        with pytest.raises(SSRFError, match="non-public"):
            validate_url("https://mixed.example/spec.json")


def test_validate_url_blocks_unresolvable_host():
    def _boom(host):
        raise SSRFError(f"could not resolve host '{host}'")

    with patch.object(ssrf_guard, "_resolve_host_ips", _boom):
        with pytest.raises(SSRFError, match="resolve"):
            validate_url("https://does-not-exist.invalid/x")


# ===========================================================================
# Dev opt-out: APIOME_SSRF_ALLOW_PRIVATE skips IP filtering only
# ===========================================================================


def test_allow_private_skips_ip_checks_but_keeps_scheme_check():
    with patch.object(ssrf_guard.settings, "ssrf_allow_private", True):
        # Internal IP now allowed...
        with _resolve_to("127.0.0.1"):
            validate_url("http://localhost/spec.json")
        # ...but scheme is still enforced.
        with pytest.raises(SSRFError, match="scheme"):
            validate_url("file:///etc/passwd")


# ===========================================================================
# Guarded client: the request hook validates every hop (incl. redirects)
# ===========================================================================


def test_guarded_client_blocks_request_to_internal_host():
    # A MockTransport stands in for the network; the guard hook should fire and
    # raise before the transport is ever reached for an internal target.
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="ok"))
    with _resolve_to("169.254.169.254"):
        with build_guarded_client(transport=transport) as client:
            with pytest.raises(SSRFError):
                client.get("http://metadata.internal/latest/meta-data/")


def test_guarded_client_allows_request_to_public_host():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="ok"))
    with _resolve_to("93.184.216.34"):
        with build_guarded_client(transport=transport) as client:
            resp = client.get("https://example.com/spec.json")
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_guarded_client_allows_private_when_flag_set():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="ok"))
    with build_guarded_client(transport=transport, allow_private=True) as client:
        resp = client.get("http://127.0.0.1:8775/mock/pets")
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_guarded_client_private_still_rejects_bad_scheme():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="ok"))
    with build_guarded_client(transport=transport, allow_private=True) as client:
        with pytest.raises(SSRFError, match="scheme"):
            client.get("file:///etc/passwd")


def test_guarded_client_blocks_redirect_to_internal_host():
    # First hop is public and returns a 302 to an internal host; the guard must
    # reject the second hop. Resolution maps the public host to a public IP and
    # the internal host to a loopback IP.
    def _resolve(host):
        return ["127.0.0.1"] if host == "internal.example" else ["93.184.216.34"]

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "public.example":
            return httpx.Response(302, headers={"Location": "http://internal.example/secrets"})
        return httpx.Response(200, text="should-not-reach")

    transport = httpx.MockTransport(_handler)
    with patch.object(ssrf_guard, "_resolve_host_ips", _resolve):
        with build_guarded_client(transport=transport, follow_redirects=True) as client:
            with pytest.raises(SSRFError, match="non-public"):
                client.get("https://public.example/start")
