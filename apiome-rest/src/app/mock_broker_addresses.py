"""Broker bootstrap addresses: normalization and the SSRF rule — XPC-2.1 (#5735).

A mock broker binding names a tenant's Kafka cluster as a list of ``host:port`` bootstrap
entries. Apiome connects to them (the ``/test`` probe now, the XPC-2.2 producer and the XPC-2.3
consumer later), so a binding is a URL-shaped SSRF vector like any other tenant-supplied address:
pointed at ``169.254.169.254:80`` or ``10.0.0.5:5432``, the platform would be the confused deputy.

This module holds the two halves of the defence:

* :func:`normalize_bootstrap` turns what a person typed into the canonical stored form: lower-case
  host, explicit port (``9092`` by default), IPv6 literals bracketed, duplicates removed, and
  anything with a scheme, userinfo, path, query or whitespace refused. The V372 CHECK constraint
  is the backstop for that shape.
* :func:`check_bootstrap` resolves every host and refuses the binding when *any* resolved address
  is private, loopback, link-local, multicast, reserved or unspecified, using
  :func:`app.ssrf_guard.is_disallowed_address` — the same address rule as every other outbound
  fetch. It returns the checked addresses so a caller can connect to exactly what it checked.

Two escape hatches, both off by default:

* **The dev broker.** ``APIOME_MOCK_DEV_BROKER_BOOTSTRAP`` (set by ``docker compose --profile
  broker``) names the compose-network Redpanda. A bootstrap entry equal to one of its entries —
  same host *and* port — skips the address check. Nothing else does.
* **``APIOME_MOCK_BROKER_ALLOW_PRIVATE=true``** lifts the address check for broker bindings only,
  for local development against a broker on your own network. It mirrors the mock's
  ``callback_allow_private``. Shape rules always apply.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from .config import settings
from .ssrf_guard import is_disallowed_address

__all__ = [
    "BOOTSTRAP_MAX_ENTRIES",
    "DEFAULT_KAFKA_PORT",
    "BootstrapAddressError",
    "BootstrapEntry",
    "CheckedHost",
    "check_bootstrap",
    "dev_broker_bootstrap",
    "normalize_bootstrap",
    "parse_entry",
]

#: The Kafka port an entry gets when it names none.
DEFAULT_KAFKA_PORT = 9092

#: Most entries one binding may list (mirrors the V372 cardinality CHECK).
BOOTSTRAP_MAX_ENTRIES = 16

#: Longest accepted hostname (RFC 1035 total length).
_HOST_MAX_CHARS = 253

#: Characters a hostname may contain once lower-cased (letters, digits, ``-``, ``.``, ``_``; the
#: underscore appears in real compose service names).
_HOST_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-._")


class BootstrapAddressError(ValueError):
    """A bootstrap list was refused.

    Attributes:
        disallowed: ``True`` when the refusal is the SSRF address rule (a host resolves to a
            non-public address, or cannot be resolved), so the route answers
            ``broker-address-disallowed``; ``False`` for a malformed entry.
        errors: One message per problem. Messages name hosts, never credentials.
    """

    def __init__(self, *errors: str, disallowed: bool = False) -> None:
        self.disallowed = disallowed
        self.errors: List[str] = [str(error) for error in errors if error]
        super().__init__("; ".join(self.errors) or "invalid bootstrap address")


@dataclass(frozen=True)
class BootstrapEntry:
    """One normalized bootstrap entry.

    Attributes:
        host: The lower-cased hostname or IP literal, without brackets.
        port: The TCP port.
    """

    host: str
    port: int

    def render(self) -> str:
        """Return the stored ``host:port`` form (an IPv6 literal is bracketed)."""
        return f"[{self.host}]:{self.port}" if ":" in self.host else f"{self.host}:{self.port}"


@dataclass(frozen=True)
class CheckedHost:
    """A bootstrap entry after the address check.

    Attributes:
        entry: The normalized entry.
        addresses: The addresses it resolved to and that passed the check, in resolver order.
            Empty when the check was skipped (dev broker, or private addresses allowed): the
            caller then connects by name.
        exempt: ``True`` when the entry is the configured dev broker.
    """

    entry: BootstrapEntry
    addresses: Tuple[str, ...]
    exempt: bool = False


def _parse_port(text: str, raw: str) -> int:
    """Parse a port, refusing anything outside 1–65535.

    Args:
        text: The port digits.
        raw: The whole entry, for the message.

    Returns:
        The port.

    Raises:
        BootstrapAddressError: When the port is not a number in range.
    """
    if not text.isdigit() or not 1 <= int(text) <= 65535:
        raise BootstrapAddressError(f"'{raw}' has no valid port (1–65535)")
    return int(text)


def parse_entry(raw: str) -> BootstrapEntry:
    """Parse one ``host[:port]`` entry into its normalized form.

    Accepted: ``broker.example.com``, ``broker.example.com:9093``, ``203.0.113.7:9092``,
    ``[2001:db8::1]:9092``. Refused: a scheme (``kafka://``), userinfo (``user@``), a path, query
    or fragment, whitespace inside the entry, an empty host, an unbracketed IPv6 literal.

    Args:
        raw: What the person typed.

    Returns:
        The entry, host lower-cased and port defaulted to :data:`DEFAULT_KAFKA_PORT`.

    Raises:
        BootstrapAddressError: When the entry is malformed.
    """
    text = (raw or "").strip()
    if not text:
        raise BootstrapAddressError("a bootstrap entry is empty")
    if any(char.isspace() for char in text):
        raise BootstrapAddressError(f"'{text}' contains whitespace")
    if "://" in text:
        raise BootstrapAddressError(f"'{text}' has a scheme; give host:port only")
    if "@" in text:
        raise BootstrapAddressError(f"'{text}' contains credentials; use the SASL credential")
    if any(char in text for char in "/?#,"):
        raise BootstrapAddressError(f"'{text}' is not a host:port entry")

    if text.startswith("["):
        close = text.find("]")
        if close < 0:
            raise BootstrapAddressError(f"'{text}' has an unclosed IPv6 bracket")
        host = text[1:close]
        rest = text[close + 1 :]
        if rest and not rest.startswith(":"):
            raise BootstrapAddressError(f"'{text}' is not a host:port entry")
        port = _parse_port(rest[1:], text) if rest else DEFAULT_KAFKA_PORT
        try:
            literal = ipaddress.IPv6Address(host)
        except ValueError as exc:
            raise BootstrapAddressError(f"'{text}' is not a valid IPv6 literal") from exc
        return BootstrapEntry(host=literal.compressed, port=port)

    if text.count(":") > 1:
        raise BootstrapAddressError(f"'{text}': write an IPv6 literal in brackets, e.g. [::1]:9092")
    host, _, port_text = text.partition(":")
    host = host.lower().rstrip(".")
    if not host:
        raise BootstrapAddressError(f"'{text}' has no host")
    if len(host) > _HOST_MAX_CHARS or not set(host) <= _HOST_CHARS:
        raise BootstrapAddressError(f"'{text}' is not a valid hostname")
    port = _parse_port(port_text, text) if port_text or text.endswith(":") else DEFAULT_KAFKA_PORT
    return BootstrapEntry(host=host, port=port)


def normalize_bootstrap(entries: Iterable[str]) -> List[BootstrapEntry]:
    """Normalize a bootstrap list, listing every malformed entry at once.

    Args:
        entries: The entries as submitted. A single entry may itself be comma-separated
            (``"a:9092,b:9092"``), the way Kafka clients accept ``bootstrap.servers``.

    Returns:
        The entries, normalized, in submission order, duplicates removed.

    Raises:
        BootstrapAddressError: When the list is empty, too long, or any entry is malformed.
    """
    raw: List[str] = []
    for entry in entries:
        raw.extend(part for part in str(entry or "").split(",") if part.strip())

    problems: List[str] = []
    out: List[BootstrapEntry] = []
    for item in raw:
        try:
            parsed = parse_entry(item)
        except BootstrapAddressError as exc:
            problems.extend(exc.errors)
            continue
        if parsed not in out:
            out.append(parsed)
    if not raw:
        problems.append("bootstrap must name at least one host:port")
    if len(out) > BOOTSTRAP_MAX_ENTRIES:
        problems.append(f"bootstrap may list at most {BOOTSTRAP_MAX_ENTRIES} hosts")
    if problems:
        raise BootstrapAddressError(*problems)
    return out


def dev_broker_bootstrap() -> List[BootstrapEntry]:
    """Return the configured dev broker entries (``APIOME_MOCK_DEV_BROKER_BOOTSTRAP``).

    Returns:
        The normalized entries, or ``[]`` when the variable is unset or malformed. A malformed
        value grants no exemption rather than failing startup: the variable only ever widens
        what is allowed, so ignoring it is the safe failure.
    """
    value = (settings.mock_dev_broker_bootstrap or "").strip()
    if not value:
        return []
    try:
        return normalize_bootstrap([value])
    except BootstrapAddressError:
        return []


def _resolve(entry: BootstrapEntry) -> List[str]:
    """Resolve an entry's host to every A/AAAA address (an IP literal resolves to itself).

    Args:
        entry: The entry.

    Returns:
        The addresses, de-duplicated, in resolver order.

    Raises:
        BootstrapAddressError: (``disallowed``) when the host does not resolve: an unresolvable
            host is refused rather than allowed, as in :mod:`app.ssrf_guard`.
    """
    try:
        infos = socket.getaddrinfo(entry.host, entry.port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as exc:
        raise BootstrapAddressError(
            f"could not resolve broker host '{entry.host}'", disallowed=True
        ) from exc
    addresses: List[str] = []
    for info in infos:
        address = str(info[4][0]) if info[4] else ""
        if address and address not in addresses:
            addresses.append(address)
    if not addresses:
        raise BootstrapAddressError(
            f"could not resolve broker host '{entry.host}'", disallowed=True
        )
    return addresses


def check_bootstrap(
    entries: Sequence[BootstrapEntry], *, dev_entries: Optional[Sequence[BootstrapEntry]] = None
) -> List[CheckedHost]:
    """Resolve every bootstrap host and refuse any that reaches a non-public address.

    Args:
        entries: Normalized entries (:func:`normalize_bootstrap`).
        dev_entries: The dev broker's entries; defaults to :func:`dev_broker_bootstrap`.

    Returns:
        One :class:`CheckedHost` per entry, carrying the addresses that passed.

    Raises:
        BootstrapAddressError: (``disallowed``) listing every host that resolves to a non-public
            address or does not resolve. The messages name the host the caller typed, never the
            address it resolved to, and never a credential.
    """
    exempt = set(dev_broker_bootstrap() if dev_entries is None else dev_entries)
    problems: List[str] = []
    checked: List[CheckedHost] = []
    for entry in entries:
        if entry in exempt:
            checked.append(CheckedHost(entry=entry, addresses=(), exempt=True))
            continue
        if settings.mock_broker_allow_private:
            checked.append(CheckedHost(entry=entry, addresses=()))
            continue
        try:
            addresses = _resolve(entry)
        except BootstrapAddressError as exc:
            problems.extend(exc.errors)
            continue
        if any(is_disallowed_address(address) for address in addresses):
            # The address itself is not quoted: echoing what an internal name resolves to would
            # turn this refusal into a way to map the private network.
            problems.append(
                f"broker host '{entry.host}' resolves to a non-public address; "
                "a broker binding must reach a public address"
            )
            continue
        checked.append(CheckedHost(entry=entry, addresses=tuple(addresses)))
    if problems:
        raise BootstrapAddressError(*problems, disallowed=True)
    return checked
