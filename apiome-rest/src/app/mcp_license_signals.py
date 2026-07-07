"""License & terms signal detection over MCP discovery text (V2-MCP-34.3 / MCAT-20.3).

Whether a server may be used, and under what terms, is often buried in its free-text
``instructions`` and never surfaced. This module is a **pure detector** that scans the
text a discovery snapshot already captured — the ``instructions``, the advertised server
title, and the validated branding website URL — for license / terms-of-service / usage
signals and reports them as informational findings:

* **SPDX license identifiers** (``Apache-2.0``, ``MIT``, ``GPL-3.0-only``, …) from a
  curated list of common ids.
* **License / terms / usage-restriction phrases** ("licensed under", "terms of service",
  "non-commercial", "all rights reserved", …).
* **License- or terms-pointing URLs** (a URL whose text suggests it is a license or
  terms/legal page; an ordinary link is *not* a signal).

Design rules (mirroring :mod:`app.mcp_lint`):

* **Pure & deterministic** — no database or network access; the same inputs always
  produce the same signals in the same order, and every signal ``id`` is a stable hash,
  so results can be compared across runs.
* **Informational only, no enforcement.** A signal means "the text *mentions* this",
  never "this is the server's license". Nothing here gates cataloging or invocation.
* **Never a false "no license" claim.** When nothing matches, the report's status is
  ``"not_stated"`` — the absence of a *statement*, explicitly not an assertion that the
  server is unlicensed. The report also names which sources were actually scanned, so an
  empty result over an empty snapshot reads as "nothing to scan", not "nothing found".

The public surface is :func:`detect_license_signals` (returning a
:class:`LicenseSignalsReport`) plus the signal-kind / status constants. The report card
(V2-MCP-33.1 / MCAT-19.1) consumes the report's :meth:`~LicenseSignalsReport.as_dict`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# --- Status model -----------------------------------------------------------------------------

#: At least one license/terms signal was found in the scanned sources.
STATUS_DETECTED = "detected"

#: No signal was found. Deliberately worded as "not stated" — the detector reports the
#: *absence of a statement*, never the absence of a license (AC: no false "no license" claim).
STATUS_NOT_STATED = "not_stated"

# --- Signal kinds -----------------------------------------------------------------------------

#: A known SPDX license identifier appeared verbatim (e.g. ``Apache-2.0``).
KIND_SPDX_ID = "spdx_id"

#: A license-related phrase appeared (e.g. "licensed under").
KIND_LICENSE_MENTION = "license_mention"

#: A terms-of-service / usage-policy phrase appeared (e.g. "terms of service").
KIND_TERMS_MENTION = "terms_mention"

#: A usage-restriction phrase appeared (e.g. "non-commercial", "all rights reserved").
KIND_USAGE_RESTRICTION = "usage_restriction"

#: A URL whose text suggests it points at a license document.
KIND_LICENSE_URL = "license_url"

#: A URL whose text suggests it points at a terms/legal page.
KIND_TERMS_URL = "terms_url"

# --- Sources ----------------------------------------------------------------------------------
# Scanned in this fixed order so signal ordering (and therefore rendering) is deterministic.

SOURCE_INSTRUCTIONS = "instructions"
SOURCE_SERVER_TITLE = "server_title"
SOURCE_WEBSITE_URL = "website_url"

_SOURCE_ORDER = (SOURCE_INSTRUCTIONS, SOURCE_SERVER_TITLE, SOURCE_WEBSITE_URL)

# --- Bounds -----------------------------------------------------------------------------------

#: Cap on the number of signals a report itemizes. The detector is informational — past this
#: many hits the marginal signal adds nothing — and the cap bounds the report card's size.
#: Overflow is counted in ``signals_truncated``, never silently dropped.
MAX_SIGNALS = 25

#: Cap on how much of a single source text is scanned. Bounds regex cost on a pathological
#: (multi-megabyte) ``instructions`` blob; real instruction texts are a few KB.
MAX_SCANNED_CHARS = 100_000

#: Length of the whitespace-collapsed context excerpt carried by each signal.
_EXCERPT_RADIUS = 60

# --- Pattern tables ---------------------------------------------------------------------------

#: Curated common SPDX license identifiers, in two ambiguity classes. Hyphen/digit-bearing ids
#: (``Apache-2.0``) are unambiguous and matched case-insensitively; short plain-word ids
#: (``MIT``, ``ISC``, ``Zlib``) collide with ordinary words when case-folded (German "mit",
#: the name "Zlib" in prose, …), so they are matched **case-sensitively** as written here.
_SPDX_CASE_INSENSITIVE: Tuple[str, ...] = (
    "Apache-2.0",
    "Apache-1.1",
    "GPL-2.0-only",
    "GPL-2.0-or-later",
    "GPL-3.0-only",
    "GPL-3.0-or-later",
    "AGPL-3.0-only",
    "AGPL-3.0-or-later",
    "LGPL-2.1-only",
    "LGPL-2.1-or-later",
    "LGPL-3.0-only",
    "LGPL-3.0-or-later",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "MPL-2.0",
    "CC0-1.0",
    "CC-BY-4.0",
    "CC-BY-SA-4.0",
    "CC-BY-NC-4.0",
    "EPL-2.0",
    "EUPL-1.2",
    "BSL-1.0",
    "0BSD",
    "Artistic-2.0",
)

_SPDX_CASE_SENSITIVE: Tuple[str, ...] = (
    "MIT",
    "ISC",
    "Zlib",
    "Unlicense",
)

#: Phrase tables per signal kind, matched case-insensitively on word boundaries. Longer/more
#: specific phrases are listed first and matched spans are claimed greedily, so "licensed
#: under" does not *also* report a bare "license" hit for the same words.
_LICENSE_PHRASES: Tuple[str, ...] = (
    "end user license agreement",
    "licensed under",
    "license terms",
    "eula",
    "licence",
    "license",
)

_TERMS_PHRASES: Tuple[str, ...] = (
    "terms of service",
    "terms of use",
    "terms and conditions",
    "acceptable use policy",
    "acceptable use",
    "usage policy",
    "tos",
)

_RESTRICTION_PHRASES: Tuple[str, ...] = (
    "all rights reserved",
    "for internal use only",
    "internal use only",
    "non-commercial use",
    "non-commercial",
    "noncommercial",
    "commercial use",
    "do not redistribute",
    "evaluation purposes only",
    "proprietary",
)

#: URL-text fragments that classify a link as license- vs terms-pointing. Checked against the
#: lower-cased URL; license wins when both match (``/legal/license`` is a license pointer).
_LICENSE_URL_HINTS: Tuple[str, ...] = ("spdx.org/licenses", "license", "licence")
_TERMS_URL_HINTS: Tuple[str, ...] = (
    "terms",
    "tos",
    "eula",
    "legal",
    "conditions",
    "acceptable-use",
    "usage-policy",
    "policies",
)

# --- Compiled patterns (module-level: compiled once, reused per call) --------------------------


def _boundary_pattern(literal: str, *, case_sensitive: bool = False) -> "re.Pattern[str]":
    """Compile ``literal`` as a boundary-anchored pattern (no partial-word matches).

    ``\\b`` misbehaves around ids that start/end with non-word characters (``0BSD``,
    ``CC0-1.0``), so the guard is an explicit lookaround: not preceded/followed by a word
    character or hyphen, and not followed by a ``.<digit>`` version continuation —
    ``permit`` never matches ``MIT``; ``Apache-2.0.1`` never matches ``Apache-2.0``; but a
    sentence-ending ``…the MIT license.`` still matches.

    Args:
        literal: The exact phrase or identifier to match.
        case_sensitive: Match the literal exactly as written (used for the short,
            collision-prone SPDX ids); otherwise matching is case-insensitive.

    Returns:
        The compiled pattern.
    """
    guarded = r"(?<![\w-])" + re.escape(literal) + r"(?![\w-])(?!\.\d)"
    return re.compile(guarded, 0 if case_sensitive else re.IGNORECASE)


_SPDX_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = tuple(
    [(spdx, _boundary_pattern(spdx)) for spdx in _SPDX_CASE_INSENSITIVE]
    + [(spdx, _boundary_pattern(spdx, case_sensitive=True)) for spdx in _SPDX_CASE_SENSITIVE]
)

_PHRASE_PATTERNS: Tuple[Tuple[str, str, "re.Pattern[str]"], ...] = tuple(
    (kind, phrase, _boundary_pattern(phrase))
    for kind, phrases in (
        (KIND_LICENSE_MENTION, _LICENSE_PHRASES),
        (KIND_TERMS_MENTION, _TERMS_PHRASES),
        (KIND_USAGE_RESTRICTION, _RESTRICTION_PHRASES),
    )
    for phrase in phrases
)

#: Bare-URL matcher for free text. Trailing punctuation that commonly closes a sentence or a
#: Markdown link is stripped from the match afterwards (see :func:`_iter_urls`).
_URL_PATTERN = re.compile(r"https?://[^\s<>\"'`\)\]]+", re.IGNORECASE)

_TRAILING_PUNCTUATION = ".,;:!?"


# --- Result model -------------------------------------------------------------------------------


@dataclass(frozen=True)
class LicenseSignal:
    """One license/terms signal found in a scanned source.

    ``id`` is a stable hash of ``source|kind|matched`` (prefixed ``mcp-license-``); equal
    inputs always yield the same id, so signals can be de-duplicated and referenced across
    runs (mirrors :class:`app.mcp_lint.LintFinding`).

    Attributes:
        kind: One of the ``KIND_*`` constants (what the match *is*).
        source: One of the ``SOURCE_*`` constants (where the match was found).
        matched: The matched identifier, phrase, or URL, verbatim from the text.
        excerpt: A short, whitespace-collapsed context window around the match (empty when
            the source *is* the matched value, e.g. the branding website URL).
        id: Stable identifier; auto-derived from ``source|kind|matched`` when not supplied.
    """

    kind: str
    source: str
    matched: str
    excerpt: str
    id: str = field(default="", compare=True)

    def __post_init__(self) -> None:
        if not self.id:
            digest = hashlib.sha256(
                f"{self.source}|{self.kind}|{self.matched}".encode("utf-8")
            ).hexdigest()[:16]
            object.__setattr__(self, "id", f"mcp-license-{digest}")

    def as_dict(self) -> Dict[str, str]:
        """Return a JSON-ready dict of this signal (stable key set)."""
        return {
            "id": self.id,
            "kind": self.kind,
            "source": self.source,
            "matched": self.matched,
            "excerpt": self.excerpt,
        }


@dataclass(frozen=True)
class LicenseSignalsReport:
    """The full detection result for one snapshot's scanned text.

    Attributes:
        status: :data:`STATUS_DETECTED` when at least one signal was found, otherwise
            :data:`STATUS_NOT_STATED` — never a "no license" claim.
        statement: One human-readable sentence summarizing the result, pre-worded so every
            consumer (report card, UI, export) states absence the same careful way.
        signals: The itemized signals, deterministically ordered (source order, then match
            position), bounded to :data:`MAX_SIGNALS`.
        signals_truncated: How many further signals were found beyond the cap (0 normally);
            overflow is stated, never silently dropped.
        sources_scanned: Which sources actually had text to scan, in scan order — so an
            empty result over an empty snapshot reads as "nothing to scan".
    """

    status: str
    statement: str
    signals: Tuple[LicenseSignal, ...]
    signals_truncated: int
    sources_scanned: Tuple[str, ...]

    def as_dict(self) -> Dict[str, object]:
        """Return a JSON-ready dict of the report (what the report card consumes)."""
        return {
            "status": self.status,
            "statement": self.statement,
            "signals": [signal.as_dict() for signal in self.signals],
            "signals_truncated": self.signals_truncated,
            "sources_scanned": list(self.sources_scanned),
        }


# --- Detection ----------------------------------------------------------------------------------


def detect_license_signals(
    *,
    instructions: Optional[str] = None,
    server_title: Optional[str] = None,
    website_url: Optional[str] = None,
) -> LicenseSignalsReport:
    """Scan a snapshot's advertised text for license / terms / usage signals.

    Pure and deterministic: no I/O, and the same inputs always produce the same report
    (same signals, same order, same ids). Each free-text source is scanned for SPDX ids,
    license/terms/restriction phrases, and license/terms-pointing URLs; the branding
    ``website_url`` — already a validated URL, not prose — is only *classified*, so an
    ordinary homepage contributes nothing.

    Args:
        instructions: The snapshot's free-text usage guidance
            (``mcp_endpoint_versions.instructions``), if any.
        server_title: The server's advertised display title, if any.
        website_url: The validated branding website URL
            (``server_branding.website_url``), if any.

    Returns:
        The :class:`LicenseSignalsReport`; ``status`` is :data:`STATUS_NOT_STATED` (with a
        carefully worded statement) when nothing matches or there is nothing to scan.
    """
    sources_scanned: List[str] = []
    signals: List[LicenseSignal] = []

    for source in _SOURCE_ORDER:
        if source == SOURCE_INSTRUCTIONS:
            text = instructions
        elif source == SOURCE_SERVER_TITLE:
            text = server_title
        else:
            text = website_url
        if text is None or not str(text).strip():
            continue
        sources_scanned.append(source)
        if source == SOURCE_WEBSITE_URL:
            signals.extend(_classify_url(str(text), source, excerpt=""))
        else:
            signals.extend(_scan_text(str(text)[:MAX_SCANNED_CHARS], source))

    shown = signals[:MAX_SIGNALS]
    truncated = max(0, len(signals) - len(shown))
    status = STATUS_DETECTED if shown else STATUS_NOT_STATED
    return LicenseSignalsReport(
        status=status,
        statement=_statement(status, len(signals), tuple(sources_scanned)),
        signals=tuple(shown),
        signals_truncated=truncated,
        sources_scanned=tuple(sources_scanned),
    )


def _statement(status: str, signal_count: int, sources_scanned: Tuple[str, ...]) -> str:
    """Word the one-line summary, stating absence as "not stated" — never "no license"."""
    if status == STATUS_DETECTED:
        noun = "signal" if signal_count == 1 else "signals"
        return (
            f"{signal_count} license/terms {noun} detected in the server's advertised text — "
            "informational only, not a compliance verdict."
        )
    if not sources_scanned:
        return (
            "Not stated — the server advertised no instructions or metadata to scan. "
            "This is not a claim that the server has no license or terms."
        )
    scanned = ", ".join(sources_scanned)
    return (
        f"Not stated — no license or terms signals were detected in the scanned sources "
        f"({scanned}). This is not a claim that the server has no license or terms."
    )


def _scan_text(text: str, source: str) -> List[LicenseSignal]:
    """Run every detector over one free-text ``source``, in deterministic position order.

    A single span of text is claimed by at most one match per family — the SPDX id
    ``Apache-2.0`` inside "licensed under Apache-2.0" does not suppress the phrase (they
    are different families and both informative), but the bare-"license" phrase never
    double-reports the words already claimed by "licensed under". Text inside a URL is
    the URL classifier's alone: ``https://acme.example/terms`` is one ``terms_url``
    signal, not also a "terms"-phrase hit. Matches are ordered by position in the text,
    then by kind, so output is stable for a fixed input.

    Args:
        text: The (already length-bounded) source text.
        source: The ``SOURCE_*`` constant to stamp on each signal.

    Returns:
        The ordered signals found in ``text``.
    """
    hits: List[Tuple[int, str, str, str]] = []  # (position, kind, matched, excerpt)

    # URLs first — license/terms-pointing links become signals (an ordinary link is not a
    # signal), and every URL's span suppresses phrase/SPDX matching over the same characters.
    urls = _iter_urls(text)
    url_spans = [(position, position + len(url)) for position, url in urls]
    for position, url in urls:
        for signal in _classify_url(url, source, excerpt=_excerpt_at(text, position, len(url))):
            hits.append((position, signal.kind, signal.matched, signal.excerpt))

    def _outside_urls(pattern: "re.Pattern[str]") -> Optional["re.Match[str]"]:
        """First match of ``pattern`` that does not fall inside a URL span."""
        for match in pattern.finditer(text):
            inside = any(
                match.start() < end and match.end() > start for start, end in url_spans
            )
            if not inside:
                return match
        return None

    # SPDX identifiers — report each distinct id once per source (first occurrence).
    for spdx, pattern in _SPDX_PATTERNS:
        match = _outside_urls(pattern)
        if match:
            hits.append((match.start(), KIND_SPDX_ID, spdx, _excerpt(text, match)))

    # Keyword phrases — longest-first per family; a claimed span blocks shorter overlaps
    # within the same family so "licensed under" is not also a bare-"license" hit.
    claimed: Dict[str, List[Tuple[int, int]]] = {}
    for kind, phrase, pattern in _PHRASE_PATTERNS:
        match = _outside_urls(pattern)
        if not match:
            continue
        spans = claimed.setdefault(kind, [])
        if any(match.start() < end and match.end() > start for start, end in spans):
            continue
        spans.append((match.start(), match.end()))
        hits.append((match.start(), kind, phrase, _excerpt(text, match)))

    hits.sort(key=lambda hit: (hit[0], hit[1], hit[2]))
    return [
        LicenseSignal(kind=kind, source=source, matched=matched, excerpt=excerpt)
        for _, kind, matched, excerpt in hits
    ]


def _iter_urls(text: str) -> List[Tuple[int, str]]:
    """Extract bare URLs from free text with their positions, trimming trailing punctuation."""
    urls: List[Tuple[int, str]] = []
    for match in _URL_PATTERN.finditer(text):
        url = match.group(0).rstrip(_TRAILING_PUNCTUATION)
        if url:
            urls.append((match.start(), url))
    return urls


def _classify_url(url: str, source: str, *, excerpt: str) -> List[LicenseSignal]:
    """Classify one URL as a license or terms pointer (or neither → no signal).

    License hints win over terms hints when both match (``/legal/license`` is a license
    pointer), so a URL yields at most one signal.
    """
    lowered = url.lower()
    if any(hint in lowered for hint in _LICENSE_URL_HINTS):
        kind = KIND_LICENSE_URL
    elif any(hint in lowered for hint in _TERMS_URL_HINTS):
        kind = KIND_TERMS_URL
    else:
        return []
    return [LicenseSignal(kind=kind, source=source, matched=url, excerpt=excerpt)]


def _excerpt(text: str, match: "re.Match[str]") -> str:
    """Return the bounded context window around a regex ``match``."""
    return _excerpt_at(text, match.start(), match.end() - match.start())


def _excerpt_at(text: str, position: int, length: int) -> str:
    """Return a whitespace-collapsed context window around ``text[position:position+length]``.

    The window extends :data:`_EXCERPT_RADIUS` characters either side of the match and is
    marked with leading/trailing ellipses when it is a strict substring, so a reader can
    tell a fragment from the whole text.
    """
    start = max(0, position - _EXCERPT_RADIUS)
    end = min(len(text), position + length + _EXCERPT_RADIUS)
    window = " ".join(text[start:end].split())
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{window}{suffix}"
