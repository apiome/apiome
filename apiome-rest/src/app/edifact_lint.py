"""UN/EDIFACT lint pack — MFI-20.5 (#3989).

Native, deterministic quality rules for UN/EDIFACT interchanges (EANCOM and ODETTE/VDA included —
they are EDIFACT profiles), layered on the canonical lint engine (MFI-4.1 :mod:`app.lint_engine`).
The :class:`EdifactRulePack` is registered under the ``edifact`` format key, so it runs with the
always-on common pack on every EDIFACT artifact. The rules read only the canonical model — the
envelope controls :class:`~app.edifact_normalizer.EdifactNormalizer` records under
``extras["edifact_controls"]`` (:func:`app.edi_envelope_controls.edifact_controls`):

* **edifact.control-references-match** (error) — a trailer does not repeat its header's control
  reference (``UNT`` 0062 ≠ ``UNH`` 0062, ``UNE`` 0048 ≠ ``UNG`` 0048, ``UNZ`` 0020 ≠ ``UNB`` 0020):
  a receiver rejects the envelope.
* **edifact.control-counts-match** (error) — a trailer's control count is not what it closes
  (``UNT`` 0074 ≠ the segments from ``UNH`` to ``UNT``, ``UNE`` 0060 ≠ the group's messages,
  ``UNZ`` 0036 ≠ the interchange's groups or messages): a receiver rejects the envelope. The
  interchange still imports, with both figures recorded.
* **edifact.message-references-unique** (warning) — two messages of one group (or of an interchange
  without groups) share a message reference: a ``CONTRL`` cannot say which one it answers.
* **edifact.directory-declared** (warning) — a ``UNH`` names no message version and release
  (``D:96A``): nothing says which directory defines its segments.
* **edifact.test-interchange** (info) — ``UNB`` 0035 is ``1``: the interchange is test data.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, List, Mapping, Optional, Tuple

from .canonical_model import CanonicalApi
from .edi_envelope_controls import EDIFACT_CONTROLS_KEY
from .lint_engine import LintRule, RulePack

__all__ = ["EdifactRulePack"]

Finding = Tuple[str, str]


def _controls(api: CanonicalApi) -> Mapping[str, Any]:
    """The envelope controls the normalizer recorded, or an empty mapping."""
    controls = api.extras.get(EDIFACT_CONTROLS_KEY)
    return controls if isinstance(controls, Mapping) else {}


def _interchange(api: CanonicalApi) -> Mapping[str, Any]:
    interchange = _controls(api).get("interchange")
    return interchange if isinstance(interchange, Mapping) else {}


def _mappings(items: Any) -> List[Mapping[str, Any]]:
    return [item for item in items or [] if isinstance(item, Mapping)]


def _message_scopes(api: CanonicalApi) -> List[Tuple[str, List[Mapping[str, Any]]]]:
    """``(path prefix, messages)`` for each group, or for the interchange when it has no groups."""
    controls = _controls(api)
    scopes = [
        (f"UNG[{group.get('reference')}]/", _mappings(group.get("messages")))
        for group in _mappings(controls.get("groups"))
    ]
    return scopes or [("", _mappings(controls.get("messages")))]


def _message_path(prefix: str, message: Mapping[str, Any]) -> str:
    return f"{prefix}UNH[{message.get('reference')}]"


def _mismatch(
    path: str, trailer: str, header: str, declared: Optional[str], expected: Optional[str]
) -> Iterable[Finding]:
    """One finding when a trailer's reference was written and differs from its header's."""
    if declared is not None and declared != expected:
        yield (path, f"{trailer} is '{declared}' but {header} is '{expected}'; the trailer must repeat it.")


def _check_control_references_match(api: CanonicalApi) -> Iterable[Finding]:
    """Every trailer repeats its header's control reference."""
    interchange = _interchange(api)
    yield from _mismatch(
        "UNB", "UNZ 0020", "UNB 0020", interchange.get("trailer_reference"), interchange.get("control_reference")
    )
    for group in _mappings(_controls(api).get("groups")):
        yield from _mismatch(
            f"UNG[{group.get('reference')}]",
            "UNE 0048",
            "UNG 0048",
            group.get("trailer_reference"),
            group.get("reference"),
        )
    for prefix, messages in _message_scopes(api):
        for message in messages:
            yield from _mismatch(
                _message_path(prefix, message),
                "UNT 0062",
                "UNH 0062",
                message.get("trailer_reference"),
                message.get("reference"),
            )


