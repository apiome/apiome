"""Deprecation & lifecycle signal detection over MCP capabilities (V2-MCP-34.4 / MCAT-20.4).

Servers signal "this tool is deprecated / experimental / beta" informally — a marker in the
``description``, a vendor annotation, a ``_beta`` suffix in the name — and catalog users never
see it aggregated. This module is a **pure detector** that inspects each normalized capability
(tool / resource / resource template / prompt) a discovery snapshot already captured and
reports per-capability lifecycle signals:

* **Annotation flags** — a boolean annotation key asserting a stage (``deprecated: true``).
* **Annotation status values** — a lifecycle-ish annotation key carrying a stage word
  (``stability: "beta"``, ``status: "experimental"``).
* **Name / title tokens** — a stage word appearing as a whole token of the programmatic name
  or human title (``search_beta``, ``legacyExport``; never a substring, so ``alphabet`` is
  not ``beta``).
* **Description phrases** — a curated stage phrase in the free-text description
  ("deprecated", "will be removed", "in beta", "(alpha)", …).

Each capability rolls up to a single **stage** — the most urgent stage among its signals
(:data:`STAGE_DEPRECATED` > :data:`STAGE_EXPERIMENTAL` > :data:`STAGE_BETA` >
:data:`STAGE_STABLE`) — which is what a UI badge renders.

Design rules (mirroring :mod:`app.mcp_license_signals`):

* **Pure & deterministic** — no database or network access; the same inputs always produce
  the same signals in the same order, and every signal ``id`` is a stable hash, so results
  can be compared across runs.
* **Informational only, no enforcement.** A signal means "the capability's own text or
  annotations *say* this", never a verified lifecycle fact. Nothing here gates cataloging
  or invocation.
* **No signal is never a "stable" claim.** A capability with no signal has stage
  :data:`STAGE_UNSPECIFIED` — the server said nothing, which is not a stability statement.
  :data:`STAGE_STABLE` is reported **only** when an annotation explicitly declares it
  (``stability: "stable"``); it is never inferred.

The public surface is :func:`assess_capability_lifecycle` (one capability →
:class:`CapabilityLifecycle`) and :func:`detect_lifecycle_signals` (a snapshot's capability
items → :class:`LifecycleSignalsReport`), plus the stage / kind / source constants. The
capability-list API serializes the per-item result; the report card (V2-MCP-33.1 /
MCAT-19.1) consumes the aggregate report's :meth:`~LifecycleSignalsReport.as_dict`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# --- Lifecycle stages ---------------------------------------------------------------------------
# Ordered most- to least-urgent; a capability's rolled-up stage is the most urgent stage any of
# its signals asserts.

#: The capability is marked deprecated / obsolete / scheduled for removal.
STAGE_DEPRECATED = "deprecated"

#: The capability is marked experimental / alpha / unstable / preview.
STAGE_EXPERIMENTAL = "experimental"

#: The capability is marked beta.
STAGE_BETA = "beta"

#: An annotation **explicitly declares** the capability stable. Never inferred from silence —
#: this stage exists so an explicit declaration reads differently from no statement at all.
STAGE_STABLE = "stable"

#: No lifecycle signal found. Deliberately worded as "unspecified", never "stable" — the
#: absence of a signal is the absence of a statement (AC: no signal ≠ a "stable" claim).
STAGE_UNSPECIFIED = "unspecified"

#: Roll-up precedence, most urgent first (:data:`STAGE_UNSPECIFIED` is the no-signal default
#: and never carried by a signal).
_STAGE_PRECEDENCE: Tuple[str, ...] = (
    STAGE_DEPRECATED,
    STAGE_EXPERIMENTAL,
    STAGE_BETA,
    STAGE_STABLE,
)

# --- Signal kinds ---------------------------------------------------------------------------

#: A boolean annotation key asserted a stage (``deprecated: true``).
KIND_ANNOTATION_FLAG = "annotation_flag"

#: A lifecycle-ish annotation key carried a stage word (``stability: "beta"``).
KIND_ANNOTATION_STATUS = "annotation_status"

#: A stage word appeared as a whole token of the name or title (``search_beta``).
KIND_NAME_TOKEN = "name_token"

#: A curated stage phrase appeared in the description ("will be removed", "in beta").
KIND_DESCRIPTION_PHRASE = "description_phrase"

# --- Sources ---------------------------------------------------------------------------------
# Scanned in this fixed order so signal ordering (and therefore rendering) is deterministic.

SOURCE_ANNOTATIONS = "annotations"
SOURCE_NAME = "name"
SOURCE_TITLE = "title"
SOURCE_DESCRIPTION = "description"

# --- Bounds ----------------------------------------------------------------------------------

#: Cap on the signals itemized per capability. The roll-up stage is decided over *all* hits;
#: past this many itemized signals the marginal one adds nothing. Overflow is counted in
#: ``signals_truncated``, never silently dropped.
MAX_SIGNALS_PER_CAPABILITY = 8

#: Cap on the flagged capabilities the aggregate report itemizes. Stage *counts* always cover
#: every capability; only the itemization is bounded, with overflow counted.
MAX_FLAGGED_CAPABILITIES = 50

#: Cap on how much of a single description is scanned. Bounds regex cost on a pathological
#: (multi-megabyte) description blob; real descriptions are well under a KB.
MAX_SCANNED_CHARS = 20_000

#: Length of the whitespace-collapsed context excerpt carried by description signals.
_EXCERPT_RADIUS = 60

# --- Pattern tables ---------------------------------------------------------------------------

#: Boolean annotation keys that assert a stage when strictly ``True`` (JSON ``true`` only —
#: mirrors :func:`app.mcp_lint_annotations._bool_hint`'s strictness; the string ``"true"``
#: does not count). Keys are compared case-insensitively.
_ANNOTATION_FLAG_STAGES: Mapping[str, str] = {
    "deprecated": STAGE_DEPRECATED,
    "experimental": STAGE_EXPERIMENTAL,
    "beta": STAGE_BETA,
}

#: Annotation keys whose *string value* is read as a lifecycle status word. Compared
#: case-insensitively; a value outside :data:`_STATUS_VALUE_STAGES` is not a signal.
_ANNOTATION_STATUS_KEYS: Tuple[str, ...] = (
    "stability",
    "status",
    "lifecycle",
    "stage",
    "maturity",
)

#: Status-word → stage vocabulary for :data:`_ANNOTATION_STATUS_KEYS` values. The only place
#: :data:`STAGE_STABLE` can originate — an explicit declaration, never an inference.
_STATUS_VALUE_STAGES: Mapping[str, str] = {
    "deprecated": STAGE_DEPRECATED,
    "obsolete": STAGE_DEPRECATED,
    "legacy": STAGE_DEPRECATED,
    "sunset": STAGE_DEPRECATED,
    "retired": STAGE_DEPRECATED,
    "experimental": STAGE_EXPERIMENTAL,
    "alpha": STAGE_EXPERIMENTAL,
    "preview": STAGE_EXPERIMENTAL,
    "unstable": STAGE_EXPERIMENTAL,
    "prototype": STAGE_EXPERIMENTAL,
    "beta": STAGE_BETA,
    "stable": STAGE_STABLE,
    "ga": STAGE_STABLE,
    "production": STAGE_STABLE,
}

#: Name/title tokens → stage. Matched against *whole tokens* only (``alphabet`` never reads
#: as ``beta``). Verb-like words (``preview``, ``sunset``) are deliberately excluded here:
#: a tool named ``preview_document`` previews documents — that is what it does, not what
#: lifecycle stage it is in.
_NAME_TOKEN_STAGES: Mapping[str, str] = {
    "deprecated": STAGE_DEPRECATED,
    "legacy": STAGE_DEPRECATED,
    "obsolete": STAGE_DEPRECATED,
    "experimental": STAGE_EXPERIMENTAL,
    "alpha": STAGE_EXPERIMENTAL,
    "unstable": STAGE_EXPERIMENTAL,
    "wip": STAGE_EXPERIMENTAL,
    "beta": STAGE_BETA,
}

#: Description phrase tables per stage, matched case-insensitively on word boundaries.
#: Longer / more specific phrases are listed first and matched spans are claimed greedily
#: within a stage, so "no longer supported" does not *also* report a shorter overlap.
#: Ambiguous bare words are deliberately absent: "preview" alone describes what many tools
#: *do*, "sunset" is a thing tools compute, "beta" alone is a statistics term — each needs
#: the surrounding context phrase (or a parenthesized marker) to count as a lifecycle signal.
_DESCRIPTION_PHRASES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (
        STAGE_DEPRECATED,
        (
            "scheduled for removal",
            "no longer supported",
            "no longer maintained",
            "will be removed",
            "superseded by",
            "end of life",
            "do not use",
            "deprecation",
            "deprecated",
            "obsolete",
        ),
    ),
    (
        STAGE_EXPERIMENTAL,
        (
            "technical preview",
            "tech preview",
            "work in progress",
            "not yet stable",
            "early access",
            "public preview",
            "private preview",
            "preview release",
            "in preview",
            "alpha release",
            "alpha version",
            "alpha quality",
            "alpha stage",
            "in alpha",
            "(alpha)",
            "[alpha]",
            "experimental",
            "unstable",
        ),
    ),
    (
        STAGE_BETA,
        (
            "public beta",
            "private beta",
            "closed beta",
            "open beta",
            "beta release",
            "beta version",
            "beta feature",
            "beta quality",
            "beta stage",
            "in beta",
            "(beta)",
            "[beta]",
        ),
    ),
)

# --- Compiled patterns (module-level: compiled once, reused per call) --------------------------


def _boundary_pattern(literal: str) -> "re.Pattern[str]":
    """Compile ``literal`` as a case-insensitive, boundary-anchored pattern.

    ``\\b`` misbehaves around literals that start/end with non-word characters
    (``(beta)``), so the guard is an explicit lookaround: not preceded/followed by a word
    character or hyphen — ``alphabet`` never matches ``beta``, but a sentence-ending
    "…is deprecated." still matches.

    Args:
        literal: The exact phrase to match.

    Returns:
        The compiled pattern.
    """
    guarded = r"(?<![\w-])" + re.escape(literal) + r"(?![\w-])"
    return re.compile(guarded, re.IGNORECASE)


_PHRASE_PATTERNS: Tuple[Tuple[str, str, "re.Pattern[str]"], ...] = tuple(
    (stage, phrase, _boundary_pattern(phrase))
    for stage, phrases in _DESCRIPTION_PHRASES
    for phrase in phrases
)

#: Tokenizer for names/titles: splits ``searchBeta`` / ``search_beta`` / ``search-beta`` /
#: ``v2beta`` alike into lower-cased word/number runs.
_TOKEN_PATTERN = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


# --- Result model -------------------------------------------------------------------------------


@dataclass(frozen=True)
class LifecycleSignal:
    """One lifecycle signal found on a capability.

    ``id`` is a stable hash of ``capability|source|kind|matched`` (prefixed
    ``mcp-lifecycle-``); equal inputs always yield the same id, so signals can be
    de-duplicated and referenced across runs (mirrors
    :class:`app.mcp_license_signals.LicenseSignal`).

    Attributes:
        stage: The ``STAGE_*`` constant this signal asserts.
        kind: One of the ``KIND_*`` constants (what the match *is*).
        source: One of the ``SOURCE_*`` constants (where the match was found).
        matched: The matched annotation (``key=value``), token, or phrase, verbatim.
        excerpt: A short, whitespace-collapsed context window around a description match
            (the full name/title for token matches; empty for annotation matches).
        id: Stable identifier (supplied by the detector, which scopes it to the capability).
    """

    stage: str
    kind: str
    source: str
    matched: str
    excerpt: str
    id: str

    def as_dict(self) -> Dict[str, str]:
        """Return a JSON-ready dict of this signal (stable key set)."""
        return {
            "id": self.id,
            "stage": self.stage,
            "kind": self.kind,
            "source": self.source,
            "matched": self.matched,
            "excerpt": self.excerpt,
        }


@dataclass(frozen=True)
class CapabilityLifecycle:
    """One capability's lifecycle assessment (what a capability-list badge renders).

    Attributes:
        item_type: The capability kind (``tool`` / ``resource`` / ``resource_template`` /
            ``prompt``).
        name: The capability's programmatic name.
        stage: The rolled-up stage — the most urgent stage among :attr:`signals`, or
            :data:`STAGE_UNSPECIFIED` when there are none (which is *not* a stability claim).
        signals: The itemized signals, deterministically ordered (source order, then match
            order), bounded to :data:`MAX_SIGNALS_PER_CAPABILITY`.
        signals_truncated: How many further signals were found beyond the cap (0 normally);
            overflow is stated, never silently dropped. The roll-up ``stage`` is computed
            over *all* hits, so truncation never changes the badge.
    """

    item_type: str
    name: str
    stage: str
    signals: Tuple[LifecycleSignal, ...]
    signals_truncated: int

    def as_dict(self) -> Dict[str, Any]:
        """Return a JSON-ready dict of this assessment (what the item API serializes)."""
        return {
            "item_type": self.item_type,
            "name": self.name,
            "stage": self.stage,
            "signals": [signal.as_dict() for signal in self.signals],
            "signals_truncated": self.signals_truncated,
        }


@dataclass(frozen=True)
class LifecycleSignalsReport:
    """The aggregate lifecycle result for one snapshot's capability items.

    Attributes:
        status: ``"detected"`` when at least one capability carries a signal, otherwise
            ``"none_detected"`` — never a "stable" verdict.
        statement: One human-readable sentence summarizing the result, pre-worded so every
            consumer (report card, UI, export) states absence the same careful way.
        stage_counts: Capability count per non-``unspecified`` stage (every key always
            present, zero when none) — computed over **all** capabilities, unaffected by
            itemization caps.
        flagged: The per-capability assessments that carry at least one signal, in snapshot
            item order, bounded to :data:`MAX_FLAGGED_CAPABILITIES`.
        flagged_truncated: How many further flagged capabilities exist beyond the cap.
        capabilities_scanned: How many capability items were assessed in total — so an
            empty result over an empty surface reads as "nothing to scan".
    """

    status: str
    statement: str
    stage_counts: Dict[str, int]
    flagged: Tuple[CapabilityLifecycle, ...]
    flagged_truncated: int
    capabilities_scanned: int

    def as_dict(self) -> Dict[str, Any]:
        """Return a JSON-ready dict of the report (what the report card consumes)."""
        return {
            "status": self.status,
            "statement": self.statement,
            "stage_counts": dict(self.stage_counts),
            "flagged": [capability.as_dict() for capability in self.flagged],
            "flagged_truncated": self.flagged_truncated,
            "capabilities_scanned": self.capabilities_scanned,
        }


#: Aggregate report statuses.
STATUS_DETECTED = "detected"

#: No capability carried a signal. Deliberately not "stable" — the detector reports the
#: absence of statements, never a stability verdict (AC: no signal ≠ "stable" claim).
STATUS_NONE_DETECTED = "none_detected"


# --- Detection ----------------------------------------------------------------------------------


def assess_capability_lifecycle(
    *,
    item_type: str,
    name: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    annotations: Optional[Mapping[str, Any]] = None,
) -> CapabilityLifecycle:
    """Assess one capability's lifecycle signals from its own advertised fields.

    Pure and deterministic: no I/O, and the same inputs always produce the same assessment
    (same signals, same order, same ids). Sources are scanned in a fixed order —
    annotations, then name, then title, then description — and the rolled-up
    :attr:`~CapabilityLifecycle.stage` is the most urgent stage any signal asserts.

    Args:
        item_type: The capability kind (``tool`` / ``resource`` / ``resource_template`` /
            ``prompt``) — part of the stable signal-id scope.
        name: The capability's programmatic name (tokenized for stage tokens).
        title: The optional human-facing title (tokenized like the name).
        description: The optional free-text description (scanned for stage phrases).
        annotations: The capability's annotations object, if any (scanned for stage flags
            and status values; non-mapping values are ignored).

    Returns:
        The :class:`CapabilityLifecycle`; ``stage`` is :data:`STAGE_UNSPECIFIED` when no
        signal is found — explicitly *not* a claim that the capability is stable.
    """
    scope = f"{item_type}:{name}"
    signals: List[LifecycleSignal] = []

    signals.extend(_scan_annotations(annotations, scope))
    signals.extend(_scan_tokens(name, SOURCE_NAME, scope))
    if title:
        signals.extend(_scan_tokens(title, SOURCE_TITLE, scope))
    if description:
        signals.extend(_scan_description(str(description)[:MAX_SCANNED_CHARS], scope))

    stage = _roll_up_stage(signals)
    shown = tuple(signals[:MAX_SIGNALS_PER_CAPABILITY])
    return CapabilityLifecycle(
        item_type=item_type,
        name=name,
        stage=stage,
        signals=shown,
        signals_truncated=max(0, len(signals) - len(shown)),
    )


def detect_lifecycle_signals(
    items: Sequence[Mapping[str, Any]],
) -> LifecycleSignalsReport:
    """Assess every capability item of a snapshot and aggregate the result.

    Pure and deterministic. Accepts the item shape both ``mcp_capability_items`` rows and
    :meth:`app.mcp_client.normalize.CapabilityItem.to_row` dicts share (``item_type`` /
    ``name`` / ``title`` / ``description`` / ``annotations``); unknown extra keys are
    ignored. Capabilities are assessed in the given order, so the flagged itemization is
    stable for a stored snapshot.

    Args:
        items: The snapshot's capability items, in their stored (kind, ordinal) order.

    Returns:
        The :class:`LifecycleSignalsReport`; ``status`` is :data:`STATUS_NONE_DETECTED`
        (with a carefully worded statement that is *not* a stability claim) when no
        capability carries a signal or there is nothing to scan.
    """
    assessments: List[CapabilityLifecycle] = []
    for item in items:
        annotations = item.get("annotations")
        assessments.append(
            assess_capability_lifecycle(
                item_type=str(item.get("item_type") or ""),
                name=str(item.get("name") or ""),
                title=_optional_str(item.get("title")),
                description=_optional_str(item.get("description")),
                annotations=annotations if isinstance(annotations, Mapping) else None,
            )
        )

    flagged = [a for a in assessments if a.stage != STAGE_UNSPECIFIED]
    stage_counts = {stage: 0 for stage in _STAGE_PRECEDENCE}
    for assessment in flagged:
        stage_counts[assessment.stage] += 1

    shown = tuple(flagged[:MAX_FLAGGED_CAPABILITIES])
    status = STATUS_DETECTED if flagged else STATUS_NONE_DETECTED
    return LifecycleSignalsReport(
        status=status,
        statement=_statement(status, stage_counts, len(flagged), len(assessments)),
        stage_counts=stage_counts,
        flagged=shown,
        flagged_truncated=max(0, len(flagged) - len(shown)),
        capabilities_scanned=len(assessments),
    )


def _statement(
    status: str,
    stage_counts: Mapping[str, int],
    flagged_count: int,
    scanned_count: int,
) -> str:
    """Word the one-line summary; absence is "no signals", never a "stable" verdict."""
    if status == STATUS_DETECTED:
        parts = ", ".join(
            f"{stage_counts[stage]} {stage}"
            for stage in _STAGE_PRECEDENCE
            if stage_counts[stage]
        )
        noun = "capability carries" if flagged_count == 1 else "capabilities carry"
        return (
            f"{flagged_count} of {scanned_count} {noun} lifecycle signals ({parts}) — "
            "drawn from the server's own descriptions, names, and annotations; "
            "informational, not a verified lifecycle fact."
        )
    if scanned_count == 0:
        return (
            "No capabilities to scan for lifecycle signals. "
            "This is not a claim that anything is stable."
        )
    noun = "capability" if scanned_count == 1 else "capabilities"
    return (
        f"No lifecycle signals detected across {scanned_count} scanned {noun}. "
        "This is not a claim that these capabilities are stable — a server that says "
        "nothing has made no stability statement."
    )


def _roll_up_stage(signals: Sequence[LifecycleSignal]) -> str:
    """Return the most urgent stage among ``signals`` (unspecified when there are none)."""
    present = {signal.stage for signal in signals}
    for stage in _STAGE_PRECEDENCE:
        if stage in present:
            return stage
    return STAGE_UNSPECIFIED


def _scan_annotations(
    annotations: Optional[Mapping[str, Any]], scope: str
) -> List[LifecycleSignal]:
    """Scan an annotations object for stage flags and status values.

    Keys are compared case-insensitively and reported in the object's own order (JSON
    objects preserve insertion order through the stack, so output is stable for a stored
    snapshot). A flag key counts only when strictly ``True``; a status key counts only when
    its string value is in the stage vocabulary — anything else is not a signal.
    """
    if not isinstance(annotations, Mapping):
        return []
    signals: List[LifecycleSignal] = []
    for key, value in annotations.items():
        lowered = str(key).lower()
        flag_stage = _ANNOTATION_FLAG_STAGES.get(lowered)
        if flag_stage is not None and value is True:
            signals.append(
                _signal(scope, flag_stage, KIND_ANNOTATION_FLAG, SOURCE_ANNOTATIONS,
                        f"{key}=true", "")
            )
            continue
        if lowered in _ANNOTATION_STATUS_KEYS and isinstance(value, str):
            status_stage = _STATUS_VALUE_STAGES.get(value.strip().lower())
            if status_stage is not None:
                signals.append(
                    _signal(scope, status_stage, KIND_ANNOTATION_STATUS,
                            SOURCE_ANNOTATIONS, f"{key}={value.strip()}", "")
                )
    return signals


def _scan_tokens(text: str, source: str, scope: str) -> List[LifecycleSignal]:
    """Scan a name/title for stage tokens (whole tokens only; each stage reported once).

    ``search_beta``, ``searchBeta``, ``v2beta``, and ``Search (beta)`` all yield the
    ``beta`` token; ``alphabet`` yields no token. One signal per distinct matched token.
    """
    signals: List[LifecycleSignal] = []
    seen: set = set()
    for token in _TOKEN_PATTERN.findall(text or ""):
        lowered = token.lower()
        stage = _NAME_TOKEN_STAGES.get(lowered)
        if stage is None or lowered in seen:
            continue
        seen.add(lowered)
        signals.append(_signal(scope, stage, KIND_NAME_TOKEN, source, lowered, text))
    return signals


def _scan_description(text: str, scope: str) -> List[LifecycleSignal]:
    """Scan a description for stage phrases, in deterministic position order.

    Phrases are tried in table order (longest / most specific first per stage) and a
    claimed span blocks shorter overlaps within the same stage, so "no longer supported"
    is not *also* a bare-"deprecated" hit. Each phrase reports its first occurrence only.
    Matches are ordered by position in the text, then stage, then phrase, so output is
    stable for a fixed input.
    """
    hits: List[Tuple[int, str, str, str]] = []  # (position, stage, phrase, excerpt)
    claimed: Dict[str, List[Tuple[int, int]]] = {}
    for stage, phrase, pattern in _PHRASE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        spans = claimed.setdefault(stage, [])
        if any(match.start() < end and match.end() > start for start, end in spans):
            continue
        spans.append((match.start(), match.end()))
        hits.append((match.start(), stage, phrase, _excerpt(text, match)))

    hits.sort(key=lambda hit: (hit[0], hit[1], hit[2]))
    return [
        _signal(scope, stage, KIND_DESCRIPTION_PHRASE, SOURCE_DESCRIPTION, phrase, excerpt)
        for _, stage, phrase, excerpt in hits
    ]


def _signal(
    scope: str, stage: str, kind: str, source: str, matched: str, excerpt: str
) -> LifecycleSignal:
    """Build a signal with its stable, capability-scoped id."""
    digest = hashlib.sha256(
        f"{scope}|{source}|{kind}|{matched}".encode("utf-8")
    ).hexdigest()[:16]
    return LifecycleSignal(
        stage=stage,
        kind=kind,
        source=source,
        matched=matched,
        excerpt=_collapse(excerpt),
        id=f"mcp-lifecycle-{digest}",
    )


def _excerpt(text: str, match: "re.Match[str]") -> str:
    """Return a whitespace-collapsed context window around a description ``match``.

    The window extends :data:`_EXCERPT_RADIUS` characters either side of the match and is
    marked with leading/trailing ellipses when it is a strict substring, so a reader can
    tell a fragment from the whole text.
    """
    start = max(0, match.start() - _EXCERPT_RADIUS)
    end = min(len(text), match.end() + _EXCERPT_RADIUS)
    window = " ".join(text[start:end].split())
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{window}{suffix}"


def _collapse(text: str) -> str:
    """Collapse whitespace in a short excerpt (name/title excerpts pass through here)."""
    return " ".join(str(text).split())


def _optional_str(value: Any) -> Optional[str]:
    """Return ``value`` as a stripped-empty-to-None optional string."""
    if value is None:
        return None
    text = str(value)
    return text if text.strip() else None
