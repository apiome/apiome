"""Secret scrubbing for import intake — IXH-1.4 (#5090), completed by MFI-29.6 (#4393).

Uploaded API descriptions routinely carry live credentials: a Postman collection
with a bearer token, an OpenAPI ``servers`` URL with basic-auth userinfo, an
example block with an AWS key, a connection string in a description. Intake
persists the *verbatim* source (``format_metadata.sourceContent``, MFI-23.9) and
echoes parser errors — which quote the offending line — into the job event log, so
without scrubbing a secret lands in the database and in every status poll.

This module is the scrubbing pass. It is deliberately **value-only**: each match
is replaced by :data:`REDACTION_MARKER` in place, so the document's structure —
and therefore its fingerprint-relevant shape — is untouched, satisfying the
MFI-29.6 acceptance criterion that scrubbing never alters structure. Findings
record *what* and *where* (secret type, line number), never the value itself.

Detection is two-layered (MFI-29.6):

* **named patterns** — provider key shapes, authorization headers, cookie jars,
  URL userinfo, secret-*named* assignments, and the ``{"key" | "name": <secret name>,
  "value": …}`` pair lists client exports use (FMT-10.1, FMT-10.2), and the XML shapes a SoapUI
  project keeps credentials in — a secret-named element's text (``<con:password>``, an escaped
  ``&lt;wsse:Password&gt;`` inside a saved envelope), ``key="<secret name>" value="…"``
  attribute pairs and ``<name>`` / ``<value>`` element pairs (FMT-10.3). Always on: each one is a
  shape that is a credential and nothing else.
* **entropy** — a value the patterns cannot name (a bespoke opaque token under a
  neutral key such as ``value`` or ``X-Custom-Auth``) is caught by its randomness.
  Because a heuristic can be wrong in a way a named pattern cannot, this layer is
  separately switchable (:func:`scrub_document_text`'s ``entropy_detection``,
  driven by the tenant policy in :mod:`app.intake_scrub_policy`), and is deliberately
  narrow — see :func:`_looks_like_secret_entropy`.

Whether a scrub is *applied* or merely *reported* is not decided here: this module
always returns both the redacted text and the findings, and
:func:`app.import_source_pipeline.scrub_intake_source` chooses between them
according to the tenant's ``enforce`` / ``warn_only`` mode.

Distinct from :func:`app.mcp_protocol_transcript.redact_text`, which scrubs short
free-text error strings and truncates them: that is right for a 200-character
transcript message and wrong for a document that must stay parseable.
"""

from __future__ import annotations

import math
import re
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Pattern, Tuple

__all__ = [
    "ENTROPY_MAX_LENGTH",
    "ENTROPY_MIN_BITS_PER_CHAR",
    "ENTROPY_MIN_LENGTH",
    "COOKIE_JAR_SECRET_TYPE",
    "ENTROPY_SECRET_TYPE",
    "REDACTION_MARKER",
    "ScrubFinding",
    "ScrubOutcome",
    "scrub_document_text",
    "scrub_message",
]

#: Replacement for every redacted value. Contains no quote or escape character, so
#: substituting it inside a JSON/YAML/XML string literal keeps the document valid.
REDACTION_MARKER = "«redacted»"


def _p(pattern: str, flags: int = 0) -> Pattern[str]:
    return re.compile(pattern, flags)


#: An XML element name that names a secret (``password``, ``wsse:Password``, ``clientSecret``,
#: ``accessToken``) — the assignment vocabulary, without a bare ``token``.
_XML_SECRET_NAME = (
    r"[A-Za-z0-9_.\-]*"
    r"(?:password|passwd|secret|api[-_]?key|apikey|access[-_]?token|refresh[-_]?token"
    r"|auth[-_]?token|client[-_]?secret|private[-_]?key|credential|passphrase)"
    r"[A-Za-z0-9_.\-]*"
)