def _count(path: str, trailer: str, declared: Any, observed: Any, what: str) -> Iterable[Finding]:
    """One finding when a declared control count was written and differs from the observed count."""
    if isinstance(declared, int) and declared != observed:
        yield (path, f"{trailer} declares {declared}, but {what} number {observed}.")


def _check_control_counts_match(api: CanonicalApi) -> Iterable[Finding]:
    """Every trailer's control count is the count of what it closes."""
    controls = _controls(api)
    interchange = _interchange(api)
    what = "the interchange's functional groups" if _mappings(controls.get("groups")) else "the interchange's messages"
    yield from _count("UNB", "UNZ 0036", interchange.get("declared_count"), interchange.get("count"), what)
    for group in _mappings(controls.get("groups")):
        yield from _count(
            f"UNG[{group.get('reference')}]",
            "UNE 0060",
            group.get("declared_message_count"),
            group.get("message_count"),
            "the group's messages",
        )
    for prefix, messages in _message_scopes(api):
        for message in messages:
            yield from _count(
                _message_path(prefix, message),
                "UNT 0074",
                message.get("declared_segment_count"),
                message.get("segment_count"),
                "the segments from UNH to UNT",
            )


def _check_message_references_unique(api: CanonicalApi) -> Iterable[Finding]:
    """No two messages of one group (or interchange) share a message reference."""
    for prefix, messages in _message_scopes(api):
        counts = Counter(message.get("reference") for message in messages if message.get("reference"))
        for reference in sorted(str(ref) for ref, count in counts.items() if count > 1):
            yield (
                prefix.rstrip("/") or "UNB",
                f"Two messages share the message reference '{reference}' (UNH 0062); a CONTRL "
                "cannot say which one it answers.",
            )


def _check_directory_declared(api: CanonicalApi) -> Iterable[Finding]:
    """Every ``UNH`` names the directory (message version and release) its segments follow."""
    for prefix, messages in _message_scopes(api):
        for message in messages:
            if not message.get("directory"):
                yield (
                    _message_path(prefix, message),
                    f"Message {message.get('message_type')} names no version and release in UNH 0052 / "
                    "0054; nothing says which directory (such as D:96A) defines its segments.",
                )


def _check_test_interchange(api: CanonicalApi) -> Iterable[Finding]:
    """``UNB`` 0035 = ``1`` marks the interchange as test data."""
    if (_interchange(api).get("test_indicator") or "").strip() == "1":
        yield (
            "UNB",
            "UNB 0035 (test indicator) is '1': this interchange is test data. A trading partner's "
            "production system rejects it.",
        )


class EdifactRulePack(RulePack, register=True):
    """Native rules for UN/EDIFACT artifacts (see the module docstring)."""

    format = "edifact"
    pack_id = "edifact"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="edifact.control-references-match",
            category="structure",
            severity="error",
            description="UNT, UNE and UNZ must repeat the control reference of UNH, UNG and UNB.",
            check=_check_control_references_match,
        ),
        LintRule(
            rule_id="edifact.control-counts-match",
            category="structure",
            severity="error",
            description="UNT, UNE and UNZ must count the segments, messages and groups they close.",
            check=_check_control_counts_match,
        ),
        LintRule(
            rule_id="edifact.message-references-unique",
            category="structure",
            severity="warning",
            description="Message references must be unique within a group or interchange.",
            check=_check_message_references_unique,
        ),
        LintRule(
            rule_id="edifact.directory-declared",
            category="structure",
            severity="warning",
            description="UNH must name the message version and release (the directory).",
            check=_check_directory_declared,
        ),
        LintRule(
            rule_id="edifact.test-interchange",
            category="structure",
            severity="info",
            description="UNB 0035 '1' marks the interchange as test data.",
            check=_check_test_interchange,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the UN/EDIFACT native rules in deterministic execution order."""
        return list(self._RULES)
