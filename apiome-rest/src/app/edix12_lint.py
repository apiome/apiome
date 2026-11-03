"""EDI X12 lint pack — MFI-20.5 (#3989).

Native, deterministic quality rules for ANSI ASC X12 interchanges, layered on the canonical lint
engine (MFI-4.1 :mod:`app.lint_engine`) the way the HL7 v2 pack (:mod:`app.hl7v2_lint`) is. The
:class:`EdiX12RulePack` is registered under the ``edix12`` format key, so it runs with the always-on
common pack on every X12 artifact. The rules read only the canonical model — the envelope controls
:class:`~app.edix12_normalizer.EdiX12Normalizer` records under ``extras["x12_controls"]``
(:func:`app.edi_envelope_controls.x12_controls`) — never the raw interchange:

* **edix12.control-numbers-match** (error) — a trailer does not repeat its header's control number
  (``SE02`` ≠ ``ST02``, ``GE02`` ≠ ``GS06``, ``IEA02`` ≠ ``ISA13``): a receiver rejects the envelope.
* **edix12.control-totals-match** (error) — a trailer's control total is not what it closes
  (``SE01`` ≠ the segments from ``ST`` to ``SE``, ``GE01`` ≠ the group's transaction sets,
  ``IEA01`` ≠ the interchange's functional groups): a receiver rejects the envelope.
* **edix12.control-numbers-unique** (warning) — two transaction sets in one group, or two groups in
  one interchange, share a control number: an acknowledgement cannot say which one it answers.
* **edix12.functional-id-matches-set** (warning) — the group's functional identifier (``GS01``) is
  not the one X12 assigns the transaction set (``PO`` for an ``850``): receivers route groups by it.
* **edix12.version-declared** (warning) — ``GS08`` is empty: nothing says which release of the
  transaction set's definition the segments follow.
* **edix12.usage-indicator-valid** (warning) — ``ISA15`` is not ``P``, ``T`` or ``I``.
* **edix12.test-interchange** (info) — ``ISA15`` is ``T``: the interchange is test data.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, List, Mapping, Optional, Tuple

from .canonical_model import CanonicalApi
from .edi_envelope_controls import X12_CONTROLS_KEY
from .lint_engine import LintRule, RulePack

__all__ = ["EdiX12RulePack", "FUNCTIONAL_ID_FOR_SET", "USAGE_INDICATORS"]

#: The ``ISA15`` usage indicators X12 defines: production, test and information.
USAGE_INDICATORS: Mapping[str, str] = {"P": "production", "T": "test", "I": "information"}

#: The functional identifier code (``GS01``) X12 assigns each common transaction set (``ST01``).
#: Sets missing from the table are not checked.
FUNCTIONAL_ID_FOR_SET: Mapping[str, str] = {
    "180": "AN",
    "204": "SM",
    "214": "QM",
    "270": "HS",
    "271": "HB",
    "276": "HR",
    "277": "HN",
    "278": "HI",
    "810": "IN",
    "812": "CD",
    "820": "RA",
    "824": "AG",
    "830": "PS",
    "832": "SC",
    "834": "BE",
    "835": "HP",
    "837": "HC",
    "846": "IB",
    "850": "PO",
    "852": "PD",
    "855": "PR",
    "856": "SH",
    "860": "PC",
    "862": "SS",
    "864": "TX",
    "940": "OW",
    "945": "SW",
    "990": "GF",
    "997": "FA",
    "999": "FA",
}

Finding = Tuple[str, str]


def _controls(api: CanonicalApi) -> Mapping[str, Any]:
    """The envelope controls the normalizer recorded, or an empty mapping."""
    controls = api.extras.get(X12_CONTROLS_KEY)
    return controls if isinstance(controls, Mapping) else {}


def _interchange(api: CanonicalApi) -> Mapping[str, Any]:
    interchange = _controls(api).get("interchange")
    return interchange if isinstance(interchange, Mapping) else {}


def _groups(api: CanonicalApi) -> List[Mapping[str, Any]]:
    groups = _controls(api).get("groups")
    return [group for group in groups or [] if isinstance(group, Mapping)]


def _transactions(group: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    return [item for item in group.get("transactions") or [] if isinstance(item, Mapping)]


def _set_path(group: Mapping[str, Any], transaction: Mapping[str, Any]) -> str:
    """The finding path of one transaction set: ``GS[<control>]/ST[<control>]``."""
    return f"GS[{group.get('control_number')}]/ST[{transaction.get('control_number')}]"


def _mismatch(
    path: str, trailer: str, header: str, declared: Optional[str], expected: Optional[str]
) -> Iterable[Finding]:
    """One finding when a trailer's control number was written and differs from its header's."""
    if declared is not None and declared != expected:
        yield (path, f"{trailer} is '{declared}' but {header} is '{expected}'; the trailer must repeat it.")


def _check_control_numbers_match(api: CanonicalApi) -> Iterable[Finding]:
    """Every trailer repeats its header's control number."""
    interchange = _interchange(api)
    yield from _mismatch(
        "ISA", "IEA02", "ISA13", interchange.get("trailer_control_number"), interchange.get("control_number")
    )
    for group in _groups(api):
        path = f"GS[{group.get('control_number')}]"
        yield from _mismatch(path, "GE02", "GS06", group.get("trailer_control_number"), group.get("control_number"))
        for transaction in _transactions(group):
            yield from _mismatch(
                _set_path(group, transaction),
                "SE02",
                "ST02",
                transaction.get("trailer_control_number"),
                transaction.get("control_number"),
            )


