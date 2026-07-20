"""Slate Edge cache policy rules — UXE-3.1 (private-suite#2473).

The decisions that must hold before cache policy changes, and the evaluation that explains what
a policy would do, kept in one pure module so they can be tested exhaustively without a
database and so the REST layer cannot implement a second, subtly different copy of them.

The refusal vocabulary here is shared with ``designer/lib/authoring/cache-actions.ts``
deliberately, for the reason :mod:`app.slate_releases` states: the authoring surface makes
``disabledReason`` the only way to disable a control, so a backend that invented its own codes
would leave the operator with a greyed-out dead end instead of a sentence explaining what to do.

Four things are worth stating outright.

1. **Presets are values, not adjectives.** :data:`PRESETS` is a table of literals. "Aggressive"
   is not a mood the system interprets at request time; it is a specific edge TTL and a specific
   stale window, printable in full and asserted byte-for-byte by a golden test. That is what
   makes acceptance criterion 1 ("documented and deterministic") checkable rather than claimed.

2. **Evaluation is a total order.** Rules are sorted by ``(ordinal, id)`` and
   ``UNIQUE (environment_id, ordinal)`` in V187 forbids ties. Without that, which rule won would
   depend on physical row order and a trace could not be reproduced. :func:`rules_digest` is the
   receipt: same digest and same request must produce the same verdict.

3. **Identity in a shared cache key is refused, not warned about.** Everything else on the
   unsafe list costs money or performance; this one serves one reader's page to another. It has
   no acknowledgement path for that reason — see :data:`_HARD_REFUSALS` and
   :func:`evaluate_cache_safety`.

4. **Nothing here evicts anything.** ``deploy/`` is a single Caddyfile with no CDN behind it.
   This module plans and explains; :mod:`app.slate_cache_store` records. A purge is real,
   audited intent with a real estimated scope, and the API says so in as many words rather than
   reporting a flush that did not happen.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple

__all__ = [
    "PRESETS",
    "PRESET_IDS",
    "PURGE_SCOPE_KINDS",
    "CachePreset",
    "CacheRefusal",
    "CacheWarning",
    "PurgePlan",
    "SlateCacheRefusedError",
    "TraceRequest",
    "TraceVerdict",
    "apply_preset",
    "evaluate_cache_safety",
    "evaluate_trace",
    "matches_route",
    "normalize_rule",
    "plan_purge_scope",
    "rules_digest",
]

# ─── Presets ──────────────────────────────────────────────────────────────────

PRESET_IDS = ("standard", "aggressive", "bypass", "personalized")

#: Routes a preset distinguishes. A preset that treated a hashed asset bundle and a living
#: HTML page identically would be wrong for one of them whichever value it chose.
_IMMUTABLE_ASSET_MATCHER = "/_next/static/**"

#: One year, the conventional ceiling for content whose URL changes when its bytes do.
_IMMUTABLE_TTL = 31_536_000


@dataclass(frozen=True)
class CachePresetRule:
    """One rule a preset contributes, as a complete set of values.

    Every field is stated even when it is zero, because a preset that left fields unset would
    push the question of what they mean to whoever read it next.
    """

    label: str
    matcher_kind: str
    matcher_value: str
    eligibility: str
    browser_ttl_seconds: int
    edge_ttl_seconds: int
    stale_while_revalidate_seconds: int
    stale_if_error_seconds: int
    cache_key_base: str = "host-url"
    vary_query_mode: str = "none"
    vary_query_keys: Tuple[str, ...] = ()
    vary_headers: Tuple[str, ...] = ()
    vary_cookies: Tuple[str, ...] = ()


@dataclass(frozen=True)
class CachePreset:
    """A named, fully-specified default policy (roadmap §29.3).

    Attributes:
        key: One of :data:`PRESET_IDS`.
        label: Operator-facing name.
        intent: The one-line intent from the roadmap table, quoted rather than paraphrased.
        rationale: Why an operator would choose this, and what it costs.
        requires_expiry: Whether the preset may exist without an end date. Only Bypass may not.
        unsafe_if: What this preset forbids, as sentences the UI renders next to the choice.
        rules: The rules the preset contributes, in precedence order.
    """

    key: str
    label: str
    intent: str
    rationale: str
    requires_expiry: bool
    unsafe_if: Tuple[str, ...]
    rules: Tuple[CachePresetRule, ...]


PRESETS: Mapping[str, CachePreset] = {
    "standard": CachePreset(
        key="standard",
        label="Standard",
        intent="Immutable assets cached long; HTML revalidated safely",
        rationale=(
            "The safe default. Hashed asset bundles are cached for a year because their URL "
            "changes when their bytes do, so a stale one is unreachable rather than wrong. "
            "HTML carries a short edge TTL and revalidates, so a publish is visible in about a "
            "minute without asking the origin for every request."
        ),
        requires_expiry=False,
        unsafe_if=(
            "Cookie or header variation on a shared route: Standard caches HTML publicly.",
        ),
        rules=(
            CachePresetRule(
                label="Immutable assets",
                matcher_kind="glob",
                matcher_value=_IMMUTABLE_ASSET_MATCHER,
                eligibility="cacheable",
                browser_ttl_seconds=_IMMUTABLE_TTL,
                edge_ttl_seconds=_IMMUTABLE_TTL,
                stale_while_revalidate_seconds=0,
                stale_if_error_seconds=0,
            ),
            CachePresetRule(
                label="HTML documents",
                matcher_kind="prefix",
                matcher_value="/",
                eligibility="cacheable",
                browser_ttl_seconds=0,
                edge_ttl_seconds=60,
                stale_while_revalidate_seconds=60,
                stale_if_error_seconds=86_400,
            ),
        ),
    ),
    "aggressive": CachePreset(
        key="aggressive",
        label="Aggressive",
        intent="Public immutable documentation with extended edge stale behavior",
        rationale=(
            "For published documentation that changes on a release boundary rather than "
            "continuously. HTML is held at the edge for ten minutes and may be served stale "
            "for a day while revalidating, and for a week if the origin is failing. That last "
            "window is the point: a documentation site should outlive its origin."
        ),
        requires_expiry=False,
        unsafe_if=(
            "Any personalization: a ten-minute shared TTL makes per-reader content visible to "
            "the wrong reader.",
            "Content that must be corrected within minutes: purge, do not wait for the TTL.",
        ),
        rules=(
            CachePresetRule(
                label="Immutable assets",
                matcher_kind="glob",
                matcher_value=_IMMUTABLE_ASSET_MATCHER,
                eligibility="cacheable",
                browser_ttl_seconds=_IMMUTABLE_TTL,
                edge_ttl_seconds=_IMMUTABLE_TTL,
                stale_while_revalidate_seconds=0,
                stale_if_error_seconds=0,
            ),
            CachePresetRule(
                label="HTML documents",
                matcher_kind="prefix",
                matcher_value="/",
                eligibility="cacheable",
                browser_ttl_seconds=0,
                edge_ttl_seconds=600,
                stale_while_revalidate_seconds=86_400,
                stale_if_error_seconds=604_800,
            ),
        ),
    ),
    "bypass": CachePreset(
        key="bypass",
        label="Bypass",
        intent="Incident/debug mode with explicit expiry",
        rationale=(
            "Everything goes to the origin. This is what you set at 03:00 when you cannot tell "
            "whether the cache is the problem. It carries a mandatory expiry because a bypass "
            "that outlives its incident stops being a decision and becomes the configuration — "
            "usually discovered months later as an origin cost."
        ),
        requires_expiry=True,
        unsafe_if=(
            "Sustained use: every request reaches the origin, including asset requests that "
            "have no reason to.",
        ),
        rules=(
            CachePresetRule(
                label="Bypass everything",
                matcher_kind="prefix",
                matcher_value="/",
                eligibility="no-store",
                browser_ttl_seconds=0,
                edge_ttl_seconds=0,
                stale_while_revalidate_seconds=0,
                stale_if_error_seconds=0,
            ),
        ),
    ),
    "personalized": CachePreset(
        key="personalized",
        label="Personalized",
        intent="Identity/variant-aware keys and private/no-store safeguards",
        rationale=(
            "For a site whose HTML differs per reader. HTML is marked private and given no "
            "shared TTL, so it may be held by the one browser it was rendered for and by "
            "nothing in between. Assets stay public and immutable, because a hashed bundle is "
            "the same bytes for everyone."
        ),
        requires_expiry=False,
        unsafe_if=(
            "Raising the edge TTL on a private route: private means one reader, and a shared "
            "tier has more than one.",
            "Serving stale personalized HTML: stale delivery re-serves a stored response "
            "without revalidating.",
        ),
        rules=(
            CachePresetRule(
                label="Immutable assets",
                matcher_kind="glob",
                matcher_value=_IMMUTABLE_ASSET_MATCHER,
                eligibility="cacheable",
                browser_ttl_seconds=_IMMUTABLE_TTL,
                edge_ttl_seconds=_IMMUTABLE_TTL,
                stale_while_revalidate_seconds=0,
                stale_if_error_seconds=0,
            ),
            CachePresetRule(
                label="Personalized HTML",
                matcher_kind="prefix",
                matcher_value="/",
                eligibility="private",
                browser_ttl_seconds=0,
                edge_ttl_seconds=0,
                stale_while_revalidate_seconds=0,
                stale_if_error_seconds=0,
            ),
        ),
    ),
}


def apply_preset(
    preset_key: str, overrides: Optional[Mapping[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Resolve a preset, plus any operator overrides, into concrete rules.

    Pure and total: the same arguments always produce the same rules, and applying the result
    again changes nothing. That idempotence is what "deterministic" means here, and is asserted
    directly by the test suite.

    Args:
        preset_key: One of :data:`PRESET_IDS`.
        overrides: Fields the operator moved off the preset default, keyed by rule label. A
            key naming no rule is ignored rather than raising: an override left behind by a
            preset change should not make the lane unreadable.

    Returns:
        The preset's rules as plain dicts in precedence order, with overrides applied.

    Raises:
        SlateCacheRefusedError: If ``preset_key`` names no preset.
    """
    preset = PRESETS.get(preset_key)
    if preset is None:
        raise SlateCacheRefusedError(CacheRefusal.of("preset-unknown"))

    applied = overrides or {}
    resolved: List[Dict[str, Any]] = []
    for ordinal, rule in enumerate(preset.rules):
        row: Dict[str, Any] = {
            "ordinal": ordinal,
            "enabled": True,
            "label": rule.label,
            "matcher_kind": rule.matcher_kind,
            "matcher_value": rule.matcher_value,
            "matcher_methods": ["GET", "HEAD"],
            "matcher_hosts": [],
            "eligibility": rule.eligibility,
            "browser_ttl_seconds": rule.browser_ttl_seconds,
            "edge_ttl_seconds": rule.edge_ttl_seconds,
            "stale_while_revalidate_seconds": rule.stale_while_revalidate_seconds,
            "stale_if_error_seconds": rule.stale_if_error_seconds,
            "cache_key_base": rule.cache_key_base,
            "vary_query_mode": rule.vary_query_mode,
            "vary_query_keys": list(rule.vary_query_keys),
            "vary_headers": list(rule.vary_headers),
            "vary_cookies": list(rule.vary_cookies),
            "bypass_conditions": [],
            "derived_from_preset": preset.key,
        }
        for key, value in (applied.get(rule.label) or {}).items():
            if key in row:
                row[key] = value
        resolved.append(row)
    return resolved