#: Credential patterns, each named by the secret *type* it recognizes. Group 1, when
#: present, is the span actually replaced — that keeps surrounding structure (the
#: key, the scheme, the URL host) intact so only the secret value is lost.
#:
#: Ordered most-specific first: a provider-shaped key is reported as that provider
#: rather than as a generic assignment.
_PATTERNS: Tuple[Tuple[str, Pattern[str]], ...] = (
    # --- provider-specific key shapes ------------------------------------------
    ("aws-access-key-id", _p(r"\b((?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA|ANVA)[0-9A-Z]{16})\b")),
    ("github-token", _p(r"\b((?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})\b")),
    ("slack-token", _p(r"\b(xox[abposr]-[A-Za-z0-9-]{10,})\b")),
    # {35,} not {35}: a trailing \b after a fixed count fails when the key runs longer,
    # which silently let a real-shaped key through.
    ("google-api-key", _p(r"\b(AIza[0-9A-Za-z_\-]{35,})")),
    ("stripe-key", _p(r"\b((?:sk|rk)_(?:live|test)_[0-9A-Za-z]{16,})\b")),
    ("jwt", _p(r"\b(eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]+)")),
    ("private-key-block", _p(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"
        r"([\s\S]*?)"
        r"-----END (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"
    )),
    # --- credentials embedded in URLs (basic auth / connection strings) ---------
    # Replaces only the userinfo, keeping scheme and host so the URL stays readable.
    ("url-embedded-credential", _p(r"://[^/\s:@\"']+:([^/\s@\"']+)@")),
    # --- authorization headers and header-shaped values ------------------------
    ("authorization-header", _p(
        r"(?:\"|')?[Aa]uthorization(?:\"|')?\s*[:=]\s*(?:\"|')?"
        r"(?:Bearer|Basic|Token|ApiKey)\s+([^\"'\s,}\]]+)",
    )),
    ("bearer-token", _p(r"\b(?:Bearer|Basic)\s+([A-Za-z0-9_\-\.=+/]{12,})")),
    # --- cookie jars -----------------------------------------------------------
    # A ``Cookie``/``Set-Cookie`` header value is a credential in full: Postman and
    # HAR exports carry live session cookies. The whole value is replaced (cookie
    # values legitimately contain ``;`` and ``=``, so the span cannot be narrowed).
    ("cookie-header", _p(
        r"(?:\"|')?(?:set-)?cookie(?:\"|')?\s*[:=]\s*(?:\"|')?([^\"'\n]{4,})",
        re.IGNORECASE,
    )),
    # --- generic secret-named assignments (JSON/YAML/env/query) ----------------
    # The key must *name* a secret; a short or placeholder-looking value still gets
    # redacted, because deciding "this one is fake" is not intake's call.
    # The lookbehind lets a match start only where a key-character run starts. The leftmost
    # match always started there anyway (the leading class covers the same characters), but
    # without it the engine retried every position inside a long run — quadratic on a long
    # token-shaped string, which the usage ingest edge (RDG-1.2) scrubs on every event.
    # The quotes may be JSON-escaped (``\"password\": \"…\"``): a HAR capture (MFI-32.2) and a
    # Postman raw body keep request and response bodies as JSON *strings*. A backslash that escapes
    # the closing quote is never part of the value, so redacting the value keeps the string valid.
    ("secret-assignment", _p(
        r"(?:\\?\"|')?(?<![A-Za-z0-9_\-])[A-Za-z0-9_\-]*"
        r"(?:password|passwd|secret|api[-_]?key|apikey|access[-_]?token|refresh[-_]?token"
        r"|auth[-_]?token|client[-_]?secret|private[-_]?key|credential|passphrase"
        r"|session[-_]?id|sessionid|session)"
        r"[A-Za-z0-9_\-]*(?:\\?\"|')?\s*[:=]\s*(?:\\?\"|')?"
        r"((?:[^\"'\s,}\]&\\]|\\(?![\"'])){4,})",
        re.IGNORECASE,
    )),
    # A key named exactly ``token`` — where a Hoppscotch bearer / OAuth 2 auth block keeps its
    # credential (FMT-10.1) — or exactly ``bearer``, where a Thunder Client bearer auth block keeps
    # it (FMT-10.2). Not folded into the alternation above, which also matches names that merely
    # *contain* a secret word: ``token`` inside ``tokenUrl`` or ``nextPageToken`` is not one.
    ("secret-assignment", _p(
        r"(?:\"|')?(?<![A-Za-z0-9_\-])(?:token|bearer)(?:\"|')?\s*:\s*(?:\"|')([^\"'\s,}\]&]{4,})",
        re.IGNORECASE,
    )),
    # --- name/value pair lists (Hoppscotch / Postman exports) --------------------
    # Client exports store variables, auth parameters and API keys as ``{"key": <name>,
    # "value": <value>}`` objects (Thunder Client spells the name member ``name``), so the
    # secret's *name* is a value and the assignment pattern cannot see it. A ``key`` / ``name``
    # naming a secret — or an ``Authorization`` / ``Cookie`` header — marks the ``value`` /
    # ``initialValue`` / ``currentValue`` member of the same object (scalar members may sit
    # between them). One pattern per value member, so an environment variable carrying both an
    # initial and a current value has both redacted.
    *(
        ("secret-key-value-pair", _p(
            r"\"(?:key|name)\"\s*:\s*\"[^\"\n]*"
            r"(?:password|passwd|secret|api[-_]?key|apikey|token|credential|passphrase"
            r"|session|private[-_]?key|authorization|cookie)"
            r"[^\"\n]*\"\s*,"
            r"(?:\s*\"[A-Za-z_]+\"\s*:\s*(?:\"[^\"\n]*\"|true|false|null|-?\d+)\s*,)*?"
            rf"\s*\"{member}\"\s*:\s*\"((?:[^\"\\\n]|\\.){{4,}})\"",
            re.IGNORECASE,
        ))
        for member in ("value", "initialValue", "currentValue")
    ),
    # --- XML-shaped credentials (SoapUI / ReadyAPI projects) ---------------------
    # A SoapUI project keeps a saved request's password as element text
    # (``<con:password>…</con:password>``) and a saved SOAP envelope — escaped into the project
    # XML — carries WS-Security as ``&lt;wsse:Password …&gt;…&lt;/wsse:Password&gt;`` (FMT-10.3).
    # The element's *name* must name a secret (same vocabulary as the assignment pattern above,
    # so a bare ``<token>`` — SoapUI's *Contains* assertion text — is left alone).
    ("secret-xml-element", _p(
        r"<(?:[A-Za-z_][\w.\-]*:)?" + _XML_SECRET_NAME + r"(?:\s[^<>]*)?>"
        r"\s*([^<\s][^<]{2,}[^<\s])\s*</",
        re.IGNORECASE,
    )),
    ("secret-xml-element", _p(
        r"&lt;(?:[A-Za-z_][\w.\-]*:)?" + _XML_SECRET_NAME + r"(?:\s(?:(?!&gt;)[^<>])*)?&gt;"
        r"\s*((?:(?!&lt;)[^<\s])(?:(?!&lt;)[^<]){2,}?(?:(?!&lt;)[^<\s]))\s*&lt;/",
        re.IGNORECASE,
    )),
    # A ``<con:name><secret name></con:name><con:value>…</con:value>`` element pair — how SoapUI
    # keeps a property's value and a REST parameter's default.
    ("secret-key-value-pair", _p(
        r"<(?:[A-Za-z_][\w.\-]*:)?name>\s*[^<\n]*"
        r"(?:password|passwd|secret|api[-_]?key|apikey|token|credential|passphrase"
        r"|session|private[-_]?key|authorization|cookie)"
        r"[^<\n]*</(?:[A-Za-z_][\w.\-]*:)?name>\s*"
        r"<(?:[A-Za-z_][\w.\-]*:)?value>\s*([^<\s][^<]{2,}[^<\s])\s*</",
        re.IGNORECASE,
    )),
    # A ``<con:entry key="<secret name>" value="…"/>`` attribute pair — how SoapUI stores a saved
    # request's parameter values and headers (also escaped inside a ``@request-headers`` setting).
    ("secret-key-value-pair", _p(
        r"\bkey\s*=\s*\"[^\"\n]*"
        r"(?:password|passwd|secret|api[-_]?key|apikey|token|credential|passphrase"
        r"|session|private[-_]?key|authorization|cookie)"
        r"[^\"\n]*\"\s+value\s*=\s*\"([^\"\n]{4,})\"",
        re.IGNORECASE,
    )),
)


