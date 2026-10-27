"""WS-I lint pack for WSDL — MFI-13.4 (#3791).

Native rules for WSDL catalog items, registered under the ``wsdl`` format key the WSDL normalizer
emits (both grammars), so they run with the always-on common pack. Each rule reports the WS-I
Basic Profile issues :mod:`app.wsdl_wsi` recorded on the item at import
(``extras["wsdl_wsi_issues"]``): bindings and the import graph are not in the canonical model, so
they are checked on the description as written. See that module for the profile assertions.

* **wsi.literal-use** (error) — ``use="encoded"``.
* **wsi.binding-style** (error) — a binding mixing rpc and document operations.
* **wsi.document-literal** (error) — a document-literal body with several parts, ``type`` parts or
  a ``namespace``.
* **wsi.rpc-literal** (error) — an rpc-literal body with ``element`` parts or no ``namespace``.
* **wsi.unique-operation-signature** (error) — operations a receiver cannot tell apart.
* **wsi.unresolved-import** (error) — a ``wsdl:import`` / ``xs:import`` / ``xs:include`` that
  resolves to nothing.
* **wsi.wsdl-import-target** (error) — a ``wsdl:import`` without ``location`` or of a non-WSDL document.
* **wsi.unique-soap-action** (warning) — operations of a binding sharing a ``soapAction``.

Paths are ``wsdl:/binding/<binding>/operation/<operation>/<input|output>``, ``wsdl:/import/<location>``
or ``wsdl:/schema/<targetNamespace>/import/<location>``.
"""

from __future__ import annotations

from typing import Callable, Iterable, List, Mapping, Tuple

from .canonical_model import CanonicalApi
from .lint_engine import LintRule, RulePack
from .wsdl_wsi import (
    RULE_BINDING_STYLE,
    RULE_DOCUMENT_LITERAL,
    RULE_LITERAL_USE,
    RULE_RPC_LITERAL,
    RULE_UNIQUE_OPERATION_SIGNATURE,
    RULE_UNIQUE_SOAP_ACTION,
    RULE_UNRESOLVED_IMPORT,
    RULE_WSDL_IMPORT_TARGET,
)

__all__ = ["WsiRulePack"]


def _check_for(rule_id: str, *, reports_overflow: bool = False) -> Callable[[CanonicalApi], Iterable[Tuple[str, str]]]:
    """A check that yields the recorded WS-I issues of one rule.

    Args:
        rule_id: The rule whose issues to report.
        reports_overflow: Whether this rule also reports how many issues the import's cap left
            unlisted (exactly one rule does, since the overflow is not broken down by rule).

    Returns:
        The rule's ``check`` function.
    """

    def check(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
        issues = api.extras.get("wsdl_wsi_issues") or []
        for issue in issues:
            if isinstance(issue, Mapping) and issue.get("rule") == rule_id:
                yield f"wsdl:{issue.get('path', '')}", str(issue.get("message", ""))
        total = api.extras.get("wsdl_wsi_issue_count")
        if reports_overflow and isinstance(total, int) and total > len(issues):
            yield "wsdl:", f"{total - len(issues)} more WS-I Basic Profile issue(s) not listed."

    return check


def _rule(rule_id: str, severity: str, category: str, description: str, *, overflow: bool = False) -> LintRule:
    """One WS-I rule bound to its recorded-issue check."""
    return LintRule(
        rule_id=rule_id,
        category=category,
        severity=severity,  # type: ignore[arg-type]
        description=description,
        check=_check_for(rule_id, reports_overflow=overflow),
    )


class WsiRulePack(RulePack, register=True):
    """WS-I Basic Profile rules for WSDL artifacts (see the module docstring)."""

    format = "wsdl"
    pack_id = "wsi"

    _RULES: Tuple[LintRule, ...] = (
        _rule(
            RULE_LITERAL_USE,
            "error",
            "structure",
            "WS-I: SOAP bindings must use literal, not encoded, messages.",
            overflow=True,
        ),
        _rule(
            RULE_BINDING_STYLE, "error", "structure", "WS-I: a binding must be all rpc-literal or all document-literal."
        ),
        _rule(
            RULE_DOCUMENT_LITERAL,
            "error",
            "structure",
            "WS-I: a document-literal body references at most one part, defined by element, with no namespace.",
        ),
        _rule(
            RULE_RPC_LITERAL,
            "error",
            "structure",
            "WS-I: an rpc-literal body references parts defined by type and names a namespace.",
        ),
        _rule(
            RULE_UNIQUE_OPERATION_SIGNATURE,
            "error",
            "structure",
            "WS-I: the operations of a binding must differ on the wire.",
        ),
        _rule(
            RULE_UNRESOLVED_IMPORT,
            "error",
            "structure",
            "Every wsdl:import, xs:import and xs:include must resolve within the import.",
        ),
        _rule(
            RULE_WSDL_IMPORT_TARGET,
            "error",
            "structure",
            "WS-I: wsdl:import must have a location and import only WSDL descriptions.",
        ),
        _rule(
            RULE_UNIQUE_SOAP_ACTION,
            "warning",
            "naming",
            "The operations of a binding should have distinct soapAction values.",
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the WS-I rules in deterministic execution order."""
        return list(self._RULES)