# ─── Refusals and warnings ────────────────────────────────────────────────────

#: Every reason a cache write can be refused. Mirrors the UI's `AuthoringCacheRefusalReason`.
CacheRefusalReason = Literal[
    "identity-in-cache-key",
    "stale-serves-identity",
    "private-served-from-edge",
    "no-store-with-ttl",
    "bypass-without-expiry",
    "preset-unknown",
    "preset-contradicted",
    "matcher-invalid",
    "ordinal-conflict",
    "purge-scope-unbounded",
    "purge-scope-empty",
    "purge-release-not-found",
    "purge-estimate-changed",
    "policy-version-conflict",
]

# One operator-facing sentence per refusal, returned verbatim by the REST layer so the reason a
# control is disabled reaches the operator as words rather than as a code.
_REFUSAL_SENTENCES: Dict[str, str] = {
    "identity-in-cache-key": (
        "This rule is shared-cacheable but varies its cache key on an identity credential. "
        "One reader's rendered page would be stored under a key another reader can reach. "
        "Mark the route private, or remove the identity variation."
    ),
    "stale-serves-identity": (
        "This rule varies on identity and also serves stale content. Stale delivery re-serves "
        "a stored response without revalidating, so it would hand one reader another reader's "
        "page."
    ),
    "private-served-from-edge": (
        "This rule is marked private but carries a non-zero edge TTL. Private means one "
        "reader; storing it at a shared tier contradicts that."
    ),
    "no-store-with-ttl": (
        "This rule is no-store but carries a TTL. No-store means the response is never "
        "stored; a TTL on it is not a weaker rule, it is a contradictory one."
    ),
    "bypass-without-expiry": (
        "The Bypass preset is an incident mode and needs an explicit expiry. A bypass with no "
        "end date stops being a decision and becomes the configuration."
    ),
    "preset-unknown": (
        "That preset does not exist. Choose Standard, Aggressive, Bypass or Personalized."
    ),
    "preset-contradicted": (
        "This rule contradicts a field its preset pins. Change the preset, or move this route "
        "onto an expert rule that does not claim to be that preset."
    ),
    "matcher-invalid": (
        "This route matcher does not compile, so it can never be evaluated. Fix the pattern."
    ),
    "ordinal-conflict": (
        "Another rule already holds that precedence on this lane. Two rules at the same "
        "precedence would make which one wins depend on row order."
    ),
    "purge-scope-unbounded": (
        "This purge names no scope, so it would cover every object on the lane. Name a "
        "release, tag, prefix, host or URL."
    ),
    "purge-scope-empty": (
        "Nothing on this lane's current release matches that scope, so this purge would do "
        "nothing. Check the scope before running it during an incident."
    ),
    "purge-release-not-found": (
        "That release does not belong to this environment, so its pages cannot be scoped here."
    ),
    "purge-estimate-changed": (
        "The scope of this purge changed between the estimate you confirmed and now. Re-read "
        "the estimate: you approved a different blast radius than the one in front of you."
    ),
    "policy-version-conflict": (
        "Another operator changed this lane's cache policy while this edit was being prepared. "
        "Re-read the policy and try again."
    ),
}

