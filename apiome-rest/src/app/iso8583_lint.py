"""ISO 8583 lint pack — MFI-20.6 (#3990).

Native, deterministic quality rules for ISO 8583 field-map documents, layered on the canonical
lint engine (MFI-4.1 :mod:`app.lint_engine`) the way the Thrift pack (:mod:`app.thrift_lint`) is.
The :class:`Iso8583RulePack` is registered under the ``iso8583`` format key, so it runs with the
always-on common pack on every ISO 8583 artifact. The rules read only the canonical model
:mod:`app.iso8583_normalizer` builds — the decoded MTI and the data elements' numbers, types and
lengths in ``extras``:

* **iso8583.mti-known** (warning) — a digit of the MTI is one the standard reserves (class
  ``0`` / ``9``, function ``8`` / ``9``, an unknown version or origin): no counterparty can route it.
* **iso8583.de-number-valid** (error) — a data element number outside 2–128 (1 is the secondary
  bitmap, 65 is the tertiary bitmap flag): the bitmap has no bit for it.
* **iso8583.de-type-known** (warning) — a data element type that is not one of the standard's
  codes (``n``, ``an``, ``ans``, ``b``, ``z``, ``x+n`` …).
* **iso8583.de-length-declared** (warning) — a data element without a length: fixed-length
  elements cannot be cut from the wire, variable ones have no maximum.
* **iso8583.stan-present** (warning) — no DE 11 (System Trace Audit Number): a response cannot be
  matched to its request.
* **iso8583.response-code-on-response** (warning) — a response or acknowledgement (MTI function
  ``1`` / ``3`` / ``5`` / ``7``) without DE 39 (Response Code): the outcome is not stated.
* **iso8583.transmission-datetime-present** (info) — no DE 7 (Transmission Date and Time).
"""

from __future__ import annotations

from typing import Any, Iterable, List, Mapping, Tuple

from .canonical_model import CanonicalApi
from .iso8583_message_type import (
    DATA_ELEMENT_RANGE,
    KNOWN_TYPE_CODES,
    MTI_CLASSES,
    MTI_FUNCTIONS,
    MTI_ORIGINS,
    MTI_VERSIONS,
    is_response_function,
)
from .lint_engine import LintRule, RulePack

__all__ = ["Iso8583RulePack"]


def _elements(api: CanonicalApi) -> List[Mapping[str, Any]]:
    """The data elements the model records, sorted by number."""
    listed = api.extras.get("iso8583_data_elements")
    elements = [e for e in listed if isinstance(e, Mapping)] if isinstance(listed, list) else []
    def order(element: Mapping[str, Any]) -> Tuple[int, str]:
        number = str(element.get("number", ""))
        return (int(number) if number.isdigit() else 10**6, number)

    return sorted(elements, key=order)


def _numbers(api: CanonicalApi) -> set:
    return {str(e.get("number")) for e in _elements(api)}


def _decoded(api: CanonicalApi) -> Mapping[str, Any]:
    decoded = api.extras.get("iso8583_mti_decoded")
    return decoded if isinstance(decoded, Mapping) else {}


def _check_mti_known(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Every MTI digit must be one the standard assigns."""
    mti = api.extras.get("iso8583_mti")
    decoded = _decoded(api)
    if not isinstance(mti, str) or not decoded:
        return
    for position, table, label in (
        ("version", MTI_VERSIONS, "version"),
        ("class", MTI_CLASSES, "class"),
        ("function", MTI_FUNCTIONS, "function"),
        ("origin", MTI_ORIGINS, "origin"),
    ):
        digit = decoded.get(position)
        if digit is None or digit not in table:
            yield (
                "mti",
                f"MTI '{mti}' has a reserved or unknown {label} digit ('{digit}'); no counterparty "
                "can route the message. Use the digits ISO 8583 assigns.",
            )


def _check_de_number_valid(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Every data element number must be in 2–128."""
    for element in _elements(api):
        number = str(element.get("number"))
        if not number.isdigit() or int(number) not in DATA_ELEMENT_RANGE:
            yield (
                f"dataElements.{number}",
                f"Data element '{number}' is outside 2–128; the bitmap has no bit for it "
                "(1 is the secondary bitmap).",
            )


def _check_de_type_known(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Every data element type should be one of the standard's codes."""
    for element in _elements(api):
        type_code = str(element.get("type") or "").strip().lower()
        if type_code and type_code not in KNOWN_TYPE_CODES:
            yield (
                f"dataElements.{element.get('number')}",
                f"Data element {element.get('number')} has type '{type_code}', which is not an ISO 8583 "
                "type code (n, an, ans, as, ns, a, s, b, z, x+n).",
            )


def _check_de_length_declared(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Every data element should declare its length (fixed, ..LL or ...LLL)."""
    for element in _elements(api):
        if element.get("length") in (None, ""):
            yield (
                f"dataElements.{element.get('number')}",
                f"Data element {element.get('number')} declares no length; a fixed-length element "
                "cannot be cut from the wire and a variable one has no maximum. Give it '6', '..19' "
                "or '...999'.",
            )


def _check_stan_present(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """DE 11 (System Trace Audit Number) should be present."""
    if _elements(api) and "11" not in _numbers(api):
        yield (
            "dataElements.11",
            "No DE 11 (System Trace Audit Number); a response cannot be matched to its request.",
        )


def _check_response_code_on_response(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """A response or acknowledgement should carry DE 39 (Response Code)."""
    if is_response_function(_decoded(api).get("function")) and "39" not in _numbers(api):
        yield (
            "dataElements.39",
            f"MTI '{api.extras.get('iso8583_mti')}' is a response, but DE 39 (Response Code) is "
            "absent; the outcome is not stated.",
        )


def _check_transmission_datetime_present(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """DE 7 (Transmission Date and Time) should be present."""
    if _elements(api) and "7" not in _numbers(api):
        yield ("dataElements.7", "No DE 7 (Transmission Date and Time); the message cannot be aged.")


class Iso8583RulePack(RulePack, register=True):
    """Native rules for ISO 8583 artifacts (see the module docstring)."""

    format = "iso8583"
    pack_id = "iso8583"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="iso8583.mti-known",
            category="structure",
            severity="warning",
            description="Every MTI digit must be one the standard assigns.",
            check=_check_mti_known,
        ),
        LintRule(
            rule_id="iso8583.de-number-valid",
            category="structure",
            severity="error",
            description="Every data element number must be in 2–128.",
            check=_check_de_number_valid,
        ),
        LintRule(
            rule_id="iso8583.de-type-known",
            category="structure",
            severity="warning",
            description="Every data element type should be an ISO 8583 type code.",
            check=_check_de_type_known,
        ),
        LintRule(
            rule_id="iso8583.de-length-declared",
            category="structure",
            severity="warning",
            description="Every data element should declare its length.",
            check=_check_de_length_declared,
        ),
        LintRule(
            rule_id="iso8583.stan-present",
            category="structure",
            severity="warning",
            description="DE 11 (System Trace Audit Number) should be present.",
            check=_check_stan_present,
        ),
        LintRule(
            rule_id="iso8583.response-code-on-response",
            category="structure",
            severity="warning",
            description="A response or acknowledgement should carry DE 39 (Response Code).",
            check=_check_response_code_on_response,
        ),
        LintRule(
            rule_id="iso8583.transmission-datetime-present",
            category="structure",
            severity="info",
            description="DE 7 (Transmission Date and Time) should be present.",
            check=_check_transmission_datetime_present,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the ISO 8583 native rules in deterministic execution order."""
        return list(self._RULES)
