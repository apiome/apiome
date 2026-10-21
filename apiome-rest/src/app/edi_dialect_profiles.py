"""EDI dialect profiles — FMT-6.5 (#5449).

UK retail runs TRADACOMS, German and European automotive runs ODETTE/VDA, and GS1 retail runs
EANCOM. None of them is a wholly separate syntax: EANCOM and ODETTE/VDA are *subsets* of UN/EDIFACT
(the same ``UNB`` … ``UNZ`` interchange, restricted to a message set and bound to their own code
lists), and TRADACOMS writes EDIFACT's segments, elements and service characters inside an envelope
of its own (``STX`` … ``END``). So each is a **profile** on the EDIFACT engine, not a new parser:

* :data:`EANCOM` and :data:`ODETTE` are recognised on a parsed EDIFACT interchange by
  :func:`detect_edifact_profile`; an interchange that carries neither's evidence is plain
  :data:`UN_EDIFACT`.
* :data:`TRADACOMS` is the profile :mod:`app.tradacoms_parser` applies — it reads its segments with
  the EDIFACT lexical layer and builds its own transmission / file / message structure.

What a profile is, and what it is not
-------------------------------------
A profile names the dialect, the evidence it was recognised by, the message set it covers and the
code lists it binds — and records all of that in the import's provenance, the canonical model's
``format_profile`` extras and the payload analysis. It is **not** an implementation guide: segment
usage (mandatory / conditional / not used), code-list restrictions and the dialect's own business
rules are never evaluated, exactly as the X12 and EDIFACT analyses never evaluate a guide. Each
profile's :attr:`DialectProfile.boundaries` says so in reviewed sentences, and the capability panel
carries them.

Recognition is evidence-based and conservative: a profile is applied only on a marker the dialect
itself defines (an EANCOM association code, an ODETTE subset designator) or on two independent
signals together (an ODETTE organisation code *and* a message from the ODETTE/VDA set). A weak
resemblance is never enough, so a plain UN/EDIFACT interchange is never mislabelled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Sequence, Tuple

if TYPE_CHECKING:  # pragma: no cover - typing only; the parser never imports this module
    from .edifact_parser import EdifactDocument

__all__ = [
    "DIALECT_PROFILES",
    "DialectProfile",
    "EANCOM",
    "ODETTE",
    "PROFILE_EXTRAS_KEY",
    "ProfileMatch",
    "TRADACOMS",
    "UN_EDIFACT",
    "detect_edifact_profile",
    "dialect_profile",
    "edifact_profile",
    "messages_outside_set",
    "profile_statement",
]

#: The canonical-model extras key every EDI dialect records its profile under. The import pipeline
#: lifts it into the revision's provenance (``format_metadata.formatProfile``).
PROFILE_EXTRAS_KEY = "format_profile"


@dataclass(frozen=True)
class DialectProfile:
    """One EDI dialect: what it is, how it is recognised and where its modelling stops.

    Attributes:
        key: Stable profile key (``eancom``, ``odette``, ``tradacoms``, ``un-edifact``).
        label: Display name (``EANCOM``, ``ODETTE/VDA``).
        engine: The adapter whose parser reads it (``edifact`` or ``tradacoms``).
        governing_body: Who maintains the dialect.
        message_set: The messages the profile covers. Membership is recorded per message, never
            enforced — a message outside the set is read like any other.
        code_lists: The code lists the dialect binds, named so a reader knows they exist; no value
            is looked up in them.
        recognition: One sentence on how the profile is recognised.
        boundaries: Reviewed sentences on what the profile does not do.
    """

    key: str
    label: str
    engine: str
    governing_body: str
    message_set: Tuple[str, ...]
    code_lists: Tuple[str, ...]
    recognition: str
    boundaries: Tuple[str, ...]

    def covers(self, message_type: str) -> bool:
        """Whether ``message_type`` is in the profile's message set.

        Args:
            message_type: A message type as the source wrote it (``ORDERS``, ``DELFOR``).

        Returns:
            True when the profile names the message; always False for a profile with no set.
        """
        return message_type.strip().upper() in self.message_set


#: Plain UN/EDIFACT — the profile an interchange gets when no dialect's evidence is present.
UN_EDIFACT = DialectProfile(
    key="un-edifact",
    label="UN/EDIFACT",
    engine="edifact",
    governing_body="UN/CEFACT",
    message_set=(),
    code_lists=("UN/EDIFACT directory code lists (UNCL)",),
    recognition=(
        "Applied when an EDIFACT interchange carries no EANCOM or ODETTE/VDA evidence: the "
        "directory each message names (D:96A, D:01B, …) is recorded as the sender's claim."
    ),
    boundaries=(
        "No directory is consulted: segment groups are flat segments and code values are recorded "
        "as written.",
    ),
)

#: GS1's EDIFACT subset for retail and consumer goods.
EANCOM = DialectProfile(
    key="eancom",
    label="EANCOM",
    engine="edifact",
    governing_body="GS1",
    message_set=(
        "APERAK",
        "CONTRL",
        "DELFOR",
        "DESADV",
        "IFTMIN",
        "INVOIC",
        "INVRPT",
        "ORDCHG",
        "ORDERS",
        "ORDRSP",
        "PARTIN",
        "PRICAT",
        "RECADV",
        "REMADV",
        "SLSRPT",
    ),
    code_lists=(
        "EANCOM code lists (GS1 restrictions of the UNCL code lists)",
        "GS1 identification keys (GLN for parties, GTIN for items)",
    ),
    recognition=(
        "Recognised by an EANCOM association assigned code (`EAN` + three digits, e.g. EAN008) in "
        "a `UNH` message identifier or a `UNG` message version."
    ),
    boundaries=(
        "The EANCOM message implementation guide is not consulted: segment status (mandatory, "
        "required, dependent, not used) and EANCOM's restricted code lists are not evaluated, and "
        "the association code is recorded as the sender's claim.",
        "GS1 identifiers (GLN, GTIN) are recorded as written; check digits and allocation are not "
        "verified.",
    ),
)

#: ODETTE International's and the German VDA's EDIFACT subsets for the automotive supply chain.
ODETTE = DialectProfile(
    key="odette",
    label="ODETTE/VDA",
    engine="edifact",
    governing_body="ODETTE International / VDA",
    message_set=(
        "APERAK",
        "CONTRL",
        "DELFOR",
        "DELJIT",
        "DESADV",
        "GLOBAL",
        "IFTMIN",
        "INVOIC",
        "INVRPT",
        "ORDERS",
        "ORDRSP",
        "RECADV",
        "REMADV",
        "SEQJIT",
    ),
    code_lists=(
        "ODETTE / VDA code lists (restrictions of the UNCL code lists)",
        "ODETTE organisation identification codes",
    ),
    recognition=(
        "Recognised by an ODETTE or VDA subset designator in a message's association assigned code, "
        "or by an interchange party identified with an ODETTE organisation code (`O` + digits) "
        "together with a message from the ODETTE/VDA message set."
    ),
    boundaries=(
        "The ODETTE and VDA implementation guidelines are not consulted: schedule semantics, "
        "segment status and the restricted code lists are not evaluated.",
        "VDA's own fixed-length record formats (VDA 4905, 4913 …) are a different syntax and are not "
        "read by this profile; only their EDIFACT subsets are.",
    ),
)

#: The UK retail standard: EDIFACT-style segments in an ``STX`` … ``END`` transmission.
TRADACOMS = DialectProfile(
    key="tradacoms",
    label="TRADACOMS",
    engine="tradacoms",
    governing_body="GS1 UK (formerly ANA)",
    message_set=(
        "ACKHDR",
        "ACKMNT",
        "ACKTLR",
        "CREHDR",
        "CREDIT",
        "CRETLR",
        "DELHDR",
        "DELIVR",
        "DELTLR",
        "INVFIL",
        "INVOIC",
        "INVTLR",
        "ORDERS",
        "ORDHDR",
        "ORDTLR",
        "VATTLR",
    ),
    code_lists=("TRADACOMS code values (GS1 UK)",),
    recognition=(
        "Recognised by an `STX=` transmission header — never `UNB` — and read as its own structure: "
        "transmission → file (header, detail and trailer messages) → `MHD` … `MTR` message."
    ),
    boundaries=(
        "The TRADACOMS manual's message specifications are not consulted: which segments a "
        "message may carry, their order and their code values are recorded as written, not "
        "checked.",
        "Files are delimited by their header message (the one carrying `TYP`); the file's "
        "transaction code is recorded as the sender's claim.",
    ),
)

#: Every profile, by key.
DIALECT_PROFILES: Dict[str, DialectProfile] = {
    profile.key: profile for profile in (UN_EDIFACT, EANCOM, ODETTE, TRADACOMS)
}

#: EANCOM's association assigned code: ``EAN`` and a three-digit subset version (``EAN008``).
_EANCOM_ASSOCIATION = re.compile(r"^EAN\d{3}$")
#: An ODETTE or VDA subset designator in an association assigned code.
_ODETTE_ASSOCIATION = re.compile(r"^(?:OD|ODETTE|VDA)[0-9A-Z]*$")
#: An ODETTE organisation identification code: ``O`` then at least four digits.
_ODETTE_PARTY = re.compile(r"^O\d{4}[0-9A-Z]*$")


@dataclass(frozen=True)
class ProfileMatch:
    """The profile applied to one document, and the evidence it was applied on.

    Attributes:
        profile: The profile.
        evidence: Each fact that led to it, as a sentence free of payload values. Empty for plain
            UN/EDIFACT, which is applied for want of evidence.
    """

    profile: DialectProfile
    evidence: Tuple[str, ...] = ()

    def extras(self) -> Dict[str, object]:
        """The ``format_profile`` extras / provenance entry for this match.

        Returns:
            A JSON-ready mapping: key, label, engine, evidence, and the explicit statement that no
            implementation guide was consulted.
        """
        return {
            "key": self.profile.key,
            "label": self.profile.label,
            "engine": self.profile.engine,
            "evidence": list(self.evidence),
            "implementation_guide_consulted": False,
        }


def profile_statement(profile: DialectProfile) -> str:
    """The reviewed capability-panel note for one profile: what it is, how it is recognised, where
    its modelling stops.

    Args:
        profile: The profile.

    Returns:
        One paragraph naming the profile, its governing body, its recognition rule and its
        boundaries.
    """
    return " ".join(
        [f"{profile.label} profile ({profile.governing_body}).", profile.recognition, *profile.boundaries]
    )


def dialect_profile(key: str) -> Optional[DialectProfile]:
    """Return the profile registered under ``key``, or ``None``."""
    return DIALECT_PROFILES.get(key)


def _first(values: Iterable[str], pattern: re.Pattern) -> Optional[str]:
    """Return the first stripped value that matches ``pattern``."""
    for value in values:
        text = (value or "").strip()
        if text and pattern.match(text):
            return text
    return None


def detect_edifact_profile(
    *,
    association_codes: Sequence[str],
    party_ids: Sequence[str],
    message_types: Sequence[str],
) -> ProfileMatch:
    """Decide which dialect profile an EDIFACT interchange is written in.

    Takes facts rather than a document so the rule can be tested, and stated, on its own;
    :func:`edifact_profile` gathers the facts from a parsed interchange.

    Precedence: an EANCOM association code, then an ODETTE/VDA association code, then the ODETTE
    two-signal rule (an ODETTE organisation code on the interchange *and* every message in the
    ODETTE/VDA set), else plain UN/EDIFACT.

    Args:
        association_codes: Association assigned codes from ``UNH`` S009 and ``UNG`` S008, in order.
        party_ids: Interchange (``UNB``) and group (``UNG``) sender and recipient identifications.
        message_types: Every message type the interchange carries.

    Returns:
        The match, with its evidence.
    """
    eancom = _first(association_codes, _EANCOM_ASSOCIATION)
    if eancom is not None:
        return ProfileMatch(
            EANCOM, (f"Association assigned code {eancom} names an EANCOM subset version.",)
        )
    odette = _first(association_codes, _ODETTE_ASSOCIATION)
    if odette is not None:
        return ProfileMatch(
            ODETTE, (f"Association assigned code {odette} names an ODETTE/VDA subset.",)
        )
    types = [message_type.strip().upper() for message_type in message_types if message_type.strip()]
    if (
        types
        and _first(party_ids, _ODETTE_PARTY) is not None
        and all(ODETTE.covers(message_type) for message_type in types)
    ):
        listed = ", ".join(sorted(set(types)))
        return ProfileMatch(
            ODETTE,
            (
                "An interchange party is identified with an ODETTE organisation code "
                "(`O` + digits).",
                f"Every message ({listed}) is in the ODETTE/VDA message set.",
            ),
        )
    return ProfileMatch(UN_EDIFACT)


def edifact_profile(document: "EdifactDocument") -> ProfileMatch:
    """Decide the dialect profile of a parsed EDIFACT interchange.

    Args:
        document: The parsed interchange (:func:`app.edifact_parser.parse_edifact`).

    Returns:
        The :class:`ProfileMatch` :func:`detect_edifact_profile` gives for its facts.
    """
    interchange = document.interchange
    messages = list(interchange.all_messages())
    association_codes = [message.association for message in messages]
    party_ids = [interchange.sender_id, interchange.recipient_id]
    for group in interchange.functional_groups:
        association_codes.append(group.header.component(7, 3))
        party_ids.extend([group.sender, group.recipient])
    return detect_edifact_profile(
        association_codes=association_codes,
        party_ids=party_ids,
        message_types=[message.message_type for message in messages],
    )


def messages_outside_set(profile: DialectProfile, message_types: Iterable[str]) -> List[str]:
    """Return the message types outside ``profile``'s set, in first-seen order.

    Args:
        profile: The applied profile.
        message_types: The message types observed.

    Returns:
        The types the profile does not name; empty for a profile with no message set.
    """
    if not profile.message_set:
        return []
    outside: List[str] = []
    for message_type in message_types:
        if not profile.covers(message_type) and message_type not in outside:
            outside.append(message_type)
    return outside