#: Refusals with no acknowledgement path. Each one describes a correctness failure — content
#: reaching a reader it was not rendered for, or a rule that contradicts itself — rather than a
#: cost. An "I accept the risk" checkbox over these would be a checkbox over a data leak.
_HARD_REFUSALS = frozenset(
    {
        "identity-in-cache-key",
        "stale-serves-identity",
        "private-served-from-edge",
        "no-store-with-ttl",
    }
)

#: Warning reasons an operator may acknowledge. These cost money, performance or clarity; none
#: of them serves the wrong bytes to the wrong person.
_WARNING_SENTENCES: Dict[str, str] = {
    "vary-query-all": (
        "Varying on every query parameter gives each distinct URL its own cache entry, "
        "including ones added by campaign trackers. This fragments the cache rather than "
        "leaking from it, but the hit rate can collapse."
    ),
    "cookie-variation-high-cardinality": (
        "This rule varies on a cookie. Every distinct value becomes its own cache entry, so a "
        "cookie with many values multiplies storage for no gain."
    ),
    "long-ttl-on-html": (
        "This rule holds HTML at a shared tier for over an hour. That is a reasonable choice "
        "for an archived version and a mistake for a living one; nothing here can tell which "
        "this is."
    ),
    "rule-shadowed": (
        "A higher-precedence rule already covers everything this one matches, so it can never "
        "win. That is usually an editing mistake."
    ),
}

#: Request headers that carry a caller's identity. Varying a *shared* cache on any of these
#: stores one reader's response under a key another reader can produce. One auditable list
#: rather than scattered conditionals, with its own golden test.
_IDENTITY_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})

#: Substrings that mark a cookie as a session or credential cookie. Matching on substrings is
#: deliberately broad: the cost of over-matching is an operator marking a route private that
#: did not have to be, and the cost of under-matching is a cross-reader leak.
_IDENTITY_COOKIE_MARKERS = ("session", "sid", "auth", "token", "jwt", "csrf", "remember")

#: Above this, a shared HTML TTL is worth a sentence. One hour: long enough that a correction
#: is not visible for a working session.
_LONG_HTML_TTL_SECONDS = 3_600


