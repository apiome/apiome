"""Reasoned exemptions from the corpus parity gate — FMT-1.4 (#5415).

The parity gate (:mod:`tests.corpus_parity`) requires every shipped, non-preview import adapter to
carry corpus examples, negatives, golden snapshots, a round-trip matrix row, and a capability
registry entry. A format that genuinely cannot meet one of those is recorded **here, by name and
with a reason** — the ticket's "closed or recorded as explicit, reasoned xfails rather than
silence".

Both maps are **strict**, in the same sense as :data:`tests.roundtrip_xfails.KNOWN_ROUNDTRIP_XFAILS`:
:mod:`tests.test_corpus_parity` fails when a listed exemption is no longer needed, so closing a gap
forces the entry to be deleted rather than leaving a permanently-excused format behind.

Adding an entry here is a review decision, not a way to land a format faster. The reason must say
*why the artifact cannot exist*, not that it has not been written yet — "no fixtures authored"
means the adapter is not finished, and the gate is supposed to say so.
"""

from __future__ import annotations

from typing import Dict, Tuple

__all__ = ["KNOWN_EXPORT_ONLY_DESTINATIONS", "KNOWN_PARITY_WAIVERS"]

#: ``(import_source_key, ParityRequirement value) -> reason``.
#:
#: Empty: as of FMT-1.4 every registered adapter carries all four artifacts. The last gap was
#: ``asyncapi``, which had intake examples but no golden corpus because its parser was an optional
#: bundled tool; FMT-1.3 (#5414) made the parser a hard dependency and the goldens landed with it.
KNOWN_PARITY_WAIVERS: Dict[Tuple[str, str], str] = {}

#: ``emitter import-source key -> reason`` for a shipped emitter with no import adapter behind it.
#:
#: Such a destination can never be covered by the *import* corpus, so it is exempt from parity —
#: but only once somebody has said so.
KNOWN_EXPORT_ONLY_DESTINATIONS: Dict[str, str] = {
    "iceberg": "MFX-36.3 (#4319): an Iceberg schema lives in a table's metadata in a catalog, not in a document "
    "anyone uploads; Apiome writes it for a lake table and reads it back with nothing. pyiceberg parses every "
    "export in the gate instead.",
    "x12-guide": "MFX-24.1 (#4145): an X12 implementation guide (JSON guide, segment CSV, Markdown) documents a "
    "transaction set for trading partners; it is not an interchange, and the X12 adapter (`edix12`) reads "
    "interchanges. The emitted guide is checked by `x12_guide_validation` in the gate instead.",
    "edifact-guide": "MFX-24.2 (#4146): an EDIFACT message implementation guide (JSON guide, segment CSV, Markdown) "
    "documents a message for trading partners; it is not an interchange, and the EDIFACT adapter (`edifact`) "
    "reads interchanges. The emitted guide is checked by `edifact_guide_validation` in the gate instead.",
    "hl7v2-guide": "MFX-26.3 (#4159): an HL7 v2 segment-definition guide (JSON guide, segment CSV, Markdown) "
    "documents messages and segments; it is not a message, and the HL7 v2 adapter (`hl7v2`) reads messages. "
    "The emitted guide is checked by `hl7v2_guide_validation` in the gate instead.",
}