#: Secret type reported for a member of a ``"cookies": [...]`` jar (see :func:`_cookie_jar_spans`).
COOKIE_JAR_SECRET_TYPE = "cookie-jar-value"

#: Where a cookie jar starts: a HAR request/response ``cookies`` list (MFI-32.2), or a Postman
#: cookie export.
_COOKIE_JAR_START: Pattern[str] = _p(r"\"cookies\"\s*:\s*\[")

#: A ``"value": "<text>"`` member inside a jar.
_COOKIE_JAR_VALUE: Pattern[str] = _p(r"\"value\"\s*:\s*\"((?:[^\"\\\n]|\\.)+)\"")


def _json_array_end(text: str, start: int) -> int:
    """Offset just past the ``]`` closing the JSON array whose body begins at ``start``.

    String-aware, so a ``]`` inside a cookie value does not end the array early. An unterminated
    array runs to the end of the text.
    """
    depth = 1
    in_string = False
    index = start
    length = len(text)
    while index < length:
        char = text[index]
        if in_string:
            if char == "\\":
                index += 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return length


def _cookie_jar_spans(text: str) -> List[Tuple[int, int]]:
    """Every ``value`` span inside a ``"cookies": [...]`` array.

    A HAR capture keeps each request's and response's cookies as ``{"name": …, "value": …}``
    objects, and a cookie's *name* (``sid``, ``connect.sid``, ``_gh_sess``) rarely says it is a
    credential, so the name/value-pair patterns cannot see them. Every cookie value in a jar is
    session material, so all of them are redacted, whatever they are called.
    """
    spans: List[Tuple[int, int]] = []
    scanned_to = 0
    for start in _COOKIE_JAR_START.finditer(text):
        # A jar opener inside a jar already scanned adds nothing, and skipping it keeps a document of
        # many unterminated openers linear rather than rescanning the tail once per opener.
        if start.start() < scanned_to:
            continue
        scanned_to = _json_array_end(text, start.end())
        for value in _COOKIE_JAR_VALUE.finditer(text, start.end(), scanned_to):
            spans.append(value.span(1))
        if scanned_to >= len(text):
            break
    return spans