@dataclass(frozen=True)
class CacheRefusal:
    """A named, explained refusal to change cache policy."""

    reason: str
    sentence: str

    @staticmethod
    def of(reason: str) -> "CacheRefusal":
        """Build a refusal from its reason code.

        Args:
            reason: One of :data:`CacheRefusalReason`.

        Returns:
            The refusal with its operator-facing sentence attached.
        """
        return CacheRefusal(
            reason=reason,
            sentence=_REFUSAL_SENTENCES.get(reason, "This cache policy change cannot be applied."),
        )


@dataclass(frozen=True)
class CacheWarning:
    """A named concern that does not block the write.

    Attributes:
        code: One of the keys of :data:`_WARNING_SENTENCES`.
        message: The operator-facing sentence.
        field: Which rule field the warning attaches to, so the UI can place it.
    """

    code: str
    message: str
    field: Optional[str] = None

    @staticmethod
    def of(code: str, field: Optional[str] = None) -> "CacheWarning":
        """Build a warning from its code.

        Args:
            code: One of the keys of :data:`_WARNING_SENTENCES`.
            field: Rule field the warning is about, when there is one.

        Returns:
            The warning with its sentence attached.
        """
        return CacheWarning(
            code=code,
            message=_WARNING_SENTENCES.get(code, "This rule may not behave as intended."),
            field=field,
        )


class SlateCacheRefusedError(Exception):
    """A cache policy change was refused. Carries the named reason and its sentence.

    Raising rather than returning is deliberate for the REST layer, matching
    :class:`app.slate_releases.SlateReleaseRefusedError`: a refused rule write must never fall
    through to a persist.
    """

    def __init__(self, refusal: CacheRefusal) -> None:
        self.refusal = refusal
        self.code = refusal.reason
        super().__init__(refusal.sentence)


# ─── Rule normalization and safety ────────────────────────────────────────────


def normalize_rule(rule: Mapping[str, Any]) -> Dict[str, Any]:
    """Coerce a rule mapping into the canonical shape evaluation and hashing assume.

    Missing fields take their column default, string lists are lower-cased where the HTTP
    specification is case-insensitive (header names, methods, hosts) and left alone where it is
    not (cookie names, query keys). Doing this once, here, is what lets :func:`rules_digest`
    produce the same hash for two rules that differ only in spelling.

    Args:
        rule: A rule row or request body.

    Returns:
        A new dict with every field present and canonically cased.
    """
    return {
        "id": str(rule.get("id") or ""),
        "ordinal": int(rule.get("ordinal") or 0),
        "enabled": bool(rule.get("enabled", True)),
        "label": str(rule.get("label") or ""),
        "matcher_kind": str(rule.get("matcher_kind") or "prefix"),
        # An absent matcher defaults to "/", but an explicitly empty one is preserved so
        # _matcher_compiles can refuse it. Coercing "" to "/" here would silently turn a
        # half-filled form into a rule that matches the entire site.
        "matcher_value": (
            "/" if rule.get("matcher_value") is None else str(rule.get("matcher_value"))
        ),
        "matcher_methods": sorted(
            {str(m).upper() for m in (rule.get("matcher_methods") or ["GET", "HEAD"])}
        ),
        "matcher_hosts": sorted({str(h).lower() for h in (rule.get("matcher_hosts") or [])}),
        "eligibility": str(rule.get("eligibility") or "cacheable"),
        "browser_ttl_seconds": int(rule.get("browser_ttl_seconds") or 0),
        "edge_ttl_seconds": int(rule.get("edge_ttl_seconds") or 0),
        "stale_while_revalidate_seconds": int(rule.get("stale_while_revalidate_seconds") or 0),
        "stale_if_error_seconds": int(rule.get("stale_if_error_seconds") or 0),
        "cache_key_base": str(rule.get("cache_key_base") or "host-url"),
        "vary_query_mode": str(rule.get("vary_query_mode") or "none"),
        "vary_query_keys": sorted({str(k) for k in (rule.get("vary_query_keys") or [])}),
        "vary_headers": sorted({str(h).lower() for h in (rule.get("vary_headers") or [])}),
        "vary_cookies": sorted({str(c) for c in (rule.get("vary_cookies") or [])}),
        "bypass_conditions": list(rule.get("bypass_conditions") or []),
        "expires_at": rule.get("expires_at"),
        "acknowledged_warnings": sorted(
            {str(w) for w in (rule.get("acknowledged_warnings") or [])}
        ),
    }


def _varies_on_identity(rule: Mapping[str, Any]) -> Optional[str]:
    """Return the identity credential a rule varies on, or ``None``.

    Args:
        rule: A normalized rule.

    Returns:
        The offending header or cookie name, for use in the refusal detail.
    """
    for header in rule["vary_headers"]:
        if header in _IDENTITY_HEADERS:
            return f"header {header}"
    for cookie in rule["vary_cookies"]:
        lowered = cookie.lower()
        if any(marker in lowered for marker in _IDENTITY_COOKIE_MARKERS):
            return f"cookie {cookie}"
    return None


