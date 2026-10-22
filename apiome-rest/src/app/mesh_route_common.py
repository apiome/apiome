"""Shared reading rules for the service-mesh route sources — FMT-7.4 (#5458).

The ``envoy-xds`` and ``istio`` adapters read different documents but face the same
problems, so the answers live here once:

* **One match-normalization table.** Both formats map their path matchers onto the
  Gateway API path types and build every pattern through
  :func:`app.gateway_match.path_pattern` (FMT-7.6) — the one table the whole gateway
  family shares — so an Envoy ``prefix``, an Istio ``uri.prefix`` and a Gateway API
  ``PathPrefix`` can never disagree about what a prefix match is.
* **YAML streams.** Both read multi-document YAML (JSON is a YAML subset, so an xDS
  ``DiscoveryResponse`` in JSON takes the same path), with the same mapping from parser
  failures to intake-error codes.
* **Declared limits, never silent drops.** A construct the canonical model has no
  analogue for (an Envoy ``connect_matcher``, an Istio ``delegate`` or ``tcp`` block) is
  counted in a :class:`LimitCollector` and surfaced on the document's ``ignored`` list,
  which the import-preview ledger renders as ``unsupported-by-canonical-model`` rows.
* **Truncation inside valid YAML.** A file cut at a line boundary often still parses.
  :func:`raise_if_truncated_tail` recognizes the cut when the stream's final scalar is a
  value its own field grammar cannot accept (a duration with no unit, a Kubernetes
  service name that stops partway through the cluster domain).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import yaml

from .gateway_config_model import (
    GatewayConfigParseError,
    GatewayPlugin,
    redact_secret_config,
)
from .gateway_match import render_match_value

__all__ = [
    "LimitCollector",
    "load_yaml_documents",
    "policy_plugin",
    "raise_if_truncated_tail",
    "reject_binary",
    "render_string_match",
    "is_duration",
    "is_truncated_cluster_host",
]


def reject_binary(text: str, *, format_label: str) -> None:
    """Refuse text that decoded from a non-UTF-8 source (NUL bytes survive decoding).

    Args:
        text: The decoded document.
        format_label: Human name of the format, for the message.

    Raises:
        GatewayConfigParseError: ``INPUT_ENCODING_INVALID`` when the text holds NUL bytes.
    """
    if "\x00" in text:
        raise GatewayConfigParseError(
            f"{format_label} document contains NUL bytes — the file is binary or not UTF-8 "
            "encoded (a UTF-16 file reads this way)",
            code="INPUT_ENCODING_INVALID",
        )


def load_yaml_documents(text: str, *, format_label: str) -> List[Any]:
    """Parse a YAML (or JSON) stream into its non-empty documents.

    Args:
        text: The decoded stream.
        format_label: Human name of the format, for messages.

    Returns:
        The parsed documents, empty ones dropped.

    Raises:
        GatewayConfigParseError: ``INPUT_MALFORMED`` for an empty stream or a YAML syntax
            error, ``INPUT_TRUNCATED`` when the parser ran out of input mid-construct.
    """
    if not text.strip():
        raise GatewayConfigParseError(f"{format_label} document is empty", code="INPUT_MALFORMED")
    try:
        documents = [doc for doc in yaml.safe_load_all(text) if doc is not None]
    except yaml.YAMLError as exc:
        message = str(exc)
        if "end of stream" in message or "<stream end>" in message:
            raise GatewayConfigParseError(
                f"{format_label} document is truncated: {message}", code="INPUT_TRUNCATED"
            ) from exc
        raise GatewayConfigParseError(
            f"{format_label} document is not valid YAML: {message}", code="INPUT_MALFORMED"
        ) from exc
    if not documents:
        raise GatewayConfigParseError(
            f"{format_label} document contains no YAML documents", code="INPUT_MALFORMED"
        )
    return documents


@dataclass
class LimitCollector:
    """Counts recognized-but-unmodeled constructs so each is declared once, with a reason.

    Attributes:
        entries: ``construct`` → ``[count, reason]``, in first-seen order.
    """

    entries: Dict[str, List[Any]] = field(default_factory=dict)

    def add(self, construct: str, reason: str, count: int = 1) -> None:
        """Record ``count`` occurrences of ``construct``; the first reason given wins.

        Args:
            construct: Stable construct name (``match.connect_matcher``, ``tcp``, …).
            reason: Why the canonical model does not hold it.
            count: How many occurrences to add.
        """
        if construct in self.entries:
            self.entries[construct][0] += count
        else:
            self.entries[construct] = [count, reason]

    def as_ignored(self) -> Tuple[Dict[str, Any], ...]:
        """The collected limits as ``GatewayConfigDocument.ignored`` entries.

        Returns:
            ``{"construct", "count", "reason"}`` mappings, sorted by construct so the
            canonical model is stable whatever order the source declared things in.
        """
        return tuple(
            {"construct": construct, "count": count, "reason": reason}
            for construct, (count, reason) in sorted(self.entries.items())
        )


def render_string_match(spec: Any) -> Optional[str]:
    """Render a string matcher (Envoy ``StringMatcher`` / Istio ``StringMatch``) as text.

    An exact match renders as the bare value, because that is the value a request must
    carry; every other operator renders as ``<operator>:<value>`` so a reader of the
    ``match_value`` extra can tell a prefix from a literal.

    Args:
        spec: The matcher mapping (``{"exact": "GET"}``, ``{"prefix": "acme-"}``,
            ``{"safe_regex": {"regex": "^x$"}}``, ``{"regex": "^x$"}`` …).

    Returns:
        The rendered value, or ``None`` when ``spec`` is not a recognized matcher.
    """
    if not isinstance(spec, Mapping):
        return None
    for operator in ("exact", "prefix", "suffix", "contains", "regex"):
        value = spec.get(operator)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            return render_match_value(operator, str(value))
    safe = spec.get("safe_regex")
    if isinstance(safe, Mapping) and isinstance(safe.get("regex"), str):
        return render_match_value("regex", safe["regex"])
    return None


def policy_plugin(
    name: str, config: Any, *, scope: str, attached_to: Optional[str]
) -> Tuple[GatewayPlugin, int]:
    """Wrap a routing-policy block (retries, timeouts, CORS, rewrites…) as a plugin.

    The canonical model has no field for traffic policy; carrying it as a named plugin
    keeps its name on every operation it governs and lists it on the coverage ledger as
    partially mapped — kept, not dropped. Secret-shaped values are redacted first.

    Args:
        name: The source key (``retry_policy``, ``corsPolicy``, ``timeout``…).
        config: The block's value.
        scope: ``global``, ``service`` or ``route``.
        attached_to: The entity the block is attached to.

    Returns:
        ``(plugin, redaction_count)``.
    """
    body = config if isinstance(config, Mapping) else {"value": config}
    redacted, count = redact_secret_config(dict(body))
    return (
        GatewayPlugin(name=name, scope=scope, attached_to=attached_to, enabled=True, config=redacted),
        count,
    )


# ---------------------------------------------------------------------------------------
# Truncation inside a stream that still parses
# ---------------------------------------------------------------------------------------

#: ``key: value`` on one line, optionally a sequence item; the value unquoted.
_TAIL_SCALAR_RE = re.compile(r"^\s*(?:-\s+)?(?P<key>[A-Za-z_][\w.-]*)\s*:\s*(?P<value>[^\s'\"#][^#]*?)\s*$")

#: A protobuf-JSON duration: a number with an ``s`` unit (Envoy), or Go's unit set (Istio).
_DURATION_RE = re.compile(r"^-?\d+(\.\d+)?(ns|us|µs|ms|s|m|h)$")

#: The Kubernetes cluster-local service suffix a service host ends with.
_CLUSTER_DOMAIN = ".cluster.local"


def is_duration(value: str) -> bool:
    """True when ``value`` is a duration with a unit (``15s``, ``0.25s``, ``10m``)."""
    return bool(_DURATION_RE.match(value.strip()))


def is_truncated_cluster_host(value: str) -> bool:
    """True when ``value`` is a service host cut partway through ``.svc.cluster.local``.

    ``orders.storefront.svc`` is a legitimate short form and ``…svc.cluster.local`` is the
    full one; anything strictly between (``…svc.cluster``, ``…svc.cluster.lo``) is a name
    that stopped mid-suffix.
    """
    match = re.search(r"\.svc(\.[a-z.]*)$", value.strip())
    if not match:
        return False
    suffix = match.group(1)
    return bool(suffix) and suffix != _CLUSTER_DOMAIN and _CLUSTER_DOMAIN.startswith(suffix)


def raise_if_truncated_tail(
    text: str,
    *,
    format_label: str,
    rules: Mapping[str, Callable[[str], bool]],
) -> None:
    """Refuse a stream whose final scalar is a value its field grammar cannot accept.

    A file cut at a line boundary usually still parses as YAML, so the cut is invisible to
    the YAML reader. What gives it away is the last value: ``timeout: 15`` (a duration
    with its unit missing) or ``host: orders.storefront.svc.cluster`` (a service name that
    stops inside the cluster domain). Only the **final** scalar is judged — the same value
    mid-file is a different fault, and judging it here would turn an authoring slip into a
    false truncation report.

    Args:
        text: The decoded stream.
        format_label: Human name of the format, for the message.
        rules: Field name → predicate returning True when the value is a cut-off value
            for that field.

    Raises:
        GatewayConfigParseError: ``INPUT_TRUNCATED`` when the final scalar fails its rule.
    """
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped in ("---", "..."):
            continue
        match = _TAIL_SCALAR_RE.match(line)
        if not match:
            return
        key, value = match.group("key"), match.group("value")
        rule = rules.get(key)
        if rule is not None and rule(value):
            raise GatewayConfigParseError(
                f"{format_label} document appears truncated: its final value {key}: {value!r} "
                "is cut off",
                code="INPUT_TRUNCATED",
            )
        return