#: Secret type reported for a value the named patterns could not identify but whose
#: randomness gives it away.
ENTROPY_SECRET_TYPE = "high-entropy-string"

#: Shortest run the entropy heuristic will consider. Below this a random-looking token
#: cannot be told apart from an identifier, and the entropy of a short string is bounded
#: by its length anyway (a 16-character string cannot exceed 4 bits/char).
ENTROPY_MIN_LENGTH = 24

#: Longest run the entropy heuristic will consider. Above this the value is an embedded
#: payload (a base64 image, an inlined certificate chain, a captured response body), not a
#: credential — redacting it would destroy a legitimate example for no security gain.
ENTROPY_MAX_LENGTH = 128

#: Shannon entropy floor, in bits per character. Measured on the two populations this has
#: to separate at these lengths: long identifier-shaped strings that dominate an API
#: description (camelCase operation ids, header names, dotted URNs) top out around 4.35,
#: while generated credential material (mixed alphanumeric, base64) starts around 4.55.
#: The floor sits in that gap, so neither side is decided by a rounding error. Hex digests
#: (≤ 4.0 by alphabet) and UUIDs (≈ 3.4) are further excluded by :data:`_ENTROPY_EXEMPT`.
ENTROPY_MIN_BITS_PER_CHAR = 4.45

