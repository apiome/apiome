"""TRADACOMS → canonical model normalizer — FMT-6.5 (#5449).

Maps a parsed :class:`~app.tradacoms_parser.TradacomsDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.DATA_SCHEMA`, the way the EDIFACT normalizer maps an
interchange — and with the same code, because a TRADACOMS message is EDIFACT-style segments
between its own ``MHD`` and ``MTR``:

* the canonical model describes **one** schema, so it is derived from the first transmission's
  first *detail* message — the first message that is not a file header (``ORDERS`` rather than
  ``ORDHDR``), or the first message when every one is a header. The payload analysis keeps the
  rest and says so (``tradacoms.canonical_projection_subset``);
* a segment that occurs once contributes its element values as fields (``ORD01``, ``CLO01-2``);
  a segment that repeats becomes its own record type, referenced as a list
  (:func:`app.edifact_normalizer.message_record_types`);
* the envelope (``STX``/``MHD``/``MTR``/``END``) and the file the message sits in are recorded in
  ``extras`` rather than as types, with the TRADACOMS dialect profile under ``format_profile``.
"""

from __future__ import annotations

from typing import Any, Tuple

from .canonical_model import ApiIdentity, ApiParadigm, CanonicalApi
from .edi_dialect_profiles import PROFILE_EXTRAS_KEY, TRADACOMS, ProfileMatch
from .edifact_normalizer import message_record_types, segment_template
from .normalizer import Normalizer, normalize_ordering
from .tradacoms_parser import TradacomsDocument, TradacomsFile, TradacomsMessage

__all__ = ["TRADACOMS_PROFILE_MATCH", "TradacomsNormalizer", "canonical_message"]

_FORMAT_KEY = "tradacoms"

#: The profile every TRADACOMS document is read with, and the one fact it is recognised by.
TRADACOMS_PROFILE_MATCH = ProfileMatch(
    TRADACOMS, ("An `STX=` transmission header opens the document; it is not an EDIFACT `UNB`.",)
)


def canonical_message(document: TradacomsDocument) -> Tuple[TradacomsFile, TradacomsMessage]:
    """Return the message the canonical model is derived from, with its file.

    Args:
        document: The parsed document.

    Returns:
        ``(file, message)`` — the first non-header message of the first transmission, or its first
        message when every message is a file header.
    """
    transmission = document.transmissions[0]
    for file in transmission.files:
        for message in file.messages:
            if not message.is_file_header:
                return file, message
    first_file = transmission.files[0]
    return first_file, first_file.messages[0]


class TradacomsNormalizer(Normalizer, register=True):
    """Normalize a parsed TRADACOMS transmission into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, TradacomsDocument):
            raise ValueError(
                "TRADACOMS source must be a TradacomsDocument "
                "(see app.tradacoms_parser.parse_tradacoms)"
            )

        transmission = source.transmissions[0]
        file, message = canonical_message(source)
        namespace = f"TRADACOMS-{message.message_type}"
        message_type, segment_types = message_record_types(
            message.message_type, message.segments, namespace=namespace
        )

        title = f"TRADACOMS {message.message_type}"
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=title, namespace=namespace),
            title=title,
            types=[message_type, *segment_types],
            raw={"tradacoms": source.raw} if include_raw else None,
            extras={
                PROFILE_EXTRAS_KEY: TRADACOMS_PROFILE_MATCH.extras(),
                "tradacoms_message_type": message.message_type,
                "tradacoms_transmission": {
                    "syntax_identifier": transmission.syntax_identifier,
                    "syntax_version": transmission.syntax_version,
                    "sender_code": transmission.sender_code,
                    "recipient_code": transmission.recipient_code,
                    "sender_reference": transmission.sender_reference,
                    "application_reference": transmission.application_reference or None,
                    "message_reference": message.reference,
                    "message_version": message.version,
                    "transmission_count": len(source.transmissions),
                },
                "tradacoms_file": {
                    "header_message_type": file.header_type or None,
                    "transaction_code": file.transaction_code or None,
                    "transaction_name": file.transaction_name or None,
                    "generation": file.generation or None,
                    "version": file.file_version or None,
                },
                "tradacoms_messages": [
                    {
                        "message_type": item.message_type,
                        "reference": item.reference,
                        "version": item.version,
                        "file_header": item.is_file_header,
                        "segments": [segment_template(segment) for segment in item.segments],
                    }
                    for item in file.messages
                ],
            },
        )
        return normalize_ordering(api)
