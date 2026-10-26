"""OData lint pack — MFI-11.1 (#3776).

Native rules for OData catalog items, registered under the ``odata`` format key the OData
normalizer emits. MFI-11.1 contributes one rule; the fuller OData pack is MFI-11.4 (#3779).

* **odata.csdl-schema** (warning) — the document departs from the OASIS CSDL JSON schema. An
  OData v4 document is validated on import (:mod:`app.odata_csdl_schema`), as uploaded CSDL JSON
  or after conversion from CSDL XML; the import still succeeds, and each recorded violation is
  reported here at its JSON-pointer path (``csdl:/ODataDemo/Product/ID/$Type``).
"""

from __future__ import annotations

from typing import Iterable, List, Tuple

from .canonical_model import CanonicalApi
from .lint_engine import LintRule, RulePack

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
    )

    def rules(self) -> List[LintRule]:
        """Return the OData native rules in deterministic execution order."""
        return list(self._RULES)