def evaluate_cache_safety(
    rule: Mapping[str, Any], *, siblings: Sequence[Mapping[str, Any]] = ()
) -> List[CacheWarning]:
    """Check a rule for unsafe or costly cache variation.

    This is the authority behind acceptance criterion 4. The UI renders what this returns and
    what :class:`SlateCacheRefusedError` carries; it does not classify variants itself, because
    two copies of this policy would eventually disagree and the one that disagreed silently
    would be the one serving production.

    Args:
        rule: The rule to check, normalized or raw.
        siblings: Other rules on the lane, used only for the shadowing warning.

    Returns:
        Warnings that do not block the write. Acknowledged warnings are still returned; the
        caller decides whether an acknowledgement is on file.

    Raises:
        SlateCacheRefusedError: On any condition in :data:`_HARD_REFUSALS` — a rule that would
            serve one reader's content to another, or that contradicts itself.
    """
    normalized = normalize_rule(rule)
    identity = _varies_on_identity(normalized)
    shared = normalized["eligibility"] == "cacheable"
    serves_stale = (
        normalized["stale_while_revalidate_seconds"] > 0
        or normalized["stale_if_error_seconds"] > 0
    )

    # Correctness failures first. Order matters only for which sentence an operator sees first;
    # each of these is independently disqualifying.
    if identity and shared:
        raise SlateCacheRefusedError(CacheRefusal.of("identity-in-cache-key"))
    if identity and serves_stale:
        raise SlateCacheRefusedError(CacheRefusal.of("stale-serves-identity"))
    if normalized["eligibility"] == "private" and normalized["edge_ttl_seconds"] > 0:
        raise SlateCacheRefusedError(CacheRefusal.of("private-served-from-edge"))
    if normalized["eligibility"] == "no-store" and (
        normalized["edge_ttl_seconds"] > 0 or normalized["browser_ttl_seconds"] > 0
    ):
        raise SlateCacheRefusedError(CacheRefusal.of("no-store-with-ttl"))

    if not _matcher_compiles(normalized):
        raise SlateCacheRefusedError(CacheRefusal.of("matcher-invalid"))

    warnings: List[CacheWarning] = []
    if normalized["vary_query_mode"] == "all":
        warnings.append(CacheWarning.of("vary-query-all", field="vary_query_mode"))
    if normalized["vary_cookies"]:
        warnings.append(
            CacheWarning.of("cookie-variation-high-cardinality", field="vary_cookies")
        )
    if (
        shared
        and normalized["edge_ttl_seconds"] > _LONG_HTML_TTL_SECONDS
        and not _looks_like_immutable_asset(normalized["matcher_value"])
    ):
        warnings.append(CacheWarning.of("long-ttl-on-html", field="edge_ttl_seconds"))

    for sibling in siblings:
        other = normalize_rule(sibling)
        if other["id"] and other["id"] == normalized["id"]:
            continue
        if not other["enabled"]:
            continue
        if other["ordinal"] < normalized["ordinal"] and _covers(other, normalized):
            warnings.append(CacheWarning.of("rule-shadowed", field="ordinal"))
            break

    return warnings


def _looks_like_immutable_asset(matcher_value: str) -> bool:
    """Whether a matcher targets content whose URL changes when its bytes do.

    A long TTL on such a route is correct rather than risky, so the long-TTL warning does not
    fire for it.

    Args:
        matcher_value: The rule's route pattern.

    Returns:
        True when the pattern targets a fingerprinted asset path.
    """
    return "/static/" in matcher_value or "/_next/" in matcher_value or "/assets/" in matcher_value


def _matcher_compiles(rule: Mapping[str, Any]) -> bool:
    """Whether a rule's matcher can be evaluated at all.

    Args:
        rule: A normalized rule.

    Returns:
        False for a regex that does not compile, or an empty pattern.
    """
    value = rule["matcher_value"]
    if not value:
        return False
    if rule["matcher_kind"] == "regex":
        try:
            re.compile(value)
        except re.error:
            return False
    return True


def _covers(outer: Mapping[str, Any], inner: Mapping[str, Any]) -> bool:
    """Whether ``outer`` matches everything ``inner`` does, for the shadowing warning.

    Only the cases that can be decided cheaply and certainly are reported. A prefix strictly
    containing another prefix is one; comparing two regexes is not, and guessing would produce
    a warning an operator cannot act on.

    Args:
        outer: The higher-precedence rule.
        inner: The rule that may be unreachable.

    Returns:
        True only when coverage is certain.
    """
    if outer["matcher_kind"] != "prefix":
        return False
    if inner["matcher_kind"] not in {"prefix", "exact"}:
        return False
    if outer["matcher_hosts"] and outer["matcher_hosts"] != inner["matcher_hosts"]:
        return False
    if not set(inner["matcher_methods"]).issubset(set(outer["matcher_methods"])):
        return False
    return inner["matcher_value"].startswith(outer["matcher_value"])


# ─── Trace evaluation ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TraceRequest:
    """The test request a trace is evaluated against.

    Attributes:
        method: HTTP method, upper-cased by :meth:`normalized`.
        host: Request host, lower-cased.
        path: Request path.
        query: Query parameters, as a mapping of name to value.
        headers: Request headers, lower-cased by :meth:`normalized`.
        cookies: Request cookies. Names are case-sensitive and are left alone.
    """

    method: str = "GET"
    host: str = ""
    path: str = "/"
    query: Mapping[str, str] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)
    cookies: Mapping[str, str] = field(default_factory=dict)

    def normalized(self) -> "TraceRequest":
        """Return a copy with case normalized the way HTTP defines it.

        Returns:
            A new :class:`TraceRequest`; the original is untouched.
        """
        return TraceRequest(
            method=self.method.upper(),
            host=self.host.lower(),
            path=self.path or "/",
            query=dict(self.query),
            headers={k.lower(): v for k, v in self.headers.items()},
            cookies=dict(self.cookies),
        )


@dataclass(frozen=True)
class TraceVerdict:
    """What a policy decides for one request, and why.

    One field per clause of acceptance criterion 2, so a partially-answered trace is a type
    error rather than a subtle omission.
    """

    eligibility: str
    eligibility_reason: str
    cache_key: str
    cache_key_components: List[Dict[str, str]]
    browser_ttl_seconds: int
    edge_ttl_seconds: int
    stale_while_revalidate_seconds: int
    stale_if_error_seconds: int
    ttl_source: str
    bypassed: bool
    bypass_reason: Optional[str]
    winning_rule_id: Optional[str]
    winning_rule_label: str
    considered: List[Dict[str, Any]]
    warnings: List[Dict[str, str]]
    rules_digest: str


