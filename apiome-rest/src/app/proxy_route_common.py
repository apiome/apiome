"""Shared reading rules for the reverse-proxy route sources — FMT-7.5 (#5459).

Traefik, nginx, HAProxy, Consul and Tyk all describe a routing surface in a config
language that was never meant to be a spec. Their parsers are separate modules, but they
face the same handful of problems, and the answers live here once (alongside the
service-mesh rules in :mod:`app.mesh_route_common`, which these parsers also use):

* **JSON with an honest truncation verdict.** Consul and Tyk documents are JSON. A JSON
  error is a *truncation* only when the text ended with a container still open — a
  trailing comma or a missing comma inside a closed document is a malformed one.
  :func:`load_json_document` makes that call from the bracket balance, not the error text.
* **Upstream addresses.** Every format names its backends as ``host:port`` or a URL.
  :func:`split_address` is the one reader, so a port is parsed the same way everywhere.
* **Path templates** are built by :func:`app.gateway_match.path_pattern` with
  ``templated=True`` (FMT-7.6), not here, so the family has one path builder.
* **Fileset order.** A set is read root first, then the other members in path order, so
  the merged document never depends on archive order (:func:`ordered_members`).
* **The capability vocabulary.** Each adapter declares the directives it reads and the
  ones it knowingly does not as dotted construct keys; :func:`directive_capabilities`
  builds that declaration from the parser's own tables, so the capability registry and the
  per-document ledger cannot name different subsets.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, List, Mapping, Optional, Tuple

from .gateway_config_model import GatewayConfigParseError
from .payload_analysis import AnalyzerCapabilities, analyzer_capabilities

__all__ = [
    "directive_capabilities",
    "is_json_text",
    "load_json_document",
    "ordered_members",
    "split_address",
]

def is_json_text(text: str) -> bool:
    """True when ``text`` looks like a JSON object (first non-blank character ``{``)."""
    return text.lstrip().startswith("{")


def _open_containers(text: str) -> int:
    """Count JSON containers still open at the end of ``text``, ignoring string contents.

    Args:
        text: The JSON text.

    Returns:
        Open ``{``/``[`` minus closing ``}``/``]``, plus one when the text ends inside a
        string. Positive means the document stopped before it was finished.
    """
    depth = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
    return depth + (1 if in_string else 0)


def load_json_document(text: str, *, format_label: str) -> Any:
    """Parse a JSON document, telling a cut-off file from a broken one.

    Args:
        text: The decoded document.
        format_label: Human name of the format, for messages.

    Returns:
        The parsed value.

    Raises:
        GatewayConfigParseError: ``INPUT_MALFORMED`` for an empty document or a JSON syntax
            error inside a balanced document; ``INPUT_TRUNCATED`` when the text ends with an
            object, array or string still open.
    """
    if not text.strip():
        raise GatewayConfigParseError(f"{format_label} document is empty", code="INPUT_MALFORMED")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        if _open_containers(text) > 0:
            raise GatewayConfigParseError(
                f"{format_label} document is truncated: it ends with a JSON object, array or "
                f"string still open ({exc.msg} at line {exc.lineno})",
                code="INPUT_TRUNCATED",
            ) from exc
        raise GatewayConfigParseError(
            f"{format_label} document is not valid JSON: {exc.msg} at line {exc.lineno} column " f"{exc.colno}",
            code="INPUT_MALFORMED",
        ) from exc


def split_address(address: str) -> Tuple[str, Optional[str], Optional[int]]:
    """Split an upstream address into ``(host, scheme, port)``.

    Accepts a bare host, ``host:port``, ``[v6]:port`` or a URL (``http://host:port/path``).

    Args:
        address: The address as written.

    Returns:
        The host (lower-cased), the URL scheme when one was written, and the port when one
        was written and is numeric.
    """
    work = address.strip()
    scheme: Optional[str] = None
    if "://" in work:
        scheme, work = work.split("://", 1)
        scheme = scheme.lower()
    work = work.split("/", 1)[0]
    port: Optional[int] = None
    if work.startswith("["):
        host, _, rest = work[1:].partition("]")
        if rest.startswith(":") and rest[1:].isdigit():
            port = int(rest[1:])
        return host.lower(), scheme, port
    if work.count(":") == 1:
        host, _, port_text = work.partition(":")
        if port_text.isdigit():
            port = int(port_text)
        return host.lower(), scheme, port
    return work.lower(), scheme, port


def ordered_members(members: Mapping[str, str], root: Optional[str]) -> List[str]:
    """A fileset's member paths, root first and the rest in path order.

    Args:
        members: Member path → text.
        root: The root member, when known.

    Returns:
        The read order.
    """
    ordered = sorted(members)
    if root in members:
        ordered = [root] + [path for path in ordered if path != root]
    return ordered


def directive_capabilities(
    prefix: str,
    *,
    read: Iterable[str],
    declared: Iterable[str],
    carried: Iterable[str] = (),
) -> AnalyzerCapabilities:
    """The capability declaration of a proxy-config adapter, built from its parser tables.

    Args:
        prefix: The format's construct namespace (``nginx``, ``haproxy`` …).
        read: Directives/constructs the parser models.
        declared: Constructs it recognizes and knowingly does not model — each is a
            declared parsing limit on the ledger when a document uses it.
        carried: Constructs kept by name as policy (on the operations they govern) but not
            modelled; listed as supported, since the ledger reports them kept.

    Returns:
        The normalized declaration (sorted, de-duplicated).
    """
    return analyzer_capabilities(
        supported=[f"{prefix}.{name}" for name in (*read, *carried)],
        unsupported=[f"{prefix}.{name}" for name in declared],
    )
