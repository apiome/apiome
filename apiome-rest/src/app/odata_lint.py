"""OData lint pack — MFI-11.1 (#3776), MFI-11.4 (#3779).

Native rules for OData catalog items, registered under the ``odata`` format key the OData
normalizer emits. Every rule reports what the import recorded on the catalog item
(:mod:`app.odata_validation`), so linting needs neither the source text nor a re-parse.

* **odata.csdl-schema** (warning) — the document departs from the OASIS CSDL JSON schema. An
  OData v4 document is validated on import (:mod:`app.odata_csdl_schema`), as uploaded CSDL JSON
  or after conversion from CSDL XML; the import still succeeds, and each recorded violation is
  reported here at its JSON-pointer path (``csdl:/ODataDemo/Product/ID/$Type``).
* **odata.csdl-xsd** (warning) — v4 CSDL XML departs from the OASIS EDMX / EDM XML schemas
  (:mod:`app.odata_csdl_xsd`): a misspelled or unknown attribute, a stray element, a missing
  required attribute — XML the JSON form never sees. Path ``xml:/ODataDemo/Product/ID``.
* **odata.unresolved-reference** (error, blocking) — a name the document uses resolves to
  nothing of the right kind (:mod:`app.odata_resolution`): a property, parameter or return type,
  a base type, an entity set's type, a navigation target / partner / binding, an import's
  operation, an association (v2/v3). Clients generated from the metadata cannot bind it.
* **odata.entity-key** (error, blocking) — an entity type with no key to declare or inherit, a
  redeclared inherited key, or a key property that is missing, nullable, a collection or of a
  type a key cannot have. Entities of that type cannot be addressed by key.
"""

from __future__ import annotations

from typing import Iterable, List, Tuple

from .canonical_model import CanonicalApi
from .lint_engine import LintRule, RulePack
from .odata_resolution import ISSUE_KEY, ISSUE_REFERENCE

__all__ = ["ODataRulePack"]


def _check_csdl_schema(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """One finding per OASIS CSDL schema violation recorded on import."""
    violations = api.extras.get("odata_csdl_violations") or []
    for violation in violations:
        if isinstance(violation, dict):
            yield (
                f"csdl:{violation.get('path', '')}",
                f"CSDL does not match the OASIS schema: {violation.get('message', '')}",
            )
    total = api.extras.get("odata_csdl_violation_count")
    if isinstance(total, int) and total > len(violations):
        yield ("csdl:", f"{total - len(violations)} more OASIS CSDL schema violation(s) not listed.")


def _check_csdl_xsd(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """One finding per OASIS CSDL XML schema violation recorded on import."""
    violations = api.extras.get("odata_xsd_violations") or []
    for violation in violations:
        if isinstance(violation, dict):
            yield (
                f"xml:{violation.get('path', '')}",
                f"CSDL XML does not match the OASIS schema: {violation.get('message', '')}",
            )
    total = api.extras.get("odata_xsd_violation_count")
    if isinstance(total, int) and total > len(violations):
        yield ("xml:", f"{total - len(violations)} more OASIS CSDL XML schema violation(s) not listed.")


def _resolution_findings(api: CanonicalApi, kind: str) -> Iterable[Tuple[str, str]]:
    """One finding per resolution issue of ``kind`` recorded on import.

    The issue list is capped at import; when the cap cut issues off, the overflow is reported
    once, on the reference rule (the list does not say which kind the uncounted issues were).
    """
    issues = api.extras.get("odata_resolution_issues") or []
    for issue in issues:
        if isinstance(issue, dict) and issue.get("kind") == kind:
            yield (f"csdl:{issue.get('path', '')}", str(issue.get("message", "")))
    total = api.extras.get("odata_resolution_issue_count")
    if kind == ISSUE_REFERENCE and isinstance(total, int) and total > len(issues):
        yield ("csdl:", f"{total - len(issues)} more unresolved reference or entity-key issue(s) not listed.")


def _check_unresolved_reference(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Names the document uses that resolve to nothing of the right kind."""
    return _resolution_findings(api, ISSUE_REFERENCE)


def _check_entity_key(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """Entity types without a usable key."""
    return _resolution_findings(api, ISSUE_KEY)


class ODataRulePack(RulePack, register=True):
    """Native rules for OData artifacts (see the module docstring)."""

    format = "odata"
    pack_id = "odata"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="odata.csdl-schema",
            category="structure",
            severity="warning",
            description="OData CSDL should validate against the OASIS CSDL JSON schema.",
            check=_check_csdl_schema,
        ),
        LintRule(
            rule_id="odata.csdl-xsd",
            category="structure",
            severity="warning",
            description="OData v4 CSDL XML should validate against the OASIS EDMX / EDM XML schemas.",
            check=_check_csdl_xsd,
        ),
        LintRule(
            rule_id="odata.unresolved-reference",
            category="structure",
            severity="error",
            description=(
                "Every type, entity set, partner, binding and operation an OData document names must be declared."
            ),
            check=_check_unresolved_reference,
        ),
        LintRule(
            rule_id="odata.entity-key",
            category="structure",
            severity="error",
            description="Every OData entity type must declare or inherit a key of non-nullable primitive properties.",
            check=_check_entity_key,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the OData native rules in deterministic execution order."""
        return list(self._RULES)