#: Characters a credential run may contain. ``/`` is deliberately **excluded**: including it
#: would let a run swallow a URL path (``api.example.com/v1/orders``), and the credential
#: alphabets that matter (hex, alphanumeric, base64url) do not use it.
_ENTROPY_CHARS = r"A-Za-z0-9_\-\.+="

#: Candidate runs for the entropy heuristic. The lookarounds make each match **maximal**, which
#: is what gives :data:`ENTROPY_MAX_LENGTH` its meaning: without them a 224-character embedded
#: payload would simply match as two in-range chunks and be redacted anyway. The upper bound is
#: enforced in the predicate instead of the pattern for exactly that reason.
_ENTROPY_CANDIDATE: Pattern[str] = _p(
    r"(?<![%s])[%s]{%d,}(?![%s])" % (_ENTROPY_CHARS, _ENTROPY_CHARS, ENTROPY_MIN_LENGTH, _ENTROPY_CHARS)
)

#: Shapes that are long, mixed, and *not* secrets. Checked before the entropy score so the
#: outcome does not depend on where a particular digest happens to land near the threshold.
_ENTROPY_EXEMPT: Tuple[Pattern[str], ...] = (
    # RFC 4122 UUID, with or without dashes — an identifier, and one that appears in
    # practically every captured collection.
    _p(r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"),
    # Pure hexadecimal: a checksum/digest/fingerprint. Its alphabet caps entropy at 4 bits,
    # but an uppercase-and-lowercase mixed digest could otherwise drift over the floor.
    _p(r"\A[0-9a-fA-F]+\Z"),
    # Dotted or dashed numeric runs: timestamps, semver ranges, OIDs.
    _p(r"\A[0-9][0-9._\-+]*\Z"),
)


def _shannon_entropy(value: str) -> float:
    """Return the Shannon entropy of ``value`` in bits per character.

    Args:
        value: The string to score; ``""`` scores 0.

    Returns:
        Average bits per character — 0 for a single repeated character, ``log2(n)`` for a
        string of ``n`` distinct, equally frequent characters.
    """
    if not value:
        return 0.0
    length = len(value)
    return -sum(
        (count / length) * math.log2(count / length) for count in Counter(value).values()
    )


def _looks_like_secret_entropy(value: str) -> bool:
    """Whether an unnamed run is random enough to be treated as a credential.

    The heuristic half of MFI-29.6's "pattern + entropy detection". It exists for the
    credential no pattern can name — an opaque token under a neutral key (``value``,
    ``X-Company-Auth``) — and is intentionally reluctant: a false positive silently
    corrupts a legitimate example, so every one of the following must hold.

    * length within [:data:`ENTROPY_MIN_LENGTH`, :data:`ENTROPY_MAX_LENGTH`];
    * both letters and digits present — the identifiers this must not touch are usually
      one or the other, while generated credentials are reliably both;
    * both upper and lower case present, for the same reason;
    * not a known non-secret shape (UUID, hex digest, numeric run);
    * Shannon entropy at or above :data:`ENTROPY_MIN_BITS_PER_CHAR`.

    Args:
        value: The candidate run, already bounded by the caller's character class.

    Returns:
        ``True`` when the run should be redacted as a high-entropy secret.
    """
    if not (ENTROPY_MIN_LENGTH <= len(value) <= ENTROPY_MAX_LENGTH):
        return False
    if not any(char.isdigit() for char in value):
        return False
    if not any(char.islower() for char in value):
        return False
    if not any(char.isupper() for char in value):
        return False
    if any(pattern.match(value) for pattern in _ENTROPY_EXEMPT):
        return False
    return _shannon_entropy(value) >= ENTROPY_MIN_BITS_PER_CHAR


@dataclass(frozen=True)
class ScrubFinding:
    """One redacted secret: what kind and where, never the value.

    Attributes:
        secret_type: The pattern name that matched (e.g. ``aws-access-key-id``).
        line: 1-based line number of the match within the document.
        occurrences: How many values of this type were redacted on that line.
    """

    secret_type: str
    line: int
    occurrences: int = 1

    def as_dict(self) -> Dict[str, object]:
        """Return the finding as a JSON-safe dict for the job summary."""
        return {
            "secret_type": self.secret_type,
            "line": self.line,
            "occurrences": self.occurrences,
        }


@dataclass
class ScrubOutcome:
    """Result of scrubbing one document.

    Attributes:
        text: The document with every detected secret value replaced by
            :data:`REDACTION_MARKER`. Identical to the input when nothing matched.
        findings: One entry per (secret type, line) pair that was redacted.
    """

    text: str
    findings: List[ScrubFinding] = field(default_factory=list)

    @property
    def scrubbed(self) -> bool:
        """Whether anything was redacted."""
        return bool(self.findings)

    @property
    def redaction_count(self) -> int:
        """Total number of redacted values."""
        return sum(finding.occurrences for finding in self.findings)

    def report(self) -> Dict[str, object]:
        """Build the job-summary scrub report (types and locations, no values)."""
        return {
            "scrubbed": self.scrubbed,
            "redactions": self.redaction_count,
            "secret_types": sorted({finding.secret_type for finding in self.findings}),
            "findings": [finding.as_dict() for finding in self.findings],
        }


#: Unquoted JSON/YAML scalars that can never hold a credential.
_NON_SECRET_LITERALS = frozenset({"true", "false", "null", "~"})


def _is_unquoted_literal(text: str, start: int, end: int, secret_type: str) -> bool:
    """True when a secret-named key's value is an unquoted boolean/null literal.

    ``allowCredentials: true`` (CORS in an API Gateway export) names a credential but holds a
    boolean; redacting it turns the boolean into a string and corrupts the document. A quoted
    ``"true"`` is still a string and is still redacted.
    """
    if secret_type != "secret-assignment" or text[start:end].lower() not in _NON_SECRET_LITERALS:
        return False
    return start == 0 or text[start - 1] not in "\"'" or _is_attribute_boolean(text, start, end)


def _is_attribute_boolean(text: str, start: int, end: int) -> bool:
    """True when a quoted ``true``/``false`` is an XML attribute value (``name="true"``).

    ``<cors allow-credentials="true">`` (an Azure API Management policy) names a credential but
    holds a boolean; XML quotes every attribute value, so the unquoted-literal rule cannot see it.
    Only ``=``-assignments are exempt: a JSON ``"key": "true"`` is a string and is still redacted.
    """
    if text[start:end].lower() not in ("true", "false") or end >= len(text) or text[end] != text[start - 1]:
        return False
    before = text[: start - 1].rstrip()
    return before.endswith("=")


def _collect_secret_spans(
    text: str, *, entropy_detection: bool
) -> List[Tuple[int, int, str]]:
    """Find the non-overlapping spans of ``text`` that hold credential values.

    Detection runs against the **original** text, never against a partly-redacted copy.
    That is what keeps the reported line numbers exact even when a match spans lines (a
    PEM block collapses to a single marker), and it makes the "most-specific pattern
    wins" rule explicit: a span already claimed by an earlier, more specific pattern is
    skipped rather than re-reported under a generic one.

    Args:
        text: The original document text.
        entropy_detection: Whether the high-entropy heuristic runs after the named
            patterns. The named patterns always run.

    Returns:
        Claimed ``(start, end, secret_type)`` spans, sorted by start offset and
        guaranteed not to overlap.
    """
    # Kept sorted by start offset so an overlap test only has to look at the two neighbouring
    # spans, not at every span claimed so far. A linear scan would be O(n²) in the number of
    # secrets, and the formats this protects most (a HAR capture, a Postman collection with a
    # large cookie jar) are precisely the ones that carry thousands of them.
    claimed: List[Tuple[int, int, str]] = []

    def _claim(start: int, end: int, secret_type: str) -> None:
        """Record a span unless it is empty, already redacted, or already claimed."""
        if end <= start:
            return
        if REDACTION_MARKER in text[start:end]:
            return
        position = bisect_left(claimed, (start, end, secret_type))
        if position > 0 and claimed[position - 1][1] > start:
            return  # the preceding span runs into this one
        if position < len(claimed) and claimed[position][0] < end:
            return  # this span runs into the following one
        claimed.insert(position, (start, end, secret_type))

    for secret_type, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            # Group 1 is the secret span when the pattern defines one; otherwise the
            # whole match is the secret.
            group = 1 if match.re.groups >= 1 else 0
            start, end = match.span(group)
            if start >= 0 and not _is_unquoted_literal(text, start, end, secret_type):
                _claim(start, end, secret_type)

    for start, end in _cookie_jar_spans(text):
        _claim(start, end, COOKIE_JAR_SECRET_TYPE)

    if entropy_detection:
        for match in _ENTROPY_CANDIDATE.finditer(text):
            if _looks_like_secret_entropy(match.group()):
                _claim(match.start(), match.end(), ENTROPY_SECRET_TYPE)

    return claimed


def scrub_document_text(text: str, *, entropy_detection: bool = True) -> ScrubOutcome:
    """Redact credential values in a source document, preserving its structure.

    Only the credential *value* is replaced (the naming key, URL scheme/host, and auth
    scheme survive), so the document remains parseable and structurally unchanged —
    values only, per the MFI-29.6 contract.

    This function always *produces* the redacted text. Whether that text is the one
    persisted is the caller's decision: under a ``warn_only`` tenant policy
    :func:`app.import_source_pipeline.scrub_intake_source` keeps the findings and
    discards the rewrite.

    Args:
        text: The raw document text.
        entropy_detection: Whether to run the high-entropy heuristic in addition to the
            named credential patterns. Defaults to on; the tenant policy can disable it
            when a corpus of opaque-but-public identifiers trips it.

    Returns:
        A :class:`ScrubOutcome` carrying the redacted text and per-line findings.
        When nothing matches, the text is returned unchanged with no findings.
    """
    if not text:
        return ScrubOutcome(text=text or "", findings=[])

    spans = _collect_secret_spans(text, entropy_detection=entropy_detection)
    if not spans:
        return ScrubOutcome(text=text, findings=[])

    # (secret_type, line) -> occurrences, so a report line is one entry per type.
    tally: Dict[Tuple[str, int], int] = {}
    pieces: List[str] = []
    cursor = 0
    # Spans are sorted, so the line number is advanced incrementally: counting from the start of the
    # text for every span is quadratic on a capture carrying thousands of cookie values.
    line, counted_to = 1, 0
    for start, end, secret_type in spans:
        pieces.append(text[cursor:start])
        pieces.append(REDACTION_MARKER)
        cursor = end
        line += text.count("\n", counted_to, start)
        counted_to = start
        key = (secret_type, line)
        tally[key] = tally.get(key, 0) + 1
    pieces.append(text[cursor:])

    findings = [
        ScrubFinding(secret_type=secret_type, line=line, occurrences=count)
        for (secret_type, line), count in sorted(tally.items(), key=lambda item: (item[0][1], item[0][0]))
    ]
    return ScrubOutcome(text="".join(pieces), findings=findings)


def scrub_message(message: Optional[str]) -> Optional[str]:
    """Redact credentials from a free-text message before it is logged or stored.

    Parser errors quote the offending source span, so a malformed line carrying a
    token would otherwise reach the job event log and the server log verbatim.
    Unlike :func:`scrub_document_text` this makes no structural promises — it is
    for human-readable text.

    Deliberately **not** governed by the tenant's scrub mode: ``warn_only`` is a statement
    about the source material the catalog persists, not permission to splash credentials
    across a log aggregator, which is a different system with a different audience and its
    own retention. Entropy detection is likewise always on here — over-redacting a
    diagnostic costs a few characters of context.

    Args:
        message: The message to scrub; ``None`` passes through.

    Returns:
        The scrubbed message, or ``None`` when ``message`` was ``None``.
    """
    if message is None:
        return None
    return scrub_document_text(message).text