def matches_route(rule: Mapping[str, Any], request: TraceRequest) -> bool:
    """Whether a rule's matcher selects this request.

    Prefix matching is textual rather than segment-aware, so ``/docs`` also selects
    ``/docsearch``. That is deliberate: :func:`plan_purge_scope` compares prefixes the same
    way, and a rule whose scope differed from the purge aimed at it would make a trace
    misleading in exactly the situation a trace is consulted. An operator who means the section
    writes ``/docs/``.

    Args:
        rule: A normalized rule.
        request: A normalized request.

    Returns:
        True when method, host and path all match. A regex that does not compile matches
        nothing rather than raising: the rule write already refused it, and a trace over
        historical data should still render.
    """
    if request.method not in rule["matcher_methods"]:
        return False
    if rule["matcher_hosts"] and request.host not in rule["matcher_hosts"]:
        return False

    kind = rule["matcher_kind"]
    value = rule["matcher_value"]
    if kind == "exact":
        return request.path == value
    if kind == "prefix":
        return request.path.startswith(value)
    if kind == "glob":
        return fnmatch.fnmatchcase(request.path, value)
    if kind == "regex":
        try:
            return re.search(value, request.path) is not None
        except re.error:
            return False
    return False


def _bypass_reason(rule: Mapping[str, Any], request: TraceRequest) -> Optional[str]:
    """The first bypass condition this request satisfies, as a sentence.

    Args:
        rule: A normalized rule.
        request: A normalized request.

    Returns:
        A sentence naming the condition that fired, or ``None``.
    """
    for condition in rule["bypass_conditions"]:
        if not isinstance(condition, Mapping):
            continue
        kind = str(condition.get("kind") or "")
        name = str(condition.get("name") or "")
        equals = condition.get("equals")

        source: Mapping[str, str]
        if kind == "cookie":
            source = request.cookies
        elif kind == "header":
            source = request.headers
            name = name.lower()
        elif kind == "query":
            source = request.query
        elif kind == "method":
            if equals and request.method == str(equals).upper():
                return f"Bypassed because the method is {request.method}."
            continue
        else:
            continue

        if name not in source:
            continue
        if equals is None:
            return f"Bypassed because {kind} {name} is present."
        if source[name] == str(equals):
            return f"Bypassed because {kind} {name} equals {equals}."
    return None


def _cache_key(rule: Mapping[str, Any], request: TraceRequest) -> Tuple[str, List[Dict[str, str]]]:
    """Build the cache key this rule produces for this request, component by component.

    The components are returned alongside the rendered key because "why is this page cached
    separately for every reader" is answered by the list, not by the string.

    Args:
        rule: A normalized rule.
        request: A normalized request.

    Returns:
        The rendered key, and one entry per contributing component with the reason it is there.
    """
    components: List[Dict[str, str]] = []
    parts: List[str] = []

    base = rule["cache_key_base"]
    if base == "host-url":
        components.append(
            {
                "source": "host",
                "name": "host",
                "value": request.host,
                "contributed_because": "The cache key base is host-url.",
            }
        )
        parts.append(request.host)

    components.append(
        {
            "source": "path",
            "name": "path",
            "value": request.path,
            "contributed_because": "Every cache key includes the path.",
        }
    )
    parts.append(request.path)

    mode = rule["vary_query_mode"]
    if base != "url-no-query" and mode != "none":
        if mode == "all":
            selected = sorted(request.query.items())
            because = "The rule varies on every query parameter."
        elif mode == "allowlist":
            selected = sorted(
                (k, v) for k, v in request.query.items() if k in rule["vary_query_keys"]
            )
            because = "The rule's query allowlist names this parameter."
        else:
            selected = sorted(
                (k, v) for k, v in request.query.items() if k not in rule["vary_query_keys"]
            )
            because = "The rule's query denylist does not exclude this parameter."
        for key, value in selected:
            components.append(
                {
                    "source": "query",
                    "name": key,
                    "value": value,
                    "contributed_because": because,
                }
            )
            parts.append(f"{key}={value}")

    for header in rule["vary_headers"]:
        components.append(
            {
                "source": "header",
                "name": header,
                "value": request.headers.get(header, ""),
                "contributed_because": "The rule varies on this header.",
            }
        )
        parts.append(f"{header}:{request.headers.get(header, '')}")

    for cookie in rule["vary_cookies"]:
        components.append(
            {
                "source": "cookie",
                "name": cookie,
                "value": request.cookies.get(cookie, ""),
                "contributed_because": "The rule varies on this cookie.",
            }
        )
        parts.append(f"{cookie}={request.cookies.get(cookie, '')}")

    return "|".join(parts), components