def _total(path: str, trailer: str, declared: Any, observed: Any, what: str) -> Iterable[Finding]:
    """One finding when a declared control total was written and differs from the observed count."""
    if isinstance(declared, int) and declared != observed:
        yield (path, f"{trailer} declares {declared}, but {what} number {observed}.")


def _check_control_totals_match(api: CanonicalApi) -> Iterable[Finding]:
    """Every trailer's control total is the count of what it closes."""
    interchange = _interchange(api)
    yield from _total(
        "ISA",
        "IEA01",
        interchange.get("declared_group_count"),
        interchange.get("group_count"),
        "the interchange's functional groups",
    )
    for group in _groups(api):
        path = f"GS[{group.get('control_number')}]"
        yield from _total(
            path,
            "GE01",
            group.get("declared_transaction_count"),
            group.get("transaction_count"),
            "the group's transaction sets",
        )
        for transaction in _transactions(group):
            yield from _total(
                _set_path(group, transaction),
                "SE01",
                transaction.get("declared_segment_count"),
                transaction.get("segment_count"),
                "the segments from ST to SE",
            )


def _duplicates(values: Iterable[Any]) -> List[str]:
    """The written values that occur more than once, sorted."""
    counts = Counter(value for value in values if value)
    return sorted(str(value) for value, count in counts.items() if count > 1)


def _check_control_numbers_unique(api: CanonicalApi) -> Iterable[Finding]:
    """No two groups of the interchange, and no two sets of a group, share a control number."""
    groups = _groups(api)
    for duplicate in _duplicates(group.get("control_number") for group in groups):
        yield (
            "ISA",
            f"Two functional groups share the control number '{duplicate}' (GS06); an acknowledgement "
            "cannot say which one it answers.",
        )
    for group in groups:
        for duplicate in _duplicates(item.get("control_number") for item in _transactions(group)):
            yield (
                f"GS[{group.get('control_number')}]",
                f"Two transaction sets share the control number '{duplicate}' (ST02); an "
                "acknowledgement cannot say which one it answers.",
            )


def _check_functional_id_matches_set(api: CanonicalApi) -> Iterable[Finding]:
    """``GS01`` is the functional identifier X12 assigns each transaction set the group carries."""
    for group in _groups(api):
        functional_id = (group.get("functional_id") or "").strip()
        for transaction in _transactions(group):
            expected = FUNCTIONAL_ID_FOR_SET.get((transaction.get("set_id") or "").strip())
            if expected and functional_id and functional_id != expected:
                yield (
                    _set_path(group, transaction),
                    f"Transaction set {transaction.get('set_id')} is in a group whose GS01 is "
                    f"'{functional_id}'; X12 assigns it '{expected}', and receivers route groups by it.",
                )


def _check_version_declared(api: CanonicalApi) -> Iterable[Finding]:
    """``GS08`` names the version, release and industry identifier the group follows."""
    for group in _groups(api):
        if not (group.get("version") or "").strip():
            yield (
                f"GS[{group.get('control_number')}]",
                "GS08 (version / release / industry identifier) is empty; nothing says which release "
                "of the transaction set's definition the segments follow. Set it, e.g. '005010'.",
            )


def _check_usage_indicator_valid(api: CanonicalApi) -> Iterable[Finding]:
    """``ISA15`` is one of the usage indicators X12 defines."""
    usage = (_interchange(api).get("usage_indicator") or "").strip()
    if _controls(api) and usage not in USAGE_INDICATORS:
        yield (
            "ISA.15",
            f"ISA15 (usage indicator) is '{usage}'; X12 defines 'P' (production), 'T' (test) and "
            "'I' (information).",
        )


def _check_test_interchange(api: CanonicalApi) -> Iterable[Finding]:
    """``ISA15`` = ``T`` marks the interchange as test data."""
    if (_interchange(api).get("usage_indicator") or "").strip() == "T":
        yield (
            "ISA.15",
            "ISA15 is 'T': this interchange is test data. A trading partner's production system "
            "rejects it.",
        )


class EdiX12RulePack(RulePack, register=True):
    """Native rules for EDI X12 artifacts (see the module docstring)."""

    format = "edix12"
    pack_id = "edix12"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="edix12.control-numbers-match",
            category="structure",
            severity="error",
            description="SE02, GE02 and IEA02 must repeat the control number of ST02, GS06 and ISA13.",
            check=_check_control_numbers_match,
        ),
        LintRule(
            rule_id="edix12.control-totals-match",
            category="structure",
            severity="error",
            description="SE01, GE01 and IEA01 must count the segments, transaction sets and groups they close.",
            check=_check_control_totals_match,
        ),
        LintRule(
            rule_id="edix12.control-numbers-unique",
            category="structure",
            severity="warning",
            description="Control numbers must be unique among a group's sets and an interchange's groups.",
            check=_check_control_numbers_unique,
        ),
        LintRule(
            rule_id="edix12.functional-id-matches-set",
            category="structure",
            severity="warning",
            description="GS01 should be the functional identifier X12 assigns the transaction set.",
            check=_check_functional_id_matches_set,
        ),
        LintRule(
            rule_id="edix12.version-declared",
            category="structure",
            severity="warning",
            description="GS08 must name the X12 version the group follows.",
            check=_check_version_declared,
        ),
        LintRule(
            rule_id="edix12.usage-indicator-valid",
            category="structure",
            severity="warning",
            description="ISA15 must be 'P', 'T' or 'I'.",
            check=_check_usage_indicator_valid,
        ),
        LintRule(
            rule_id="edix12.test-interchange",
            category="structure",
            severity="info",
            description="ISA15 'T' marks the interchange as test data.",
            check=_check_test_interchange,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the EDI X12 native rules in deterministic execution order."""
        return list(self._RULES)