def rules_digest(rules: Sequence[Mapping[str, Any]]) -> str:
    """Content-address an ordered ruleset.

    The determinism receipt for acceptance criterion 2: two traces carrying the same digest and
    the same request must agree, and a trace whose digest no longer matches the lane is
    *explained* by that fact rather than contradicted by it. Same instinct as
    ``slate_artifacts.content_digest`` — identity by content.

    Only enabled rules contribute, and only the fields that affect a decision; ``label`` and
    timestamps are excluded so renaming a rule does not invalidate historical traces.

    Args:
        rules: Rules in any order; they are normalized and sorted here.

    Returns:
        ``sha256:<64 hex chars>``, matching the CHECK constraint on
        ``slate_cache_traces.rules_digest``.
    """
    decisive: List[Dict[str, Any]] = []
    for rule in rules:
        normalized = normalize_rule(rule)
        if not normalized["enabled"]:
            continue
        decisive.append(
            {
                key: normalized[key]
                for key in (
                    "ordinal",
                    "matcher_kind",
                    "matcher_value",
                    "matcher_methods",
                    "matcher_hosts",
                    "eligibility",
                    "browser_ttl_seconds",
                    "edge_ttl_seconds",
                    "stale_while_revalidate_seconds",
                    "stale_if_error_seconds",
                    "cache_key_base",
                    "vary_query_mode",
                    "vary_query_keys",
                    "vary_headers",
                    "vary_cookies",
                    "bypass_conditions",
                )
            }
        )
    decisive.sort(key=lambda r: r["ordinal"])
    canonical = json.dumps(decisive, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evaluate_trace(
    *,
    request: TraceRequest,
    preset_key: str,
    rules: Sequence[Mapping[str, Any]],
    now: datetime,
) -> TraceVerdict:
    """Explain what this policy decides for this request.

    No I/O, no clock and no randomness: ``now`` is injected the way
    :func:`app.slate_releases.measure_activation_slo` injects it, so a trace is reproducible
    from its recorded inputs. Rules are evaluated in ``(ordinal, id)`` order and **every** rule
    is reported — a rule that lost says why, because "why did my rule not fire" is the question
    a trace exists to answer.

    Args:
        request: The test request.
        preset_key: The lane's preset, used when no expert rule matches.
        rules: The lane's expert rules, in any order.
        now: Evaluation time, for expiry.

    Returns:
        The verdict, answering eligibility, cache key, TTL, bypass and winning rule.

    Raises:
        SlateCacheRefusedError: If ``preset_key`` names no preset.
    """
    normalized_request = request.normalized()
    normalized = sorted(
        (normalize_rule(rule) for rule in rules),
        key=lambda r: (r["ordinal"], r["id"]),
    )

    considered: List[Dict[str, Any]] = []
    winner: Optional[Dict[str, Any]] = None

    for rule in normalized:
        entry: Dict[str, Any] = {
            "rule_id": rule["id"] or None,
            "label": rule["label"],
            "ordinal": rule["ordinal"],
            "matched": False,
        }
        if winner is not None:
            entry["outcome"] = "not-reached"
            entry["reason"] = (
                f"Not reached: rule {winner['ordinal']} \"{winner['label']}\" already decided."
            )
            considered.append(entry)
            continue
        if not rule["enabled"]:
            entry["outcome"] = "skipped"
            entry["reason"] = "Disabled."
            considered.append(entry)
            continue
        if rule["expires_at"] is not None and _expired(rule["expires_at"], now):
            entry["outcome"] = "skipped"
            entry["reason"] = f"Expired at {rule['expires_at']}."
            considered.append(entry)
            continue
        if not matches_route(rule, normalized_request):
            entry["outcome"] = "skipped"
            entry["reason"] = (
                f"Matcher {rule['matcher_kind']} \"{rule['matcher_value']}\" does not match "
                f"{normalized_request.method} {normalized_request.path}."
            )
            considered.append(entry)
            continue

        entry["matched"] = True
        entry["outcome"] = "matched"
        entry["reason"] = f"Matched {normalized_request.path} and decided the response."
        considered.append(entry)
        winner = rule

    if winner is None:
        preset_rules = apply_preset(preset_key)
        for candidate in (normalize_rule(r) for r in preset_rules):
            if matches_route(candidate, normalized_request):
                winner = candidate
                winner_label = f"{PRESETS[preset_key].label} preset: {candidate['label']}"
                break
        else:
            winner = normalize_rule({"label": "No rule", "eligibility": "no-store"})
            winner_label = f"{PRESETS[preset_key].label} preset default"
        ttl_source = f"{PRESETS[preset_key].label} preset"
        winning_rule_id = None
    else:
        winner_label = winner["label"]
        ttl_source = f"rule {winner['ordinal']} \"{winner['label']}\""
        winning_rule_id = winner["id"] or None

    bypass_reason = _bypass_reason(winner, normalized_request)
    bypassed = bypass_reason is not None

    cache_key, components = _cache_key(winner, normalized_request)

    eligibility = "no-store" if bypassed else winner["eligibility"]
    eligibility_reason = _eligibility_sentence(eligibility, bypassed, winner_label)

    warnings: List[Dict[str, str]] = []
    try:
        for warning in evaluate_cache_safety(winner, siblings=normalized):
            warnings.append(
                {"code": warning.code, "message": warning.message, "field": warning.field or ""}
            )
    except SlateCacheRefusedError as exc:
        # A stored rule can become unsafe when the policy around it changes. The trace reports
        # that rather than refusing to render: an operator debugging a leak needs to see the
        # verdict, and a trace is a read.
        warnings.append(
            {"code": exc.refusal.reason, "message": exc.refusal.sentence, "field": "eligibility"}
        )

    return TraceVerdict(
        eligibility=eligibility,
        eligibility_reason=eligibility_reason,
        cache_key=cache_key,
        cache_key_components=components,
        browser_ttl_seconds=0 if bypassed else winner["browser_ttl_seconds"],
        edge_ttl_seconds=0 if bypassed else winner["edge_ttl_seconds"],
        stale_while_revalidate_seconds=(
            0 if bypassed else winner["stale_while_revalidate_seconds"]
        ),
        stale_if_error_seconds=0 if bypassed else winner["stale_if_error_seconds"],
        ttl_source=ttl_source,
        bypassed=bypassed,
        bypass_reason=bypass_reason,
        winning_rule_id=winning_rule_id,
        winning_rule_label=winner_label,
        considered=considered,
        warnings=warnings,
        rules_digest=rules_digest(rules),
    )


def _eligibility_sentence(eligibility: str, bypassed: bool, winner_label: str) -> str:
    """Explain an eligibility verdict in one sentence.

    Args:
        eligibility: The resolved eligibility.
        bypassed: Whether a bypass condition fired.
        winner_label: The rule or preset that decided.

    Returns:
        A sentence naming both the outcome and what produced it.
    """
    if bypassed:
        return f"Not cached: a bypass condition on {winner_label} fired for this request."
    if eligibility == "cacheable":
        return f"Cacheable at a shared tier, decided by {winner_label}."
    if eligibility == "private":
        return (
            f"Private, decided by {winner_label}: storable by the one browser it was rendered "
            "for and by nothing in between."
        )
    return f"Never stored, decided by {winner_label}."


def _expired(expires_at: Any, now: datetime) -> bool:
    """Whether a rule's expiry has passed.

    Args:
        expires_at: The rule's ``expires_at``, as a datetime or ISO-8601 string.
        now: Evaluation time.

    Returns:
        True when the rule no longer applies. An unparseable value is treated as not expired,
        so a bad timestamp cannot silently disable a rule an operator is relying on.
    """
    if isinstance(expires_at, datetime):
        moment = expires_at
    else:
        try:
            moment = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        except ValueError:
            return False
    if moment.tzinfo is None and now.tzinfo is not None:
        moment = moment.replace(tzinfo=now.tzinfo)
    return moment <= now


# ─── Purge scope planning ─────────────────────────────────────────────────────

PURGE_SCOPE_KINDS = ("release", "tag", "prefix", "host", "url")

#: How many routes a purge estimate carries as a sample. Enough to recognize the shape of what
#: would be hit; not so many that the response becomes the inventory it is summarizing.
_SAMPLE_LIMIT = 50


@dataclass(frozen=True)
class PurgePlan:
    """An estimated purge scope and the basis of that estimate.

    Attributes:
        scope_kind: One of :data:`PURGE_SCOPE_KINDS`.
        scope_value: The release id, tag, prefix, host or URL.
        estimated_objects: How many objects the scope covers. An estimate, never a count of
            things evicted.
        estimate_basis: Which table produced the number, so it can be checked rather than
            believed.
        sample_routes: A bounded sample of what is in scope.
        truncated: Whether the sample is shorter than the scope.
        coverage: A sentence stating what the basis does and does not include.
    """

    scope_kind: str
    scope_value: str
    estimated_objects: int
    estimate_basis: str
    sample_routes: List[str]
    truncated: bool
    coverage: str


def plan_purge_scope(
    *,
    scope_kind: str,
    scope_value: str,
    routes: Sequence[str],
    basis: str,
) -> PurgePlan:
    """Turn a resolved route set into an estimate an operator can check.

    The store does the SQL; this function is pure so the estimate can be tested without a
    database. Prefix matching happens here rather than in SQL so that ``%`` and ``_`` in a
    route cannot silently widen a purge — an unescaped underscore in a ``LIKE`` pattern matches
    any character, which during an incident is the difference between purging one section and
    purging the site.

    Args:
        scope_kind: One of :data:`PURGE_SCOPE_KINDS`.
        scope_value: The scope itself.
        routes: Candidate routes already fetched for the lane's basis release.
        basis: Which table produced ``routes``.

    Returns:
        The plan, with a bounded sample and a coverage sentence.

    Raises:
        SlateCacheRefusedError: On an unbounded or empty scope.
    """
    if scope_kind not in PURGE_SCOPE_KINDS:
        raise SlateCacheRefusedError(CacheRefusal.of("purge-scope-unbounded"))
    if not scope_value.strip():
        raise SlateCacheRefusedError(CacheRefusal.of("purge-scope-unbounded"))

    if scope_kind == "prefix":
        selected = [route for route in routes if route.startswith(scope_value)]
    elif scope_kind == "url":
        selected = [route for route in routes if route == _path_of(scope_value)]
    else:
        # release, tag and host scopes are resolved by the store's query; everything it
        # returned is in scope.
        selected = list(routes)

    if not selected:
        raise SlateCacheRefusedError(CacheRefusal.of("purge-scope-empty"))

    ordered = sorted(set(selected))
    return PurgePlan(
        scope_kind=scope_kind,
        scope_value=scope_value,
        estimated_objects=len(ordered),
        estimate_basis=basis,
        sample_routes=ordered[:_SAMPLE_LIMIT],
        truncated=len(ordered) > _SAMPLE_LIMIT,
        coverage=_coverage_sentence(basis),
    )


def _path_of(url: str) -> str:
    """Reduce an absolute URL to its path, leaving a bare path alone.

    Args:
        url: An absolute URL or a path.

    Returns:
        The path component.
    """
    if "://" not in url:
        return url
    remainder = url.split("://", 1)[1]
    slash = remainder.find("/")
    return remainder[slash:] if slash != -1 else "/"


def _coverage_sentence(basis: str) -> str:
    """State what an estimate's basis does and does not include.

    A number whose provenance is unstated invites belief; stating it invites checking, which is
    what an operator about to purge production actually needs.

    Args:
        basis: One of the ``estimate_basis`` values V187 enumerates.

    Returns:
        A sentence describing the basis.
    """
    return {
        "changed-pages": (
            "Estimated from the pages this release changed. Unchanged pages may also be held "
            "at a cache and are not counted here."
        ),
        "artifact-manifest": "Estimated from the release's full page manifest.",
        "domain-inventory": "Estimated from the routes served under this host.",
        "rule-tags": "Estimated from the routes matched by rules carrying this tag.",
        "single-url": (
            "A single URL on this lane's current release. Other variants of the same page, "
            "such as a different query string, are separate cache entries and are not covered."
        ),
        "none": "No basis was available, so this estimate is zero rather than unknown.",
    }.get(basis, "Estimated from the lane's current release.")
